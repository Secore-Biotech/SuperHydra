# Risk Standard v1.0 — Family-Capital Qualification

**Status:** Locked policy. Pre-registered before any candidate is evaluated against it. Operator decision, not a research finding — these numbers define what "good enough for family capital" means, and they bind every future candidate.
**Author:** Wasseem Katt
**Date:** 2026-06-03
**Purpose:** Convert the implicit gates that the SuperHydra direction map applied case-by-case into one explicit, pre-registered standard, so that no future result is negotiated after the fact. A candidate either clears this standard or it does not. The standard exists *before* the next candidate so the candidate cannot move it.
**Relationship to the map:** `direction_map.md` records what was tested and why each direction closed. This document records the bar each would have had to clear. Together they make "search exhausted" a precise statement — "exhausted *under this standard*" — rather than a vibe.

---

## 1. Core thresholds

A **core engine** (eligible for the majority of family capital) must clear ALL of:

| Metric | Threshold | Measurement frame |
|---|---|---|
| Sharpe ratio | ≥ 1.5 | **Net** of realistic operator-tier costs (fees, slippage, funding); **out-of-sample**; on a **point-in-time universe** (no survivorship bias); over the OOS window in §3 |
| Maximum drawdown | ≤ 20% | Peak-to-trough on the net OOS equity curve, same window |
| Parameter sensitivity | ≤ 0.30 | The canonical sensitivity metric defined in §4 |

All three are **necessary**. None alone is sufficient (see §5, review zone).

## 2. Experimental thresholds and containment

An **experimental sleeve** runs a looser sensitivity bar in exchange for a hard capital cap:

| Metric | Experimental threshold |
|---|---|
| Sharpe | ≥ 1.5 (same as core) |
| Maximum drawdown | ≤ 20% (same as core) |
| Parameter sensitivity | ≤ 0.50 (looser than core's 0.30) |

**Containment (binding, or the looser tier becomes a bypass):**

- **Total experimental allocation ≤ 10% of total capital**, across all experimental sleeves combined. This is a hard cap, not per-sleeve.
- **No grandfathering.** An experimental sleeve cannot become core by performing well live. Promotion experimental → core requires a **fresh evaluation against the full core standard**, including re-testing parameter sensitivity at ≤ 0.30. "It worked live so we'll ignore sensitivity" is explicitly disallowed.
- **The looser sensitivity bar (0.50) is the *only* relaxation.** Sharpe and drawdown are identical to core. Experimental status buys a higher tolerance for parameter-dependence at small capital, nothing else.
- A candidate may only be labeled experimental *before* evaluation, as a declared capital-tier choice — not relabeled experimental after missing the core sensitivity bar, which would be result-driven gate-shopping.

## 3. Measurement window

- **Minimum OOS window: 24 months.** Below this, crypto results are too regime-specific to trust — 24 months captures at least one meaningful regime transition.
- **Preferred OOS window: 36 months.** Ideal, but not a hard requirement (a hard 36 would eliminate otherwise-valid candidates on data availability alone).
- A candidate with < 24 months OOS is **not evaluable** under this standard — it is data-limited, not pass or fail (cf. Section A: insufficient sample is a third state, not a kill).

## 4. Canonical parameter-sensitivity metric

"Parameter sensitivity ≤ X" is only comparable across candidates if it is the **same computation** every time. The canonical metric is inherited from the F1.4 window-sensitivity gate already calibrated in the Sleeve B framework (the metric that killed candidate #4 at 0.711):

> Over rolling windows (≈9 weekly samples per window, ≈63 days), compute stdev/mean of the strategy's primary parameterized quantity per window; take the median across windows per asset; then the median across assets. A candidate-specific parameter (lookback length, threshold) is perturbed across its plausible range; the metric captures how much the result moves.

If a candidate's primary parameter is not a lookback window, the operator must define the analogous perturbation **before** evaluation and record it — but the metric family (median-of-window-dispersion under parameter perturbation) is fixed. A bespoke sensitivity definition invented after seeing results is disallowed for the same reason as §2's relabeling.

## 5. Review zone — passing is necessary, not sufficient

Clearing all thresholds is required but does **not** auto-promote. A candidate that clears every threshold *marginally* is not the same as one that clears comfortably:

> **Sharpe 1.50 / DD 19.9% / sensitivity 0.30** (all barely passing) is not **Sharpe 2.4 / DD 10% / sensitivity 0.12** (all comfortable). Both "pass." One is robust; one is at the cliff edge.

**Review-zone rule:** any candidate within **10% of any gate** enters mandatory manual review before promotion — neither auto-rejected nor auto-promoted. For the core thresholds, the review zone is:

| Metric | Review zone (manual review required) |
|---|---|
| Sharpe | < 1.65 |
| Maximum drawdown | > 18% |
| Parameter sensitivity | > 0.27 |

A candidate in the review zone on any axis requires a written promotion rationale examining *why* it sits near the boundary and whether the proximity reflects genuine marginal edge or hidden fragility. This closes the boundary ambiguity: the gate is not a single sharp line that a 1.47 narrowly misses and a 1.51 narrowly clears with no scrutiny — the neighborhood of every line is a review region.

## 6. What this standard makes precise

Applied retroactively to the closed directions, the standard explains *why* each closed, in one vocabulary:

- **Sleeve B #1 (xs-momentum):** DD 25.92% > 20% (gate fail) AND survivorship-biased universe (violates §1 PIT-clean measurement frame). Fails on two independent grounds.
- **Sleeve B #4 (vol-scaled momentum v2):** parameter sensitivity 0.711 > 0.30 core (and > 0.50 experimental). Fails the §4 metric outright — not a core/experimental question, fragile under both.
- **Section A:** < required OOS sample → not evaluable (§3 third state), consistent with its terminal data-limited verdict.
- **A1 / basis / funding family:** never reached a sample-sufficient §1 evaluation, or failed economics upstream of it.

The standard does not reopen any of these. It records that they failed a bar that is now explicit and defensible, not an inherited research framework.

## 7. The fork this standard defines

With the standard locked, "search exhausted under the current envelope" becomes a precise, defensible statement: **no signal in the explored space cleared this bar.** The bar is not excessively strict — 20% DD, 1.5 Sharpe, 0.30 sensitivity are reasonable family-capital numbers, not institutional-grade ones. So the conclusion is the strong form: the search succeeded and found nothing meeting the required standard, which is different from "we couldn't find anything."

The remaining forks are therefore:

1. **Generate clean constituents** that clear this standard — a signal-research program (larger envelope than the current one).
2. **A structurally new economic mechanism** outside the exhausted funding/basis/momentum/factor families.
3. **Accept completion** under this envelope-and-standard and decide what the capital does instead.

This standard does **not** include a fourth fork of "loosen the gates," because the gates were just set deliberately, cold, and judged reasonable. Any future change to these numbers must be made *before* looking at a candidate, with a written rationale, and recorded as Risk Standard v1.1 — never as a result-driven rescue of a candidate that missed v1.0.

## 8. Amendment rule

These numbers are locked as v1.0. They may be changed only by a deliberate, pre-registered revision (v1.1, v1.2, …) made **before** evaluating the candidate that would benefit, with a written rationale for the change. There is no path by which a candidate that missed the standard triggers a loosening that then admits it. That path is post-hoc fitting and is the exact failure this entire document exists to prevent.

— end —
