# Data Policy

**Version:** 1.1
**Effective:** 2026-05-02 (revised from v1.0 same date)
**Author:** Wasseem Katt
**Source:** SuperHydra Enhanced Plan; HYDRA postmortem 2026-05-01; vendor decisions logged in docs/decisions/; v1.1 incorporates external review 2026-05-02
**Supersedes:** v1.0 (same date)

This policy defines what data is permitted in SuperHydra, where it comes from, how fresh it must be, and how its integrity is guaranteed. The data layer is the foundation under measurement, risk, model, and allocator policies. Bad data invalidates everything downstream.

## Why v1.1

v1.0 vendor registry covered Phase 1 only. v1.1 separates "Phase 1 active vendors" from "future-engine vendor categories not yet procured" -- the future categories are documented so they aren't forgotten when later engines scope, but no procurement commitment exists for them. v1.1 also adds metric-specific tolerances for cross-source disagreement (1% is too loose for some metrics, too strict for others), and adds the policy hierarchy.

## 1. Vendor registry -- Phase 1 active vendors

Every data source actively used in SuperHydra must be registered here. Sources not registered are forbidden in production code paths.

| Vendor | Data type | Tier (current) | Phase 1 use | Status |
|---|---|---|---|---|
| Binance API | OHLCV, trades, account state | Free | Yes -- primary execution venue | Active |
| CCXT (library) | Multi-exchange OHLCV abstraction | Free (open-source) | Yes -- research convenience layer | Active |
| Tardis.dev | L2 order book + trades historical and live | Academic ($650/mo, pending) | Yes -- required for Shadow admission per deployment_gates v1.1 | Pending signup, then VERIFICATION required before any Shadow promotion |
| Glassnode | On-chain metrics, exchange flows | Free tier | Phase 2 evaluation only; upgrade to Advanced when Phase 2 features built | Active free tier |
| Polygon RPC | On-chain reads (legacy HYDRA wallet) | Free public RPC | Decommissioning with HYDRA freeze May 15 | Sunsetting |

**Forbidden:**
- Free public APIs without rate-limit guarantees in production code (acceptable for one-off research; not for live signal generation)
- Scraping any source not on this registry
- Using a source for live signals before it is tagged `VERIFIED` per measurement_policy.md

Vendor changes (additions, removals, tier changes) require this policy doc to be updated and re-committed.

## 2. Future-engine vendor categories -- not yet procured (v1.1 addition)

The following categories are required for engines scheduled in Phase 7+ of the SuperHydra plan (post-canary of L/S engine). They are documented here so they're not forgotten when scoping begins, but no procurement, signup, or budget commitment exists. Specific vendors are selected and added to the active registry (section 1) at the time the corresponding engine enters scoping.

| Category | Required for engine | Candidate vendors | Notes |
|---|---|---|---|
| Options data (BTC/ETH IV, Greeks, surfaces) | Options vol overlay (Phase 7+) | Deribit API (free real-time), Genesis Volatility, Amberdata, Laevitas | Deribit alone may suffice for Phase 7 single-venue work |
| Tokenomics / unlocks | Tokenomics overlay or L/S enhancement | Tokenomist, TokenUnlocks, Token Terminal, project APIs | Free tier of Tokenomist may suffice initially |
| ETF / fund flows | Long-flat product, regime overlay | CoinShares (weekly free), issuer disclosures, Farside-style aggregators | Public sources sufficient for weekly-resolution work |
| News / events | Sentiment classifier (Class F per model_policy v1.1) | Santiment, The TIE, official exchange/project feeds, regulator RSS | Composite feed required; no single vendor sufficient |
| Macro calendar | Regime overlay enhancement | FRED, Trading Economics, economic calendar APIs | Free sources adequate for weekly/daily resolution |
| DeFi rates and protocol state | EBTC vault scoping (Phase 7+) | Aave subgraph, Compound subgraph, Morpho, DeFiLlama | Open data; integration cost is engineering, not subscription |
| Multi-venue perp / futures | Cross-venue carry (Phase 7+) | Tardis multi-venue tier, Kaiko, Coinmetrics | Tardis upgrade likely sufficient; full Kaiko expensive |

**Procurement trigger:** A category transitions from "future" to "active" only when:
1. The engine that requires it has entered Research stage per deployment_gates.md
2. A specific vendor in the category has been selected with documented rationale
3. Budget approved by operator
4. Vendor onboarding complete and source tagged `UNVERIFIED` initially
5. Verification per measurement_policy.md before the source is consumed by any production code

## 3. Freshness SLAs

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
- Outage > 4 hours triggers a re-verification requirement when source recovers

## 4. Immutability and reproducibility

**Raw data is immutable:**
- Raw data ingested from any vendor is written to S3/MinIO storage with timestamp and vendor identifier
- Raw data files are never modified after write
- Corrections from vendor are written as new records, not edits to existing records
- Storage uses versioned bucket configuration to prevent accidental overwrite

**Processed data is reproducible:**
- Any processed dataset must be reproducible from raw data using committed scripts
- Processing scripts are versioned in git
- Datasets used in model training are tagged with: source raw data version, processing script version, processing timestamp
- A processed dataset that cannot be reproduced from registered sources is invalid

**Forbidden:**
- Hand-edited data files in production paths
- Datasets with unknown provenance
- "Cleaned" data without a script that produces it from raw

## 5. Data quality checks

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
| Cross-source disagreement | Same metric from two sources differs (metric-specific tolerance, see below) | Flag per tolerance |

**Cross-source disagreement tolerances (v1.1, metric-specific):**

| Metric | Tolerance | Rationale |
|---|---|---|
| Account balances (cash, position quantity) | 0% | Hard fail on any disagreement; reconciliation break |
| Spot price (mid) | 0.1% | Tight; cross-vendor mid quotes should agree closely |
| Volume (1-minute) | 5% | Vendors aggregate trades differently; some lag |
| Volume (daily) | 2% | Daily totals should converge across vendors |
| Funding rate | 0% | Single source of truth (the venue itself) |
| Order book depth at price level | 10% | Snapshot timing differences acceptable |
| On-chain metrics (SOPR, exchange flows) | 5% | Different oracle methodologies |
| Sentiment scores | N/A | Vendor-specific scales; no cross-vendor check |

Quality check results are logged to `data_quality_log` continuously. Quarterly review covers patterns of degradation by source.

## 6. Lookahead bias controls

The single largest backtest failure mode in quant work. Controls:

**Required at every level:**
- Every dataset has an as-of timestamp; queries must respect "data available at time T"
- Feature computation never uses data later than the prediction time
- Walk-forward training has explicit embargo period (per model_policy.md)
- Validation harness includes a "shuffle future" lookahead-bias test

**Forbidden:**
- Computing features over the entire dataset before splitting (creates leakage)
- Using survivor-only universe in historical training
- Importing future data through any "convenience" path

## 7. Survivorship bias controls

Historical backtests must include assets that existed at the historical time point but have since been delisted, hacked, or otherwise removed.

**Required:**
- Universe construction at time T uses the asset list active at time T, not the current asset list
- Delisted assets are tracked with delisting date and reason
- Failed/hacked tokens are included in historical training (their failures are part of the realistic distribution)

**Forbidden:**
- "Top 50 altcoins by current market cap" applied retroactively to historical periods
- Excluding "noisy" or "outlier" assets without documented rationale
- Cherry-picking universe windows that conveniently exclude bad performers

## 8. Time-zone discipline

All timestamps in SuperHydra are stored as UTC. Display layers may convert for human readability; storage and computation never use local time.

**Forbidden:**
- Local time in any database column
- Mixed-timezone joins
- Daylight-saving-aware computations in continuous data (crypto markets are 24/7, no DST)

Venue clock alignment is verified at ingestion: if a venue's reported timestamp differs from system UTC by more than 5 seconds, the source is flagged for clock-drift investigation.

## 9. Symbol normalization

Different vendors use different symbols for the same asset (BTC, BTCUSDT, BTC-USDT, BTCUSD, XBT, XBTUSD). SuperHydra uses a canonical symbol registry per the registry.assets and registry.instruments schema in ledger v0.2.

**Required:**
- Every traded asset has a canonical symbol (e.g., `BTCUSDT-PERP-BINANCE` for Binance perpetual)
- Vendor-specific symbols map to canonical symbols in a registered translation table
- Translation table changes are version-controlled
- Cross-vendor data joins use canonical symbols

**Forbidden:**
- Hard-coded vendor-specific symbols in strategy code
- Implicit symbol mapping

## 10. Data retention

| Data class | Retention period | Storage |
|---|---|---|
| Raw vendor data | Indefinite | S3/MinIO with versioning |
| Processed datasets | Indefinite while strategy is active; 2 years after sunset | S3/MinIO |
| Model training artifacts | Indefinite while model is in any production environment | S3/MinIO |
| Order book snapshots | 7 days hot (Redis), 30 days warm (Postgres), indefinite cold (S3) | Tiered |
| Logs (system, strategy, risk) | 90 days hot, 1 year cold | Loki/S3 |
| Database backups (ledger, registry) | Daily for 30 days, weekly for 1 year, monthly indefinite | S3 |

Data is not deleted before its retention boundary except for vendor compliance requirements.

## 11. Data provenance and audit

Every dataset used in any decision has provenance metadata:
- Vendor source(s)
- Ingestion timestamp
- Processing script version
- Processed-at timestamp
- Verification status per measurement_policy.md

A dataset without provenance is forbidden in production. The provenance table is queryable: any historical decision can be traced back to the exact data version that produced it.

## 12. Quarterly data review

A data review runs quarterly. It:
- Audits vendor SLAs against realized freshness over the quarter
- Reviews data quality check log for patterns of degradation
- Re-verifies sources tagged `VERIFIED` per measurement_policy.md
- Evaluates whether data spending matches data utility (cost vs benefit per vendor)
- Reviews future-engine vendor categories: any approaching procurement trigger?
- Updates this policy if vendor or SLA changes are warranted

**Sign-off:** Operator (Wasseem Katt). Both signatures required if/when a second operator joins.

**First quarterly review scheduled:** 2026-08-02

## 13. Policy hierarchy

This policy is part of the SuperHydra Policy Pack. When policies conflict:

1. Safety/compliance/venue permission requirements
2. Risk policy
3. Measurement policy
4. Deployment gates policy
5. Data policy (this document)
6. Model policy
7. Allocator policy
8. Incident severity policy

The stricter safety/risk interpretation applies until policies are amended and re-signed.

## Revision log

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-05-02 | Wasseem Katt | Initial policy with vendor registry, freshness SLAs, immutability rules |
| 1.1 | 2026-05-02 | Wasseem Katt + external reviewer | Separated Phase 1 active vendors from future-engine vendor categories not yet procured. Added procurement trigger conditions for category-to-active transition. Added metric-specific cross-source disagreement tolerances. Added Tardis-VERIFIED prerequisite reference (enforced in deployment_gates v1.1). Added policy hierarchy. |
