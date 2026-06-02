# A1 Funding-Rate Capture Probe — Specification v1

**Status:** Locked, pre-implementation. No code is written until this spec is committed.
**Author:** Wasseem Katt
**Date:** 2026-06-02
**Implements:** roadmap v2.2 §3.1.1 (Engine A1 — funding-rate capture); notes/edge_scoping.md v0.2 §5 (probe specification discipline)
**Related:** notes/section_a_probe_spec_v1.md (parallel spec for Section A — vol-event persistence; precedent for under-sample decision rule); docs/decisions/2026-05-28-vol-event-persistence-probe-outcome.md (Section A outcome, which established the discipline this spec inherits)
**Threshold parameter:** θ = 0.0200% per 8h. Immutable in v1; an alternate θ requires a new v2 spec. See §8.

This document specifies the v1 probe for Engine A1 — funding-rate capture on
Binance USDM-Futures perp / Binance spot leg-pairs. The structure tests
whether **expected positive funding above a pre-locked threshold predicts
realised positive funding cashflow net of execution and basis drift, over
fixed holding windows of 1, 3, and 7 funding intervals.**

The spec is locked end-to-end before any code is written. Discipline
inherited from Section A: pre-lock the spec, build the probe against the
locked spec, run, decide. No mid-execution parameter changes; no rescues by
spec amendment.

---

## §1. Measured object

**Net realised cashflow of a same-venue Binance long-spot / short-perp
BTC/ETH leg-pair, entered only when expected positive funding clears a
pre-locked threshold, held for 1 / 3 / 7 funding intervals, after both-leg
execution costs and realised funding payments, expressed in basis points
on deployed capital.**

This is the single number the probe attributes per event. Section §6.1
decomposes it into three explicit attribution lines (`gross_funding_bps`,
`basis_drift_bps`, `execution_cost_bps`) for diagnostic interpretation,
but the gate evaluation operates on net.

The object **deliberately excludes:**

- Directional P&L. Equal-notional hedge means price moves on one leg are
  offset by the other; if directional P&L shows up, the hedge is broken,
  not the edge.
- Funding-distribution analysis. Distribution-shape questions inform θ
  selection but are not what the probe measures.
- Execution-quality alpha. Better maker fills are a cost-model accuracy
  concern, not the measured object.
- Deployment assumptions. Capital scale, leg-pairs per week, simultaneous-
  position limits are §4 v0.2 filter questions, not measured here.

## §2. Universe

- **Instruments:** BTCUSDT and ETHUSDT.
- **Venue:** Binance, same-venue for both legs.
- **Leg structure:** long spot + short USDM perp, equal notional at entry.
- **No borrow.** Positive-funding capture only. Short-spot / borrow
  mechanics are explicitly out of scope for v1.

Other Binance pairs (e.g. SOLUSDT) are explicitly out of scope. Cross-venue
funding capture is explicitly out of scope. Perp-only directional positioning
is explicitly out of scope. v2 may expand any of these; v1 does not.

## §3. Event definition

### §3.1 Trigger

At time `T - ε` (just before each funding settlement at time `T`), evaluate
the most recently settled funding rate `f(T - 8h)`. If

```
f(T - 8h) ≥ θ
```

where `θ = 0.0002` (raw funding_rate, equivalent to 0.0200% per 8h,
immutable in v1 per §8), the event fires. Otherwise the event is FLAT
and no leg-pair is entered.

### §3.2 Threshold rationale (load-bearing)

The threshold is deliberately set **above Binance's observed 0.0100%
default-rate mass.** Funding observations at or below 0.0100% per 8h are
not treated as elevated-funding events for A1 v1. Binance's funding-rate
mechanism produces a large concentration of observations at exactly
0.0100%/8h (the formula's default when premium-index and interest-rate
components are within a band); thresholds at or below that level would
fire on the default state rather than on genuinely elevated funding.

The single value `θ = 0.0002` is applied symmetrically to BTCUSDT and
ETHUSDT. Per-instrument calibration is rejected for v1 because:

- BTC and ETH funding distributions on Binance are empirically similar
  (density above 0.0200% is ~6% for both, per the train-only density
  reconnaissance);
- per-instrument calibration introduces a fit step on train data and
  doubles the parameter surface;
- the hypothesis under test is structural ("Binance liquid-major funding
  capture"), not per-coin.

### §3.3 Direction

```
expected positive funding → long spot + short perp
otherwise                  → FLAT (no leg-pair entered)
```

Short-perp captures positive funding when the perp trades at a premium
to spot (the historical mode on BTCUSDT/ETHUSDT). Negative-funding capture
(short spot + long perp) is explicitly out of scope for v1, because it
requires short-spot borrow machinery and introduces a borrow-cost variable
the spec does not test.

### §3.4 Entry timing

```
T - ε    : signal evaluated using f(T-8h)
T        : funding settlement occurs (last funding payment received by
           the existing holders at this instant; we are not yet positioned)
T + δ    : entry leg-pair established at the open of the first executable
           bar after T (hourly bars; δ ≤ 1 hour)
```

Practically: entry price for both legs is the **open of the bar at time
`T + 1h`** (one hour after the funding settlement, matching the first
fully-formed bar). This is unambiguous, executable, no look-ahead.

### §3.5 Exit timing

For horizon `N ∈ {1, 3, 7}` funding intervals (= 8h, 24h, 56h):

```
exit price = open of the bar at time T + N×8h + 1h
```

Same convention as entry — first executable bar after the horizon end.
Holding window for funding-cashflow purposes is the half-open interval
`(T, T + N×8h]`. Funding payments occurring at instants in this interval
(with millisecond jitter tolerance per the interval-membership rule
established in Section A's funding-jitter fix) accrue to the leg-pair.

### §3.6 Equal-notional sizing

At entry, both legs are sized to equal notional in USDT:

```
spot_notional_usdt  = capital_deployed_usdt
perp_notional_usdt  = capital_deployed_usdt
spot_qty_btc        = capital_deployed_usdt / spot_entry_open
perp_qty_btc        = capital_deployed_usdt / perp_entry_open
```

`spot_qty_btc` and `perp_qty_btc` differ slightly because spot and perp
open prices may differ at entry (this is the entry basis). The leg-pair
is **dollar-notional flat**, not **quantity-flat**. Basis drift between
entry and exit is the P&L consequence of this choice and is attributed
separately per §6.1.

**Quantity mismatch between spot and perp is expected when their entry
prices differ; this is not a hedge error.** Dollar-notional flat is the
deliberate convention because A1 is a capital-deployment probe and gates
are evaluated in bps on deployed capital. Quantity-flat would tie the
perp position to the spot quantity (`perp_qty_btc = spot_qty_btc`) at
the cost of unequal capital between legs — a cleaner choice for hedging
an existing position, but the wrong choice for "deploy $X hedged."

## §4. Cost model

### §4.1 Execution cost (locked, immutable)

```
EXECUTION_COST_BPS = 15
```

Decomposed:

- Spot leg round-trip: **10 bps** (5 bps entry + 5 bps exit; taker
  assumption on Binance spot; covers fee + light slippage).
- Perp leg round-trip: **5 bps** (2.5 bps entry + 2.5 bps exit; maker
  assumption on Binance USDM perp; covers fee + minimal slippage).
- Total: **15 bps round-trip per leg-pair.**

This is constant per event. Horizon does not change cost (one entry + one
exit regardless of holding length). Symbol does not change cost.

The 15 bps is **immutable for v1.** If realised execution is worse than
this in deployment, that is a deployment-stage sensitivity question for
the canary follow-up, not a v1 probe redesign. The probe asks: *under a
realistic-but-not-pessimistic execution model, does the funding signal
survive?* It does not ask: *what is the worst execution this can tolerate?*

### §4.2 Funding cashflow

```
gross_funding_bps = (sum of funding_rate values during (T, T + N×8h])
                    × 10000
                    × sign convention (+ for short-perp receives)
```

For the locked long-spot / short-perp structure, the leg-pair **receives**
funding payments when funding rate is positive (sign = +1), and **pays**
when funding rate is negative (sign = -1). The per-event
`gross_funding_bps` may therefore be positive, zero, or negative, even
though the entry rule fires only on expected-positive funding.

Negative `gross_funding_bps` is interpreted as a **failure of funding
persistence**, not as an execution or basis-drift effect.

Funding-cashflow summation uses **interval-membership over (T, T + N×8h]**,
not exact-instant lookup against a predicted grid. This is the convention
established by Section A's commit `15a9d15` after the millisecond-jitter
defect; A1 inherits the convention as a hard requirement and the harness
must implement it the same way. Completeness guard: if any consecutive
funding-record gap that overlaps `(T, T + N×8h]` exceeds 12 hours, the
event's funding cashflow is undefined and the event is **skipped** with
reason `SKIP_FUNDING_GAP`.

### §4.3 Basis drift

```
basis_entry  = spot_open(T + 1h)   - perp_open(T + 1h)
basis_exit   = spot_open(T + N×8h + 1h) - perp_open(T + N×8h + 1h)
basis_drift_bps = (basis_exit - basis_entry) / spot_open(T + 1h) × 10000
```

`basis_drift_bps` is signed: positive if basis widens in favor of the
long-spot / short-perp structure (spot rises relative to perp, or perp
falls relative to spot), negative if it widens against. Per-event can be
either sign and is expected to average near zero over a sufficient sample
but to have material per-event variance.

### §4.4 Net P&L attribution

```
net_bps = gross_funding_bps + basis_drift_bps - execution_cost_bps
        = gross_funding_bps + basis_drift_bps - 15
```

This is the single number the gates evaluate. The three attribution lines
are reported separately per §6.1.

---

## §5. Statistical gate

### §5.1 Scope and pooling

The statistical gate is evaluated **per horizon.** There are three horizons —
1, 3, and 7 funding intervals (8h / 24h / 56h respectively) — each a distinct
holding decision. Each horizon is gated independently.

Within a horizon, **BTCUSDT and ETHUSDT events are pooled into a single
sample.** The hypothesis under test is "positive-funding capture on Binance
liquid-major USDM perp/spot leg-pairs," not a per-coin edge claim.
Per-symbol disaggregation is reported as diagnostic (§7.3) but not gated.

The probe passes overall if **≥1 horizon clears both the statistical gate
(§5) and the economic gate (§6).**

### §5.2 Train/OOS split

The sample is split 80/20 by **calendar time**, locked at spec-finalisation
time. The boundary is set once, never recalculated, never re-tuned during
probe execution.

- **Train window:** first 80% of calendar-time span from the first valid
  event to the last available funding observation in the fixture.
- **OOS window:** the remaining 20%.
- **OOS span:** end of OOS window minus start of OOS window, in days.

Events are assigned to train or OOS by **entry timestamp** (i.e. the time
`T + 1h` at which the leg-pair is established). The split point is
calendar-fixed; an event landing on either side is not reassigned.

### §5.3 Sample sufficiency

For a horizon to be eligible for statistical-gate evaluation, all the
following must hold:

| Metric                | Threshold | Reasoning                                                                 |
|-----------------------|-----------|---------------------------------------------------------------------------|
| Train events (pooled) | ≥ 100     | Matches Section A floor; matches v0.2 §5 minimum evidence requirement.    |
| OOS events (pooled)   | ≥ 30      | Matches Section A floor.                                                  |
| OOS span (days)       | ≥ 182     | Six calendar months minimum; regime-shift coverage.                       |

If any of these fail, the horizon's statistical gate status is
**`INSUFFICIENT_SAMPLE`**. The under-sample decision rule in §7.4 governs
interpretation.

### §5.4 Sharpe gates (only computed if §5.3 passes)

Per-event Sharpe is **unannualised**, computed on net basis points per
event:

```
sharpe = mean(net_bps_per_event) / sample_stdev(net_bps_per_event)
```

where:

- `net_bps_per_event` is defined in §4.4 (`net_bps`);
- `sample_stdev` uses the n−1 (Bessel-corrected) denominator;
- if `n < 2` or `sample_stdev == 0`, Sharpe is **undefined** and the
  horizon fails the statistical gate.

Unannualised is correct because events are irregular in time. Annualising
would assume a fixed event cadence A1 does not have.

| Sub-gate     | Threshold | Evaluated on      |
|--------------|-----------|-------------------|
| Train Sharpe | ≥ 2.0     | Train events only |
| OOS Sharpe   | ≥ 1.5     | OOS events only   |

Both must clear for the statistical gate to **PASS** at a horizon.

### §5.5 Statistical gate outcomes per horizon

- **`INSUFFICIENT_SAMPLE`** — §5.3 floors not all cleared. Sharpe gates
  not evaluated. Horizon cannot pass the probe.
- **`FAIL`** — §5.3 cleared; one or both of (train Sharpe, OOS Sharpe)
  below threshold.
- **`PASS`** — §5.3 cleared; both Sharpe sub-gates cleared.

---

## §6. Economic gate

### §6.1 Per-event P&L attribution

For each (event, horizon) pair, the per-event P&L is decomposed into
three explicit attribution lines reported in basis points on deployed
capital:

```
net_bps = gross_funding_bps + basis_drift_bps - execution_cost_bps
```

where:

- **`gross_funding_bps`** is the realised funding cashflow over the
  holding window (per §4.2), and may be positive, zero, or negative.
  Negative values indicate a failure of funding persistence.

- **`basis_drift_bps`** is the basis-drift P&L (per §4.3); may be either
  sign; expected near-zero on average with material per-event variance.

- **`execution_cost_bps`** is the constant 15 bps per event (per §4.1);
  always subtracted (positive value reduces `net_bps`).

The three lines are reported **separately** in the harness output for
every event. They are not opaque inputs to a single number. This separation
is load-bearing: it lets the economic gate evaluate `net_bps` (the answer
that matters for promotion) while letting the cost-coverage check (§6.3)
evaluate whether funding alone pays enough over explicit execution cost
(the answer that matters for *understanding* the edge).

### §6.2 Economic-gate metrics (computed per horizon, on pooled BTC+ETH)

If §5.3 sample sufficiency fails for the horizon, these metrics are
computed and reported as diagnostic but **not** evaluated as a formal
gate. Otherwise:

| Metric                    | Threshold | Definition                                                                                                                                                          |
|---------------------------|-----------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Mean net (bps)            | ≥ 20      | `mean(net_bps_per_event)` across all events in horizon (pooled).                                                                                                    |
| Median net (bps)          | > 0       | `median(net_bps_per_event)` across all events in horizon (pooled).                                                                                                  |
| Win rate                  | > 50%     | Fraction of events with `net_bps > 0`. (Events with `net_bps == 0` count as losses.)                                                                                |
| Cost coverage             | ≥ 2.5×    | See §6.3.                                                                                                                                                           |
| Final-90-day net (bps)    | > 0       | `mean(net_bps_per_event)` over events whose **entry timestamp** falls in the last 90 calendar days of the OOS span (regardless of OOS event count in that window). |

All five thresholds must hold for the economic gate to **PASS** at a
horizon. Any one failing yields **`FAIL`**.

The final-90-day calendar-based check guards against an edge that worked
historically but has decayed. Calendar (not event-count) basis is
deliberate: a quiet final 90 days may produce few events, but the
question is whether the edge **survives recent time**, not whether the
most recent cluster looks good. If the last 90 calendar days of OOS
produce zero events, the metric is **undefined** and the gate fails.

### §6.3 Cost coverage definition

```
cost_coverage = mean(gross_funding_bps) / mean(execution_cost_bps)
```

Denominator is the mean realised execution cost per event (which, under
the locked v1 cost model, equals 15 bps for every event). The numerator
is the mean realised funding cashflow across all entered events — which,
per §4.2, may include events with negative `gross_funding_bps` from
persistence failure.

If `mean(gross_funding_bps) ≤ 0`, cost coverage is reported as ≤ 0 and
the gate fails by construction. If the numerator is positive but
`< 2.5 × mean(execution_cost_bps)` = 37.5 bps, the gate fails on the
threshold.

**Basis drift is deliberately excluded from this metric.** The
cost-coverage check asks one specific question: *does the funding
cashflow the leg-pair captures, net of persistence failures, pay for the
explicit execution friction needed to deploy it?* That is a cleaner
question than "is net P&L positive after everything," which is what the
mean/median/win-rate gates already cover.

A horizon can have `cost_coverage ≥ 2.5×` and still fail the economic
gate on `mean_net_bps` if basis drift is severely adverse. This is the
intended behaviour.

### §6.4 Economic gate outcomes per horizon

- **`NOT_EVALUATED`** — §5.3 sample sufficiency failed; metrics reported
  as diagnostic only.
- **`FAIL`** — §5.3 cleared; one or more of the §6.2 thresholds breached.
- **`PASS`** — §5.3 cleared; all §6.2 thresholds clear.

---

## §7. Probe pass rule and reporting

### §7.1 Pass rule

The probe **passes** if at least one horizon has:

- statistical gate `PASS` (§5.5) **and**
- economic gate `PASS` (§6.4).

Otherwise the probe **fails** (or returns `DATA_LIMITED` per §7.4).

### §7.2 Required harness output

Per horizon, the harness reports:

- **statistical:** train events, OOS events, OOS span (days), train Sharpe
  (or `undefined`), OOS Sharpe (or `undefined`), status.
- **economic:** mean net (bps), median net (bps), win rate, cost coverage,
  final-90d mean net (bps), final-90d event count, status.
- **attribution summary:** pooled mean `gross_funding_bps`, mean
  `basis_drift_bps`, mean `execution_cost_bps` (separate; not collapsed
  into net).

### §7.3 Required diagnostics (not gated)

- **Per-symbol disaggregation** within each horizon: event count, mean
  net (bps), win rate. Reported but not gated; promotion is on the
  pooled hypothesis.
- **Skip-counter taxonomy:** events fired, events skipped for funding
  gap, events skipped for missing entry bar, events skipped for missing
  exit bar, events skipped for truncated horizon beyond fixture end.
  Matches Section A's skip-summary structure.
- **Data-quality suspect flag** if any skip class exceeds **10% of fired
  events.** This is intentionally higher than Section A's 5% threshold:
  A1's pipeline depends on four series (funding, spot, perp, funding-
  window alignment) where Section A's depended on one, so there are more
  ways to legitimately lose events without indicating pipeline corruption.

### §7.4 Pre-locked decision rule for under-sample outcomes

This probe adopts the same principle demonstrated during Section A:
economic observations from an insufficient-sample run may be recorded,
but they do not constitute a formal pass/fail verdict. Section A is
referenced as the precedent that established this principle; the rule
below is A1's own locked policy and stands independently of Section A's
spec.

**A1 under-sample rule (locked):**

- If a horizon's status is `INSUFFICIENT_SAMPLE` (§5.3), economic-gate
  metrics are computed and reported (per §6.2) but classified as
  `NOT_EVALUATED` for purposes of probe pass/fail.
- The horizon's outcome is **`DATA_LIMITED`** regardless of whether the
  under-sample economic numbers are favourable or unfavourable. They are
  directionally informative but never a formal verdict.
- A horizon is **eligible for re-run** once the data ceiling that
  limited it is lifted (e.g. additional months of funding / spot / perp
  data publish).

**Probe-level outcome under under-sample:**

- If at least one horizon clears §5.3, the probe is evaluated normally
  on that horizon. Under-sample horizons do not block the probe.
- If all three horizons are `INSUFFICIENT_SAMPLE`, the probe outcome is
  **`DATA_LIMITED`** overall. A §10 decision-log entry records the
  result, the data-ceiling cause, and explicit re-run conditions.
  Promotion is not authorised.

---

## §8. Immutable locks

These specifications are **locked at commit time** and may not be
modified during probe execution. Any change requires a new spec version
(v2), commit-replacing this document.

- **Universe:** BTCUSDT, ETHUSDT, Binance same-venue spot + USDM perp.
- **Leg structure:** long spot + short perp, equal notional at entry,
  positive-funding capture only.
- **Holding horizons:** 1, 3, 7 funding intervals (8h, 24h, 56h).
- **Entry / exit timing:** open of first bar after T / T+N×8h respectively.
- **Threshold θ:** **0.0200% per 8h** (raw `0.0002`). θ is **immutable
  in v1.** If sample sufficiency at this θ fails on any horizon, the
  outcome for that horizon is `DATA_LIMITED` and is recorded as such.
  An alternate θ requires a new v2 spec before any further execution.
  θ was set from the train-only density reconnaissance prior to spec
  commit; that calibration step is concluded.
- **Execution cost:** 15 bps round-trip per leg-pair, constant.
- **Train/OOS split:** 80/20 calendar-time, fixed at fixture-finalisation.
- **Statistical gate thresholds:** train events ≥ 100, OOS events ≥ 30,
  OOS span ≥ 182 days, train Sharpe ≥ 2.0, OOS Sharpe ≥ 1.5.
- **Economic gate thresholds:** mean net ≥ 20 bps, median net > 0,
  win rate > 50%, cost coverage ≥ 2.5×, final-90d net > 0.
- **Pass rule:** ≥ 1 horizon clearing both §5 and §6.
- **Data-quality suspect threshold:** 10% of fired events.
- **Funding cashflow summation:** interval-membership over
  `(T, T + N×8h]`, with consecutive-gap completeness check at 12h
  (Section A `15a9d15` convention).

---

## §9. Workflow before execution

1. **Commit this spec.** Document is final; no further mid-execution
   amendments.
2. **OOS density check.** Compute event density at θ = 0.0200% on the
   OOS window only (last 20% calendar split). Per §8, θ is immutable in
   v1: this check is diagnostic only — it tells the operator in advance
   whether the OOS-sample gate is likely to clear at this θ, so the
   `DATA_LIMITED` outcome (if it happens) is not a surprise. If OOS
   density at this θ produces a sample the operator considers
   unworkable, the response is to **not execute v1** and instead author
   a v2 spec with a different θ.
3. **Build the probe.** Same discipline as Section A: signal /
   sizing / attribution / gates / harness as a small number of named
   modules under `strategies/funding_capture/`. Test-driven.
4. **Run the probe** on a fixture containing **funding, perp klines, and
   spot klines** for both symbols. The Section A fixtures (e.g.
   `real_vol_event_fixture_v3.json`) contain funding and perp klines but
   **not** spot klines — `scripts/export_vol_event_fixture.py` was built
   for Section A and pulls funding + USDM perp only. A1 requires a new
   exporter (or an extension of the existing one) that additionally pulls
   Binance spot 1h klines for BTCUSDT and ETHUSDT. This is a build
   dependency for §9 step 3, not a parameter decision. The new exporter
   should follow the same cache-served-then-HTTP-fallback pattern as the
   existing one, against `artifacts/cache/binance_klines_1h_spot/` (or
   equivalent), and produce a fixture matching the same schema with an
   additional `spot_klines` field.
5. **Apply the locked decision rule** to the harness output. Record in
   `docs/decisions/YYYY-MM-DD-a1-funding-capture-probe-outcome.md`.
6. **`notes/edge_scoping.md`** updated with the outcome in the appropriate
   §3 sub-category (closed, killed, data-limited, or — if the probe
   passes — entry stays in §4 open space pending canary).

— end of v1 —
