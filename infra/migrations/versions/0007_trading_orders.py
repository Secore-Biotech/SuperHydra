"""trading_orders

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-04

OMS persistence layer (v5.2-final) — 8 tables, 31 controlled+helper+trigger functions.

Foundational principle: Every column on trading.orders that represents
execution truth (state, fills, ack, reject, errors, timestamps) is
mutable only through a controlled function path with the appropriate
session flag. Direct UPDATE statements from application code are
rejected (under the privilege assumption stated below).

State-target ownership rule:
  submitted              -> transition_order_state (after reservation + active submit outbox)
  working                -> record_order_ack (sole path; ack must precede fill in Phase 1)
  partially_filled       -> process_fill_update_order
  filled                 -> process_fill_update_order
  cancel_requested       -> transition_order_state
  canceled (from pending_submit)              -> transition_order_state
  canceled (from submitted/working/partial)   -> process_cancel_update_order
  rejected               -> record_order_reject
  failed_submit          -> record_order_failed_submit
  expired                -> transition_order_state (reconciler/SLA)
  stale/unknown          -> transition_order_state

Phase 1 ack-before-fill assumption (v5.2):
  An order's first state transition out of 'submitted' is to 'working'
  via record_order_ack (venue acknowledgment), NOT directly to
  partially_filled/filled. process_fill_update_order rejects fills
  against orders in pending_submit or submitted state.

Cancel-before-ack (v5.2-final):
  A confirmed cancel event from the venue can arrive before the ack.
  The FSM 'submitted' branch therefore allows
  ('working', 'rejected', 'canceled', 'stale_needs_reconciliation').
  The cancel path is process_cancel_update_order.

Approved by external reviewer on 2026-05-04 (round 7).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # =====================================================================
    # TABLE 1: trading.order_intents
    # =====================================================================
    op.execute("""
        CREATE TABLE trading.order_intents (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            intent_uuid UUID NOT NULL DEFAULT gen_uuidv7() UNIQUE,
            allocator_run_id UUID NOT NULL REFERENCES registry.allocator_runs(id),
            target_weight_id UUID REFERENCES registry.target_weights(id),
            strategy_id BIGINT NOT NULL REFERENCES registry.strategies(id),
            portfolio_id BIGINT NOT NULL REFERENCES registry.portfolios(id),
            account_id BIGINT NOT NULL REFERENCES registry.accounts(id),
            instrument_id BIGINT NOT NULL REFERENCES registry.instruments(id),
            venue_id BIGINT NOT NULL REFERENCES registry.venues(id),
            venue_namespace TEXT NOT NULL,

            side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
            target_quantity NUMERIC(38,18) NOT NULL CHECK (target_quantity > 0),
            target_value_usd NUMERIC(38,12) NOT NULL CHECK (target_value_usd > 0),
            intent_type TEXT NOT NULL CHECK (intent_type IN (
                'open', 'close', 'rebalance', 'hedge', 'manual_override'
            )),
            urgency TEXT NOT NULL CHECK (urgency IN (
                'passive', 'normal', 'aggressive', 'urgent'
            )),
            execution_environment TEXT NOT NULL CHECK (execution_environment IN (
                'SHADOW', 'CANARY', 'SCALE'
            )),
            created_via TEXT NOT NULL CHECK (created_via IN (
                'strategy', 'allocator', 'manual', 'repl', 'system'
            )),

            constraints_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            intended_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CHECK (LENGTH(TRIM(venue_namespace)) > 0),
            CHECK (LENGTH(TRIM(created_by)) > 0),
            CHECK (jsonb_typeof(constraints_metadata) = 'object')
        );
    """)

    op.execute("""
        CREATE INDEX idx_order_intents_allocator_run
            ON trading.order_intents(allocator_run_id);
        CREATE INDEX idx_order_intents_strategy
            ON trading.order_intents(strategy_id, intended_at DESC);
        CREATE INDEX idx_order_intents_portfolio
            ON trading.order_intents(portfolio_id, intended_at DESC);
        CREATE INDEX idx_order_intents_venue
            ON trading.order_intents(venue_id, intended_at DESC);
    """)

    # =====================================================================
    # TABLE 2: trading.order_groups
    # =====================================================================
    op.execute("""
        CREATE TABLE trading.order_groups (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            group_uuid UUID NOT NULL DEFAULT gen_uuidv7() UNIQUE,
            portfolio_id BIGINT NOT NULL REFERENCES registry.portfolios(id),
            strategy_id BIGINT REFERENCES registry.strategies(id),
            group_type TEXT NOT NULL CHECK (group_type IN (
                'pair_trade', 'basket', 'iceberg_parent', 'twap_parent', 'oco', 'manual'
            )),
            group_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (LENGTH(TRIM(created_by)) > 0),
            CHECK (jsonb_typeof(group_metadata) = 'object')
        );
    """)

    # =====================================================================
    # TABLE 3: trading.order_reservations
    # =====================================================================
    op.execute("""
        CREATE TABLE trading.order_reservations (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            intent_id BIGINT NOT NULL REFERENCES trading.order_intents(id),
            account_id BIGINT NOT NULL REFERENCES registry.accounts(id),
            asset_id BIGINT NOT NULL REFERENCES registry.assets(id),
            reservation_type TEXT NOT NULL CHECK (reservation_type IN (
                'cash', 'margin_initial', 'borrowed_funds'
            )),
            amount_reserved NUMERIC(38,18) NOT NULL CHECK (amount_reserved > 0),
            amount_released NUMERIC(38,18) NOT NULL DEFAULT 0 CHECK (amount_released >= 0),
            reserved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            released_at TIMESTAMPTZ,
            released_by TEXT,
            release_reason TEXT,
            CHECK (
                (amount_released = 0
                 AND released_at IS NULL
                 AND released_by IS NULL
                 AND release_reason IS NULL)
                OR
                (amount_released = amount_reserved
                 AND released_at IS NOT NULL
                 AND released_by IS NOT NULL AND LENGTH(TRIM(released_by)) > 0
                 AND release_reason IS NOT NULL AND LENGTH(TRIM(release_reason)) > 0)
            ),
            UNIQUE (intent_id, asset_id, reservation_type)
        );
    """)

    op.execute("""
        CREATE INDEX idx_reservations_intent ON trading.order_reservations(intent_id);
        CREATE INDEX idx_reservations_account ON trading.order_reservations(account_id, reserved_at DESC);
        CREATE INDEX idx_reservations_active
            ON trading.order_reservations(intent_id) WHERE released_at IS NULL;
    """)

    # =====================================================================
    # TABLE 4: trading.orders
    # =====================================================================
    op.execute("""
        CREATE TABLE trading.orders (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            order_uuid UUID NOT NULL DEFAULT gen_uuidv7() UNIQUE,
            intent_id BIGINT NOT NULL UNIQUE REFERENCES trading.order_intents(id),
            order_group_id BIGINT REFERENCES trading.order_groups(id),
            account_id BIGINT NOT NULL REFERENCES registry.accounts(id),
            instrument_id BIGINT NOT NULL REFERENCES registry.instruments(id),
            venue_id BIGINT NOT NULL REFERENCES registry.venues(id),
            venue_namespace TEXT NOT NULL,

            client_order_id TEXT NOT NULL UNIQUE,
            venue_order_id TEXT,

            side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
            order_type TEXT NOT NULL CHECK (order_type IN (
                'market', 'limit', 'stop_market', 'stop_limit'
            )),
            post_only BOOLEAN NOT NULL DEFAULT FALSE,
            reduce_only BOOLEAN NOT NULL DEFAULT FALSE,

            quantity NUMERIC(38,18) NOT NULL CHECK (quantity > 0),
            price NUMERIC(38,18) CHECK (price IS NULL OR price > 0),
            stop_price NUMERIC(38,18) CHECK (stop_price IS NULL OR stop_price > 0),
            time_in_force TEXT NOT NULL CHECK (time_in_force IN ('gtc', 'ioc', 'fok', 'gtd')),
            expires_at TIMESTAMPTZ,

            state TEXT NOT NULL DEFAULT 'pending_submit' CHECK (state IN (
                'pending_submit', 'submitted', 'working',
                'partially_filled', 'filled',
                'cancel_requested', 'canceled',
                'rejected', 'expired', 'failed_submit',
                'stale_needs_reconciliation', 'unknown'
            )),

            filled_quantity NUMERIC(38,18) NOT NULL DEFAULT 0 CHECK (filled_quantity >= 0),
            avg_fill_price NUMERIC(38,18),

            submitted_at TIMESTAMPTZ,
            venue_acknowledged_at TIMESTAMPTZ,
            terminal_at TIMESTAMPTZ,

            rejection_reason TEXT,
            submission_error TEXT,
            raw_ack_payload JSONB,
            raw_reject_payload JSONB,

            created_via TEXT NOT NULL CHECK (created_via IN (
                'strategy', 'allocator', 'manual', 'repl', 'system'
            )),
            created_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CHECK (filled_quantity <= quantity),
            CHECK (
                (order_type IN ('limit', 'stop_limit') AND price IS NOT NULL)
                OR (order_type IN ('market', 'stop_market') AND price IS NULL)
            ),
            CHECK (
                (order_type IN ('stop_market', 'stop_limit') AND stop_price IS NOT NULL)
                OR (order_type NOT IN ('stop_market', 'stop_limit') AND stop_price IS NULL)
            ),
            CHECK (NOT post_only OR order_type IN ('limit', 'stop_limit')),
            CHECK (
                (time_in_force = 'gtd' AND expires_at IS NOT NULL)
                OR (time_in_force != 'gtd' AND expires_at IS NULL)
            ),

            CHECK (
                state NOT IN ('submitted', 'working', 'partially_filled', 'filled',
                              'cancel_requested', 'expired', 'stale_needs_reconciliation', 'unknown')
                OR submitted_at IS NOT NULL
            ),
            CHECK (
                venue_order_id IS NULL OR venue_acknowledged_at IS NOT NULL
            ),
            CHECK (
                raw_ack_payload IS NULL OR venue_acknowledged_at IS NOT NULL
            ),

            CHECK (state != 'rejected' OR rejection_reason IS NOT NULL),
            CHECK (state != 'failed_submit' OR submission_error IS NOT NULL),

            CHECK (LENGTH(TRIM(client_order_id)) > 0),
            CHECK (LENGTH(TRIM(venue_namespace)) > 0),
            CHECK (rejection_reason IS NULL OR LENGTH(TRIM(rejection_reason)) > 0),
            CHECK (submission_error IS NULL OR LENGTH(TRIM(submission_error)) > 0),
            CHECK (LENGTH(TRIM(created_by)) > 0),
            CHECK (raw_ack_payload IS NULL OR jsonb_typeof(raw_ack_payload) = 'object'),
            CHECK (raw_reject_payload IS NULL OR jsonb_typeof(raw_reject_payload) = 'object')
        );
    """)

    op.execute("""
        CREATE INDEX idx_orders_intent ON trading.orders(intent_id);
        CREATE INDEX idx_orders_state ON trading.orders(state) WHERE state NOT IN (
            'filled', 'canceled', 'rejected', 'expired', 'failed_submit'
        );
        CREATE INDEX idx_orders_group ON trading.orders(order_group_id) WHERE order_group_id IS NOT NULL;
        CREATE INDEX idx_orders_venue_namespace
            ON trading.orders(venue_namespace, account_id, created_at DESC);
        CREATE UNIQUE INDEX uniq_orders_venue_order_id
            ON trading.orders(venue_namespace, account_id, venue_order_id)
            WHERE venue_order_id IS NOT NULL;
    """)

    # =====================================================================
    # TABLE 5: trading.order_state_events
    # =====================================================================
    op.execute("""
        CREATE TABLE trading.order_state_events (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            event_uuid UUID NOT NULL DEFAULT gen_uuidv7() UNIQUE,
            order_id BIGINT NOT NULL REFERENCES trading.orders(id),
            old_state TEXT NOT NULL,
            new_state TEXT NOT NULL,
            transition_reason TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_namespace TEXT NOT NULL,
            source_id TEXT,
            created_by TEXT NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (old_state <> new_state),
            CHECK (LENGTH(TRIM(transition_reason)) > 0),
            CHECK (LENGTH(TRIM(source_type)) > 0),
            CHECK (LENGTH(TRIM(source_namespace)) > 0),
            CHECK (source_id IS NULL OR LENGTH(TRIM(source_id)) > 0),
            CHECK (LENGTH(TRIM(created_by)) > 0),
            CHECK (jsonb_typeof(metadata) = 'object'),
            CHECK (old_state IN (
                'pending_submit', 'submitted', 'working',
                'partially_filled', 'filled',
                'cancel_requested', 'canceled',
                'rejected', 'expired', 'failed_submit',
                'stale_needs_reconciliation', 'unknown'
            )),
            CHECK (new_state IN (
                'pending_submit', 'submitted', 'working',
                'partially_filled', 'filled',
                'cancel_requested', 'canceled',
                'rejected', 'expired', 'failed_submit',
                'stale_needs_reconciliation', 'unknown'
            ))
        );
    """)

    op.execute("""
        CREATE INDEX idx_state_events_order
            ON trading.order_state_events(order_id, created_at DESC);
        CREATE INDEX idx_state_events_at
            ON trading.order_state_events(created_at DESC);
    """)

    # =====================================================================
    # TABLE 6: trading.fills
    # =====================================================================
    op.execute("""
        CREATE TABLE trading.fills (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            fill_uuid UUID NOT NULL DEFAULT gen_uuidv7() UNIQUE,
            order_id BIGINT NOT NULL REFERENCES trading.orders(id),
            instrument_id BIGINT NOT NULL REFERENCES registry.instruments(id),

            venue_fill_id TEXT NOT NULL,
            venue_namespace TEXT NOT NULL,

            side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
            quantity NUMERIC(38,18) NOT NULL CHECK (quantity > 0),
            price NUMERIC(38,18) NOT NULL CHECK (price > 0),
            notional_value NUMERIC(38,12) NOT NULL CHECK (notional_value > 0),

            liquidity_side TEXT CHECK (liquidity_side IN ('maker', 'taker', 'unknown')),

            fill_environment TEXT NOT NULL CHECK (fill_environment IN (
                'LIVE', 'SHADOW', 'REPLAY', 'BACKTEST'
            )),
            fill_settlement_type TEXT NOT NULL CHECK (fill_settlement_type IN (
                'CONFIRMED_SETTLED', 'MODELED_FILL', 'SIMULATED_FILL'
            )),

            filled_at TIMESTAMPTZ NOT NULL,
            received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            journal_id BIGINT REFERENCES accounting.journals(id),
            reconciled_at TIMESTAMPTZ,
            reconciled_by TEXT,

            raw_record_hash TEXT,
            raw_record JSONB NOT NULL,

            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CHECK (LENGTH(TRIM(venue_fill_id)) > 0),
            CHECK (LENGTH(TRIM(venue_namespace)) > 0),
            CHECK (raw_record_hash IS NULL OR LENGTH(TRIM(raw_record_hash)) > 0),
            CHECK (jsonb_typeof(raw_record) = 'object'),
            CHECK (
                (journal_id IS NULL AND reconciled_at IS NULL AND reconciled_by IS NULL)
                OR
                (journal_id IS NOT NULL AND reconciled_at IS NOT NULL
                 AND reconciled_by IS NOT NULL AND LENGTH(TRIM(reconciled_by)) > 0)
            ),
            CHECK (
                (fill_environment = 'LIVE' AND fill_settlement_type = 'CONFIRMED_SETTLED')
                OR (fill_environment = 'SHADOW' AND fill_settlement_type = 'MODELED_FILL')
                OR (fill_environment IN ('REPLAY', 'BACKTEST')
                    AND fill_settlement_type IN ('SIMULATED_FILL', 'MODELED_FILL'))
            ),
            UNIQUE (venue_namespace, venue_fill_id)
        );
    """)

    op.execute("""
        CREATE INDEX idx_fills_order ON trading.fills(order_id, filled_at DESC);
        CREATE INDEX idx_fills_at ON trading.fills(filled_at DESC);
        CREATE INDEX idx_fills_journal ON trading.fills(journal_id) WHERE journal_id IS NOT NULL;
        CREATE INDEX idx_fills_unreconciled
            ON trading.fills(received_at DESC) WHERE journal_id IS NULL;
    """)

    # =====================================================================
    # TABLE 7: trading.cancels
    # =====================================================================
    op.execute("""
        CREATE TABLE trading.cancels (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            order_id BIGINT NOT NULL REFERENCES trading.orders(id),

            venue_cancel_id TEXT,
            venue_namespace TEXT NOT NULL,

            source_type TEXT NOT NULL DEFAULT 'cancel_event',
            source_id TEXT NOT NULL,

            cancel_reason TEXT NOT NULL CHECK (cancel_reason IN (
                'user_requested', 'venue_initiated', 'expired',
                'replaced', 'risk_kill', 'system_shutdown'
            )),
            requested_at TIMESTAMPTZ,
            confirmed_at TIMESTAMPTZ NOT NULL,
            quantity_canceled NUMERIC(38,18) NOT NULL CHECK (quantity_canceled >= 0),
            raw_record JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (LENGTH(TRIM(venue_namespace)) > 0),
            CHECK (LENGTH(TRIM(source_type)) > 0),
            CHECK (LENGTH(TRIM(source_id)) > 0),
            CHECK (venue_cancel_id IS NULL OR LENGTH(TRIM(venue_cancel_id)) > 0),
            CHECK (jsonb_typeof(raw_record) = 'object'),
            UNIQUE (source_type, venue_namespace, source_id)
        );
    """)

    op.execute("""
        CREATE INDEX idx_cancels_order ON trading.cancels(order_id, confirmed_at DESC);
        CREATE INDEX idx_cancels_at ON trading.cancels(confirmed_at DESC);
    """)

    # =====================================================================
    # TABLE 8: trading.oms_outbox
    # =====================================================================
    op.execute("""
        CREATE TABLE trading.oms_outbox (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            order_id BIGINT NOT NULL REFERENCES trading.orders(id),
            operation TEXT NOT NULL CHECK (operation IN (
                'submit', 'cancel', 'amend', 'replace'
            )),
            operation_key TEXT NOT NULL UNIQUE,

            payload JSONB NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending' CHECK (state IN (
                'pending', 'in_flight', 'failed', 'succeeded', 'abandoned'
            )),
            attempts INT NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            max_attempts INT NOT NULL DEFAULT 5 CHECK (max_attempts > 0),
            last_error TEXT,
            next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMPTZ,
            CHECK (LENGTH(TRIM(operation_key)) > 0),
            CHECK (jsonb_typeof(payload) = 'object'),
            CHECK (last_error IS NULL OR LENGTH(TRIM(last_error)) > 0),
            CHECK (
                (state IN ('pending', 'in_flight', 'failed') AND completed_at IS NULL)
                OR (state IN ('succeeded', 'abandoned') AND completed_at IS NOT NULL)
            ),
            CHECK (attempts <= max_attempts)
        );
    """)

    op.execute("""
        CREATE INDEX idx_outbox_order ON trading.oms_outbox(order_id, created_at DESC);
        CREATE INDEX idx_outbox_state_attempt
            ON trading.oms_outbox(state, next_attempt_at)
            WHERE state IN ('pending', 'in_flight', 'failed');
        CREATE INDEX idx_outbox_completed
            ON trading.oms_outbox(completed_at DESC) WHERE completed_at IS NOT NULL;
        CREATE UNIQUE INDEX uniq_outbox_one_submit_per_order
            ON trading.oms_outbox(order_id) WHERE operation = 'submit';
        CREATE UNIQUE INDEX uniq_outbox_one_cancel_per_order
            ON trading.oms_outbox(order_id) WHERE operation = 'cancel';
    """)

    # =====================================================================
    # TRIGGER 1: order_intents lineage consistency
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION trading.enforce_intent_lineage_consistency()
        RETURNS TRIGGER AS $$
        DECLARE
            v_run_portfolio_id BIGINT;
            v_tw_allocator_run_id UUID;
            v_tw_instrument_id BIGINT;
            v_account_venue_id BIGINT;
            v_instrument_venue_id BIGINT;
        BEGIN
            SELECT portfolio_id INTO v_run_portfolio_id
            FROM registry.allocator_runs WHERE id = NEW.allocator_run_id;
            IF v_run_portfolio_id IS NULL THEN
                RAISE EXCEPTION 'allocator_run % does not exist', NEW.allocator_run_id;
            END IF;
            IF v_run_portfolio_id IS DISTINCT FROM NEW.portfolio_id THEN
                RAISE EXCEPTION
                    'order_intent.portfolio_id=% does not match allocator_run.portfolio_id=%',
                    NEW.portfolio_id, v_run_portfolio_id;
            END IF;
            IF NEW.target_weight_id IS NOT NULL THEN
                SELECT allocator_run_id, instrument_id
                INTO v_tw_allocator_run_id, v_tw_instrument_id
                FROM registry.target_weights WHERE id = NEW.target_weight_id;
                IF v_tw_allocator_run_id IS NULL THEN
                    RAISE EXCEPTION 'target_weight % does not exist', NEW.target_weight_id;
                END IF;
                IF v_tw_allocator_run_id IS DISTINCT FROM NEW.allocator_run_id THEN
                    RAISE EXCEPTION
                        'target_weight.allocator_run_id=% does not match intent.allocator_run_id=%',
                        v_tw_allocator_run_id, NEW.allocator_run_id;
                END IF;
                IF v_tw_instrument_id IS DISTINCT FROM NEW.instrument_id THEN
                    RAISE EXCEPTION
                        'target_weight.instrument_id=% does not match intent.instrument_id=%',
                        v_tw_instrument_id, NEW.instrument_id;
                END IF;
            END IF;
            SELECT venue_id INTO v_account_venue_id
            FROM registry.accounts WHERE id = NEW.account_id;
            IF v_account_venue_id IS DISTINCT FROM NEW.venue_id THEN
                RAISE EXCEPTION
                    'account.venue_id=% does not match intent.venue_id=%',
                    v_account_venue_id, NEW.venue_id;
            END IF;
            SELECT venue_id INTO v_instrument_venue_id
            FROM registry.instruments WHERE id = NEW.instrument_id;
            IF v_instrument_venue_id IS DISTINCT FROM NEW.venue_id THEN
                RAISE EXCEPTION
                    'instrument.venue_id=% does not match intent.venue_id=%',
                    v_instrument_venue_id, NEW.venue_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER order_intents_lineage_consistency
            BEFORE INSERT ON trading.order_intents
            FOR EACH ROW EXECUTE FUNCTION trading.enforce_intent_lineage_consistency();
    """)

    # =====================================================================
    # TRIGGER 2: Promotion gate
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION trading.enforce_order_intent_promotion()
        RETURNS TRIGGER AS $$
        DECLARE
            v_active_phase TEXT;
            v_required_phases TEXT[];
        BEGIN
            SELECT to_phase INTO v_active_phase
            FROM registry.promotions
            WHERE strategy_id = NEW.strategy_id AND revoked_at IS NULL
            ORDER BY promoted_at DESC LIMIT 1 FOR UPDATE;
            IF v_active_phase IS NULL THEN
                RAISE EXCEPTION
                    'No active promotion for strategy %; cannot create order intent', NEW.strategy_id;
            END IF;
            IF NEW.execution_environment = 'SHADOW' THEN
                v_required_phases := ARRAY['shadow', 'canary', 'scale'];
            ELSIF NEW.execution_environment = 'CANARY' THEN
                v_required_phases := ARRAY['canary', 'scale'];
            ELSIF NEW.execution_environment = 'SCALE' THEN
                v_required_phases := ARRAY['scale'];
            END IF;
            IF NOT (v_active_phase = ANY(v_required_phases)) THEN
                RAISE EXCEPTION
                    'Active promotion phase=% does not permit execution_environment=% (requires one of %)',
                    v_active_phase, NEW.execution_environment, v_required_phases;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER order_intents_promotion_gate
            BEFORE INSERT ON trading.order_intents
            FOR EACH ROW EXECUTE FUNCTION trading.enforce_order_intent_promotion();
    """)

    # =====================================================================
    # TRIGGERS 3+4: order_intents and order_groups append-only
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION trading.prevent_intent_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'trading.order_intents is append-only; UPDATE/DELETE forbidden.';
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER order_intents_no_update
            BEFORE UPDATE ON trading.order_intents
            FOR EACH ROW EXECUTE FUNCTION trading.prevent_intent_mutation();
        CREATE TRIGGER order_intents_no_delete
            BEFORE DELETE ON trading.order_intents
            FOR EACH ROW EXECUTE FUNCTION trading.prevent_intent_mutation();
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION trading.prevent_group_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'trading.order_groups is append-only; UPDATE/DELETE forbidden.';
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER order_groups_no_update
            BEFORE UPDATE ON trading.order_groups
            FOR EACH ROW EXECUTE FUNCTION trading.prevent_group_mutation();
        CREATE TRIGGER order_groups_no_delete
            BEFORE DELETE ON trading.order_groups
            FOR EACH ROW EXECUTE FUNCTION trading.prevent_group_mutation();
    """)

    # =====================================================================
    # TRIGGER 5: Reservation → intent consistency
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION trading.enforce_reservation_intent_consistency()
        RETURNS TRIGGER AS $$
        DECLARE
            v_intent_account_id BIGINT;
        BEGIN
            SELECT account_id INTO v_intent_account_id
            FROM trading.order_intents WHERE id = NEW.intent_id;
            IF v_intent_account_id IS NULL THEN
                RAISE EXCEPTION 'order_intent % does not exist', NEW.intent_id;
            END IF;
            IF v_intent_account_id IS DISTINCT FROM NEW.account_id THEN
                RAISE EXCEPTION
                    'reservation.account_id=% does not match intent.account_id=%',
                    NEW.account_id, v_intent_account_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER order_reservations_intent_consistency
            BEFORE INSERT ON trading.order_reservations
            FOR EACH ROW EXECUTE FUNCTION trading.enforce_reservation_intent_consistency();
    """)

    # =====================================================================
    # TRIGGER 6: Reservation lifecycle
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION trading.enforce_reservation_lifecycle()
        RETURNS TRIGGER AS $$
        DECLARE
            v_release_changed BOOLEAN;
            v_release_flag TEXT;
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.intent_id IS DISTINCT FROM OLD.intent_id
               OR NEW.account_id IS DISTINCT FROM OLD.account_id
               OR NEW.asset_id IS DISTINCT FROM OLD.asset_id
               OR NEW.reservation_type IS DISTINCT FROM OLD.reservation_type
               OR NEW.amount_reserved IS DISTINCT FROM OLD.amount_reserved
               OR NEW.reserved_at IS DISTINCT FROM OLD.reserved_at
            THEN
                RAISE EXCEPTION 'Reservation % identity fields are immutable', OLD.id;
            END IF;
            v_release_changed := (
                NEW.amount_released IS DISTINCT FROM OLD.amount_released
                OR NEW.released_at IS DISTINCT FROM OLD.released_at
                OR NEW.released_by IS DISTINCT FROM OLD.released_by
                OR NEW.release_reason IS DISTINCT FROM OLD.release_reason
            );
            IF v_release_changed THEN
                v_release_flag := current_setting('superhydra.allow_reservation_release', true);
                IF v_release_flag IS DISTINCT FROM 'on' THEN
                    RAISE EXCEPTION
                        'Direct mutation of reservation release fields is forbidden; use trading.release_reservation()';
                END IF;
                IF OLD.released_at IS NOT NULL THEN
                    RAISE EXCEPTION
                        'Reservation % is already released; release metadata is immutable', OLD.id;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION trading.prevent_reservation_delete()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'trading.order_reservations forbids DELETE.';
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER order_reservations_lifecycle
            BEFORE UPDATE ON trading.order_reservations
            FOR EACH ROW EXECUTE FUNCTION trading.enforce_reservation_lifecycle();
        CREATE TRIGGER order_reservations_no_delete
            BEFORE DELETE ON trading.order_reservations
            FOR EACH ROW EXECUTE FUNCTION trading.prevent_reservation_delete();
    """)

    # =====================================================================
    # FUNCTION: trading.release_reservation()
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION trading.release_reservation(
            p_reservation_id BIGINT,
            p_released_by TEXT,
            p_release_reason TEXT
        ) RETURNS VOID AS $$
        DECLARE
            v_intent_id BIGINT;
            v_reservation RECORD;
            v_order_state TEXT;
        BEGIN
            IF p_reservation_id IS NULL OR p_released_by IS NULL OR p_release_reason IS NULL THEN
                RAISE EXCEPTION 'release_reservation() arguments must be non-NULL';
            END IF;
            IF LENGTH(TRIM(p_released_by)) = 0 OR LENGTH(TRIM(p_release_reason)) = 0 THEN
                RAISE EXCEPTION 'released_by and release_reason must be non-empty';
            END IF;
            SELECT intent_id INTO v_intent_id
            FROM trading.order_reservations WHERE id = p_reservation_id;
            IF v_intent_id IS NULL THEN
                RAISE EXCEPTION 'Reservation % does not exist', p_reservation_id;
            END IF;
            SELECT state INTO v_order_state
            FROM trading.orders WHERE intent_id = v_intent_id FOR UPDATE;
            IF v_order_state IS NOT NULL
               AND v_order_state NOT IN (
                   'canceled', 'rejected', 'expired', 'failed_submit', 'filled'
               )
            THEN
                RAISE EXCEPTION
                    'Cannot release reservation % while order is in non-terminal state %',
                    p_reservation_id, v_order_state;
            END IF;
            SELECT id, intent_id, amount_reserved, released_at
            INTO v_reservation
            FROM trading.order_reservations WHERE id = p_reservation_id FOR UPDATE;
            IF v_reservation.id IS NULL THEN
                RAISE EXCEPTION 'Reservation % vanished during release', p_reservation_id;
            END IF;
            IF v_reservation.released_at IS NOT NULL THEN
                RAISE EXCEPTION 'Reservation % is already released', p_reservation_id;
            END IF;
            PERFORM set_config('superhydra.allow_reservation_release', 'on', true);
            BEGIN
                UPDATE trading.order_reservations
                SET amount_released = amount_reserved,
                    released_at = NOW(),
                    released_by = p_released_by,
                    release_reason = p_release_reason
                WHERE id = p_reservation_id;
            EXCEPTION WHEN OTHERS THEN
                PERFORM set_config('superhydra.allow_reservation_release', 'off', true);
                RAISE;
            END;
            PERFORM set_config('superhydra.allow_reservation_release', 'off', true);
        END;
        $$ LANGUAGE plpgsql;
    """)

    # =====================================================================
    # FUNCTION: trading.assert_order_reservation_ready()
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION trading.assert_order_reservation_ready(
            p_order_id BIGINT
        ) RETURNS VOID AS $$
        DECLARE
            v_order RECORD;
            v_intent_target_value_usd NUMERIC(38,12);
            v_required_notional NUMERIC(38,12);
            v_total_reserved NUMERIC(38,18);
            v_total_released NUMERIC(38,18);
            v_remaining_reserved NUMERIC(38,18);
            v_reservation_id BIGINT;
        BEGIN
            SELECT id, intent_id, state, quantity, price
            INTO v_order FROM trading.orders WHERE id = p_order_id FOR UPDATE;
            IF v_order.id IS NULL THEN
                RAISE EXCEPTION 'Order % does not exist', p_order_id;
            END IF;
            IF v_order.price IS NOT NULL THEN
                v_required_notional := v_order.quantity * v_order.price;
            ELSE
                SELECT target_value_usd INTO v_intent_target_value_usd
                FROM trading.order_intents WHERE id = v_order.intent_id;
                v_required_notional := v_intent_target_value_usd;
            END IF;
            FOR v_reservation_id IN
                SELECT id FROM trading.order_reservations
                WHERE intent_id = v_order.intent_id AND released_at IS NULL ORDER BY id
            LOOP
                PERFORM 1 FROM trading.order_reservations WHERE id = v_reservation_id FOR UPDATE;
            END LOOP;
            SELECT COALESCE(SUM(amount_reserved), 0), COALESCE(SUM(amount_released), 0)
            INTO v_total_reserved, v_total_released
            FROM trading.order_reservations
            WHERE intent_id = v_order.intent_id AND released_at IS NULL;
            v_remaining_reserved := v_total_reserved - v_total_released;
            IF v_remaining_reserved < v_required_notional THEN
                RAISE EXCEPTION
                    'Insufficient reservation for order %. required=%, remaining_reserved=%',
                    p_order_id, v_required_notional, v_remaining_reserved;
            END IF;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # =====================================================================
    # FUNCTION: trading.assert_order_submit_ready()
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION trading.assert_order_submit_ready(
            p_order_id BIGINT
        ) RETURNS VOID AS $$
        DECLARE
            v_outbox_id BIGINT;
        BEGIN
            PERFORM trading.assert_order_reservation_ready(p_order_id);
            SELECT id INTO v_outbox_id
            FROM trading.oms_outbox
            WHERE order_id = p_order_id AND operation = 'submit'
              AND state IN ('pending', 'in_flight') FOR UPDATE;
            IF v_outbox_id IS NULL THEN
                RAISE EXCEPTION
                    'Order % cannot be submitted: no usable submit outbox row (must be in pending or in_flight state; failed must be requeued first)',
                    p_order_id;
            END IF;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # =====================================================================
    # TRIGGER 7: Order INSERT initial-state guard
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION trading.enforce_order_initial_state()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.state != 'pending_submit' THEN
                RAISE EXCEPTION
                    'Orders must be inserted with state=pending_submit (got %)', NEW.state;
            END IF;
            IF NEW.filled_quantity != 0 THEN
                RAISE EXCEPTION 'Orders must be inserted with filled_quantity=0';
            END IF;
            IF NEW.avg_fill_price IS NOT NULL
               OR NEW.terminal_at IS NOT NULL
               OR NEW.submitted_at IS NOT NULL
               OR NEW.venue_acknowledged_at IS NOT NULL
               OR NEW.venue_order_id IS NOT NULL
               OR NEW.raw_ack_payload IS NOT NULL
               OR NEW.raw_reject_payload IS NOT NULL
               OR NEW.rejection_reason IS NOT NULL
               OR NEW.submission_error IS NOT NULL
            THEN
                RAISE EXCEPTION 'Orders must be inserted with NULL execution-truth fields';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER orders_initial_state_guard
            BEFORE INSERT ON trading.orders
            FOR EACH ROW EXECUTE FUNCTION trading.enforce_order_initial_state();
    """)

    # =====================================================================
    # TRIGGER 8: Order → intent consistency (16-char deterministic COID)
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION trading.enforce_order_intent_consistency()
        RETURNS TRIGGER AS $$
        DECLARE
            v_intent RECORD;
            v_group_portfolio_id BIGINT;
            v_group_strategy_id BIGINT;
            v_expected_coid TEXT;
        BEGIN
            SELECT intent_uuid, account_id, instrument_id, venue_id, venue_namespace,
                   side, target_quantity, portfolio_id, strategy_id
            INTO v_intent FROM trading.order_intents WHERE id = NEW.intent_id;
            IF v_intent.intent_uuid IS NULL THEN
                RAISE EXCEPTION 'order_intent % does not exist', NEW.intent_id;
            END IF;
            IF NEW.account_id IS DISTINCT FROM v_intent.account_id THEN
                RAISE EXCEPTION 'order.account_id=% does not match intent.account_id=%',
                    NEW.account_id, v_intent.account_id;
            END IF;
            IF NEW.instrument_id IS DISTINCT FROM v_intent.instrument_id THEN
                RAISE EXCEPTION 'order.instrument_id=% does not match intent.instrument_id=%',
                    NEW.instrument_id, v_intent.instrument_id;
            END IF;
            IF NEW.venue_id IS DISTINCT FROM v_intent.venue_id THEN
                RAISE EXCEPTION 'order.venue_id=% does not match intent.venue_id=%',
                    NEW.venue_id, v_intent.venue_id;
            END IF;
            IF NEW.venue_namespace IS DISTINCT FROM v_intent.venue_namespace THEN
                RAISE EXCEPTION 'order.venue_namespace=% does not match intent.venue_namespace=%',
                    NEW.venue_namespace, v_intent.venue_namespace;
            END IF;
            IF NEW.side IS DISTINCT FROM v_intent.side THEN
                RAISE EXCEPTION 'order.side=% does not match intent.side=%',
                    NEW.side, v_intent.side;
            END IF;
            IF NEW.quantity > v_intent.target_quantity THEN
                RAISE EXCEPTION 'order.quantity=% exceeds intent.target_quantity=%',
                    NEW.quantity, v_intent.target_quantity;
            END IF;
            v_expected_coid := 'so_' || substr(replace(v_intent.intent_uuid::text, '-', ''), 1, 16) || '_' || NEW.side;
            IF NEW.client_order_id IS DISTINCT FROM v_expected_coid THEN
                RAISE EXCEPTION
                    'order.client_order_id=% does not match expected deterministic value=%',
                    NEW.client_order_id, v_expected_coid;
            END IF;
            IF NEW.order_group_id IS NOT NULL THEN
                SELECT portfolio_id, strategy_id
                INTO v_group_portfolio_id, v_group_strategy_id
                FROM trading.order_groups WHERE id = NEW.order_group_id;
                IF v_group_portfolio_id IS NULL THEN
                    RAISE EXCEPTION 'order_group % does not exist', NEW.order_group_id;
                END IF;
                IF v_group_portfolio_id IS DISTINCT FROM v_intent.portfolio_id THEN
                    RAISE EXCEPTION 'order_group.portfolio_id=% does not match intent.portfolio_id=%',
                        v_group_portfolio_id, v_intent.portfolio_id;
                END IF;
                IF v_group_strategy_id IS NOT NULL
                   AND v_group_strategy_id IS DISTINCT FROM v_intent.strategy_id
                THEN
                    RAISE EXCEPTION 'order_group.strategy_id=% does not match intent.strategy_id=%',
                        v_group_strategy_id, v_intent.strategy_id;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER orders_intent_consistency
            BEFORE INSERT ON trading.orders
            FOR EACH ROW EXECUTE FUNCTION trading.enforce_order_intent_consistency();
    """)

    # =====================================================================
    # TRIGGER 9: Order identity + execution-truth immutability
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION trading.enforce_order_identity_immutability()
        RETURNS TRIGGER AS $$
        DECLARE
            v_state_event_flag TEXT;
            v_fill_flag TEXT;
            v_cancel_flag TEXT;
            v_ack_flag TEXT;
            v_reject_flag TEXT;
            v_failed_submit_flag TEXT;
            v_state_changed BOOLEAN;
            v_fill_fields_changed BOOLEAN;
            v_ack_fields_changed BOOLEAN;
            v_reject_fields_changed BOOLEAN;
            v_failed_submit_fields_changed BOOLEAN;
            v_submit_terminal_changed BOOLEAN;
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.order_uuid IS DISTINCT FROM OLD.order_uuid
               OR NEW.intent_id IS DISTINCT FROM OLD.intent_id
               OR NEW.order_group_id IS DISTINCT FROM OLD.order_group_id
               OR NEW.venue_id IS DISTINCT FROM OLD.venue_id
               OR NEW.venue_namespace IS DISTINCT FROM OLD.venue_namespace
               OR NEW.account_id IS DISTINCT FROM OLD.account_id
               OR NEW.instrument_id IS DISTINCT FROM OLD.instrument_id
               OR NEW.client_order_id IS DISTINCT FROM OLD.client_order_id
               OR NEW.side IS DISTINCT FROM OLD.side
               OR NEW.order_type IS DISTINCT FROM OLD.order_type
               OR NEW.post_only IS DISTINCT FROM OLD.post_only
               OR NEW.reduce_only IS DISTINCT FROM OLD.reduce_only
               OR NEW.quantity IS DISTINCT FROM OLD.quantity
               OR NEW.price IS DISTINCT FROM OLD.price
               OR NEW.stop_price IS DISTINCT FROM OLD.stop_price
               OR NEW.time_in_force IS DISTINCT FROM OLD.time_in_force
               OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
               OR NEW.created_via IS DISTINCT FROM OLD.created_via
               OR NEW.created_by IS DISTINCT FROM OLD.created_by
               OR NEW.created_at IS DISTINCT FROM OLD.created_at
            THEN
                RAISE EXCEPTION 'Order % identity fields are immutable', OLD.id;
            END IF;
            v_submit_terminal_changed := (
                NEW.submitted_at IS DISTINCT FROM OLD.submitted_at
                OR NEW.terminal_at IS DISTINCT FROM OLD.terminal_at
            );
            v_state_changed := NEW.state IS DISTINCT FROM OLD.state;
            v_fill_fields_changed := (
                NEW.filled_quantity IS DISTINCT FROM OLD.filled_quantity
                OR NEW.avg_fill_price IS DISTINCT FROM OLD.avg_fill_price
            );
            v_ack_fields_changed := (
                NEW.venue_order_id IS DISTINCT FROM OLD.venue_order_id
                OR NEW.venue_acknowledged_at IS DISTINCT FROM OLD.venue_acknowledged_at
                OR NEW.raw_ack_payload IS DISTINCT FROM OLD.raw_ack_payload
            );
            v_reject_fields_changed := (
                NEW.rejection_reason IS DISTINCT FROM OLD.rejection_reason
                OR NEW.raw_reject_payload IS DISTINCT FROM OLD.raw_reject_payload
            );
            v_failed_submit_fields_changed := (
                NEW.submission_error IS DISTINCT FROM OLD.submission_error
            );
            IF OLD.venue_order_id IS NOT NULL
               AND NEW.venue_order_id IS DISTINCT FROM OLD.venue_order_id
            THEN
                RAISE EXCEPTION 'Order % venue_order_id is one-time set', OLD.id;
            END IF;
            IF OLD.raw_ack_payload IS NOT NULL
               AND NEW.raw_ack_payload IS DISTINCT FROM OLD.raw_ack_payload
            THEN
                RAISE EXCEPTION 'Order % raw_ack_payload is one-time set', OLD.id;
            END IF;
            IF OLD.raw_reject_payload IS NOT NULL
               AND NEW.raw_reject_payload IS DISTINCT FROM OLD.raw_reject_payload
            THEN
                RAISE EXCEPTION 'Order % raw_reject_payload is one-time set', OLD.id;
            END IF;
            v_state_event_flag := current_setting('superhydra.allow_order_state_event_insert', true);
            v_fill_flag := current_setting('superhydra.allow_order_fill_update', true);
            v_cancel_flag := current_setting('superhydra.allow_order_cancel_update', true);
            v_ack_flag := current_setting('superhydra.allow_order_ack_update', true);
            v_reject_flag := current_setting('superhydra.allow_order_reject_update', true);
            v_failed_submit_flag := current_setting('superhydra.allow_order_failed_submit_update', true);
            IF v_submit_terminal_changed AND NOT v_state_changed THEN
                IF v_state_event_flag IS DISTINCT FROM 'on'
                   AND v_fill_flag IS DISTINCT FROM 'on'
                   AND v_cancel_flag IS DISTINCT FROM 'on'
                   AND v_ack_flag IS DISTINCT FROM 'on'
                   AND v_reject_flag IS DISTINCT FROM 'on'
                   AND v_failed_submit_flag IS DISTINCT FROM 'on'
                THEN
                    RAISE EXCEPTION
                        'Order % submitted_at and terminal_at are populated only by controlled state transitions',
                        OLD.id;
                END IF;
            END IF;
            IF v_fill_fields_changed THEN
                IF v_fill_flag IS DISTINCT FROM 'on' THEN
                    RAISE EXCEPTION
                        'Order % fill fields require fill insert (process_fill_update_order trigger)',
                        OLD.id;
                END IF;
            END IF;
            IF v_ack_fields_changed THEN
                IF v_ack_flag IS DISTINCT FROM 'on' THEN
                    RAISE EXCEPTION
                        'Order % ack fields require trading.record_order_ack()',
                        OLD.id;
                END IF;
            END IF;
            IF v_reject_fields_changed THEN
                IF v_reject_flag IS DISTINCT FROM 'on' THEN
                    RAISE EXCEPTION
                        'Order % reject fields require trading.record_order_reject()',
                        OLD.id;
                END IF;
            END IF;
            IF v_failed_submit_fields_changed THEN
                IF v_failed_submit_flag IS DISTINCT FROM 'on' THEN
                    RAISE EXCEPTION
                        'Order % submission_error requires trading.record_order_failed_submit()',
                        OLD.id;
                END IF;
            END IF;
            IF v_state_changed THEN
                CASE NEW.state
                    WHEN 'submitted' THEN
                        IF v_state_event_flag IS DISTINCT FROM 'on' THEN
                            RAISE EXCEPTION 'state -> submitted requires trading.transition_order_state()';
                        END IF;
                    WHEN 'working' THEN
                        IF v_ack_flag IS DISTINCT FROM 'on' THEN
                            RAISE EXCEPTION 'state -> working requires trading.record_order_ack()';
                        END IF;
                    WHEN 'partially_filled', 'filled' THEN
                        IF v_fill_flag IS DISTINCT FROM 'on' THEN
                            RAISE EXCEPTION 'state -> % requires fill insert (process_fill_update_order trigger)', NEW.state;
                        END IF;
                    WHEN 'cancel_requested' THEN
                        IF v_state_event_flag IS DISTINCT FROM 'on' THEN
                            RAISE EXCEPTION 'state -> cancel_requested requires trading.transition_order_state()';
                        END IF;
                    WHEN 'canceled' THEN
                        IF OLD.state = 'pending_submit' THEN
                            IF v_state_event_flag IS DISTINCT FROM 'on' THEN
                                RAISE EXCEPTION 'state pending_submit -> canceled requires trading.transition_order_state()';
                            END IF;
                        ELSE
                            IF v_cancel_flag IS DISTINCT FROM 'on' THEN
                                RAISE EXCEPTION 'state % -> canceled requires cancel insert (process_cancel_update_order trigger)', OLD.state;
                            END IF;
                        END IF;
                    WHEN 'rejected' THEN
                        IF v_reject_flag IS DISTINCT FROM 'on' THEN
                            RAISE EXCEPTION 'state -> rejected requires trading.record_order_reject()';
                        END IF;
                    WHEN 'failed_submit' THEN
                        IF v_failed_submit_flag IS DISTINCT FROM 'on' THEN
                            RAISE EXCEPTION 'state -> failed_submit requires trading.record_order_failed_submit()';
                        END IF;
                    WHEN 'expired', 'stale_needs_reconciliation', 'unknown' THEN
                        IF v_state_event_flag IS DISTINCT FROM 'on' THEN
                            RAISE EXCEPTION 'state -> % requires trading.transition_order_state()', NEW.state;
                        END IF;
                    ELSE
                        RAISE EXCEPTION 'Unhandled state target % in ownership check', NEW.state;
                END CASE;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION trading.prevent_order_delete()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'trading.orders forbids DELETE; orders are audit records.';
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER orders_identity_immutability
            BEFORE UPDATE ON trading.orders
            FOR EACH ROW EXECUTE FUNCTION trading.enforce_order_identity_immutability();
        CREATE TRIGGER orders_no_delete
            BEFORE DELETE ON trading.orders
            FOR EACH ROW EXECUTE FUNCTION trading.prevent_order_delete();
    """)

    # =====================================================================
    # TRIGGER 10: Order state machine (v5.2-final: submitted allows canceled)
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION trading.enforce_order_state_machine()
        RETURNS TRIGGER AS $$
        DECLARE
            v_valid_transitions TEXT[];
            v_terminal_states TEXT[] := ARRAY[
                'filled', 'canceled', 'rejected', 'expired', 'failed_submit'
            ];
        BEGIN
            IF NEW.state IS NOT DISTINCT FROM OLD.state THEN
                RETURN NEW;
            END IF;
            CASE OLD.state
                WHEN 'pending_submit' THEN
                    v_valid_transitions := ARRAY['submitted', 'failed_submit', 'rejected', 'canceled'];
                WHEN 'submitted' THEN
                    v_valid_transitions := ARRAY['working', 'rejected', 'canceled', 'stale_needs_reconciliation'];
                WHEN 'working' THEN
                    v_valid_transitions := ARRAY[
                        'partially_filled', 'filled', 'cancel_requested',
                        'canceled', 'expired', 'stale_needs_reconciliation'
                    ];
                WHEN 'partially_filled' THEN
                    v_valid_transitions := ARRAY[
                        'filled', 'cancel_requested', 'canceled', 'expired',
                        'stale_needs_reconciliation'
                    ];
                WHEN 'cancel_requested' THEN
                    v_valid_transitions := ARRAY[
                        'canceled', 'filled', 'partially_filled', 'stale_needs_reconciliation'
                    ];
                WHEN 'stale_needs_reconciliation' THEN
                    v_valid_transitions := ARRAY[
                        'working', 'partially_filled', 'filled',
                        'canceled', 'rejected', 'expired', 'unknown'
                    ];
                WHEN 'unknown' THEN
                    v_valid_transitions := ARRAY[
                        'working', 'partially_filled', 'filled',
                        'canceled', 'rejected', 'expired'
                    ];
                ELSE
                    v_valid_transitions := ARRAY[]::TEXT[];
            END CASE;
            IF NOT (NEW.state = ANY(v_valid_transitions)) THEN
                RAISE EXCEPTION
                    'Invalid order state transition for order %: % -> % (valid from %: %)',
                    OLD.id, OLD.state, NEW.state, OLD.state, v_valid_transitions;
            END IF;
            IF OLD.state = 'pending_submit'
               AND NEW.state IN ('submitted', 'working', 'partially_filled', 'filled')
               AND NEW.submitted_at IS NULL
            THEN
                NEW.submitted_at := NOW();
            END IF;
            IF NEW.state = ANY(v_terminal_states) AND NEW.terminal_at IS NULL THEN
                NEW.terminal_at := NOW();
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER orders_state_machine
            BEFORE UPDATE OF state ON trading.orders
            FOR EACH ROW EXECUTE FUNCTION trading.enforce_order_state_machine();
    """)

    # =====================================================================
    # FUNCTION: trading.transition_order_state()
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION trading.transition_order_state(
            p_order_id BIGINT, p_new_state TEXT, p_transition_reason TEXT,
            p_source_type TEXT, p_source_namespace TEXT, p_source_id TEXT,
            p_created_by TEXT, p_metadata JSONB DEFAULT '{}'::jsonb
        ) RETURNS VOID AS $$
        DECLARE
            v_old_state TEXT;
        BEGIN
            SELECT state INTO v_old_state FROM trading.orders WHERE id = p_order_id FOR UPDATE;
            IF v_old_state IS NULL THEN
                RAISE EXCEPTION 'Order % does not exist', p_order_id;
            END IF;
            IF v_old_state IS NOT DISTINCT FROM p_new_state THEN
                RAISE EXCEPTION 'Order % is already in state %', p_order_id, p_new_state;
            END IF;
            IF p_new_state = 'submitted' THEN
                PERFORM trading.assert_order_submit_ready(p_order_id);
            END IF;
            PERFORM set_config('superhydra.allow_order_state_event_insert', 'on', true);
            BEGIN
                UPDATE trading.orders SET state = p_new_state, updated_at = NOW() WHERE id = p_order_id;
                INSERT INTO trading.order_state_events (
                    order_id, old_state, new_state, transition_reason,
                    source_type, source_namespace, source_id, created_by, metadata
                ) VALUES (
                    p_order_id, v_old_state, p_new_state, p_transition_reason,
                    p_source_type, p_source_namespace, p_source_id, p_created_by, p_metadata
                );
            EXCEPTION WHEN OTHERS THEN
                PERFORM set_config('superhydra.allow_order_state_event_insert', 'off', true);
                RAISE;
            END;
            PERFORM set_config('superhydra.allow_order_state_event_insert', 'off', true);
        END;
        $$ LANGUAGE plpgsql;
    """)

    # =====================================================================
    # FUNCTION: trading.record_order_ack()
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION trading.record_order_ack(
            p_order_id BIGINT, p_venue_order_id TEXT,
            p_raw_ack_payload JSONB, p_recorded_by TEXT
        ) RETURNS VOID AS $$
        DECLARE
            v_old_state TEXT;
        BEGIN
            IF p_order_id IS NULL OR p_venue_order_id IS NULL
               OR p_raw_ack_payload IS NULL OR p_recorded_by IS NULL
            THEN
                RAISE EXCEPTION 'record_order_ack() arguments must be non-NULL';
            END IF;
            IF LENGTH(TRIM(p_venue_order_id)) = 0 OR LENGTH(TRIM(p_recorded_by)) = 0 THEN
                RAISE EXCEPTION 'venue_order_id and recorded_by must be non-empty';
            END IF;
            IF jsonb_typeof(p_raw_ack_payload) != 'object' THEN
                RAISE EXCEPTION 'raw_ack_payload must be a JSON object';
            END IF;
            SELECT state INTO v_old_state FROM trading.orders WHERE id = p_order_id FOR UPDATE;
            IF v_old_state IS NULL THEN
                RAISE EXCEPTION 'Order % does not exist', p_order_id;
            END IF;
            IF v_old_state NOT IN ('submitted', 'stale_needs_reconciliation') THEN
                RAISE EXCEPTION
                    'record_order_ack requires order state IN (submitted, stale_needs_reconciliation); got %',
                    v_old_state;
            END IF;
            PERFORM set_config('superhydra.allow_order_ack_update', 'on', true);
            PERFORM set_config('superhydra.allow_order_state_event_insert', 'on', true);
            BEGIN
                UPDATE trading.orders
                SET venue_order_id = p_venue_order_id, venue_acknowledged_at = NOW(),
                    raw_ack_payload = p_raw_ack_payload, state = 'working', updated_at = NOW()
                WHERE id = p_order_id;
                INSERT INTO trading.order_state_events (
                    order_id, old_state, new_state, transition_reason,
                    source_type, source_namespace, source_id, created_by, metadata
                ) VALUES (
                    p_order_id, v_old_state, 'working', 'venue acknowledged',
                    'venue_ack', 'system', p_venue_order_id, p_recorded_by,
                    jsonb_build_object('venue_order_id', p_venue_order_id)
                );
            EXCEPTION WHEN OTHERS THEN
                PERFORM set_config('superhydra.allow_order_ack_update', 'off', true);
                PERFORM set_config('superhydra.allow_order_state_event_insert', 'off', true);
                RAISE;
            END;
            PERFORM set_config('superhydra.allow_order_ack_update', 'off', true);
            PERFORM set_config('superhydra.allow_order_state_event_insert', 'off', true);
        END;
        $$ LANGUAGE plpgsql;
    """)

    # =====================================================================
    # FUNCTION: trading.record_order_reject()
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION trading.record_order_reject(
            p_order_id BIGINT, p_rejection_reason TEXT,
            p_raw_reject_payload JSONB, p_recorded_by TEXT
        ) RETURNS VOID AS $$
        DECLARE
            v_old_state TEXT;
        BEGIN
            IF p_order_id IS NULL OR p_rejection_reason IS NULL OR p_recorded_by IS NULL THEN
                RAISE EXCEPTION 'record_order_reject() arguments must be non-NULL (raw_reject_payload may be NULL)';
            END IF;
            IF LENGTH(TRIM(p_rejection_reason)) = 0 OR LENGTH(TRIM(p_recorded_by)) = 0 THEN
                RAISE EXCEPTION 'rejection_reason and recorded_by must be non-empty';
            END IF;
            IF p_raw_reject_payload IS NOT NULL AND jsonb_typeof(p_raw_reject_payload) != 'object' THEN
                RAISE EXCEPTION 'raw_reject_payload must be a JSON object or NULL';
            END IF;
            SELECT state INTO v_old_state FROM trading.orders WHERE id = p_order_id FOR UPDATE;
            IF v_old_state IS NULL THEN
                RAISE EXCEPTION 'Order % does not exist', p_order_id;
            END IF;
            IF v_old_state NOT IN ('pending_submit', 'submitted') THEN
                RAISE EXCEPTION
                    'record_order_reject requires order state IN (pending_submit, submitted); got %',
                    v_old_state;
            END IF;
            PERFORM set_config('superhydra.allow_order_reject_update', 'on', true);
            PERFORM set_config('superhydra.allow_order_state_event_insert', 'on', true);
            BEGIN
                UPDATE trading.orders
                SET rejection_reason = p_rejection_reason,
                    raw_reject_payload = p_raw_reject_payload,
                    state = 'rejected', updated_at = NOW()
                WHERE id = p_order_id;
                INSERT INTO trading.order_state_events (
                    order_id, old_state, new_state, transition_reason,
                    source_type, source_namespace, source_id, created_by, metadata
                ) VALUES (
                    p_order_id, v_old_state, 'rejected',
                    'venue rejection: ' || p_rejection_reason,
                    'venue_reject', 'system', NULL, p_recorded_by,
                    jsonb_build_object('rejection_reason', p_rejection_reason)
                );
            EXCEPTION WHEN OTHERS THEN
                PERFORM set_config('superhydra.allow_order_reject_update', 'off', true);
                PERFORM set_config('superhydra.allow_order_state_event_insert', 'off', true);
                RAISE;
            END;
            PERFORM set_config('superhydra.allow_order_reject_update', 'off', true);
            PERFORM set_config('superhydra.allow_order_state_event_insert', 'off', true);
        END;
        $$ LANGUAGE plpgsql;
    """)

    # =====================================================================
    # FUNCTION: trading.record_order_failed_submit()
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION trading.record_order_failed_submit(
            p_order_id BIGINT, p_submission_error TEXT, p_recorded_by TEXT
        ) RETURNS VOID AS $$
        DECLARE
            v_old_state TEXT;
        BEGIN
            IF p_order_id IS NULL OR p_submission_error IS NULL OR p_recorded_by IS NULL THEN
                RAISE EXCEPTION 'record_order_failed_submit() arguments must be non-NULL';
            END IF;
            IF LENGTH(TRIM(p_submission_error)) = 0 OR LENGTH(TRIM(p_recorded_by)) = 0 THEN
                RAISE EXCEPTION 'submission_error and recorded_by must be non-empty';
            END IF;
            SELECT state INTO v_old_state FROM trading.orders WHERE id = p_order_id FOR UPDATE;
            IF v_old_state IS NULL THEN
                RAISE EXCEPTION 'Order % does not exist', p_order_id;
            END IF;
            IF v_old_state != 'pending_submit' THEN
                RAISE EXCEPTION
                    'record_order_failed_submit requires order state=pending_submit; got %', v_old_state;
            END IF;
            PERFORM set_config('superhydra.allow_order_failed_submit_update', 'on', true);
            PERFORM set_config('superhydra.allow_order_state_event_insert', 'on', true);
            BEGIN
                UPDATE trading.orders
                SET submission_error = p_submission_error,
                    state = 'failed_submit', updated_at = NOW()
                WHERE id = p_order_id;
                INSERT INTO trading.order_state_events (
                    order_id, old_state, new_state, transition_reason,
                    source_type, source_namespace, source_id, created_by, metadata
                ) VALUES (
                    p_order_id, v_old_state, 'failed_submit',
                    'submission failed: ' || p_submission_error,
                    'submission_error', 'system', NULL, p_recorded_by,
                    jsonb_build_object('submission_error', p_submission_error)
                );
            EXCEPTION WHEN OTHERS THEN
                PERFORM set_config('superhydra.allow_order_failed_submit_update', 'off', true);
                PERFORM set_config('superhydra.allow_order_state_event_insert', 'off', true);
                RAISE;
            END;
            PERFORM set_config('superhydra.allow_order_failed_submit_update', 'off', true);
            PERFORM set_config('superhydra.allow_order_state_event_insert', 'off', true);
        END;
        $$ LANGUAGE plpgsql;
    """)

    # =====================================================================
    # TRIGGER 11: order_state_events insert authorization
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION trading.enforce_state_event_audit()
        RETURNS TRIGGER AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF current_setting('superhydra.allow_order_state_event_insert', true) IS DISTINCT FROM 'on' THEN
                    RAISE EXCEPTION 'Direct INSERT into trading.order_state_events is forbidden';
                END IF;
                RETURN NEW;
            ELSE
                RAISE EXCEPTION 'trading.order_state_events is append-only; UPDATE/DELETE forbidden.';
            END IF;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER order_state_events_insert_gate
            BEFORE INSERT ON trading.order_state_events
            FOR EACH ROW EXECUTE FUNCTION trading.enforce_state_event_audit();
        CREATE TRIGGER order_state_events_no_update
            BEFORE UPDATE ON trading.order_state_events
            FOR EACH ROW EXECUTE FUNCTION trading.enforce_state_event_audit();
        CREATE TRIGGER order_state_events_no_delete
            BEFORE DELETE ON trading.order_state_events
            FOR EACH ROW EXECUTE FUNCTION trading.enforce_state_event_audit();
    """)

    # =====================================================================
    # TRIGGER 12: fills initial-state guard
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION trading.enforce_fill_initial_state()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.journal_id IS NOT NULL OR NEW.reconciled_at IS NOT NULL OR NEW.reconciled_by IS NOT NULL THEN
                RAISE EXCEPTION 'Fills must be inserted unreconciled; use trading.reconcile_fill()';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER fills_initial_state_guard
            BEFORE INSERT ON trading.fills
            FOR EACH ROW EXECUTE FUNCTION trading.enforce_fill_initial_state();
    """)

    # =====================================================================
    # TRIGGER 13: process_fill_update_order (v5.2: ack-before-fill)
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION trading.process_fill_update_order()
        RETURNS TRIGGER AS $$
        DECLARE
            v_order RECORD;
            v_intent_env TEXT;
            v_new_filled NUMERIC(38,18);
            v_new_avg_price NUMERIC(38,18);
            v_old_state TEXT;
            v_new_state TEXT;
            v_total_notional NUMERIC(38,18);
        BEGIN
            SELECT id, intent_id, side, quantity, filled_quantity, avg_fill_price,
                   state, instrument_id, venue_id, venue_namespace, account_id
            INTO v_order FROM trading.orders WHERE id = NEW.order_id FOR UPDATE;
            IF v_order.id IS NULL THEN
                RAISE EXCEPTION 'Order % does not exist', NEW.order_id;
            END IF;
            IF v_order.state IN (
                'pending_submit', 'submitted',
                'filled', 'canceled', 'rejected', 'expired', 'failed_submit'
            ) THEN
                RAISE EXCEPTION
                    'Cannot insert fill: order % is in non-fillable state %',
                    v_order.id, v_order.state;
            END IF;
            IF v_order.instrument_id IS DISTINCT FROM NEW.instrument_id THEN
                RAISE EXCEPTION 'Fill instrument_id=% does not match order instrument_id=%',
                    NEW.instrument_id, v_order.instrument_id;
            END IF;
            IF v_order.side IS DISTINCT FROM NEW.side THEN
                RAISE EXCEPTION 'Fill side=% does not match order side=%', NEW.side, v_order.side;
            END IF;
            IF v_order.venue_namespace IS DISTINCT FROM NEW.venue_namespace THEN
                RAISE EXCEPTION 'Fill venue_namespace=% does not match order venue_namespace=%',
                    NEW.venue_namespace, v_order.venue_namespace;
            END IF;
            SELECT execution_environment INTO v_intent_env
            FROM trading.order_intents WHERE id = v_order.intent_id;
            IF v_intent_env = 'SHADOW' AND NEW.fill_environment != 'SHADOW' THEN
                RAISE EXCEPTION
                    'Intent execution_environment=SHADOW requires fill_environment=SHADOW (got %)',
                    NEW.fill_environment;
            ELSIF v_intent_env IN ('CANARY', 'SCALE') AND NEW.fill_environment != 'LIVE' THEN
                RAISE EXCEPTION
                    'Intent execution_environment=% requires fill_environment=LIVE (got %)',
                    v_intent_env, NEW.fill_environment;
            END IF;
            v_new_filled := v_order.filled_quantity + NEW.quantity;
            IF v_new_filled > v_order.quantity THEN
                RAISE EXCEPTION 'Cumulative filled quantity % exceeds order quantity %',
                    v_new_filled, v_order.quantity;
            END IF;
            IF v_order.avg_fill_price IS NULL THEN
                v_new_avg_price := NEW.price;
            ELSE
                v_total_notional := (v_order.avg_fill_price * v_order.filled_quantity)
                                  + (NEW.price * NEW.quantity);
                v_new_avg_price := v_total_notional / v_new_filled;
            END IF;
            v_old_state := v_order.state;
            IF v_new_filled = v_order.quantity THEN
                v_new_state := 'filled';
            ELSE
                v_new_state := 'partially_filled';
            END IF;
            PERFORM set_config('superhydra.allow_order_fill_update', 'on', true);
            PERFORM set_config('superhydra.allow_order_state_event_insert', 'on', true);
            BEGIN
                UPDATE trading.orders
                SET filled_quantity = v_new_filled, avg_fill_price = v_new_avg_price,
                    state = v_new_state, updated_at = NOW()
                WHERE id = v_order.id;
                IF v_old_state IS DISTINCT FROM v_new_state THEN
                    INSERT INTO trading.order_state_events (
                        order_id, old_state, new_state, transition_reason,
                        source_type, source_namespace, source_id, created_by, metadata
                    ) VALUES (
                        v_order.id, v_old_state, v_new_state, 'fill received',
                        'fill', NEW.venue_namespace, NEW.venue_fill_id, 'system',
                        jsonb_build_object('fill_id', NEW.id, 'fill_quantity', NEW.quantity, 'fill_price', NEW.price)
                    );
                END IF;
            EXCEPTION WHEN OTHERS THEN
                PERFORM set_config('superhydra.allow_order_fill_update', 'off', true);
                PERFORM set_config('superhydra.allow_order_state_event_insert', 'off', true);
                RAISE;
            END;
            PERFORM set_config('superhydra.allow_order_fill_update', 'off', true);
            PERFORM set_config('superhydra.allow_order_state_event_insert', 'off', true);
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER fills_process_update_order
            AFTER INSERT ON trading.fills
            FOR EACH ROW EXECUTE FUNCTION trading.process_fill_update_order();
    """)

    # =====================================================================
    # TRIGGER 14: Fill reconciliation gate
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION trading.enforce_fill_reconciliation()
        RETURNS TRIGGER AS $$
        DECLARE
            v_journal_status TEXT;
            v_journal_type TEXT;
            v_journal_voided_at TIMESTAMPTZ;
            v_journal_source_type TEXT;
            v_journal_source_namespace TEXT;
            v_journal_source_id TEXT;
            v_journal_portfolio_id BIGINT;
            v_journal_strategy_id BIGINT;
            v_intent_portfolio_id BIGINT;
            v_intent_strategy_id BIGINT;
            v_recon_flag TEXT;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'trading.fills DELETE is forbidden; fills are audit records.';
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.fill_uuid IS DISTINCT FROM OLD.fill_uuid
               OR NEW.order_id IS DISTINCT FROM OLD.order_id
               OR NEW.instrument_id IS DISTINCT FROM OLD.instrument_id
               OR NEW.venue_fill_id IS DISTINCT FROM OLD.venue_fill_id
               OR NEW.venue_namespace IS DISTINCT FROM OLD.venue_namespace
               OR NEW.side IS DISTINCT FROM OLD.side
               OR NEW.quantity IS DISTINCT FROM OLD.quantity
               OR NEW.price IS DISTINCT FROM OLD.price
               OR NEW.notional_value IS DISTINCT FROM OLD.notional_value
               OR NEW.liquidity_side IS DISTINCT FROM OLD.liquidity_side
               OR NEW.fill_environment IS DISTINCT FROM OLD.fill_environment
               OR NEW.fill_settlement_type IS DISTINCT FROM OLD.fill_settlement_type
               OR NEW.filled_at IS DISTINCT FROM OLD.filled_at
               OR NEW.received_at IS DISTINCT FROM OLD.received_at
               OR NEW.raw_record_hash IS DISTINCT FROM OLD.raw_record_hash
               OR NEW.raw_record IS DISTINCT FROM OLD.raw_record
               OR NEW.created_at IS DISTINCT FROM OLD.created_at
            THEN
                RAISE EXCEPTION 'Fill % identity / measurement fields are immutable', OLD.id;
            END IF;
            IF OLD.journal_id IS NOT NULL THEN
                IF NEW.journal_id IS DISTINCT FROM OLD.journal_id
                   OR NEW.reconciled_at IS DISTINCT FROM OLD.reconciled_at
                   OR NEW.reconciled_by IS DISTINCT FROM OLD.reconciled_by
                THEN
                    RAISE EXCEPTION 'Fill % is already reconciled; reconciliation metadata is immutable', OLD.id;
                END IF;
                RETURN NEW;
            END IF;
            IF NEW.journal_id IS NOT NULL THEN
                v_recon_flag := current_setting('superhydra.allow_fill_reconcile', true);
                IF v_recon_flag IS DISTINCT FROM 'on' THEN
                    RAISE EXCEPTION 'Direct fill reconciliation UPDATE forbidden; use trading.reconcile_fill()';
                END IF;
                SELECT status, journal_type, voided_at, source_type, source_namespace, source_id,
                       portfolio_id, strategy_id
                INTO v_journal_status, v_journal_type, v_journal_voided_at,
                     v_journal_source_type, v_journal_source_namespace, v_journal_source_id,
                     v_journal_portfolio_id, v_journal_strategy_id
                FROM accounting.journals WHERE id = NEW.journal_id FOR UPDATE;
                IF v_journal_status IS NULL THEN
                    RAISE EXCEPTION 'Journal % does not exist', NEW.journal_id;
                END IF;
                IF v_journal_status != 'posted' THEN
                    RAISE EXCEPTION 'Fill reconciliation journal % must be posted (current: %)',
                        NEW.journal_id, v_journal_status;
                END IF;
                IF v_journal_voided_at IS NOT NULL THEN
                    RAISE EXCEPTION 'Fill reconciliation journal % has been voided', NEW.journal_id;
                END IF;
                IF v_journal_type IS DISTINCT FROM 'trade' THEN
                    RAISE EXCEPTION 'Fill reconciliation journal % must be journal_type=trade (got %)',
                        NEW.journal_id, v_journal_type;
                END IF;
                IF v_journal_source_type IS DISTINCT FROM 'fill' THEN
                    RAISE EXCEPTION 'Fill reconciliation journal % must be source_type=fill (got %)',
                        NEW.journal_id, v_journal_source_type;
                END IF;
                IF v_journal_source_namespace IS DISTINCT FROM NEW.venue_namespace THEN
                    RAISE EXCEPTION 'Fill reconciliation journal source_namespace=% does not match fill venue_namespace=%',
                        v_journal_source_namespace, NEW.venue_namespace;
                END IF;
                IF v_journal_source_id IS DISTINCT FROM NEW.venue_fill_id THEN
                    RAISE EXCEPTION 'Fill reconciliation journal source_id=% does not match fill venue_fill_id=%',
                        v_journal_source_id, NEW.venue_fill_id;
                END IF;
                SELECT i.portfolio_id, i.strategy_id
                INTO v_intent_portfolio_id, v_intent_strategy_id
                FROM trading.orders o
                JOIN trading.order_intents i ON i.id = o.intent_id
                WHERE o.id = NEW.order_id;
                IF v_journal_portfolio_id IS DISTINCT FROM v_intent_portfolio_id THEN
                    RAISE EXCEPTION 'Fill reconciliation journal portfolio_id=% does not match intent portfolio_id=%',
                        v_journal_portfolio_id, v_intent_portfolio_id;
                END IF;
                IF v_journal_strategy_id IS DISTINCT FROM v_intent_strategy_id THEN
                    RAISE EXCEPTION 'Fill reconciliation journal strategy_id=% does not match intent strategy_id=%',
                        v_journal_strategy_id, v_intent_strategy_id;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER fills_reconciliation_gate
            BEFORE UPDATE ON trading.fills
            FOR EACH ROW EXECUTE FUNCTION trading.enforce_fill_reconciliation();
        CREATE TRIGGER fills_no_delete
            BEFORE DELETE ON trading.fills
            FOR EACH ROW EXECUTE FUNCTION trading.enforce_fill_reconciliation();
    """)

    # =====================================================================
    # FUNCTION: trading.reconcile_fill()
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION trading.reconcile_fill(
            p_fill_id BIGINT, p_journal_id BIGINT, p_reconciled_by TEXT
        ) RETURNS VOID AS $$
        BEGIN
            IF p_fill_id IS NULL OR p_journal_id IS NULL OR p_reconciled_by IS NULL THEN
                RAISE EXCEPTION 'reconcile_fill() arguments must be non-NULL';
            END IF;
            IF LENGTH(TRIM(p_reconciled_by)) = 0 THEN
                RAISE EXCEPTION 'reconciled_by must be non-empty';
            END IF;
            PERFORM set_config('superhydra.allow_fill_reconcile', 'on', true);
            BEGIN
                UPDATE trading.fills
                SET journal_id = p_journal_id, reconciled_at = NOW(), reconciled_by = p_reconciled_by
                WHERE id = p_fill_id;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Fill % does not exist', p_fill_id;
                END IF;
            EXCEPTION WHEN OTHERS THEN
                PERFORM set_config('superhydra.allow_fill_reconcile', 'off', true);
                RAISE;
            END;
            PERFORM set_config('superhydra.allow_fill_reconcile', 'off', true);
        END;
        $$ LANGUAGE plpgsql;
    """)

    # =====================================================================
    # TRIGGER 15: process_cancel_update_order
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION trading.process_cancel_update_order()
        RETURNS TRIGGER AS $$
        DECLARE
            v_order RECORD;
            v_remaining NUMERIC(38,18);
            v_old_state TEXT;
            v_new_state TEXT;
        BEGIN
            SELECT id, state, filled_quantity, quantity, venue_namespace
            INTO v_order FROM trading.orders WHERE id = NEW.order_id FOR UPDATE;
            IF v_order.id IS NULL THEN
                RAISE EXCEPTION 'Order % does not exist', NEW.order_id;
            END IF;
            IF v_order.state = 'pending_submit' THEN
                RAISE EXCEPTION
                    'Cancel event cannot be inserted for pending_submit order %; use trading.transition_order_state(... canceled) for local pre-submit cancel',
                    v_order.id;
            END IF;
            IF v_order.state IN ('filled', 'canceled', 'rejected', 'expired', 'failed_submit') THEN
                RAISE EXCEPTION 'Cannot accept cancel for order % in terminal state %',
                    v_order.id, v_order.state;
            END IF;
            IF v_order.venue_namespace IS DISTINCT FROM NEW.venue_namespace THEN
                RAISE EXCEPTION 'Cancel venue_namespace=% does not match order venue_namespace=%',
                    NEW.venue_namespace, v_order.venue_namespace;
            END IF;
            v_remaining := v_order.quantity - v_order.filled_quantity;
            IF NEW.quantity_canceled > v_remaining THEN
                RAISE EXCEPTION
                    'quantity_canceled=% exceeds remaining=% (order qty=%, filled=%)',
                    NEW.quantity_canceled, v_remaining, v_order.quantity, v_order.filled_quantity;
            END IF;
            v_old_state := v_order.state;
            v_new_state := 'canceled';
            PERFORM set_config('superhydra.allow_order_cancel_update', 'on', true);
            PERFORM set_config('superhydra.allow_order_state_event_insert', 'on', true);
            BEGIN
                UPDATE trading.orders SET state = v_new_state, updated_at = NOW() WHERE id = v_order.id;
                INSERT INTO trading.order_state_events (
                    order_id, old_state, new_state, transition_reason,
                    source_type, source_namespace, source_id, created_by, metadata
                ) VALUES (
                    v_order.id, v_old_state, v_new_state,
                    'cancel confirmed: ' || NEW.cancel_reason,
                    NEW.source_type, NEW.venue_namespace, NEW.source_id, 'system',
                    jsonb_build_object('cancel_id', NEW.id, 'cancel_reason', NEW.cancel_reason,
                                       'quantity_canceled', NEW.quantity_canceled)
                );
            EXCEPTION WHEN OTHERS THEN
                PERFORM set_config('superhydra.allow_order_cancel_update', 'off', true);
                PERFORM set_config('superhydra.allow_order_state_event_insert', 'off', true);
                RAISE;
            END;
            PERFORM set_config('superhydra.allow_order_cancel_update', 'off', true);
            PERFORM set_config('superhydra.allow_order_state_event_insert', 'off', true);
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER cancels_process_update_order
            AFTER INSERT ON trading.cancels
            FOR EACH ROW EXECUTE FUNCTION trading.process_cancel_update_order();
    """)

    # =====================================================================
    # TRIGGER 16: Cancels append-only
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION trading.prevent_cancel_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'trading.cancels is append-only; UPDATE/DELETE forbidden.';
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER cancels_no_update
            BEFORE UPDATE ON trading.cancels
            FOR EACH ROW EXECUTE FUNCTION trading.prevent_cancel_mutation();
        CREATE TRIGGER cancels_no_delete
            BEFORE DELETE ON trading.cancels
            FOR EACH ROW EXECUTE FUNCTION trading.prevent_cancel_mutation();
    """)

    # =====================================================================
    # TRIGGER 17: oms_outbox initial-state guard
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION trading.enforce_outbox_initial_state()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.state != 'pending' THEN
                RAISE EXCEPTION 'Outbox rows must be inserted with state=pending (got %)', NEW.state;
            END IF;
            IF NEW.attempts != 0 THEN
                RAISE EXCEPTION 'Outbox rows must be inserted with attempts=0';
            END IF;
            IF NEW.completed_at IS NOT NULL THEN
                RAISE EXCEPTION 'Outbox rows must be inserted with completed_at=NULL';
            END IF;
            IF NEW.last_error IS NOT NULL THEN
                RAISE EXCEPTION 'Outbox rows must be inserted with last_error=NULL';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER oms_outbox_initial_state_guard
            BEFORE INSERT ON trading.oms_outbox
            FOR EACH ROW EXECUTE FUNCTION trading.enforce_outbox_initial_state();
    """)

    # =====================================================================
    # TRIGGER 18: oms_outbox state machine
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION trading.enforce_oms_outbox_state_machine()
        RETURNS TRIGGER AS $$
        DECLARE
            v_valid_transitions TEXT[];
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.order_id IS DISTINCT FROM OLD.order_id
               OR NEW.operation IS DISTINCT FROM OLD.operation
               OR NEW.operation_key IS DISTINCT FROM OLD.operation_key
               OR NEW.payload IS DISTINCT FROM OLD.payload
               OR NEW.created_at IS DISTINCT FROM OLD.created_at
               OR NEW.max_attempts IS DISTINCT FROM OLD.max_attempts
            THEN
                RAISE EXCEPTION 'oms_outbox % identity/payload fields are immutable', OLD.id;
            END IF;
            IF OLD.state IN ('succeeded', 'abandoned') THEN
                IF NEW.state IS DISTINCT FROM OLD.state
                   OR NEW.attempts IS DISTINCT FROM OLD.attempts
                   OR NEW.last_error IS DISTINCT FROM OLD.last_error
                   OR NEW.completed_at IS DISTINCT FROM OLD.completed_at
                THEN
                    RAISE EXCEPTION 'Outbox row % is in terminal state %; immutable', OLD.id, OLD.state;
                END IF;
                RETURN NEW;
            END IF;
            IF NEW.state IS NOT DISTINCT FROM OLD.state THEN
                NEW.updated_at := NOW();
                RETURN NEW;
            END IF;
            CASE OLD.state
                WHEN 'pending' THEN
                    v_valid_transitions := ARRAY['in_flight'];
                WHEN 'in_flight' THEN
                    v_valid_transitions := ARRAY['pending', 'succeeded', 'failed', 'abandoned'];
                WHEN 'failed' THEN
                    v_valid_transitions := ARRAY['pending', 'abandoned'];
                ELSE
                    v_valid_transitions := ARRAY[]::TEXT[];
            END CASE;
            IF NOT (NEW.state = ANY(v_valid_transitions)) THEN
                RAISE EXCEPTION 'Invalid outbox state transition for %: % -> % (valid: %)',
                    OLD.id, OLD.state, NEW.state, v_valid_transitions;
            END IF;
            IF NEW.state IN ('succeeded', 'abandoned') AND NEW.completed_at IS NULL THEN
                NEW.completed_at := NOW();
            END IF;
            NEW.updated_at := NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION trading.prevent_oms_outbox_delete()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'trading.oms_outbox forbids DELETE.';
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER oms_outbox_state_machine
            BEFORE UPDATE ON trading.oms_outbox
            FOR EACH ROW EXECUTE FUNCTION trading.enforce_oms_outbox_state_machine();
        CREATE TRIGGER oms_outbox_no_delete
            BEFORE DELETE ON trading.oms_outbox
            FOR EACH ROW EXECUTE FUNCTION trading.prevent_oms_outbox_delete();
    """)

    # =====================================================================
    # TRIGGER 19: oms_outbox operation gate
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION trading.enforce_outbox_operation_gate()
        RETURNS TRIGGER AS $$
        DECLARE
            v_order_state TEXT;
            v_allowed_states TEXT[];
        BEGIN
            SELECT state INTO v_order_state FROM trading.orders WHERE id = NEW.order_id FOR UPDATE;
            IF v_order_state IS NULL THEN
                RAISE EXCEPTION 'Order % does not exist', NEW.order_id;
            END IF;
            IF NEW.operation = 'submit' THEN
                IF v_order_state != 'pending_submit' THEN
                    RAISE EXCEPTION 'submit outbox requires order in pending_submit state (got %)', v_order_state;
                END IF;
                PERFORM trading.assert_order_reservation_ready(NEW.order_id);
            ELSIF NEW.operation = 'cancel' THEN
                v_allowed_states := ARRAY['cancel_requested', 'submitted', 'working', 'partially_filled'];
                IF NOT (v_order_state = ANY(v_allowed_states)) THEN
                    RAISE EXCEPTION 'cancel outbox requires order in one of % (got %)', v_allowed_states, v_order_state;
                END IF;
            ELSIF NEW.operation IN ('amend', 'replace') THEN
                v_allowed_states := ARRAY['working', 'partially_filled'];
                IF NOT (v_order_state = ANY(v_allowed_states)) THEN
                    RAISE EXCEPTION '% outbox requires order in one of % (got %)',
                        NEW.operation, v_allowed_states, v_order_state;
                END IF;
            ELSE
                RAISE EXCEPTION 'Unknown outbox operation: %', NEW.operation;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER oms_outbox_operation_gate
            BEFORE INSERT ON trading.oms_outbox
            FOR EACH ROW EXECUTE FUNCTION trading.enforce_outbox_operation_gate();
    """)

    # =====================================================================
    # TRIGGER 20: oms_outbox operation_key format validation
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION trading.enforce_outbox_operation_key_format()
        RETURNS TRIGGER AS $$
        DECLARE
            v_order_uuid UUID;
            v_expected_prefix TEXT;
            v_suffix TEXT;
        BEGIN
            SELECT order_uuid INTO v_order_uuid FROM trading.orders WHERE id = NEW.order_id;
            IF v_order_uuid IS NULL THEN
                RAISE EXCEPTION 'Order % does not exist', NEW.order_id;
            END IF;
            IF NEW.operation = 'submit' THEN
                v_expected_prefix := 'submit:' || v_order_uuid::text;
                IF NEW.operation_key != v_expected_prefix THEN
                    RAISE EXCEPTION 'submit outbox operation_key must be exactly %; got %',
                        v_expected_prefix, NEW.operation_key;
                END IF;
            ELSIF NEW.operation = 'cancel' THEN
                v_expected_prefix := 'cancel:' || v_order_uuid::text;
                IF NEW.operation_key != v_expected_prefix THEN
                    RAISE EXCEPTION 'cancel outbox operation_key must be exactly %; got %',
                        v_expected_prefix, NEW.operation_key;
                END IF;
            ELSIF NEW.operation = 'amend' THEN
                v_expected_prefix := 'amend:' || v_order_uuid::text || ':';
                IF NOT NEW.operation_key LIKE (v_expected_prefix || '%') THEN
                    RAISE EXCEPTION 'amend outbox operation_key must start with %; got %',
                        v_expected_prefix, NEW.operation_key;
                END IF;
                v_suffix := substr(NEW.operation_key, length(v_expected_prefix) + 1);
                IF length(v_suffix) = 0 THEN
                    RAISE EXCEPTION 'amend outbox operation_key requires a non-empty sequence suffix; got %',
                        NEW.operation_key;
                END IF;
            ELSIF NEW.operation = 'replace' THEN
                v_expected_prefix := 'replace:' || v_order_uuid::text || ':';
                IF NOT NEW.operation_key LIKE (v_expected_prefix || '%') THEN
                    RAISE EXCEPTION 'replace outbox operation_key must start with %; got %',
                        v_expected_prefix, NEW.operation_key;
                END IF;
                v_suffix := substr(NEW.operation_key, length(v_expected_prefix) + 1);
                IF length(v_suffix) = 0 THEN
                    RAISE EXCEPTION 'replace outbox operation_key requires a non-empty sequence suffix; got %',
                        NEW.operation_key;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER oms_outbox_operation_key_format
            BEFORE INSERT ON trading.oms_outbox
            FOR EACH ROW EXECUTE FUNCTION trading.enforce_outbox_operation_key_format();
    """)

    # =====================================================================
    # Verification block (v5.2-final: 31 functions total)
    # =====================================================================
    op.execute("""
        DO $$
        DECLARE
            expected_tables TEXT[] := ARRAY[
                'order_intents', 'order_groups', 'order_reservations',
                'orders', 'order_state_events', 'fills', 'cancels', 'oms_outbox'
            ];
            expected_functions TEXT[] := ARRAY[
                'enforce_intent_lineage_consistency',
                'enforce_order_intent_promotion',
                'prevent_intent_mutation',
                'prevent_group_mutation',
                'enforce_reservation_intent_consistency',
                'enforce_reservation_lifecycle',
                'prevent_reservation_delete',
                'release_reservation',
                'assert_order_reservation_ready',
                'assert_order_submit_ready',
                'enforce_order_initial_state',
                'enforce_order_intent_consistency',
                'enforce_order_identity_immutability',
                'prevent_order_delete',
                'enforce_order_state_machine',
                'transition_order_state',
                'record_order_ack',
                'record_order_reject',
                'record_order_failed_submit',
                'enforce_state_event_audit',
                'enforce_fill_initial_state',
                'process_fill_update_order',
                'enforce_fill_reconciliation',
                'reconcile_fill',
                'process_cancel_update_order',
                'prevent_cancel_mutation',
                'enforce_outbox_initial_state',
                'enforce_oms_outbox_state_machine',
                'prevent_oms_outbox_delete',
                'enforce_outbox_operation_gate',
                'enforce_outbox_operation_key_format'
            ];
            t TEXT;
            f TEXT;
            actual_count INT;
        BEGIN
            FOREACH t IN ARRAY expected_tables LOOP
                SELECT COUNT(*) INTO actual_count
                FROM information_schema.tables
                WHERE table_schema = 'trading' AND table_name = t AND table_type = 'BASE TABLE';
                IF actual_count != 1 THEN
                    RAISE EXCEPTION 'trading.% not created', t;
                END IF;
            END LOOP;
            FOREACH f IN ARRAY expected_functions LOOP
                SELECT COUNT(*) INTO actual_count
                FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'trading' AND p.proname = f;
                IF actual_count < 1 THEN
                    RAISE EXCEPTION 'trading.%() not created', f;
                END IF;
            END LOOP;
            RAISE NOTICE 'trading orders / OMS persistence verified (0007 v5.2-final) -- 31 trading functions';
        END;
        $$;
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS oms_outbox_operation_key_format ON trading.oms_outbox;")
    op.execute("DROP TRIGGER IF EXISTS oms_outbox_operation_gate ON trading.oms_outbox;")
    op.execute("DROP FUNCTION IF EXISTS trading.enforce_outbox_operation_key_format();")
    op.execute("DROP FUNCTION IF EXISTS trading.enforce_outbox_operation_gate();")
    op.execute("DROP TRIGGER IF EXISTS oms_outbox_no_delete ON trading.oms_outbox;")
    op.execute("DROP TRIGGER IF EXISTS oms_outbox_state_machine ON trading.oms_outbox;")
    op.execute("DROP TRIGGER IF EXISTS oms_outbox_initial_state_guard ON trading.oms_outbox;")
    op.execute("DROP FUNCTION IF EXISTS trading.prevent_oms_outbox_delete();")
    op.execute("DROP FUNCTION IF EXISTS trading.enforce_oms_outbox_state_machine();")
    op.execute("DROP FUNCTION IF EXISTS trading.enforce_outbox_initial_state();")
    op.execute("DROP TRIGGER IF EXISTS cancels_no_delete ON trading.cancels;")
    op.execute("DROP TRIGGER IF EXISTS cancels_no_update ON trading.cancels;")
    op.execute("DROP TRIGGER IF EXISTS cancels_process_update_order ON trading.cancels;")
    op.execute("DROP FUNCTION IF EXISTS trading.prevent_cancel_mutation();")
    op.execute("DROP FUNCTION IF EXISTS trading.process_cancel_update_order();")
    op.execute("DROP FUNCTION IF EXISTS trading.reconcile_fill(BIGINT, BIGINT, TEXT);")
    op.execute("DROP TRIGGER IF EXISTS fills_no_delete ON trading.fills;")
    op.execute("DROP TRIGGER IF EXISTS fills_reconciliation_gate ON trading.fills;")
    op.execute("DROP TRIGGER IF EXISTS fills_process_update_order ON trading.fills;")
    op.execute("DROP TRIGGER IF EXISTS fills_initial_state_guard ON trading.fills;")
    op.execute("DROP FUNCTION IF EXISTS trading.enforce_fill_reconciliation();")
    op.execute("DROP FUNCTION IF EXISTS trading.process_fill_update_order();")
    op.execute("DROP FUNCTION IF EXISTS trading.enforce_fill_initial_state();")
    op.execute("DROP TRIGGER IF EXISTS order_state_events_no_delete ON trading.order_state_events;")
    op.execute("DROP TRIGGER IF EXISTS order_state_events_no_update ON trading.order_state_events;")
    op.execute("DROP TRIGGER IF EXISTS order_state_events_insert_gate ON trading.order_state_events;")
    op.execute("DROP FUNCTION IF EXISTS trading.enforce_state_event_audit();")
    op.execute("DROP FUNCTION IF EXISTS trading.record_order_failed_submit(BIGINT, TEXT, TEXT);")
    op.execute("DROP FUNCTION IF EXISTS trading.record_order_reject(BIGINT, TEXT, JSONB, TEXT);")
    op.execute("DROP FUNCTION IF EXISTS trading.record_order_ack(BIGINT, TEXT, JSONB, TEXT);")
    op.execute("DROP FUNCTION IF EXISTS trading.transition_order_state(BIGINT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB);")
    op.execute("DROP TRIGGER IF EXISTS orders_state_machine ON trading.orders;")
    op.execute("DROP TRIGGER IF EXISTS orders_no_delete ON trading.orders;")
    op.execute("DROP TRIGGER IF EXISTS orders_identity_immutability ON trading.orders;")
    op.execute("DROP TRIGGER IF EXISTS orders_intent_consistency ON trading.orders;")
    op.execute("DROP TRIGGER IF EXISTS orders_initial_state_guard ON trading.orders;")
    op.execute("DROP FUNCTION IF EXISTS trading.enforce_order_state_machine();")
    op.execute("DROP FUNCTION IF EXISTS trading.prevent_order_delete();")
    op.execute("DROP FUNCTION IF EXISTS trading.enforce_order_identity_immutability();")
    op.execute("DROP FUNCTION IF EXISTS trading.enforce_order_intent_consistency();")
    op.execute("DROP FUNCTION IF EXISTS trading.enforce_order_initial_state();")
    op.execute("DROP FUNCTION IF EXISTS trading.assert_order_submit_ready(BIGINT);")
    op.execute("DROP FUNCTION IF EXISTS trading.assert_order_reservation_ready(BIGINT);")
    op.execute("DROP FUNCTION IF EXISTS trading.release_reservation(BIGINT, TEXT, TEXT);")
    op.execute("DROP TRIGGER IF EXISTS order_reservations_no_delete ON trading.order_reservations;")
    op.execute("DROP TRIGGER IF EXISTS order_reservations_lifecycle ON trading.order_reservations;")
    op.execute("DROP TRIGGER IF EXISTS order_reservations_intent_consistency ON trading.order_reservations;")
    op.execute("DROP FUNCTION IF EXISTS trading.prevent_reservation_delete();")
    op.execute("DROP FUNCTION IF EXISTS trading.enforce_reservation_lifecycle();")
    op.execute("DROP FUNCTION IF EXISTS trading.enforce_reservation_intent_consistency();")
    op.execute("DROP TRIGGER IF EXISTS order_groups_no_delete ON trading.order_groups;")
    op.execute("DROP TRIGGER IF EXISTS order_groups_no_update ON trading.order_groups;")
    op.execute("DROP FUNCTION IF EXISTS trading.prevent_group_mutation();")
    op.execute("DROP TRIGGER IF EXISTS order_intents_no_delete ON trading.order_intents;")
    op.execute("DROP TRIGGER IF EXISTS order_intents_no_update ON trading.order_intents;")
    op.execute("DROP TRIGGER IF EXISTS order_intents_promotion_gate ON trading.order_intents;")
    op.execute("DROP TRIGGER IF EXISTS order_intents_lineage_consistency ON trading.order_intents;")
    op.execute("DROP FUNCTION IF EXISTS trading.prevent_intent_mutation();")
    op.execute("DROP FUNCTION IF EXISTS trading.enforce_order_intent_promotion();")
    op.execute("DROP FUNCTION IF EXISTS trading.enforce_intent_lineage_consistency();")
    op.execute("DROP TABLE IF EXISTS trading.oms_outbox;")
    op.execute("DROP TABLE IF EXISTS trading.cancels;")
    op.execute("DROP TABLE IF EXISTS trading.fills;")
    op.execute("DROP TABLE IF EXISTS trading.order_state_events;")
    op.execute("DROP TABLE IF EXISTS trading.orders;")
    op.execute("DROP TABLE IF EXISTS trading.order_reservations;")
    op.execute("DROP TABLE IF EXISTS trading.order_groups;")
    op.execute("DROP TABLE IF EXISTS trading.order_intents;")
