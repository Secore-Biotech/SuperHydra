# SuperHydra Live Status Memo

This memo refreshes weekly per roadmap section 11. The roadmap holds principles and gates; this memo holds the snapshot.

---

## Current state - 2026-05-08

### Migration foundation
- 0009 (risk evaluation) - Round 4 closed. Commit 0f8b7b5. 319/319 tests passing. Alembic round-trip clean.
- Reviewer signoff received. Round 4.5 coverage hardening tracked as carry-forward debt; non-blocking.

### Sleeve A (build-to-trade)
- Engine A1 - Funding-rate capture: Phase P0.
  - Day 1 (0e7b377): package skeleton + FundingRate + cost-model schema + PaperAdapter contract.
  - Day 2-3 (8e60933): Binance funding-rate fetcher.
  - Day 4-5 (fdb5450): expected-funding model + signal evaluator.
  - Day 6-7 (6ea6fa5): SizingConfig + OrderIntent + sizer. End of week 1.
  - Day 8 (ef45eaf): vertical smoke test through 0007/0008/0009. 1 passed + 2 strict xfail. Recon revealed downstream chain blocks on a single missing module: execution/ledger/fill_journal_writer.py.
  - Day 9 (e8ea7fc): pure-function journal construction (spot/perp dispatch, v1 chart-of-accounts naming, idempotency hash). 72 unit tests.
  - Day 10 (41bc333): pure-function account-code parser inverting v1 codes into typed AccountSpec. Strict version-gating. 54 unit tests.
  - Day 11 (fb340c1): DB writer with idempotency, draft-resume recovery, source-hash mismatch detection, account-code collision detection. 13 integration tests against real Postgres. Caller owns transaction.
  - Day 12.5 (a62861e): FillRecord uses venue_namespace + venue_fill_id (was fill_uuid). The accounting layer reconciles by venue identity, not internal ids.
  - Day 12 (62ad88a): smoke test wires writer end-to-end. Steps 7.5-9 added (build/write/post journal per fill, reconcile_fill, compute_position_snapshot). All 3 smoke tests pass. KEY DISCOVERY: the schema's fills_reconciled_derive_positions trigger (0008_positions.py, AFTER UPDATE OF journal_id ON trading.fills) automatically calls process_fill_to_lots when reconcile_fill sets the journal_id. This means Day 13 (originally scoped as fills-to-position_lots writer) is UNNECESSARY - the schema handles it.
  - Cumulative: 128 unit + 16 integration tests passing. Full migration suite: 319 passing.
  - The Day 9-15 keystone is operationally complete. The vertical pipeline runs end-to-end: pure-function pipeline -> OrderIntent -> orders -> risk -> reservations -> outbox -> state transitions -> fills -> journal -> reconciliation -> position_lots -> position_snapshots, all in 3.5 seconds against the real schema.
  - Day 13 CANCELED.
  - Day 14 next: build_funding_journal for funding-event accruals. The actual A1 P&L source. Different shape from trade journals (cash to/from funding_income/funding_expense per instrument).
  - Day 15: already done (smoke test xfails are lifted).
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
- Day 12 closes the vertical pipeline. Trade journals reconcile to position lots automatically via schema cascade. Day 14 builds funding-event journals on the same writer infrastructure - the one remaining piece of A1 P&L attribution.
- After Day 14, A1 has everything needed to start a 60-day paper run.

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
