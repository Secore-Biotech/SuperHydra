# Day 21 design brief — A2 perp-vs-spot basis engine

Strategic design memo opening the A2 implementation arc. Successor to
Day 20.7 (`a1_reclassification_a2_advancement.md`) which advanced A2
to the next Sleeve A implementation candidate.

**Day 21 is docs-only. No code. Code starts Day 22 after this brief
has reviewer-locked design decisions in place.**

---

## Why A2 may succeed where A1 did not

A1 funding-rate capture depended on **sustained funding persistence
after volatility discounting**. Its signal evaluator computed
`forecast = mean(12) - 1.0 × stdev(12)` and required this forecast to
clear ~7.7 bps. The Day 20.6 structural finding showed that this
formulation penalizes the very regimes that produce funding edge:
high-mean SOL windows are characterized by high variance, and the
stdev penalty suppressed the forecast even when individual prints
were extreme (e.g. Sep 2021 SOL with 12.15 bps peak realized funding
yielded only a 4.24 bps rolling-12 forecast).

A2 targets a **statistically opposite signal shape**: transient
dislocations in realized basis. Where A1 needed *persistence* of
elevated funding, A2 fires on *deviation* of current basis from its
recent mean.

This changes the statistical shape of the signal:

| Property | A1 funding-rate capture | A2 basis dislocation |
| --- | --- | --- |
| Signal type | persistence-based | deviation-based |
| Edge metric | sustained mean over rolling window | current value's distance from recent mean |
| Stdev penalty | suppresses signal (variance reduces edge) | provides scale (variance defines the unit of deviation) |
| Best regime | sustained one-sided funding pressure | volatile periods with sharp dislocations |
| Worst regime | volatile periods (Day 20.6 finding) | calm periods with no dislocations |

A2 benefits from temporary deviations whereas A1 required persistence.
This is not a guarantee that A2 will produce more fires than A1; it
is a structural reason to expect A2's signal-vs-regime relationship
to differ qualitatively from A1's.

The Day 20.6 finding does NOT predict A2's outcome. It only predicts
that A2's outcome will not be the same kind of negative finding for
the same kind of structural reason.

---

## 1. What A2 actually trades

When perp price > spot price by enough basis points, the perp is
trading at a premium. The strategy:

- **Short the perp** (collect the premium as basis converges down)
- **Long the spot** (hedge directional exposure)

When perp < spot by enough basis points (perp at discount):

- **Long the perp** (gain as basis converges up)
- **Short the spot** (hedge — typically via spot borrow on a margin-
  enabled exchange, which adds operational complexity)

The strategy holds until basis converges (within transaction-cost
threshold), at which point both legs are closed. A2 captures the
convergence as risk-free spread, minus round-trip costs on two legs
across two markets.

A2 is structurally different from A1:

- **A1 trades the funding rate** (the mechanism that forces basis
  toward zero over time)
- **A2 trades the basis itself** (the spread that the funding rate
  is trying to close)

They are related — sustained funding causes basis to compress, and
extreme basis triggers funding adjustments — but they are not the
same signal and they fire under different conditions.

---

## 2. Reviewer-locked design decisions

### 21.1 — Signal source: realized basis

**Locked: realized basis snapshot from perp and spot mark prices.**

The runner samples `basis_bps = (perp_mark - spot_mark) / spot_mark
× 10000` at each tick, builds a rolling window, and evaluates the
signal at signal-eval moments.

Rejected alternatives:
- Funding-implied basis (basis ≈ funding × time_to_settlement):
  inherits A1's regime-sensitivity. A2 should avoid that dependency.
- Combined (both required): doubles calibration surface for marginal
  robustness gain.

### 21.2 — Threshold formulation: z-score / percentile-based

**Locked: fire when current basis z-score over rolling window N
exceeds threshold Z.**

```
z = (current_basis - mean(window_N)) / stdev(window_N)
fire if |z| > Z_threshold
```

Direction follows the sign of z:

- `z > Z_threshold` (positive): basis spike up → perp at premium →
  short perp + long spot
- `z < -Z_threshold` (negative): basis spike down → perp at discount →
  long perp + short spot

This addresses Day 20.6's structural finding directly:

| Statistical property | A1 forecast formula | A2 z-score formula |
| --- | --- | --- |
| Effect of high variance | reduces forecast → less likely to fire | enlarges the unit of measurement; current value still needs to deviate by Z standard deviations |
| Effect of high mean | raises forecast → more likely to fire | irrelevant (z-score is mean-centered) |
| Effect of high spike | smoothed into mean over window | directly reflected in z-score |

Calibration parameters reserved for Day 22 implementation:
- Window size N (open: 12 intervals? 24? regime-specific?)
- Z threshold (open: z > 2.0? z > 2.5? cost-derived?)
- Cost-threshold integration: signal must clear z-threshold AND
  basis-distance must exceed round-trip cost

### 21.3 — Instrument scope: BTC + SOL dual scope (reviewer amendment)

**Locked: A2 initially supports BTCUSDT and SOLUSDT equally. Empirical
results determine which becomes the primary deployment candidate.**

Original recommendation was BTC-primary on the strategic argument
that A1 was structurally locked out of BTC (1 bp funding cap, Day
17c finding) while A2's basis dynamics are not funding-rate-capped.
This is a strong argument but the reviewer correctly noted that all
empirical calibration work to date is SOL-centered. Making BTC
primary before any A2 evidence exists would replace one unvalidated
assumption with another.

Dual scope from Day 21 design forward:

- **BTCUSDT**: A1 was structurally untradeable (cap-bound). A2's
  basis is not cap-bound. The strategic case is strong but unproven.
- **SOLUSDT**: existing slippage tier (`binance_vip5_alt_v1`) covers
  the perp leg. Empirical A2 evidence comparable to A1's six-window
  body of evidence.

Empirical sweep across both instruments determines the primary deploy
target. The infrastructure should support both equally; the deploy
decision is data-driven.

### 21.4 — Capital co-deployment with A1: fully separate

**Locked: A1 and A2 use different registry accounts and different
capital allocations.**

A1 remains in research classification per Day 20.7 — it is not
actually trading capital. If A1 ever advances to paper, the shared-
account question reopens. For Day 21+ implementation purposes, A2
operates on:

- Separate strategy registry entry (`a2_basis_research`)
- Separate portfolio code (`a2_basis_portfolio`)
- Separate account code (`a2_basis_account`)
- Independent capital allocation

This makes the firewall trivial: A2's paper.fills rows never share an
account_id with A1's paper.fills rows; aggregation, drawdown, and
risk tracking are naturally separated. Cross-strategy operational
concerns (allocator, NAV reconciliation, cross-strategy risk caps)
are deferred until at least one of A1/A2 reaches a phase where they
matter.

### 21.5 — A2 canary semantics: two paper.fills rows per intent

**Locked: each A2 intent produces two paper.fills rows (one per leg),
sharing an intent_uuid in metadata. Single venue (Binance) initially.
No schema migration required.**

A2 is two-legged: every fire produces an order on the perp venue AND
an order on the spot venue. The Day 20.1 paper.fills schema is
single-leg by design (one row = one order = one fill hypothesis).
Two paper.fills rows per A2 intent fits naturally without schema
changes:

| Field | Perp-leg row | Spot-leg row |
| --- | --- | --- |
| `paper_fill_uuid` | deterministic UUID for perp leg | deterministic UUID for spot leg |
| `instrument_id` | perp instrument (e.g. BTCUSDT perp) | spot instrument (e.g. BTCUSDT spot) |
| `side` | "sell" for short perp; "buy" for long perp | opposite of perp side |
| `metadata.a2_intent_uuid` | shared parent UUID for joining | same shared parent UUID |
| `metadata.a2_leg` | "perp" | "spot" |
| `metadata.a2_pair_uuid` | same | same |

This lets per-leg slippage be observed independently (which is the
honest measurement: spot and perp slippage differ structurally) while
the round-trip cost is reconstructible by joining on `a2_intent_uuid`.

The Day 20.2 aggregator already filters by `instrument_id`, so it
naturally produces separate slippage stats per leg without any
change. Cross-leg analysis would need an additional Day 22+
aggregator (out of scope here).

**Operational consequence: registry.instruments needs a spot
instrument record for each A2-traded symbol.** Day 22 implementation
will add `BTCUSDT_SPOT` and `SOLUSDT_SPOT` as registry instruments
(with `instrument_type='spot'`, or whatever the schema's enum allows).
This is a registry bootstrap detail, not a schema migration.

---

## 3. Substrate inheritance from Days 17-20

Per Day 20.7's carry-forward table, A2 reuses most of A1's substrate.
The new work for A2:

| Component | Status |
| --- | --- |
| Cost model schema | reused as-is |
| **Cost profile for A2 (basis-trade slippage)** | **NEW** — Day 22 work |
| **Spot-leg slippage tier** | **NEW** — Day 22 work (existing tiers are perp-only) |
| Signal evaluator (z-score) | NEW — Day 23 work |
| Forecast / window stats infrastructure | A1's `expected_next_funding` doesn't apply; A2 needs different stats math |
| Profile selector pattern | reused — A2 gets its own `select_research_profile_for_a2` |
| Profile selector firewall | reused — same `_research_` infix discipline |
| Replay observation machinery | reused as-is — A2 calls `replay_intents()` per leg |
| paper.fills writer | reused as-is — A2 just writes two rows per intent |
| Slippage calibration aggregator | reused as-is — per-leg `instrument_id` filtering |
| Runner composition pattern | reused — A2 runner mirrors A1 runner shape |
| Operator harness pattern | reused — A2 harness mirrors A1 harness CLI |

**Estimated A2 infrastructure cost: 30-35% of A1's**, consistent
with the Day 20.7 estimate. The cost model and signal evaluator are
new economic logic; everything else is composition over existing
machinery.

---

## 4. Estimated commit sequence

Mirroring Day 20's substructure for A2:

| Day | What | Status |
| --- | --- | --- |
| **21** | This design brief (docs-only) | **LANDS THIS COMMIT** |
| 22 | A2 cost model + spot-leg slippage tier calibration | Approved-pending |
| 23 | A2 signal evaluator (z-score formulation) + cost-threshold integration | Approved-pending |
| 24 | A2 paper-research runner (composition mirror of Day 20.4) | Approved-pending |
| 25 | A2 operator harness (mirror of Day 20.5) | Approved-pending |
| 26+ | Live data wiring (perp+spot tick observation) and sweeps | Open scope |

Estimated total: 5-7 commits. Each commit goes through the same
scope-locking discipline that produced Day 20.

---

## 5. Out of scope for Day 21

- **No code in Day 21 itself.** Memo only.
- **No A1 changes.** A1 stays exactly as it is per Day 20.7.
- **No schema migrations.** A2 uses existing `paper.fills` and
  `registry.instruments`.
- **No multi-venue.** Single-venue (Binance perp + Binance spot)
  initially. Cross-venue A2 (e.g. Binance perp + Coinbase spot) is
  deferred indefinitely.
- **No allocator integration.** A2 runs as a research-classified
  engine alongside A1; cross-strategy capital scheduling is out of
  scope until at least one engine reaches paper.
- **No live trading.** A2's first execution surface is PAPER_RESEARCH,
  not paper-canary.
- **No funding-implied basis.** Rejected at 21.1. The signal is
  realized basis only.
- **No `mean - k*stdev` formulation.** Rejected at 21.2 per Day 20.6
  structural finding.

---

## 6. Cross-references

- Day 17b memo: A1 cost-profile selector (pattern A2 reuses)
- Day 17c memo: BTCUSDT structural no-trade (A1-specific; doesn't bind A2)
- Day 19a memo: SOL slippage calibration (perp leg; A2 spot leg is new work)
- Day 19c.3 memo: Roll's effective-spread (methodology may apply to spot leg)
- Day 20.1 commit (`9193b65`): `paper.fills` writer (A2 writes here)
- Day 20.2 commit (`b2b17bc`): slippage calibration aggregator (A2 uses)
- Day 20.3a commit (`d9fd108`): replay observation machinery (A2 uses)
- Day 20.4 commit (`fd9bea7`): A1 runner composition shape (A2 mirrors)
- Day 20.5 commit (`08cd109`): operator harness pattern (A2 mirrors)
- Day 20.6 commit (`87d121e`): structural threshold-formulation finding (motivates A2 z-score choice)
- Day 20.7 commit (`6b410a9`): A1 reclassification / A2 advancement (precedes this memo)

---

## 7. Reviewer-locked status

| Item | Status |
| --- | --- |
| Signal source | realized basis (perp_mark - spot_mark) |
| Threshold formulation | z-score over rolling window |
| Instrument scope | BTCUSDT + SOLUSDT dual scope (no primary) |
| Capital co-deployment | fully separate accounts from A1 |
| Canary semantics | 2 paper.fills rows per intent, single venue, shared a2_intent_uuid metadata |
| Day 21 deliverable | this memo (docs-only) |
| Day 22 opener | cost model + spot-leg slippage tier |
| Schema migrations | none required through at least Day 25 |
| Multi-venue | deferred indefinitely |
| Live trading | out of scope; PAPER_RESEARCH only |

Day 21 closes here as the design brief. Day 22 opens with the cost
model and spot-leg slippage tier calibration — the first piece of
new economic infrastructure A2 requires.
