# Ledger Schema Design v0.2

**Status:** Design draft, supersedes v0.1
**Author:** Wasseem Katt
**Reviewer credit:** External review 2026-05-02 contributed double-entry ledger structure, registry normalization, mark-price provenance, signal-to-PnL traceability tables, risk limits as data, numeric precision conventions, and 11 specific schema corrections.
**Date:** 2026-05-02
**Implements:** measurement_policy.md, risk_policy.md, deployment_gates.md, model_policy.md, data_policy.md
**Implementation target:** Phase 1 (May 11 - June 15 2026)
**Supersedes:** v0.1 (2026-05-02-ledger-schema-design.md). v0.1 is retained for reference but Phase 1 implementation reads v0.2.

This document specifies the canonical ledger schema for SuperHydra. v0.2 upgrades v0.1 from "good trading database" to "enterprise ledger" by adding double-entry accounting, full registry normalization, mark-price provenance, and signal-to-PnL audit chain.

## Database engine

PostgreSQL 16 with extensions:
- `pg_partman` for automated time-based partitioning
- `pg_uuidv7` for time-ordered UUIDs (or hand-rolled `gen_uuidv7()` function if extension unavailable)
- TimescaleDB for time-series tables

ClickHouse for tick-level high-frequency data (full L2 order book history, individual trades). Postgres ledger never reads from ClickHouse for accounting decisions.

## Schema organization

Eight logical schemas (up from six in v0.1):

- `registry` -- venues, accounts, assets, instruments, portfolios, strategies, models, vendors, features, promotions, signal_batches, allocator_runs, target_weights, model_deployments
- `accounting` -- cash_balances, cashflows, fees, funding_payments, borrow_costs, mark_prices, nav_snapshots, strategy_pnl, journals, ledger_accounts, ledger_entries
- `trading` -- order_intents, orders, fills, cancels
- `positions` -- positions, position_snapshots
- `risk` -- risk_events, kill_switch_log, override_log, reconciliation_breaks, limits, limit_evaluations, risk_state, strategy_constraints
- `audit` -- measurement_audit, flag_audit_log, data_quality_log
- `vault` -- DEFERRED to v0.3 when EBTC scoping begins (Phase 7+)
- `defi` -- DEFERRED to v0.3 when EBTC scoping begins (Phase 7+)
- `intelligence` -- DEFERRED to v0.3 when sentiment/news engines are built (Phase 4+)

## Conventions

### Timestamps
All timestamps are `TIMESTAMPTZ` (UTC, never local time). Per data_policy section 7.

### Numeric precision (revised in v0.2)

| Use | Type |
|---|---|
| Token quantities, asset amounts, vault shares | NUMERIC(38,18) |
| USD values, accounting | NUMERIC(38,12) |
| Prices | NUMERIC(38,18) |
| Rates, returns, percentages, weights | NUMERIC(20,12) |
| Basis points | NUMERIC(20,12) |

Never FLOAT or DOUBLE for any monetary or accounting value.

### Identifiers (revised in v0.2)

**Internal IDs on high-velocity tables (UUIDv7):**
- `trading.order_intents`, `trading.orders`, `trading.fills`, `trading.cancels`
- `risk.risk_events`, `risk.limit_evaluations`, `risk.reconciliation_breaks`
- `audit.data_quality_log`
- `accounting.journals`, `accounting.ledger_entries`
- `registry.signal_batches`, `registry.allocator_runs`, `registry.target_weights`

These use `id UUID NOT NULL DEFAULT gen_uuidv7() PRIMARY KEY`.

**Internal IDs on lower-velocity tables (BIGINT IDENTITY):**
- All `registry.*` tables for stable entities (venues, accounts, assets, instruments, portfolios, strategies, models, vendors, features, promotions, model_deployments, portfolio_strategies)
- All `accounting.*` lower-velocity tables (cash_balances, cashflows, fees, funding_payments, borrow_costs, mark_prices, nav_snapshots, strategy_pnl, ledger_accounts)
- `risk.kill_switch_log`, `risk.override_log`, `risk.limits`, `risk.risk_state`, `risk.strategy_constraints`
- `audit.measurement_audit`, `audit.flag_audit_log`
- `positions.positions`, `positions.position_snapshots`

These use `id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY`.

### Foreign keys
ON DELETE RESTRICT by default. Cascade only with explicit rationale documented in the table comment.

### Soft delete
Tables that need soft delete include `deleted_at TIMESTAMPTZ` (nullable). Production queries default to filter `deleted_at IS NULL`.

### Mutation tracking
All mutable tables include `updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()` with trigger.

### Partitioning
The following tables are PARTITIONED BY RANGE on their primary timestamp column from day one:
- `risk.risk_events` partitioned daily, 90-day hot retention
- `risk.limit_evaluations` partitioned daily, 90-day hot retention
- `audit.data_quality_log` partitioned daily, 90-day hot retention
- `trading.order_intents` partitioned daily, 180-day hot retention
- `accounting.ledger_entries` partitioned monthly, indefinite retention
- Use pg_partman for automated partition lifecycle.

## Schema: registry

### registry.venues

```sql
CREATE TABLE registry.venues (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    venue_code TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    venue_type TEXT NOT NULL CHECK (venue_type IN (
        'cex_spot', 'cex_futures', 'cex_options',
        'dex', 'lending_protocol', 'custodian',
        'vault', 'paper', 'bank'
    )),
    status TEXT NOT NULL CHECK (status IN ('active', 'paused', 'sunset')),
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Initial seed values: 'binance_futures', 'binance_spot', 'okx_futures', 'paper'. Additional venues added as registry rows, never via schema migration.

### registry.accounts

```sql
CREATE TABLE registry.accounts (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    venue_id BIGINT NOT NULL REFERENCES registry.venues(id),
    account_code TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    account_type TEXT NOT NULL CHECK (account_type IN (
        'trading', 'custody', 'margin', 'vault', 'paper', 'bank', 'subaccount'
    )),
    parent_account_id BIGINT REFERENCES registry.accounts(id),
    base_currency TEXT NOT NULL DEFAULT 'USD',
    status TEXT NOT NULL CHECK (status IN ('active', 'paused', 'closed')),
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_accounts_venue ON registry.accounts(venue_id);
CREATE INDEX idx_accounts_parent ON registry.accounts(parent_account_id) WHERE parent_account_id IS NOT NULL;
```

### registry.assets

```sql
CREATE TABLE registry.assets (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    symbol TEXT NOT NULL,
    display_name TEXT NOT NULL,
    asset_type TEXT NOT NULL CHECK (asset_type IN (
        'crypto', 'stablecoin', 'fiat', 'vault_share', 'tokenized_tbill', 'lp_token'
    )),
    decimals INTEGER NOT NULL CHECK (decimals BETWEEN 0 AND 30),
    chain TEXT,
    contract_address TEXT,
    status TEXT NOT NULL CHECK (status IN ('active', 'paused', 'delisted')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE NULLS NOT DISTINCT (symbol, chain, contract_address)
);
```

### registry.instruments

```sql
CREATE TABLE registry.instruments (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    instrument_code TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    venue_id BIGINT NOT NULL REFERENCES registry.venues(id),
    base_asset_id BIGINT REFERENCES registry.assets(id),
    quote_asset_id BIGINT REFERENCES registry.assets(id),
    instrument_type TEXT NOT NULL CHECK (instrument_type IN (
        'spot', 'perp', 'future', 'option', 'vault_share',
        'lending_position', 'cash', 'synthetic'
    )),
    expiry TIMESTAMPTZ,
    strike NUMERIC(38,18),
    option_type TEXT CHECK (option_type IN ('call', 'put')),
    contract_size NUMERIC(38,18),
    tick_size NUMERIC(38,18),
    lot_size NUMERIC(38,18),
    status TEXT NOT NULL CHECK (status IN ('active', 'paused', 'expired', 'delisted')),
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (
        (instrument_type = 'option' AND expiry IS NOT NULL AND strike IS NOT NULL AND option_type IS NOT NULL)
        OR (instrument_type IN ('future', 'vault_share') AND expiry IS NOT NULL)
        OR (instrument_type IN ('spot', 'perp', 'lending_position', 'cash', 'synthetic'))
    )
);

CREATE INDEX idx_instruments_venue ON registry.instruments(venue_id);
CREATE INDEX idx_instruments_active ON registry.instruments(status) WHERE status = 'active';
```

### registry.portfolios

```sql
CREATE TABLE registry.portfolios (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    portfolio_code TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    product_type TEXT NOT NULL CHECK (product_type IN (
        'internal', 'market_neutral_fund', 'long_flat_certificate',
        'ebtc_vault', 'paper'
    )),
    base_currency TEXT NOT NULL DEFAULT 'USD',
    status TEXT NOT NULL CHECK (status IN ('research', 'shadow', 'canary', 'live', 'paused', 'sunset')),
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Initial seed values: 'paper_research', 'mn_ls_phase1'. Additional portfolios added as engines come online.

### registry.portfolio_strategies

```sql
CREATE TABLE registry.portfolio_strategies (
    portfolio_id BIGINT NOT NULL REFERENCES registry.portfolios(id),
    strategy_id BIGINT NOT NULL REFERENCES registry.strategies(id),
    active_risk_weight NUMERIC(20,12),
    capital_allocation_pct NUMERIC(20,12),
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ,
    PRIMARY KEY (portfolio_id, strategy_id, starts_at)
);
```

### registry.strategies

```sql
CREATE TABLE registry.strategies (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    description TEXT,
    current_phase TEXT NOT NULL CHECK (current_phase IN (
        'research', 'shadow', 'canary', 'scale', 'paused', 'sunset'
    )),
    phase_entered_at TIMESTAMPTZ NOT NULL,
    hypothesis_doc_path TEXT NOT NULL,
    ev_check_passed BOOLEAN NOT NULL DEFAULT FALSE,
    ev_check_value NUMERIC(20,12),
    ev_check_at TIMESTAMPTZ,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### registry.promotions

```sql
CREATE TABLE registry.promotions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    strategy_id BIGINT NOT NULL REFERENCES registry.strategies(id),
    from_phase TEXT NOT NULL,
    to_phase TEXT NOT NULL CHECK (to_phase IN ('shadow', 'canary', 'scale', 'paused', 'sunset')),
    operator_id TEXT NOT NULL,
    operator_signature TEXT NOT NULL,
    signature_method TEXT NOT NULL CHECK (signature_method IN ('gpg', 'yubikey')),
    gate_evidence_doc_path TEXT NOT NULL,
    promoted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at TIMESTAMPTZ,
    revocation_reason TEXT,
    CHECK (
        (to_phase IN ('shadow', 'paused', 'sunset')) OR
        (signature_method = 'yubikey')
    )
);

CREATE INDEX idx_promotions_strategy_active
    ON registry.promotions(strategy_id, promoted_at DESC)
    WHERE revoked_at IS NULL;
```

### registry.models

```sql
CREATE TABLE registry.models (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    strategy_id BIGINT NOT NULL REFERENCES registry.strategies(id),
    version_id TEXT NOT NULL UNIQUE,
    model_class TEXT NOT NULL,
    training_data_version TEXT NOT NULL,
    feature_version TEXT NOT NULL,
    hyperparam_hash TEXT NOT NULL,
    artifact_path TEXT NOT NULL,
    validation_report_path TEXT,
    trained_at TIMESTAMPTZ NOT NULL,
    retired_at TIMESTAMPTZ,
    retirement_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_models_strategy ON registry.models(strategy_id, trained_at DESC);
```

### registry.model_deployments

```sql
CREATE TABLE registry.model_deployments (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    model_id BIGINT NOT NULL REFERENCES registry.models(id),
    environment TEXT NOT NULL CHECK (environment IN ('research', 'shadow', 'canary', 'scale')),
    deployed_at TIMESTAMPTZ NOT NULL,
    retired_at TIMESTAMPTZ,
    deployed_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_deployments_model ON registry.model_deployments(model_id, deployed_at DESC);
CREATE INDEX idx_deployments_active
    ON registry.model_deployments(environment, model_id)
    WHERE retired_at IS NULL;
```

### registry.vendors

```sql
CREATE TABLE registry.vendors (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    data_types TEXT[] NOT NULL,
    tier TEXT NOT NULL,
    monthly_cost_usd NUMERIC(38,12) NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK (status IN ('active', 'pending', 'paused', 'sunset')),
    verified_status TEXT NOT NULL CHECK (verified_status IN ('VERIFIED', 'UNVERIFIED')),
    last_verified_at TIMESTAMPTZ,
    verification_due_by DATE,
    phase_one_use BOOLEAN NOT NULL DEFAULT FALSE,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_vendors_verification_due
    ON registry.vendors(verification_due_by)
    WHERE verified_status = 'VERIFIED';
```

### registry.features

```sql
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
    UNIQUE (feature_name, version)
);

CREATE INDEX idx_features_active
    ON registry.features(feature_name)
    WHERE deprecated = FALSE;
```

### registry.signal_batches

```sql
CREATE TABLE registry.signal_batches (
    id UUID NOT NULL DEFAULT gen_uuidv7() PRIMARY KEY,
    strategy_id BIGINT NOT NULL REFERENCES registry.strategies(id),
    model_id BIGINT REFERENCES registry.models(id),
    feature_version TEXT NOT NULL,
    data_snapshot_id TEXT NOT NULL,
    batch_size INTEGER NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_signal_batches_strategy ON registry.signal_batches(strategy_id, generated_at DESC);
```

Note: per-prediction granularity (model_predictions table) deferred to v0.3 due to row-volume considerations. Aggregate batch metadata stored here; individual predictions reconstructible from model artifact + data_snapshot_id.

### registry.allocator_runs

```sql
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
    solve_status TEXT NOT NULL CHECK (solve_status IN ('optimal', 'suboptimal', 'infeasible', 'failed')),
    solve_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    generated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_allocator_runs_portfolio ON registry.allocator_runs(portfolio_id, generated_at DESC);
```

### registry.target_weights

```sql
CREATE TABLE registry.target_weights (
    id UUID NOT NULL DEFAULT gen_uuidv7() PRIMARY KEY,
    allocator_run_id UUID NOT NULL REFERENCES registry.allocator_runs(id),
    instrument_id BIGINT NOT NULL REFERENCES registry.instruments(id),
    target_weight NUMERIC(20,12) NOT NULL,
    target_notional_usd NUMERIC(38,12),
    target_quantity NUMERIC(38,18),
    reason JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (allocator_run_id, instrument_id)
);

CREATE INDEX idx_target_weights_run ON registry.target_weights(allocator_run_id);
```

## Schema: accounting

### accounting.ledger_accounts

```sql
CREATE TABLE accounting.ledger_accounts (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_code TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    account_type TEXT NOT NULL CHECK (account_type IN (
        'asset', 'liability', 'equity', 'income', 'expense'
    )),
    venue_id BIGINT REFERENCES registry.venues(id),
    venue_account_id BIGINT REFERENCES registry.accounts(id),
    strategy_id BIGINT REFERENCES registry.strategies(id),
    portfolio_id BIGINT REFERENCES registry.portfolios(id),
    asset_id BIGINT REFERENCES registry.assets(id),
    parent_account_code TEXT REFERENCES accounting.ledger_accounts(account_code),
    status TEXT NOT NULL CHECK (status IN ('active', 'closed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ledger_accounts_venue ON accounting.ledger_accounts(venue_id);
CREATE INDEX idx_ledger_accounts_strategy ON accounting.ledger_accounts(strategy_id);
CREATE INDEX idx_ledger_accounts_portfolio ON accounting.ledger_accounts(portfolio_id);
```

Standard chart of accounts seeded at install: cash accounts per venue/asset, position accounts per instrument, fee/funding/borrow expense accounts per strategy, equity accounts per portfolio.

### accounting.journals

```sql
CREATE TABLE accounting.journals (
    id UUID NOT NULL DEFAULT gen_uuidv7() PRIMARY KEY,
    event_type TEXT NOT NULL CHECK (event_type IN (
        'fill', 'fee', 'funding', 'borrow_cost', 'cashflow',
        'transfer', 'mark_to_market', 'rebate', 'vault_share_event',
        'manual_adjustment'
    )),
    source_table TEXT NOT NULL,
    source_id TEXT NOT NULL,
    portfolio_id BIGINT REFERENCES registry.portfolios(id),
    strategy_id BIGINT REFERENCES registry.strategies(id),
    journal_at TIMESTAMPTZ NOT NULL,
    description TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_journals_at ON accounting.journals(journal_at DESC);
CREATE INDEX idx_journals_source ON accounting.journals(source_table, source_id);
CREATE INDEX idx_journals_portfolio ON accounting.journals(portfolio_id, journal_at DESC);
```

### accounting.ledger_entries

```sql
CREATE TABLE accounting.ledger_entries (
    id UUID NOT NULL DEFAULT gen_uuidv7() PRIMARY KEY,
    journal_id UUID NOT NULL REFERENCES accounting.journals(id) ON DELETE RESTRICT,
    account_id BIGINT NOT NULL REFERENCES accounting.ledger_accounts(id) ON DELETE RESTRICT,
    asset_id BIGINT NOT NULL REFERENCES registry.assets(id),
    debit_credit TEXT NOT NULL CHECK (debit_credit IN ('debit', 'credit')),
    amount NUMERIC(38,18) NOT NULL CHECK (amount > 0),
    amount_usd NUMERIC(38,12),
    mark_price_id BIGINT REFERENCES accounting.mark_prices(id),
    entry_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
) PARTITION BY RANGE (entry_at);

CREATE INDEX idx_ledger_entries_journal ON accounting.ledger_entries(journal_id);
CREATE INDEX idx_ledger_entries_account ON accounting.ledger_entries(account_id, entry_at DESC);
CREATE INDEX idx_ledger_entries_at ON accounting.ledger_entries(entry_at DESC);
```

**Conservation constraint enforced by trigger:**
For every journal_id, sum(debits per asset_id) = sum(credits per asset_id). Trigger function rejects journals that fail conservation.

### accounting.mark_prices

```sql
CREATE TABLE accounting.mark_prices (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    instrument_id BIGINT NOT NULL REFERENCES registry.instruments(id),
    mark_type TEXT NOT NULL CHECK (mark_type IN (
        'mid', 'bid', 'ask', 'last', 'index', 'oracle',
        'conservative_exit', 'settlement'
    )),
    price NUMERIC(38,18) NOT NULL CHECK (price > 0),
    source TEXT NOT NULL,
    source_timestamp TIMESTAMPTZ NOT NULL,
    confidence NUMERIC(5,4),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (instrument_id, mark_type, source_timestamp, source)
);

CREATE INDEX idx_mark_prices_instrument_at
    ON accounting.mark_prices(instrument_id, source_timestamp DESC);
```

### accounting.cash_balances

```sql
CREATE TABLE accounting.cash_balances (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    venue_id BIGINT NOT NULL REFERENCES registry.venues(id),
    account_id BIGINT NOT NULL REFERENCES registry.accounts(id),
    asset_id BIGINT NOT NULL REFERENCES registry.assets(id),
    balance NUMERIC(38,18) NOT NULL,
    balance_locked NUMERIC(38,18) NOT NULL DEFAULT 0 CHECK (balance_locked >= 0),
    balance_available NUMERIC(38,18) GENERATED ALWAYS AS (balance - balance_locked) STORED,
    source TEXT NOT NULL CHECK (source IN ('venue_api', 'reconciler', 'manual')),
    source_record_id TEXT,
    snapshot_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (balance_locked <= balance)
);

CREATE INDEX idx_balances_account_asset_at
    ON accounting.cash_balances(account_id, asset_id, snapshot_at DESC);
CREATE INDEX idx_balances_at ON accounting.cash_balances(snapshot_at DESC);
```

Note: balance can be negative for margin accounts (representing borrowed positions). The CHECK constraint on balance_locked >= 0 holds; the CHECK on balance >= 0 is removed in v0.2 because margin liabilities are real. Negative balances must be backed by corresponding liability journal entries.

### accounting.cashflows

```sql
CREATE TABLE accounting.cashflows (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    direction TEXT NOT NULL CHECK (direction IN ('deposit', 'withdrawal', 'internal_transfer')),
    account_from_id BIGINT REFERENCES registry.accounts(id),
    account_to_id BIGINT REFERENCES registry.accounts(id),
    asset_id BIGINT NOT NULL REFERENCES registry.assets(id),
    amount NUMERIC(38,18) NOT NULL CHECK (amount > 0),
    fee NUMERIC(38,18) NOT NULL DEFAULT 0 CHECK (fee >= 0),
    external_tx_hash TEXT,
    external_record_id TEXT,
    operator_id TEXT NOT NULL,
    operator_signature TEXT,
    flow_at TIMESTAMPTZ NOT NULL,
    journal_id UUID REFERENCES accounting.journals(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (
        (direction = 'deposit' AND account_to_id IS NOT NULL) OR
        (direction = 'withdrawal' AND account_from_id IS NOT NULL) OR
        (direction = 'internal_transfer' AND account_from_id IS NOT NULL AND account_to_id IS NOT NULL)
    )
);

CREATE INDEX idx_cashflows_at ON accounting.cashflows(flow_at DESC);
CREATE INDEX idx_cashflows_account_from ON accounting.cashflows(account_from_id);
CREATE INDEX idx_cashflows_account_to ON accounting.cashflows(account_to_id);
```

### accounting.fees

```sql
CREATE TABLE accounting.fees (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_type TEXT NOT NULL CHECK (source_type IN (
        'fill', 'cashflow', 'vault_event', 'gas', 'borrow', 'liquidation', 'manual_adjustment'
    )),
    source_id TEXT,
    fee_type TEXT NOT NULL CHECK (fee_type IN (
        'maker', 'taker', 'liquidation', 'withdrawal', 'gas',
        'management', 'performance', 'custody', 'other'
    )),
    asset_id BIGINT NOT NULL REFERENCES registry.assets(id),
    amount NUMERIC(38,18) NOT NULL CHECK (amount >= 0),
    venue_id BIGINT REFERENCES registry.venues(id),
    strategy_id BIGINT REFERENCES registry.strategies(id),
    journal_id UUID REFERENCES accounting.journals(id),
    charged_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_fees_source ON accounting.fees(source_type, source_id);
CREATE INDEX idx_fees_at ON accounting.fees(charged_at DESC);
CREATE INDEX idx_fees_strategy ON accounting.fees(strategy_id, charged_at DESC);
```

### accounting.funding_payments

```sql
CREATE TABLE accounting.funding_payments (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    venue_id BIGINT NOT NULL REFERENCES registry.venues(id),
    account_id BIGINT NOT NULL REFERENCES registry.accounts(id),
    strategy_id BIGINT NOT NULL REFERENCES registry.strategies(id),
    instrument_id BIGINT REFERENCES registry.instruments(id),
    position_id BIGINT REFERENCES positions.positions(id),
    asset_id BIGINT NOT NULL REFERENCES registry.assets(id),
    direction TEXT NOT NULL CHECK (direction IN ('paid', 'received')),
    amount NUMERIC(38,18) NOT NULL CHECK (amount > 0),
    funding_rate NUMERIC(20,12) NOT NULL,
    journal_id UUID REFERENCES accounting.journals(id),
    funded_at TIMESTAMPTZ NOT NULL,
    external_record_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_funding_strategy_at ON accounting.funding_payments(strategy_id, funded_at DESC);
CREATE INDEX idx_funding_at ON accounting.funding_payments(funded_at DESC);
```

### accounting.borrow_costs

```sql
CREATE TABLE accounting.borrow_costs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    venue_id BIGINT NOT NULL REFERENCES registry.venues(id),
    account_id BIGINT NOT NULL REFERENCES registry.accounts(id),
    strategy_id BIGINT REFERENCES registry.strategies(id),
    asset_id BIGINT NOT NULL REFERENCES registry.assets(id),
    amount NUMERIC(38,18) NOT NULL CHECK (amount >= 0),
    rate NUMERIC(20,12),
    journal_id UUID REFERENCES accounting.journals(id),
    charged_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_borrow_strategy ON accounting.borrow_costs(strategy_id, charged_at DESC);
```

### accounting.nav_snapshots

```sql
CREATE TABLE accounting.nav_snapshots (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
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
    computation_method TEXT NOT NULL CHECK (computation_method IN ('eod_close', 'recomputed_historical')),
    computation_metadata JSONB NOT NULL,
    mark_price_set_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE NULLS NOT DISTINCT (portfolio_id, strategy_id, snapshot_date)
);

CREATE INDEX idx_nav_portfolio_date ON accounting.nav_snapshots(portfolio_id, snapshot_date DESC);
CREATE INDEX idx_nav_strategy_date ON accounting.nav_snapshots(strategy_id, snapshot_date DESC) WHERE strategy_id IS NOT NULL;
CREATE INDEX idx_nav_date ON accounting.nav_snapshots(snapshot_date DESC);
```

### accounting.strategy_pnl

```sql
CREATE TABLE accounting.strategy_pnl (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
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
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (strategy_id, pnl_date)
);

CREATE INDEX idx_pnl_strategy_date ON accounting.strategy_pnl(strategy_id, pnl_date DESC);
CREATE INDEX idx_pnl_portfolio_date ON accounting.strategy_pnl(portfolio_id, pnl_date DESC);
```

## Schema: trading

### trading.order_intents

```sql
CREATE TABLE trading.order_intents (
    id UUID NOT NULL DEFAULT gen_uuidv7() PRIMARY KEY,
    intent_uuid UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    strategy_id BIGINT NOT NULL REFERENCES registry.strategies(id),
    portfolio_id BIGINT NOT NULL REFERENCES registry.portfolios(id),
    venue_id BIGINT NOT NULL REFERENCES registry.venues(id),
    account_id BIGINT NOT NULL REFERENCES registry.accounts(id),
    instrument_id BIGINT NOT NULL REFERENCES registry.instruments(id),
    allocator_run_id UUID REFERENCES registry.allocator_runs(id),
    signal_batch_id UUID REFERENCES registry.signal_batches(id),
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity NUMERIC(38,18) NOT NULL CHECK (quantity > 0),
    price NUMERIC(38,18),
    order_type TEXT NOT NULL CHECK (order_type IN ('market', 'limit', 'stop_limit', 'stop_market')),
    time_in_force TEXT NOT NULL CHECK (time_in_force IN ('GTC', 'IOC', 'FOK', 'GTD')),
    post_only BOOLEAN NOT NULL DEFAULT FALSE,
    reduce_only BOOLEAN NOT NULL DEFAULT FALSE,
    expected_edge_bps NUMERIC(20,12),
    expected_slippage_bps NUMERIC(20,12),
    expected_funding_bps NUMERIC(20,12),
    confidence NUMERIC(20,12),
    horizon_minutes INTEGER,
    risk_kernel_decision TEXT NOT NULL CHECK (risk_kernel_decision IN ('approved', 'rejected', 'pending')),
    risk_kernel_decision_at TIMESTAMPTZ,
    risk_kernel_failed_check TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
) PARTITION BY RANGE (created_at);

CREATE INDEX idx_intents_strategy_at ON trading.order_intents(strategy_id, created_at DESC);
CREATE INDEX idx_intents_decision ON trading.order_intents(risk_kernel_decision);
CREATE INDEX idx_intents_allocator ON trading.order_intents(allocator_run_id) WHERE allocator_run_id IS NOT NULL;
```

### trading.orders

```sql
CREATE TABLE trading.orders (
    id UUID NOT NULL DEFAULT gen_uuidv7() PRIMARY KEY,
    intent_id UUID NOT NULL REFERENCES trading.order_intents(id),
    client_order_id TEXT NOT NULL,
    venue_id BIGINT NOT NULL REFERENCES registry.venues(id),
    account_id BIGINT NOT NULL REFERENCES registry.accounts(id),
    venue_order_id TEXT,
    instrument_id BIGINT NOT NULL REFERENCES registry.instruments(id),
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity NUMERIC(38,18) NOT NULL CHECK (quantity > 0),
    quantity_filled NUMERIC(38,18) NOT NULL DEFAULT 0 CHECK (quantity_filled >= 0),
    quantity_remaining NUMERIC(38,18) GENERATED ALWAYS AS (quantity - quantity_filled) STORED,
    price NUMERIC(38,18),
    order_type TEXT NOT NULL CHECK (order_type IN ('market', 'limit', 'stop_limit', 'stop_market')),
    time_in_force TEXT NOT NULL,
    post_only BOOLEAN NOT NULL DEFAULT FALSE,
    reduce_only BOOLEAN NOT NULL DEFAULT FALSE,
    status TEXT NOT NULL CHECK (status IN (
        'SUBMITTING', 'SUBMITTED', 'ACKNOWLEDGED', 'PARTIALLY_FILLED',
        'FILLED', 'CANCEL_REQUESTED', 'CANCELED', 'REJECTED',
        'STALE_NEEDS_RECONCILIATION', 'UNKNOWN'
    )),
    status_changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    submitted_at TIMESTAMPTZ,
    acknowledged_at TIMESTAMPTZ,
    filled_at TIMESTAMPTZ,
    canceled_at TIMESTAMPTZ,
    rejected_at TIMESTAMPTZ,
    rejection_reason TEXT,
    raw_submission_payload JSONB,
    raw_response_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (quantity_filled <= quantity),
    UNIQUE (venue_id, client_order_id)
);

CREATE INDEX idx_orders_status
    ON trading.orders(status, status_changed_at DESC)
    WHERE status NOT IN ('FILLED', 'CANCELED', 'REJECTED');
CREATE INDEX idx_orders_intent ON trading.orders(intent_id);
CREATE INDEX idx_orders_stale
    ON trading.orders(submitted_at)
    WHERE status = 'SUBMITTING';
```

### trading.fills

```sql
CREATE TABLE trading.fills (
    id UUID NOT NULL DEFAULT gen_uuidv7() PRIMARY KEY,
    order_id UUID NOT NULL REFERENCES trading.orders(id),
    venue_fill_id TEXT NOT NULL,
    venue_id BIGINT NOT NULL REFERENCES registry.venues(id),
    instrument_id BIGINT NOT NULL REFERENCES registry.instruments(id),
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity NUMERIC(38,18) NOT NULL CHECK (quantity > 0),
    price NUMERIC(38,18) NOT NULL CHECK (price > 0),
    liquidity TEXT CHECK (liquidity IN ('maker', 'taker', 'unknown')),
    journal_id UUID REFERENCES accounting.journals(id),
    raw_fill_payload JSONB NOT NULL,
    filled_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (venue_id, instrument_id, venue_fill_id)
);

CREATE INDEX idx_fills_order ON trading.fills(order_id);
CREATE INDEX idx_fills_at ON trading.fills(filled_at DESC);
```

### trading.cancels

```sql
CREATE TABLE trading.cancels (
    id UUID NOT NULL DEFAULT gen_uuidv7() PRIMARY KEY,
    order_id UUID NOT NULL REFERENCES trading.orders(id),
    requested_at TIMESTAMPTZ NOT NULL,
    venue_cancel_id TEXT,
    confirmed_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('requested', 'confirmed', 'failed')),
    failure_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_cancels_order ON trading.cancels(order_id);
```

## Schema: positions

### positions.positions

```sql
CREATE TABLE positions.positions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    strategy_id BIGINT NOT NULL REFERENCES registry.strategies(id),
    portfolio_id BIGINT NOT NULL REFERENCES registry.portfolios(id),
    venue_id BIGINT NOT NULL REFERENCES registry.venues(id),
    account_id BIGINT NOT NULL REFERENCES registry.accounts(id),
    instrument_id BIGINT NOT NULL REFERENCES registry.instruments(id),
    side TEXT NOT NULL CHECK (side IN ('long', 'short')),
    quantity NUMERIC(38,18) NOT NULL CHECK (quantity > 0),
    average_entry_price NUMERIC(38,18) NOT NULL CHECK (average_entry_price > 0),
    mark_price NUMERIC(38,18),
    mark_price_id BIGINT REFERENCES accounting.mark_prices(id),
    unrealized_pnl NUMERIC(38,12),
    notional_usd NUMERIC(38,12),
    margin_mode TEXT CHECK (margin_mode IN ('isolated', 'cross', 'spot')),
    collateral_asset_id BIGINT REFERENCES registry.assets(id),
    initial_margin NUMERIC(38,12),
    maintenance_margin NUMERIC(38,12),
    leverage NUMERIC(20,12),
    liquidation_price NUMERIC(38,18),
    liquidation_distance_pct NUMERIC(20,12),
    opened_at TIMESTAMPTZ NOT NULL,
    last_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closing', 'closed', 'liquidated')),
    closed_at TIMESTAMPTZ,
    close_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uniq_open_position
    ON positions.positions(strategy_id, account_id, instrument_id, side)
    WHERE status IN ('open', 'closing');
CREATE INDEX idx_positions_open ON positions.positions(strategy_id, status) WHERE status = 'open';
CREATE INDEX idx_positions_instrument ON positions.positions(instrument_id) WHERE status = 'open';
CREATE INDEX idx_positions_liquidation ON positions.positions(liquidation_distance_pct) WHERE status = 'open';
```

### positions.position_snapshots

```sql
CREATE TABLE positions.position_snapshots (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    position_id BIGINT NOT NULL REFERENCES positions.positions(id),
    snapshot_date DATE NOT NULL,
    quantity NUMERIC(38,18) NOT NULL,
    mark_price NUMERIC(38,18) NOT NULL,
    mark_price_id BIGINT REFERENCES accounting.mark_prices(id),
    mark_value NUMERIC(38,12) NOT NULL,
    unrealized_pnl NUMERIC(38,12) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (position_id, snapshot_date)
);

CREATE INDEX idx_snapshots_date ON positions.position_snapshots(snapshot_date DESC);
```

## Schema: risk

### risk.limits

```sql
CREATE TABLE risk.limits (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    limit_name TEXT NOT NULL,
    scope_type TEXT NOT NULL CHECK (scope_type IN (
        'portfolio', 'strategy', 'venue', 'account', 'instrument', 'cluster', 'asset'
    )),
    scope_id BIGINT,
    limit_value NUMERIC(38,18) NOT NULL,
    unit TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('warn', 'block', 'reduce_only', 'kill')),
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ,
    policy_doc_path TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_signature TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_limits_active ON risk.limits(limit_name, starts_at DESC) WHERE ends_at IS NULL;
CREATE INDEX idx_limits_scope ON risk.limits(scope_type, scope_id) WHERE ends_at IS NULL;
```

### risk.limit_evaluations

```sql
CREATE TABLE risk.limit_evaluations (
    id UUID NOT NULL DEFAULT gen_uuidv7() PRIMARY KEY,
    limit_id BIGINT NOT NULL REFERENCES risk.limits(id),
    intent_id UUID REFERENCES trading.order_intents(id),
    observed_value NUMERIC(38,18) NOT NULL,
    threshold_value NUMERIC(38,18) NOT NULL,
    result TEXT NOT NULL CHECK (result IN ('pass', 'warn', 'fail')),
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    context JSONB NOT NULL DEFAULT '{}'::jsonb
) PARTITION BY RANGE (evaluated_at);

CREATE INDEX idx_limit_eval_intent ON risk.limit_evaluations(intent_id);
CREATE INDEX idx_limit_eval_at ON risk.limit_evaluations(evaluated_at DESC);
CREATE INDEX idx_limit_eval_failures ON risk.limit_evaluations(evaluated_at DESC) WHERE result = 'fail';
```

### risk.risk_state

```sql
CREATE TABLE risk.risk_state (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    portfolio_id BIGINT NOT NULL REFERENCES registry.portfolios(id),
    state TEXT NOT NULL CHECK (state IN ('GREEN', 'YELLOW', 'ORANGE', 'RED', 'BLACK')),
    reason TEXT NOT NULL,
    drawdown_pct NUMERIC(20,12),
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_risk_state_portfolio_active
    ON risk.risk_state(portfolio_id, starts_at DESC)
    WHERE ends_at IS NULL;
```

### risk.strategy_constraints

```sql
CREATE TABLE risk.strategy_constraints (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    strategy_id BIGINT NOT NULL REFERENCES registry.strategies(id),
    allow_leverage BOOLEAN NOT NULL DEFAULT FALSE,
    allow_shorts BOOLEAN NOT NULL DEFAULT FALSE,
    allowed_instrument_types TEXT[] NOT NULL,
    allowed_venues BIGINT[],
    max_gross_exposure_pct NUMERIC(20,12),
    max_net_exposure_pct NUMERIC(20,12),
    max_leverage NUMERIC(20,12),
    enforced_from TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_strategy_constraints_strategy ON risk.strategy_constraints(strategy_id, enforced_from DESC);
```

### risk.risk_events

```sql
CREATE TABLE risk.risk_events (
    id UUID NOT NULL DEFAULT gen_uuidv7() PRIMARY KEY,
    intent_id UUID REFERENCES trading.order_intents(id),
    portfolio_id BIGINT REFERENCES registry.portfolios(id),
    event_type TEXT NOT NULL CHECK (event_type IN (
        'pre_trade_check', 'limit_breach', 'state_transition',
        'kill_switch_engaged', 'override_applied'
    )),
    check_name TEXT,
    result TEXT NOT NULL CHECK (result IN ('pass', 'fail', 'warning')),
    context JSONB NOT NULL,
    event_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
) PARTITION BY RANGE (event_at);

CREATE INDEX idx_risk_events_at ON risk.risk_events(event_at DESC);
CREATE INDEX idx_risk_events_intent ON risk.risk_events(intent_id);
CREATE INDEX idx_risk_events_failures ON risk.risk_events(event_at DESC) WHERE result = 'fail';
```

### risk.kill_switch_log

```sql
CREATE TABLE risk.kill_switch_log (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    switch_type TEXT NOT NULL CHECK (switch_type IN ('STRATEGY_HALT', 'VENUE_HALT', 'PORTFOLIO_HALT')),
    target TEXT NOT NULL,
    engaged BOOLEAN NOT NULL,
    operator_id TEXT NOT NULL,
    operator_signature TEXT,
    reason TEXT NOT NULL,
    auto_triggered BOOLEAN NOT NULL DEFAULT FALSE,
    auto_trigger_source TEXT,
    review_due_by TIMESTAMPTZ,
    review_completed_at TIMESTAMPTZ,
    review_operator_id TEXT,
    review_signature TEXT,
    review_outcome TEXT,
    event_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (
        (auto_triggered = TRUE) OR
        (operator_signature IS NOT NULL)
    )
);

CREATE INDEX idx_kill_at ON risk.kill_switch_log(event_at DESC);
CREATE INDEX idx_kill_active ON risk.kill_switch_log(switch_type, target, engaged, event_at DESC);
CREATE INDEX idx_kill_review_due
    ON risk.kill_switch_log(review_due_by)
    WHERE auto_triggered = TRUE AND review_completed_at IS NULL;
```

### risk.override_log

```sql
CREATE TABLE risk.override_log (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    limit_name TEXT NOT NULL,
    strategy_id BIGINT REFERENCES registry.strategies(id),
    operator_id TEXT NOT NULL,
    operator_signature TEXT NOT NULL,
    rationale TEXT NOT NULL,
    scope_starts_at TIMESTAMPTZ NOT NULL,
    scope_ends_at TIMESTAMPTZ NOT NULL,
    review_due_by DATE NOT NULL,
    review_completed_at TIMESTAMPTZ,
    review_outcome TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_overrides_active
    ON risk.override_log(scope_ends_at)
    WHERE review_completed_at IS NULL;
```

### risk.reconciliation_breaks

```sql
CREATE TABLE risk.reconciliation_breaks (
    id UUID NOT NULL DEFAULT gen_uuidv7() PRIMARY KEY,
    venue_id BIGINT NOT NULL REFERENCES registry.venues(id),
    account_id BIGINT REFERENCES registry.accounts(id),
    break_type TEXT NOT NULL CHECK (break_type IN (
        'order_state', 'fill_missing', 'position_quantity', 'position_existence',
        'cash_balance', 'margin_state', 'funding_payment'
    )),
    local_state JSONB NOT NULL,
    venue_state JSONB NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    resolution_method TEXT,
    resolution_details JSONB
);

CREATE INDEX idx_breaks_unresolved ON risk.reconciliation_breaks(detected_at) WHERE resolved_at IS NULL;
CREATE INDEX idx_breaks_venue_at ON risk.reconciliation_breaks(venue_id, detected_at DESC);
```

## Schema: audit

### audit.measurement_audit

```sql
CREATE TABLE audit.measurement_audit (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_name TEXT NOT NULL,
    verification_method TEXT NOT NULL,
    samples_checked INTEGER NOT NULL CHECK (samples_checked >= 5),
    samples_passed INTEGER NOT NULL CHECK (samples_passed <= samples_checked),
    verifier_id TEXT NOT NULL,
    verifier_signature TEXT NOT NULL,
    verified_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at DATE NOT NULL,
    notes TEXT
);

CREATE INDEX idx_audit_source ON audit.measurement_audit(source_name, verified_at DESC);
CREATE INDEX idx_audit_expiring ON audit.measurement_audit(expires_at);
```

### audit.flag_audit_log

```sql
CREATE TABLE audit.flag_audit_log (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    flag_name TEXT NOT NULL,
    old_value JSONB,
    new_value JSONB,
    changed_by TEXT NOT NULL,
    change_signature TEXT,
    behavior_affecting BOOLEAN NOT NULL,
    re_promotion_required BOOLEAN GENERATED ALWAYS AS (behavior_affecting) STORED,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_flag_changes_at ON audit.flag_audit_log(changed_at DESC);
CREATE INDEX idx_flag_changes_name ON audit.flag_audit_log(flag_name, changed_at DESC);
```

### audit.data_quality_log

```sql
CREATE TABLE audit.data_quality_log (
    id UUID NOT NULL DEFAULT gen_uuidv7() PRIMARY KEY,
    vendor_id BIGINT NOT NULL REFERENCES registry.vendors(id),
    check_type TEXT NOT NULL CHECK (check_type IN (
        'freshness', 'missing_data', 'duplicate', 'bad_tick', 'symbol_mapping',
        'timezone', 'volume_sanity', 'cross_source_disagreement'
    )),
    result TEXT NOT NULL CHECK (result IN ('pass', 'flag', 'halt')),
    context JSONB NOT NULL,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
) PARTITION BY RANGE (checked_at);

CREATE INDEX idx_dq_vendor_at ON audit.data_quality_log(vendor_id, checked_at DESC);
CREATE INDEX idx_dq_failures ON audit.data_quality_log(checked_at DESC) WHERE result IN ('flag', 'halt');
```

## Acceptance criteria for Phase 1 ledger implementation (v0.2)

The ledger is considered complete when ALL eleven of the following pass:

1. **Reproducibility**: given the raw fill log from old HYDRA's last 90 days, NAV trajectory recomputes deterministically. Two runs produce byte-identical results.

2. **Conservation by aggregate**: SUM(strategy_pnl.pnl_total) for any date equals nav_snapshots.nav_total change for that date (excluding cashflows). Conservation enforced as a daily integrity test.

3. **Validation against historical**: the new ledger replays old HYDRA's corrected daily returns CSV and produces matching NAV trajectory within 1 cent.

4. **Audit trail**: every PnL number can be traced via foreign keys back to specific fill records.

5. **Source typing**: every aggregate display shows pnl_type explicitly. No code path produces a numeric PnL without an associated REALIZED/UNREALIZED/MIXED tag.

6. **Empty-source safety**: every read query that aggregates over zero rows raises NoDataError or returns explicit zero-with-flag. No silent zero aggregations exist anywhere in the codebase.

7. **Double-entry conservation**: every accounting.journal balances by asset (sum of debits = sum of credits per asset_id within the journal). Trigger-enforced. No journal can be posted with unbalanced entries.

8. **Price-source reproducibility**: every NAV number identifies the exact mark_price_id, mark_type, source, and source_timestamp used. NAV computation queries can be replayed against historical mark_prices to reproduce the same NAV.

9. **Signal-to-PnL traceability**: every live fill traces through model_id -> signal_batch_id -> allocator_run_id -> target_weight -> order_intent -> orders -> fills -> ledger_entries -> strategy_pnl. SQL query "show me the full chain for fill X" returns all eight links.

10. **Risk-limit reproducibility**: every approved or rejected order can identify the exact active risk.limits rows used at decision time via risk.limit_evaluations. Limit changes preserve audit history.

11. **Product-level NAV**: portfolio NAV is reproducible independently from strategy NAV. Market-neutral fund, long-flat product, and EBTC vault accounting are separable. SQL query "show me portfolio X NAV on date Y" returns a number that does not depend on other portfolios.

These eleven criteria are the gate from Phase 1 to Phase 2.

## Deferred to v0.3

The following schemas are needed eventually but not in Phase 1. They are deferred to v0.3 when their corresponding engines enter scoping:

**vault schema** (Phase 7+, EBTC scoping):
- vault.share_events (deposits, redeems, mints, burns, fee accruals)
- vault.investor_whitelist (KYC/AML records)
- vault.share_price_history

**defi schema** (Phase 7+, EBTC scoping):
- defi.lending_positions (Aave/Compound positions with health factor, LTV)
- defi.routing_decisions (perp vs WBTC loop vs cash route selection)
- defi.protocol_states (lending protocol parameter snapshots)
- defi.liquidation_events

**Options support** (Phase 7+, options engine scoping):
- positions.option_greeks_snapshots (delta, gamma, vega, theta, rho, IV per snapshot)
- accounting.option_exercise_events
- risk limits for: max_delta, max_gamma, max_vega, max_short_gamma, max_options_notional, max_expiry_concentration

**intelligence schema** (Phase 4+, sentiment/news/tokenomics):
- intelligence.events (news, announcements, exploits, regulator actions)
- intelligence.token_unlocks (unlock schedules with circulating supply impact)
- intelligence.sentiment_snapshots (per-asset rolling sentiment scores)

**Per-prediction granularity** (Phase 2-3, when feature store goes in):
- registry.model_predictions (one row per prediction; deferred due to row volume)

## Open design questions deferred to implementation

1. Exact partition chunk size for `risk.limit_evaluations` -- daily for now; revisit if volume exceeds 10M rows/day.
2. Retention policy for `risk.risk_events` -- current default 90 days hot, indefinite cold to S3.
3. Materialized views for common queries (strategy daily PnL, NAV history, portfolio rollups). Add when query patterns are established, not pre-emptively.
4. Connection pooling and read-replica strategy -- defer until volume justifies.
5. Whether `accounting.ledger_entries` partitioning should be monthly vs weekly -- start monthly, monitor.

## Implementation note: UUIDv7 function

If pg_uuidv7 extension is unavailable, hand-roll the function:

```sql
CREATE OR REPLACE FUNCTION gen_uuidv7() RETURNS UUID AS $$
DECLARE
    unix_ts_ms BIGINT;
    rand_bytes BYTEA;
BEGIN
    unix_ts_ms := (EXTRACT(EPOCH FROM NOW()) * 1000)::BIGINT;
    rand_bytes := gen_random_bytes(10);
    RETURN encode(
        set_byte(set_byte(
            int8send(unix_ts_ms) || rand_bytes,
            6, (get_byte(rand_bytes, 0) & 15) | 112
        ), 8, (get_byte(rand_bytes, 2) & 63) | 128),
        'hex'
    )::UUID;
END;
$$ LANGUAGE plpgsql VOLATILE;
```

## Revision log

| Version | Date | Author | Changes |
|---|---|---|---|
| 0.1 | 2026-05-02 | Wasseem Katt | Initial design implementing all five Phase 0 policy docs |
| 0.2 | 2026-05-02 | Wasseem Katt + external reviewer | Added double-entry ledger; full registry normalization (venues, accounts, assets, instruments, portfolios); mark_prices for NAV reproducibility; signal_batches/allocator_runs/target_weights for signal-to-PnL audit; risk.limits as data; risk.strategy_constraints; risk.risk_state; auto-trigger handling for kill switches; UUIDv7 on high-velocity tables; partitioning made mandatory in Phase 1 for high-volume tables; numeric precision conventions revised; nav_snapshots NULL uniqueness fix via portfolio_id and NULLS NOT DISTINCT; fees/PnL gross treatment per Option A; smaller fixes (post_only/time_in_force separation, partial unique index on positions, model_deployments bridge, raw payload columns on fills/orders, quantity_filled <= quantity check). 5 additional acceptance criteria. EBTC/options/intelligence schemas explicitly deferred to v0.3 |
