# SuperHydra Live Status Memo

This memo refreshes weekly per roadmap section 11. The roadmap holds principles and gates; this memo holds the snapshot.

---

## Current state - 2026-05-09 (fifth update, end of Day 19b infrastructure arc)

### Migration foundation
- 0009 (risk evaluation) - Round 4 closed. Commit 0f8b7b5. Full integration suite 355/355 in 5:14 after Day 19a; full suite stable through Day 19b infrastructure additions.

### Sleeve A (build-to-trade)
- Engine A1 - Funding-rate capture: Phase P0.
  - Days 1-12.5: pipeline + smoke test + writers.
  - Days 14a-c: funding journal writer + funding_payment INSERT + smoke test extension.
  - Days 15a-c: A1PaperRunner + OMS submit helper + dispatch_due_funding_events.
  - Day 16a (0b0f431): synthetic 30-interval backfill harness against real Postgres in 1.32s.
  - Day 16c (d4b6a75): Sharpe computation analytics module.
  - Day 16b (9a6be81): real-data no-trade regime test (Apr-May 2026 fixture, placeholder costs).
  - Day 16d.1 / 16d.2 (37018b9, a182090): test ordering hygiene + snapshot-source disambiguation.
  - Day 16b.2 probe (27bf80d): Dec 2024 BTCUSDT fixture committed.
  - Day 16e (9ba2be0): structural cost-threshold invariant tests.
  - Day 17a (52c9604): calibrated cost-profile foundation.
  - Day 17b (0221efa): A1 cost-profile selector module.
  - Day 17c PIVOT (5b8a7c3): BTCUSDT structurally untradeable across all profiles.
  - Day 18a (e3e0c89): calibrated altcoin profile binance_vip5_alt_v1 + SOLUSDT selector branch.
  - Day 18b (673bc7c): SOL March 2024 fixture committed; integration test asserting no-trade under VIP5+alt because rolling-12 forecast is below threshold despite genuinely strong realized funding.
  - Day 19a (6b423d7): binance_vip5_alt_research_v1 with explicit research-only firewall. Threshold matches BTC at ~7.7 bps. Evidence basis: Kaiko Q1 2024 + Amberdata Jan 2026.
  - Day 19b.1 (63df547): Binance aggTrades fetcher — BinanceTrade dataclass + BinanceTradeFetcher mirroring funding_fetcher.py conventions.
  - Day 19b.2 (b386ac4): Roll effective-spread estimator (Roll 1984) with Decimal arithmetic, returning explicit None for undefined estimates rather than zero.
  - Day 19b.3 (5f8b644): Roll-spread estimation harness + research-only memo + .gitignore for ephemeral artifacts.
  - Cumulative: 314 unit + 39 integration tests across the strategy and analytics. Full integration suite 355/355 in ~5:15.

### Day 19b infrastructure arc complete

The reviewer-locked path was: tape-based effective-spread estimation as a second independent research-calibrated estimate, with explicit research-only labeling. Three sub-tasks executed cleanly:

| Sub-task | Deliverable | Status |
|---|---|---|
| 19b.1 | Trade-history fetcher mirroring funding_fetcher conventions | ✓ |
| 19b.2 | Roll's autocovariance estimator with Decimal end-to-end | ✓ |
| 19b.3 | CLI harness + research memo + .gitignore for ephemeral artifacts | ✓ |

Discipline preserved: raw trade data is ephemeral by design (the harness is what is committed, not its outputs); the memo includes explicit interpretation guide and promotion path; no cost profile is promoted from Roll estimates alone.

### Three independent research-calibrated estimates now in place for SOL slippage

| Source | Estimate | Status |
|---|---|---|
| Day 18a placeholder | 3 bps per leg | Conservative governance profile (binance_vip5_alt_v1) |
| Day 19a Kaiko + Amberdata | 1 bp per leg | Research-only profile (binance_vip5_alt_research_v1), firewalled from selector |
| Day 19b.1-3 Roll on aggTrades | TBD - harness ready, not yet executed | Research-only by design; no profile created |

Day 19b's harness produces a second independent estimate that can be compared to Day 19a's number. Convergence across two methodologies (third-party aggregated + tape-based) would meaningfully strengthen the research profile's defensibility — but still not promote it, because both are research artifacts and the promotion gate remains live A1 fills.

### Three structural binds documented as tested invariants (unchanged)

A1 has demonstrated three distinct no-trade regimes, each documented with both unit-level structural tests and integration tests against real-data fixtures: no-edge regime (Day 16b), cap-bound (Day 17c), slippage-bound (Day 18b). Detail in prior memo update.

### Day 19a research-calibrated profile firewall (unchanged)

The TestResearchProfileFirewall class in test_profile_selector.py asserts that no input to select_profile_for_a1 returns binance_vip5_alt_research_v1. Detail in prior memo update.

### Next deliverables, in order

1. **Run the Day 19b.3 harness under controlled conditions** to produce numeric Roll estimates for SOLUSDT in quiet (Jan 2025) and volatile (Mar 2024) regimes. Approximately 10 throttled HTTP calls per regime, 5-10 minutes wall time per regime.
2. **Append numeric results to docs/research/sol_roll_spread_estimation_memo.md.** Compare against Day 19a's 1 bp per leg; classify per the memo's interpretation guide (corroborates / partial / re-pivot).
3. **Decide whether the estimates support adding a second research-only alt profile** with the Roll-derived calibration, or whether the current research profile (1 bp from third-party data) is sufficient research-only artifact.
4. **Day 20+: Live A1 paper-fill recording infrastructure.** This is the actual promotion-unblocking work. Deferred until Day 19b interpretation lands or in parallel as orthogonal track.

Alternative orthogonal: maker-rebate-only research profile. Same firewall pattern; not promoted; could be added in parallel.

### Sleeve A2/A3
- A2 - Basis: Not started.
- A3 - Cash-and-carry: Deferred.

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

### Test-suite flake observed earlier today
- Single-incident flake in test_migrations.py logged in prior memo update; not seen again across subsequent runs (Day 19a, Day 19b.1, Day 19b.2 each ran the full integration suite cleanly). Treated as resolved unless recurring.

### Next gate status
- A1 P0 to P1 gate: paper run reproducible end-to-end on production code path with paper Sharpe >= 2.0 over a meaningful window.
- Reproducibility: proven (synthetic + 3 real-data fixtures, all byte-stable).
- Three safety-property findings proven across different cost profiles + real fixtures.
- Sharpe number from yes-trade real-data window: blocked on Day 20+ live-fill calibration. Day 19b infrastructure is one step closer (second independent research estimate available); the gate itself still requires venue-validated execution costs, not research artifacts.

### Carry-forward debt
0009 Round 4.5 - Replay/Risk Matrix Hardening (non-blocking, post-signoff).

Day 19b harness execution prerequisites:
1. Run harness once under controlled conditions (network connection, ~15 minutes wall time, output paths set up).
2. Decide on numeric result interpretation per memo's guide.
3. Update memo with results section.

Day 20 prerequisites (deferred):
1. Live A1 paper-fill recording infrastructure (currently no fill writer for paper-mode separate from production submit_callback).
2. Paper-fill cost-instrumentation: per-fill record of intended price, fill price, slippage in bps.
3. Aggregation across fills to produce empirical-calibration estimate.

### Capital deployed
- $0. Program in P0 across all engines.
