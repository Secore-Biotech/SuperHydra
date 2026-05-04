"""positions

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-04

Position derivation layer (v1.5) — 5 tables, 15 functions.

Foundational principle:
  Positions are DERIVED state, not source-of-truth. Lots and snapshots
  derive only from accounting-reconciled fills (trading.fills with
  journal_id NOT NULL AND journal posted+non-voided+source-matched).

Approved by external reviewer on 2026-05-04 (round 5).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS positions;")

    # TABLE 1: position_snapshots
    op.execute("""
        CREATE TABLE positions.position_snapshots (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            snapshot_uuid UUID NOT NULL DEFAULT gen_uuidv7() UNIQUE,
            portfolio_id BIGINT NOT NULL REFERENCES registry.portfolios(id),
            strategy_id BIGINT NOT NULL REFERENCES registry.strategies(id),
            account_id BIGINT NOT NULL REFERENCES registry.accounts(id),
            instrument_id BIGINT NOT NULL REFERENCES registry.instruments(id),
            quantity NUMERIC(38,18) NOT NULL,
            avg_cost_basis NUMERIC(38,18),
            realized_pnl_usd NUMERIC(38,12) NOT NULL DEFAULT 0,
            position_environment TEXT NOT NULL CHECK (position_environment IN (
                'LIVE', 'SHADOW', 'REPLAY', 'BACKTEST'
            )),
            snapshot_at TIMESTAMPTZ NOT NULL,
            fill_cutoff_at TIMESTAMPTZ NOT NULL,
            last_fill_id BIGINT REFERENCES trading.fills(id),
            contributing_fill_count INT NOT NULL CHECK (contributing_fill_count >= 0),
            computation_hash TEXT NOT NULL,
            computation_version TEXT NOT NULL,
            computation_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK ((quantity = 0 AND avg_cost_basis IS NULL) OR (quantity != 0 AND avg_cost_basis IS NOT NULL AND avg_cost_basis > 0)),
            CHECK (LENGTH(TRIM(computation_hash)) > 0),
            CHECK (LENGTH(TRIM(computation_version)) > 0),
            CHECK (LENGTH(TRIM(created_by)) > 0),
            CHECK (jsonb_typeof(computation_metadata) = 'object'),
            CHECK (fill_cutoff_at <= snapshot_at),
            UNIQUE (portfolio_id, strategy_id, account_id, instrument_id, position_environment, snapshot_at, computation_hash)
        );
    """)
    op.execute("""
        CREATE INDEX idx_position_snapshots_attribution ON positions.position_snapshots(
            portfolio_id, strategy_id, account_id, instrument_id, position_environment, snapshot_at DESC);
        CREATE INDEX idx_position_snapshots_at ON positions.position_snapshots(snapshot_at DESC);
    """)

    # TABLE 2: position_snapshot_fills
    op.execute("""
        CREATE TABLE positions.position_snapshot_fills (
            snapshot_id BIGINT NOT NULL REFERENCES positions.position_snapshots(id),
            fill_id BIGINT NOT NULL REFERENCES trading.fills(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (snapshot_id, fill_id)
        );
    """)
    op.execute("CREATE INDEX idx_snapshot_fills_fill ON positions.position_snapshot_fills(fill_id);")

    # TABLE 3: position_lots
    op.execute("""
        CREATE TABLE positions.position_lots (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            lot_uuid UUID NOT NULL DEFAULT gen_uuidv7() UNIQUE,
            portfolio_id BIGINT NOT NULL REFERENCES registry.portfolios(id),
            strategy_id BIGINT NOT NULL REFERENCES registry.strategies(id),
            account_id BIGINT NOT NULL REFERENCES registry.accounts(id),
            instrument_id BIGINT NOT NULL REFERENCES registry.instruments(id),
            opening_fill_id BIGINT NOT NULL REFERENCES trading.fills(id),
            side TEXT NOT NULL CHECK (side IN ('long', 'short')),
            original_quantity NUMERIC(38,18) NOT NULL CHECK (original_quantity > 0),
            cost_basis NUMERIC(38,18) NOT NULL CHECK (cost_basis > 0),
            notional_value_usd NUMERIC(38,12) NOT NULL CHECK (notional_value_usd > 0),
            opened_at TIMESTAMPTZ NOT NULL,
            position_environment TEXT NOT NULL CHECK (position_environment IN ('LIVE', 'SHADOW', 'REPLAY', 'BACKTEST')),
            closed_quantity NUMERIC(38,18) NOT NULL DEFAULT 0 CHECK (closed_quantity >= 0),
            open_quantity NUMERIC(38,18) GENERATED ALWAYS AS (original_quantity - closed_quantity) STORED,
            fully_closed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (closed_quantity <= original_quantity),
            CHECK ((closed_quantity < original_quantity AND fully_closed_at IS NULL) OR (closed_quantity = original_quantity AND fully_closed_at IS NOT NULL)),
            UNIQUE (opening_fill_id)
        );
    """)
    op.execute("""
        CREATE INDEX idx_lots_attribution_open ON positions.position_lots(
            portfolio_id, strategy_id, account_id, instrument_id,
            position_environment, side, opened_at, id) WHERE fully_closed_at IS NULL;
        CREATE INDEX idx_lots_opening_fill ON positions.position_lots(opening_fill_id);
    """)

    # TABLE 4: position_lot_closures
    op.execute("""
        CREATE TABLE positions.position_lot_closures (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            closure_uuid UUID NOT NULL DEFAULT gen_uuidv7() UNIQUE,
            lot_id BIGINT NOT NULL REFERENCES positions.position_lots(id),
            closing_fill_id BIGINT NOT NULL REFERENCES trading.fills(id),
            portfolio_id BIGINT NOT NULL REFERENCES registry.portfolios(id),
            strategy_id BIGINT NOT NULL REFERENCES registry.strategies(id),
            account_id BIGINT NOT NULL REFERENCES registry.accounts(id),
            instrument_id BIGINT NOT NULL REFERENCES registry.instruments(id),
            closed_quantity NUMERIC(38,18) NOT NULL CHECK (closed_quantity > 0),
            closing_price NUMERIC(38,18) NOT NULL CHECK (closing_price > 0),
            realized_pnl_usd NUMERIC(38,12) NOT NULL,
            position_environment TEXT NOT NULL CHECK (position_environment IN ('LIVE', 'SHADOW', 'REPLAY', 'BACKTEST')),
            closed_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (lot_id, closing_fill_id)
        );
    """)
    op.execute("""
        CREATE INDEX idx_closures_lot ON positions.position_lot_closures(lot_id, closed_at);
        CREATE INDEX idx_closures_closing_fill ON positions.position_lot_closures(closing_fill_id);
        CREATE INDEX idx_closures_attribution_at ON positions.position_lot_closures(
            portfolio_id, strategy_id, account_id, instrument_id, position_environment, closed_at DESC);
    """)

    # TABLE 5: position_reconciliations
    op.execute("""
        CREATE TABLE positions.position_reconciliations (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            reconciliation_uuid UUID NOT NULL DEFAULT gen_uuidv7() UNIQUE,
            portfolio_id BIGINT NOT NULL REFERENCES registry.portfolios(id),
            strategy_id BIGINT NOT NULL REFERENCES registry.strategies(id),
            account_id BIGINT NOT NULL REFERENCES registry.accounts(id),
            instrument_id BIGINT NOT NULL REFERENCES registry.instruments(id),
            snapshot_id BIGINT NOT NULL REFERENCES positions.position_snapshots(id),
            computed_quantity NUMERIC(38,18) NOT NULL,
            venue_reported_quantity NUMERIC(38,18) NOT NULL,
            drift NUMERIC(38,18) GENERATED ALWAYS AS (computed_quantity - venue_reported_quantity) STORED,
            drift_tolerance NUMERIC(38,18) NOT NULL CHECK (drift_tolerance >= 0),
            drift_within_tolerance BOOLEAN GENERATED ALWAYS AS (ABS(computed_quantity - venue_reported_quantity) <= drift_tolerance) STORED,
            position_environment TEXT NOT NULL CHECK (position_environment IN ('LIVE', 'SHADOW', 'REPLAY', 'BACKTEST')),
            venue_namespace TEXT NOT NULL,
            venue_source_id TEXT,
            raw_venue_response JSONB NOT NULL,
            reconciled_at TIMESTAMPTZ NOT NULL,
            reconciled_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (LENGTH(TRIM(venue_namespace)) > 0),
            CHECK (venue_source_id IS NULL OR LENGTH(TRIM(venue_source_id)) > 0),
            CHECK (LENGTH(TRIM(reconciled_by)) > 0),
            CHECK (jsonb_typeof(raw_venue_response) = 'object')
        );
    """)
    op.execute("""
        CREATE INDEX idx_reconciliations_snapshot ON positions.position_reconciliations(snapshot_id);
        CREATE INDEX idx_reconciliations_drift_alert ON positions.position_reconciliations(reconciled_at DESC) WHERE drift_within_tolerance = false;
        CREATE INDEX idx_reconciliations_attribution_at ON positions.position_reconciliations(
            portfolio_id, strategy_id, account_id, instrument_id, position_environment, reconciled_at DESC);
    """)

    # TRIGGER FUNCTIONS - Insert gates
    for tbl, fn, hint in [
        ('position_snapshots', 'enforce_snapshot_audit', 'compute_position_snapshot()'),
        ('position_snapshot_fills', 'enforce_snapshot_fills_audit', 'compute_position_snapshot()'),
    ]:
        flag = f'superhydra.allow_{tbl.replace("position_", "position_")}_insert'
        if tbl == 'position_snapshots':
            flag = 'superhydra.allow_position_snapshot_insert'
        elif tbl == 'position_snapshot_fills':
            flag = 'superhydra.allow_position_snapshot_fills_insert'
        op.execute(f"""
            CREATE OR REPLACE FUNCTION positions.{fn}() RETURNS TRIGGER AS $$
            BEGIN
                IF TG_OP = 'INSERT' THEN
                    IF current_setting('{flag}', true) IS DISTINCT FROM 'on' THEN
                        RAISE EXCEPTION 'Direct INSERT into positions.{tbl} is forbidden; use positions.{hint}';
                    END IF;
                    RETURN NEW;
                ELSE
                    RAISE EXCEPTION 'positions.{tbl} is append-only; UPDATE/DELETE forbidden.';
                END IF;
            END;
            $$ LANGUAGE plpgsql;
        """)
        op.execute(f"""
            CREATE TRIGGER {tbl}_a_insert_gate BEFORE INSERT ON positions.{tbl}
                FOR EACH ROW EXECUTE FUNCTION positions.{fn}();
            CREATE TRIGGER {tbl}_no_update BEFORE UPDATE ON positions.{tbl}
                FOR EACH ROW EXECUTE FUNCTION positions.{fn}();
            CREATE TRIGGER {tbl}_no_delete BEFORE DELETE ON positions.{tbl}
                FOR EACH ROW EXECUTE FUNCTION positions.{fn}();
        """)

    # Lot insert gate
    op.execute("""
        CREATE OR REPLACE FUNCTION positions.enforce_lot_insert() RETURNS TRIGGER AS $$
        BEGIN
            IF current_setting('superhydra.allow_position_lot_insert', true) IS DISTINCT FROM 'on' THEN
                RAISE EXCEPTION 'Direct INSERT into positions.position_lots is forbidden; use positions.process_fill_to_lots()';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("CREATE TRIGGER position_lots_a_insert_gate BEFORE INSERT ON positions.position_lots FOR EACH ROW EXECUTE FUNCTION positions.enforce_lot_insert();")

    # Lot opening-fill consistency trigger
    op.execute("""
        CREATE OR REPLACE FUNCTION positions.enforce_lot_opening_fill_consistency() RETURNS TRIGGER AS $$
        DECLARE
            v_fill RECORD; v_intent RECORD; v_expected_side TEXT;
            v_expected_notional NUMERIC(38,12); v_existing_closure_qty NUMERIC(38,18);
            v_expected_residual NUMERIC(38,18);
        BEGIN
            SELECT id, order_id, instrument_id, side, quantity, price, fill_environment, filled_at, journal_id, venue_namespace
            INTO v_fill FROM trading.fills WHERE id = NEW.opening_fill_id;
            IF v_fill.id IS NULL THEN RAISE EXCEPTION 'opening_fill_id % does not exist', NEW.opening_fill_id; END IF;
            IF v_fill.journal_id IS NULL THEN RAISE EXCEPTION 'Lot cannot be opened from unreconciled fill % (journal_id IS NULL)', NEW.opening_fill_id; END IF;
            SELECT i.portfolio_id, i.strategy_id, o.account_id INTO v_intent
            FROM trading.orders o JOIN trading.order_intents i ON i.id = o.intent_id WHERE o.id = v_fill.order_id;
            IF v_intent.portfolio_id IS NULL THEN RAISE EXCEPTION 'Fill % order/intent attribution not found', NEW.opening_fill_id; END IF;
            IF NEW.portfolio_id IS DISTINCT FROM v_intent.portfolio_id THEN RAISE EXCEPTION 'Lot portfolio_id=% does not match fill intent portfolio_id=%', NEW.portfolio_id, v_intent.portfolio_id; END IF;
            IF NEW.strategy_id IS DISTINCT FROM v_intent.strategy_id THEN RAISE EXCEPTION 'Lot strategy_id=% does not match fill intent strategy_id=%', NEW.strategy_id, v_intent.strategy_id; END IF;
            IF NEW.account_id IS DISTINCT FROM v_intent.account_id THEN RAISE EXCEPTION 'Lot account_id=% does not match fill order account_id=%', NEW.account_id, v_intent.account_id; END IF;
            IF NEW.instrument_id IS DISTINCT FROM v_fill.instrument_id THEN RAISE EXCEPTION 'Lot instrument_id=% does not match fill instrument_id=%', NEW.instrument_id, v_fill.instrument_id; END IF;
            IF NEW.position_environment IS DISTINCT FROM v_fill.fill_environment THEN RAISE EXCEPTION 'Lot position_environment=% does not match fill fill_environment=%', NEW.position_environment, v_fill.fill_environment; END IF;
            v_expected_side := CASE v_fill.side WHEN 'buy' THEN 'long' ELSE 'short' END;
            IF NEW.side IS DISTINCT FROM v_expected_side THEN RAISE EXCEPTION 'Lot side=% does not match expected from fill side=% (expected %)', NEW.side, v_fill.side, v_expected_side; END IF;
            IF NEW.cost_basis IS DISTINCT FROM v_fill.price THEN RAISE EXCEPTION 'Lot cost_basis=% does not match fill price=%', NEW.cost_basis, v_fill.price; END IF;
            SELECT COALESCE(SUM(closed_quantity), 0) INTO v_existing_closure_qty FROM positions.position_lot_closures WHERE closing_fill_id = NEW.opening_fill_id;
            v_expected_residual := v_fill.quantity - v_existing_closure_qty;
            IF ABS(NEW.original_quantity - v_expected_residual) > 0.000000000000000001 THEN
                RAISE EXCEPTION 'Lot original_quantity=% does not match expected residual=% (fill.quantity=% - prior closures on this fill=%)', NEW.original_quantity, v_expected_residual, v_fill.quantity, v_existing_closure_qty;
            END IF;
            v_expected_notional := NEW.original_quantity * NEW.cost_basis;
            IF ABS(NEW.notional_value_usd - v_expected_notional) > 0.000001 THEN RAISE EXCEPTION 'Lot notional_value_usd=% does not match qty*cost_basis=%', NEW.notional_value_usd, v_expected_notional; END IF;
            IF NEW.opened_at IS DISTINCT FROM v_fill.filled_at THEN RAISE EXCEPTION 'Lot opened_at=% does not match fill filled_at=%', NEW.opened_at, v_fill.filled_at; END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("CREATE TRIGGER position_lots_b_opening_fill_consistency BEFORE INSERT ON positions.position_lots FOR EACH ROW EXECUTE FUNCTION positions.enforce_lot_opening_fill_consistency();")

    # Lot lifecycle trigger
    op.execute("""
        CREATE OR REPLACE FUNCTION positions.enforce_lot_lifecycle() RETURNS TRIGGER AS $$
        DECLARE v_lifecycle_changed BOOLEAN; v_update_flag TEXT;
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id OR NEW.lot_uuid IS DISTINCT FROM OLD.lot_uuid
               OR NEW.portfolio_id IS DISTINCT FROM OLD.portfolio_id OR NEW.strategy_id IS DISTINCT FROM OLD.strategy_id
               OR NEW.account_id IS DISTINCT FROM OLD.account_id OR NEW.instrument_id IS DISTINCT FROM OLD.instrument_id
               OR NEW.opening_fill_id IS DISTINCT FROM OLD.opening_fill_id OR NEW.side IS DISTINCT FROM OLD.side
               OR NEW.original_quantity IS DISTINCT FROM OLD.original_quantity OR NEW.cost_basis IS DISTINCT FROM OLD.cost_basis
               OR NEW.notional_value_usd IS DISTINCT FROM OLD.notional_value_usd OR NEW.opened_at IS DISTINCT FROM OLD.opened_at
               OR NEW.position_environment IS DISTINCT FROM OLD.position_environment OR NEW.created_at IS DISTINCT FROM OLD.created_at
            THEN RAISE EXCEPTION 'Lot % identity fields are immutable', OLD.id; END IF;
            v_lifecycle_changed := (NEW.closed_quantity IS DISTINCT FROM OLD.closed_quantity OR NEW.fully_closed_at IS DISTINCT FROM OLD.fully_closed_at OR NEW.updated_at IS DISTINCT FROM OLD.updated_at);
            IF v_lifecycle_changed THEN
                v_update_flag := current_setting('superhydra.allow_position_lot_update', true);
                IF v_update_flag IS DISTINCT FROM 'on' THEN RAISE EXCEPTION 'Direct mutation of position_lot lifecycle fields (closed_quantity, fully_closed_at, updated_at) is forbidden; use positions.process_fill_to_lots()'; END IF;
                IF NEW.closed_quantity < OLD.closed_quantity THEN RAISE EXCEPTION 'Lot % closed_quantity cannot decrease (% -> %)', OLD.id, OLD.closed_quantity, NEW.closed_quantity; END IF;
                IF OLD.fully_closed_at IS NOT NULL THEN RAISE EXCEPTION 'Lot % is already fully closed; lifecycle is immutable', OLD.id; END IF;
                NEW.updated_at := NOW();
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION positions.prevent_lot_delete() RETURNS TRIGGER AS $$
        BEGIN RAISE EXCEPTION 'positions.position_lots forbids DELETE; lots are audit records.'; END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER position_lots_lifecycle BEFORE UPDATE ON positions.position_lots FOR EACH ROW EXECUTE FUNCTION positions.enforce_lot_lifecycle();
        CREATE TRIGGER position_lots_no_delete BEFORE DELETE ON positions.position_lots FOR EACH ROW EXECUTE FUNCTION positions.prevent_lot_delete();
    """)

    # Closure audit gate
    op.execute("""
        CREATE OR REPLACE FUNCTION positions.enforce_closure_audit() RETURNS TRIGGER AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF current_setting('superhydra.allow_position_lot_closure_insert', true) IS DISTINCT FROM 'on' THEN
                    RAISE EXCEPTION 'Direct INSERT into positions.position_lot_closures is forbidden; use positions.process_fill_to_lots()';
                END IF;
                RETURN NEW;
            ELSE
                RAISE EXCEPTION 'positions.position_lot_closures is append-only; UPDATE/DELETE forbidden.';
            END IF;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER position_lot_closures_a_insert_gate BEFORE INSERT ON positions.position_lot_closures FOR EACH ROW EXECUTE FUNCTION positions.enforce_closure_audit();
        CREATE TRIGGER position_lot_closures_no_update BEFORE UPDATE ON positions.position_lot_closures FOR EACH ROW EXECUTE FUNCTION positions.enforce_closure_audit();
        CREATE TRIGGER position_lot_closures_no_delete BEFORE DELETE ON positions.position_lot_closures FOR EACH ROW EXECUTE FUNCTION positions.enforce_closure_audit();
    """)

    # Closure consistency trigger
    op.execute("""
        CREATE OR REPLACE FUNCTION positions.enforce_closure_consistency() RETURNS TRIGGER AS $$
        DECLARE
            v_lot RECORD; v_closing_fill RECORD; v_closing_intent RECORD;
            v_expected_closing_side TEXT; v_older_open_exists BOOLEAN;
            v_expected_pnl NUMERIC(38,12); v_cumulative_closure_qty NUMERIC(38,18);
            v_existing_lot_closure_qty NUMERIC(38,18);
        BEGIN
            SELECT id, portfolio_id, strategy_id, account_id, instrument_id, side, original_quantity, closed_quantity, cost_basis, position_environment, opened_at
            INTO v_lot FROM positions.position_lots WHERE id = NEW.lot_id FOR UPDATE;
            IF v_lot.id IS NULL THEN RAISE EXCEPTION 'Lot % does not exist', NEW.lot_id; END IF;
            IF NEW.portfolio_id IS DISTINCT FROM v_lot.portfolio_id OR NEW.strategy_id IS DISTINCT FROM v_lot.strategy_id OR NEW.account_id IS DISTINCT FROM v_lot.account_id OR NEW.instrument_id IS DISTINCT FROM v_lot.instrument_id THEN
                RAISE EXCEPTION 'Closure attribution does not match lot attribution (lot % portfolio=%, strategy=%, account=%, instrument=%)', NEW.lot_id, v_lot.portfolio_id, v_lot.strategy_id, v_lot.account_id, v_lot.instrument_id;
            END IF;
            IF NEW.position_environment IS DISTINCT FROM v_lot.position_environment THEN RAISE EXCEPTION 'Closure environment=% does not match lot environment=%', NEW.position_environment, v_lot.position_environment; END IF;
            SELECT id, order_id, instrument_id, side, quantity, price, fill_environment, filled_at, journal_id INTO v_closing_fill FROM trading.fills WHERE id = NEW.closing_fill_id;
            IF v_closing_fill.id IS NULL THEN RAISE EXCEPTION 'Closing fill % does not exist', NEW.closing_fill_id; END IF;
            IF v_closing_fill.journal_id IS NULL THEN RAISE EXCEPTION 'Closing fill % is not yet reconciled (journal_id IS NULL)', NEW.closing_fill_id; END IF;
            IF v_closing_fill.instrument_id IS DISTINCT FROM v_lot.instrument_id THEN RAISE EXCEPTION 'Closing fill instrument_id=% does not match lot instrument_id=%', v_closing_fill.instrument_id, v_lot.instrument_id; END IF;
            IF v_closing_fill.fill_environment IS DISTINCT FROM v_lot.position_environment THEN RAISE EXCEPTION 'Closing fill environment=% does not match lot environment=%', v_closing_fill.fill_environment, v_lot.position_environment; END IF;
            IF v_closing_fill.filled_at < v_lot.opened_at THEN RAISE EXCEPTION 'Closing fill filled_at=% is before lot opened_at=% (impossible history)', v_closing_fill.filled_at, v_lot.opened_at; END IF;
            SELECT i.portfolio_id, i.strategy_id, o.account_id INTO v_closing_intent FROM trading.orders o JOIN trading.order_intents i ON i.id = o.intent_id WHERE o.id = v_closing_fill.order_id;
            IF v_closing_intent.portfolio_id IS DISTINCT FROM v_lot.portfolio_id OR v_closing_intent.strategy_id IS DISTINCT FROM v_lot.strategy_id OR v_closing_intent.account_id IS DISTINCT FROM v_lot.account_id THEN
                RAISE EXCEPTION 'Closing fill attribution does not match lot attribution';
            END IF;
            v_expected_closing_side := CASE v_lot.side WHEN 'long' THEN 'sell' WHEN 'short' THEN 'buy' END;
            IF v_closing_fill.side IS DISTINCT FROM v_expected_closing_side THEN RAISE EXCEPTION 'Closing fill side=% cannot close % lot (expected %)', v_closing_fill.side, v_lot.side, v_expected_closing_side; END IF;
            IF EXISTS (SELECT 1 FROM positions.position_lot_closures plc WHERE plc.lot_id = NEW.lot_id AND plc.closed_at > NEW.closed_at) THEN
                RAISE EXCEPTION 'Retroactive closure insertion is forbidden: lot % has existing closure with closed_at > % (rebuild required)', NEW.lot_id, NEW.closed_at;
            END IF;
            SELECT EXISTS (
                SELECT 1 FROM positions.position_lots older
                WHERE older.portfolio_id = v_lot.portfolio_id AND older.strategy_id = v_lot.strategy_id
                  AND older.account_id = v_lot.account_id AND older.instrument_id = v_lot.instrument_id
                  AND older.position_environment = v_lot.position_environment AND older.side = v_lot.side
                  AND older.opened_at <= NEW.closed_at
                  AND (older.opened_at, older.id) < (v_lot.opened_at, v_lot.id)
                  AND (older.original_quantity - COALESCE((SELECT SUM(plc.closed_quantity) FROM positions.position_lot_closures plc WHERE plc.lot_id = older.id AND plc.closed_at <= NEW.closed_at), 0)) > 0
            ) INTO v_older_open_exists;
            IF v_older_open_exists THEN RAISE EXCEPTION 'FIFO violation (as-of %): older open % lot exists for same attribution; cannot close lot % first', NEW.closed_at, v_lot.side, v_lot.id; END IF;
            SELECT COALESCE(SUM(closed_quantity), 0) INTO v_existing_lot_closure_qty FROM positions.position_lot_closures WHERE lot_id = NEW.lot_id;
            IF (v_existing_lot_closure_qty + NEW.closed_quantity) > v_lot.original_quantity THEN
                RAISE EXCEPTION 'Cumulative closure quantity for lot % exceeds original quantity: existing %, new %, original %', NEW.lot_id, v_existing_lot_closure_qty, NEW.closed_quantity, v_lot.original_quantity;
            END IF;
            SELECT COALESCE(SUM(closed_quantity), 0) INTO v_cumulative_closure_qty FROM positions.position_lot_closures WHERE closing_fill_id = NEW.closing_fill_id;
            IF (v_cumulative_closure_qty + NEW.closed_quantity) > v_closing_fill.quantity THEN
                RAISE EXCEPTION 'Cumulative closure quantity=% (existing % + new %) exceeds closing fill quantity=%', v_cumulative_closure_qty + NEW.closed_quantity, v_cumulative_closure_qty, NEW.closed_quantity, v_closing_fill.quantity;
            END IF;
            IF v_lot.side = 'long' THEN v_expected_pnl := (NEW.closing_price - v_lot.cost_basis) * NEW.closed_quantity;
            ELSE v_expected_pnl := (v_lot.cost_basis - NEW.closing_price) * NEW.closed_quantity; END IF;
            IF ABS(NEW.realized_pnl_usd - v_expected_pnl) > 0.000001 THEN
                RAISE EXCEPTION 'Closure realized_pnl_usd=% does not match expected=% (lot side=%, cost_basis=%, closing_price=%, qty=%)', NEW.realized_pnl_usd, v_expected_pnl, v_lot.side, v_lot.cost_basis, NEW.closing_price, NEW.closed_quantity;
            END IF;
            IF NEW.closing_price IS DISTINCT FROM v_closing_fill.price THEN RAISE EXCEPTION 'Closure closing_price=% does not match closing fill price=%', NEW.closing_price, v_closing_fill.price; END IF;
            IF NEW.closed_at IS DISTINCT FROM v_closing_fill.filled_at THEN RAISE EXCEPTION 'Closure closed_at=% does not match closing fill filled_at=%', NEW.closed_at, v_closing_fill.filled_at; END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("CREATE TRIGGER position_lot_closures_b_consistency BEFORE INSERT ON positions.position_lot_closures FOR EACH ROW EXECUTE FUNCTION positions.enforce_closure_consistency();")

    # Reconciliation triggers
    op.execute("""
        CREATE OR REPLACE FUNCTION positions.enforce_reconciliation_audit() RETURNS TRIGGER AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF current_setting('superhydra.allow_position_reconciliation_insert', true) IS DISTINCT FROM 'on' THEN
                    RAISE EXCEPTION 'Direct INSERT into positions.position_reconciliations is forbidden; use positions.record_position_reconciliation()';
                END IF;
                RETURN NEW;
            ELSE
                RAISE EXCEPTION 'positions.position_reconciliations is append-only; UPDATE/DELETE forbidden.';
            END IF;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER position_reconciliations_a_insert_gate BEFORE INSERT ON positions.position_reconciliations FOR EACH ROW EXECUTE FUNCTION positions.enforce_reconciliation_audit();
        CREATE TRIGGER position_reconciliations_no_update BEFORE UPDATE ON positions.position_reconciliations FOR EACH ROW EXECUTE FUNCTION positions.enforce_reconciliation_audit();
        CREATE TRIGGER position_reconciliations_no_delete BEFORE DELETE ON positions.position_reconciliations FOR EACH ROW EXECUTE FUNCTION positions.enforce_reconciliation_audit();
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION positions.enforce_reconciliation_snapshot_consistency() RETURNS TRIGGER AS $$
        DECLARE v_snap RECORD;
        BEGIN
            SELECT portfolio_id, strategy_id, account_id, instrument_id, position_environment, quantity INTO v_snap FROM positions.position_snapshots WHERE id = NEW.snapshot_id;
            IF v_snap.portfolio_id IS NULL THEN RAISE EXCEPTION 'Snapshot % does not exist', NEW.snapshot_id; END IF;
            IF NEW.portfolio_id IS DISTINCT FROM v_snap.portfolio_id OR NEW.strategy_id IS DISTINCT FROM v_snap.strategy_id OR NEW.account_id IS DISTINCT FROM v_snap.account_id OR NEW.instrument_id IS DISTINCT FROM v_snap.instrument_id THEN
                RAISE EXCEPTION 'Reconciliation attribution does not match snapshot %', NEW.snapshot_id;
            END IF;
            IF NEW.position_environment IS DISTINCT FROM v_snap.position_environment THEN RAISE EXCEPTION 'Reconciliation environment=% does not match snapshot environment=%', NEW.position_environment, v_snap.position_environment; END IF;
            IF NEW.computed_quantity IS DISTINCT FROM v_snap.quantity THEN RAISE EXCEPTION 'Reconciliation computed_quantity=% does not match snapshot quantity=%', NEW.computed_quantity, v_snap.quantity; END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("CREATE TRIGGER position_reconciliations_b_snapshot_consistency BEFORE INSERT ON positions.position_reconciliations FOR EACH ROW EXECUTE FUNCTION positions.enforce_reconciliation_snapshot_consistency();")

    op.execute("""
        CREATE OR REPLACE FUNCTION positions.notice_reconciliation_drift() RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.drift_within_tolerance = false THEN
                RAISE NOTICE 'Position reconciliation drift outside tolerance: portfolio=%, strategy=%, instrument=%, env=%, computed=%, venue=%, drift=%, tolerance=%',
                    NEW.portfolio_id, NEW.strategy_id, NEW.instrument_id, NEW.position_environment,
                    NEW.computed_quantity, NEW.venue_reported_quantity, NEW.drift, NEW.drift_tolerance;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("CREATE TRIGGER position_reconciliations_drift_notice AFTER INSERT ON positions.position_reconciliations FOR EACH ROW EXECUTE FUNCTION positions.notice_reconciliation_drift();")

    # CONTROLLED FUNCTION: process_fill_to_lots
    op.execute("""
        CREATE OR REPLACE FUNCTION positions.process_fill_to_lots(p_fill_id BIGINT) RETURNS VOID AS $$
        DECLARE
            v_fill RECORD; v_intent RECORD; v_journal RECORD;
            v_quote_asset_symbol TEXT; v_fill_side TEXT; v_opposing_side TEXT;
            v_remaining_to_close NUMERIC(38,18); v_lot RECORD;
            v_close_qty NUMERIC(38,18); v_realized_pnl NUMERIC(38,12);
            v_existing_lot_count INT; v_existing_closure_count INT;
            v_later_processed_count INT; v_lock_key TEXT;
        BEGIN
            SELECT f.id, f.order_id, f.instrument_id, f.side, f.quantity, f.price, f.fill_environment, f.filled_at, f.journal_id, f.venue_namespace, f.venue_fill_id
            INTO v_fill FROM trading.fills f WHERE f.id = p_fill_id FOR UPDATE;
            IF v_fill.id IS NULL THEN RAISE EXCEPTION 'Fill % does not exist', p_fill_id; END IF;
            IF v_fill.journal_id IS NULL THEN RAISE EXCEPTION 'Fill % is not yet reconciled (journal_id IS NULL); cannot derive lots', p_fill_id; END IF;
            SELECT i.portfolio_id, i.strategy_id, o.account_id INTO v_intent FROM trading.orders o JOIN trading.order_intents i ON i.id = o.intent_id WHERE o.id = v_fill.order_id;
            IF v_intent.portfolio_id IS NULL THEN RAISE EXCEPTION 'Fill % order/intent attribution not found', p_fill_id; END IF;
            v_lock_key := format('positions:%s:%s:%s:%s:%s', v_intent.portfolio_id, v_intent.strategy_id, v_intent.account_id, v_fill.instrument_id, v_fill.fill_environment);
            PERFORM pg_advisory_xact_lock(hashtextextended(v_lock_key, 0));
            SELECT j.id, j.status, j.journal_type, j.voided_at, j.source_type, j.source_namespace, j.source_id, j.portfolio_id, j.strategy_id
            INTO v_journal FROM accounting.journals j WHERE j.id = v_fill.journal_id FOR UPDATE;
            IF v_journal.id IS NULL THEN RAISE EXCEPTION 'Linked journal % does not exist for fill %', v_fill.journal_id, p_fill_id; END IF;
            IF v_journal.status != 'posted' THEN RAISE EXCEPTION 'Linked journal % must be posted (got %) for fill %', v_fill.journal_id, v_journal.status, p_fill_id; END IF;
            IF v_journal.journal_type != 'trade' THEN RAISE EXCEPTION 'Linked journal % must be journal_type=trade (got %) for fill %', v_fill.journal_id, v_journal.journal_type, p_fill_id; END IF;
            IF v_journal.voided_at IS NOT NULL THEN RAISE EXCEPTION 'Linked journal % has been voided (voided_at=%); fill % cannot derive lots', v_fill.journal_id, v_journal.voided_at, p_fill_id; END IF;
            IF v_journal.source_type IS DISTINCT FROM 'fill' THEN RAISE EXCEPTION 'Linked journal % source_type must be fill (got %)', v_fill.journal_id, v_journal.source_type; END IF;
            IF v_journal.source_namespace IS DISTINCT FROM v_fill.venue_namespace THEN RAISE EXCEPTION 'Linked journal source_namespace=% does not match fill venue_namespace=%', v_journal.source_namespace, v_fill.venue_namespace; END IF;
            IF v_journal.source_id IS DISTINCT FROM v_fill.venue_fill_id THEN RAISE EXCEPTION 'Linked journal source_id=% does not match fill venue_fill_id=%', v_journal.source_id, v_fill.venue_fill_id; END IF;
            IF v_journal.portfolio_id IS DISTINCT FROM v_intent.portfolio_id THEN RAISE EXCEPTION 'Linked journal portfolio_id=% does not match fill intent portfolio_id=%', v_journal.portfolio_id, v_intent.portfolio_id; END IF;
            IF v_journal.strategy_id IS DISTINCT FROM v_intent.strategy_id THEN RAISE EXCEPTION 'Linked journal strategy_id=% does not match fill intent strategy_id=%', v_journal.strategy_id, v_intent.strategy_id; END IF;
            SELECT a.symbol INTO v_quote_asset_symbol FROM registry.instruments inst JOIN registry.assets a ON a.id = inst.quote_asset_id WHERE inst.id = v_fill.instrument_id;
            IF v_quote_asset_symbol IS NULL THEN RAISE EXCEPTION 'Instrument % has no quote asset; positions require USD-equivalent quote', v_fill.instrument_id; END IF;
            IF v_quote_asset_symbol NOT IN ('USD', 'USDT', 'USDC', 'BUSD') THEN RAISE EXCEPTION 'Instrument % has non-USD quote asset %; Phase 1 positions support USD/USDT/USDC/BUSD-quoted instruments only', v_fill.instrument_id, v_quote_asset_symbol; END IF;
            SELECT COUNT(*) INTO v_existing_lot_count FROM positions.position_lots WHERE opening_fill_id = p_fill_id;
            SELECT COUNT(*) INTO v_existing_closure_count FROM positions.position_lot_closures WHERE closing_fill_id = p_fill_id;
            IF v_existing_lot_count > 0 OR v_existing_closure_count > 0 THEN RETURN; END IF;
            SELECT COUNT(*) INTO v_later_processed_count FROM (
                SELECT f.id, f.filled_at FROM trading.fills f JOIN trading.orders o ON o.id = f.order_id JOIN trading.order_intents i ON i.id = o.intent_id
                WHERE i.portfolio_id = v_intent.portfolio_id AND i.strategy_id = v_intent.strategy_id AND o.account_id = v_intent.account_id
                  AND f.instrument_id = v_fill.instrument_id AND f.fill_environment = v_fill.fill_environment AND f.id != p_fill_id
                  AND (f.filled_at, f.id) > (v_fill.filled_at, p_fill_id)
                  AND EXISTS (SELECT 1 FROM positions.position_lots pl WHERE pl.opening_fill_id = f.id UNION SELECT 1 FROM positions.position_lot_closures plc WHERE plc.closing_fill_id = f.id)
            ) AS later_processed;
            IF v_later_processed_count > 0 THEN RAISE EXCEPTION 'Fill % cannot be processed: % later-filled fill(s) for same attribution/instrument/environment have already been processed. Out-of-order reconciliation requires a replay/rebuild migration.', p_fill_id, v_later_processed_count; END IF;
            v_fill_side := v_fill.side;
            v_opposing_side := CASE v_fill_side WHEN 'buy' THEN 'short' WHEN 'sell' THEN 'long' END;
            v_remaining_to_close := v_fill.quantity;
            FOR v_lot IN
                SELECT id, side, original_quantity, closed_quantity, cost_basis, opened_at, position_environment
                FROM positions.position_lots
                WHERE portfolio_id = v_intent.portfolio_id AND strategy_id = v_intent.strategy_id AND account_id = v_intent.account_id
                  AND instrument_id = v_fill.instrument_id AND side = v_opposing_side AND fully_closed_at IS NULL
                  AND position_environment = v_fill.fill_environment
                ORDER BY opened_at, id FOR UPDATE
            LOOP
                EXIT WHEN v_remaining_to_close = 0;
                v_close_qty := LEAST(v_lot.original_quantity - v_lot.closed_quantity, v_remaining_to_close);
                IF v_lot.side = 'long' THEN v_realized_pnl := (v_fill.price - v_lot.cost_basis) * v_close_qty;
                ELSE v_realized_pnl := (v_lot.cost_basis - v_fill.price) * v_close_qty; END IF;
                PERFORM set_config('superhydra.allow_position_lot_closure_insert', 'on', true);
                BEGIN
                    INSERT INTO positions.position_lot_closures (lot_id, closing_fill_id, portfolio_id, strategy_id, account_id, instrument_id, closed_quantity, closing_price, realized_pnl_usd, position_environment, closed_at)
                    VALUES (v_lot.id, p_fill_id, v_intent.portfolio_id, v_intent.strategy_id, v_intent.account_id, v_fill.instrument_id, v_close_qty, v_fill.price, v_realized_pnl, v_fill.fill_environment, v_fill.filled_at);
                EXCEPTION WHEN OTHERS THEN PERFORM set_config('superhydra.allow_position_lot_closure_insert', 'off', true); RAISE; END;
                PERFORM set_config('superhydra.allow_position_lot_closure_insert', 'off', true);
                PERFORM set_config('superhydra.allow_position_lot_update', 'on', true);
                BEGIN
                    UPDATE positions.position_lots SET closed_quantity = closed_quantity + v_close_qty,
                        fully_closed_at = CASE WHEN closed_quantity + v_close_qty = original_quantity THEN v_fill.filled_at ELSE NULL END, updated_at = NOW() WHERE id = v_lot.id;
                EXCEPTION WHEN OTHERS THEN PERFORM set_config('superhydra.allow_position_lot_update', 'off', true); RAISE; END;
                PERFORM set_config('superhydra.allow_position_lot_update', 'off', true);
                v_remaining_to_close := v_remaining_to_close - v_close_qty;
            END LOOP;
            IF v_remaining_to_close > 0 THEN
                PERFORM set_config('superhydra.allow_position_lot_insert', 'on', true);
                BEGIN
                    INSERT INTO positions.position_lots (portfolio_id, strategy_id, account_id, instrument_id, opening_fill_id, side, original_quantity, cost_basis, notional_value_usd, position_environment, opened_at)
                    VALUES (v_intent.portfolio_id, v_intent.strategy_id, v_intent.account_id, v_fill.instrument_id, p_fill_id,
                            CASE v_fill_side WHEN 'buy' THEN 'long' ELSE 'short' END, v_remaining_to_close, v_fill.price, v_remaining_to_close * v_fill.price, v_fill.fill_environment, v_fill.filled_at);
                EXCEPTION WHEN OTHERS THEN PERFORM set_config('superhydra.allow_position_lot_insert', 'off', true); RAISE; END;
                PERFORM set_config('superhydra.allow_position_lot_insert', 'off', true);
            END IF;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # CONTROLLED FUNCTION: compute_position_snapshot
    op.execute("""
        CREATE OR REPLACE FUNCTION positions.compute_position_snapshot(
            p_portfolio_id BIGINT, p_strategy_id BIGINT, p_account_id BIGINT, p_instrument_id BIGINT,
            p_position_environment TEXT, p_snapshot_at TIMESTAMPTZ, p_fill_cutoff_at TIMESTAMPTZ,
            p_computation_version TEXT, p_created_by TEXT, p_metadata JSONB DEFAULT '{}'::jsonb
        ) RETURNS BIGINT AS $$
        DECLARE
            v_signed_quantity NUMERIC(38,18) := 0; v_long_open NUMERIC(38,18) := 0;
            v_long_cost_notional NUMERIC(38,18) := 0; v_short_open NUMERIC(38,18) := 0;
            v_short_cost_notional NUMERIC(38,18) := 0; v_avg_cost_basis NUMERIC(38,18);
            v_realized_total NUMERIC(38,12) := 0; v_last_fill_id BIGINT;
            v_contributing_fill_count INT := 0; v_computation_hash TEXT;
            v_snapshot_id BIGINT; v_fill_id BIGINT; v_fill_ids BIGINT[]; v_lock_key TEXT;
        BEGIN
            IF p_portfolio_id IS NULL OR p_strategy_id IS NULL OR p_account_id IS NULL OR p_instrument_id IS NULL
               OR p_position_environment IS NULL OR p_snapshot_at IS NULL OR p_fill_cutoff_at IS NULL
               OR p_computation_version IS NULL OR p_created_by IS NULL
            THEN RAISE EXCEPTION 'compute_position_snapshot() arguments must be non-NULL'; END IF;
            IF p_position_environment NOT IN ('LIVE', 'SHADOW', 'REPLAY', 'BACKTEST') THEN RAISE EXCEPTION 'invalid position_environment: %', p_position_environment; END IF;
            IF p_fill_cutoff_at > p_snapshot_at THEN RAISE EXCEPTION 'fill_cutoff_at (%) cannot be after snapshot_at (%)', p_fill_cutoff_at, p_snapshot_at; END IF;
            v_lock_key := format('positions:%s:%s:%s:%s:%s', p_portfolio_id, p_strategy_id, p_account_id, p_instrument_id, p_position_environment);
            PERFORM pg_advisory_xact_lock(hashtextextended(v_lock_key, 0));
            WITH lots_with_as_of_close AS (
                SELECT pl.id, pl.side, pl.cost_basis, pl.original_quantity,
                    COALESCE((SELECT SUM(plc.closed_quantity) FROM positions.position_lot_closures plc WHERE plc.lot_id = pl.id AND plc.closed_at <= p_fill_cutoff_at), 0) AS as_of_closed
                FROM positions.position_lots pl
                WHERE pl.portfolio_id = p_portfolio_id AND pl.strategy_id = p_strategy_id AND pl.account_id = p_account_id
                  AND pl.instrument_id = p_instrument_id AND pl.position_environment = p_position_environment AND pl.opened_at <= p_fill_cutoff_at
            )
            SELECT COALESCE(SUM(CASE WHEN side = 'long' THEN (original_quantity - as_of_closed) END), 0),
                   COALESCE(SUM(CASE WHEN side = 'long' THEN (original_quantity - as_of_closed) * cost_basis END), 0),
                   COALESCE(SUM(CASE WHEN side = 'short' THEN (original_quantity - as_of_closed) END), 0),
                   COALESCE(SUM(CASE WHEN side = 'short' THEN (original_quantity - as_of_closed) * cost_basis END), 0)
            INTO v_long_open, v_long_cost_notional, v_short_open, v_short_cost_notional
            FROM lots_with_as_of_close WHERE (original_quantity - as_of_closed) > 0;
            v_signed_quantity := v_long_open - v_short_open;
            IF v_signed_quantity > 0 THEN v_avg_cost_basis := v_long_cost_notional / v_long_open;
            ELSIF v_signed_quantity < 0 THEN v_avg_cost_basis := v_short_cost_notional / v_short_open;
            ELSE v_avg_cost_basis := NULL; END IF;
            SELECT COALESCE(SUM(realized_pnl_usd), 0) INTO v_realized_total FROM positions.position_lot_closures
            WHERE portfolio_id = p_portfolio_id AND strategy_id = p_strategy_id AND account_id = p_account_id
              AND instrument_id = p_instrument_id AND position_environment = p_position_environment AND closed_at <= p_fill_cutoff_at;
            SELECT array_agg(DISTINCT fid ORDER BY fid) INTO v_fill_ids FROM (
                SELECT opening_fill_id AS fid FROM positions.position_lots
                WHERE portfolio_id = p_portfolio_id AND strategy_id = p_strategy_id AND account_id = p_account_id
                  AND instrument_id = p_instrument_id AND position_environment = p_position_environment AND opened_at <= p_fill_cutoff_at
                UNION
                SELECT closing_fill_id AS fid FROM positions.position_lot_closures
                WHERE portfolio_id = p_portfolio_id AND strategy_id = p_strategy_id AND account_id = p_account_id
                  AND instrument_id = p_instrument_id AND position_environment = p_position_environment AND closed_at <= p_fill_cutoff_at
            ) AS contributors;
            v_contributing_fill_count := COALESCE(array_length(v_fill_ids, 1), 0);
            v_computation_hash := encode(digest(COALESCE(array_to_string(v_fill_ids, ','), ''), 'sha256'), 'hex');
            IF v_contributing_fill_count > 0 THEN
                SELECT f.id INTO v_last_fill_id FROM trading.fills f WHERE f.id = ANY(v_fill_ids) ORDER BY f.filled_at DESC, f.id DESC LIMIT 1;
            END IF;
            PERFORM set_config('superhydra.allow_position_snapshot_insert', 'on', true);
            BEGIN
                INSERT INTO positions.position_snapshots (portfolio_id, strategy_id, account_id, instrument_id,
                    quantity, avg_cost_basis, realized_pnl_usd, position_environment,
                    snapshot_at, fill_cutoff_at, last_fill_id, contributing_fill_count,
                    computation_hash, computation_version, computation_metadata, created_by)
                VALUES (p_portfolio_id, p_strategy_id, p_account_id, p_instrument_id,
                    v_signed_quantity, v_avg_cost_basis, v_realized_total, p_position_environment,
                    p_snapshot_at, p_fill_cutoff_at, v_last_fill_id, v_contributing_fill_count,
                    v_computation_hash, p_computation_version, p_metadata, p_created_by)
                RETURNING id INTO v_snapshot_id;
            EXCEPTION WHEN OTHERS THEN PERFORM set_config('superhydra.allow_position_snapshot_insert', 'off', true); RAISE; END;
            PERFORM set_config('superhydra.allow_position_snapshot_insert', 'off', true);
            IF v_contributing_fill_count > 0 THEN
                PERFORM set_config('superhydra.allow_position_snapshot_fills_insert', 'on', true);
                BEGIN
                    FOREACH v_fill_id IN ARRAY v_fill_ids LOOP
                        INSERT INTO positions.position_snapshot_fills (snapshot_id, fill_id) VALUES (v_snapshot_id, v_fill_id);
                    END LOOP;
                EXCEPTION WHEN OTHERS THEN PERFORM set_config('superhydra.allow_position_snapshot_fills_insert', 'off', true); RAISE; END;
                PERFORM set_config('superhydra.allow_position_snapshot_fills_insert', 'off', true);
            END IF;
            RETURN v_snapshot_id;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # CONTROLLED FUNCTION: record_position_reconciliation
    op.execute("""
        CREATE OR REPLACE FUNCTION positions.record_position_reconciliation(
            p_snapshot_id BIGINT, p_venue_reported_quantity NUMERIC(38,18),
            p_venue_namespace TEXT, p_venue_source_id TEXT, p_raw_venue_response JSONB,
            p_drift_tolerance NUMERIC(38,18), p_reconciled_by TEXT
        ) RETURNS BIGINT AS $$
        DECLARE v_snap RECORD; v_recon_id BIGINT;
        BEGIN
            IF p_snapshot_id IS NULL OR p_venue_reported_quantity IS NULL OR p_venue_namespace IS NULL
               OR p_raw_venue_response IS NULL OR p_drift_tolerance IS NULL OR p_reconciled_by IS NULL
            THEN RAISE EXCEPTION 'record_position_reconciliation() required arguments must be non-NULL'; END IF;
            IF LENGTH(TRIM(p_venue_namespace)) = 0 OR LENGTH(TRIM(p_reconciled_by)) = 0 THEN RAISE EXCEPTION 'venue_namespace and reconciled_by must be non-empty'; END IF;
            IF p_drift_tolerance < 0 THEN RAISE EXCEPTION 'drift_tolerance must be >= 0'; END IF;
            IF jsonb_typeof(p_raw_venue_response) != 'object' THEN RAISE EXCEPTION 'raw_venue_response must be a JSON object'; END IF;
            SELECT portfolio_id, strategy_id, account_id, instrument_id, quantity, position_environment INTO v_snap FROM positions.position_snapshots WHERE id = p_snapshot_id;
            IF v_snap.portfolio_id IS NULL THEN RAISE EXCEPTION 'Snapshot % does not exist', p_snapshot_id; END IF;
            PERFORM set_config('superhydra.allow_position_reconciliation_insert', 'on', true);
            BEGIN
                INSERT INTO positions.position_reconciliations (portfolio_id, strategy_id, account_id, instrument_id,
                    snapshot_id, computed_quantity, venue_reported_quantity, drift_tolerance, position_environment,
                    venue_namespace, venue_source_id, raw_venue_response, reconciled_at, reconciled_by)
                VALUES (v_snap.portfolio_id, v_snap.strategy_id, v_snap.account_id, v_snap.instrument_id,
                    p_snapshot_id, v_snap.quantity, p_venue_reported_quantity, p_drift_tolerance, v_snap.position_environment,
                    p_venue_namespace, p_venue_source_id, p_raw_venue_response, NOW(), p_reconciled_by)
                RETURNING id INTO v_recon_id;
            EXCEPTION WHEN OTHERS THEN PERFORM set_config('superhydra.allow_position_reconciliation_insert', 'off', true); RAISE; END;
            PERFORM set_config('superhydra.allow_position_reconciliation_insert', 'off', true);
            RETURN v_recon_id;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Cross-schema trigger on trading.fills
    op.execute("""
        CREATE OR REPLACE FUNCTION positions.fill_reconciled_to_lots() RETURNS TRIGGER AS $$
        BEGIN
            IF OLD.journal_id IS NULL AND NEW.journal_id IS NOT NULL THEN
                PERFORM positions.process_fill_to_lots(NEW.id);
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("CREATE TRIGGER fills_reconciled_derive_positions AFTER UPDATE OF journal_id ON trading.fills FOR EACH ROW EXECUTE FUNCTION positions.fill_reconciled_to_lots();")

    # Verification
    op.execute("""
        DO $$
        DECLARE
            expected_tables TEXT[] := ARRAY['position_snapshots', 'position_snapshot_fills', 'position_lots', 'position_lot_closures', 'position_reconciliations'];
            expected_functions TEXT[] := ARRAY[
                'enforce_snapshot_audit', 'enforce_snapshot_fills_audit', 'enforce_lot_insert',
                'enforce_lot_opening_fill_consistency', 'enforce_lot_lifecycle', 'prevent_lot_delete',
                'enforce_closure_audit', 'enforce_closure_consistency',
                'enforce_reconciliation_audit', 'enforce_reconciliation_snapshot_consistency',
                'notice_reconciliation_drift', 'process_fill_to_lots', 'compute_position_snapshot',
                'record_position_reconciliation', 'fill_reconciled_to_lots'
            ];
            t TEXT; f TEXT; actual_count INT;
        BEGIN
            FOREACH t IN ARRAY expected_tables LOOP
                SELECT COUNT(*) INTO actual_count FROM information_schema.tables WHERE table_schema = 'positions' AND table_name = t AND table_type = 'BASE TABLE';
                IF actual_count != 1 THEN RAISE EXCEPTION 'positions.% not created', t; END IF;
            END LOOP;
            FOREACH f IN ARRAY expected_functions LOOP
                SELECT COUNT(*) INTO actual_count FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'positions' AND p.proname = f;
                IF actual_count < 1 THEN RAISE EXCEPTION 'positions.%() not created', f; END IF;
            END LOOP;
            RAISE NOTICE 'positions verified (0008 v1.5) -- 15 functions in positions schema';
        END;
        $$;
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS fills_reconciled_derive_positions ON trading.fills;")
    op.execute("DROP FUNCTION IF EXISTS positions.fill_reconciled_to_lots();")
    op.execute("DROP FUNCTION IF EXISTS positions.record_position_reconciliation(BIGINT, NUMERIC, TEXT, TEXT, JSONB, NUMERIC, TEXT);")
    op.execute("DROP FUNCTION IF EXISTS positions.compute_position_snapshot(BIGINT, BIGINT, BIGINT, BIGINT, TEXT, TIMESTAMPTZ, TIMESTAMPTZ, TEXT, TEXT, JSONB);")
    op.execute("DROP FUNCTION IF EXISTS positions.process_fill_to_lots(BIGINT);")
    op.execute("DROP TRIGGER IF EXISTS position_reconciliations_drift_notice ON positions.position_reconciliations;")
    op.execute("DROP TRIGGER IF EXISTS position_reconciliations_b_snapshot_consistency ON positions.position_reconciliations;")
    op.execute("DROP TRIGGER IF EXISTS position_reconciliations_no_delete ON positions.position_reconciliations;")
    op.execute("DROP TRIGGER IF EXISTS position_reconciliations_no_update ON positions.position_reconciliations;")
    op.execute("DROP TRIGGER IF EXISTS position_reconciliations_a_insert_gate ON positions.position_reconciliations;")
    op.execute("DROP FUNCTION IF EXISTS positions.notice_reconciliation_drift();")
    op.execute("DROP FUNCTION IF EXISTS positions.enforce_reconciliation_snapshot_consistency();")
    op.execute("DROP FUNCTION IF EXISTS positions.enforce_reconciliation_audit();")
    op.execute("DROP TRIGGER IF EXISTS position_lot_closures_b_consistency ON positions.position_lot_closures;")
    op.execute("DROP TRIGGER IF EXISTS position_lot_closures_no_delete ON positions.position_lot_closures;")
    op.execute("DROP TRIGGER IF EXISTS position_lot_closures_no_update ON positions.position_lot_closures;")
    op.execute("DROP TRIGGER IF EXISTS position_lot_closures_a_insert_gate ON positions.position_lot_closures;")
    op.execute("DROP FUNCTION IF EXISTS positions.enforce_closure_consistency();")
    op.execute("DROP FUNCTION IF EXISTS positions.enforce_closure_audit();")
    op.execute("DROP TRIGGER IF EXISTS position_lots_no_delete ON positions.position_lots;")
    op.execute("DROP TRIGGER IF EXISTS position_lots_lifecycle ON positions.position_lots;")
    op.execute("DROP TRIGGER IF EXISTS position_lots_b_opening_fill_consistency ON positions.position_lots;")
    op.execute("DROP TRIGGER IF EXISTS position_lots_a_insert_gate ON positions.position_lots;")
    op.execute("DROP FUNCTION IF EXISTS positions.prevent_lot_delete();")
    op.execute("DROP FUNCTION IF EXISTS positions.enforce_lot_lifecycle();")
    op.execute("DROP FUNCTION IF EXISTS positions.enforce_lot_opening_fill_consistency();")
    op.execute("DROP FUNCTION IF EXISTS positions.enforce_lot_insert();")
    op.execute("DROP TRIGGER IF EXISTS position_snapshot_fills_no_delete ON positions.position_snapshot_fills;")
    op.execute("DROP TRIGGER IF EXISTS position_snapshot_fills_no_update ON positions.position_snapshot_fills;")
    op.execute("DROP TRIGGER IF EXISTS position_snapshot_fills_a_insert_gate ON positions.position_snapshot_fills;")
    op.execute("DROP FUNCTION IF EXISTS positions.enforce_snapshot_fills_audit();")
    op.execute("DROP TRIGGER IF EXISTS position_snapshots_no_delete ON positions.position_snapshots;")
    op.execute("DROP TRIGGER IF EXISTS position_snapshots_no_update ON positions.position_snapshots;")
    op.execute("DROP TRIGGER IF EXISTS position_snapshots_a_insert_gate ON positions.position_snapshots;")
    op.execute("DROP FUNCTION IF EXISTS positions.enforce_snapshot_audit();")
    op.execute("DROP TABLE IF EXISTS positions.position_reconciliations;")
    op.execute("DROP TABLE IF EXISTS positions.position_lot_closures;")
    op.execute("DROP TABLE IF EXISTS positions.position_lots;")
    op.execute("DROP TABLE IF EXISTS positions.position_snapshot_fills;")
    op.execute("DROP TABLE IF EXISTS positions.position_snapshots;")
