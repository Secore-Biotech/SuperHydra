# SuperHydra Live Status Memo

This memo refreshes weekly per roadmap §11. The roadmap holds principles and gates; this memo holds the snapshot.

---

## Week of 2026-05-06

### Migration foundation
- **0009 (risk evaluation)** — Round 4 closed. Commit `0f8b7b5` on `feature/migrations-0001-foundation`. 319/319 tests passing. Alembic round-trip 0001 → 0009 → base → 0009 clean.
- Reviewer's round-3 blocker (replay `+1µs` hack on `p_as_of_at`) closed via lineage-stored snapshot reuse with identity check. 0008 contract preserved untouched.
- Reviewer signoff: round 4 structural contract closed; remaining items classified as round 4.5 coverage hardening, not blockers to merge unless reviewer requests them beforehand.

### Sleeve A (build-to-trade)
- **Engine A1 — Funding-rate capture:** Phase P0 (research & build). End of week 1 milestone hit: signal+sizer pipeline unit-tested end-to-end.
  - Day 1 (`0e7b377`): package skeleton + canonical FundingRate dataclass + cost-model config schema + PaperAdapter contract. 63 unit tests.
  - Day 2-3 (`8e60933`): Binance funding-rate fetcher with injectable HTTP transport, throttle, retry, fail-loud parsing. No new deps. 23 unit tests.
  - Day 4-5 (`fdb5450`): pure-function expected-next-period funding model (mean - discount_k * stdev, Decimal arithmetic, no look-ahead) and net-edge signal evaluator (LONG_PERP_SHORT_SPOT / SHORT_PERP_LONG_SPOT / FLAT). Reproducibility byte-equality test passes. 39 unit tests.
  - Day 6-7 (`6ea6fa5`): SizingConfig with content-hashed per-instrument caps, OrderIntent with enforced two-leg hedge invariants, position-aware sizer (open/flip/close/no-trade) with min-quantity suppression. Full lineage threading: cost_model_hash + sizing_config_hash on every intent. 65 unit tests.
  - **Cumulative A1 unit tests: 190 passing.**
  - Pure-function pipeline working end-to-end as a unit-tested chain: `list[FundingRate]` → `ExpectedFunding` → `SignalEvaluation` → `OrderIntent | None`. Same inputs → byte-equal outputs at every step.
  - Day 8 next: vertical smoke test — wire one synthetic OrderIntent through 0007 OMS → 0009 risk → PaperAdapter → 0005 journal → 0008 position snapshot. Recon step first to read the existing OMS code-path shape.
- **Engine A2 — Basis:** Not started. Engages after A1 clears canary.
- **Engine A3 — Cash-and-carry:** Deferred.

### Sleeve B (build-to-research)
- Phase P0. No constructions promoted to paper. No work this week.

### Build blockers
- None.

### Data integrity issues
- None.

### Paper-vs-live drift
- N/A — no engines in paper or canary yet.

### Unresolved risk exceptions
- None.

### Next gate status
- A1 P0 → P1 gate: paper run reproducible end-to-end on production code path. Expected to land at the end of week 4.

### Carry-forward debt
**0009 Round 4.5 — Replay/Risk Matrix Hardening** (non-blocking, post-signoff, no schema changes expected, no evaluator semantic changes unless a test exposes a defect; purpose is coverage expansion and adversarial confidence). Priority order:
1. Replay determinism stress (multi-CB, multi-limit)
2. Cross-environment isolation
3. CB × source_type full 16-cell matrix
4. Bucket D + cb_hard_stop combined
5. Cancel matrix × non-LIVE envs
6. Per-dimension exhaustive

### Capital deployed
- $0. Program in P0 across all engines.

