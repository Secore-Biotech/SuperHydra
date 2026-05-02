# Data Policy

**Version:** 1.0
**Effective:** 2026-05-02
**Author:** Wasseem Katt
**Source:** SuperHydra Enhanced Plan; HYDRA postmortem 2026-05-01; vendor decisions logged in docs/decisions/

This policy defines what data is permitted in SuperHydra, where it comes from, how fresh it must be, and how its integrity is guaranteed. The data layer is the foundation under measurement, risk, and model policies. Bad data invalidates everything downstream.

## 1. Vendor registry

Every data source in SuperHydra must be registered here. Sources not registered are forbidden in production code paths.

| Vendor | Data type | Tier (current) | Phase 1 use | Status |
|---|---|---|---|---|
| Binance API | OHLCV, trades, account state | Free | Yes -- primary execution venue | Active |
| CCXT (library) | Multi-exchange OHLCV abstraction | Free (open-source) | Yes -- research convenience layer | Active |
| Tardis.dev | L2 order book + trades historical and live | Academic ($650/mo, pending) | Yes -- required from Phase 2 (Jun 15) | Pending signup |
| Glassnode | On-chain metrics, exchange flows | Free tier | Phase 2 evaluation only; upgrade to Advanced when Phase 2 features built | Active free tier |
| Polygon RPC | On-chain reads (legacy HYDRA wallet) | Free public RPC | Decommissioning with HYDRA freeze May 15 | Sunsetting |
| (Future) Glassnode Advanced | Real-time SOPR, supply, exchange flows | $800/mo | Phase 2-3 when on-chain features built | Deferred |
| (Future) Tardis Pro | More venues, longer history, premium connectivity | $1,200+/mo | Phase 5+ if multi-venue work begins | Deferred |

**Forbidden:**
- Free public APIs without rate-limit guarantees in production code (acceptable for one-off research; not for live signal generation)
- Scraping any source not on this registry
- Using a source for live signals before it is tagged `VERIFIED` per measurement_policy.md section 4

Vendor changes (additions, removals, tier changes) require this policy doc to be updated and re-committed.

## 2. Freshness SLAs

Every data source has a maximum staleness threshold. Data older than its SLA is treated as missing for the purpose of signal generation. The risk kernel pre-trade check `require_data_fresh` enforces these.

| Source | Data type | Freshness SLA |
|---|---|---|
| Binance live API | Account balances, position state | 5 seconds |
| Binance live API | Order book top of book | 1 second |
| Tardis live | L2 order book full depth | 5 seconds |
| Tardis live | Trade tick stream | 5 seconds |
| Binance/Tardis | OHLCV bars (1m) | 90 seconds (1 bar + 30s grace) |
| Binance/Tardis | OHLCV bars (1h) | 1 hour 5 minutes |
| Glassnode (Advanced) | On-chain hourly metrics | 2 hours |
| Glassnode (Standard, free tier) | Daily metrics | 36 hours |
| Funding rate API | Current funding rate | 5 minutes |

**Stale-data response:**
- Source goes stale: signals dependent on that source are suspended
- Strategy with all-stale sources: pauses new orders, manages existing positions only
- Stale period > 5 minutes: strategy halts entirely until source recovers
- Stale period > 1 hour: operator alert, manual review of strategy state

**Vendor outage handling:**
- Outage detected by missed expected updates exceeding 2x the freshness SLA
- Outage triggers reconciler to pause signal generation for affected strategies
- Outage > 4 hours triggers a re-verification requirement when source recovers (per measurement_policy.md section 4)

## 3. Immutability and reproducibility

**Raw data is immutable:**
- Raw data ingested from any vendor is written to S3/MinIO storage with timestamp and vendor identifier
- Raw data files are never modified after write
- Corrections from vendor (e.g., fill restated by exchange) are written as new records, not edits to existing records
- Storage uses versioned bucket configuration to prevent accidental overwrite

**Processed data is reproducible:**
- Any processed dataset (cleaned OHLCV, computed features, training datasets) must be reproducible from raw data using committed scripts
- Processing scripts are versioned in git
- Datasets used in model training are tagged with: source raw data version, processing script version, processing timestamp
- A processed dataset that cannot be reproduced from registered sources is invalid

**Forbidden:**
- Hand-edited data files in production paths
- Datasets with unknown provenance
- "Cleaned" data without a script that produces it from raw

## 4. Data quality checks

Every data feed runs continuous quality checks. Failure of any check flags the source as `DEGRADED` and triggers operator alert.

| Check | Computation | Threshold |
|---|---|---|
| Freshness | Time since last update vs SLA | Flag at SLA, halt at 2x SLA |
| Missing data | Gap in expected timestamps | Flag at 1 missing bar, halt at 5 |
| Duplicate data | Repeated timestamps with different values | Flag at any occurrence |
| Bad ticks | Price > 5 sigma from rolling mean (extreme outliers) | Flag for review, suspend if persistent |
| Symbol mapping | Asset symbol consistency across sources | Hard fail on mismatch |
| Timezone alignment | All timestamps UTC | Hard fail on non-UTC source |
| Volume sanity | Volume = 0 during expected market hours | Flag for review |
| Cross-source disagreement | Same metric from two sources differs > 1% | Flag for review |

Quality check results are logged to `data_quality_log` continuously. Quarterly review covers patterns of degradation by source.

## 5. Lookahead bias controls

The single largest backtest failure mode in quant work. Controls:

**Required at every level:**
- Every dataset has an as-of timestamp; queries must respect "data available at time T"
- Feature computation never uses data later than the prediction time
- Walk-forward training has explicit embargo period (per model_policy.md section 2)
- Validation harness includes a "shuffle future" lookahead-bias test (per model_policy.md section 2)

**Forbidden:**
- Computing features over the entire dataset before splitting (creates leakage)
- Using survivor-only universe in historical training (creates survivorship bias which is a relative of lookahead)
- Importing future data through any "convenience" path (e.g., a labels file that includes future returns alongside features)

## 6. Survivorship bias controls

Historical backtests must include assets that existed at the historical time point but have since been delisted, hacked, or otherwise removed.

**Required:**
- Universe construction at time T uses the asset list active at time T, not the current asset list
- Delisted assets are tracked with delisting date and reason
- Failed/hacked tokens are included in historical training (their failures are part of the realistic distribution)

**Forbidden:**
- "Top 50 altcoins by current market cap" applied retroactively to historical periods
- Excluding "noisy" or "outlier" assets without documented rationale
- Cherry-picking universe windows that conveniently exclude bad performers

## 7. Time-zone discipline

All timestamps in SuperHydra are stored as UTC. Display layers may convert for human readability; storage and computation never use local time.

**Forbidden:**
- Local time in any database column
- Mixed-timezone joins (a known failure pattern in quant systems)
- Daylight-saving-aware computations in continuous data (crypto markets are 24/7, no DST)

Venue clock alignment is verified at ingestion: if a venue's reported timestamp differs from system UTC by more than 5 seconds, the source is flagged for clock-drift investigation.

## 8. Symbol normalization

Different vendors use different symbols for the same asset (BTC, BTCUSDT, BTC-USDT, BTCUSD, XBT, XBTUSD). SuperHydra uses a canonical symbol registry.

**Required:**
- Every traded asset has a canonical symbol (e.g., `BTCUSDT-PERP-BINANCE` for Binance perpetual)
- Vendor-specific symbols map to canonical symbols in a registered translation table
- Translation table changes are version-controlled
- Cross-vendor data joins use canonical symbols

**Forbidden:**
- Hard-coded vendor-specific symbols in strategy code
- Implicit symbol mapping (e.g., assuming "BTC" means the same thing across vendors)

## 9. Data retention

| Data class | Retention period | Storage |
|---|---|---|
| Raw vendor data | Indefinite | S3/MinIO with versioning |
| Processed datasets | Indefinite while strategy is active; 2 years after sunset | S3/MinIO |
| Model training artifacts | Indefinite while model is in any production environment | S3/MinIO |
| Order book snapshots | 7 days hot (Redis), 30 days warm (Postgres), indefinite cold (S3) | Tiered |
| Logs (system, strategy, risk) | 90 days hot, 1 year cold | Loki/S3 |
| Database backups (ledger, registry) | Daily for 30 days, weekly for 1 year, monthly indefinite | S3 |

Data is not deleted before its retention boundary except for vendor compliance requirements.

## 10. Data provenance and audit

Every dataset used in any decision (model training, gate evaluation, live signal) has provenance metadata:
- Vendor source(s)
- Ingestion timestamp
- Processing script version
- Processed-at timestamp
- Verification status per measurement_policy.md section 4

A dataset without provenance is forbidden in production. The provenance table is queryable: any historical decision can be traced back to the exact data version that produced it.

## 11. Quarterly data review

Alongside measurement, risk, and model reviews, a data review runs quarterly. It:
- Audits vendor SLAs against realized freshness over the quarter
- Reviews data quality check log for patterns of degradation
- Re-verifies sources tagged `VERIFIED` per measurement_policy.md
- Evaluates whether data spending matches data utility (cost vs benefit per vendor)
- Updates this policy if vendor or SLA changes are warranted

**Sign-off:** Operator (Wasseem Katt). Both signatures required if/when a second operator joins.

**First quarterly review scheduled:** 2026-08-02

## Revision log

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-05-02 | Wasseem Katt | Initial policy with vendor registry, freshness SLAs, immutability rules |
