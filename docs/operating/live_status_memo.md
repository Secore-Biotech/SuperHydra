# SuperHydra Live Status Memo

This memo refreshes weekly per roadmap section 11. The roadmap holds principles and gates; this memo holds the snapshot.

---

## Current state - 2026-05-09 (late evening, second update)

### Migration foundation
- 0009 (risk evaluation) - Round 4 closed. Commit 0f8b7b5. Full integration suite passes 353/353 in 5:13 after Day 16d.1 fix.

### Sleeve A (build-to-trade)
- Engine A1 - Funding-rate capture: Phase P0.
  - Days 1-12.5: pipeline + smoke test + writers.
  - Days 14a-c: funding journal writer + funding_payment INSERT + smoke test extension.
  - Days 15a-c: A1PaperRunner skeleton, OMS submit helper, real-DB integration test, multi-tick idempotency tests, dispatch_due_funding_events.
  - Day 16a (0b0f431): synthetic 30-interval backfill harness against real Postgres in 1.32s.
  - Day 16c (d4b6a75): Sharpe computation. analytics/strategy_metrics.py with IntervalReturn, SharpeResult, compute_interval_returns, compute_sharpe. 12 unit tests + 3 integration tests.
  - Day 16b (9a6be81): real-data no-trade regime test against committed 14-day Binance fixture. The fixture window (Apr 24 - May 8 2026) was a no-edge regime: mean rate -0.000026, 32 of 42 intervals negative. Engine correctly produced signal_flat on every tick. Tripwire callbacks raise if submit/fund ever fire.
  - Day 16d.1 (37018b9): fixed test_round4_evaluate_action_rejects_foreign_snapshot under load. Diagnosis was not test ordering but two separate datetime.now() calls hitting a Postgres timestamp-precision boundary; capture once and reuse fixed it.
  - Day 16d.2 (a182090): synthetic harness fill_ts now uses the logical clock; restored strict fee assertion in Sharpe integration. Also discovered and fixed a snapshot-source ambiguity: risk.evaluate_action creates side-effect snapshots at NOW() with computation_version='risk_eval_v1', distinct from the runner's authoritative snapshots at computation_version='a1.runner.v0'. Position queries now filter on the version invariant.
  - Day 16b.2 probe (27bf80d): Dec 2024 BTCUSDT funding fixture committed for future yes-trade test. Empirical finding: 42/43 intervals positive (mean 0.000091, max 0.0001), but 0/43 above the conservative_default_v0 cost threshold of ~0.0012 per interval.
  - Cumulative: 247 unit + 36 integration tests across the strategy. Full integration suite 353/353 in 5:13.
  - **Engine safety properties documented with real-data evidence**:
    - Trades correctly when synthetic edge exists (Days 15b/c, 16a synthetic backfill).
    - Refuses to trade when real-data edge does not exist (Day 16b Apr-May 2026; Day 16b.2 Dec 2024).
  - Sharpe pipeline working end-to-end against accounting rows (Day 16c).
  - Real Binance fetcher integration proven (Days 16b + 16b.2 fixtures).

### Structural finding: BTCUSDT yes-trade not reachable under placeholder costs

The Dec 2024 fixture probe surfaced a real economics finding rather than a pipeline issue. With conservative_default_v0 (the placeholder cost model documented in its own docstring as "pending empirical calibration"):

  - Per-interval cost = 2x taker (10 bps) + 2x slippage (2 bps) + borrow amortization (~0.33 bps/interval) = ~12.3 bps per interval.
  - Binance BTCUSDT funding caps structurally at 0.01% (1 bp) per 8h interval.
  - Even in the strongest historical funding window we have data for (Dec 2024, near peak euphoria), the rolling 12-interval mean topped out at 9.9 bps - still below the cost threshold.

This means the engine's correct behavior on real Binance BTCUSDT under the current cost model is **always no-trade**, regardless of regime. This is governance-positive: the engine refuses unprofitable carry. But it also means a yes-trade real-data demonstration requires either:
  - Calibrated VIP-tier cost model (Binance VIP9 maker rebate brings round-trip cost to ~3 bps), or
  - A different instrument class (altcoin perps with 0.5%-1% funding spikes) and a corresponding altcoin cost profile.

### Next deliverables, in order:
  1. **Memo + structural assertion test** (next session start). Add an explicit integration test that verifies `current placeholder cost threshold > 0.01% Binance BTCUSDT funding cap` so that any future cost model change either preserves the structural inequality (with documentation) or invalidates the assertion (forcing the test to be relabeled or split). This makes today's finding a tested invariant rather than a memo footnote.
  2. **Day 17: empirical cost-model calibration**. VIP-tier maker/taker scenarios for Binance, Bybit, OKX. Realistic top-of-book slippage for BTC vs altcoins. Per-engine cost profiles (A1, A2, A3). Replace `conservative_default_v0` with calibrated `binance_vip_btc_v1`, `binance_vip_alt_v1`, etc. Each profile gets its own content hash so old paper Sharpes preserve their lineage.
  3. **Day 16b.2 revisited**. Once Day 17 produces calibrated cost models, retry yes-trade fixture using either VIP-tier BTC costs against the Dec 2024 fixture, or an altcoin window. Both Apr-May 2026 and Dec 2024 fixtures stay committed - the Dec 2024 fixture immediately becomes yes-trade evidence under VIP costs.

### Sleeve A2/A3
- A2 - Basis: Not started.
- A3 - Cash-and-carry: Deferred.

### Sleeve B
- Phase P0. No work this week.

### Build blockers
- None blocking forward progress.

### Data integrity issues
- None in production code paths.

### Paper-vs-live drift
- N/A. No live deployment.

### Unresolved risk exceptions
- None.

### Next gate status
- A1 P0 to P1 gate: paper run reproducible end-to-end on production code path with paper Sharpe >= 2.0 over a meaningful window.
- Reproducibility: proven (synthetic + 2 real-data fixtures, all byte-stable).
- Both safety properties proven across synthetic + real data.
- Sharpe number from a yes-trade real-data window: blocked on Day 17 cost calibration. Today's structural finding is itself gate-relevant evidence: the engine does not generate spurious trades under realistic Binance BTCUSDT funding caps with placeholder costs.

### Carry-forward debt
0009 Round 4.5 - Replay/Risk Matrix Hardening (non-blocking, post-signoff).

Day 17 prerequisites:
1. Add structural-inequality assertion test (Day 16e or first task of Day 17).
2. Empirical cost calibration for top venues + tier combinations.
3. Per-engine cost-profile selection logic (A1 picks BTC profile or alt profile based on instrument).

### Capital deployed
- $0. Program in P0 across all engines.
