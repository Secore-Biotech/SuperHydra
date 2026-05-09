# SuperHydra Live Status Memo

This memo refreshes weekly per roadmap section 11. The roadmap holds principles and gates; this memo holds the snapshot.

---

## Current state - 2026-05-09

### Migration foundation
- 0009 (risk evaluation) - Round 4 closed. Commit 0f8b7b5. 319/319 tests passing. Alembic round-trip clean.
- Reviewer signoff received. Round 4.5 coverage hardening tracked as carry-forward debt; non-blocking.

### Sleeve A (build-to-trade)
- Engine A1 - Funding-rate capture: Phase P0.
  - Day 1 (0e7b377): package skeleton + FundingRate + cost-model schema + PaperAdapter contract.
  - Day 2-3 (8e60933): Binance funding-rate fetcher.
  - Day 4-5 (fdb5450): expected-funding model + signal evaluator.
  - Day 6-7 (6ea6fa5): SizingConfig + OrderIntent + sizer. End of week 1.
  - Day 8 (ef45eaf): vertical smoke test through 0007/0008/0009. Recon revealed downstream chain blocks on a single missing module: execution/ledger/fill_journal_writer.py.
  - Day 9 (e8ea7fc): pure-function trade-journal construction (spot/perp dispatch, v1 chart-of-accounts, idempotency hash). 72 unit tests.
  - Day 10 (41bc333): pure-function account-code parser. 54 unit tests.
  - Day 11 (fb340c1): DB writer for fill journals - idempotency, draft-resume, hash mismatch, account-code collision. 13 integration tests.
  - Day 12.5 (a62861e): FillRecord uses venue_namespace + venue_fill_id (was fill_uuid).
  - Day 12 (62ad88a): smoke test wires writer end-to-end. KEY DISCOVERY: schema's fills_reconciled_derive_positions trigger auto-populates position_lots when reconcile_fill sets journal_id. Day 13 CANCELED.
  - Day 14a (cc2ef54): pure-function build_funding_journal + FundingEventRecord. 33 unit tests.
  - Day 14b (4f47a14): write_and_post_funding_journal + funding_payment INSERT. 9 integration tests covering all four state-machine branches (fresh, replay-idempotent, recovery, integrity-failure).
  - Day 14c (04a0b35): smoke test extended with one fake funding event end-to-end. Receives $0.05 (short -0.01 BTC at rate +0.0001, mark $50k). 4 smoke tests now pass.
  - Cumulative: 166 unit + 26 integration tests passing. Full migration suite: 319 passing.
  - The vertical pipeline runs end-to-end: pure-function pipeline -> OrderIntent -> orders -> risk -> reservations -> outbox -> state transitions -> fills -> trade journal -> reconciliation -> position_lots (auto via trigger) -> position_snapshots -> funding event -> funding journal -> funding_payment -> ledger entries, in 4.7 seconds against the real schema.
  - A1 P0 deliverables for the engine itself are complete. Trade journals + reconciliation + position lots + snapshots + funding journals + funding payments all working with idempotency, source-hash mismatch detection, and recovery semantics. The P0 -> P1 gate now reads as: paper run reproducible end-to-end on production code path. The infrastructure to support that paper run exists.
  - Next concrete deliverable: A1 paper runner. Polls Binance for funding rates, evaluates the signal, sizes intents, submits orders through the OMS path proven by the smoke test, ingests fills, writes trade journals, polls funding intervals, builds and posts funding events. Day 15+.
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
- Day 14c closes the structural gap on funding events. The accounting layer of A1 is complete: trade journals, fill reconciliation, position snapshots, funding journals, funding payments all working in the smoke test against real Postgres.
- Next deliverable: A1 paper runner that drives the proven schema path with real Binance data. Day 15+.

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
