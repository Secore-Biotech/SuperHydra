# Data Ingestion and Feature Store Design v0.2

**Status:** Design draft, ready for Phase 1-2 implementation
**Author:** Wasseem Katt
**Date:** 2026-05-02
**Implements:** data_policy.md v1.1 (vendor registry, freshness SLAs, immutability, quality checks, provenance); model_policy.md v1.1 section 4 (feature governance); measurement_policy.md v1.1 (source typing, empty-source safety, cross-check requirements); deployment_gates.md v1.1 (Shadow data prerequisites)
**Implementation target:** Phase 1 (May 11 - June 15 2026) and Phase 2 (June 15 - July 15 2026), per the SuperHydra Enhanced Plan
**Related:** ledger schema v0.3, validation engine design v0.2, OMS skeleton design v0.2

This document specifies the data layer underneath SuperHydra: how raw data flows from vendors into immutable storage, how features are computed and versioned, how research and live paths consume the same feature values, and how the entire chain is auditable and reproducible end-to-end.

The document is organized in five parts. Parts I-III define the system. Part IV is anti-patterns. Part V is acceptance criteria. The combined-document decision was made because ingestion and feature store have different ownership but share contracts that must be defined together.

## Why this design exists

HYDRA's failures included five distinct integrity failure classes. The fifth — redemption omission ($1,476 in winning tokens uncounted) — maps to a data-layer bug class: real-world events that never made it into the ledger because no ingestion path captured them.

This design prevents that class architecturally:

1. Every data source is registered before consumption
2. Raw data is immutable; vendor corrections create new records, never edits
3. Every raw object has a queryable manifest entry — provenance is queryable, not just navigable
4. Processed data is reproducible from raw via committed scripts
5. Research and live feature computation use the same code path (parity-tested nightly)
6. Lookahead bias is structurally prevented via two-timestamp model + as-of joins
7. Feature freshness is monitored continuously per (vendor, data_type, instrument); stale features halt strategy signal generation
8. Full lineage chain is queryable: raw manifest → canonical → feature values → snapshots → labels → training datasets → validation reports → models → live signals

## Why v0.2 (not v0.1)

v0.2 is the first committed version. The v0.1 prompt was reviewed before committing and produced these structural changes: queryable raw manifest table replacing path-only references; ingestion runs and checkpoints for durable job state; full L2 storage moved to ClickHouse/S3 (not Postgres) for scale; canonical SQL tables alongside dataclasses; explicit source/ingested/available timestamp triple; vendor correction modes (AS_RECORDED/CORRECTED/CURRENT_TRUTH); relational feature dependency tables (not JSONB-only); strategy/model feature dependency mapping; label store with prediction/start/end times; feature freshness state table; FeatureServer with explicit decision_timestamp; instrument spec history and fee schedules; missing-value semantics on feature_values; feature value immutability policy; Shadow freshness matching live; production feature code path; explicit lineage chain section.

## Ownership boundaries

Enforced by code structure, not just convention:
INGESTION owns:
raw vendor data → normalized canonical data

raw manifest, ingestion runs, checkpoints

FEATURE STORE owns:
normalized canonical data → versioned features → research/live serving

feature freshness, snapshots, label store, training datasets

VALIDATION ENGINE owns (per validation engine v0.2):
feature snapshots + label sets → model validation
OMS / RISK KERNEL owns (per OMS v0.2):
live freshness checks before trading

Code in `data/ingestion/` does not compute features. Code in `data/feature_store/` does not call vendor APIs. Code in OMS does not transform data. Code in research notebooks does not write to production registries.

---

# Part I — Data Ingestion

## I.1 Vendor registry contract

Every data source consumed by SuperHydra is registered in `registry.vendors` (per ledger v0.3). Endpoint metadata in registry; credentials in secrets manager only.

```sql
-- registry.vendors per ledger v0.3, with v0.2 additions noted
-- credential_secret_name field references secrets manager entry; never holds value
ALTER TABLE registry.vendors ADD COLUMN IF NOT EXISTS credential_secret_name TEXT;
ALTER TABLE registry.vendors ADD COLUMN IF NOT EXISTS endpoint_config JSONB NOT NULL DEFAULT '{}'::jsonb;
```

**Forbidden:**
- Code paths consuming a vendor not in `registry.vendors`
- Consuming an UNVERIFIED vendor in any production code path (validation engine pipelines, OMS pre-trade checks, live or shadow strategy signal generation)
- Hardcoded vendor URLs in code (use registry.endpoint_config)
- Credentials in registry, code, or git (use secrets manager only; registry holds secret_name reference)
- Research code consuming UNVERIFIED vendors without tagging output as UNVERIFIED

**UNVERIFIED-source handling (research mode):**
- Research code may consume UNVERIFIED sources only when the run is tagged `research_only=true`
- Output datasets generated from UNVERIFIED sources are tagged `verification_status='UNVERIFIED'` in their metadata
- Validation engine rejects datasets tagged UNVERIFIED at admission (per validation engine v0.2)
- Strategies cannot enter Research stage with UNVERIFIED dataset dependencies

**Vendor lifecycle:**

Sign up with vendor (operator action, in browser)
Add row to registry.vendors with status='pending', verified_status='UNVERIFIED'
Store credentials in secrets manager (e.g., AWS Secrets Manager); set credential_secret_name in registry
Implement vendor adapter (data/ingestion/vendors/<vendor>_adapter.py)
Run cross-check verification per measurement_policy v1.1 section 4 (≥5 manual samples)
Sign verification, set verified_status='VERIFIED', last_verified_at=now()
Set status='active'
Quarterly re-verify; if not re-verified in 90 days, status reverts to UNVERIFIED


## I.2 Raw immutable storage

Raw data ingested from any vendor is written to S3/MinIO with versioning enabled. The S3 layer stores bytes; the manifest layer stores audit trail.

**Bucket configuration:**
Bucket: superhydra-raw-data
Versioning: ENABLED
Object lock: COMPLIANCE mode at canary phase (Phase 5+)
Lifecycle: never delete; transition to Glacier after 90 days

**Path convention:**
s3://superhydra-raw-data/
<vendor_name>/
<data_type>/
<symbol>/
year=YYYY/month=MM/day=DD/
<timestamp>_<vendor_record_id>.<format>

## I.3 Raw manifest table (v0.2 addition)

Every raw object written to S3 has a queryable database row. Provenance queries answer via SQL JOIN, not S3 listing.

```sql
CREATE SCHEMA data_ingestion;

CREATE TABLE data_ingestion.raw_records (
    id UUID PRIMARY KEY DEFAULT gen_uuidv7(),
    vendor_id BIGINT NOT NULL REFERENCES registry.vendors(id),
    data_type TEXT NOT NULL,
    vendor_symbol TEXT,
    canonical_instrument_id BIGINT REFERENCES registry.instruments(id),
    vendor_record_id TEXT,
    
    -- Three timestamps per v0.2
    source_timestamp TIMESTAMPTZ,         -- timestamp from vendor (event time)
    ingested_at TIMESTAMPTZ NOT NULL,     -- when SuperHydra received the record
    available_at TIMESTAMPTZ NOT NULL,    -- when downstream can consume (typically = ingested_at)
    
    -- S3 storage pointer
    s3_path TEXT NOT NULL,
    s3_version_id TEXT,
    raw_record_hash TEXT NOT NULL,
    file_size_bytes BIGINT,
    schema_version TEXT NOT NULL,         -- vendor's schema version at ingestion time
    
    -- Correction handling
    correction_of_record_id UUID REFERENCES data_ingestion.raw_records(id),
    correction_received_at TIMESTAMPTZ,
    
    -- Provenance
    ingestion_run_id UUID NOT NULL,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (vendor_id, data_type, vendor_record_id, raw_record_hash)
);

CREATE INDEX idx_raw_records_vendor_type_time 
    ON data_ingestion.raw_records(vendor_id, data_type, source_timestamp DESC);
CREATE INDEX idx_raw_records_instrument 
    ON data_ingestion.raw_records(canonical_instrument_id, source_timestamp DESC);
CREATE INDEX idx_raw_records_corrections 
    ON data_ingestion.raw_records(correction_of_record_id) WHERE correction_of_record_id IS NOT NULL;
CREATE INDEX idx_raw_records_run 
    ON data_ingestion.raw_records(ingestion_run_id);
```

**Rule:** No raw object can be referenced by validation, feature computation, or NAV computation unless it has a corresponding row in `data_ingestion.raw_records`. The manifest is the source of truth for "what raw data exists."

## I.4 Ingestion runs and checkpoints (v0.2 addition)

Durable job state for backfill recovery and live stream resumption.

```sql
CREATE TABLE data_ingestion.ingestion_runs (
    id UUID PRIMARY KEY DEFAULT gen_uuidv7(),
    vendor_id BIGINT NOT NULL REFERENCES registry.vendors(id),
    data_type TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('historical_backfill', 'live_stream', 'reverification')),
    instrument_ids JSONB NOT NULL,
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'canceled')),
    records_ingested BIGINT NOT NULL DEFAULT 0,
    records_rejected BIGINT NOT NULL DEFAULT 0,
    error_summary TEXT,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    initiated_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ingestion_runs_vendor_status 
    ON data_ingestion.ingestion_runs(vendor_id, status, started_at DESC);

CREATE TABLE data_ingestion.ingestion_checkpoints (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    vendor_id BIGINT NOT NULL REFERENCES registry.vendors(id),
    data_type TEXT NOT NULL,
    instrument_id BIGINT REFERENCES registry.instruments(id),
    checkpoint_type TEXT NOT NULL,        -- e.g., 'last_seen_timestamp', 'sequence_number'
    checkpoint_value TEXT NOT NULL,
    checkpoint_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (vendor_id, data_type, instrument_id, checkpoint_type)
);

CREATE INDEX idx_checkpoints_vendor_type 
    ON data_ingestion.ingestion_checkpoints(vendor_id, data_type, checkpoint_at DESC);
```

**Rule:** Every backfill is idempotent — restarting from checkpoint produces identical canonical records. Verified via `raw_record_hash` deduplication on manifest insert.

## I.5 Canonical schemas (Python dataclasses + SQL tables)

Vendor raw schemas convert to canonical schemas. Both Python types and SQL tables specified — Python for code, SQL for storage.

### Python dataclasses

```python
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

@dataclass(frozen=True)
class CanonicalOHLCV:
    canonical_schema_version: str
    instrument_id: int
    source_timestamp: datetime           # timestamp from vendor (the bar's time)
    ingested_at: datetime                # when SuperHydra received it
    available_at: datetime               # when downstream can consume
    interval_seconds: int                # 60, 300, 3600, 86400
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume_base: Decimal
    volume_quote: Decimal
    trade_count: Optional[int]
    vwap: Optional[Decimal]
    raw_record_hash: str

@dataclass(frozen=True)
class CanonicalL2Snapshot:
    canonical_schema_version: str
    instrument_id: int
    source_timestamp: datetime
    ingested_at: datetime
    available_at: datetime
    snapshot_id: str                     # used by PaperAdapter for deterministic replays
    snapshot_hash: str                   # content hash
    storage_backend: str                 # 'clickhouse' or 's3_parquet'
    storage_path: str                    # pointer to actual L2 data
    sequence_number: int                 # vendor's sequence ID for gap detection

@dataclass(frozen=True)
class CanonicalTrade:
    canonical_schema_version: str
    instrument_id: int
    source_timestamp: datetime
    ingested_at: datetime
    available_at: datetime
    venue_trade_id: str
    side: str                            # 'buy' or 'sell' (taker side)
    price: Decimal
    quantity: Decimal
    raw_record_hash: str

@dataclass(frozen=True)
class CanonicalFundingRate:
    canonical_schema_version: str
    instrument_id: int
    source_timestamp: datetime
    ingested_at: datetime
    available_at: datetime
    funding_rate: Decimal                # decimal, not percent (0.0001 = 0.01%)
    interval_hours: int
    raw_record_hash: str

@dataclass(frozen=True)
class CanonicalOnChainMetric:
    canonical_schema_version: str
    metric_name: str
    asset_id: int
    source_timestamp: datetime           # the period the metric represents
    ingested_at: datetime                # when received from vendor
    available_at: datetime               # when usable downstream (often hours after source)
    value: Decimal
    raw_record_hash: str
```

### SQL tables

```sql
CREATE SCHEMA market_data;

CREATE TABLE market_data.ohlcv (
    instrument_id BIGINT NOT NULL REFERENCES registry.instruments(id),
    interval_seconds INTEGER NOT NULL,
    source_timestamp TIMESTAMPTZ NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    open NUMERIC(38,18) NOT NULL,
    high NUMERIC(38,18) NOT NULL,
    low NUMERIC(38,18) NOT NULL,
    close NUMERIC(38,18) NOT NULL,
    volume_base NUMERIC(38,18),
    volume_quote NUMERIC(38,18),
    trade_count INTEGER,
    vwap NUMERIC(38,18),
    raw_record_hash TEXT NOT NULL,
    canonical_schema_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (instrument_id, interval_seconds, source_timestamp)
);
SELECT create_hypertable('market_data.ohlcv', 'source_timestamp', 
    chunk_time_interval => INTERVAL '7 days');

CREATE TABLE market_data.funding_rates (
    instrument_id BIGINT NOT NULL REFERENCES registry.instruments(id),
    source_timestamp TIMESTAMPTZ NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    funding_rate NUMERIC(20,12) NOT NULL,
    interval_hours INTEGER NOT NULL,
    raw_record_hash TEXT NOT NULL,
    canonical_schema_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (instrument_id, source_timestamp)
);
SELECT create_hypertable('market_data.funding_rates', 'source_timestamp',
    chunk_time_interval => INTERVAL '30 days');

CREATE TABLE market_data.on_chain_metrics (
    metric_name TEXT NOT NULL,
    asset_id BIGINT NOT NULL REFERENCES registry.assets(id),
    source_timestamp TIMESTAMPTZ NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    value NUMERIC(38,18) NOT NULL,
    raw_record_hash TEXT NOT NULL,
    canonical_schema_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (metric_name, asset_id, source_timestamp)
);
```

### L2 storage — ClickHouse or S3 Parquet, manifest in Postgres

Postgres stores manifest only; full L2 depth lives in ClickHouse or S3 Parquet.

```sql
CREATE TABLE market_data.l2_snapshot_manifest (
    snapshot_id UUID PRIMARY KEY DEFAULT gen_uuidv7(),
    instrument_id BIGINT NOT NULL REFERENCES registry.instruments(id),
    source_timestamp TIMESTAMPTZ NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    snapshot_hash TEXT NOT NULL,
    sequence_number BIGINT,
    storage_backend TEXT NOT NULL CHECK (storage_backend IN ('clickhouse', 's3_parquet')),
    storage_path TEXT NOT NULL,
    bid_levels INTEGER NOT NULL,         -- count of bid levels in snapshot
    ask_levels INTEGER NOT NULL,
    canonical_schema_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_l2_manifest_instrument_time 
    ON market_data.l2_snapshot_manifest(instrument_id, source_timestamp DESC);
CREATE INDEX idx_l2_manifest_hash 
    ON market_data.l2_snapshot_manifest(snapshot_hash);
```

PaperAdapter (per OMS design v0.2) retrieves L2 snapshots by `snapshot_id` for deterministic shadow runs.

## I.6 Symbol mapping

Per data_policy v1.1 section 9, vendor-specific symbols map to canonical instrument codes via `registry.symbol_translations`.

```sql
CREATE TABLE registry.symbol_translations (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    vendor_id BIGINT NOT NULL REFERENCES registry.vendors(id),
    vendor_symbol TEXT NOT NULL,
    canonical_instrument_id BIGINT NOT NULL REFERENCES registry.instruments(id),
    effective_from TIMESTAMPTZ NOT NULL,
    effective_to TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (vendor_id, vendor_symbol, effective_from)
);

CREATE INDEX idx_symbol_lookup 
    ON registry.symbol_translations(vendor_id, vendor_symbol, effective_from DESC);
```

## I.7 Instrument spec history (v0.2 addition)

Tick size, lot size, contract size, fee schedule — all change over time. Historical backtests must use historical specs, not current.

```sql
CREATE TABLE registry.instrument_specs_history (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    instrument_id BIGINT NOT NULL REFERENCES registry.instruments(id),
    tick_size NUMERIC(38,18),
    lot_size NUMERIC(38,18),
    min_notional NUMERIC(38,18),
    contract_size NUMERIC(38,18),
    price_precision INTEGER,
    quantity_precision INTEGER,
    margin_mode TEXT,
    effective_from TIMESTAMPTZ NOT NULL,
    effective_to TIMESTAMPTZ,
    source TEXT NOT NULL,
    source_record_hash TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_instrument_specs_lookup
    ON registry.instrument_specs_history(instrument_id, effective_from DESC);

CREATE TABLE registry.fee_schedules (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    venue_id BIGINT NOT NULL REFERENCES registry.venues(id),
    account_id BIGINT REFERENCES registry.accounts(id),
    instrument_type TEXT,
    maker_fee_bps NUMERIC(20,12),
    taker_fee_bps NUMERIC(20,12),
    effective_from TIMESTAMPTZ NOT NULL,
    effective_to TIMESTAMPTZ,
    source TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_fee_schedules_lookup
    ON registry.fee_schedules(venue_id, COALESCE(account_id, 0), effective_from DESC);
```

Lookup pattern in cost model and validation engine:
```sql
SELECT * FROM registry.instrument_specs_history
WHERE instrument_id = ? 
  AND effective_from <= ?  -- historical decision time
  AND (effective_to IS NULL OR effective_to > ?)
ORDER BY effective_from DESC LIMIT 1;
```

## I.8 Vendor correction modes (v0.2 addition)

Different consumers need different views of vendor data. Three modes:

| Mode | Definition | Used by |
|---|---|---|
| `AS_RECORDED` | Original record as it was first received from vendor | Live decision replay, validation reproduction, audit |
| `CORRECTED` | Latest verified vendor correction | Research backtests (with explicit choice tagged in report) |
| `CURRENT_TRUTH` | Current best-known state, all corrections applied | Ledger reconciliation, NAV computation, risk monitoring |

Implementation: queries on canonical tables filter by `correction_of_record_id IS NULL` for AS_RECORDED, or join with corrections for CORRECTED, or apply correction chain for CURRENT_TRUTH.

**Rule:** every research dataset records its `data_revision_policy` (one of the three modes). Validation reports include this in their config hash so reproductions use the same policy.

## I.9 Data quality checks

Per data_policy v1.1 section 5, refined for v0.2:

| Check | Computation | Threshold |
|---|---|---|
| Freshness | Time since last update vs SLA | Flag at SLA, halt at 2x SLA |
| Missing data | Gap in expected timestamps | Flag at 1 missing bar, halt at 5 |
| Duplicate data | Repeated timestamps with different values | Flag any occurrence |
| Bad ticks | Price > 5σ from rolling mean | Flag for review, suspend if persistent |
| Symbol mapping | Asset symbol consistency across sources | Hard fail on mismatch |
| Timezone alignment | All timestamps UTC | Hard fail on non-UTC source |
| Volume sanity | Volume = 0 during continuous trading window | Flag for review (crypto trades 24/7, no expected market hours) |
| Cross-source disagreement | Same metric from two sources differs | Per metric tolerance (table below) |

**Cross-source disagreement tolerances (v0.2 refinements):**

| Metric | Tolerance | Notes |
|---|---|---|
| Account balances (cash, position quantity) | 0% (hard fail) | Reconciliation break |
| Spot price (mid) | 0.1% | |
| Volume (1-minute) | 5% | Vendors aggregate trades differently |
| Volume (daily) | 2% | |
| Funding rate | Exact match for same venue event_id | Tolerance based on funding interval alignment when comparing different sources |
| Order book depth at price level | 10% | Snapshot timing differences acceptable |
| On-chain metrics (SOPR, exchange flows) | 5% | Different oracle methodologies |
| Sentiment scores | N/A | Vendor-specific scales |

Quality check results logged continuously to `audit.data_quality_log` (per ledger v0.3, partitioned daily).

## I.10 Freshness states — per (vendor, data_type, instrument)

Freshness is tracked per triple, not per vendor. Tardis BTC may be FRESH while Tardis SOL is DEGRADED.
FRESH       — last update within SLA; consumable for live signals
STALE       — past SLA but less than 2x; degraded but usable for research
DEGRADED    — past 2x SLA; cannot consume for live signals; OMS halts dependent strategies
OUTAGE      — vendor unreachable or returning errors; reconciliation triggered

**Critical rule (v0.2 change from v0.1):** Shadow freshness behavior matches live. STALE/DEGRADED in Shadow halts strategy entries the same way live would. Otherwise Shadow tests less than what live demands, and Shadow results overstate live viability.

## I.11 Vendor adapters (Phase 1-2)

`data/ingestion/vendors/<vendor_name>_adapter.py` per vendor.

```python
from typing import Protocol, AsyncIterator

class VendorIngestionAdapter(Protocol):
    vendor_id: int
    vendor_name: str
    
    async def ingest_historical(
        self,
        instrument_ids: list[int],
        start: datetime,
        end: datetime,
        run_id: UUID,
    ) -> AsyncIterator[RawRecord]:
        """Pulls historical data; yields raw records. Resumes from checkpoint if interrupted."""
        ...
    
    async def stream_live(
        self,
        instrument_ids: list[int],
        run_id: UUID,
    ) -> AsyncIterator[RawRecord]:
        """Live data stream. Reconnects on disconnect; logs to data_quality_log."""
        ...
    
    def supported_data_types(self) -> list[str]:
        ...
    
    def vendor_config(self) -> dict:
        """Endpoints, rate limits, schema versions. No credentials."""
        ...
```

Credentials loaded from secrets manager via `credential_secret_name` from registry. Never in code, env files committed to git, or logs.

**Phase 1-2 adapters:**
- `binance_futures_adapter` — OHLCV, trades, account state, funding rate (Phase 1)
- `tardis_adapter` — L2 order book, trades historical and live (Phase 2)
- `glassnode_adapter` — on-chain metrics (Phase 2 evaluation)
- `ccxt_adapter` — multi-exchange OHLCV abstraction (Phase 1, research only)

## I.12 Ingestion runner

```python
class IngestionRunner:
    def schedule_historical_backfill(
        self, vendor_id, instrument_ids, start, end, initiated_by
    ) -> UUID:
        """
        Idempotent. Reuses raw_record_hash for dedup.
        Returns ingestion_run_id.
        Resumable from ingestion_checkpoints if interrupted.
        """
        ...
    
    def start_live_streams(self, vendor_id, instrument_ids, initiated_by) -> UUID:
        """Long-running task; supervised by systemd."""
        ...
    
    def freshness_state(
        self, vendor_id: int, data_type: str, instrument_id: int
    ) -> FreshnessState:
        """Returns FRESH / STALE / DEGRADED / OUTAGE per (vendor, data_type, instrument)."""
        ...
```

---

# Part II — Feature Store

## II.1 Feature registry

Per ledger v0.3 `registry.features`. Versioned; changes create new version, never modify existing.

**Forbidden:**
- Features in models that aren't registered
- Hardcoded feature computations in strategy code
- Inline feature computation bypassing the registry
- Production feature code outside `data/feature_store/features/` (research/factors is for prototyping only)

## II.2 Feature dependency tables (v0.2 addition)

JSONB metadata is okay for human reading; relational dependency tables enforce the DAG.

```sql
CREATE SCHEMA feature_store;

CREATE TABLE feature_store.feature_dependencies (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    feature_id BIGINT NOT NULL REFERENCES registry.features(id),
    feature_version INTEGER NOT NULL,
    dependency_type TEXT NOT NULL CHECK (dependency_type IN (
        'canonical_data', 'feature', 'vendor_metric', 'instrument_spec', 'fee_schedule'
    )),
    -- Exactly one of the following groups populated based on dependency_type
    dependency_feature_id BIGINT REFERENCES registry.features(id),
    dependency_feature_version INTEGER,
    vendor_id BIGINT REFERENCES registry.vendors(id),
    canonical_data_type TEXT,
    instrument_id BIGINT REFERENCES registry.instruments(id),
    required BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    CHECK (
        (dependency_type = 'feature' AND dependency_feature_id IS NOT NULL) OR
        (dependency_type IN ('canonical_data', 'vendor_metric') AND vendor_id IS NOT NULL) OR
        (dependency_type IN ('instrument_spec', 'fee_schedule'))
    )
);

CREATE INDEX idx_feature_deps_lookup ON feature_store.feature_dependencies(feature_id, feature_version);
CREATE INDEX idx_feature_deps_reverse ON feature_store.feature_dependencies(dependency_feature_id, dependency_feature_version);
CREATE INDEX idx_feature_deps_vendor ON feature_store.feature_dependencies(vendor_id) WHERE vendor_id IS NOT NULL;
```

This answers SQL queries like:
- "Which features depend on Tardis L2?"
- "Which features depend on funding_zscore:v3?"
- "If Tardis goes DEGRADED, which features become invalid?"

## II.3 Strategy/model feature dependency mapping (v0.2 addition)

OMS `require_data_fresh` check needs to know which features each strategy depends on.

```sql
CREATE TABLE registry.model_features (
    model_id BIGINT NOT NULL REFERENCES registry.models(id),
    feature_id BIGINT NOT NULL REFERENCES registry.features(id),
    feature_version INTEGER NOT NULL,
    required BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (model_id, feature_id, feature_version)
);

CREATE TABLE registry.strategy_feature_dependencies (
    strategy_id BIGINT NOT NULL REFERENCES registry.strategies(id),
    feature_id BIGINT NOT NULL REFERENCES registry.features(id),
    feature_version INTEGER NOT NULL,
    required BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (strategy_id, feature_id, feature_version)
);

CREATE INDEX idx_model_features_feature ON registry.model_features(feature_id, feature_version);
CREATE INDEX idx_strategy_features_feature ON registry.strategy_feature_dependencies(feature_id, feature_version);
```

`require_data_fresh` check:
```sql
SELECT f.feature_id, f.feature_version, ff.state
FROM registry.strategy_feature_dependencies sfd
JOIN feature_store.feature_freshness ff
  ON ff.feature_id = sfd.feature_id 
  AND ff.feature_version = sfd.feature_version
WHERE sfd.strategy_id = $1 
  AND sfd.required = TRUE
  AND ff.state IN ('DEGRADED', 'OUTAGE');
-- Any rows returned → reject the order
```

## II.4 Feature versioning and immutability

Feature values are immutable. Vendor corrections or computation bug fixes create new feature versions, not in-place updates.

```sql
CREATE TABLE feature_store.feature_values (
    id UUID NOT NULL DEFAULT gen_uuidv7() PRIMARY KEY,
    feature_id BIGINT NOT NULL REFERENCES registry.features(id),
    feature_version INTEGER NOT NULL,
    instrument_id BIGINT NOT NULL REFERENCES registry.instruments(id),
    
    -- Two timestamps for lookahead prevention
    as_of_timestamp TIMESTAMPTZ NOT NULL,           -- the timestamp this value applies to
    available_at_timestamp TIMESTAMPTZ NOT NULL,    -- when this value first became computable
    
    -- Value with explicit type and missing-value semantics (v0.2 addition)
    value_type TEXT NOT NULL CHECK (value_type IN ('numeric', 'string', 'json', 'missing')),
    value NUMERIC(38,18),
    value_string TEXT,
    value_json JSONB,
    missing_reason TEXT,
    
    computation_metadata JSONB NOT NULL,            -- raw record hashes, intermediate values
    computation_script_hash TEXT NOT NULL,          -- which script produced this
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    UNIQUE (feature_id, feature_version, instrument_id, as_of_timestamp),
    
    CHECK (
        (value_type = 'numeric' AND value IS NOT NULL AND value_string IS NULL AND value_json IS NULL AND missing_reason IS NULL)
        OR
        (value_type = 'string' AND value_string IS NOT NULL AND value IS NULL AND value_json IS NULL AND missing_reason IS NULL)
        OR
        (value_type = 'json' AND value_json IS NOT NULL AND value IS NULL AND value_string IS NULL AND missing_reason IS NULL)
        OR
        (value_type = 'missing' AND missing_reason IS NOT NULL AND value IS NULL AND value_string IS NULL AND value_json IS NULL)
    )
) PARTITION BY RANGE (as_of_timestamp);

CREATE INDEX idx_feature_values_lookup 
    ON feature_store.feature_values(feature_id, feature_version, instrument_id, as_of_timestamp DESC);
CREATE INDEX idx_feature_values_available 
    ON feature_store.feature_values(available_at_timestamp DESC);
```

**Missing-value semantics (v0.2):** A feature that cannot compute (input data missing, dependency outage, computation error) writes a row with `value_type='missing'` and `missing_reason` populated. Silent zero or NULL is forbidden — that's the empty-source-safety lesson from measurement_policy v1.1 applied at the feature layer.

**Immutability rule:** A row in `feature_values` is never updated after insert. Corrections create new feature versions or new feature snapshots.

## II.5 Feature freshness state table (v0.2 addition)

```sql
CREATE TABLE feature_store.feature_freshness (
    feature_id BIGINT NOT NULL REFERENCES registry.features(id),
    feature_version INTEGER NOT NULL,
    instrument_id BIGINT REFERENCES registry.instruments(id),
    state TEXT NOT NULL CHECK (state IN ('FRESH', 'STALE', 'DEGRADED', 'OUTAGE')),
    last_computed_at TIMESTAMPTZ,
    last_available_at TIMESTAMPTZ,
    expected_next_at TIMESTAMPTZ,
    reason TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (feature_id, feature_version, COALESCE(instrument_id, 0))
);

CREATE INDEX idx_freshness_state ON feature_store.feature_freshness(state) WHERE state IN ('DEGRADED', 'OUTAGE');
```

Updated by feature computation runner on each compute pass, and by quality runner when underlying data sources change state. OMS `require_data_fresh` reads this table directly.

## II.6 Feature computation DAG

Topologically sorted from the dependency tables.

```python
class FeatureComputationRunner:
    def compute_pass(self, as_of: datetime):
        """
        Compute all features whose dependencies are satisfied at as_of time.
        Topological sort from feature_dependencies table.
        Skip features whose dependencies are DEGRADED or OUTAGE 
          (writes 'missing' row with missing_reason='dependency_unavailable').
        """
        ...
    
    def compute_feature(
        self,
        feature_id: int,
        feature_version: int,
        instrument_id: int,
        as_of: datetime,
    ) -> FeatureValue:
        """
        Compute a single feature. Loads dependencies via dependency table.
        Returns FeatureValue with computation_metadata recording 
          dependency feature_value IDs and raw_record_hashes used.
        """
        ...
```

## II.7 As-of joins and lookahead prevention

Per data_policy v1.1 section 6 and validation engine v0.2:

```sql
-- Query feature value at decision time T
SELECT * FROM feature_store.feature_values
WHERE feature_id = ?
  AND feature_version = ?
  AND instrument_id = ?
  AND as_of_timestamp <= $T
  AND available_at_timestamp <= $T
ORDER BY as_of_timestamp DESC
LIMIT 1;
```

Both timestamps must be ≤ decision time. Backtests at time T cannot consult features that became available after T.

## II.8 Research vs live parity

Same code computes features in both paths. Parity verified nightly per model_policy v1.1.

```python
def run_parity_test_for_feature(feature_id: int, feature_version: int):
    """
    Pick 100 random (instrument_id, as_of_timestamp) pairs from past 30 days.
    For each pair:
        # Research path: recompute from canonical data with same as_of/available_at rules
        research_value = compute_feature_from_canonical(
            feature_id, feature_version, instrument_id, as_of_timestamp
        )
        # Live path: fetch what the live runner stored
        live_value = feature_store.fetch(
            feature_id, feature_version, instrument_id, as_of_timestamp
        )
        assert research_value == live_value (within float tolerance for numeric, exact for others)
    
    Test cases must include:
        - Normal (data complete)
        - Missing data (dependency was unavailable; both should produce 'missing' value type)
        - Delayed availability (dependency arrived after as_of but before available_at)
        - Vendor correction (after correction was received, but as-of-recorded view)
    """
```

**Failure response (v0.2 strengthened):** If a required feature fails parity, action is automatic:
- Shadow strategies consuming the feature: HALT strategy entries (per shadow-matches-live rule)
- Canary/scale strategies consuming the feature: BLOCK new orders, REDUCE-ONLY mode for existing positions, OPERATOR ALERT
- Models trained against the failing feature: MARK as parity_test_failing in registry.models
- Validation engine: REJECT new validation runs against the failing feature

P1 incident logged per incident_severity_policy v1.0. v0.1's "alert and continue" was too lenient.

## II.9 Feature snapshots

```sql
CREATE TABLE feature_store.feature_snapshots (
    id UUID NOT NULL DEFAULT gen_uuidv7() PRIMARY KEY,
    snapshot_name TEXT NOT NULL UNIQUE,
    snapshot_hash TEXT NOT NULL,
    as_of_timestamp TIMESTAMPTZ NOT NULL,
    instrument_count INTEGER NOT NULL,
    feature_count INTEGER NOT NULL,
    snapshot_data_path TEXT NOT NULL,
    storage_backend TEXT NOT NULL CHECK (storage_backend IN ('s3_parquet', 'postgres_materialized')),
    data_revision_policy TEXT NOT NULL CHECK (data_revision_policy IN ('AS_RECORDED', 'CORRECTED', 'CURRENT_TRUTH')),
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE feature_store.feature_snapshot_items (
    snapshot_id UUID NOT NULL REFERENCES feature_store.feature_snapshots(id) ON DELETE RESTRICT,
    feature_id BIGINT NOT NULL REFERENCES registry.features(id),
    feature_version INTEGER NOT NULL,
    PRIMARY KEY (snapshot_id, feature_id, feature_version)
);

CREATE INDEX idx_snapshot_items_feature ON feature_store.feature_snapshot_items(feature_id, feature_version);
```

Snapshots are append-only. A snapshot referenced by a validation report (per validation engine v0.2) cannot be deleted while the report exists.

## II.10 Label store (v0.2 addition)

Required by validation engine v0.2 for proper CPCV purging. Labels include explicit start/end times.

```sql
CREATE TABLE feature_store.label_sets (
    id UUID NOT NULL DEFAULT gen_uuidv7() PRIMARY KEY,
    label_set_name TEXT NOT NULL,
    label_set_hash TEXT NOT NULL UNIQUE,
    label_type TEXT NOT NULL CHECK (label_type IN (
        'forward_return', 'rank_return', 'classification', 
        'tail_loss', 'execution_slippage', 'event_outcome'
    )),
    horizon_minutes INTEGER NOT NULL,
    description TEXT,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE feature_store.labels (
    id UUID NOT NULL DEFAULT gen_uuidv7() PRIMARY KEY,
    label_set_id UUID NOT NULL REFERENCES feature_store.label_sets(id),
    instrument_id BIGINT NOT NULL REFERENCES registry.instruments(id),
    prediction_time TIMESTAMPTZ NOT NULL,
    label_start_time TIMESTAMPTZ NOT NULL,
    label_end_time TIMESTAMPTZ NOT NULL,
    target_value NUMERIC(38,18),
    target_class TEXT,
    label_metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (label_set_id, instrument_id, prediction_time)
);

CREATE INDEX idx_labels_lookup 
    ON feature_store.labels(label_set_id, prediction_time);
CREATE INDEX idx_labels_instrument 
    ON feature_store.labels(instrument_id, prediction_time);
```

CPCV purging in validation engine uses `label_end_time` to identify overlapping samples that must be purged from training folds.

## II.11 Training datasets

```sql
CREATE TABLE feature_store.training_datasets (
    id UUID NOT NULL DEFAULT gen_uuidv7() PRIMARY KEY,
    training_data_hash TEXT NOT NULL UNIQUE,
    feature_snapshot_id UUID NOT NULL REFERENCES feature_store.feature_snapshots(id),
    label_set_id UUID NOT NULL REFERENCES feature_store.label_sets(id),
    split_spec JSONB NOT NULL,
    train_row_count BIGINT NOT NULL,
    val_row_count BIGINT NOT NULL,
    test_row_count BIGINT NOT NULL,
    dataset_path TEXT NOT NULL,
    storage_backend TEXT NOT NULL CHECK (storage_backend IN ('s3_parquet', 'postgres_materialized')),
    lookahead_test_passed BOOLEAN NOT NULL,
    survivorship_test_passed BOOLEAN NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_training_datasets_snapshot 
    ON feature_store.training_datasets(feature_snapshot_id);
CREATE INDEX idx_training_datasets_labels 
    ON feature_store.training_datasets(label_set_id);
```

Training dataset builder verifies lookahead absence (every row's feature `available_at <= label.prediction_time`) and records the result as `lookahead_test_passed`.

## II.12 FeatureServer with explicit decision_timestamp (v0.2)

```python
class FeatureServer:
    def get_feature(
        self,
        feature_id: int,
        feature_version: int,
        instrument_id: int,
        decision_timestamp: datetime,
    ) -> FeatureValue:
        """
        Returns most recent feature value where:
            as_of_timestamp <= decision_timestamp
            available_at_timestamp <= decision_timestamp
        
        For LIVE path: caller passes decision_timestamp = current_utc()
        For REPLAY/BACKTEST: caller passes decision_timestamp = historical prediction time
        
        Raises FeatureStaleError if freshness state is DEGRADED or OUTAGE.
        Returns FeatureValue with value_type='missing' if no satisfying value exists.
        """
        ...
```

Same code path for live and replay — only the `decision_timestamp` differs. This is what makes parity automatic.

---

# Part III — Shared Contracts

## III.1 Provenance and lineage (v0.2 strengthened)

The full lineage chain, every link queryable via SQL JOIN:
data_ingestion.raw_records         -- raw S3 manifest
↓ (raw_record_hash)
market_data.<canonical_table>      -- canonical data
↓ (raw_record_hash)
feature_store.feature_values       -- feature values
↓ (computation_metadata.feature_value_ids)
feature_store.feature_snapshots    -- frozen snapshots

feature_store.feature_snapshot_items
↓ (snapshot_id)
feature_store.training_datasets    -- training datasets
feature_store.label_sets/labels
↓ (training_data_hash)
validation.reports                 -- validation runs (per validation engine v0.2)
↓ (model_id)
registry.models                    -- deployed models
↓ (model_id, signal_batch_id)
registry.signal_batches            -- live signals
↓ (signal_batch_id, allocator_run_id)
registry.allocator_runs            -- allocator decisions
↓ (allocator_run_id)
registry.target_weights            -- target portfolio weights
↓ (target_weight_id)
trading.order_intents              -- order intents (per OMS v0.2)
↓ (intent_uuid)
trading.orders                     -- venue orders
↓ (order_uuid)
trading.fills                      -- confirmed fills
↓ (fill_id)
accounting.ledger_entries          -- double-entry ledger (per ledger v0.3)
↓ (journal_id)
accounting.nav_snapshots           -- NAV
↓ (portfolio_id, snapshot_date)
accounting.strategy_pnl            -- daily PnL


A live strategy's PnL traces all the way back to specific raw vendor records through this chain via SQL JOIN. Audit and compliance queries become tractable.

## III.2 Reproducibility primitives

1. **Raw data immutable.** Same S3 versionId = same bytes forever.
2. **Computation deterministic.** Same canonical input + same script hash = same output.
3. **Versioning enforced.** Feature value never updated; corrections create new versions.
4. **Snapshots immutable.** Snapshot referenced by a validation report cannot be deleted.

Verified by validation engine `engine.reproduce(report_id)` per validation engine v0.2.

## III.3 Lookahead prevention primitives

1. Two-timestamp model: `as_of_timestamp` and `available_at_timestamp` on every feature value
2. As-of joins: queries filter on both timestamps
3. Embargo periods: training data has explicit gap between train and test
4. Bias test suite: validation engine v0.2 runs 6 lookahead tests including timestamp_audit and negative_control
5. Parity check: research and live paths produce identical values

If any fail, lookahead becomes possible. Verified continuously.

## III.4 Schema integration
registry.vendors / registry.symbol_translations / registry.instruments /
registry.instrument_specs_history / registry.fee_schedules / registry.assets
←  consumed by ingestion
data_ingestion.raw_records / ingestion_runs / ingestion_checkpoints
←  produced by ingestion
market_data.* (ohlcv, funding_rates, on_chain_metrics, l2_snapshot_manifest)
←  produced by ingestion, consumed by feature store
registry.features / feature_store.feature_dependencies
←  feature definitions
registry.model_features / registry.strategy_feature_dependencies
←  consumption mapping (used by OMS)
feature_store.feature_values / feature_freshness / feature_snapshots /
feature_snapshot_items / label_sets / labels / training_datasets
←  feature computation and serving
audit.data_quality_log
←  quality checks
audit.measurement_audit
←  vendor verification records
accounting.mark_prices
←  consumed by NAV computation, produced by ingestion

## III.5 Validation engine integration

Per validation engine v0.2:
- ScientificValidationConfig references `feature_set_hash` (= feature_snapshot snapshot_hash) and `data_snapshot_hash`
- Resolves to specific feature_snapshots and training_datasets rows
- Validation runs reproducible because snapshots and training datasets are immutable
- LabelSpec dataclass populated from feature_store.labels rows

## III.6 OMS / Risk Kernel integration

Per OMS design v0.2:
- `require_data_fresh` pre-trade check joins `registry.strategy_feature_dependencies` with `feature_store.feature_freshness`
- Any required feature in DEGRADED or OUTAGE rejects orders for the strategy
- FeatureServer queried by live strategies with decision_timestamp = current_utc()

## III.7 Ledger integration

Per ledger schema v0.3:
- `audit.data_quality_log` partitioned daily, populated by quality runner
- `registry.vendors` has verified_status driving production-vs-research access
- `registry.features` parity_test_passing flag drives model promotion eligibility
- `accounting.mark_prices` populated by ingestion (mark price source for NAV)

---

# Part IV — Anti-patterns and explicit non-goals

**Anti-pattern 1: Computing aggregates at ingest time.** Aggregates depend on as-of windows; computing at ingest hardcodes the window. Right: store raw + canonical only; aggregates are versioned features.

**Anti-pattern 2: Caching feature values in strategy code.** Defeats freshness checks. Right: every read goes through FeatureServer.

**Anti-pattern 3: Denormalizing for query speed.** Pre-joining locks in feature versions; updates require rewriting. Right: keep features normalized; build snapshots on demand.

**Anti-pattern 4: Skipping verification because vendor is "obviously correct."** "Obvious correctness" is the assumption that produced HYDRA's MM measurement fiction. Right: every vendor goes through ≥5-sample cross-check verification.

**Anti-pattern 5: Implicit feature dependencies.** Right: every dependency declared in feature_dependencies table; computation runner reads from registry.

**Anti-pattern 6: Live and research feature paths diverge.** Parity test fails; floating-point differences accumulate. Right: same code path; parity test enforces nightly.

**Anti-pattern 7: Using "current" data instead of "as-of" data.** Tick size, fee schedule, instrument metadata change over time. Right: query `instrument_specs_history` and `fee_schedules` joined on effective_from <= as_of.

**Anti-pattern 8: Silent zero or NULL for missing feature values.** Right: explicit `value_type='missing'` with `missing_reason`.

**Anti-pattern 9: Production feature code in research/factors/.** Research is for prototyping; production code lives in `data/feature_store/features/`.

**Anti-pattern 10: Credentials in registry, code, or env files in git.** Right: secrets manager only; registry holds secret_name reference.

**Anti-pattern 11: Shadow allowing STALE data while live halts.** Makes Shadow tests less than live demands. Right: Shadow freshness behavior matches live.

**Anti-pattern 12: Comments-only enforcement of UNVERIFIED sources.** A `# UNVERIFIED_SOURCE` comment isn't enforcement. Right: research mode tags output as UNVERIFIED; validation engine rejects UNVERIFIED-tagged datasets.

**Anti-pattern 13: Updating feature_values rows in place.** Breaks reproducibility. Right: feature values immutable; corrections create new versions.

**Anti-pattern 14: Putting full L2 history in Postgres/TimescaleDB.** Will choke at Tardis volumes. Right: ClickHouse or S3 Parquet; manifest in Postgres.

---

# Part V — Implementation scope and acceptance criteria

## Phase 1 (May 11 - June 15)

Implements:
- `registry.vendors`, `registry.symbol_translations`, `registry.instruments`, `registry.instrument_specs_history`, `registry.fee_schedules`
- `data_ingestion.raw_records`, `ingestion_runs`, `ingestion_checkpoints`
- Vendor adapter interface (Protocol)
- Binance Futures adapter (free; primary venue)
- CCXT adapter (free; research convenience layer)
- Canonical schemas: CanonicalOHLCV, CanonicalFundingRate
- SQL canonical tables: market_data.ohlcv, market_data.funding_rates
- Quality check runner skeleton with freshness, missing-data, duplicate, bad-tick checks
- Feature registry skeleton (`registry.features`, `feature_store.feature_dependencies`; no features yet)
- `feature_store.feature_values`, `feature_freshness` tables
- `audit.data_quality_log`

Sufficient to validate ledger v0.3 against historical Binance fills.

## Phase 2 (June 15 - July 15)

Adds:
- Tardis adapter (after Academic onboarding completes)
- Glassnode adapter (free tier evaluation)
- Canonical schemas: CanonicalL2Snapshot, CanonicalTrade, CanonicalOnChainMetric
- L2 storage backend (ClickHouse or S3 Parquet) + `market_data.l2_snapshot_manifest`
- 30-50 features per model_policy v1.1 ceiling
- Feature computation runner with DAG topological sort
- Parity test runner (nightly cron)
- Feature snapshot generation
- `feature_store.label_sets`, `feature_store.labels`, `feature_store.training_datasets`, `feature_store.feature_snapshots`, `feature_store.feature_snapshot_items`
- Training dataset builder with lookahead and survivorship verification
- FeatureServer with decision_timestamp API
- `registry.model_features`, `registry.strategy_feature_dependencies`

## Phase 1 acceptance criteria

1. **Vendor registry populated.** Binance Futures registered, status='active', verified_status='VERIFIED'.
2. **Binance adapter functional.** Historical OHLCV backfill works for top 30 perps over 12 months; live stream stays connected.
3. **Canonical normalization.** Raw Binance records convert to CanonicalOHLCV deterministically; same raw input produces identical canonical output across two runs.
4. **Quality checks running.** Freshness, missing-data, duplicate, bad-tick checks log to audit.data_quality_log.
5. **Symbol translation.** registry.symbol_translations populated for top 30 instruments; queries via canonical instrument_code resolve correctly.
6. **Empty-source safety.** Ingestion runner with no active vendors raises NoDataError; doesn't silently produce empty result.
7. **S3 immutability verified.** Raw record written to S3 cannot be modified (versioning catches attempt).
8. **Raw manifest exists.** Every raw S3 object has a row in `data_ingestion.raw_records`. Verified by manifest-vs-S3 reconciliation test.
9. **Ingestion idempotency.** Rerunning the same Binance OHLCV backfill does not duplicate canonical records.
10. **Ingestion checkpoint recovery.** Interrupted backfill resumes from checkpoint and produces identical result.
11. **Canonical SQL tables exist.** Not only dataclasses; SQL tables created and migration tested.
12. **Instrument spec history exists.** Tick size / lot size / min notional effective-dated; lookups by historical timestamp return correct historical spec.
13. **Vendor source enforcement.** Failing test verified: code attempting to consume vendor with status='pending' or verified_status='UNVERIFIED' raises VendorNotAvailableError.

## Phase 2 acceptance criteria

In addition to Phase 1:

14. **Tardis adapter functional.** L2 snapshots, trades, funding for top 30 perps; both historical and live.
15. **Tardis VERIFIED.** ≥5 manual cross-checks against Binance public API confirm Tardis data correctness.
16. **Glassnode adapter functional.** SOPR, exchange flows, supply metrics fetchable; data stored as CanonicalOnChainMetric.
17. **L2 snapshot determinism.** PaperAdapter can retrieve a specific Tardis snapshot by snapshot_id/hash; same retrieval produces identical bytes.
18. **Feature parity test passing.** Sample feature implemented in research and live paths; parity test passes nightly with 100-sample audit.
19. **Feature dependency propagation.** Degrading a vendor source marks dependent features as DEGRADED in feature_freshness.
20. **Strategy dependency mapping.** require_data_fresh can identify all features required by a strategy/model via SQL JOIN on registry.strategy_feature_dependencies.
21. **Label store functional.** Labels contain prediction_time, label_start_time, label_end_time; CPCV purge query removes overlapping samples correctly.
22. **Feature correction policy tested.** Vendor correction creates new feature version, not silent mutation; old feature_values rows remain intact.
23. **FeatureServer replay determinism.** Same decision_timestamp returns same feature value in research and live-style replay paths.
24. **Missing feature semantics.** Missing values are explicit (value_type='missing') and cannot become silent zero. Verified by inserting a known-bad input and checking result type.
25. **Cross-source disagreement detection.** Deliberate disagreement between vendor sources triggers data_quality_log flag with appropriate tolerance per metric type.
26. **Vendor outage handling.** Simulated 4-hour outage triggers re-verification requirement; vendor returns to UNVERIFIED status.

## Open design questions deferred to implementation

1. **L2 snapshot storage compression.** Tardis L2 data voluminous (GB/day/venue). Phase 2 may use parquet + zstd; cost-vs-query trade-off resolved when actual volumes observed.

2. **Feature backfill strategy.** New feature version: backfill last 12 months by default; older periods on-demand only.

3. **Streaming feature computation vs batch.** Phase 2 batch (compute at fixed cadence). Phase 4+ may add streaming for latency-sensitive features.

4. **Feature TTL and pruning.** Phase 2 retains indefinitely. Pruning revisited if storage exceeds budget.

5. **Multi-venue feature normalization.** Cross-venue features (e.g., basis between Binance and OKX) require multi-venue support. Phase 7+.

6. **Real-time vendor disagreement alerting.** Streaming compute. Phase 4+ optimization.

7. **Schema evolution within canonical types.** New field needed: new schema_version (`ohlcv_v2`); old data remains v1; consumers handle both.

8. **ClickHouse vs S3 Parquet for L2 storage.** Decided in Phase 2 implementation based on observed query patterns.

## Revision log

| Version | Date | Author | Changes |
|---|---|---|---|
| 0.1 | 2026-05-02 | Wasseem Katt | Drafted but not committed; reviewed before commit |
| 0.2 | 2026-05-02 | Wasseem Katt | First committed version. Added raw manifest table, ingestion runs and checkpoints, source/ingested/available timestamp triple, vendor correction modes, relational feature dependency tables, strategy/model feature dependency mapping, label store, feature freshness state table, FeatureServer with explicit decision_timestamp, instrument spec history and fee schedules, missing-value semantics, feature value immutability policy, Shadow freshness matches live, production feature code path, full lineage chain section, ClickHouse/S3-Parquet for L2, canonical SQL tables, secrets-manager rule, UNVERIFIED-source enforcement via dataset tagging, parity-failure halt rule. 11 must-fix safety/correctness fixes from review applied; 13 should-fix improvements applied; 1 deferred (acceptance criteria additions, all 13 applied) |
