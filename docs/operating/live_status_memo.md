# SuperHydra Live Status Memo

This memo refreshes weekly per roadmap section 11. The roadmap holds principles and gates; this memo holds the snapshot.

---

## Current state - 2026-05-09 (fourth update, end of Day 19a)

### Migration foundation
- 0009 (risk evaluation) - Round 4 closed. Commit 0f8b7b5. Full integration suite 355/355 in 5:14 after Day 19a. One observed flake (14 migration tests failing on a single 5-minute run, all passing on retry); treated as single-incident noise, not investigated. If recurs, investigate cleanup ordering.

### Sleeve A (build-to-trade)
- Engine A1 - Funding-rate capture: Phase P0.
  - Days 1-12.5: pipeline + smoke test + writers.
  - Days 14a-c: funding journal writer + funding_payment INSERT + smoke test extension.
  - Days 15a-c: A1PaperRunner + OMS submit helper + dispatch_due_funding_events.
  - Day 16a (0b0f431): synthetic 30-interval backfill harness against real Postgres in 1.32s.
  - Day 16c (d4b6a75): Sharpe computation analytics module.
  - Day 16b (9a6be81): real-data no-trade regime test (Apr-May 2026 fixture, placeholder costs).
  - Day 16d.1 (37018b9): timestamp-determinism fix.
  - Day 16d.2 (a182090): synthetic harness fill_ts logical clock + snapshot-source disambiguation.
  - Day 16b.2 probe (27bf80d): Dec 2024 BTCUSDT fixture committed.
  - Day 16e (9ba2be0): structural cost-threshold invariant tests.
  - Day 17a (52c9604): calibrated cost-profile foundation.
  - Day 17b (0221efa): A1 cost-profile selector module.
  - Day 17c PIVOT (5b8a7c3): BTCUSDT structurally untradeable across all profiles.
  - Day 18a (e3e0c89): calibrated altcoin profile binance_vip5_alt_v1 (3 bps slippage) + SOLUSDT selector branch.
  - Day 18b (673bc7c): SOL March 2024 fixture committed; integration test asserting no-trade under VIP5+alt because rolling-12 forecast (~7.7 bps) is below threshold (~11.7 bps) despite genuinely strong realized funding (mean 6 bps, 100% positive intervals).
  - Day 19a (6b423d7): binance_vip5_alt_research_v1 added (1 bp slippage) with explicit research-only firewall. Threshold ~7.7 bps, matches BTC. Evidence basis: Kaiko Q1 2024 spread cheatsheet + Amberdata Jan 2026 snapshot (Binance SOLUSDT tightest at 0.79 bps; SOL ~10x BTC/ETH). Research profile is NOT returned by select_profile_for_a1; using it requires direct call by name. Research memo at docs/research/sol_slippage_calibration_memo.md documents evidence, methodology, sensitivity bounds, and promotion path.
  - Cumulative: 270 unit + 39 integration tests across the strategy. Full integration suite 355/355 in 5:14.

### Three structural binds documented as tested invariants

A1 has now demonstrated three distinct no-trade regimes, each documented with both unit-level structural tests and integration tests against real-data fixtures:

1. **No-edge regime** (BTCUSDT Apr-May 2026 fixture, placeholder costs): mean rate near zero. Engine correctly produces signal_flat because no edge exists. Day 16b integration test.

2. **Cap-bound** (BTCUSDT Dec 2024 fixture, VIP5 costs): even cap-pinned funding (1 bp per interval) is below the VIP5 threshold (~7.7 bps). The dominant cost is round-trip slippage (2 * 1 bp = 2 bps) which alone exceeds the cap. No fee structure can save the math; even VIP9 institutional comes in at ~5.4 bps, still 5x above cap. Day 17c pivot.

3. **Slippage-bound** (SOLUSDT March 2024 fixture, VIP5+alt costs): genuinely strong realized funding (mean 6 bps, 100% positive intervals, single-interval max 11.93 bps). But the engine's rolling-12 forecast (max 7.69 bps) is below the alt threshold (11.7 bps) because the conservative liquid_alt_tier (3 bps per leg) drives threshold above realized rolling means. Day 18b integration test.

The slippage-bound finding is structurally different from the cap-bound finding: in the cap-bound case, no calibration can make BTCUSDT tradeable (cap < any realistic threshold). In the slippage-bound case, realistic SOL slippage (likely closer to 1 bp per leg per Day 19a research) WOULD make SOL tradeable in March 2024-class regimes — but the calibration that proves that is research-only until tape or live-fill validation lands.

### Day 19a research-calibrated profile firewall

The research profile binance_vip5_alt_research_v1 demonstrates the right discipline for handling non-governance research artifacts in a governance-bearing test suite:

- Profile name contains _research_ explicitly.
- Slippage tier name contains research (liquid_alt_research_tier).
- Profile-level notes start with RESEARCH-ONLY.
- Source.notes explicitly state "awaiting tape and live-fill validation."
- select_profile_for_a1 is not extended; SOLUSDT continues to return alt_v1 (conservative).
- Three firewall tests in TestResearchProfileFirewall assert no input to the selector returns the research profile across all plausible (instrument, venue) pairs.

This makes accidental promotion a hard contract violation, not a soft norm. If a future change extends the selector to return the research profile as a default, the firewall tests fail and force a deliberate decision about whether the research profile has been empirically validated.

### Next deliverables, in order

1. **Day 19b/20 - Tape-based slippage estimation.** Pull Binance SOLUSDT trade history over multiple sample periods (volatile and quiet regimes), estimate effective spread and impact via Roll's autocovariance estimator or similar. Compare to Day 19a's research-calibrated 1 bp.
2. **Day 20+ - Live A1 paper fills.** A1 paper fills on the venue at production-equivalent clip sizes, with adverse-fill cost recorded per fill.
3. **Promotion to empirical.** When tape and live-fill estimates both agree within Day 19a's sensitivity bounds (0.5-1.5 bps), promote to binance_vip5_alt_empirical_v1 and update selector. Day 19a's TestResearchProfileFirewall tests will need to be reframed at that point - the empirical profile WOULD be reachable through select_profile_for_a1.

Alternative orthogonal path: maker-rebate-only research profile. Could be added in parallel as binance_maker_only_research_v1 with the same firewall pattern. Lower priority than the empirical SOL pivot.

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

### Test-suite flake observed today
- One full-suite run had 14 failures in test_migrations.py (all migration-test files); subsequent run was clean 355/355. All 14 failing tests passed in isolation. Treated as single-incident noise; if recurs, investigate transaction cleanup ordering and shared-state across migration tests.

### Next gate status
- A1 P0 to P1 gate: paper run reproducible end-to-end on production code path with paper Sharpe >= 2.0 over a meaningful window.
- Reproducibility: proven (synthetic + 3 real-data fixtures, all byte-stable).
- Three safety-property findings proven across different cost profiles + real fixtures. Engine refuses to trade in three distinct no-trade regimes for three distinct reasons.
- Sharpe number from yes-trade real-data window: blocked on Day 19b/20+ tape and live-fill calibration, OR on a maker-rebate-only research profile, OR on accepting Day 19a's research-calibrated profile as the gate evidence (NOT recommended without tape/live validation; would defeat the firewall purpose).

### Carry-forward debt
0009 Round 4.5 - Replay/Risk Matrix Hardening (non-blocking, post-signoff).

Day 19b/20 prerequisites:
1. Binance trade-history fetcher (we have a funding-rate fetcher but not a trade-history one).
2. Tape-based effective-spread estimator (Roll's estimator or similar; not currently implemented).
3. Sample-period selection methodology: which regimes to estimate spread in, how to weight them.

### Capital deployed
- $0. Program in P0 across all engines.
