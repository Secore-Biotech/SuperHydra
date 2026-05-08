# SuperHydra Live Status Memo

This memo refreshes weekly per roadmap §11. The roadmap holds principles and gates; this memo holds the snapshot.

---

## Current state — 2026-05-08

### Migration foundation
- **0009 (risk evaluation)** — Round 4 closed. Commit `0f8b7b5`. 319/319 tests passing. Alembic round-trip clean.
- Reviewer signoff received. Round 4.5 coverage hardening tracked as carry-forward debt; non-blocking.

### Sleeve A (build-to-trade)
- **Engine A1 — Funding-rate capture:** Phase P0.
  - Day 1 (`0e7b377`): package skeleton + FundingRate + cost-model schema + PaperAdapter contract.
  - Day 2-3 (`8e60933`): Binance funding-rate fetcher.
  - Day 4-5 (`fdb5450`): expected-funding model + signal evaluator.
  - Day 6-7 (`6ea6fa5`): SizingConfig + OrderIntent + sizer. End of week 1.
  - Day 8 (`ef45eaf`): vertical smoke test through 0007/0008/0009. **1 passed + 2 strict xfail.** Recon revealed the entire downstream chain (reconcile_fill, position_lots, snapshots, journals, P&L) blocks on `execution/ledger/fill_journal_writer.py`.
  - Day 9 (`e8ea7fc`): pure-function `fill_journal_writer` with spot/perp dispatch and v1 chart-of-accounts naming. 72 unit tests.
  - Day 10 (`41bc333`): pure-function `chart_of_accounts` parser inverting v1 codes into typed AccountSpec. Strict version-gating (no silent v2 fallback). Resolver-callable design keeps it DB-independent. 54 unit tests.
  - **Cumulative: 294 unit tests passing + 1 smoke passed + 2 strict xfail. Full migration suite: 319 passing.**
  - The pure-function half of the Day 9-15 keystone is complete: Day 9 builds balanced JournalDrafts from fills; Day 10 inverts account codes back to AccountSpecs. Day 11-12 wires both to Postgres.
  - Day 11 next: DB-side `resolve_account_id` (UPSERT into accounting.ledger_accounts) + `write_and_post_journal` (insert + post_journal). Integration tests prove idempotency on (source_type, source_id, source_hash).
  - Day 12: wire writer into smoke test step 8, lift xfail on reconcile_fill.
  - Day 13: discover whether fills→position_lots also needs a writer; if so, build it.
  - Day 14: funding-event journals (`build_funding_journal`).
  - Day 15: lift remaining xfails on smoke test steps 11-12.
- **Engine A2 — Basis:** Not started.
- **Engine A3 — Cash-and-carry:** Deferred.

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
- A1 P0 → P1 gate: paper run reproducible end-to-end on production code path.
- Days 9-10 complete the structural pure-function design. Day 11 closes the DB-write gap. Day 12 unblocks reconciliation in the smoke test. After that, the path to a 60-day paper run is mechanical wiring.

### Carry-forward debt
**0009 Round 4.5 — Replay/Risk Matrix Hardening** (non-blocking, post-signoff). Priority order:
1. Replay determinism stress (multi-CB, multi-limit)
2. Cross-environment isolation
3. CB × source_type full 16-cell matrix
4. Bucket D + cb_hard_stop combined
5. Cancel matrix × non-LIVE envs
6. Per-dimension exhaustive

### Capital deployed
- $0. Program in P0 across all engines.

