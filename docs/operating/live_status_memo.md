# SuperHydra Live Status Memo

This memo refreshes weekly per roadmap §11. The roadmap holds principles and gates; this memo holds the snapshot.

---

## Week of 2026-05-06

### Migration foundation
- **0009 (risk evaluation)** — Round 4 closed. Commit `0f8b7b5`. 319/319 tests passing. Alembic round-trip clean.
- Reviewer's round-3 blocker (replay `+1µs` hack) closed via lineage-stored snapshot reuse with identity check. 0008 contract preserved.
- Reviewer signoff: round 4 structural contract closed; remaining items classified as round 4.5 coverage hardening.

### Sleeve A (build-to-trade)
- **Engine A1 — Funding-rate capture:** Phase P0 (research & build).
  - Day 1 (`0e7b377`): package skeleton + canonical FundingRate dataclass + cost-model config schema + PaperAdapter contract. 63 unit tests.
  - Day 2-3 (`8e60933`): Binance funding-rate fetcher with injectable HTTP transport, throttle, retry, fail-loud parsing. No new deps. 23 unit tests.
  - Day 4-5 (`fdb5450`): pure-function expected-next-period funding model (Decimal arithmetic, no look-ahead) and net-edge signal evaluator. Reproducibility byte-equality. 39 unit tests.
  - Day 6-7 (`6ea6fa5`): SizingConfig + OrderIntent (two-leg hedge invariants) + position-aware sizer. End of week 1: signal+sizer pipeline unit-tested end-to-end. 65 unit tests.
  - Day 8 (`ef45eaf`): vertical smoke test driving Day 1-7 pipeline through 0007 OMS / 0009 risk / 0008 positions on a fresh DB. **1 passed + 2 xfail.** Smoke test passes through fill insertion + order FSM advance to 'filled'. Reconcile, position_lots, snapshots, journals, and P&L all xfail strictly on the same root cause: missing `execution/ledger/fill_journal_writer.py`. That module is the keystone for Day 9-15 wiring.
  - **Cumulative A1 unit tests: 190 passing. Smoke test: 1 passed + 2 xfail (strict). Full migration suite: 319 passing.**
  - Day 9-15 next: build `execution/ledger/fill_journal_writer.py` — emits balanced journal entries from a SHADOW fill, allowing reconcile_fill to succeed and lifting the entire xfail block.
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
- A1 P0 → P1 gate: paper run reproducible end-to-end on production code path. Day 8 smoke test exposed `fill_journal_writer.py` as the single missing module; Day 9-15 work is now scoped against that target.

### Carry-forward debt
**0009 Round 4.5 — Replay/Risk Matrix Hardening** (non-blocking, post-signoff). Priority order:
1. Replay determinism stress (multi-CB, multi-limit)
2. Cross-environment isolation
3. CB × source_type full 16-cell matrix
4. Bucket D + cb_hard_stop combined
5. Cancel matrix × non-LIVE envs
6. Per-dimension exhaustive

**Day 8 reveal — fills→journal writer.** Single missing module blocks reconcile_fill, position_lots, position_snapshots, balanced journals, and P&L derivability. First Day 9-15 deliverable.

### Capital deployed
- $0. Program in P0 across all engines.

