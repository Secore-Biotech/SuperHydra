# SuperHydra Live Status Memo

This memo refreshes weekly per roadmap section 11. The roadmap holds principles and gates; this memo holds the snapshot.

---

## Current state - 2026-05-09 (third update, end of Day 17)

### Migration foundation
- 0009 (risk evaluation) - Round 4 closed. Commit 0f8b7b5. Full integration suite passes 354/354 in 5:17 after Day 17c pivot.

### Sleeve A (build-to-trade)
- Engine A1 - Funding-rate capture: Phase P0.
  - Days 1-12.5: pipeline + smoke test + writers.
  - Days 14a-c: funding journal writer + funding_payment INSERT + smoke test extension.
  - Days 15a-c: A1PaperRunner + OMS submit helper + dispatch_due_funding_events.
  - Day 16a (0b0f431): synthetic 30-interval backfill harness against real Postgres in 1.32s.
  - Day 16c (d4b6a75): Sharpe computation analytics module.
  - Day 16b (9a6be81): real-data no-trade regime test (Apr-May 2026 fixture, placeholder costs).
  - Day 16d.1 (37018b9): timestamp-determinism fix in the migration test.
  - Day 16d.2 (a182090): synthetic harness fill_ts logical clock + snapshot-source disambiguation.
  - Day 16b.2 probe (27bf80d): Dec 2024 BTCUSDT fixture committed.
  - Day 16e (9ba2be0): structural cost-threshold invariant tests (placeholder vs BTCUSDT cap).
  - Day 17a (52c9604): calibrated cost-profile foundation - placeholder_v0 rename + alias, three Binance profiles (vip0_retail / vip5_btc / vip9_institutional), ProfileSource metadata, hash includes profile identity.
  - Day 17b (0221efa): A1 cost-profile selector module under strategies/a1_funding/config/. Maps (instrument, venue) to CostModelConfig.
  - Day 17c PIVOT (5b8a7c3): The original Day 17c hypothesis was that VIP5 economics would open a BTCUSDT yes-trade window. The math falsified the hypothesis. Pivoted to commit the honest finding.
  - Cumulative: 264 unit + 39 integration tests across the strategy. Full integration suite 354/354 in 5:17.
  - Engine safety properties documented with real-data evidence:
    - Trades correctly when synthetic edge exists (Days 15b/c, 16a synthetic backfill).
    - Refuses to trade when real-data edge does not exist (Days 16b + 17c, two cost profiles, two real fixtures).
  - Sharpe pipeline working end-to-end against accounting rows (Day 16c).

### Structural finding (Day 17c): BTCUSDT untradeable across all currently-modeled cost profiles

The Day 17 calibration sweep produced a stronger structural result than the Day 16b.2 probe surfaced. Tested across three cost profiles:

  - placeholder_v0 threshold:           ~12.3 bps per interval
  - binance_vip5_btc_v1 threshold:       ~7.7 bps per interval
  - binance_vip9_institutional_v1:       ~5.4 bps per interval

  - Binance BTCUSDT funding cap:           1 bp per interval (structural, cf. official funding-rate spec)

Even institutional VIP9 fees leave the threshold ~5x above the cap. The dominant cost component is slippage (btc_eth_top_tier = 1 bp per leg = 2 bps round-trip), which alone is 2x the funding cap. Fees cannot save the math.

This is a genuine economics finding, not a pipeline bug. Five unit tests + two integration tests document it as a tested invariant. If anyone changes a cost profile and accidentally drops it below the BTCUSDT cap, the right tests will fail with diagnostic messages pointing at investigation.

A1 yes-trade evidence requires either:
  - Altcoin perps (DOGE, AVAX, SOL, etc.) where funding routinely reaches 50+ bps in volatile regimes, paired with a calibrated alt slippage tier.
  - A research-only maker-rebate profile modeling passive-only execution at top-of-book with sub-bp slippage assumptions.

Both are real Day 18+ deliverables, not blocked by anything Day 17 did.

### Next deliverables, in order

1. **Day 18a - Altcoin profile + selector extension.** Add a calibrated altcoin slippage tier (probably 2-5 bps per leg for liquid alts vs 1 bp for BTC/ETH) and an alt fee profile if it differs from BTC profiles. Extend select_profile_for_a1 to handle altcoin instruments. Smallest possible scope: pick one alt (e.g. SOLUSDT) and one realistic profile.
2. **Day 18b - Real altcoin funding fixture.** Probe + commit a 14-day fixture for the chosen alt, similar to the Dec 2024 BTC fixture. Compute fixture stats; only commit yes-trade if rates genuinely clear the alt threshold.
3. **Day 18c - Yes-trade integration test under altcoin + alt profile.** The actual gate-readable Sharpe number.

Alternative path: research-only maker-rebate profile. Could be done in parallel as binance_maker_only_research_v1 with documented "research-only, do not deploy" caveat. Lower priority than altcoin pivot.

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

### Next gate status
- A1 P0 to P1 gate: paper run reproducible end-to-end on production code path with paper Sharpe >= 2.0 over a meaningful window.
- Reproducibility: proven (synthetic + 2 real-data fixtures, all byte-stable).
- Both safety properties proven across synthetic + real data + two cost profiles.
- Sharpe number from a yes-trade real-data window: blocked on Day 18 altcoin pivot OR maker-rebate research profile. Today's Day 17c finding is itself gate-relevant evidence: A1 has no edge on BTCUSDT, regardless of fee tier, under realistic costs. The strategy is structurally correct; the instrument choice was wrong.

### Carry-forward debt
0009 Round 4.5 - Replay/Risk Matrix Hardening (non-blocking, post-signoff).

Day 18 prerequisites:
1. Choose altcoin (likely SOLUSDT based on liquidity + funding-rate volatility).
2. Calibrate alt slippage tier and (if different from BTC) alt fee schedule.
3. Decide whether to pursue maker-rebate research profile in parallel or sequence.

### Capital deployed
- $0. Program in P0 across all engines.
