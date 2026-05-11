# SuperHydra Live Status Memo

This memo refreshes weekly per roadmap section 11. The roadmap holds principles and gates; this memo holds the snapshot.

---

## Current state - 2026-05-11 (sixth update, Day 19 outer arc closure)

### Migration foundation
- 0009 (risk evaluation) - Round 4 closed. Commit 0f8b7b5. Full integration suite 355/355 in ~5:15 stable through Day 19c additions.

### Sleeve A (build-to-trade)
- Engine A1 - Funding-rate capture: Phase P0 (late P0).
  - Days 1-12.5: pipeline + smoke test + writers.
  - Days 14a-c: funding journal writer + funding_payment INSERT + smoke test extension.
  - Days 15a-c: A1PaperRunner + OMS submit helper + dispatch_due_funding_events.
  - Day 16a (0b0f431): synthetic 30-interval backfill harness against real Postgres in 1.32s.
  - Day 16c (d4b6a75): Sharpe computation analytics module.
  - Day 16b (9a6be81): real-data no-trade regime test (Apr-May 2026 fixture, placeholder costs).
  - Day 16d.1/16d.2 (37018b9, a182090): test ordering hygiene + snapshot-source disambiguation.
  - Day 16b.2 probe (27bf80d): Dec 2024 BTCUSDT fixture committed.
  - Day 16e (9ba2be0): structural cost-threshold invariant tests.
  - Day 17a (52c9604): calibrated cost-profile foundation.
  - Day 17b (0221efa): A1 cost-profile selector module.
  - Day 17c PIVOT (5b8a7c3): BTCUSDT structurally untradeable across all profiles.
  - Day 18a (e3e0c89): calibrated altcoin profile binance_vip5_alt_v1 + SOLUSDT selector branch.
  - Day 18b (673bc7c): SOL March 2024 fixture committed; integration test asserting no-trade under VIP5+alt because rolling-12 forecast is below threshold despite genuinely strong realized funding.
  - Day 19a (6b423d7): binance_vip5_alt_research_v1 with explicit research-only firewall. Threshold matches BTC at ~7.7 bps. Evidence basis: Kaiko Q1 2024 + Amberdata Jan 2026.
  - Day 19b.1 (63df547): Binance aggTrades fetcher - BinanceTrade dataclass + BinanceTradeFetcher mirroring funding_fetcher.py conventions.
  - Day 19b.2 (b386ac4): Roll effective-spread estimator (Roll 1984) with Decimal arithmetic, returning explicit None for undefined estimates rather than zero.
  - Day 19b.3 (5f8b644): Roll-spread estimation harness + research-only memo + .gitignore for ephemeral artifacts.
  - Day 19b closing (78633b6): aggTrades REST TTL finding documented in memo and warning added to harness.
  - Day 19c.1+19c.2 (4c9a2bf): Binance Vision archive trade fetcher (BinanceArchiveTradeFetcher) + 22 unit tests. Streaming zip decompression, multi-month support, repo-relative cache, header sniffing, sort+dedupe by (time, id).
  - Day 19c.3 (fd7e523): harness gains --source flag (rest|archive, default rest). Both fetchers share the fetch_window API.
  - Day 19c.3 results (65bb5f1): first numeric Roll-tape estimates against predefined regimes + harness limit/max_pages bug fix.
  - Cumulative: 314 strategy unit + 39 integration + 22 archive-fetcher unit + 18 effective-spread unit tests. Full integration suite 355/355 in ~5:15.

### Day 19 outer arc closed

The Day 19 arc was scoped to produce a second independent research-calibrated estimate of SOLUSDT effective spread, comparable to Day 19a's 1 bp/leg Kaiko+Amberdata calibration. Execution required closing two gaps:

| Gap | Resolution |
| --- | --- |
| Public REST aggTrades does not serve deep history (TTL discovered in Day 19b closing) | Day 19c archive ingestion from data.binance.vision |
| Roll estimator does not exist in codebase | Day 19b.2 with Decimal arithmetic, explicit None for undefined estimates |

The full pipeline (fetcher → estimator → harness → archive backend) is operational end-to-end. The Roll-estimator pipeline is the second independent path to research-grade slippage calibration.

### Three independent research-calibrated estimates of SOL slippage now on record

| Source | Per-leg estimate | Status |
| --- | --- | --- |
| Day 18a placeholder | 3 bps | Conservative governance profile (binance_vip5_alt_v1, active in selector) |
| Day 19a Kaiko + Amberdata | 1 bp | Research-only profile (binance_vip5_alt_research_v1, firewalled from selector) |
| Day 19c.3 Roll-tape (median) | 0.146 bps (quiet Jan 2025) / 0.192 bps (volatile Mar 2024) | Research artifact, no profile created |

All three agree the cost is small. The most pessimistic (governance placeholder) is roughly 20x the most empirical (tape median). Day 19a's 1 bp research calibration sits comfortably between them and is now corroborated as conservative by tape evidence. None of this changes the active cost profile A1 uses; promotion is gated elsewhere (see Day 20 reviewer question below).

### Day 19c.3 numeric Roll-tape results

Quiet regime (Jan 2025, 5x5min windows): all 5 windows valid. Full-spread median 0.292 bps, range 0.134-0.480 bps. Per-leg half-spread median 0.146 bps.

Volatile regime (Mar 2024, 5x5min windows): 2 of 5 windows valid; 3 of 5 returned undefined non_negative_autocovariance because directional flow dominates - itself a documented limitation of Roll's estimator and a methodological argument for moving to side-aware estimators (Lee-Ready, Glosten-Harris) in future research extension work. The two valid estimates 0.349 and 0.417 bps full are tightly clustered (median 0.383 bps full = 0.192 bps half) but a sample of 2 is not statistical evidence.

Combined: 7 valid Roll estimates across both regimes. Both regimes fall in the memo's "0.5-2 bps full spread → corroborates Day 19a" interpretation band - in fact tighter than expected.

### Three structural no-trade binds documented as tested invariants (unchanged)

A1 has three distinct no-trade regimes, each documented with both unit-level structural tests and integration tests against real-data fixtures:

| Bind | Fixture | Cause |
| --- | --- | --- |
| No-edge regime | BTC Apr-May 2026 (placeholder cost) | Mean realized rate near zero |
| Cap-bound | BTC Dec 2024 (VIP5) | Even cap-pinned funding < threshold |
| Slippage-bound | SOL Mar 2024 (VIP5+alt) | Rolling-12 forecast < threshold despite mean realized 6 bps |

### Day 19a research-calibrated profile firewall (unchanged)

The TestResearchProfileFirewall class in test_profile_selector.py asserts that no input to select_profile_for_a1 returns binance_vip5_alt_research_v1. The profile remains research-only despite triple corroboration by Day 19c.3 tape evidence. Promotion to binance_vip5_alt_empirical_v1 requires live A1 paper fills (Day 20+).

### Archive backend characteristics (recorded for future reference)

- Source: data.binance.vision monthly aggTrades zip archives.
- Cache: artifacts/cache/binance_archive/{SYMBOL}-aggTrades-{YYYY}-{MM}.zip. Gitignored via the artifacts/ rule. Filename layout preserved so future .CHECKSUM verification (deferred per Day 19c reviewer Q2 amendment) can land without API or filename changes.
- Memory: streaming decompression via zipfile.ZipFile.open + io.TextIOWrapper + csv.reader. Window-filter rows in flight. Full monthly archives (50M+ trades possible) never materialized in memory.
- Raw trade data remains ephemeral by design. The harness is committed; per-run outputs and downloaded archives are not.
- Archive backend is now the primary path for any historical microstructure work past the REST TTL boundary.

### Why no promotion-grade calibration exists yet despite triple corroboration

Three reasons the research profile remains research-only:

1. Sample size. 7 valid Roll estimates across both regimes is research-grade evidence, not governance-grade calibration.
2. Roll captures market-wide spread, not A1-clip-size impact. Venue-specific market impact and cancellation behavior under A1's actual order sizes are absent from tape estimates.
3. Live-fill gate. The reviewer-locked promotion path requires live A1 paper fills with adverse-fill cost recorded per fill (Day 20+). Roll estimates corroborate but do not substitute.

### Day 20 reviewer question (next session opening)

Framing locked per reviewer:

**What is the minimum infrastructure required to turn paper fills into empirically calibrated execution-cost evidence?**

The transition this question gates:

```
research-only estimates  →  empirical paper-fill recording  →  governance-grade calibration
```

Subordinate questions that fall out:

1. Where does A1 record fills in paper mode? The current submit_callback is production-shaped; paper mode needs its own fill writer that records intended_price, fill_price, slippage_bps, venue_response_ms, ts per fill without flowing into trading.fills (which is for real fills only).
2. Which cost profile does A1 use during paper recording? The research profile (1 bp/leg) is firewalled from the selector; the governance profile (3 bps/leg) is conservative enough that A1 won't fire orders under most market conditions. Three options on the table: (a) reviewer-locked paper-only exception allowing research profile, (b) build an empirical-only profile from Day 19c.3 tape data with the same self-firewall pattern, (c) leave A1 idle until conditions change naturally; let the recording infrastructure sit ready.
3. What is the aggregation function that produces a candidate empirical profile from recorded fills? Mean realized slippage per leg? Median? Sensitivity-tested across alpha quantiles?
4. What is the promotion criterion? Day 19a memo's sensitivity band was 0.5-1.5 bps/leg; does that still hold given Day 19c.3 evidence is tighter?

### Sleeve A2/A3
- A2 (basis): not started.
- A3 (cash-and-carry): deferred.

### Sleeve B
- Phase P0. No work this week.

### Build blockers
- None blocking forward progress.

### Data integrity issues
- None.

### Paper-vs-live drift
- N/A. No live deployment.

### Unresolved risk exceptions
- None.

### Test-suite stability
- Day 19c additions did not regress the integration suite. 355/355 stable across Day 19a, Day 19b.1, Day 19b.2, and Day 19c.1+19c.2 runs. Two-day gap before Day 20 opening also confirmed clean (355/355 in 5:18, May 11).
- Single-incident flake in test_migrations.py recorded at Day 18 not seen again. Treated as resolved unless recurring.

### Next gate status
- A1 P0 to P1 gate: paper run reproducible end-to-end on production code path with paper Sharpe >= 2.0 over a >= 60-day window.
- Reproducibility: proven (synthetic + 3 real-data fixtures, all byte-stable).
- No-trade findings: 3 distinct structural binds documented as tested invariants.
- Three independent calibrations of execution cost: all agreeing the cost is small.
- Sharpe number from yes-trade window: blocked on Day 20+ paper-fill recording infrastructure + live paper running until conditions produce trades A1 can fire on.

### Capital deployed
- $0. Program in P0 across all engines.

### Carry-forward debt (unchanged unless noted)
- 0009 Round 4.5 Replay/Risk Matrix Hardening (non-blocking, post-signoff).
- Untracked design docs (0009_R11_feedback.md.rtf, 0009_v1_10_handoff.md, 0009_v1_11_design.md): persistent untracked state since session start. Decision deferred (gitignore vs commit vs delete).
- Side-aware Lee-Ready / Glosten-Harris estimators: queued as research extension, motivated by Day 19c.3 Finding 1 (3 of 5 volatile windows undefined under Roll).
- .CHECKSUM verification on archive fetcher: deferred per Day 19c reviewer Q2 amendment. Cache filename layout preserves room for it.
- Maker-rebate-only research profile: orthogonal track, low priority.

### Sub-arcs complete vs open

| Arc | Status |
| --- | --- |
| 0009 Round 4 (risk evaluation migration) | Closed |
| Day 16: synthetic backfill + Sharpe analytics + first real fixture | Closed |
| Day 17: cost-profile foundation + BTC pivot | Closed |
| Day 18: SOL profile + SOL fixture | Closed |
| Day 19a: research-calibrated alt profile + selector firewall | Closed |
| Day 19b: REST infrastructure + Roll estimator + harness + TTL finding | Closed |
| Day 19c: archive ingestion + harness wiring + first numeric estimates | Closed |
| **Day 20**: paper-fill recording infrastructure (reviewer question first) | **Open** |
| A1 P0 to P1 (60-day paper proof, Sharpe >= 2.0) | Open (gated on Day 20) |
| A2 (basis) | Not started; gated on A1 P3 |
| A3 (cash-and-carry) | Deferred |
| Sleeve B research | Not started |
