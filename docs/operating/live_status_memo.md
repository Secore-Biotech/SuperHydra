# SuperHydra Live Status Memo

This memo refreshes weekly per roadmap section 11. The roadmap holds principles and gates; this memo holds the snapshot.

---

## Current state - 2026-05-09 (evening update)

### Migration foundation
- 0009 (risk evaluation) - Round 4 closed. Commit 0f8b7b5. 319/319 tests passing. Alembic round-trip clean.
- Reviewer signoff received. Round 4.5 coverage hardening tracked as carry-forward debt; non-blocking.

### Sleeve A (build-to-trade)
- Engine A1 - Funding-rate capture: Phase P0.
  - Day 1 (0e7b377): package skeleton + FundingRate + cost-model schema + PaperAdapter contract.
  - Day 2-3 (8e60933): Binance funding-rate fetcher.
  - Day 4-5 (fdb5450): expected-funding model + signal evaluator.
  - Day 6-7 (6ea6fa5): SizingConfig + OrderIntent + sizer.
  - Day 8 (ef45eaf): vertical smoke test through 0007/0008/0009.
  - Day 9 (e8ea7fc): pure-function trade-journal construction.
  - Day 10 (41bc333): pure-function account-code parser.
  - Day 11 (fb340c1): DB writer for fill journals.
  - Day 12.5 (a62861e): FillRecord uses venue_namespace + venue_fill_id.
  - Day 12 (62ad88a): smoke test wires writer end-to-end. KEY DISCOVERY: schema's fills_reconciled_derive_positions trigger auto-populates position_lots. Day 13 CANCELED.
  - Day 14a (cc2ef54): pure-function build_funding_journal.
  - Day 14b (4f47a14): write_and_post_funding_journal + funding_payment INSERT.
  - Day 14c (04a0b35): smoke test extended with one fake funding event end-to-end.
  - Day 15a (c2c7d40): A1PaperRunner skeleton — pure orchestration with injected dependencies.
  - Day 15b.1 (9891680): extracted submit_intent_through_oms helper into strategies/a1_funding/runner/oms_submit.py.
  - Day 15b.2 (9f3b037): A1PaperRunner integration test against real Postgres. submit_callback closure composes helper + journal writer + reconcile_fill + compute_position_snapshot. Single tick produces full accounted state in ~1 second.
  - Day 15c (8d1646f): dispatch_due_funding_events + multi-tick idempotency tests. Two-tick test (tick 2 reads existing position, no double exposure) and funding-dispatch replay test (3 events post once, replay no-ops) prove the runner's idempotency contract holds against real schema.
  - Cumulative: 220 unit + 29 integration tests passing. Full migration suite: 319 passing. Total: 390 tests across the strategy.
  - The engine has a fully wired runtime API: tick() for signal-driven order generation, dispatch_due_funding_events() for accrual posting, both with one-coherent-timestamp semantics and per-event error capture. The runner stays DB-ignorant; production wiring lives in callbacks.
  - A1 Day 15 complete. Day 15 deliverables: runner skeleton, OMS-submit extraction, real-DB integration test, multi-tick idempotency proofs, funding-event dispatch.
  - The P0 -> P1 gate reads: paper run reproducible end-to-end on production code path. The infrastructure exists. What remains is execution — actually running the runner against historical or live Binance funding data for a meaningful window and measuring paper Sharpe.
  - Next concrete deliverable: paper window execution. Two viable modes:
    - Backfill: historical Binance funding rates fed through the runner with a logical-clock fake that jumps forward, producing decisions for each historical interval. Faster (no wall-clock wait); produces an evaluable Sharpe number quickly.
    - Live shadow: runner runs in real-time against current Binance feeds, producing intents and modeled fills at observed marks. Slower but production-shaped.
    - Backfill mode is preferred for the P0 -> P1 gate because it produces measurable results in days, not weeks.
- Engine A2 - Basis: Not started.
- Engine A3 - Cash-and-carry: Deferred.

### Sleeve B (build-to-research)
- Phase P0. No work this week.

### Build blockers
- None.

### Data integrity issues
- None.

### Paper-vs-live drift
- N/A. No live deployment.

### Unresolved risk exceptions
- None.

### Next gate status
- A1 P0 to P1 gate: paper run reproducible end-to-end on production code path.
- The runtime API is wired. What remains is paper-window execution at meaningful length to satisfy the per-engine paper Sharpe gate (>= 2.0) over a meaningful window.
- The fastest path is backfill mode against historical Binance funding-rate data.

### Carry-forward debt
0009 Round 4.5 - Replay/Risk Matrix Hardening (non-blocking, post-signoff). Priority order:
1. Replay determinism stress (multi-CB, multi-limit)
2. Cross-environment isolation
3. CB x source_type full 16-cell matrix
4. Bucket D + cb_hard_stop combined
5. Cancel matrix x non-LIVE envs
6. Per-dimension exhaustive

### Capital deployed
- $0. Program in P0 across all engines.
