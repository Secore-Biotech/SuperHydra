"""registry_guardrails_followup

Revision ID: 0004c
Revises: 0005
Create Date: 2026-05-03

Audit hardening for registry lifecycle records (v3).

Per reviewer rounds 1-3:
  Registry lifecycle events (promotions, models, model_deployments, features)
  are governance audit records. The audit trail principle:
    INSERT active.
    UPDATE only lifecycle metadata (revocation, retirement).
    Retirement/revocation is irreversible once set.
    DELETE forbidden.

19 patches.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0004c"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # =====================================================================
    # PATCHES 18+19: Add retirement metadata columns
    # =====================================================================
    op.execute("ALTER TABLE registry.models ADD COLUMN retired_by TEXT;")
    op.execute("""
        ALTER TABLE registry.model_deployments ADD COLUMN retired_by TEXT;
        ALTER TABLE registry.model_deployments ADD COLUMN retirement_reason TEXT;
    """)

    # =====================================================================
    # PATCHES 3+5: Retirement metadata all-or-nothing
    # =====================================================================
    op.execute("""
        ALTER TABLE registry.models
        ADD CONSTRAINT models_retirement_all_or_nothing
        CHECK (
            (retired_at IS NULL AND retired_by IS NULL AND retirement_reason IS NULL)
            OR
            (retired_at IS NOT NULL
             AND retired_by IS NOT NULL AND LENGTH(TRIM(retired_by)) > 0
             AND retirement_reason IS NOT NULL AND LENGTH(TRIM(retirement_reason)) > 0)
        );
    """)
    op.execute("""
        ALTER TABLE registry.model_deployments
        ADD CONSTRAINT model_deployments_retirement_all_or_nothing
        CHECK (
            (retired_at IS NULL AND retired_by IS NULL AND retirement_reason IS NULL)
            OR
            (retired_at IS NOT NULL
             AND retired_by IS NOT NULL AND LENGTH(TRIM(retired_by)) > 0
             AND retirement_reason IS NOT NULL AND LENGTH(TRIM(retirement_reason)) > 0)
        );
    """)

    # =====================================================================
    # PATCH 2: Replace sync function (lock strategy row + 'paused' fallback)
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION registry.sync_strategy_phase_from_promotion()
        RETURNS TRIGGER AS $$
        DECLARE
            target_phase TEXT;
            target_phase_at TIMESTAMPTZ;
            strategy_to_update BIGINT;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                strategy_to_update := NEW.strategy_id;
            ELSIF TG_OP = 'UPDATE' THEN
                strategy_to_update := NEW.strategy_id;
            ELSE
                strategy_to_update := OLD.strategy_id;
            END IF;

            PERFORM 1 FROM registry.strategies WHERE id = strategy_to_update FOR UPDATE;

            SELECT to_phase, promoted_at
            INTO target_phase, target_phase_at
            FROM registry.promotions
            WHERE strategy_id = strategy_to_update AND revoked_at IS NULL
            ORDER BY promoted_at DESC LIMIT 1;

            IF target_phase IS NULL THEN
                target_phase := 'paused';
                target_phase_at := NOW();
            END IF;

            PERFORM set_config('superhydra.allow_strategy_phase_sync', 'on', true);

            BEGIN
                UPDATE registry.strategies
                SET current_phase = target_phase, phase_entered_at = target_phase_at
                WHERE id = strategy_to_update;
            EXCEPTION WHEN OTHERS THEN
                PERFORM set_config('superhydra.allow_strategy_phase_sync', 'off', true);
                RAISE;
            END;

            PERFORM set_config('superhydra.allow_strategy_phase_sync', 'off', true);

            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            ELSE
                RETURN NEW;
            END IF;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # =====================================================================
    # PATCH 1: Strategy phase cache guard
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION registry.enforce_strategy_phase_cache_update()
        RETURNS TRIGGER AS $$
        DECLARE
            v_phase_changed BOOLEAN;
            v_sync_flag TEXT;
        BEGIN
            v_phase_changed := (
                NEW.current_phase IS DISTINCT FROM OLD.current_phase
                OR NEW.phase_entered_at IS DISTINCT FROM OLD.phase_entered_at
            );
            IF v_phase_changed THEN
                v_sync_flag := current_setting('superhydra.allow_strategy_phase_sync', true);
                IF v_sync_flag IS DISTINCT FROM 'on' THEN
                    RAISE EXCEPTION
                        'Direct modification of strategies.current_phase or phase_entered_at on strategy % is forbidden; promotions are authoritative',
                        OLD.id;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER strategies_phase_cache_guard
            BEFORE UPDATE ON registry.strategies
            FOR EACH ROW EXECUTE FUNCTION registry.enforce_strategy_phase_cache_update();
    """)

    # =====================================================================
    # PATCH 4: Model retirement irreversible
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION registry.enforce_model_retirement_irreversibility()
        RETURNS TRIGGER AS $$
        BEGIN
            IF OLD.retired_at IS NOT NULL THEN
                IF NEW.retired_at IS DISTINCT FROM OLD.retired_at
                   OR NEW.retired_by IS DISTINCT FROM OLD.retired_by
                   OR NEW.retirement_reason IS DISTINCT FROM OLD.retirement_reason
                THEN
                    RAISE EXCEPTION
                        'Model % is already retired; retirement metadata is immutable', OLD.id;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER models_retirement_irreversible
            BEFORE UPDATE ON registry.models
            FOR EACH ROW EXECUTE FUNCTION registry.enforce_model_retirement_irreversibility();
    """)

    # =====================================================================
    # PATCH 6: Deployment retirement irreversible
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION registry.enforce_deployment_retirement_irreversibility()
        RETURNS TRIGGER AS $$
        BEGIN
            IF OLD.retired_at IS NOT NULL THEN
                IF NEW.retired_at IS DISTINCT FROM OLD.retired_at
                   OR NEW.retired_by IS DISTINCT FROM OLD.retired_by
                   OR NEW.retirement_reason IS DISTINCT FROM OLD.retirement_reason
                THEN
                    RAISE EXCEPTION
                        'Model deployment % is already retired; retirement metadata is immutable', OLD.id;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER model_deployments_retirement_irreversible
            BEFORE UPDATE ON registry.model_deployments
            FOR EACH ROW EXECUTE FUNCTION registry.enforce_deployment_retirement_irreversibility();
    """)

    # =====================================================================
    # PATCH 7: Retired model cannot receive new active deployments
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION registry.enforce_no_deploy_retired_model()
        RETURNS TRIGGER AS $$
        DECLARE
            v_model_retired_at TIMESTAMPTZ;
        BEGIN
            IF NEW.retired_at IS NOT NULL THEN
                RETURN NEW;
            END IF;

            SELECT retired_at INTO v_model_retired_at
            FROM registry.models WHERE id = NEW.model_id FOR UPDATE;

            IF v_model_retired_at IS NOT NULL THEN
                RAISE EXCEPTION
                    'Cannot create or activate deployment for model %: model is retired (retired_at=%)',
                    NEW.model_id, v_model_retired_at;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER model_deployments_no_deploy_retired_insert
            BEFORE INSERT ON registry.model_deployments
            FOR EACH ROW EXECUTE FUNCTION registry.enforce_no_deploy_retired_model();
        CREATE TRIGGER model_deployments_no_deploy_retired_update
            BEFORE UPDATE ON registry.model_deployments
            FOR EACH ROW EXECUTE FUNCTION registry.enforce_no_deploy_retired_model();
    """)

    # =====================================================================
    # PATCH 8: Cannot retire model with active deployments
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION registry.enforce_no_retire_with_active_deployments()
        RETURNS TRIGGER AS $$
        DECLARE
            v_active_deployment_count INT;
        BEGIN
            IF OLD.retired_at IS NOT NULL OR NEW.retired_at IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT COUNT(*) INTO v_active_deployment_count
            FROM registry.model_deployments
            WHERE model_id = OLD.id AND retired_at IS NULL;

            IF v_active_deployment_count > 0 THEN
                RAISE EXCEPTION
                    'Cannot retire model % while % active deployment(s) exist; retire deployments first',
                    OLD.id, v_active_deployment_count;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER models_no_retire_with_active_deployments
            BEFORE UPDATE ON registry.models
            FOR EACH ROW EXECUTE FUNCTION registry.enforce_no_retire_with_active_deployments();
    """)

    # =====================================================================
    # PATCHES 9+10: Promotion event immutability + insert-active-only
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION registry.enforce_promotion_event_immutability()
        RETURNS TRIGGER AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.revoked_at IS NOT NULL
                   OR NEW.revoked_by IS NOT NULL
                   OR NEW.revocation_signature IS NOT NULL
                   OR NEW.revocation_signature_method IS NOT NULL
                   OR NEW.revocation_reason IS NOT NULL
                THEN
                    RAISE EXCEPTION
                        'Promotion events must be inserted active; revoke via UPDATE with revocation metadata';
                END IF;
                RETURN NEW;
            END IF;

            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.strategy_id IS DISTINCT FROM OLD.strategy_id
               OR NEW.from_phase IS DISTINCT FROM OLD.from_phase
               OR NEW.to_phase IS DISTINCT FROM OLD.to_phase
               OR NEW.operator_id IS DISTINCT FROM OLD.operator_id
               OR NEW.operator_signature IS DISTINCT FROM OLD.operator_signature
               OR NEW.signature_method IS DISTINCT FROM OLD.signature_method
               OR NEW.gate_evidence_doc_path IS DISTINCT FROM OLD.gate_evidence_doc_path
               OR NEW.promoted_at IS DISTINCT FROM OLD.promoted_at
               OR NEW.created_at IS DISTINCT FROM OLD.created_at
            THEN
                RAISE EXCEPTION
                    'Promotion event % is immutable; only revocation metadata may change',
                    OLD.id;
            END IF;

            IF OLD.revoked_at IS NOT NULL THEN
                IF NEW.revoked_at IS DISTINCT FROM OLD.revoked_at
                   OR NEW.revoked_by IS DISTINCT FROM OLD.revoked_by
                   OR NEW.revocation_signature IS DISTINCT FROM OLD.revocation_signature
                   OR NEW.revocation_signature_method IS DISTINCT FROM OLD.revocation_signature_method
                   OR NEW.revocation_reason IS DISTINCT FROM OLD.revocation_reason
                THEN
                    RAISE EXCEPTION
                        'Promotion event % is already revoked; revocation metadata is immutable',
                        OLD.id;
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER promotions_event_immutability
            BEFORE INSERT OR UPDATE ON registry.promotions
            FOR EACH ROW EXECUTE FUNCTION registry.enforce_promotion_event_immutability();
    """)

    # =====================================================================
    # PATCH 11: Model deployment identity immutability
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION registry.enforce_deployment_identity_immutability()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.model_id IS DISTINCT FROM OLD.model_id
               OR NEW.strategy_id IS DISTINCT FROM OLD.strategy_id
               OR NEW.environment IS DISTINCT FROM OLD.environment
               OR NEW.deployment_role IS DISTINCT FROM OLD.deployment_role
               OR NEW.deployment_slot IS DISTINCT FROM OLD.deployment_slot
               OR NEW.deployed_at IS DISTINCT FROM OLD.deployed_at
               OR NEW.deployed_by IS DISTINCT FROM OLD.deployed_by
               OR NEW.created_at IS DISTINCT FROM OLD.created_at
            THEN
                RAISE EXCEPTION
                    'Model deployment % identity fields are immutable; only retirement metadata may change',
                    OLD.id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER model_deployments_identity_immutability
            BEFORE UPDATE ON registry.model_deployments
            FOR EACH ROW EXECUTE FUNCTION registry.enforce_deployment_identity_immutability();
    """)

    # =====================================================================
    # PATCH 12: Models must be inserted active
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION registry.enforce_model_insert_active()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.retired_at IS NOT NULL
               OR NEW.retired_by IS NOT NULL
               OR NEW.retirement_reason IS NOT NULL
            THEN
                RAISE EXCEPTION
                    'Models must be inserted active; retire via UPDATE with retirement metadata';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER models_insert_active
            BEFORE INSERT ON registry.models
            FOR EACH ROW EXECUTE FUNCTION registry.enforce_model_insert_active();
    """)

    # =====================================================================
    # PATCH 13: Deployments must be inserted active
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION registry.enforce_deployment_insert_active()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.retired_at IS NOT NULL
               OR NEW.retired_by IS NOT NULL
               OR NEW.retirement_reason IS NOT NULL
            THEN
                RAISE EXCEPTION
                    'Model deployments must be inserted active; retire via UPDATE with retirement metadata';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER model_deployments_insert_active
            BEFORE INSERT ON registry.model_deployments
            FOR EACH ROW EXECUTE FUNCTION registry.enforce_deployment_insert_active();
    """)

    # =====================================================================
    # PATCHES 14-17: DELETE protection on audit records
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION registry.prevent_registry_audit_delete()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION
                'DELETE forbidden on %.%: registry lifecycle/audit records are append-only',
                TG_TABLE_SCHEMA, TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER promotions_no_delete
            BEFORE DELETE ON registry.promotions
            FOR EACH ROW EXECUTE FUNCTION registry.prevent_registry_audit_delete();
        CREATE TRIGGER models_no_delete
            BEFORE DELETE ON registry.models
            FOR EACH ROW EXECUTE FUNCTION registry.prevent_registry_audit_delete();
        CREATE TRIGGER model_deployments_no_delete
            BEFORE DELETE ON registry.model_deployments
            FOR EACH ROW EXECUTE FUNCTION registry.prevent_registry_audit_delete();
        CREATE TRIGGER features_no_delete
            BEFORE DELETE ON registry.features
            FOR EACH ROW EXECUTE FUNCTION registry.prevent_registry_audit_delete();
    """)

    # =====================================================================
    # Verification block
    # =====================================================================
    op.execute("""
        DO $$
        DECLARE
            expected_functions TEXT[] := ARRAY[
                'enforce_strategy_phase_cache_update',
                'enforce_no_deploy_retired_model',
                'enforce_no_retire_with_active_deployments',
                'enforce_model_retirement_irreversibility',
                'enforce_deployment_retirement_irreversibility',
                'enforce_promotion_event_immutability',
                'enforce_deployment_identity_immutability',
                'enforce_model_insert_active',
                'enforce_deployment_insert_active',
                'prevent_registry_audit_delete'
            ];
            f TEXT;
            actual_count INT;
            col_count INT;
        BEGIN
            FOREACH f IN ARRAY expected_functions LOOP
                SELECT COUNT(*) INTO actual_count
                FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'registry' AND p.proname = f;
                IF actual_count < 1 THEN
                    RAISE EXCEPTION 'registry.%() not created', f;
                END IF;
            END LOOP;

            SELECT COUNT(*) INTO col_count
            FROM information_schema.columns
            WHERE table_schema = 'registry'
              AND ((table_name = 'models' AND column_name = 'retired_by')
                   OR (table_name = 'model_deployments' AND column_name IN ('retired_by', 'retirement_reason')));
            IF col_count != 3 THEN
                RAISE EXCEPTION 'Expected 3 retirement columns added, found %', col_count;
            END IF;

            RAISE NOTICE 'registry guardrails followup verified (0004c v3)';
        END;
        $$;
    """)


def downgrade() -> None:
    # Drop in reverse dependency order
    op.execute("DROP TRIGGER IF EXISTS features_no_delete ON registry.features;")
    op.execute("DROP TRIGGER IF EXISTS model_deployments_no_delete ON registry.model_deployments;")
    op.execute("DROP TRIGGER IF EXISTS models_no_delete ON registry.models;")
    op.execute("DROP TRIGGER IF EXISTS promotions_no_delete ON registry.promotions;")
    op.execute("DROP FUNCTION IF EXISTS registry.prevent_registry_audit_delete();")

    op.execute("DROP TRIGGER IF EXISTS model_deployments_insert_active ON registry.model_deployments;")
    op.execute("DROP FUNCTION IF EXISTS registry.enforce_deployment_insert_active();")

    op.execute("DROP TRIGGER IF EXISTS models_insert_active ON registry.models;")
    op.execute("DROP FUNCTION IF EXISTS registry.enforce_model_insert_active();")

    op.execute("DROP TRIGGER IF EXISTS model_deployments_identity_immutability ON registry.model_deployments;")
    op.execute("DROP FUNCTION IF EXISTS registry.enforce_deployment_identity_immutability();")

    op.execute("DROP TRIGGER IF EXISTS promotions_event_immutability ON registry.promotions;")
    op.execute("DROP FUNCTION IF EXISTS registry.enforce_promotion_event_immutability();")

    op.execute("DROP TRIGGER IF EXISTS models_no_retire_with_active_deployments ON registry.models;")
    op.execute("DROP FUNCTION IF EXISTS registry.enforce_no_retire_with_active_deployments();")

    op.execute("DROP TRIGGER IF EXISTS model_deployments_no_deploy_retired_update ON registry.model_deployments;")
    op.execute("DROP TRIGGER IF EXISTS model_deployments_no_deploy_retired_insert ON registry.model_deployments;")
    op.execute("DROP FUNCTION IF EXISTS registry.enforce_no_deploy_retired_model();")

    op.execute("DROP TRIGGER IF EXISTS model_deployments_retirement_irreversible ON registry.model_deployments;")
    op.execute("DROP FUNCTION IF EXISTS registry.enforce_deployment_retirement_irreversibility();")

    op.execute("DROP TRIGGER IF EXISTS models_retirement_irreversible ON registry.models;")
    op.execute("DROP FUNCTION IF EXISTS registry.enforce_model_retirement_irreversibility();")

    op.execute("DROP TRIGGER IF EXISTS strategies_phase_cache_guard ON registry.strategies;")
    op.execute("DROP FUNCTION IF EXISTS registry.enforce_strategy_phase_cache_update();")

    op.execute("ALTER TABLE registry.model_deployments DROP CONSTRAINT IF EXISTS model_deployments_retirement_all_or_nothing;")
    op.execute("ALTER TABLE registry.model_deployments DROP COLUMN IF EXISTS retirement_reason;")
    op.execute("ALTER TABLE registry.model_deployments DROP COLUMN IF EXISTS retired_by;")

    op.execute("ALTER TABLE registry.models DROP CONSTRAINT IF EXISTS models_retirement_all_or_nothing;")
    op.execute("ALTER TABLE registry.models DROP COLUMN IF EXISTS retired_by;")

    # Restore the original 0004b sync function
    op.execute("""
        CREATE OR REPLACE FUNCTION registry.sync_strategy_phase_from_promotion()
        RETURNS TRIGGER AS $$
        DECLARE
            target_phase TEXT;
            target_phase_at TIMESTAMPTZ;
            strategy_to_update BIGINT;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                strategy_to_update := NEW.strategy_id;
            ELSIF TG_OP = 'UPDATE' THEN
                strategy_to_update := NEW.strategy_id;
            ELSE
                strategy_to_update := OLD.strategy_id;
            END IF;

            SELECT to_phase, promoted_at
            INTO target_phase, target_phase_at
            FROM registry.promotions
            WHERE strategy_id = strategy_to_update AND revoked_at IS NULL
            ORDER BY promoted_at DESC LIMIT 1;

            IF target_phase IS NOT NULL THEN
                UPDATE registry.strategies
                SET current_phase = target_phase, phase_entered_at = target_phase_at
                WHERE id = strategy_to_update;
            END IF;

            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            ELSE
                RETURN NEW;
            END IF;
        END;
        $$ LANGUAGE plpgsql;
    """)
