"""risk

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-05

Risk evaluation layer (v1.15) — 9 tables, ~23 functions.

Round 2a of N (schema + non-evaluator functions):
  - 9 CREATE TABLE statements with CHECK constraints, PKs, FKs, indexes (round 1).
  - 14 trigger functions + triggers: append-only enforcement, identity-immutable
    enforcement, controlled-INSERT gates, CB FSM enforcement.
  - 4 controlled write functions: upsert_limit, upsert_circuit_breaker,
    record_regime_transition, set_circuit_breaker_state.
  - 3 read helpers: resolve_active_limit_versions, resolve_active_circuit_breakers,
    current_regime.
  - DEFERRED to round 2b: evaluate_action, replay_evaluation.

Idempotency convention (0009-specific, choose Option B per R-round-1):
  Controlled write functions INSERT first, catch unique_violation, and return
  the existing row identifier. Callers retrying with the same idempotency_key
  observe success, not a raw constraint violation.

Append-only / controlled-only enforcement:
  Pattern matches 0007/0008: BEFORE-INSERT triggers reject direct inserts
  except when invoked through controlled-function session flag; BEFORE
  UPDATE/DELETE triggers raise on append-only tables; identity-row triggers
  reject mutation of identity columns.

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
    (round 2b); not enforced at table level here.
  - Effective_at monotonicity (R-round-1 B3): version effective_at must be
    non-decreasing per (limit_id) / (circuit_breaker_id).

Structural design approved by external reviewer 2026-05-05 (v1.15, round 15).
Round 1 SQL approved 2026-05-05 (with patches for evaluations.id BIGINT and
index accounting). Round 2a in progress.

See docs/migrations/0009_v1_15_design.md for the full structural specification.
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

    # =====================================================================
    # ROUND 2a — TRIGGER FUNCTIONS, CONTROLLED WRITERS, READ HELPERS
    # =====================================================================

    # ─────────────────────────────────────────────────────────────────────
    # CONTROLLED-INSERT GATE PATTERN
    # Every append-only / version table has a BEFORE INSERT trigger that
    # rejects direct INSERTs. The controlled function sets a per-session
    # config flag (set_config(..., true) for transaction-local scope) that
    # the trigger reads to allow the insert through.
    # Matches 0007/0008 pattern.
    # ─────────────────────────────────────────────────────────────────────

    # ─────────────────────────────────────────────────────────────────────
    # TRIGGER FN 1: enforce_limit_insert_gate
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION risk.enforce_limit_insert_gate()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            IF current_setting('risk.allow_limit_insert', true) IS DISTINCT FROM 'on' THEN
                RAISE EXCEPTION 'Direct INSERT into risk.limits is forbidden; use risk.upsert_limit()';
            END IF;
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("CREATE TRIGGER limits_a_insert_gate BEFORE INSERT ON risk.limits FOR EACH ROW EXECUTE FUNCTION risk.enforce_limit_insert_gate();")

    # ─────────────────────────────────────────────────────────────────────
    # TRIGGER FN 2: enforce_limit_identity_immutable
    # risk.limits is identity-only; no field on it should ever be updated.
    # DELETE forbidden because version rows FK to it.
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION risk.enforce_limit_identity_immutable()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                RAISE EXCEPTION 'risk.limits identity row % is immutable', OLD.id;
            ELSIF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'risk.limits forbids DELETE; limits are referenced by version history.';
            END IF;
            RETURN NULL;
        END;
        $$;
    """)
    op.execute("CREATE TRIGGER limits_b_identity_immutable BEFORE UPDATE OR DELETE ON risk.limits FOR EACH ROW EXECUTE FUNCTION risk.enforce_limit_identity_immutable();")

    # ─────────────────────────────────────────────────────────────────────
    # TRIGGER FN 3: enforce_limit_version_insert_gate
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION risk.enforce_limit_version_insert_gate()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            IF current_setting('risk.allow_limit_version_insert', true) IS DISTINCT FROM 'on' THEN
                RAISE EXCEPTION 'Direct INSERT into risk.limit_versions is forbidden; use risk.upsert_limit()';
            END IF;
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("CREATE TRIGGER limit_versions_a_insert_gate BEFORE INSERT ON risk.limit_versions FOR EACH ROW EXECUTE FUNCTION risk.enforce_limit_version_insert_gate();")

    # ─────────────────────────────────────────────────────────────────────
    # TRIGGER FN 4: enforce_limit_version_append_only
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION risk.enforce_limit_version_append_only()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'risk.limit_versions is append-only; UPDATE/DELETE forbidden.';
            RETURN NULL;
        END;
        $$;
    """)
    op.execute("CREATE TRIGGER limit_versions_b_append_only BEFORE UPDATE OR DELETE ON risk.limit_versions FOR EACH ROW EXECUTE FUNCTION risk.enforce_limit_version_append_only();")

    # ─────────────────────────────────────────────────────────────────────
    # TRIGGER FN 5: enforce_regime_transitions_insert_gate
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION risk.enforce_regime_transitions_insert_gate()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            IF current_setting('risk.allow_regime_transition_insert', true) IS DISTINCT FROM 'on' THEN
                RAISE EXCEPTION 'Direct INSERT into risk.regime_transitions is forbidden; use risk.record_regime_transition()';
            END IF;
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("CREATE TRIGGER regime_transitions_a_insert_gate BEFORE INSERT ON risk.regime_transitions FOR EACH ROW EXECUTE FUNCTION risk.enforce_regime_transitions_insert_gate();")

    # ─────────────────────────────────────────────────────────────────────
    # TRIGGER FN 6: enforce_regime_transitions_append_only
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION risk.enforce_regime_transitions_append_only()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'risk.regime_transitions is append-only; UPDATE/DELETE forbidden.';
            RETURN NULL;
        END;
        $$;
    """)
    op.execute("CREATE TRIGGER regime_transitions_b_append_only BEFORE UPDATE OR DELETE ON risk.regime_transitions FOR EACH ROW EXECUTE FUNCTION risk.enforce_regime_transitions_append_only();")

    # ─────────────────────────────────────────────────────────────────────
    # TRIGGER FN 7: enforce_evaluations_append_only
    # No INSERT gate here; evaluate_action (round 2b) is the only writer
    # and the gate will be added then. Append-only protects against
    # post-evaluation mutation.
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION risk.enforce_evaluations_append_only()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'risk.evaluations is append-only; UPDATE/DELETE forbidden.';
            RETURN NULL;
        END;
        $$;
    """)
    op.execute("CREATE TRIGGER evaluations_a_append_only BEFORE UPDATE OR DELETE ON risk.evaluations FOR EACH ROW EXECUTE FUNCTION risk.enforce_evaluations_append_only();")

    # ─────────────────────────────────────────────────────────────────────
    # TRIGGER FN 8: enforce_evaluation_inputs_append_only
    # Same comment as 7: writer is evaluate_action, gate lands round 2b.
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION risk.enforce_evaluation_inputs_append_only()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'risk.evaluation_inputs is append-only; UPDATE/DELETE forbidden.';
            RETURN NULL;
        END;
        $$;
    """)
    op.execute("CREATE TRIGGER evaluation_inputs_a_append_only BEFORE UPDATE OR DELETE ON risk.evaluation_inputs FOR EACH ROW EXECUTE FUNCTION risk.enforce_evaluation_inputs_append_only();")

    # ─────────────────────────────────────────────────────────────────────
    # TRIGGER FN 9: enforce_evaluation_limit_results_append_only
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION risk.enforce_evaluation_limit_results_append_only()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'risk.evaluation_limit_results is append-only; UPDATE/DELETE forbidden.';
            RETURN NULL;
        END;
        $$;
    """)
    op.execute("CREATE TRIGGER evaluation_limit_results_a_append_only BEFORE UPDATE OR DELETE ON risk.evaluation_limit_results FOR EACH ROW EXECUTE FUNCTION risk.enforce_evaluation_limit_results_append_only();")

    # ─────────────────────────────────────────────────────────────────────
    # TRIGGER FN 10: enforce_circuit_breaker_insert_gate
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION risk.enforce_circuit_breaker_insert_gate()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            IF current_setting('risk.allow_cb_insert', true) IS DISTINCT FROM 'on' THEN
                RAISE EXCEPTION 'Direct INSERT into risk.circuit_breakers is forbidden; use risk.upsert_circuit_breaker()';
            END IF;
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("CREATE TRIGGER circuit_breakers_a_insert_gate BEFORE INSERT ON risk.circuit_breakers FOR EACH ROW EXECUTE FUNCTION risk.enforce_circuit_breaker_insert_gate();")

    # ─────────────────────────────────────────────────────────────────────
    # TRIGGER FN 11: enforce_circuit_breaker_identity_immutable
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION risk.enforce_circuit_breaker_identity_immutable()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                RAISE EXCEPTION 'risk.circuit_breakers identity row % is immutable', OLD.id;
            ELSIF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'risk.circuit_breakers forbids DELETE; CBs are referenced by version and state history.';
            END IF;
            RETURN NULL;
        END;
        $$;
    """)
    op.execute("CREATE TRIGGER circuit_breakers_b_identity_immutable BEFORE UPDATE OR DELETE ON risk.circuit_breakers FOR EACH ROW EXECUTE FUNCTION risk.enforce_circuit_breaker_identity_immutable();")

    # ─────────────────────────────────────────────────────────────────────
    # TRIGGER FN 12: enforce_cb_version_insert_gate
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION risk.enforce_cb_version_insert_gate()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            IF current_setting('risk.allow_cb_version_insert', true) IS DISTINCT FROM 'on' THEN
                RAISE EXCEPTION 'Direct INSERT into risk.circuit_breaker_versions is forbidden; use risk.upsert_circuit_breaker()';
            END IF;
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("CREATE TRIGGER cb_versions_a_insert_gate BEFORE INSERT ON risk.circuit_breaker_versions FOR EACH ROW EXECUTE FUNCTION risk.enforce_cb_version_insert_gate();")

    # ─────────────────────────────────────────────────────────────────────
    # TRIGGER FN 13: enforce_cb_version_append_only
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION risk.enforce_cb_version_append_only()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'risk.circuit_breaker_versions is append-only; UPDATE/DELETE forbidden.';
            RETURN NULL;
        END;
        $$;
    """)
    op.execute("CREATE TRIGGER cb_versions_b_append_only BEFORE UPDATE OR DELETE ON risk.circuit_breaker_versions FOR EACH ROW EXECUTE FUNCTION risk.enforce_cb_version_append_only();")

    # ─────────────────────────────────────────────────────────────────────
    # TRIGGER FN 14: enforce_cb_state_insert_gate
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION risk.enforce_cb_state_insert_gate()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            IF current_setting('risk.allow_cb_state_insert', true) IS DISTINCT FROM 'on' THEN
                RAISE EXCEPTION 'Direct INSERT into risk.circuit_breaker_states is forbidden; use risk.upsert_circuit_breaker() or risk.set_circuit_breaker_state()';
            END IF;
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("CREATE TRIGGER cb_states_a_insert_gate BEFORE INSERT ON risk.circuit_breaker_states FOR EACH ROW EXECUTE FUNCTION risk.enforce_cb_state_insert_gate();")

    # ─────────────────────────────────────────────────────────────────────
    # TRIGGER FN 15: enforce_cb_state_fsm
    # CB state machine: armed → tripped, tripped → reset_pending,
    # reset_pending → armed. Initial state must be 'armed' (no prior state).
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION risk.enforce_cb_state_fsm()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        DECLARE
            v_prev_state TEXT;
            v_prev_transitioned_at TIMESTAMPTZ;
        BEGIN
            -- Latest state for this breaker, by (state_transitioned_at DESC, id DESC)
            SELECT state, state_transitioned_at
              INTO v_prev_state, v_prev_transitioned_at
            FROM risk.circuit_breaker_states
            WHERE circuit_breaker_id = NEW.circuit_breaker_id
            ORDER BY state_transitioned_at DESC, id DESC
            LIMIT 1;

            -- Initial state: must be 'armed'
            IF v_prev_state IS NULL THEN
                IF NEW.state <> 'armed' THEN
                    RAISE EXCEPTION 'risk.circuit_breaker_states: initial state for breaker % must be ''armed'', got ''%''',
                        NEW.circuit_breaker_id, NEW.state;
                END IF;
            ELSE
                -- Monotonic time: cannot insert state earlier than latest
                IF NEW.state_transitioned_at < v_prev_transitioned_at THEN
                    RAISE EXCEPTION 'risk.circuit_breaker_states: state_transitioned_at % is before latest existing % for breaker %',
                        NEW.state_transitioned_at, v_prev_transitioned_at, NEW.circuit_breaker_id;
                END IF;
                -- FSM transitions
                IF NOT (
                       (v_prev_state = 'armed'         AND NEW.state = 'tripped')
                    OR (v_prev_state = 'tripped'       AND NEW.state = 'reset_pending')
                    OR (v_prev_state = 'reset_pending' AND NEW.state = 'armed')
                ) THEN
                    RAISE EXCEPTION 'risk.circuit_breaker_states: invalid FSM transition % → % for breaker %',
                        v_prev_state, NEW.state, NEW.circuit_breaker_id;
                END IF;
            END IF;

            -- triggering_evaluation_id only valid when transitioning to tripped
            IF NEW.triggering_evaluation_id IS NOT NULL AND NEW.state <> 'tripped' THEN
                RAISE EXCEPTION 'risk.circuit_breaker_states: triggering_evaluation_id only valid when state=tripped, got state=%', NEW.state;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("CREATE TRIGGER cb_states_b_fsm BEFORE INSERT ON risk.circuit_breaker_states FOR EACH ROW EXECUTE FUNCTION risk.enforce_cb_state_fsm();")

    # ─────────────────────────────────────────────────────────────────────
    # TRIGGER FN 16: enforce_cb_state_append_only
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION risk.enforce_cb_state_append_only()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'risk.circuit_breaker_states is append-only; UPDATE/DELETE forbidden.';
            RETURN NULL;
        END;
        $$;
    """)
    op.execute("CREATE TRIGGER cb_states_c_append_only BEFORE UPDATE OR DELETE ON risk.circuit_breaker_states FOR EACH ROW EXECUTE FUNCTION risk.enforce_cb_state_append_only();")

    # =====================================================================
    # CONTROLLED WRITE FUNCTIONS
    # =====================================================================

    # ─────────────────────────────────────────────────────────────────────
    # FUNCTION: risk.upsert_limit
    # Atomically creates the logical limit row (if absent) and appends a
    # version row. Idempotent on (limit_id, idempotency_key) UNIQUE.
    # Enforces:
    #   - dimension × scope × environment compatibility (full matrix; CHECK on
    #     limits enforces partial; this function enforces fullness)
    #   - effective_at monotonic non-decreasing per limit_id (R-round-1 B3)
    #   - LIVE rejection of declared-but-not-enforced dimensions
    #   - default nav_staleness_bound_seconds (P20: 36h LIVE / NULL non-LIVE)
    #     when caller passes NULL for drawdown limits
    # Returns (limit_id, limit_version_id).
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION risk.upsert_limit(
            p_portfolio_id    BIGINT,
            p_strategy_id     BIGINT,        -- NULL allowed depending on scope
            p_account_id      BIGINT,        -- NULL allowed depending on scope
            p_instrument_id   BIGINT,        -- NULL allowed depending on scope
            p_dimension       TEXT,
            p_scope           TEXT,
            p_risk_environment TEXT,
            p_limit_value     NUMERIC,
            p_blocking        BOOLEAN,
            p_nav_staleness_bound_seconds INTEGER,  -- NULL → default
            p_effective_at    TIMESTAMPTZ,
            p_idempotency_key TEXT,
            p_config_metadata JSONB,
            p_created_by      TEXT
        ) RETURNS TABLE(limit_id BIGINT, limit_version_id BIGINT)
        LANGUAGE plpgsql AS $$
        DECLARE
            v_limit_id BIGINT;
            v_limit_version_id BIGINT;
            v_existing_version_id BIGINT;
            v_max_existing_effective_at TIMESTAMPTZ;
            v_effective_nav_bound INTEGER;
        BEGIN
            -- Argument validation
            IF p_portfolio_id IS NULL OR p_dimension IS NULL OR p_scope IS NULL
               OR p_risk_environment IS NULL OR p_limit_value IS NULL
               OR p_blocking IS NULL OR p_effective_at IS NULL
               OR p_idempotency_key IS NULL OR p_created_by IS NULL THEN
                RAISE EXCEPTION 'risk.upsert_limit: required arguments must be non-NULL';
            END IF;
            IF LENGTH(TRIM(p_idempotency_key)) = 0 OR LENGTH(TRIM(p_created_by)) = 0 THEN
                RAISE EXCEPTION 'risk.upsert_limit: idempotency_key and created_by must be non-empty';
            END IF;

            -- Full dimension × scope × environment compatibility matrix.
            -- (CHECK on risk.limits handles the easy cases; this function
            -- enforces the LIVE-rejection of declared-but-not-enforced
            -- dimensions, which the row-level CHECK also catches but we
            -- raise here with a clearer message.)
            IF p_risk_environment = 'LIVE'
               AND p_dimension IN ('max_leverage', 'max_concentration_pct') THEN
                RAISE EXCEPTION 'risk.upsert_limit: dimension % is declared-but-not-enforced and not allowed in LIVE environment', p_dimension;
            END IF;
            IF p_dimension = 'max_position_quantity' AND p_scope <> 'instrument' THEN
                RAISE EXCEPTION 'risk.upsert_limit: max_position_quantity requires scope=instrument, got %', p_scope;
            END IF;
            IF p_dimension = 'max_drawdown_usd' AND p_scope NOT IN ('portfolio', 'strategy') THEN
                RAISE EXCEPTION 'risk.upsert_limit: max_drawdown_usd requires scope IN (portfolio, strategy), got %', p_scope;
            END IF;

            -- Default nav_staleness_bound_seconds for drawdown limits (P20)
            IF p_dimension = 'max_drawdown_usd' AND p_nav_staleness_bound_seconds IS NULL THEN
                v_effective_nav_bound := CASE p_risk_environment
                                            WHEN 'LIVE' THEN 129600  -- 36h
                                            ELSE NULL
                                          END;
            ELSE
                v_effective_nav_bound := p_nav_staleness_bound_seconds;
            END IF;
            -- Non-drawdown limits should not carry nav_staleness_bound
            IF p_dimension <> 'max_drawdown_usd' AND v_effective_nav_bound IS NOT NULL THEN
                RAISE EXCEPTION 'risk.upsert_limit: nav_staleness_bound_seconds only valid for max_drawdown_usd dimension';
            END IF;

            -- Insert-or-find logical row (idempotent on identity UNIQUE)
            PERFORM set_config('risk.allow_limit_insert', 'on', true);
            BEGIN
                INSERT INTO risk.limits (
                    portfolio_id, strategy_id, account_id, instrument_id,
                    dimension, scope, risk_environment, created_by
                ) VALUES (
                    p_portfolio_id, p_strategy_id, p_account_id, p_instrument_id,
                    p_dimension, p_scope, p_risk_environment, p_created_by
                ) RETURNING id INTO v_limit_id;
            EXCEPTION WHEN unique_violation THEN
                SELECT id INTO v_limit_id
                FROM risk.limits
                WHERE portfolio_id = p_portfolio_id
                  AND strategy_id IS NOT DISTINCT FROM p_strategy_id
                  AND account_id  IS NOT DISTINCT FROM p_account_id
                  AND instrument_id IS NOT DISTINCT FROM p_instrument_id
                  AND dimension = p_dimension
                  AND risk_environment = p_risk_environment;
            END;
            PERFORM set_config('risk.allow_limit_insert', 'off', true);

            -- Idempotent version-insert: caller may retry with same key
            SELECT id INTO v_existing_version_id
            FROM risk.limit_versions
            WHERE limit_id = v_limit_id AND idempotency_key = p_idempotency_key;
            IF v_existing_version_id IS NOT NULL THEN
                RETURN QUERY SELECT v_limit_id, v_existing_version_id;
                RETURN;
            END IF;

            -- Monotonic effective_at (R-round-1 B3)
            SELECT MAX(effective_at) INTO v_max_existing_effective_at
            FROM risk.limit_versions
            WHERE limit_id = v_limit_id;
            IF v_max_existing_effective_at IS NOT NULL
               AND p_effective_at < v_max_existing_effective_at THEN
                RAISE EXCEPTION 'risk.upsert_limit: effective_at % is before latest version effective_at % for limit %; versions must be monotonically non-decreasing',
                    p_effective_at, v_max_existing_effective_at, v_limit_id;
            END IF;

            -- Insert version row
            PERFORM set_config('risk.allow_limit_version_insert', 'on', true);
            BEGIN
                INSERT INTO risk.limit_versions (
                    limit_id, limit_value, blocking,
                    nav_staleness_bound_seconds, effective_at,
                    idempotency_key, config_metadata, created_by
                ) VALUES (
                    v_limit_id, p_limit_value, p_blocking,
                    v_effective_nav_bound, p_effective_at,
                    p_idempotency_key, COALESCE(p_config_metadata, '{}'::jsonb), p_created_by
                ) RETURNING id INTO v_limit_version_id;
            EXCEPTION WHEN unique_violation THEN
                -- Race: another concurrent caller inserted same idempotency_key
                SELECT id INTO v_limit_version_id
                FROM risk.limit_versions
                WHERE limit_id = v_limit_id AND idempotency_key = p_idempotency_key;
            END;
            PERFORM set_config('risk.allow_limit_version_insert', 'off', true);

            RETURN QUERY SELECT v_limit_id, v_limit_version_id;
        END;
        $$;
    """)

    # ─────────────────────────────────────────────────────────────────────
    # FUNCTION: risk.upsert_circuit_breaker
    # Atomically creates the logical CB, first version, AND initial 'armed'
    # state row on first creation (R5 v1.5 patch). On subsequent calls,
    # appends only a new version (state preserved across version changes
    # since states are keyed to breaker identity, not version).
    # Returns (cb_id, cb_version_id).
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION risk.upsert_circuit_breaker(
            p_portfolio_id      BIGINT,
            p_strategy_id       BIGINT,
            p_cb_name           TEXT,
            p_risk_environment  TEXT,
            p_action            TEXT,
            p_throttle_params   JSONB,
            p_applies_in_regimes TEXT[],
            p_effective_at      TIMESTAMPTZ,
            p_idempotency_key   TEXT,
            p_config_metadata   JSONB,
            p_created_by        TEXT
        ) RETURNS TABLE(cb_id BIGINT, cb_version_id BIGINT)
        LANGUAGE plpgsql AS $$
        DECLARE
            v_cb_id BIGINT;
            v_cb_version_id BIGINT;
            v_existing_version_id BIGINT;
            v_max_existing_effective_at TIMESTAMPTZ;
            v_was_created BOOLEAN := false;
        BEGIN
            -- Argument validation
            IF p_portfolio_id IS NULL OR p_cb_name IS NULL OR p_risk_environment IS NULL
               OR p_action IS NULL OR p_applies_in_regimes IS NULL
               OR p_effective_at IS NULL OR p_idempotency_key IS NULL
               OR p_created_by IS NULL THEN
                RAISE EXCEPTION 'risk.upsert_circuit_breaker: required arguments must be non-NULL';
            END IF;
            IF LENGTH(TRIM(p_cb_name)) = 0 OR LENGTH(TRIM(p_idempotency_key)) = 0
               OR LENGTH(TRIM(p_created_by)) = 0 THEN
                RAISE EXCEPTION 'risk.upsert_circuit_breaker: cb_name, idempotency_key, created_by must be non-empty';
            END IF;
            IF p_action = 'throttle' AND p_throttle_params IS NULL THEN
                RAISE EXCEPTION 'risk.upsert_circuit_breaker: action=throttle requires throttle_params';
            END IF;
            IF p_action <> 'throttle' AND p_throttle_params IS NOT NULL THEN
                RAISE EXCEPTION 'risk.upsert_circuit_breaker: throttle_params only valid when action=throttle, got action=%', p_action;
            END IF;
            IF cardinality(p_applies_in_regimes) = 0 THEN
                RAISE EXCEPTION 'risk.upsert_circuit_breaker: applies_in_regimes must be non-empty';
            END IF;

            -- Insert-or-find logical row
            PERFORM set_config('risk.allow_cb_insert', 'on', true);
            BEGIN
                INSERT INTO risk.circuit_breakers (
                    portfolio_id, strategy_id, cb_name, risk_environment, created_by
                ) VALUES (
                    p_portfolio_id, p_strategy_id, p_cb_name, p_risk_environment, p_created_by
                ) RETURNING id INTO v_cb_id;
                v_was_created := true;
            EXCEPTION WHEN unique_violation THEN
                SELECT id INTO v_cb_id
                FROM risk.circuit_breakers
                WHERE portfolio_id = p_portfolio_id
                  AND strategy_id IS NOT DISTINCT FROM p_strategy_id
                  AND cb_name = p_cb_name
                  AND risk_environment = p_risk_environment;
                v_was_created := false;
            END;
            PERFORM set_config('risk.allow_cb_insert', 'off', true);

            -- Idempotent version-insert
            SELECT id INTO v_existing_version_id
            FROM risk.circuit_breaker_versions
            WHERE circuit_breaker_id = v_cb_id AND idempotency_key = p_idempotency_key;
            IF v_existing_version_id IS NOT NULL THEN
                RETURN QUERY SELECT v_cb_id, v_existing_version_id;
                RETURN;
            END IF;

            -- Monotonic effective_at
            SELECT MAX(effective_at) INTO v_max_existing_effective_at
            FROM risk.circuit_breaker_versions
            WHERE circuit_breaker_id = v_cb_id;
            IF v_max_existing_effective_at IS NOT NULL
               AND p_effective_at < v_max_existing_effective_at THEN
                RAISE EXCEPTION 'risk.upsert_circuit_breaker: effective_at % is before latest version effective_at % for breaker %; versions must be monotonically non-decreasing',
                    p_effective_at, v_max_existing_effective_at, v_cb_id;
            END IF;

            -- Insert version row
            PERFORM set_config('risk.allow_cb_version_insert', 'on', true);
            BEGIN
                INSERT INTO risk.circuit_breaker_versions (
                    circuit_breaker_id, action, throttle_params,
                    applies_in_regimes, effective_at,
                    idempotency_key, config_metadata, created_by
                ) VALUES (
                    v_cb_id, p_action, p_throttle_params,
                    p_applies_in_regimes, p_effective_at,
                    p_idempotency_key, COALESCE(p_config_metadata, '{}'::jsonb), p_created_by
                ) RETURNING id INTO v_cb_version_id;
            EXCEPTION WHEN unique_violation THEN
                SELECT id INTO v_cb_version_id
                FROM risk.circuit_breaker_versions
                WHERE circuit_breaker_id = v_cb_id AND idempotency_key = p_idempotency_key;
            END;
            PERFORM set_config('risk.allow_cb_version_insert', 'off', true);

            -- On first creation only: insert initial 'armed' state row (R5 v1.5)
            IF v_was_created THEN
                PERFORM set_config('risk.allow_cb_state_insert', 'on', true);
                BEGIN
                    INSERT INTO risk.circuit_breaker_states (
                        circuit_breaker_id, state, state_transitioned_at,
                        triggering_evaluation_id, transition_reason,
                        state_metadata, idempotency_key, created_by
                    ) VALUES (
                        v_cb_id, 'armed', p_effective_at,
                        NULL, 'initial_arm',
                        '{}'::jsonb,
                        'initial_arm:' || p_idempotency_key,
                        p_created_by
                    );
                EXCEPTION WHEN unique_violation THEN
                    -- Concurrent initial-arm race; one other caller won. Fine.
                    NULL;
                END;
                PERFORM set_config('risk.allow_cb_state_insert', 'off', true);
            END IF;

            RETURN QUERY SELECT v_cb_id, v_cb_version_id;
        END;
        $$;
    """)

    # ─────────────────────────────────────────────────────────────────────
    # FUNCTION: risk.record_regime_transition
    #
    # LIVE chronology guard (R-round-2a): in LIVE, p_transitioned_at must
    # be >= MAX(transitioned_at) for the same (portfolio_id, strategy_id,
    # risk_environment) scope. Backdated regime transitions are rejected
    # in LIVE because they retroactively change `current_regime` semantics
    # for evaluations that already executed against the prior regime,
    # violating the v1.1 R1 "retroactive-insert policy for regimes" rule.
    # REPLAY/SHADOW/BACKTEST allow backdating (research / replay / what-if).
    #
    # Idempotency-on-retry preserved: if the existing row matches the
    # (scope + idempotency_key) UNIQUE before the chronology check fires,
    # we return the existing id without re-checking chronology. (The
    # chronology check happens for genuinely-new inserts only.)
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION risk.record_regime_transition(
            p_portfolio_id     BIGINT,
            p_strategy_id      BIGINT,
            p_regime           TEXT,
            p_risk_environment TEXT,
            p_transitioned_at  TIMESTAMPTZ,
            p_idempotency_key  TEXT,
            p_transition_metadata JSONB,
            p_created_by       TEXT
        ) RETURNS BIGINT
        LANGUAGE plpgsql AS $$
        DECLARE
            v_transition_id BIGINT;
            v_existing_id BIGINT;
            v_max_existing_transitioned_at TIMESTAMPTZ;
        BEGIN
            IF p_portfolio_id IS NULL OR p_regime IS NULL OR p_risk_environment IS NULL
               OR p_transitioned_at IS NULL OR p_idempotency_key IS NULL
               OR p_created_by IS NULL THEN
                RAISE EXCEPTION 'risk.record_regime_transition: required arguments must be non-NULL';
            END IF;
            IF LENGTH(TRIM(p_idempotency_key)) = 0 OR LENGTH(TRIM(p_created_by)) = 0 THEN
                RAISE EXCEPTION 'risk.record_regime_transition: idempotency_key and created_by must be non-empty';
            END IF;

            -- Idempotent on (portfolio_id, strategy_id, risk_environment, idempotency_key).
            -- Check this BEFORE the chronology guard so retries don't fail on
            -- "your transition is now older than the latest" simply because the
            -- caller is retrying after other transitions landed.
            SELECT id INTO v_existing_id
            FROM risk.regime_transitions
            WHERE portfolio_id = p_portfolio_id
              AND strategy_id IS NOT DISTINCT FROM p_strategy_id
              AND risk_environment = p_risk_environment
              AND idempotency_key = p_idempotency_key;
            IF v_existing_id IS NOT NULL THEN
                RETURN v_existing_id;
            END IF;

            -- LIVE chronology guard (v1.1 R1 retroactive-insert policy).
            -- Reject backdated transitions in LIVE only.
            IF p_risk_environment = 'LIVE' THEN
                SELECT MAX(transitioned_at) INTO v_max_existing_transitioned_at
                FROM risk.regime_transitions
                WHERE portfolio_id = p_portfolio_id
                  AND strategy_id IS NOT DISTINCT FROM p_strategy_id
                  AND risk_environment = 'LIVE';

                IF v_max_existing_transitioned_at IS NOT NULL
                   AND p_transitioned_at < v_max_existing_transitioned_at THEN
                    RAISE EXCEPTION
                        'risk.record_regime_transition: LIVE backdated transition rejected. '
                        'p_transitioned_at=% is before latest existing transition at % '
                        'for (portfolio_id=%, strategy_id=%, env=LIVE). '
                        'LIVE regime transitions must be monotonically non-decreasing in transitioned_at.',
                        p_transitioned_at, v_max_existing_transitioned_at,
                        p_portfolio_id, p_strategy_id;
                END IF;
            END IF;

            PERFORM set_config('risk.allow_regime_transition_insert', 'on', true);
            BEGIN
                INSERT INTO risk.regime_transitions (
                    portfolio_id, strategy_id, regime, risk_environment,
                    transitioned_at, idempotency_key, transition_metadata, created_by
                ) VALUES (
                    p_portfolio_id, p_strategy_id, p_regime, p_risk_environment,
                    p_transitioned_at, p_idempotency_key,
                    COALESCE(p_transition_metadata, '{}'::jsonb), p_created_by
                ) RETURNING id INTO v_transition_id;
            EXCEPTION WHEN unique_violation THEN
                -- Concurrent insert with same idempotency key; find and return.
                SELECT id INTO v_transition_id
                FROM risk.regime_transitions
                WHERE portfolio_id = p_portfolio_id
                  AND strategy_id IS NOT DISTINCT FROM p_strategy_id
                  AND risk_environment = p_risk_environment
                  AND idempotency_key = p_idempotency_key;
            END;
            PERFORM set_config('risk.allow_regime_transition_insert', 'off', true);

            RETURN v_transition_id;
        END;
        $$;
    """)

    # ─────────────────────────────────────────────────────────────────────
    # FUNCTION: risk.set_circuit_breaker_state
    # Append-only state writer; FSM enforced by trigger (TRIGGER FN 15).
    # Used for manual transitions (operator action) and by evaluate_action
    # (round 2b) for trip transitions from CB-active evaluations.
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION risk.set_circuit_breaker_state(
            p_circuit_breaker_id    BIGINT,
            p_state                 TEXT,
            p_state_transitioned_at TIMESTAMPTZ,
            p_triggering_evaluation_id BIGINT,
            p_transition_reason     TEXT,
            p_state_metadata        JSONB,
            p_idempotency_key       TEXT,
            p_created_by            TEXT
        ) RETURNS BIGINT
        LANGUAGE plpgsql AS $$
        DECLARE
            v_state_id BIGINT;
            v_existing_id BIGINT;
        BEGIN
            IF p_circuit_breaker_id IS NULL OR p_state IS NULL
               OR p_state_transitioned_at IS NULL OR p_idempotency_key IS NULL
               OR p_created_by IS NULL THEN
                RAISE EXCEPTION 'risk.set_circuit_breaker_state: required arguments must be non-NULL';
            END IF;
            IF LENGTH(TRIM(p_idempotency_key)) = 0 OR LENGTH(TRIM(p_created_by)) = 0 THEN
                RAISE EXCEPTION 'risk.set_circuit_breaker_state: idempotency_key and created_by must be non-empty';
            END IF;

            -- Idempotent on (circuit_breaker_id, idempotency_key)
            SELECT id INTO v_existing_id
            FROM risk.circuit_breaker_states
            WHERE circuit_breaker_id = p_circuit_breaker_id
              AND idempotency_key = p_idempotency_key;
            IF v_existing_id IS NOT NULL THEN
                RETURN v_existing_id;
            END IF;

            PERFORM set_config('risk.allow_cb_state_insert', 'on', true);
            BEGIN
                INSERT INTO risk.circuit_breaker_states (
                    circuit_breaker_id, state, state_transitioned_at,
                    triggering_evaluation_id, transition_reason,
                    state_metadata, idempotency_key, created_by
                ) VALUES (
                    p_circuit_breaker_id, p_state, p_state_transitioned_at,
                    p_triggering_evaluation_id, p_transition_reason,
                    COALESCE(p_state_metadata, '{}'::jsonb), p_idempotency_key, p_created_by
                ) RETURNING id INTO v_state_id;
            EXCEPTION WHEN unique_violation THEN
                SELECT id INTO v_state_id
                FROM risk.circuit_breaker_states
                WHERE circuit_breaker_id = p_circuit_breaker_id
                  AND idempotency_key = p_idempotency_key;
            END;
            PERFORM set_config('risk.allow_cb_state_insert', 'off', true);

            RETURN v_state_id;
        END;
        $$;
    """)

    # =====================================================================
    # READ HELPERS
    # =====================================================================

    # ─────────────────────────────────────────────────────────────────────
    # FUNCTION: risk.resolve_active_limit_versions
    # Returns the latest applicable limit version for each limit matching
    # the (portfolio, strategy, account, instrument, environment) scope at
    # the given as_of_at. "Active" = effective_at <= as_of_at, latest by
    # effective_at DESC, id DESC.
    # All-applicable resolution (R1 v1.1): returns one row per matching
    # logical limit, even across overlapping scopes.
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION risk.resolve_active_limit_versions(
            p_portfolio_id     BIGINT,
            p_strategy_id      BIGINT,
            p_account_id       BIGINT,
            p_instrument_id    BIGINT,
            p_risk_environment TEXT,
            p_as_of_at         TIMESTAMPTZ
        ) RETURNS TABLE (
            limit_id BIGINT,
            limit_version_id BIGINT,
            dimension TEXT,
            scope TEXT,
            limit_value NUMERIC,
            blocking BOOLEAN,
            nav_staleness_bound_seconds INTEGER,
            effective_at TIMESTAMPTZ
        )
        LANGUAGE sql STABLE AS $$
            SELECT
                l.id              AS limit_id,
                lv.id             AS limit_version_id,
                l.dimension,
                l.scope,
                lv.limit_value,
                lv.blocking,
                lv.nav_staleness_bound_seconds,
                lv.effective_at
            FROM risk.limits l
            JOIN LATERAL (
                SELECT lvi.id, lvi.limit_value, lvi.blocking,
                       lvi.nav_staleness_bound_seconds, lvi.effective_at
                FROM risk.limit_versions lvi
                WHERE lvi.limit_id = l.id
                  AND lvi.effective_at <= p_as_of_at
                ORDER BY lvi.effective_at DESC, lvi.id DESC
                LIMIT 1
            ) lv ON true
            WHERE l.risk_environment = p_risk_environment
              AND l.portfolio_id = p_portfolio_id
              -- Scope-matching: a limit is applicable when its populated
              -- scope keys are a subset of the action's scope keys.
              AND (l.strategy_id IS NULL    OR l.strategy_id    = p_strategy_id)
              AND (l.account_id IS NULL     OR l.account_id     = p_account_id)
              AND (l.instrument_id IS NULL  OR l.instrument_id  = p_instrument_id);
        $$;
    """)

    # ─────────────────────────────────────────────────────────────────────
    # FUNCTION: risk.resolve_active_circuit_breakers
    # Returns active CB versions for a given scope, including each CB's
    # latest state. Filters by applies_in_regimes if a regime is provided.
    # Centralizes the (state_transitioned_at DESC, id DESC) lookup so
    # evaluate_action and operator tooling share the same definition of
    # "current state".
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION risk.resolve_active_circuit_breakers(
            p_portfolio_id     BIGINT,
            p_strategy_id      BIGINT,
            p_risk_environment TEXT,
            p_as_of_at         TIMESTAMPTZ
        ) RETURNS TABLE (
            cb_id BIGINT,
            cb_version_id BIGINT,
            cb_name TEXT,
            action TEXT,
            throttle_params JSONB,
            applies_in_regimes TEXT[],
            current_state TEXT,
            current_state_transitioned_at TIMESTAMPTZ
        )
        LANGUAGE sql STABLE AS $$
            SELECT
                cb.id                           AS cb_id,
                cv.id                           AS cb_version_id,
                cb.cb_name,
                cv.action,
                cv.throttle_params,
                cv.applies_in_regimes,
                cs.state                        AS current_state,
                cs.state_transitioned_at        AS current_state_transitioned_at
            FROM risk.circuit_breakers cb
            JOIN LATERAL (
                SELECT cvi.id, cvi.action, cvi.throttle_params, cvi.applies_in_regimes
                FROM risk.circuit_breaker_versions cvi
                WHERE cvi.circuit_breaker_id = cb.id
                  AND cvi.effective_at <= p_as_of_at
                ORDER BY cvi.effective_at DESC, cvi.id DESC
                LIMIT 1
            ) cv ON true
            JOIN LATERAL (
                SELECT csi.state, csi.state_transitioned_at
                FROM risk.circuit_breaker_states csi
                WHERE csi.circuit_breaker_id = cb.id
                  AND csi.state_transitioned_at <= p_as_of_at
                ORDER BY csi.state_transitioned_at DESC, csi.id DESC
                LIMIT 1
            ) cs ON true
            WHERE cb.risk_environment = p_risk_environment
              AND cb.portfolio_id = p_portfolio_id
              AND (cb.strategy_id IS NULL OR cb.strategy_id = p_strategy_id);
        $$;
    """)

    # ─────────────────────────────────────────────────────────────────────
    # FUNCTION: risk.current_regime
    # Returns the latest regime transition for a scope at p_as_of_at,
    # or no rows if no regime has been recorded.
    #
    # TWO-STAGE STRATEGY OVERRIDE (R-round-2a):
    # Strategy-specific regime rows override portfolio-level fallback rows.
    # Resolution:
    #   1. If p_strategy_id IS NOT NULL, look for latest
    #      (portfolio_id=X, strategy_id=Y, env=Z, transitioned_at<=as_of_at).
    #   2. If none found (or p_strategy_id IS NULL), fall back to latest
    #      (portfolio_id=X, strategy_id IS NULL, env=Z, transitioned_at<=as_of_at).
    # This preserves the structural contract from v1.3 R3:
    #   "regime scope = portfolio NOT NULL + strategy NULLABLE",
    # interpreted as specific-wins-over-general (not "latest of either").
    #
    # Ordering within each stage: (transitioned_at DESC, id DESC).
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION risk.current_regime(
            p_portfolio_id     BIGINT,
            p_strategy_id      BIGINT,
            p_risk_environment TEXT,
            p_as_of_at         TIMESTAMPTZ
        ) RETURNS TABLE (
            regime_transition_id BIGINT,
            regime TEXT,
            transitioned_at TIMESTAMPTZ,
            resolved_via TEXT  -- 'strategy' | 'portfolio_fallback'
        )
        LANGUAGE plpgsql STABLE AS $$
        DECLARE
            v_id BIGINT;
            v_regime TEXT;
            v_transitioned_at TIMESTAMPTZ;
        BEGIN
            -- Stage 1: strategy-specific lookup (only if strategy provided)
            IF p_strategy_id IS NOT NULL THEN
                SELECT rt.id, rt.regime, rt.transitioned_at
                  INTO v_id, v_regime, v_transitioned_at
                FROM risk.regime_transitions rt
                WHERE rt.portfolio_id = p_portfolio_id
                  AND rt.strategy_id = p_strategy_id
                  AND rt.risk_environment = p_risk_environment
                  AND rt.transitioned_at <= p_as_of_at
                ORDER BY rt.transitioned_at DESC, rt.id DESC
                LIMIT 1;

                IF v_id IS NOT NULL THEN
                    RETURN QUERY SELECT v_id, v_regime, v_transitioned_at, 'strategy'::TEXT;
                    RETURN;
                END IF;
            END IF;

            -- Stage 2: portfolio-level fallback (strategy_id IS NULL rows)
            SELECT rt.id, rt.regime, rt.transitioned_at
              INTO v_id, v_regime, v_transitioned_at
            FROM risk.regime_transitions rt
            WHERE rt.portfolio_id = p_portfolio_id
              AND rt.strategy_id IS NULL
              AND rt.risk_environment = p_risk_environment
              AND rt.transitioned_at <= p_as_of_at
            ORDER BY rt.transitioned_at DESC, rt.id DESC
            LIMIT 1;

            IF v_id IS NOT NULL THEN
                RETURN QUERY SELECT v_id, v_regime, v_transitioned_at, 'portfolio_fallback'::TEXT;
                RETURN;
            END IF;

            -- No match: return zero rows
            RETURN;
        END;
        $$;
    """)


def downgrade() -> None:
    # ─────────────────────────────────────────────────────────────────────
    # Drop triggers (reverse order)
    # ─────────────────────────────────────────────────────────────────────
    op.execute("DROP TRIGGER IF EXISTS cb_states_a_insert_gate ON risk.circuit_breaker_states;")
    op.execute("DROP TRIGGER IF EXISTS cb_states_b_fsm ON risk.circuit_breaker_states;")
    op.execute("DROP TRIGGER IF EXISTS cb_states_c_append_only ON risk.circuit_breaker_states;")
    op.execute("DROP TRIGGER IF EXISTS cb_versions_a_insert_gate ON risk.circuit_breaker_versions;")
    op.execute("DROP TRIGGER IF EXISTS cb_versions_b_append_only ON risk.circuit_breaker_versions;")
    op.execute("DROP TRIGGER IF EXISTS circuit_breakers_a_insert_gate ON risk.circuit_breakers;")
    op.execute("DROP TRIGGER IF EXISTS circuit_breakers_b_identity_immutable ON risk.circuit_breakers;")
    op.execute("DROP TRIGGER IF EXISTS evaluation_limit_results_a_append_only ON risk.evaluation_limit_results;")
    op.execute("DROP TRIGGER IF EXISTS evaluation_inputs_a_append_only ON risk.evaluation_inputs;")
    op.execute("DROP TRIGGER IF EXISTS evaluations_a_append_only ON risk.evaluations;")
    op.execute("DROP TRIGGER IF EXISTS regime_transitions_a_insert_gate ON risk.regime_transitions;")
    op.execute("DROP TRIGGER IF EXISTS regime_transitions_b_append_only ON risk.regime_transitions;")
    op.execute("DROP TRIGGER IF EXISTS limit_versions_a_insert_gate ON risk.limit_versions;")
    op.execute("DROP TRIGGER IF EXISTS limit_versions_b_append_only ON risk.limit_versions;")
    op.execute("DROP TRIGGER IF EXISTS limits_a_insert_gate ON risk.limits;")
    op.execute("DROP TRIGGER IF EXISTS limits_b_identity_immutable ON risk.limits;")

    # ─────────────────────────────────────────────────────────────────────
    # Drop functions (read helpers, controlled writers, trigger functions)
    # ─────────────────────────────────────────────────────────────────────
    op.execute("DROP FUNCTION IF EXISTS risk.current_regime(BIGINT, BIGINT, TEXT, TIMESTAMPTZ);")
    op.execute("DROP FUNCTION IF EXISTS risk.resolve_active_circuit_breakers(BIGINT, BIGINT, TEXT, TIMESTAMPTZ);")
    op.execute("DROP FUNCTION IF EXISTS risk.resolve_active_limit_versions(BIGINT, BIGINT, BIGINT, BIGINT, TEXT, TIMESTAMPTZ);")
    op.execute("DROP FUNCTION IF EXISTS risk.set_circuit_breaker_state(BIGINT, TEXT, TIMESTAMPTZ, BIGINT, TEXT, JSONB, TEXT, TEXT);")
    op.execute("DROP FUNCTION IF EXISTS risk.record_regime_transition(BIGINT, BIGINT, TEXT, TEXT, TIMESTAMPTZ, TEXT, JSONB, TEXT);")
    op.execute("DROP FUNCTION IF EXISTS risk.upsert_circuit_breaker(BIGINT, BIGINT, TEXT, TEXT, TEXT, JSONB, TEXT[], TIMESTAMPTZ, TEXT, JSONB, TEXT);")
    op.execute("DROP FUNCTION IF EXISTS risk.upsert_limit(BIGINT, BIGINT, BIGINT, BIGINT, TEXT, TEXT, TEXT, NUMERIC, BOOLEAN, INTEGER, TIMESTAMPTZ, TEXT, JSONB, TEXT);")

    op.execute("DROP FUNCTION IF EXISTS risk.enforce_cb_state_fsm();")
    op.execute("DROP FUNCTION IF EXISTS risk.enforce_cb_state_insert_gate();")
    op.execute("DROP FUNCTION IF EXISTS risk.enforce_cb_state_append_only();")
    op.execute("DROP FUNCTION IF EXISTS risk.enforce_cb_version_insert_gate();")
    op.execute("DROP FUNCTION IF EXISTS risk.enforce_cb_version_append_only();")
    op.execute("DROP FUNCTION IF EXISTS risk.enforce_circuit_breaker_insert_gate();")
    op.execute("DROP FUNCTION IF EXISTS risk.enforce_circuit_breaker_identity_immutable();")
    op.execute("DROP FUNCTION IF EXISTS risk.enforce_evaluation_limit_results_append_only();")
    op.execute("DROP FUNCTION IF EXISTS risk.enforce_evaluation_inputs_append_only();")
    op.execute("DROP FUNCTION IF EXISTS risk.enforce_evaluations_append_only();")
    op.execute("DROP FUNCTION IF EXISTS risk.enforce_regime_transitions_insert_gate();")
    op.execute("DROP FUNCTION IF EXISTS risk.enforce_regime_transitions_append_only();")
    op.execute("DROP FUNCTION IF EXISTS risk.enforce_limit_version_insert_gate();")
    op.execute("DROP FUNCTION IF EXISTS risk.enforce_limit_version_append_only();")
    op.execute("DROP FUNCTION IF EXISTS risk.enforce_limit_insert_gate();")
    op.execute("DROP FUNCTION IF EXISTS risk.enforce_limit_identity_immutable();")

    # ─────────────────────────────────────────────────────────────────────
    # Drop tables (reverse FK dependency order)
    # ─────────────────────────────────────────────────────────────────────
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
