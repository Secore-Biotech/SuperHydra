# SuperHydra Live Status Memo

This memo refreshes weekly per roadmap section 11. The roadmap holds principles and gates; this memo holds the snapshot.

---

## Current state - 2026-05-09 (afternoon update)

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
  - Day 9 (e8ea7fc): pure-function trade-journal construction. 72 unit tests.
  - Day 10 (41bc333): pure-function account-code parser. 54 unit tests.
  - Day 11 (fb340c1): DB writer for fill journals. 13 integration tests.
  - Day 12.5 (a62861e): FillRecord uses venue_namespace + venue_fill_id.
  - Day 12 (62ad88a): smoke test wires writer end-to-end. KEY DISCOVERY: schema's fills_reconciled_derive_positions trigger auto-populates position_lots. Day 13 CANCELED.
  - Day 14a (cc2ef54): pure-function build_funding_journal. 33 unit tests.
  - Day 14b (4f47a14): write_and_post_funding_journal + funding_payment INSERT. 9 integration tests.
  - Day 14c (04a0b35): smoke test extended with one fake funding event end-to-end.
  - Day 15a (c2c7d40): A1PaperRunner skeleton — pure orchestration with injected dependencies. 23 unit tests across 6 classes.
  - Day 15b.1 (9891680): extracted submit_intent_through_oms helper into strategies/a1_funding/runner/oms_submit.py. Smoke test refactored, no behavior change. 4 smoke tests still pass in 4.36s.
  - Day 15b.2 (9f3b037): A1PaperRunner integration test against real Postgres. submit_callback closure composes helper + journal writer + reconcile_fill + compute_position_snapshot. Single tick produces full accounted state in ~1 second.
  - Cumulative: 215 unit + 27 integration tests passing. Full migration suite: 319 passing. Total: 383 tests across the strategy.
  - The runner now drives the full accounted path end-to-end against real Postgres in ~1 second: clock → signal → size → submit → allocator/targets → intents → orders → risk → reservations → outbox → FSM → fills → journals → reconcile → position_lots (auto via trigger) → position_snapshots.
  - A1 P0 deliverables for the engine itself are complete. The P0 -> P1 gate now reads as: paper run reproducible end-to-end on production code path. The runner exists, the path is wired, the assertions hold.
  - Next concrete deliverable: Day 15c — multi-tick idempotency tests proving the runner doesn't break itself across repeated ticks.
- Engine A2 - Basis: Not started.
- Engine A3 - Cash-and-carry: Deferred.

### Sleeve B (build-to-research)
- Phase P0. No work this week.

### Build blockers
- None.

### Data integrity issues
- None.

### Paper-vs-live drift
- N/A.

### Unresolved risk exceptions
- None.

### Next gate status
- A1 P0 to P1 gate: paper run reproducible end-to-end on production code path.
- The single-tick path is proven (Day 15b). Multi-tick idempotency is Day 15c.
- After Day 15c the engine is positioned for actual paper-window execution against real Binance feeds.

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
