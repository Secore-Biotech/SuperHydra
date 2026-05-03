"""registry_strategy_model

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-03

Creates strategy/model registry tables completing the registry layer:
- promotions: signed promotion events with active-uniqueness + revocation audit
- features: feature registry per model_policy v1.1
- models: versioned model artifacts with hash fields for reproducibility
- model_deployments: strategy-aware, role-aware, effective-dated deployments
- signal_batches: signal generation provenance (UUIDv7)
- allocator_runs: portfolio optimizer run records (UUIDv7)
- allocator_run_signal_batches: bridge for queryable allocator-signal lineage
- target_weights: per-instrument target weights (UUIDv7)
- portfolio_strategies: many-to-many bridge with no-overlap enforcement
- model_features: many-to-many bridge models <-> features
- strategy_feature_dependencies: many-to-many bridge for OMS data-fresh check

TODO 0016: model and feature immutability triggers; parity-passing requirement
on model_features insert.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ===== registry.promotions =====
    # Per measurement_policy v1.1 section 6
    # v0.2: from_phase CHECK, revocation audit fields, active-uniqueness index
    op.execute("""
        CREATE TABLE registry.promotions (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            strategy_id BIGINT NOT NULL REFERENCES registry.strategies(id),
            from_phase TEXT NOT NULL CHECK (from_phase IN (
                'research', 'shadow', 'canary', 'scale', 'paused', 'sunset'
            )),
            to_phase TEXT NOT NULL CHECK (to_phase IN (
                'research', 'shadow', 'canary', 'scale', 'paused', 'sunset'
            )),
            operator_id TEXT NOT NULL,
            operator_signature TEXT NOT NULL,
            signature_method TEXT NOT NULL CHECK (signature_method IN ('gpg', 'yubikey')),
            gate_evidence_doc_path TEXT NOT NULL,
            promoted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            revoked_at TIMESTAMPTZ,
            revoked_by TEXT,
            revocation_signature TEXT,
            revocation_signature_method TEXT CHECK (revocation_signature_method IN ('gpg', 'yubikey')),
            revocation_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (
                (to_phase IN ('research', 'shadow', 'paused', 'sunset')) OR
                (signature_method = 'yubikey')
            ),
            CHECK (revoked_at IS NULL OR revoked_at >= promoted_at),
            CHECK (
                (revoked_at IS NULL AND revoked_by IS NULL AND revocation_signature IS NULL
                 AND revocation_signature_method IS NULL)
                OR
                (revoked_at IS NOT NULL AND revoked_by IS NOT NULL
                 AND revocation_signature IS NOT NULL
                 AND revocation_signature_method IS NOT NULL)
            )
        );
    """)

    # Active-promotion uniqueness: a strategy has at most one un-revoked promotion
    op.execute("""
        CREATE UNIQUE INDEX uniq_active_strategy_promotion
            ON registry.promotions(strategy_id) WHERE revoked_at IS NULL;
    """)

    op.execute("""
        CREATE INDEX idx_promotions_strategy_active
            ON registry.promotions(strategy_id, promoted_at DESC) WHERE revoked_at IS NULL;
        CREATE INDEX idx_promotions_to_phase
            ON registry.promotions(to_phase) WHERE revoked_at IS NULL;
    """)

    op.execute("""
        COMMENT ON TABLE registry.promotions IS
            'Promotion events per measurement_policy v1.1 section 6. Yubikey required for canary+ promotions. Revocation requires same audit (revoked_by + revocation_signature). Partial unique index uniq_active_strategy_promotion enforces at most one active promotion per strategy.';
    """)

    # ===== registry.features =====
    # Per model_policy v1.1 section 4
    # v0.2: JSONB type check on data_sources
    op.execute("""
        CREATE TABLE registry.features (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            feature_name TEXT NOT NULL,
            version INTEGER NOT NULL,
            definition TEXT NOT NULL,
            computation_script_path TEXT NOT NULL,
            data_sources JSONB NOT NULL,
            refresh_cadence TEXT NOT NULL,
            expected_range JSONB,
            parity_test_passing BOOLEAN NOT NULL DEFAULT FALSE,
            parity_last_tested_at TIMESTAMPTZ,
            deprecated BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (feature_name, version),
            CHECK (version > 0),
            CHECK (jsonb_typeof(data_sources) = 'array')
        );
    """)

    op.execute("""
        CREATE INDEX idx_features_active
            ON registry.features(feature_name) WHERE deprecated = FALSE;
        CREATE INDEX idx_features_parity_failing
            ON registry.features(feature_name)
            WHERE parity_test_passing = FALSE AND deprecated = FALSE;
    """)

    op.execute("""
        CREATE TRIGGER features_updated_at
            BEFORE UPDATE ON registry.features
            FOR EACH ROW EXECUTE FUNCTION registry.set_updated_at();
    """)

    op.execute("""
        COMMENT ON TABLE registry.features IS
            'Feature registry per model_policy v1.1. (feature_name, version) uniquely identifies. data_sources is JSONB array. TODO 0016: immutability trigger preventing edits to definition/computation_script_path/data_sources after insert (only parity_test_passing, parity_last_tested_at, deprecated may change).';
    """)

    # ===== registry.models =====
    # v0.2: replaced single feature_version TEXT with feature_set_hash and friends
    # for proper validation-engine reproducibility
    op.execute("""
        CREATE TABLE registry.models (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            strategy_id BIGINT NOT NULL REFERENCES registry.strategies(id),
            version_id TEXT NOT NULL UNIQUE,
            model_class TEXT NOT NULL,
            training_data_hash TEXT NOT NULL,
            feature_set_hash TEXT NOT NULL,
            label_set_hash TEXT,
            hyperparam_hash TEXT NOT NULL,
            artifact_path TEXT NOT NULL,
            artifact_hash TEXT NOT NULL,
            validation_report_path TEXT,
            trained_at TIMESTAMPTZ NOT NULL,
            retired_at TIMESTAMPTZ,
            retirement_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (retired_at IS NULL OR retired_at >= trained_at)
        );
    """)

    op.execute("""
        CREATE INDEX idx_models_strategy
            ON registry.models(strategy_id, trained_at DESC);
        CREATE INDEX idx_models_active
            ON registry.models(strategy_id) WHERE retired_at IS NULL;
        CREATE INDEX idx_models_artifact_hash
            ON registry.models(artifact_hash);
    """)

    op.execute("""
        COMMENT ON TABLE registry.models IS
            'Model registry. version_id is human-readable; artifact_hash is content integrity. training_data_hash + feature_set_hash + label_set_hash + hyperparam_hash collectively identify reproducibility scope per validation engine v0.2. TODO 0016: immutability trigger preventing edits to artifact/training/feature/hash fields after insert (only retired_at and retirement_reason may change).';
    """)

    # ===== registry.model_deployments =====
    # v0.2: strategy_id + deployment_role per reviewer
    op.execute("""
        CREATE TABLE registry.model_deployments (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            model_id BIGINT NOT NULL REFERENCES registry.models(id),
            strategy_id BIGINT NOT NULL REFERENCES registry.strategies(id),
            environment TEXT NOT NULL CHECK (environment IN (
                'research', 'shadow', 'canary', 'scale'
            )),
            deployment_role TEXT NOT NULL DEFAULT 'primary' CHECK (deployment_role IN (
                'primary', 'ensemble_member', 'challenger', 'shadow_comparator'
            )),
            deployed_at TIMESTAMPTZ NOT NULL,
            retired_at TIMESTAMPTZ,
            deployed_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (retired_at IS NULL OR retired_at > deployed_at)
        );
    """)

    # No two deployments with same (strategy_id, environment, deployment_role) overlap
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

    op.execute("""
        CREATE INDEX idx_deployments_model
            ON registry.model_deployments(model_id, deployed_at DESC);
        CREATE INDEX idx_deployments_active
            ON registry.model_deployments(strategy_id, environment, deployment_role)
            WHERE retired_at IS NULL;
    """)

    op.execute("""
        COMMENT ON TABLE registry.model_deployments IS
            'Strategy-aware model-environment-role deployment history. (strategy_id, environment, deployment_role) ranges cannot overlap. Supports primary + ensemble_members + challenger simultaneously without conflict. App-level invariant: model.strategy_id == deployment.strategy_id (TODO 0016: trigger).';
    """)

    # ===== registry.signal_batches =====
    # UUIDv7 PK, JSONB type check
    op.execute("""
        CREATE TABLE registry.signal_batches (
            id UUID NOT NULL DEFAULT gen_uuidv7() PRIMARY KEY,
            strategy_id BIGINT NOT NULL REFERENCES registry.strategies(id),
            model_id BIGINT REFERENCES registry.models(id),
            feature_version TEXT NOT NULL,
            data_snapshot_id TEXT NOT NULL,
            batch_size INTEGER NOT NULL,
            generated_at TIMESTAMPTZ NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (batch_size >= 0),
            CHECK (jsonb_typeof(metadata) = 'object')
        );
    """)

    op.execute("""
        CREATE INDEX idx_signal_batches_strategy
            ON registry.signal_batches(strategy_id, generated_at DESC);
        CREATE INDEX idx_signal_batches_model
            ON registry.signal_batches(model_id, generated_at DESC) WHERE model_id IS NOT NULL;
    """)

    op.execute("""
        COMMENT ON TABLE registry.signal_batches IS
            'Signal generation provenance. Each batch represents one strategy-cycle of signal computation.';
    """)

    # ===== registry.allocator_runs =====
    # UUIDv7 PK; input_signal_batch_ids retained as cached metadata,
    # but allocator_run_signal_batches is the source of truth
    op.execute("""
        CREATE TABLE registry.allocator_runs (
            id UUID NOT NULL DEFAULT gen_uuidv7() PRIMARY KEY,
            portfolio_id BIGINT NOT NULL REFERENCES registry.portfolios(id),
            input_signal_batch_ids JSONB NOT NULL,
            objective_version TEXT NOT NULL,
            constraints_version TEXT NOT NULL,
            expected_return NUMERIC(20,12),
            expected_volatility NUMERIC(20,12),
            expected_sharpe NUMERIC(20,12),
            expected_turnover NUMERIC(20,12),
            solve_status TEXT NOT NULL CHECK (solve_status IN (
                'optimal', 'suboptimal', 'infeasible', 'failed'
            )),
            solve_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            generated_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (expected_volatility IS NULL OR expected_volatility >= 0),
            CHECK (expected_turnover IS NULL OR expected_turnover >= 0),
            CHECK (jsonb_typeof(input_signal_batch_ids) = 'array'),
            CHECK (jsonb_typeof(solve_metadata) = 'object')
        );
    """)

    op.execute("""
        CREATE INDEX idx_allocator_runs_portfolio
            ON registry.allocator_runs(portfolio_id, generated_at DESC);
        CREATE INDEX idx_allocator_runs_status
            ON registry.allocator_runs(solve_status, generated_at DESC) WHERE solve_status != 'optimal';
    """)

    op.execute("""
        COMMENT ON TABLE registry.allocator_runs IS
            'Portfolio optimizer runs. input_signal_batch_ids is cached metadata; allocator_run_signal_batches is source of truth for queryable lineage.';
    """)

    # ===== registry.allocator_run_signal_batches =====
    # NEW in v0.2: bridge table for queryable lineage (per reviewer)
    op.execute("""
        CREATE TABLE registry.allocator_run_signal_batches (
            allocator_run_id UUID NOT NULL REFERENCES registry.allocator_runs(id),
            signal_batch_id UUID NOT NULL REFERENCES registry.signal_batches(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (allocator_run_id, signal_batch_id)
        );
    """)

    op.execute("""
        CREATE INDEX idx_arsb_signal_batch
            ON registry.allocator_run_signal_batches(signal_batch_id);
    """)

    op.execute("""
        COMMENT ON TABLE registry.allocator_run_signal_batches IS
            'Bridge mapping allocator runs to the signal batches consumed. Source of truth for queryable lineage. allocator_runs.input_signal_batch_ids is denormalized cache.';
    """)

    # ===== registry.target_weights =====
    # UUIDv7; target_weight is signed (positive=long, negative=short for L/S strategies)
    op.execute("""
        CREATE TABLE registry.target_weights (
            id UUID NOT NULL DEFAULT gen_uuidv7() PRIMARY KEY,
            allocator_run_id UUID NOT NULL REFERENCES registry.allocator_runs(id),
            instrument_id BIGINT NOT NULL REFERENCES registry.instruments(id),
            target_weight NUMERIC(20,12) NOT NULL,
            target_notional_usd NUMERIC(38,12),
            target_quantity NUMERIC(38,18),
            reason JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (allocator_run_id, instrument_id),
            CHECK (jsonb_typeof(reason) = 'object')
        );
    """)

    op.execute("""
        CREATE INDEX idx_target_weights_run
            ON registry.target_weights(allocator_run_id);
        CREATE INDEX idx_target_weights_instrument
            ON registry.target_weights(instrument_id, created_at DESC);
    """)

    op.execute("""
        COMMENT ON TABLE registry.target_weights IS
            'Per-instrument target weights from allocator runs. target_weight is signed (positive=long, negative=short for L/S). Range-checks deferred to risk policy enforcement layer.';
    """)

    # ===== registry.portfolio_strategies =====
    # v0.2: active_risk_weight >= 0 check
    op.execute("""
        CREATE TABLE registry.portfolio_strategies (
            portfolio_id BIGINT NOT NULL REFERENCES registry.portfolios(id),
            strategy_id BIGINT NOT NULL REFERENCES registry.strategies(id),
            active_risk_weight NUMERIC(20,12),
            capital_allocation_pct NUMERIC(20,12),
            starts_at TIMESTAMPTZ NOT NULL,
            ends_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (portfolio_id, strategy_id, starts_at),
            CHECK (ends_at IS NULL OR ends_at > starts_at),
            CHECK (capital_allocation_pct IS NULL OR (capital_allocation_pct >= 0 AND capital_allocation_pct <= 1)),
            CHECK (active_risk_weight IS NULL OR active_risk_weight >= 0)
        );
    """)

    op.execute("""
        ALTER TABLE registry.portfolio_strategies
        ADD CONSTRAINT no_overlapping_portfolio_strategies
        EXCLUDE USING gist (
            portfolio_id WITH =,
            strategy_id WITH =,
            tstzrange(starts_at, COALESCE(ends_at, 'infinity'::timestamptz), '[)') WITH &&
        );
    """)

    op.execute("""
        CREATE INDEX idx_portfolio_strategies_active
            ON registry.portfolio_strategies(portfolio_id) WHERE ends_at IS NULL;
        CREATE INDEX idx_portfolio_strategies_strategy
            ON registry.portfolio_strategies(strategy_id);
    """)

    op.execute("""
        COMMENT ON TABLE registry.portfolio_strategies IS
            'Many-to-many bridge with no-overlap enforcement. capital_allocation_pct in [0,1]; active_risk_weight nonnegative.';
    """)

    # ===== registry.model_features =====
    # v0.2: feature_version removed (redundant with feature_id since (name,version) is unique)
    # FK ordering bug from v0.1 eliminated entirely
    op.execute("""
        CREATE TABLE registry.model_features (
            model_id BIGINT NOT NULL REFERENCES registry.models(id),
            feature_id BIGINT NOT NULL REFERENCES registry.features(id),
            required BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (model_id, feature_id)
        );
    """)

    op.execute("""
        CREATE INDEX idx_model_features_feature
            ON registry.model_features(feature_id);
    """)

    op.execute("""
        COMMENT ON TABLE registry.model_features IS
            'Bridge mapping models to features. feature_id uniquely identifies (feature_name, version) tuple. TODO 0016: trigger rejecting insert when feature.parity_test_passing = FALSE or feature.deprecated = TRUE.';
    """)

    # ===== registry.strategy_feature_dependencies =====
    # v0.2: feature_version removed for same reason
    op.execute("""
        CREATE TABLE registry.strategy_feature_dependencies (
            strategy_id BIGINT NOT NULL REFERENCES registry.strategies(id),
            feature_id BIGINT NOT NULL REFERENCES registry.features(id),
            required BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (strategy_id, feature_id)
        );
    """)

    op.execute("""
        CREATE INDEX idx_strategy_features_feature
            ON registry.strategy_feature_dependencies(feature_id);
    """)

    op.execute("""
        COMMENT ON TABLE registry.strategy_feature_dependencies IS
            'Bridge for OMS require_data_fresh check. feature_id resolves to specific (name, version). TODO 0016: trigger rejecting insert when feature parity-failing AND strategy in shadow/canary/scale.';
    """)

    # ===== Verification block =====
    op.execute("""
        DO $$
        DECLARE
            expected_tables TEXT[] := ARRAY[
                'promotions', 'features', 'models', 'model_deployments',
                'signal_batches', 'allocator_runs', 'allocator_run_signal_batches',
                'target_weights', 'portfolio_strategies', 'model_features',
                'strategy_feature_dependencies'
            ];
            actual_count INT;
            t TEXT;
        BEGIN
            FOREACH t IN ARRAY expected_tables LOOP
                SELECT COUNT(*) INTO actual_count
                FROM information_schema.tables
                WHERE table_schema = 'registry' AND table_name = t;

                IF actual_count != 1 THEN
                    RAISE EXCEPTION 'registry.% not created', t;
                END IF;
            END LOOP;

            RAISE NOTICE 'All 11 registry strategy/model tables verified';
        END;
        $$;
    """)


def downgrade() -> None:
    # Drop in reverse dependency order, no CASCADE
    op.execute("DROP TABLE IF EXISTS registry.strategy_feature_dependencies;")
    op.execute("DROP TABLE IF EXISTS registry.model_features;")
    op.execute("DROP TABLE IF EXISTS registry.portfolio_strategies;")
    op.execute("DROP TABLE IF EXISTS registry.target_weights;")
    op.execute("DROP TABLE IF EXISTS registry.allocator_run_signal_batches;")
    op.execute("DROP TABLE IF EXISTS registry.allocator_runs;")
    op.execute("DROP TABLE IF EXISTS registry.signal_batches;")
    op.execute("DROP TABLE IF EXISTS registry.model_deployments;")
    op.execute("DROP TABLE IF EXISTS registry.models;")
    op.execute("DROP TABLE IF EXISTS registry.features;")
    op.execute("DROP TABLE IF EXISTS registry.promotions;")
