# Ledger Schema Design v0.3

**Status:** Incremental patch over v0.2
**Author:** Wasseem Katt
**Date:** 2026-05-02
**Implements:** measurement_policy v1.1 environment and settlement typing
**Supersedes:** v0.2 (2026-05-02-ledger-schema-design-v0.2.md, commit a2db950) for the specific tables modified below; all other v0.2 specifications stand
**Implementation target:** Phase 1 (May 11 - June 15 2026)

This patch adds `pnl_environment` and `pnl_settlement_type` columns to two tables in v0.2 to align the schema with measurement_policy v1.1. v0.2 used a single `pnl_type` column which conflated two orthogonal classifications and could not distinguish a SHADOW modeled fill from a LIVE confirmed fill -- exactly the terminology conflict that caused the v1.0 -> v1.1 policy revision.

## Why v0.3 (small patch, not full revision)

The reviewer of v1.0 policies identified that "REALIZED" was being used to mean both "cash settled from a venue" (measurement_policy v1.0) and "modeled fill in a shadow run" (deployment_gates v1.0). measurement_policy v1.1 resolves this by introducing two orthogonal classifications:

- **pnl_environment**: LIVE / SHADOW / REPLAY / BACKTEST
- **pnl_settlement_type**: CONFIRMED_SETTLED / MODELED_FILL / SIMULATED_FILL / UNREALIZED_MTM

The schema must enforce these as separate columns so that a query like "show me REALIZED Sharpe over the last 90 days for promotion gate evaluation" can filter on `pnl_environment = 'LIVE' AND pnl_settlement_type = 'CONFIRMED_SETTLED'` rather than relying on naming convention.

This patch is small enough to apply during Phase 1 ledger implementation directly rather than requiring a full v0.4 revision. Two tables affected.

## Changes from v0.2

### Modified table: accounting.strategy_pnl

v0.2 had a single `pnl_type` column with values `REALIZED / UNREALIZED / MIXED`. v0.3 keeps `pnl_type` (renamed to `pnl_realization_type` for clarity) and adds two new columns.

**v0.3 schema:**

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
    pnl_realization_type TEXT NOT NULL CHECK (pnl_realization_type IN ('REALIZED', 'UNREALIZED', 'MIXED')),
    pnl_environment TEXT NOT NULL CHECK (pnl_environment IN ('LIVE', 'SHADOW', 'REPLAY', 'BACKTEST')),
    pnl_settlement_type TEXT NOT NULL CHECK (pnl_settlement_type IN (
        'CONFIRMED_SETTLED', 'MODELED_FILL', 'SIMULATED_FILL', 'UNREALIZED_MTM', 'MIXED'
    )),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (strategy_id, pnl_date, pnl_environment),
    CHECK (
        (pnl_environment = 'LIVE' AND pnl_settlement_type IN ('CONFIRMED_SETTLED', 'UNREALIZED_MTM', 'MIXED')) OR
        (pnl_environment = 'SHADOW' AND pnl_settlement_type IN ('MODELED_FILL', 'UNREALIZED_MTM', 'MIXED')) OR
        (pnl_environment IN ('REPLAY', 'BACKTEST'))
    )
);

CREATE INDEX idx_pnl_strategy_date ON accounting.strategy_pnl(strategy_id, pnl_date DESC);
CREATE INDEX idx_pnl_portfolio_date ON accounting.strategy_pnl(portfolio_id, pnl_date DESC);
CREATE INDEX idx_pnl_env_date ON accounting.strategy_pnl(pnl_environment, pnl_date DESC);
CREATE INDEX idx_pnl_gate_query ON accounting.strategy_pnl(strategy_id, pnl_date DESC)
    WHERE pnl_environment = 'LIVE' AND pnl_settlement_type = 'CONFIRMED_SETTLED';
```

**Changes:**
1. Renamed `pnl_type` to `pnl_realization_type` (REALIZED/UNREALIZED/MIXED)
2. Added `pnl_environment` (LIVE/SHADOW/REPLAY/BACKTEST)
3. Added `pnl_settlement_type` (CONFIRMED_SETTLED/MODELED_FILL/SIMULATED_FILL/UNREALIZED_MTM/MIXED)
4. Modified UNIQUE constraint to include environment (a strategy can have separate PnL rows for LIVE and SHADOW on the same date during canary phase)
5. Added CHECK constraint enforcing valid environment+settlement combinations
6. Added partial index on the gate-query path (LIVE + CONFIRMED_SETTLED) for fast promotion-Sharpe queries

**The valid environment+settlement combinations:**
- LIVE + CONFIRMED_SETTLED: real cash settled (the only thing that counts for promotion gates per measurement_policy v1.1)
- LIVE + UNREALIZED_MTM: open positions in live trading marked to market (the basis for risk/drawdown monitoring)
- LIVE + MIXED: combination
- SHADOW + MODELED_FILL: paper-adapter fills against live order book (the basis for shadow Sharpe gate)
- SHADOW + UNREALIZED_MTM: open positions in shadow marked to market
- SHADOW + MIXED: combination
- REPLAY + any settlement: historical replay; settlement type indicates fidelity
- BACKTEST + any settlement: research-phase backtests; settlement type indicates fidelity

The CHECK constraint enforces that LIVE environment cannot have MODELED_FILL settlement (live trading produces real fills, not models), and SHADOW cannot have CONFIRMED_SETTLED (paper fills aren't real cash).

### Modified table: accounting.ledger_entries

v0.2 had no environment field. v0.3 adds `pnl_environment` so ledger entries from SHADOW vs LIVE can be filtered without joining back to journals.

**v0.3 schema:**

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
    pnl_environment TEXT NOT NULL CHECK (pnl_environment IN ('LIVE', 'SHADOW', 'REPLAY', 'BACKTEST')),
    pnl_settlement_type TEXT NOT NULL CHECK (pnl_settlement_type IN (
        'CONFIRMED_SETTLED', 'MODELED_FILL', 'SIMULATED_FILL', 'UNREALIZED_MTM'
    )),
    entry_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (
        (pnl_environment = 'LIVE' AND pnl_settlement_type IN ('CONFIRMED_SETTLED', 'UNREALIZED_MTM')) OR
        (pnl_environment = 'SHADOW' AND pnl_settlement_type IN ('MODELED_FILL', 'UNREALIZED_MTM')) OR
        (pnl_environment IN ('REPLAY', 'BACKTEST'))
    )
) PARTITION BY RANGE (entry_at);

CREATE INDEX idx_ledger_entries_journal ON accounting.ledger_entries(journal_id);
CREATE INDEX idx_ledger_entries_account ON accounting.ledger_entries(account_id, entry_at DESC);
CREATE INDEX idx_ledger_entries_at ON accounting.ledger_entries(entry_at DESC);
CREATE INDEX idx_ledger_entries_env ON accounting.ledger_entries(pnl_environment, entry_at DESC);
CREATE INDEX idx_ledger_entries_live_settled
    ON accounting.ledger_entries(account_id, entry_at DESC)
    WHERE pnl_environment = 'LIVE' AND pnl_settlement_type = 'CONFIRMED_SETTLED';
```

The partial index on LIVE + CONFIRMED_SETTLED accelerates the most common query path (promotion gate evaluation, audit, regulatory reporting) without bloating writes.

**Conservation constraint enforced by trigger (refined in v0.3):**

The conservation rule from v0.2 (sum of debits = sum of credits per journal per asset) is now scoped per environment:

- For each journal_id, sum(debits per asset_id per pnl_environment) = sum(credits per asset_id per pnl_environment)

This means a SHADOW journal balances within SHADOW entries; a LIVE journal balances within LIVE entries. A single journal cannot mix environments -- the trigger rejects it.

### Modified table: positions.position_snapshots

The same environment classification needs to apply to position snapshots so the conservative-NAV computation can correctly select LIVE vs SHADOW open positions.

**v0.3 schema:**

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
    pnl_environment TEXT NOT NULL CHECK (pnl_environment IN ('LIVE', 'SHADOW', 'REPLAY', 'BACKTEST')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (position_id, snapshot_date, pnl_environment)
);

CREATE INDEX idx_snapshots_date ON positions.position_snapshots(snapshot_date DESC);
CREATE INDEX idx_snapshots_env ON positions.position_snapshots(pnl_environment, snapshot_date DESC);
```

The UNIQUE constraint includes pnl_environment so a position can have separate LIVE and SHADOW snapshots on the same date (relevant during canary, when the same strategy code path generates both).

## Changes NOT made in v0.3 (deferred to v0.4)

The reviewer flagged additional schema considerations that are not addressed in this patch:

1. **Per-prediction granularity** (`registry.model_predictions`) -- still deferred to v0.4 due to row-volume considerations. Aggregate batch metadata in `registry.signal_batches` remains the v0.3 approach.

2. **Vault and DeFi schemas** -- still deferred to when EBTC scoping begins (Phase 7+).

3. **Options Greeks support** -- still deferred to options engine scoping.

4. **Intelligence schema** (sentiment/news/tokenomics events) -- still deferred to Phase 4+ when those engines are scoped.

5. **Bridge tables for strategy <-> portfolio many-to-many** -- `registry.portfolio_strategies` exists in v0.2 and is sufficient; no v0.3 change.

These deferrals are documented in v0.2 and remain in effect.

## Acceptance criteria additions for v0.3

The eleven acceptance criteria from v0.2 stand. v0.3 adds two:

12. **Environment-aware Sharpe queries:** the gate-evaluation query "show me REALIZED Sharpe over last 90 days for strategy X" filters on `pnl_environment = 'LIVE' AND pnl_settlement_type = 'CONFIRMED_SETTLED'` and returns the correct number distinct from any SHADOW PnL on the same dates.

13. **Conservative NAV queries:** the risk-monitoring query "show me current conservative NAV for portfolio X" includes both LIVE + CONFIRMED_SETTLED and LIVE + UNREALIZED_MTM entries, marked at conservative_exit prices. Excludes SHADOW entries.

These two queries are the operational manifestation of measurement_policy v1.1's REALIZED-only-for-promotion vs conservative-NAV-for-risk distinction.

## Migration note for Phase 1 implementation

Phase 1 implementation builds the v0.3 schema from scratch (no migration from v0.2 needed since v0.2 was a design doc, not a deployed schema). The Phase 1 ledger acceptance test must include:

- Insert a SHADOW + MODELED_FILL row, verify it cannot have CONFIRMED_SETTLED settlement
- Insert a LIVE + CONFIRMED_SETTLED row, verify gate-query returns it
- Insert both LIVE and SHADOW rows for same strategy on same date, verify UNIQUE constraint allows both
- Compute conservative NAV for portfolio, verify SHADOW rows excluded
- Compute promotion Sharpe, verify only LIVE + CONFIRMED_SETTLED rows used

These tests fail if the schema doesn't enforce the typing correctly.

## Revision log

| Version | Date | Author | Changes |
|---|---|---|---|
| 0.1 | 2026-05-02 | Wasseem Katt | Initial design |
| 0.2 | 2026-05-02 | Wasseem Katt + external reviewer | Enterprise ledger upgrade |
| 0.3 | 2026-05-02 | Wasseem Katt + external reviewer | Added pnl_environment and pnl_settlement_type columns to accounting.strategy_pnl, accounting.ledger_entries, positions.position_snapshots. Refined conservation trigger to scope per environment. Added partial indexes on LIVE + CONFIRMED_SETTLED query path. Added two acceptance criteria for environment-aware Sharpe and conservative-NAV queries |

---

## Addendum: corrected gen_uuidv7() function (2026-05-03)

The gen_uuidv7() function specified in the original v0.3 body is incorrect. It produces 18-byte hex strings (36 chars) which cannot be cast to UUID (16 bytes / 32 hex chars). The bug: int8send(unix_ts_ms) returns 8 bytes; concatenated with gen_random_bytes(10) the result is 18 bytes, not 16.

Discovered at Phase 1 dev environment setup (commit b01e333). The corrected implementation, verified working with init-time sanity test:

```sql
CREATE OR REPLACE FUNCTION gen_uuidv7() RETURNS UUID AS $$
DECLARE
    unix_ts_ms_bytes BYTEA;
    rand_bytes BYTEA;
    uuid_bytes BYTEA;
BEGIN
    -- 48-bit timestamp: take last 6 bytes of the 8-byte BIGINT
    unix_ts_ms_bytes := substring(int8send((EXTRACT(EPOCH FROM clock_timestamp()) * 1000)::BIGINT) FROM 3 FOR 6);
    
    -- 10 random bytes for the rest of the 16-byte UUID
    rand_bytes := gen_random_bytes(10);
    
    -- Concatenate: 6 timestamp + 10 random = 16 bytes
    uuid_bytes := unix_ts_ms_bytes || rand_bytes;
    
    -- Set version 7 in byte 6 (top 4 bits = 0111)
    uuid_bytes := set_byte(uuid_bytes, 6, (get_byte(uuid_bytes, 6) & 15) | 112);
    
    -- Set RFC 4122 variant in byte 8 (top 2 bits = 10)
    uuid_bytes := set_byte(uuid_bytes, 8, (get_byte(uuid_bytes, 8) & 63) | 128);
    
    RETURN encode(uuid_bytes, 'hex')::UUID;
END;
$$ LANGUAGE plpgsql VOLATILE;
```

Validation: after install, test with:
```sql
SELECT 
    gen_uuidv7() AS sample,
    length(gen_uuidv7()::text) AS should_be_36,
    substring(gen_uuidv7()::text, 15, 1) AS should_be_7;
```

Expected: valid UUID; length 36; version nibble 7.

Time-ordering: UUIDv7 sorts by millisecond timestamp; sub-millisecond ordering is random per RFC 9562. UUIDs generated in different milliseconds sort in generation order; UUIDs generated within the same millisecond sort randomly. This is by design and acceptable for UUIDv7 use cases (primary keys, time-ordered indexes).

Production reference: infra/postgres/extensions/00_init_extensions.sql committed at b01e333.
