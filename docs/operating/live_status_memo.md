# SuperHydra Live Status Memo

This memo refreshes weekly per roadmap section 11. The roadmap holds principles and gates; this memo holds the snapshot.

---

## Current state - 2026-05-09 (late evening update)

### Migration foundation
- 0009 (risk evaluation) - Round 4 closed. Commit 0f8b7b5. 319/319 tests passing in isolation. Alembic round-trip clean.
- One full-suite test ordering failure observed: test_round4_evaluate_action_rejects_foreign_snapshot fails when run as part of the full integration suite but passes in isolation. Tracked as Day 16d cleanup; non-blocking.
- Reviewer signoff received. Round 4.5 coverage hardening tracked as carry-forward debt; non-blocking.

### Sleeve A (build-to-trade)
- Engine A1 - Funding-rate capture: Phase P0.
  - Days 1-12.5: pipeline + smoke test + writers (see prior memo entries).
  - Days 14a-c: funding journal writer + funding_payment INSERT + smoke test extension.
  - Day 15a (c2c7d40): A1PaperRunner skeleton — pure orchestration with injected dependencies.
  - Day 15b.1 (9891680): extracted submit_intent_through_oms helper.
  - Day 15b.2 (9f3b037): A1PaperRunner integration test against real Postgres.
  - Day 15c (8d1646f): dispatch_due_funding_events + multi-tick idempotency tests.
  - Day 16a (0b0f431): synthetic 30-interval backfill harness against real Postgres. Drives the runner across 30 funding intervals in 1.32s. Tick 1 establishes hedged BTCUSDT perp/spot exposure (-0.01 BTC perp short, +0.01 BTC spot long); ticks 2-30 self-regulate via current_position_matches_target; 29 funding events accrue coherently across the held window; realized USD lands in expected $130-$160 band; no double exposure; no orphan accounting rows. Determinism by hardcoded rate sequence (12-rate prior + 30-rate backfill in [0.0045, 0.0055]); the realized USD figure is byte-stable across machines.
  - Cumulative: 220 unit + 30 integration tests passing across the strategy. Total: 391 tests.
  - The runtime API is wired AND demonstrated under sustained sequential operation. The 30-interval harness is the proof that a longer paper window (60d, 180d) will produce coherent accounting state.
  - Next deliverables, in order:
    1. Day 16c — Sharpe computation. Pure-function reading accounting.journals + accounting.funding_payments over a time window, returns annualized Sharpe. Testable with synthetic accounting fixtures. Once in place, every backfill becomes gate-readable evidence.
    2. Day 16b — real Binance 60-day replay. Same harness as 16a, fetcher-driven instead of hardcoded. With 16c, this produces the actual P0->P1 gate evidence number.
    3. Day 16d — test ordering cleanup. Investigate the test_round4 ordering issue before more tests pile on.
- Engine A2 - Basis: Not started.
- Engine A3 - Cash-and-carry: Deferred.

### Sleeve B (build-to-research)
- Phase P0. No work this week.

### Build blockers
- None.

### Data integrity issues
- None in functional code paths. One pre-existing test ordering issue noted under Migration foundation; isolated test passes.

### Paper-vs-live drift
- N/A. No live deployment.

### Unresolved risk exceptions
- None.

### Next gate status
- A1 P0 to P1 gate: paper run reproducible end-to-end on production code path with paper Sharpe >= 2.0 over a meaningful window.
- Reproducibility: proven (Day 16a, 30-interval synthetic backfill, byte-stable).
- Sharpe number: not yet computed. Day 16c is the immediate next deliverable that turns the existing backfill into a gate-readable Sharpe.
- Real-data evidence: pending Day 16b. Synthetic mean rate ~0.0050 vs ~0.0012 cost gives unrealistically clean P&L; real Binance data will surface the noise.

### Carry-forward debt
0009 Round 4.5 - Replay/Risk Matrix Hardening (non-blocking, post-signoff). Priority order:
1. Replay determinism stress (multi-CB, multi-limit)
2. Cross-environment isolation
3. CB x source_type full 16-cell matrix
4. Bucket D + cb_hard_stop combined
5. Cancel matrix x non-LIVE envs
6. Per-dimension exhaustive

Test ordering cleanup (Day 16d):
1. Identify which earlier integration test pollutes state
2. Either fix the pollution or harden the round4 test's setup

### Capital deployed
- $0. Program in P0 across all engines.
