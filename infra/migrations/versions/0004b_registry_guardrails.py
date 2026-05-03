"""registry_guardrails

Revision ID: 0004b
Revises: 0004
Create Date: 2026-05-03

Hardens the registry layer before accounting/trading/risk migrations start
referencing it. Closes intra-registry consistency gaps that would be
materially harder to fix after cross-schema FKs lock in.

Per reviewer hard review 2026-05-03.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0004b"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ===== 1. Composite FK ensuring model_deployments.strategy_id matches model.strategy_id =====
    # Add unique index on (id, strategy_id) so the composite FK has a valid target
    op.execute("""
        CREATE UNIQUE INDEX models_id_strategy_unique
            ON registry.models(id, strategy_id);
    """)

    # Drop the existing single-column FK on model_id and add composite FK
    # First find the FK name (alembic-generated; safe to drop by spec)
    op.execute("""
        ALTER TABLE registry.model_deployments
        DROP CONSTRAINT model_deployments_model_id_fkey;
    """)

    op.execute("""
        ALTER TABLE registry.model_deployments
        ADD CONSTRAINT fk_model_deployment_model_strategy
        FOREIGN KEY (model_id, strategy_id) REFERENCES registry.models(id, strategy_id);
    """)

    # ===== 2. Add deployment_slot for ensemble members =====
    op.execute("""
        ALTER TABLE registry.model_deployments
        ADD COLUMN deployment_slot TEXT NOT NULL DEFAULT 'default';
    """)

    # Drop old exclusion constraint and add new one with deployment_slot
    op.execute("""
        ALTER TABLE registry.model_deployments
        DROP CONSTRAINT no_overlapping_strategy_model_deployments;
    """)

    op.execute("""
        ALTER TABLE registry.model_deployments
        ADD CONSTRAINT no_overlapping_strategy_model_deployments
        EXCLUDE USING gist (
            strategy_id WITH =,
            environment WITH =,
            deployment_role WITH =,
            deployment_slot WITH =,
            tstzrange(deployed_at, COALESCE(retired_at, 'infinity'::timestamptz), '[)') WITH &&
        );
    """)

    # ===== 3. Remove input_signal_batch_ids from allocator_runs =====
    # Bridge table allocator_run_signal_batches is sole source of truth
    op.execute("""
        ALTER TABLE registry.allocator_runs
        DROP COLUMN input_signal_batch_ids;
    """)

    # ===== 4. Strategy phase consistency: promotions are authoritative =====
    # Trigger maintains strategies.current_phase from active promotions
    op.execute("""
        CREATE OR REPLACE FUNCTION registry.sync_strategy_phase_from_promotion() RETURNS TRIGGER AS $$
        DECLARE
            target_phase TEXT;
            target_phase_at TIMESTAMPTZ;
        BEGIN
            -- For both INSERT and UPDATE (revocation), recompute strategy phase from active promotion
            -- Active = revoked_at IS NULL

            -- Get the strategy_id whose phase needs recomputation
            -- TG_OP could be INSERT, UPDATE, DELETE
            DECLARE strategy_to_update BIGINT;
            BEGIN
                IF TG_OP = 'INSERT' THEN
                    strategy_to_update := NEW.strategy_id;
                ELSIF TG_OP = 'UPDATE' THEN
                    strategy_to_update := NEW.strategy_id;
                ELSE  -- DELETE (not expected, but handle defensively)
                    strategy_to_update := OLD.strategy_id;
                END IF;

                -- Find the most recent active promotion for this strategy
                SELECT to_phase, promoted_at
                INTO target_phase, target_phase_at
                FROM registry.promotions
                WHERE strategy_id = strategy_to_update
                  AND revoked_at IS NULL
                ORDER BY promoted_at DESC
                LIMIT 1;

                IF target_phase IS NOT NULL THEN
                    UPDATE registry.strategies
                    SET current_phase = target_phase,
                        phase_entered_at = target_phase_at
                    WHERE id = strategy_to_update;
                END IF;
                -- If no active promotion exists, leave strategy phase unchanged
                -- (revoking the last promotion does not auto-demote; operator decides)
            END;

            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            ELSE
                RETURN NEW;
            END IF;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER promotions_sync_strategy_phase
            AFTER INSERT OR UPDATE OF revoked_at ON registry.promotions
            FOR EACH ROW
            EXECUTE FUNCTION registry.sync_strategy_phase_from_promotion();
    """)

    # ===== 5. Models immutability trigger =====
    # After insert, only retired_at and retirement_reason may change
    op.execute("""
        CREATE OR REPLACE FUNCTION registry.enforce_model_immutability() RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.strategy_id IS DISTINCT FROM OLD.strategy_id THEN
                RAISE EXCEPTION 'models.strategy_id is immutable';
            END IF;
            IF NEW.version_id IS DISTINCT FROM OLD.version_id THEN
                RAISE EXCEPTION 'models.version_id is immutable';
            END IF;
            IF NEW.model_class IS DISTINCT FROM OLD.model_class THEN
                RAISE EXCEPTION 'models.model_class is immutable';
            END IF;
            IF NEW.training_data_hash IS DISTINCT FROM OLD.training_data_hash THEN
                RAISE EXCEPTION 'models.training_data_hash is immutable';
            END IF;
            IF NEW.feature_set_hash IS DISTINCT FROM OLD.feature_set_hash THEN
                RAISE EXCEPTION 'models.feature_set_hash is immutable';
            END IF;
            IF NEW.label_set_hash IS DISTINCT FROM OLD.label_set_hash THEN
                RAISE EXCEPTION 'models.label_set_hash is immutable';
            END IF;
            IF NEW.hyperparam_hash IS DISTINCT FROM OLD.hyperparam_hash THEN
                RAISE EXCEPTION 'models.hyperparam_hash is immutable';
            END IF;
            IF NEW.artifact_path IS DISTINCT FROM OLD.artifact_path THEN
                RAISE EXCEPTION 'models.artifact_path is immutable';
            END IF;
            IF NEW.artifact_hash IS DISTINCT FROM OLD.artifact_hash THEN
                RAISE EXCEPTION 'models.artifact_hash is immutable';
            END IF;
            IF NEW.trained_at IS DISTINCT FROM OLD.trained_at THEN
                RAISE EXCEPTION 'models.trained_at is immutable';
            END IF;
            -- Allowed to change: retired_at, retirement_reason, validation_report_path
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER models_immutability
            BEFORE UPDATE ON registry.models
            FOR EACH ROW
            EXECUTE FUNCTION registry.enforce_model_immutability();
    """)

    # ===== 6. Features immutability trigger =====
    op.execute("""
        CREATE OR REPLACE FUNCTION registry.enforce_feature_immutability() RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.feature_name IS DISTINCT FROM OLD.feature_name THEN
                RAISE EXCEPTION 'features.feature_name is immutable';
            END IF;
            IF NEW.version IS DISTINCT FROM OLD.version THEN
                RAISE EXCEPTION 'features.version is immutable';
            END IF;
            IF NEW.definition IS DISTINCT FROM OLD.definition THEN
                RAISE EXCEPTION 'features.definition is immutable';
            END IF;
            IF NEW.computation_script_path IS DISTINCT FROM OLD.computation_script_path THEN
                RAISE EXCEPTION 'features.computation_script_path is immutable';
            END IF;
            IF NEW.data_sources IS DISTINCT FROM OLD.data_sources THEN
                RAISE EXCEPTION 'features.data_sources is immutable';
            END IF;
            IF NEW.refresh_cadence IS DISTINCT FROM OLD.refresh_cadence THEN
                RAISE EXCEPTION 'features.refresh_cadence is immutable';
            END IF;
            IF NEW.expected_range IS DISTINCT FROM OLD.expected_range THEN
                RAISE EXCEPTION 'features.expected_range is immutable';
            END IF;
            -- Allowed to change: parity_test_passing, parity_last_tested_at, deprecated, updated_at
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER features_immutability
            BEFORE UPDATE ON registry.features
            FOR EACH ROW
            EXECUTE FUNCTION registry.enforce_feature_immutability();
    """)

    # ===== 7. Current-state views =====

    op.execute("""
        CREATE OR REPLACE VIEW registry.active_promotions AS
        SELECT
            p.id,
            p.strategy_id,
            s.name AS strategy_name,
            p.from_phase,
            p.to_phase,
            p.operator_id,
            p.signature_method,
            p.gate_evidence_doc_path,
            p.promoted_at
        FROM registry.promotions p
        JOIN registry.strategies s ON s.id = p.strategy_id
        WHERE p.revoked_at IS NULL;
    """)

    op.execute("""
        COMMENT ON VIEW registry.active_promotions IS
            'Active (un-revoked) promotion per strategy. Source of truth for OMS require_strategy_promoted check. Each strategy has at most one row (enforced by partial unique index on promotions).';
    """)

    op.execute("""
        CREATE OR REPLACE VIEW registry.active_model_deployments AS
        SELECT
            md.id,
            md.model_id,
            md.strategy_id,
            s.name AS strategy_name,
            m.version_id AS model_version,
            md.environment,
            md.deployment_role,
            md.deployment_slot,
            md.deployed_at,
            md.deployed_by
        FROM registry.model_deployments md
        JOIN registry.models m ON m.id = md.model_id
        JOIN registry.strategies s ON s.id = md.strategy_id
        WHERE md.retired_at IS NULL;
    """)

    op.execute("""
        COMMENT ON VIEW registry.active_model_deployments IS
            'Active model deployments. One row per (strategy, environment, deployment_role, deployment_slot) is currently deployed. Use this to determine which model is in production for a strategy.';
    """)

    op.execute("""
        CREATE OR REPLACE VIEW registry.current_instrument_specs AS
        SELECT DISTINCT ON (instrument_id)
            isp.instrument_id,
            i.instrument_code,
            isp.tick_size,
            isp.lot_size,
            isp.min_notional,
            isp.contract_size,
            isp.price_precision,
            isp.quantity_precision,
            isp.margin_mode,
            isp.effective_from,
            isp.source
        FROM registry.instrument_specs_history isp
        JOIN registry.instruments i ON i.id = isp.instrument_id
        WHERE isp.effective_from <= NOW()
          AND (isp.effective_to IS NULL OR isp.effective_to > NOW())
        ORDER BY instrument_id, effective_from DESC;
    """)

    op.execute("""
        COMMENT ON VIEW registry.current_instrument_specs IS
            'Current instrument specs (as of NOW). For historical lookups, query instrument_specs_history directly with WHERE effective_from <= T AND (effective_to IS NULL OR effective_to > T).';
    """)

    op.execute("""
        CREATE OR REPLACE VIEW registry.current_fee_schedules AS
        SELECT
            fs.id,
            fs.venue_id,
            fs.account_id,
            fs.instrument_id,
            fs.instrument_type,
            fs.maker_fee_bps,
            fs.taker_fee_bps,
            fs.effective_from,
            fs.source,
            -- Precedence rank: lower number = higher specificity
            CASE
                WHEN fs.account_id IS NOT NULL AND fs.instrument_id IS NOT NULL THEN 1
                WHEN fs.account_id IS NOT NULL AND fs.instrument_type IS NOT NULL THEN 2
                WHEN fs.instrument_id IS NOT NULL THEN 3
                WHEN fs.instrument_type IS NOT NULL THEN 4
                ELSE 5
            END AS precedence_rank
        FROM registry.fee_schedules fs
        WHERE fs.effective_from <= NOW()
          AND (fs.effective_to IS NULL OR fs.effective_to > NOW());
    """)

    op.execute("""
        COMMENT ON VIEW registry.current_fee_schedules IS
            'Current fee schedules with precedence_rank. Cost model selects the lowest precedence_rank for a given (venue, account, instrument) lookup.';
    """)

    op.execute("""
        CREATE OR REPLACE VIEW registry.active_venue_capabilities AS
        SELECT
            vc.id,
            vc.venue_id,
            v.venue_code,
            vc.max_client_order_id_len,
            vc.supports_post_only,
            vc.supports_reduce_only,
            vc.supports_gtc,
            vc.supports_ioc,
            vc.supports_fok,
            vc.supports_gtd,
            vc.supports_batch_orders,
            vc.supports_order_amend,
            vc.supports_client_order_id_lookup,
            vc.min_notional_usd,
            vc.max_orders_per_second,
            vc.self_trade_prevention,
            vc.effective_from
        FROM registry.venue_capabilities vc
        JOIN registry.venues v ON v.id = vc.venue_id
        WHERE vc.effective_from <= NOW()
          AND (vc.effective_to IS NULL OR vc.effective_to > NOW());
    """)

    op.execute("""
        COMMENT ON VIEW registry.active_venue_capabilities IS
            'Active venue capabilities. OMS pre-submit checks query this view for current feature support. For historical decisions, query venue_capabilities directly with effective ranges.';
    """)


def downgrade() -> None:
    # Drop in reverse order
    op.execute("DROP VIEW IF EXISTS registry.active_venue_capabilities;")
    op.execute("DROP VIEW IF EXISTS registry.current_fee_schedules;")
    op.execute("DROP VIEW IF EXISTS registry.current_instrument_specs;")
    op.execute("DROP VIEW IF EXISTS registry.active_model_deployments;")
    op.execute("DROP VIEW IF EXISTS registry.active_promotions;")

    op.execute("DROP TRIGGER IF EXISTS features_immutability ON registry.features;")
    op.execute("DROP FUNCTION IF EXISTS registry.enforce_feature_immutability();")

    op.execute("DROP TRIGGER IF EXISTS models_immutability ON registry.models;")
    op.execute("DROP FUNCTION IF EXISTS registry.enforce_model_immutability();")

    op.execute("DROP TRIGGER IF EXISTS promotions_sync_strategy_phase ON registry.promotions;")
    op.execute("DROP FUNCTION IF EXISTS registry.sync_strategy_phase_from_promotion();")

    # Restore allocator_runs.input_signal_batch_ids (downgrade reverses removal)
    op.execute("""
        ALTER TABLE registry.allocator_runs
        ADD COLUMN input_signal_batch_ids JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(input_signal_batch_ids) = 'array');
    """)

    # Restore old model_deployments exclusion constraint (without deployment_slot)
    op.execute("""
        ALTER TABLE registry.model_deployments
        DROP CONSTRAINT no_overlapping_strategy_model_deployments;
    """)
    op.execute("""
        ALTER TABLE registry.model_deployments
        ADD CONSTRAINT no_overlapping_strategy_model_deployments
        EXCLUDE USING gist (
            strategy_id WITH =,
            environment WITH =,
            deployment_role WITH =,
            tstzrange(deployed_at, COALESCE(retired_at, 'infinity'::timestamptz), '[)') WITH &&
        );
    """)
    op.execute("ALTER TABLE registry.model_deployments DROP COLUMN deployment_slot;")

    # Restore old single-column FK on model_id
    op.execute("""
        ALTER TABLE registry.model_deployments
        DROP CONSTRAINT fk_model_deployment_model_strategy;
    """)
    op.execute("""
        ALTER TABLE registry.model_deployments
        ADD CONSTRAINT model_deployments_model_id_fkey
        FOREIGN KEY (model_id) REFERENCES registry.models(id);
    """)
    op.execute("DROP INDEX IF EXISTS registry.models_id_strategy_unique;")
