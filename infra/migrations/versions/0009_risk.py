"""risk

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-05

Risk evaluation layer (v1.15) — 9 tables, ~23 functions (deferred to later rounds).

Round 1 of N (schema skeleton only):
  - 9 CREATE TABLE statements with CHECK constraints, PKs, FKs, indexes.
  - NO trigger functions, NO controlled write functions, NO read helpers.
  - Tables are inserted-into only via controlled functions (round 2+); empty
    in production until round 2 lands.

Foundational principles (v1.15):
  - Logical/version split: identity tables (limits, circuit_breakers) hold
    immutable scope keys; version tables (limit_versions, circuit_breaker_versions)
    are append-only configuration history.
  - Typed-FK lineage: evaluation_inputs records every input to an evaluation
    via typed FK columns (one populated per row, matching input_kind).
  - One-row-per-applicable-limit invariant (R7): evaluation_limit_results has
    UNIQUE (evaluation_id, limit_version_id).
  - Split result_reason taxonomy (R12-A / P8): per-limit reasons on
    evaluation_limit_results, top-line CB reasons on evaluations.
  - Verdict split (v1.4 R4 / P10 / P15): verdict_raw is 3-state, verdict_effective
    is 2-state with environment-dependent mapping. blocking↔severity_bucket
    invariant enforced via CHECK.
  - Environment isolation: LIVE / SHADOW / REPLAY / BACKTEST throughout.
  - 12-state cancel-target FSM (V4-resolved): handled in evaluator logic
    (round 2+); not enforced at table level here.

Structural design approved by external reviewer 2026-05-05 (v1.15, round 15).
See docs/migrations/0009_v1_15_design.md for the full specification.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS risk;")

    # ─────────────────────────────────────────────────────────────────────
    # TABLE 1: risk.limits (identity-only, logical/version split)
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE risk.limits (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            limit_uuid UUID NOT NULL DEFAULT gen_uuidv7() UNIQUE,
            portfolio_id BIGINT NOT NULL REFERENCES registry.portfolios(id),
            strategy_id BIGINT REFERENCES registry.strategies(id),
            account_id BIGINT REFERENCES registry.accounts(id),
            instrument_id BIGINT REFERENCES registry.instruments(id),
            dimension TEXT NOT NULL CHECK (dimension IN (
                'max_position_quantity',
                'max_notional_usd',
                'max_drawdown_usd',
                'max_leverage',          -- declared, not enforced in v1
                'max_concentration_pct'  -- declared, not enforced in v1
            )),
            scope TEXT NOT NULL CHECK (scope IN ('portfolio', 'strategy', 'instrument')),
            risk_environment TEXT NOT NULL CHECK (risk_environment IN (
                'LIVE', 'SHADOW', 'REPLAY', 'BACKTEST'
            )),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by TEXT NOT NULL,
            CHECK (LENGTH(TRIM(created_by)) > 0),
            -- Scope ↔ populated keys consistency
            CHECK (
                (scope = 'portfolio'  AND strategy_id IS NULL AND instrument_id IS NULL)
                OR (scope = 'strategy'   AND strategy_id IS NOT NULL AND instrument_id IS NULL)
                OR (scope = 'instrument' AND instrument_id IS NOT NULL)
            ),
            -- Dimension × scope compatibility (R2 v1.2; partial; upsert_limit enforces full matrix)
            CHECK (
                (dimension = 'max_position_quantity' AND scope = 'instrument')
                OR (dimension = 'max_notional_usd')
                OR (dimension = 'max_drawdown_usd' AND scope IN ('portfolio', 'strategy'))
                OR (dimension IN ('max_leverage', 'max_concentration_pct'))
            ),
            -- Unsupported-in-LIVE dimensions rejected at row level (R3 v1.3)
            CHECK (
                risk_environment != 'LIVE'
                OR dimension NOT IN ('max_leverage', 'max_concentration_pct')
            ),
            -- Identity uniqueness: one logical limit per (full scope keys, dimension, environment)
            UNIQUE NULLS NOT DISTINCT (
                portfolio_id, strategy_id, account_id, instrument_id,
                dimension, risk_environment
            )
        );
    """)
    op.execute("""
        CREATE INDEX idx_limits_resolution ON risk.limits(
            portfolio_id, strategy_id, account_id, instrument_id, risk_environment
        );
    """)

    # ─────────────────────────────────────────────────────────────────────
    # TABLE 2: risk.limit_versions (append-only)
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE risk.limit_versions (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            version_uuid UUID NOT NULL DEFAULT gen_uuidv7() UNIQUE,
            limit_id BIGINT NOT NULL REFERENCES risk.limits(id),
            limit_value NUMERIC(38,18) NOT NULL CHECK (limit_value > 0),
            blocking BOOLEAN NOT NULL,
            -- Drawdown-only; default 36h LIVE / NULL non-LIVE set at upsert_limit (P20)
            nav_staleness_bound_seconds INTEGER
                CHECK (nav_staleness_bound_seconds IS NULL OR nav_staleness_bound_seconds > 0),
            effective_at TIMESTAMPTZ NOT NULL,
            idempotency_key TEXT NOT NULL,
            config_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by TEXT NOT NULL,
            CHECK (LENGTH(TRIM(idempotency_key)) > 0),
            CHECK (LENGTH(TRIM(created_by)) > 0),
            CHECK (jsonb_typeof(config_metadata) = 'object'),
            UNIQUE (limit_id, idempotency_key)
        );
    """)
    op.execute("""
        CREATE INDEX idx_limit_versions_resolve ON risk.limit_versions(
            limit_id, effective_at DESC, id DESC
        );
    """)

    # ─────────────────────────────────────────────────────────────────────
    # TABLE 3: risk.regime_transitions (append-only)
    # Ordering convention: (transitioned_at, id) for "latest regime"
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE risk.regime_transitions (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            transition_uuid UUID NOT NULL DEFAULT gen_uuidv7() UNIQUE,
            portfolio_id BIGINT NOT NULL REFERENCES registry.portfolios(id),
            strategy_id BIGINT REFERENCES registry.strategies(id),
            regime TEXT NOT NULL CHECK (regime IN (
                'CRISIS', 'RECOVERY', 'NORMAL', 'GREED'
            )),
            risk_environment TEXT NOT NULL CHECK (risk_environment IN (
                'LIVE', 'SHADOW', 'REPLAY', 'BACKTEST'
            )),
            transitioned_at TIMESTAMPTZ NOT NULL,
            idempotency_key TEXT NOT NULL,
            transition_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by TEXT NOT NULL,
            CHECK (LENGTH(TRIM(idempotency_key)) > 0),
            CHECK (LENGTH(TRIM(created_by)) > 0),
            CHECK (jsonb_typeof(transition_metadata) = 'object'),
            UNIQUE NULLS NOT DISTINCT (
                portfolio_id, strategy_id, risk_environment, idempotency_key
            )
        );
    """)
    op.execute("""
        CREATE INDEX idx_regime_transitions_current ON risk.regime_transitions(
            portfolio_id, strategy_id, risk_environment, transitioned_at DESC, id DESC
        );
    """)

    # ─────────────────────────────────────────────────────────────────────
    # TABLE 4: risk.evaluations (append-only, UUID id)
    # Carries top-line CB result_reason (P8) and verdict_raw/verdict_effective (P10/P15)
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE risk.evaluations (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            evaluation_uuid UUID NOT NULL DEFAULT gen_uuidv7() UNIQUE,
            -- Scope
            portfolio_id BIGINT NOT NULL REFERENCES registry.portfolios(id),
            strategy_id BIGINT REFERENCES registry.strategies(id),
            -- Action context
            source_type TEXT NOT NULL CHECK (source_type IN (
                'intent', 'order', 'cancel', 'manual'
            )),
            source_id TEXT NOT NULL,
            cancel_target_order_id BIGINT REFERENCES trading.orders(id),
            -- Temporal
            as_of_at TIMESTAMPTZ NOT NULL,
            fill_cutoff_at TIMESTAMPTZ NOT NULL,
            -- Environment / regime (R14 cleanup: risk_environment, not environment)
            risk_environment TEXT NOT NULL CHECK (risk_environment IN (
                'LIVE', 'SHADOW', 'REPLAY', 'BACKTEST'
            )),
            regime_at_eval TEXT CHECK (
                regime_at_eval IS NULL
                OR regime_at_eval IN ('CRISIS', 'RECOVERY', 'NORMAL', 'GREED')
            ),
            regime_transition_id BIGINT REFERENCES risk.regime_transitions(id),
            -- Drawdown anchor (v1.5)
            anchor_valuation_run_id UUID REFERENCES accounting.valuation_runs(id),
            -- CB top-line outcome (P8 / R12-A)
            circuit_breaker_result_reason TEXT CHECK (
                circuit_breaker_result_reason IS NULL
                OR circuit_breaker_result_reason IN (
                    'cb_warn_only:applied',
                    'cb_throttle:applied',
                    'cb_throttle:cancel_exempted',
                    'cb_throttle:risk_reducer_exempted',
                    'cb_block_new_risk:applied',
                    'cb_block_new_risk:risk_reducer_exempted',
                    'cb_hard_stop:applied',
                    'insufficient_inputs:cb_missing'
                )
            ),
            -- Verdict resolution (P10/P15)
            verdict_raw TEXT NOT NULL CHECK (verdict_raw IN (
                'allowed', 'blocked', 'degraded'
            )),
            verdict_effective TEXT NOT NULL CHECK (verdict_effective IN (
                'allowed', 'blocked'
            )),
            -- Canonical predicate result (R10)
            is_genuinely_risk_reducing BOOLEAN,
            -- Idempotency / audit
            idempotency_key TEXT NOT NULL,
            eval_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by TEXT NOT NULL,
            CHECK (LENGTH(TRIM(source_id)) > 0),
            CHECK (LENGTH(TRIM(idempotency_key)) > 0),
            CHECK (LENGTH(TRIM(created_by)) > 0),
            CHECK (jsonb_typeof(eval_metadata) = 'object'),
            CHECK (fill_cutoff_at <= as_of_at),
            -- v1.10: cancel_target_order_id required iff source_type='cancel'
            CHECK (
                (source_type = 'cancel' AND cancel_target_order_id IS NOT NULL)
                OR (source_type != 'cancel' AND cancel_target_order_id IS NULL)
            ),
            -- v1.4 R4: LIVE missing regime → must be degraded (fail-closed)
            CHECK (
                risk_environment != 'LIVE'
                OR regime_at_eval IS NOT NULL
                OR verdict_raw = 'degraded'
            ),
            -- verdict_raw → verdict_effective mapping (P10):
            -- blocked → blocked; allowed → allowed; degraded depends on env
            CHECK (
                (verdict_raw = 'blocked'  AND verdict_effective = 'blocked')
                OR (verdict_raw = 'allowed'  AND verdict_effective = 'allowed')
                OR (verdict_raw = 'degraded' AND risk_environment = 'LIVE'  AND verdict_effective = 'blocked')
                OR (verdict_raw = 'degraded' AND risk_environment != 'LIVE' AND verdict_effective = 'allowed')
            ),
            -- Idempotency: per-environment unique action evaluation
            UNIQUE (source_type, source_id, risk_environment, idempotency_key)
        );
    """)
    op.execute("""
        CREATE INDEX idx_evaluations_portfolio_at ON risk.evaluations(
            portfolio_id, as_of_at DESC
        );
        CREATE INDEX idx_evaluations_source ON risk.evaluations(source_type, source_id);
        CREATE INDEX idx_evaluations_cancel_target ON risk.evaluations(cancel_target_order_id)
            WHERE cancel_target_order_id IS NOT NULL;
    """)

    # ─────────────────────────────────────────────────────────────────────
    # TABLE 5: risk.evaluation_inputs (append-only, typed-FK lineage; R1 v1.1, R4 v1.4)
    # Exactly one typed FK populated per row, matching input_kind.
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE risk.evaluation_inputs (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            evaluation_id BIGINT NOT NULL REFERENCES risk.evaluations(id),
            input_kind TEXT NOT NULL CHECK (input_kind IN (
                'mark_price_set',
                'mark_price',
                'valuation_run',
                'nav_snapshot',
                'position_snapshot',
                'fill',
                'order',
                'regime_transition'
            )),
            mark_price_set_id    UUID   REFERENCES accounting.mark_price_sets(id),
            mark_price_id        BIGINT REFERENCES accounting.mark_prices(id),
            valuation_run_id     UUID   REFERENCES accounting.valuation_runs(id),
            nav_snapshot_id      BIGINT REFERENCES accounting.nav_snapshots(id),
            position_snapshot_id BIGINT REFERENCES positions.position_snapshots(id),
            fill_id              BIGINT REFERENCES trading.fills(id),
            order_id             BIGINT REFERENCES trading.orders(id),
            regime_transition_id BIGINT REFERENCES risk.regime_transitions(id),
            -- For staleness checks (R4 v1.4): timestamp on the referenced source row
            input_source_timestamp TIMESTAMPTZ,
            -- Drawdown nav_window_hash etc. (R3 v1.3)
            input_hash TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            -- Exactly one typed FK populated
            CHECK (
                num_nonnulls(
                    mark_price_set_id, mark_price_id, valuation_run_id,
                    nav_snapshot_id, position_snapshot_id, fill_id,
                    order_id, regime_transition_id
                ) = 1
            ),
            -- Populated FK matches input_kind
            CHECK (
                   (input_kind = 'mark_price_set'    AND mark_price_set_id    IS NOT NULL)
                OR (input_kind = 'mark_price'        AND mark_price_id        IS NOT NULL)
                OR (input_kind = 'valuation_run'     AND valuation_run_id     IS NOT NULL)
                OR (input_kind = 'nav_snapshot'      AND nav_snapshot_id      IS NOT NULL)
                OR (input_kind = 'position_snapshot' AND position_snapshot_id IS NOT NULL)
                OR (input_kind = 'fill'              AND fill_id              IS NOT NULL)
                OR (input_kind = 'order'             AND order_id             IS NOT NULL)
                OR (input_kind = 'regime_transition' AND regime_transition_id IS NOT NULL)
            ),
            CHECK (input_hash IS NULL OR LENGTH(TRIM(input_hash)) > 0)
        );
    """)
    op.execute("""
        CREATE INDEX idx_evaluation_inputs_eval ON risk.evaluation_inputs(evaluation_id);
        CREATE INDEX idx_evaluation_inputs_mark_price_set ON risk.evaluation_inputs(mark_price_set_id)
            WHERE mark_price_set_id IS NOT NULL;
        CREATE INDEX idx_evaluation_inputs_valuation_run ON risk.evaluation_inputs(valuation_run_id)
            WHERE valuation_run_id IS NOT NULL;
    """)

    # ─────────────────────────────────────────────────────────────────────
    # TABLE 6: risk.evaluation_limit_results (append-only, R7 invariant)
    # One row per applicable limit per evaluation.
    # P15 invariant: blocking ↔ severity_bucket IN ('breach','critical').
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE risk.evaluation_limit_results (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            evaluation_id BIGINT NOT NULL REFERENCES risk.evaluations(id),
            limit_version_id BIGINT NOT NULL REFERENCES risk.limit_versions(id),
            result_reason TEXT NOT NULL CHECK (result_reason IN (
                'evaluated:within_limits',
                'evaluated:limit_breached',
                'evaluated:exit:reducing',
                'evaluated:exit:complete',
                'evaluated:exit:flip',
                'evaluated:cancel_no_effect',
                'insufficient_inputs:missing',
                'insufficient_inputs:stale',
                'insufficient_inputs:target_state_indeterminate'
            )),
            severity_bucket TEXT NOT NULL CHECK (severity_bucket IN (
                'within_limits', 'breach', 'critical', 'insufficient_inputs'
            )),
            blocking BOOLEAN NOT NULL,
            -- Decision values (NULL when not derivable, e.g. Bucket D indeterminate)
            limit_value    NUMERIC(38,18),
            observed_value NUMERIC(38,18),
            breach_ratio   NUMERIC(38,18),  -- observed_value / limit_value
            result_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (jsonb_typeof(result_metadata) = 'object'),
            -- P15 invariant: blocking reserved for breach/critical severities
            CHECK (
                (blocking = true  AND severity_bucket IN ('breach', 'critical'))
                OR blocking = false
            ),
            -- severity_bucket ↔ result_reason prefix consistency (P13)
            CHECK (
                (severity_bucket = 'insufficient_inputs'
                    AND result_reason LIKE 'insufficient_inputs:%')
                OR
                (severity_bucket != 'insufficient_inputs'
                    AND result_reason NOT LIKE 'insufficient_inputs:%')
            ),
            -- R7: one row per applicable limit per evaluation
            UNIQUE (evaluation_id, limit_version_id)
        );
    """)
    op.execute("""
        CREATE INDEX idx_eval_limit_results_eval ON risk.evaluation_limit_results(evaluation_id);
        CREATE INDEX idx_eval_limit_results_blocking ON risk.evaluation_limit_results(evaluation_id)
            WHERE blocking = true;
        CREATE INDEX idx_eval_limit_results_degraded ON risk.evaluation_limit_results(evaluation_id)
            WHERE severity_bucket = 'insufficient_inputs';
    """)

    # ─────────────────────────────────────────────────────────────────────
    # TABLE 7: risk.circuit_breakers (identity-only)
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE risk.circuit_breakers (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            cb_uuid UUID NOT NULL DEFAULT gen_uuidv7() UNIQUE,
            portfolio_id BIGINT NOT NULL REFERENCES registry.portfolios(id),
            strategy_id BIGINT REFERENCES registry.strategies(id),
            cb_name TEXT NOT NULL,
            risk_environment TEXT NOT NULL CHECK (risk_environment IN (
                'LIVE', 'SHADOW', 'REPLAY', 'BACKTEST'
            )),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by TEXT NOT NULL,
            CHECK (LENGTH(TRIM(cb_name)) > 0),
            CHECK (LENGTH(TRIM(created_by)) > 0),
            UNIQUE NULLS NOT DISTINCT (portfolio_id, strategy_id, cb_name, risk_environment)
        );
    """)
    op.execute("""
        CREATE INDEX idx_circuit_breakers_resolution ON risk.circuit_breakers(
            portfolio_id, strategy_id, risk_environment
        );
    """)

    # ─────────────────────────────────────────────────────────────────────
    # TABLE 8: risk.circuit_breaker_versions (append-only)
    # P21: throttle_params JSONB present iff action='throttle'.
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE risk.circuit_breaker_versions (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            version_uuid UUID NOT NULL DEFAULT gen_uuidv7() UNIQUE,
            circuit_breaker_id BIGINT NOT NULL REFERENCES risk.circuit_breakers(id),
            action TEXT NOT NULL CHECK (action IN (
                'warn_only', 'block_new_risk', 'throttle', 'hard_stop'
            )),
            -- P21: required iff action='throttle'; runtime owns interpretation
            throttle_params JSONB,
            -- R4 v1.4: regime control-plane via per-version applies_in_regimes
            applies_in_regimes TEXT[] NOT NULL,
            effective_at TIMESTAMPTZ NOT NULL,
            idempotency_key TEXT NOT NULL,
            config_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by TEXT NOT NULL,
            CHECK (LENGTH(TRIM(idempotency_key)) > 0),
            CHECK (LENGTH(TRIM(created_by)) > 0),
            CHECK (jsonb_typeof(config_metadata) = 'object'),
            -- P21: throttle_params consistency
            CHECK (
                (action = 'throttle'
                    AND throttle_params IS NOT NULL
                    AND jsonb_typeof(throttle_params) = 'object')
                OR (action != 'throttle' AND throttle_params IS NULL)
            ),
            -- applies_in_regimes: non-empty subset of canonical regime values
            CHECK (
                cardinality(applies_in_regimes) > 0
                AND applies_in_regimes <@ ARRAY['CRISIS', 'RECOVERY', 'NORMAL', 'GREED']::TEXT[]
            ),
            UNIQUE (circuit_breaker_id, idempotency_key)
        );
    """)
    op.execute("""
        CREATE INDEX idx_cb_versions_resolve ON risk.circuit_breaker_versions(
            circuit_breaker_id, effective_at DESC, id DESC
        );
    """)

    # ─────────────────────────────────────────────────────────────────────
    # TABLE 9: risk.circuit_breaker_states (append-only; keyed to BREAKER identity, not version)
    # R4 v1.4: states keyed to breaker identity so version changes don't lose state.
    # Ordering convention: (state_transitioned_at, id) for "latest state".
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE risk.circuit_breaker_states (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            state_uuid UUID NOT NULL DEFAULT gen_uuidv7() UNIQUE,
            circuit_breaker_id BIGINT NOT NULL REFERENCES risk.circuit_breakers(id),
            state TEXT NOT NULL CHECK (state IN ('armed', 'tripped', 'reset_pending')),
            state_transitioned_at TIMESTAMPTZ NOT NULL,
            -- Set when state='tripped' from an evaluation; NULL for manual transitions / initial arm
            triggering_evaluation_id BIGINT REFERENCES risk.evaluations(id),
            transition_reason TEXT,
            state_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            idempotency_key TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by TEXT NOT NULL,
            CHECK (LENGTH(TRIM(idempotency_key)) > 0),
            CHECK (LENGTH(TRIM(created_by)) > 0),
            CHECK (jsonb_typeof(state_metadata) = 'object'),
            CHECK (transition_reason IS NULL OR LENGTH(TRIM(transition_reason)) > 0),
            UNIQUE (circuit_breaker_id, idempotency_key)
        );
    """)
    op.execute("""
        CREATE INDEX idx_cb_states_current ON risk.circuit_breaker_states(
            circuit_breaker_id, state_transitioned_at DESC, id DESC
        );
        CREATE INDEX idx_cb_states_triggering_eval ON risk.circuit_breaker_states(triggering_evaluation_id)
            WHERE triggering_evaluation_id IS NOT NULL;
    """)


def downgrade() -> None:
    # Reverse FK dependency order
    op.execute("DROP TABLE IF EXISTS risk.circuit_breaker_states;")
    op.execute("DROP TABLE IF EXISTS risk.circuit_breaker_versions;")
    op.execute("DROP TABLE IF EXISTS risk.circuit_breakers;")
    op.execute("DROP TABLE IF EXISTS risk.evaluation_limit_results;")
    op.execute("DROP TABLE IF EXISTS risk.evaluation_inputs;")
    op.execute("DROP TABLE IF EXISTS risk.evaluations;")
    op.execute("DROP TABLE IF EXISTS risk.regime_transitions;")
    op.execute("DROP TABLE IF EXISTS risk.limit_versions;")
    op.execute("DROP TABLE IF EXISTS risk.limits;")
    # Note: risk schema was created in 0001; do not drop here.
