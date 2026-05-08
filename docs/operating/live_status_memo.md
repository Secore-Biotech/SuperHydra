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
  - Day 6-7 (`6ea6fa5`): SizingConfig + OrderIntent + sizer. End of week 1 milestone.
  - Day 8 (`ef45eaf`): vertical smoke test through 0007/0008/0009. **1 passed + 2 strict xfail.** Recon revealed entire downstream chain (reconcile_fill, position_lots, snapshots, journals, P&L) blocks on a single missing module: `execution/ledger/fill_journal_writer.py`.
  - Day 9 (`e8ea7fc`): pure-function `fill_journal_writer` with spot/perp dispatch and v1 chart-of-accounts naming. 72 unit tests covering helpers, validation, balance enforcement, hash determinism, byte-equality reproducibility. **No DB; pure functions only.** Day 10-11 wires it to Postgres.
  - **Cumulative: 240 unit tests passing + 1 smoke passed + 2 strict xfail. Full migration suite: 319 passing.**
  - Day 10 next: chart-of-accounts seeder (`execution/ledger/chart_of_accounts.py`) — creates the ledger_accounts that the writer references on first use of each (portfolio, strategy, account, asset/instrument) tuple.
  - Day 11: DB-side `write_and_post_journal` + integration tests proving idempotency.
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
- N/A — no engines in paper or canary.

### Unresolved risk exceptions
- None.

### Next gate status
- A1 P0 → P1 gate: paper run reproducible end-to-end on production code path.
- Day 9 closed the structural gap on journal construction. Day 10-11 closes the DB wiring. Day 12 unblocks reconciliation in the smoke test. After that, the path to a 60-day paper run is mechanical.

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

