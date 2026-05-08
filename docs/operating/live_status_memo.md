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
  - Day 8 (ef45eaf): vertical smoke test through 0007/0008/0009. 1 passed + 2 strict xfail. Recon revealed downstream chain (reconcile_fill, position_lots, snapshots, journals, P&L) blocks on a single missing module: execution/ledger/fill_journal_writer.py.
  - Day 9 (e8ea7fc): pure-function journal construction (spot/perp dispatch, v1 chart-of-accounts naming, idempotency hash). 72 unit tests.
  - Day 10 (41bc333): pure-function account-code parser inverting v1 codes into typed AccountSpec. Strict version-gating. 54 unit tests.
  - Day 11 (fb340c1): DB writer with idempotency, draft-resume recovery, source-hash mismatch detection, account-code collision detection. 13 integration tests against real Postgres, all passing first attempt. Caller owns transaction.
  - Cumulative: 307 unit + integration tests passing + 1 smoke passed + 2 strict xfail. Full migration suite: 319 passing.
  - The Day 9-15 keystone is operational. The fill-to-journal writer now exists, is idempotent, integrity-checked, and battle-tested against the 0005 schema's actual triggers and constraints.
  - Day 12 next: wire the writer into smoke test step 8. Lift xfail on reconcile_fill - confirms a fill can now produce a journal_id that satisfies the trigger chain. Expected to expose whether step 9 (compute_position_snapshot) needs additional wiring (likely yes - position_lots requires reconciled fills + something to drive lot creation from fill events).
  - Day 13: discover whether fills-to-position_lots also needs a writer; if so, build it.
  - Day 14: funding-event journals (build_funding_journal) - the actual P&L engine for A1.
  - Day 15: lift remaining xfails on smoke test steps 11-12.
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
- Day 11 closes the structural gap on journal writes. Day 12 unblocks reconciliation in the smoke test by integrating the writer. After that, the path to a 60-day paper run is mechanical wiring.

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
