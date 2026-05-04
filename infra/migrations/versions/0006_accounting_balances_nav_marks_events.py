"""accounting_balances_nav_marks_events

Revision ID: 0006
Revises: 0004c
Create Date: 2026-05-04

Eleven tables for accounting balances, NAV, marks, and events (v4).

Foundational principle:
  Append-only accounting events and valuation outputs tied to posted
  journals, exact mark sets, and valuation runs.

Lineage chain established here:
  posted journal -> event row (cashflow/fee/funding/borrow)
  mark_price -> mark_price_set -> valuation_run
  valuation_run -> nav_snapshot / strategy_pnl

v4 hardenings from review rounds 1-4:
  - enforce_event_journal_link locks journal row, rejects voided journals,
    forces cashflow journals to be portfolio-level (NULL strategy_id)
  - enforce_mark_price_set_not_used locks the mark_price_sets row
  - new lock_mark_price_set_for_valuation_run trigger on valuation_run insert
    pairs with the above to serialize item insertion vs run creation
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0004c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # =====================================================================
    # SCHEMA EXTENSION: Add 'borrow' to journals.journal_type
    # =====================================================================
    op.execute("""
        DO $$
        DECLARE
            constraint_name TEXT;
        BEGIN
            SELECT conname INTO constraint_name
            FROM pg_constraint
            WHERE conrelid = 'accounting.journals'::regclass
              AND contype = 'c'
              AND pg_get_constraintdef(oid) LIKE '%journal_type%trade%fee%funding%';

            IF constraint_name IS NOT NULL THEN
                EXECUTE 'ALTER TABLE accounting.journals DROP CONSTRAINT ' || quote_ident(constraint_name);
            END IF;
        END;
        $$;
    """)

    op.execute("""
        ALTER TABLE accounting.journals
        ADD CONSTRAINT journals_journal_type_check_v6
        CHECK (journal_type IN (
            'trade', 'fee', 'funding', 'cashflow', 'transfer',
            'mtm', 'adjustment', 'reversal', 'borrow'
        ));
    """)

    # =====================================================================
    # TABLE 1: accounting.mark_prices
    # =====================================================================
    op.execute("""
        CREATE TABLE accounting.mark_prices (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            instrument_id BIGINT NOT NULL REFERENCES registry.instruments(id),
            mark_type TEXT NOT NULL CHECK (mark_type IN (
                'mid', 'bid', 'ask', 'last', 'index', 'oracle',
                'conservative_exit', 'settlement'
            )),
            price NUMERIC(38,18) NOT NULL CHECK (price > 0),
            source TEXT NOT NULL,
            source_namespace TEXT NOT NULL DEFAULT 'global',
            source_id TEXT,
            source_timestamp TIMESTAMPTZ NOT NULL,
            confidence NUMERIC(5,4),
            raw_record_hash TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (LENGTH(TRIM(source)) > 0),
            CHECK (LENGTH(TRIM(source_namespace)) > 0),
            CHECK (source_id IS NULL OR LENGTH(TRIM(source_id)) > 0),
            CHECK (raw_record_hash IS NULL OR LENGTH(TRIM(raw_record_hash)) > 0),
            CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
        );
    """)

    op.execute("""
        CREATE UNIQUE INDEX uniq_mark_prices_full
            ON accounting.mark_prices(instrument_id, mark_type, source_namespace, source, source_timestamp);
        CREATE UNIQUE INDEX uniq_mark_prices_source_id
            ON accounting.mark_prices(source_namespace, source_id, instrument_id, mark_type)
            WHERE source_id IS NOT NULL;
        CREATE INDEX idx_mark_prices_instrument_at
            ON accounting.mark_prices(instrument_id, source_timestamp DESC);
        CREATE INDEX idx_mark_prices_type_at
            ON accounting.mark_prices(mark_type, source_timestamp DESC);
    """)

    # =====================================================================
    # TABLE 2: accounting.mark_price_sets
    # =====================================================================
    op.execute("""
        CREATE TABLE accounting.mark_price_sets (
            id UUID NOT NULL DEFAULT gen_uuidv7() PRIMARY KEY,
            set_hash TEXT NOT NULL UNIQUE,
            purpose TEXT NOT NULL CHECK (purpose IN (
                'performance_nav', 'conservative_nav', 'risk_monitoring', 'replay'
            )),
            description TEXT,
            created_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (LENGTH(TRIM(set_hash)) > 0),
            CHECK (LENGTH(TRIM(created_by)) > 0)
        );
    """)

    op.execute("CREATE INDEX idx_mark_price_sets_purpose ON accounting.mark_price_sets(purpose);")

    # =====================================================================
    # TABLE 3: accounting.mark_price_set_items
    # =====================================================================
    op.execute("""
        CREATE TABLE accounting.mark_price_set_items (
            mark_price_set_id UUID NOT NULL REFERENCES accounting.mark_price_sets(id),
            mark_price_id BIGINT NOT NULL REFERENCES accounting.mark_prices(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (mark_price_set_id, mark_price_id)
        );
    """)

    op.execute("CREATE INDEX idx_mark_price_set_items_mark_price ON accounting.mark_price_set_items(mark_price_id);")

    # =====================================================================
    # TABLE 4: accounting.valuation_runs
    # =====================================================================
    op.execute("""
        CREATE TABLE accounting.valuation_runs (
            id UUID NOT NULL DEFAULT gen_uuidv7() PRIMARY KEY,
            portfolio_id BIGINT NOT NULL REFERENCES registry.portfolios(id),
            run_type TEXT NOT NULL CHECK (run_type IN (
                'eod_close', 'recomputed_historical', 'replay', 'backtest'
            )),
            valuation_date DATE NOT NULL,
            mark_price_set_id UUID NOT NULL REFERENCES accounting.mark_price_sets(id),
            journal_cutoff_at TIMESTAMPTZ NOT NULL,
            engine_version TEXT NOT NULL,
            calculation_hash TEXT NOT NULL,
            run_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (LENGTH(TRIM(engine_version)) > 0),
            CHECK (LENGTH(TRIM(calculation_hash)) > 0),
            CHECK (LENGTH(TRIM(created_by)) > 0),
            CHECK (jsonb_typeof(run_metadata) = 'object')
        );
    """)

    op.execute("""
        CREATE INDEX idx_valuation_runs_portfolio_date
            ON accounting.valuation_runs(portfolio_id, valuation_date DESC);
        CREATE INDEX idx_valuation_runs_type
            ON accounting.valuation_runs(run_type, valuation_date DESC);
        CREATE INDEX idx_valuation_runs_mark_set
            ON accounting.valuation_runs(mark_price_set_id);
    """)

    # =====================================================================
    # TABLE 5: accounting.cash_balances
    # =====================================================================
    op.execute("""
        CREATE TABLE accounting.cash_balances (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            account_id BIGINT NOT NULL REFERENCES registry.accounts(id),
            asset_id BIGINT NOT NULL REFERENCES registry.assets(id),
            balance NUMERIC(38,18) NOT NULL,
            balance_locked NUMERIC(38,18) NOT NULL DEFAULT 0 CHECK (balance_locked >= 0),
            balance_available NUMERIC(38,18) GENERATED ALWAYS AS (balance - balance_locked) STORED,
            source TEXT NOT NULL CHECK (source IN ('venue_api', 'reconciler', 'manual')),
            source_namespace TEXT NOT NULL DEFAULT 'global',
            source_record_id TEXT,
            snapshot_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (
                (balance >= 0 AND balance_locked <= balance)
                OR
                (balance < 0 AND balance_locked = 0)
            ),
            CHECK (LENGTH(TRIM(source_namespace)) > 0),
            CHECK (source_record_id IS NULL OR LENGTH(TRIM(source_record_id)) > 0)
        );
    """)

    op.execute("""
        CREATE UNIQUE INDEX uniq_cash_balance_snapshot
            ON accounting.cash_balances(
                account_id, asset_id, snapshot_at, source,
                source_namespace, COALESCE(source_record_id, '')
            );
        CREATE INDEX idx_balances_account_asset_at
            ON accounting.cash_balances(account_id, asset_id, snapshot_at DESC);
        CREATE INDEX idx_balances_at
            ON accounting.cash_balances(snapshot_at DESC);
    """)

    # =====================================================================
    # TABLE 6: accounting.cashflows
    # =====================================================================
    op.execute("""
        CREATE TABLE accounting.cashflows (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            direction TEXT NOT NULL CHECK (direction IN (
                'deposit', 'withdrawal', 'internal_transfer'
            )),
            account_from_id BIGINT REFERENCES registry.accounts(id),
            account_to_id BIGINT REFERENCES registry.accounts(id),
            asset_id BIGINT NOT NULL REFERENCES registry.assets(id),
            amount NUMERIC(38,18) NOT NULL CHECK (amount > 0),
            fee NUMERIC(38,18) NOT NULL DEFAULT 0 CHECK (fee >= 0),
            external_tx_hash TEXT,
            source_type TEXT NOT NULL,
            source_namespace TEXT NOT NULL,
            source_id TEXT NOT NULL,
            operator_id TEXT NOT NULL,
            operator_signature TEXT,
            flow_at TIMESTAMPTZ NOT NULL,
            journal_id BIGINT NOT NULL UNIQUE REFERENCES accounting.journals(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (
                (direction = 'deposit' AND account_to_id IS NOT NULL AND account_from_id IS NULL)
                OR
                (direction = 'withdrawal' AND account_from_id IS NOT NULL AND account_to_id IS NULL)
                OR
                (direction = 'internal_transfer' AND account_from_id IS NOT NULL AND account_to_id IS NOT NULL
                 AND account_from_id <> account_to_id)
            ),
            CHECK (LENGTH(TRIM(source_type)) > 0),
            CHECK (LENGTH(TRIM(source_namespace)) > 0),
            CHECK (LENGTH(TRIM(source_id)) > 0),
            CHECK (LENGTH(TRIM(operator_id)) > 0),
            CHECK (operator_signature IS NULL OR LENGTH(TRIM(operator_signature)) > 0),
            CHECK (external_tx_hash IS NULL OR LENGTH(TRIM(external_tx_hash)) > 0)
        );
    """)

    op.execute("""
        CREATE UNIQUE INDEX uniq_cashflow_source
            ON accounting.cashflows(source_type, source_namespace, source_id);
        CREATE INDEX idx_cashflows_at ON accounting.cashflows(flow_at DESC);
        CREATE INDEX idx_cashflows_account_from
            ON accounting.cashflows(account_from_id) WHERE account_from_id IS NOT NULL;
        CREATE INDEX idx_cashflows_account_to
            ON accounting.cashflows(account_to_id) WHERE account_to_id IS NOT NULL;
    """)

    # =====================================================================
    # TABLE 7: accounting.fees
    # =====================================================================
    op.execute("""
        CREATE TABLE accounting.fees (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            account_id BIGINT NOT NULL REFERENCES registry.accounts(id),
            strategy_id BIGINT REFERENCES registry.strategies(id),
            instrument_id BIGINT REFERENCES registry.instruments(id),
            asset_id BIGINT NOT NULL REFERENCES registry.assets(id),
            fee_type TEXT NOT NULL CHECK (fee_type IN (
                'maker', 'taker', 'liquidation', 'withdrawal', 'gas',
                'borrow', 'vault_management', 'vault_performance',
                'custody', 'other'
            )),
            amount NUMERIC(38,18) NOT NULL CHECK (amount > 0),
            amount_usd NUMERIC(38,12) NOT NULL CHECK (amount_usd > 0),
            source_type TEXT NOT NULL,
            source_namespace TEXT NOT NULL,
            source_id TEXT NOT NULL,
            charged_at TIMESTAMPTZ NOT NULL,
            journal_id BIGINT NOT NULL UNIQUE REFERENCES accounting.journals(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (LENGTH(TRIM(source_type)) > 0),
            CHECK (LENGTH(TRIM(source_namespace)) > 0),
            CHECK (LENGTH(TRIM(source_id)) > 0)
        );
    """)

    op.execute("""
        CREATE UNIQUE INDEX uniq_fee_source
            ON accounting.fees(source_type, source_namespace, source_id, fee_type);
        CREATE INDEX idx_fees_account_at ON accounting.fees(account_id, charged_at DESC);
        CREATE INDEX idx_fees_strategy_at
            ON accounting.fees(strategy_id, charged_at DESC) WHERE strategy_id IS NOT NULL;
    """)

    # =====================================================================
    # TABLE 8: accounting.funding_payments
    # =====================================================================
    op.execute("""
        CREATE TABLE accounting.funding_payments (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            account_id BIGINT NOT NULL REFERENCES registry.accounts(id),
            strategy_id BIGINT REFERENCES registry.strategies(id),
            instrument_id BIGINT NOT NULL REFERENCES registry.instruments(id),
            asset_id BIGINT NOT NULL REFERENCES registry.assets(id),
            direction TEXT NOT NULL CHECK (direction IN ('paid', 'received')),
            amount NUMERIC(38,18) NOT NULL CHECK (amount > 0),
            amount_usd NUMERIC(38,12) NOT NULL CHECK (amount_usd > 0),
            funding_rate NUMERIC(20,12) NOT NULL,
            position_size NUMERIC(38,18),
            source_type TEXT NOT NULL DEFAULT 'funding_event',
            source_namespace TEXT NOT NULL,
            source_id TEXT NOT NULL,
            funded_at TIMESTAMPTZ NOT NULL,
            journal_id BIGINT NOT NULL UNIQUE REFERENCES accounting.journals(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (LENGTH(TRIM(source_type)) > 0),
            CHECK (LENGTH(TRIM(source_namespace)) > 0),
            CHECK (LENGTH(TRIM(source_id)) > 0)
        );
    """)

    op.execute("""
        CREATE UNIQUE INDEX uniq_funding_source
            ON accounting.funding_payments(source_type, source_namespace, source_id);
        CREATE INDEX idx_funding_account_at ON accounting.funding_payments(account_id, funded_at DESC);
        CREATE INDEX idx_funding_strategy_at
            ON accounting.funding_payments(strategy_id, funded_at DESC) WHERE strategy_id IS NOT NULL;
        CREATE INDEX idx_funding_instrument_at
            ON accounting.funding_payments(instrument_id, funded_at DESC);
    """)

    # =====================================================================
    # TABLE 9: accounting.borrow_costs
    # =====================================================================
    op.execute("""
        CREATE TABLE accounting.borrow_costs (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            account_id BIGINT NOT NULL REFERENCES registry.accounts(id),
            strategy_id BIGINT REFERENCES registry.strategies(id),
            instrument_id BIGINT REFERENCES registry.instruments(id),
            asset_id BIGINT NOT NULL REFERENCES registry.assets(id),
            borrowed_amount NUMERIC(38,18) NOT NULL CHECK (borrowed_amount > 0),
            cost_amount NUMERIC(38,18) NOT NULL CHECK (cost_amount > 0),
            cost_amount_usd NUMERIC(38,12) NOT NULL CHECK (cost_amount_usd > 0),
            rate NUMERIC(20,12) NOT NULL,
            period_seconds INT NOT NULL CHECK (period_seconds > 0),
            source_type TEXT NOT NULL DEFAULT 'borrow_event',
            source_namespace TEXT NOT NULL,
            source_id TEXT NOT NULL,
            charged_at TIMESTAMPTZ NOT NULL,
            journal_id BIGINT NOT NULL UNIQUE REFERENCES accounting.journals(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (LENGTH(TRIM(source_type)) > 0),
            CHECK (LENGTH(TRIM(source_namespace)) > 0),
            CHECK (LENGTH(TRIM(source_id)) > 0)
        );
    """)

    op.execute("""
        CREATE UNIQUE INDEX uniq_borrow_source
            ON accounting.borrow_costs(source_type, source_namespace, source_id);
        CREATE INDEX idx_borrow_account_at ON accounting.borrow_costs(account_id, charged_at DESC);
        CREATE INDEX idx_borrow_strategy_at
            ON accounting.borrow_costs(strategy_id, charged_at DESC) WHERE strategy_id IS NOT NULL;
    """)

    # =====================================================================
    # TABLE 10: accounting.nav_snapshots
    # =====================================================================
    op.execute("""
        CREATE TABLE accounting.nav_snapshots (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            valuation_run_id UUID NOT NULL REFERENCES accounting.valuation_runs(id),
            portfolio_id BIGINT NOT NULL REFERENCES registry.portfolios(id),
            strategy_id BIGINT REFERENCES registry.strategies(id),
            snapshot_date DATE NOT NULL,
            nav_total NUMERIC(38,12) NOT NULL,
            nav_realized NUMERIC(38,12) NOT NULL,
            nav_unrealized NUMERIC(38,12) NOT NULL,
            nav_accrued_funding NUMERIC(38,12) NOT NULL DEFAULT 0,
            nav_accrued_fees NUMERIC(38,12) NOT NULL DEFAULT 0,
            nav_accrued_borrow NUMERIC(38,12) NOT NULL DEFAULT 0,
            nav_breakdown JSONB NOT NULL,
            twr_daily NUMERIC(20,12),
            deposits_today NUMERIC(38,12) NOT NULL DEFAULT 0,
            withdrawals_today NUMERIC(38,12) NOT NULL DEFAULT 0,
            nav_environment TEXT NOT NULL CHECK (nav_environment IN (
                'LIVE', 'SHADOW', 'REPLAY', 'BACKTEST'
            )),
            nav_settlement_type TEXT NOT NULL CHECK (nav_settlement_type IN (
                'CONFIRMED_SETTLED', 'MODELED_FILL', 'SIMULATED_FILL', 'UNREALIZED_MTM', 'MIXED'
            )),
            computation_metadata JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (jsonb_typeof(nav_breakdown) = 'object'),
            CHECK (jsonb_typeof(computation_metadata) = 'object'),
            CHECK (
                (nav_environment = 'LIVE' AND nav_settlement_type IN ('CONFIRMED_SETTLED', 'UNREALIZED_MTM', 'MIXED'))
                OR (nav_environment = 'SHADOW' AND nav_settlement_type IN ('MODELED_FILL', 'UNREALIZED_MTM', 'MIXED'))
                OR (nav_environment IN ('REPLAY', 'BACKTEST'))
            ),
            CHECK (
                (nav_settlement_type IN ('CONFIRMED_SETTLED', 'MODELED_FILL', 'SIMULATED_FILL')
                    AND nav_unrealized = 0)
                OR
                (nav_settlement_type = 'UNREALIZED_MTM'
                    AND nav_realized = 0)
                OR
                (nav_settlement_type = 'MIXED')
            ),
            UNIQUE NULLS NOT DISTINCT (valuation_run_id, portfolio_id, strategy_id, snapshot_date)
        );
    """)

    op.execute("""
        CREATE INDEX idx_nav_snapshots_portfolio_date
            ON accounting.nav_snapshots(portfolio_id, snapshot_date DESC);
        CREATE INDEX idx_nav_snapshots_strategy_date
            ON accounting.nav_snapshots(strategy_id, snapshot_date DESC) WHERE strategy_id IS NOT NULL;
        CREATE INDEX idx_nav_snapshots_run
            ON accounting.nav_snapshots(valuation_run_id);
    """)

    # =====================================================================
    # TABLE 11: accounting.strategy_pnl
    # =====================================================================
    op.execute("""
        CREATE TABLE accounting.strategy_pnl (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            valuation_run_id UUID NOT NULL REFERENCES accounting.valuation_runs(id),
            strategy_id BIGINT NOT NULL REFERENCES registry.strategies(id),
            portfolio_id BIGINT NOT NULL REFERENCES registry.portfolios(id),
            pnl_date DATE NOT NULL,
            pnl_realized_gross NUMERIC(38,12) NOT NULL,
            pnl_unrealized NUMERIC(38,12) NOT NULL,
            pnl_fees NUMERIC(38,12) NOT NULL DEFAULT 0,
            pnl_funding NUMERIC(38,12) NOT NULL DEFAULT 0,
            pnl_borrow NUMERIC(38,12) NOT NULL DEFAULT 0,
            pnl_total NUMERIC(38,12) GENERATED ALWAYS AS (
                pnl_realized_gross + pnl_unrealized - pnl_fees + pnl_funding - pnl_borrow
            ) STORED,
            pnl_type TEXT NOT NULL CHECK (pnl_type IN ('REALIZED', 'UNREALIZED', 'MIXED')),
            pnl_environment TEXT NOT NULL CHECK (pnl_environment IN (
                'LIVE', 'SHADOW', 'REPLAY', 'BACKTEST'
            )),
            pnl_settlement_type TEXT NOT NULL CHECK (pnl_settlement_type IN (
                'CONFIRMED_SETTLED', 'MODELED_FILL', 'SIMULATED_FILL', 'UNREALIZED_MTM', 'MIXED'
            )),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (
                (pnl_type = 'REALIZED'
                 AND pnl_unrealized = 0
                 AND pnl_settlement_type IN ('CONFIRMED_SETTLED', 'MODELED_FILL', 'SIMULATED_FILL'))
                OR
                (pnl_type = 'UNREALIZED'
                 AND pnl_realized_gross = 0
                 AND pnl_fees = 0
                 AND pnl_funding = 0
                 AND pnl_borrow = 0
                 AND pnl_settlement_type = 'UNREALIZED_MTM')
                OR
                (pnl_type = 'MIXED' AND pnl_settlement_type = 'MIXED')
            ),
            CHECK (
                (pnl_environment = 'LIVE' AND pnl_settlement_type IN ('CONFIRMED_SETTLED', 'UNREALIZED_MTM', 'MIXED'))
                OR (pnl_environment = 'SHADOW' AND pnl_settlement_type IN ('MODELED_FILL', 'UNREALIZED_MTM', 'MIXED'))
                OR (pnl_environment IN ('REPLAY', 'BACKTEST'))
            ),
            UNIQUE (valuation_run_id, portfolio_id, strategy_id, pnl_date, pnl_environment)
        );
    """)

    op.execute("""
        CREATE INDEX idx_strategy_pnl_strategy_date
            ON accounting.strategy_pnl(strategy_id, pnl_date DESC);
        CREATE INDEX idx_strategy_pnl_portfolio_date
            ON accounting.strategy_pnl(portfolio_id, pnl_date DESC);
        CREATE INDEX idx_strategy_pnl_run
            ON accounting.strategy_pnl(valuation_run_id);
    """)

    # =====================================================================
    # TRIGGER: Append-only enforcement
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION accounting.prevent_accounting_audit_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION
                '%.% is append-only; UPDATE and DELETE are forbidden. Corrections must be represented by new rows.',
                TG_TABLE_SCHEMA, TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql;
    """)

    for table in [
        'cash_balances', 'cashflows', 'fees', 'funding_payments', 'borrow_costs',
        'mark_prices', 'mark_price_sets', 'mark_price_set_items',
        'valuation_runs', 'nav_snapshots', 'strategy_pnl'
    ]:
        op.execute(f"""
            CREATE TRIGGER {table}_append_only_update
                BEFORE UPDATE ON accounting.{table}
                FOR EACH ROW EXECUTE FUNCTION accounting.prevent_accounting_audit_mutation();
            CREATE TRIGGER {table}_append_only_delete
                BEFORE DELETE ON accounting.{table}
                FOR EACH ROW EXECUTE FUNCTION accounting.prevent_accounting_audit_mutation();
        """)

    # =====================================================================
    # TRIGGER: Mark price set immutability after valuation use (v4: with FOR UPDATE)
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION accounting.enforce_mark_price_set_not_used()
        RETURNS TRIGGER AS $$
        DECLARE
            v_used BOOLEAN;
        BEGIN
            -- v4: lock the mark_price_sets row to serialize against concurrent
            -- valuation_run creation (paired with lock_mark_price_set_for_valuation_run)
            PERFORM 1
            FROM accounting.mark_price_sets
            WHERE id = NEW.mark_price_set_id
            FOR UPDATE;

            SELECT EXISTS (
                SELECT 1 FROM accounting.valuation_runs
                WHERE mark_price_set_id = NEW.mark_price_set_id
            ) INTO v_used;

            IF v_used THEN
                RAISE EXCEPTION
                    'Cannot add items to mark_price_set %; it is already referenced by a valuation_run',
                    NEW.mark_price_set_id;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER mark_price_set_items_immutable_after_use
            BEFORE INSERT ON accounting.mark_price_set_items
            FOR EACH ROW EXECUTE FUNCTION accounting.enforce_mark_price_set_not_used();
    """)

    # =====================================================================
    # TRIGGER: Lock mark_price_set when a valuation_run is created (v4 NEW)
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION accounting.lock_mark_price_set_for_valuation_run()
        RETURNS TRIGGER AS $$
        BEGIN
            PERFORM 1
            FROM accounting.mark_price_sets
            WHERE id = NEW.mark_price_set_id
            FOR UPDATE;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER valuation_runs_lock_mark_set
            BEFORE INSERT ON accounting.valuation_runs
            FOR EACH ROW EXECUTE FUNCTION accounting.lock_mark_price_set_for_valuation_run();
    """)

    # =====================================================================
    # TRIGGER: Event-journal link enforcement (v4: FOR UPDATE, voided check, cashflow strategy guard)
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION accounting.enforce_event_journal_link()
        RETURNS TRIGGER AS $$
        DECLARE
            v_journal_status TEXT;
            v_journal_type TEXT;
            v_journal_source_type TEXT;
            v_journal_source_namespace TEXT;
            v_journal_source_id TEXT;
            v_journal_strategy_id BIGINT;
            v_journal_voided_at TIMESTAMPTZ;
            v_expected_journal_type TEXT;
            v_event_source_type TEXT;
            v_event_source_namespace TEXT;
            v_event_source_id TEXT;
            v_event_strategy_id BIGINT;
        BEGIN
            IF TG_TABLE_NAME = 'cashflows' THEN
                IF NEW.direction = 'internal_transfer' THEN
                    v_expected_journal_type := 'transfer';
                ELSE
                    v_expected_journal_type := 'cashflow';
                END IF;
                v_event_source_type := NEW.source_type;
                v_event_source_namespace := NEW.source_namespace;
                v_event_source_id := NEW.source_id;
                v_event_strategy_id := NULL;
            ELSIF TG_TABLE_NAME = 'fees' THEN
                v_expected_journal_type := 'fee';
                v_event_source_type := NEW.source_type;
                v_event_source_namespace := NEW.source_namespace;
                v_event_source_id := NEW.source_id;
                v_event_strategy_id := NEW.strategy_id;
            ELSIF TG_TABLE_NAME = 'funding_payments' THEN
                v_expected_journal_type := 'funding';
                v_event_source_type := NEW.source_type;
                v_event_source_namespace := NEW.source_namespace;
                v_event_source_id := NEW.source_id;
                v_event_strategy_id := NEW.strategy_id;
            ELSIF TG_TABLE_NAME = 'borrow_costs' THEN
                v_expected_journal_type := 'borrow';
                v_event_source_type := NEW.source_type;
                v_event_source_namespace := NEW.source_namespace;
                v_event_source_id := NEW.source_id;
                v_event_strategy_id := NEW.strategy_id;
            ELSE
                RAISE EXCEPTION
                    'enforce_event_journal_link() called on unsupported table %', TG_TABLE_NAME;
            END IF;

            -- v4: lock journal row to serialize against void_journal()
            SELECT status, journal_type, source_type, source_namespace, source_id, strategy_id, voided_at
            INTO v_journal_status, v_journal_type, v_journal_source_type,
                 v_journal_source_namespace, v_journal_source_id,
                 v_journal_strategy_id, v_journal_voided_at
            FROM accounting.journals
            WHERE id = NEW.journal_id
            FOR UPDATE;

            IF v_journal_status IS NULL THEN
                RAISE EXCEPTION 'Linked journal % does not exist', NEW.journal_id;
            END IF;

            IF v_journal_status != 'posted' THEN
                RAISE EXCEPTION
                    'Linked journal % must be posted (current: %)', NEW.journal_id, v_journal_status;
            END IF;

            -- v4: reject voided journals
            IF v_journal_voided_at IS NOT NULL THEN
                RAISE EXCEPTION
                    'Linked journal % has been voided and cannot receive new event rows',
                    NEW.journal_id;
            END IF;

            IF v_journal_type IS DISTINCT FROM v_expected_journal_type THEN
                RAISE EXCEPTION
                    'Linked journal % has journal_type=%, expected % for event in table %.%',
                    NEW.journal_id, v_journal_type, v_expected_journal_type,
                    TG_TABLE_SCHEMA, TG_TABLE_NAME;
            END IF;

            IF v_journal_source_type IS DISTINCT FROM v_event_source_type THEN
                RAISE EXCEPTION
                    'Linked journal % source_type=% does not match event source_type=%',
                    NEW.journal_id, v_journal_source_type, v_event_source_type;
            END IF;

            IF v_journal_source_namespace IS DISTINCT FROM v_event_source_namespace THEN
                RAISE EXCEPTION
                    'Linked journal % source_namespace=% does not match event source_namespace=%',
                    NEW.journal_id, v_journal_source_namespace, v_event_source_namespace;
            END IF;

            IF v_journal_source_id IS DISTINCT FROM v_event_source_id THEN
                RAISE EXCEPTION
                    'Linked journal % source_id=% does not match event source_id=%',
                    NEW.journal_id, v_journal_source_id, v_event_source_id;
            END IF;

            -- v4: cashflow journals must be portfolio-level (NULL strategy_id)
            IF TG_TABLE_NAME = 'cashflows' AND v_journal_strategy_id IS NOT NULL THEN
                RAISE EXCEPTION
                    'Cashflow journal % must have NULL strategy_id; cashflows are portfolio-level',
                    NEW.journal_id;
            END IF;

            IF v_event_strategy_id IS NOT NULL
               AND v_journal_strategy_id IS DISTINCT FROM v_event_strategy_id
            THEN
                RAISE EXCEPTION
                    'Linked journal % strategy_id=% does not match event strategy_id=%',
                    NEW.journal_id, v_journal_strategy_id, v_event_strategy_id;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    for table in ['cashflows', 'fees', 'funding_payments', 'borrow_costs']:
        op.execute(f"""
            CREATE TRIGGER {table}_journal_link_check
                BEFORE INSERT ON accounting.{table}
                FOR EACH ROW EXECUTE FUNCTION accounting.enforce_event_journal_link();
        """)

    # =====================================================================
    # TRIGGER: Valuation output consistency
    # =====================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION accounting.enforce_valuation_output_consistency()
        RETURNS TRIGGER AS $$
        DECLARE
            v_run_portfolio_id BIGINT;
            v_run_date DATE;
            v_event_portfolio_id BIGINT;
            v_event_date DATE;
        BEGIN
            SELECT portfolio_id, valuation_date
            INTO v_run_portfolio_id, v_run_date
            FROM accounting.valuation_runs
            WHERE id = NEW.valuation_run_id;

            IF v_run_portfolio_id IS NULL THEN
                RAISE EXCEPTION
                    'valuation_run % does not exist', NEW.valuation_run_id;
            END IF;

            v_event_portfolio_id := NEW.portfolio_id;

            IF TG_TABLE_NAME = 'nav_snapshots' THEN
                v_event_date := NEW.snapshot_date;
            ELSIF TG_TABLE_NAME = 'strategy_pnl' THEN
                v_event_date := NEW.pnl_date;
            ELSE
                RAISE EXCEPTION
                    'enforce_valuation_output_consistency() called on unsupported table %',
                    TG_TABLE_NAME;
            END IF;

            IF v_event_portfolio_id IS DISTINCT FROM v_run_portfolio_id THEN
                RAISE EXCEPTION
                    '%.% portfolio_id=% does not match valuation_run portfolio_id=%',
                    TG_TABLE_SCHEMA, TG_TABLE_NAME, v_event_portfolio_id, v_run_portfolio_id;
            END IF;

            IF v_event_date IS DISTINCT FROM v_run_date THEN
                RAISE EXCEPTION
                    '%.% date=% does not match valuation_run valuation_date=%',
                    TG_TABLE_SCHEMA, TG_TABLE_NAME, v_event_date, v_run_date;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER nav_snapshots_run_consistency
            BEFORE INSERT ON accounting.nav_snapshots
            FOR EACH ROW EXECUTE FUNCTION accounting.enforce_valuation_output_consistency();
        CREATE TRIGGER strategy_pnl_run_consistency
            BEFORE INSERT ON accounting.strategy_pnl
            FOR EACH ROW EXECUTE FUNCTION accounting.enforce_valuation_output_consistency();
    """)

    # =====================================================================
    # Verification block
    # =====================================================================
    op.execute("""
        DO $$
        DECLARE
            expected_tables TEXT[] := ARRAY[
                'cash_balances', 'cashflows', 'fees', 'funding_payments',
                'borrow_costs', 'mark_prices', 'mark_price_sets',
                'mark_price_set_items', 'valuation_runs',
                'nav_snapshots', 'strategy_pnl'
            ];
            expected_functions TEXT[] := ARRAY[
                'prevent_accounting_audit_mutation',
                'enforce_event_journal_link',
                'enforce_mark_price_set_not_used',
                'enforce_valuation_output_consistency',
                'lock_mark_price_set_for_valuation_run'
            ];
            expected_indexes TEXT[] := ARRAY[
                'uniq_cashflow_source', 'uniq_fee_source',
                'uniq_funding_source', 'uniq_borrow_source',
                'uniq_mark_prices_source_id'
            ];
            t TEXT;
            f TEXT;
            ix TEXT;
            actual_count INT;
        BEGIN
            FOREACH t IN ARRAY expected_tables LOOP
                SELECT COUNT(*) INTO actual_count
                FROM information_schema.tables
                WHERE table_schema = 'accounting' AND table_name = t
                  AND table_type = 'BASE TABLE';
                IF actual_count != 1 THEN
                    RAISE EXCEPTION 'accounting.% not created', t;
                END IF;
            END LOOP;

            FOREACH f IN ARRAY expected_functions LOOP
                SELECT COUNT(*) INTO actual_count
                FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'accounting' AND p.proname = f;
                IF actual_count < 1 THEN
                    RAISE EXCEPTION 'accounting.%() not created', f;
                END IF;
            END LOOP;

            FOREACH ix IN ARRAY expected_indexes LOOP
                SELECT COUNT(*) INTO actual_count
                FROM pg_indexes
                WHERE schemaname = 'accounting' AND indexname = ix;
                IF actual_count < 1 THEN
                    RAISE EXCEPTION 'index %.% not created', 'accounting', ix;
                END IF;
            END LOOP;

            SELECT COUNT(*) INTO actual_count
            FROM pg_constraint
            WHERE conrelid = 'accounting.journals'::regclass
              AND conname = 'journals_journal_type_check_v6'
              AND pg_get_constraintdef(oid) LIKE '%borrow%';
            IF actual_count != 1 THEN
                RAISE EXCEPTION 'journal_type=borrow not present in journals_journal_type_check_v6';
            END IF;

            RAISE NOTICE 'accounting balances/NAV/marks/events verified (0006 v4)';
        END;
        $$;
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS valuation_runs_lock_mark_set ON accounting.valuation_runs;")
    op.execute("DROP FUNCTION IF EXISTS accounting.lock_mark_price_set_for_valuation_run();")

    op.execute("DROP TRIGGER IF EXISTS strategy_pnl_run_consistency ON accounting.strategy_pnl;")
    op.execute("DROP TRIGGER IF EXISTS nav_snapshots_run_consistency ON accounting.nav_snapshots;")
    op.execute("DROP FUNCTION IF EXISTS accounting.enforce_valuation_output_consistency();")

    op.execute("DROP TRIGGER IF EXISTS mark_price_set_items_immutable_after_use ON accounting.mark_price_set_items;")
    op.execute("DROP FUNCTION IF EXISTS accounting.enforce_mark_price_set_not_used();")

    for table in ['borrow_costs', 'funding_payments', 'fees', 'cashflows']:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_journal_link_check ON accounting.{table};")
    op.execute("DROP FUNCTION IF EXISTS accounting.enforce_event_journal_link();")

    for table in [
        'strategy_pnl', 'nav_snapshots', 'valuation_runs',
        'mark_price_set_items', 'mark_price_sets', 'mark_prices',
        'borrow_costs', 'funding_payments', 'fees', 'cashflows', 'cash_balances'
    ]:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only_delete ON accounting.{table};")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only_update ON accounting.{table};")
    op.execute("DROP FUNCTION IF EXISTS accounting.prevent_accounting_audit_mutation();")

    op.execute("DROP TABLE IF EXISTS accounting.strategy_pnl;")
    op.execute("DROP TABLE IF EXISTS accounting.nav_snapshots;")
    op.execute("DROP TABLE IF EXISTS accounting.borrow_costs;")
    op.execute("DROP TABLE IF EXISTS accounting.funding_payments;")
    op.execute("DROP TABLE IF EXISTS accounting.fees;")
    op.execute("DROP TABLE IF EXISTS accounting.cashflows;")
    op.execute("DROP TABLE IF EXISTS accounting.cash_balances;")
    op.execute("DROP TABLE IF EXISTS accounting.valuation_runs;")
    op.execute("DROP TABLE IF EXISTS accounting.mark_price_set_items;")
    op.execute("DROP TABLE IF EXISTS accounting.mark_price_sets;")
    op.execute("DROP TABLE IF EXISTS accounting.mark_prices;")

    op.execute("ALTER TABLE accounting.journals DROP CONSTRAINT IF EXISTS journals_journal_type_check_v6;")
    op.execute("""
        ALTER TABLE accounting.journals
        ADD CONSTRAINT journals_journal_type_check
        CHECK (journal_type IN (
            'trade', 'fee', 'funding', 'cashflow', 'transfer',
            'mtm', 'adjustment', 'reversal'
        ));
    """)
