# Sleeve B framework evolution — Q0 cluster-diversity sub-criterion

**Status:** Framework evolution memo — binding for candidate #5 onward
**Subordinate to:**
- `docs/strategies/sleeve_b_research_preregistration.md` (commit `fe909bb`) — master
- `docs/strategies/sleeve_b_framework_evolution_q0_data_viability.md` (commit `cb9d975`) — Q0 Data Viability Gate
- `docs/strategies/sleeve_b_framework_evolution_stage_a_gate_inheritance.md` (commit `39970f1`) — gate inheritance
**Date:** 2026-05-21
**Origin:** Sleeve B framework review (`docs/strategies/sleeve_b_framework_review_2026_05.md`, commit `7c10ca0`), §6.2

---

## 0. Scope and authority

This memo is a **subordinate framework evolution**, not an amendment.

- It does not modify the master Sleeve B pre-registration at commit `fe909bb`.
- It does not modify the Q0 Data Viability Gate memo at commit `cb9d975`.
- It does not modify the gate-inheritance memo at commit `39970f1`.
- It does not modify any candidate-specific pre-registration commit.
- It does not apply retroactively to candidates #1, #2, #3, or #4 — all closed under their own pre-registrations and prior framework state.
- It is binding for Sleeve B candidate selection from candidate #5 onward.

Where this memo is more restrictive than the master, the Q0 memo, or the gate-inheritance memo, this memo governs for future candidates. Where it is silent, those govern. The prior memos remain immutable.

This memo is itself subject to anti-cherry-pick discipline. Once committed, it is binding until a successor framework evolution memo is committed under the same discipline. No mid-candidate amendment, no threshold negotiation after a candidate has been classified.

---

## 1. Why this memo exists

The Sleeve B framework review (commit `7c10ca0`) synthesized the five-kill record and answered three diagnostic questions. Two of the three verdicts produced no recommended changes:

- **Verdict A1** (gates filter correctly) → no gate changes
- **Verdict C3** (premise too soon to assess) → continue Sleeve B as scoped

The third verdict was different:

- **Verdict B2** (specific blind spot identified) → one targeted change to Q0

This memo executes that one change.

The structural lesson from the review:

> **The candidate-generation process has been clustering on cross-sectional factor research within one universe construction. The cluster is rationalized by infrastructure investment, master pre-registration framing, and Q0 data constraints. It is not a generation error — every individual selection was defensible — but it is a systematic bias that the review surfaced. Future candidate selection should explicitly choose whether to draw from inside the cluster or outside it. Right now, selection drifts inside by default because the infrastructure makes it cheaper.**

This memo formalizes that lesson into one concrete change:

A new Q0 sub-criterion (Q0 §4) requires the candidate selection memo to classify the candidate against a defined family taxonomy, count the prior candidates in the same family, and — if the count is 3 or more — include a written justification for what new evidence this candidate is expected to surface that the prior cluster did not.

The sub-criterion is NOT a kill criterion. It is a forcing function on the selection narrative. A clustered candidate can still proceed, but the cluster choice becomes explicit and defended at selection time rather than drifted-into by default.

---

## 2. The Q0 cluster-diversity sub-criterion

### 2.1 Q0 §4 — Cluster diversity check

The Q0 screen (commit `cb9d975`) is extended with a new sub-criterion §4. The existing Q0 sub-criteria (§1 PIT availability, §2 vendor independence, §3 reconstruction feasibility, §3.5 survivorship and temporal stability per `39970f1`) are unchanged.

The new §4 reads:

> **Q0 §4 — Cluster diversity check.**
>
> Before pre-registration drafting, the candidate selection memo must:
>
> **(a)** Classify the candidate against the corpus by signal family, using the taxonomy in §3 below. Where the candidate spans multiple families, list the primary family first and the secondary in parentheses.
>
> **(b)** Note the count of prior candidates in the same primary family. The count is over the entire Sleeve B program (including killed candidates), not just within the current open window.
>
> **(b′) Cross-sectional super-family aggregation.** For candidates whose primary family is any cross-sectional factor sub-family (§3.1.2 return-based, §3.1.3 fundamental-ratio, §3.1.4 risk-adjusted), the count for §4(c) purposes is computed at the **super-family** level — i.e., the sum of priors across §3.1.2 + §3.1.3 + §3.1.4 — not at the sub-family level. The sub-family count is logged separately for descriptive purposes, but the super-family count is what determines whether §4(c) fires.
>
>     This aggregation rule applies *only* to the cross-sectional factor super-family because the cluster identified by framework review `7c10ca0` was located at that level (shared universe construction, shared rebalance cadence, shared long-short ranking pattern). For other families (§3.1.1, §3.1.5–§3.1.11), the count for §4(c) is the sub-family count as written in §4(b). Future framework evolutions may introduce additional super-family aggregations if and when other clusters emerge.
>
> **(c)** If 3 or more prior candidates exist in the relevant family (sub-family per §4(b), or super-family per §4(b′) when applicable), the selection memo must include a written justification for why this candidate is expected to surface evidence the prior cluster did not. The justification must be at least one paragraph and address what specifically would be different about this candidate's outcome — signal mechanism, parameter regime, universe construction, evaluation discipline, or other identifiable axis.
>
> If fewer than 3 prior candidates exist in the relevant family, the count is logged but no justification is required.
>
> The cluster-diversity check is NOT a kill criterion. A candidate cannot fail Q0 §4. The check is a forcing function on the selection memo, requiring the cluster choice to be explicit when the cluster is dense.

The threshold of 3 is chosen because:

- It triggers on the 4th candidate in any family (or super-family per §4(b′)), after the cluster has accumulated enough evidence to be informative about what the cluster is and is not producing.
- It does not retroactively pressure prior selections (none of which were drafted under this rule).
- For the program's current state (cross-sectional factor super-family has 4 members already), it ensures candidate #5 must address the cluster question if-and-only-if #5 stays inside the cross-sectional super-family — regardless of which sub-family it picks.

A lower threshold (2+) would have applied retroactively to candidate #3, which was already governed by the gate-inheritance correction at `39970f1`; relitigating that kill through a new lens is out of scope. A higher threshold (4+) would not trigger on #5 in either direction, defeating the purpose of installing the check now.

### 2.2 What the written justification must do

The written justification required by §4(c) is not a generic defense of the candidate. It is a specific answer to a specific question:

> **What evidence is this candidate expected to produce that the prior cluster has not?**

Acceptable patterns (illustrative, not exhaustive):

- "This candidate uses a different parameter regime (e.g., monthly rather than weekly rebalance) which addresses the specific window-sensitivity finding from candidate #4."
- "This candidate uses a different universe construction (e.g., top-50 rather than top-30, or non-frozen) which would surface evidence about whether the cluster's findings are universe-specific."
- "This candidate uses a different signal mechanism within the family (e.g., return-based rather than risk-adjusted) and would corroborate or contradict the finding from candidate #4 that pure momentum is weak on this universe."
- "This candidate's evaluation discipline differs in a specific identifiable way (e.g., monthly attribution rather than weekly, or fundamentals lookback rather than price-based)."

Unacceptable patterns:

- "This is a better implementation than prior candidates." (Improvement claims are inherent to every candidate and don't address the cluster question.)
- "We expect Sharpe to be higher." (Forward Sharpe claims are not evidence about what the candidate will surface.)
- "This is the most promising candidate in the family." (Relative ranking within the cluster doesn't address what's outside it.)

The justification is logged in the selection memo and is reviewable on the same audit-trail basis as Q0 §1-§3.5.

---

## 3. Candidate family taxonomy

The taxonomy below is the **initial** classification system. It is not locked for all time. Future framework-evolution memos may extend it. But for candidate #5 onward, every selection memo's §4(a) classification must use this taxonomy or explicitly propose a taxonomy extension.

### 3.1 Family definitions

**3.1.1 Inter-instrument relative-value.** Trading the spread between two related instruments (e.g., perp vs spot, two correlated assets, or one asset across venues). Prior candidates: A2 perp-vs-spot basis.

**3.1.2 Cross-sectional factor — return-based.** Ranking the universe by a return-derived score (raw returns, momentum, reversion). Long-short or long-only portfolio construction from the ranking. Prior candidates: xs-momentum.

**3.1.3 Cross-sectional factor — fundamental-ratio.** Ranking the universe by a fundamental ratio (fee-yield, revenue-per-token, treasury-ratio, similar). Prior candidates: fee-yield quality.

**3.1.4 Cross-sectional factor — risk-adjusted.** Ranking the universe by a return-divided-by-risk score (Sharpe-like, vol-scaled momentum, ratio-style constructions). Prior candidates: vol-scaled momentum #3, vol-scaled momentum #4.

**3.1.5 Time-series / trend.** Single-asset directional signals based on the asset's own historical price or volatility (trend-following, mean-reversion on individual price series, regime-switching on single-asset features). Prior candidates: none.

**3.1.6 Calendar / cyclical.** Signals anchored to time-of-day, day-of-week, weekend, or exchange-cycle phenomena (funding cycles, settlement windows, weekend effects). Prior candidates: none.

**3.1.7 Event-driven.** Signals triggered by discrete events (listings, delistings, hard forks, regulatory announcements, governance votes, major liquidations). Prior candidates: none.

**3.1.8 Microstructure.** Signals derived from order-book state, depth imbalance, queue position, or short-timescale liquidity dynamics. Prior candidates: none.

**3.1.9 Cross-venue arbitrage.** Trading price or basis differentials across venues other than the A2-specified perp-vs-spot pair. Prior candidates: none.

**3.1.10 Volatility carry / term-structure.** Signals derived from implied vs realized volatility, vol term structure, or vol-surface dynamics. Often infrastructure-blocked without options data. Prior candidates: none.

**3.1.11 Cross-asset / regime.** Signals using correlation, regime-state, or cross-asset relative behavior as the primary input (BTC-ETH correlation regime, dollar regime, risk-on/risk-off). Prior candidates: none.

**3.1.12 Other.** Candidates not classifiable under §3.1.1-§3.1.11 must propose a taxonomy extension in the selection memo.

### 3.2 Current family counts

For reference at the time of this memo's commit:

| Family | Count | Members |
|---|---|---|
| §3.1.1 Inter-instrument relative-value | 1 | A2 basis |
| §3.1.2 Cross-sectional factor — return-based | 1 | xs-momentum |
| §3.1.3 Cross-sectional factor — fundamental-ratio | 1 | fee-yield quality |
| §3.1.4 Cross-sectional factor — risk-adjusted | 2 | vol-scaled momentum #3, vol-scaled momentum #4 |
| §3.1.5-§3.1.11 | 0 each | — |

The cross-sectional factor super-family (§3.1.2 + §3.1.3 + §3.1.4) has 4 members. **A candidate #5 that proposes another cross-sectional factor (any of the three sub-families) will trigger the §4(c) written justification requirement.** A candidate #5 in any other family will not.

This is the intended behavior. The forcing function fires when-and-only-when selection would extend the cluster.

### 3.3 How to classify

Family assignment is the operator's call in the selection memo. The taxonomy is descriptive, not bureaucratic — a candidate that obviously belongs in §3.1.4 should not be relabeled as §3.1.5 to avoid the §4(c) requirement. Anti-cherry-pick discipline applies: classification is determined by the candidate's actual mechanism, not by the convenience of the count.

If a candidate genuinely spans two families, the primary is the one most descriptive of the *signal mechanism*, not the one most descriptive of the implementation. Example: a fundamental-ratio signal whose ranking is risk-adjusted is §3.1.3 (the signal is the ratio; risk-adjustment is an implementation choice).

If the operator is uncertain, the selection memo records both candidate classifications and the §4(c) requirement is triggered if **either** primary classification has 3+ priors. This rule prevents classification ambiguity from being a workaround.

---

## 4. What this evolution does NOT do

**It does NOT establish that clustered candidates should be discouraged.** The §4(c) requirement is a forcing function on selection narrative, not a discouragement. A clustered candidate with a strong §4(c) justification proceeds normally. The check ensures the cluster choice is explicit, not that it is rejected.

**It does NOT establish that diversifying signal family will improve clearance rate.** The framework review's verdict C3 explicitly says the strategic-question evidence base is too thin. This memo addresses §6.2 of the review (the cluster blind spot), not §6.3 or the strategic question.

**It does NOT modify any gate.** The Q0 sub-criterion §4 is not a gate. A candidate cannot fail Q0 §4. No threshold determines pass/fail. The check is purely narrative-forcing.

**It does NOT modify Stage A or Stage B sub-gates.** F1, F3, B3 gates remain calibrated as per current pre-registration practice. The framework review's verdict A1 explicitly recommends against gate changes; this memo honors that.

**It does NOT lock the family taxonomy.** §3.1 is the initial taxonomy. Future candidates may propose extensions per §3.1.12. The taxonomy evolves; family assignments do not become unfalsifiable.

**It does NOT retroactively reassess prior candidates.** A2, xs-momentum, quality, #3, and #4 were all selected and killed under prior framework state. Their kill actions remain binding. This memo's effect is prospective from candidate #5.

**It does NOT amend the master Sleeve B pre-registration at `fe909bb`.** That pre-registration's framing (market-neutral long/short) remains as-is. The cluster check operates within that framing, not against it.

---

## 5. Interaction with prior framework evolutions

This memo is the third Sleeve B framework evolution. The accumulated framework state for candidate #5 selection is:

| Memo | Commit | Adds |
|---|---|---|
| Master pre-registration | `fe909bb` | Universe, master gates, anti-cherry-pick discipline, budget |
| Q0 Data Viability | `cb9d975` | Q0 §1-§3 (PIT, vendor, reconstruction), §3.5 (survivorship) |
| Gate inheritance | `39970f1` | A2 spec rewrite, per-candidate verification, Q0 §3.5 update |
| **Cluster diversity (this memo)** | this commit | **Q0 §4 (cluster check, family taxonomy)** |

All four are binding for candidate #5. None contradict each other. The cluster-diversity check is the only one that operates *before* metric selection within a family — Q0 §1-§3.5 ask "can this candidate be evaluated?" Q0 §4 asks "should this candidate be selected from this family rather than another?"

A candidate that passes Q0 §1-§3.5 but triggers Q0 §4(c) is a fully evaluable candidate whose family choice requires explicit defense. A candidate that fails Q0 §1-§3 is not evaluable and does not reach §4 at all.

---

## 6. What changes about candidate #5 selection specifically

The candidate #5 selection memo, drafted in a separate session after this memo commits, must include the following sections:

**6.1** Q0 §1 (PIT availability) — as currently required.

**6.2** Q0 §2 (vendor independence) — as currently required.

**6.3** Q0 §3 (reconstruction feasibility) — as currently required.

**6.4** Q0 §3.5 (survivorship and temporal stability) — as currently required per `39970f1`.

**6.5** Q0 §4(a) — family classification using §3.1 of this memo. (NEW.)

**6.6** Q0 §4(b) — sub-family count of prior candidates in the same primary family. (NEW.)

**6.6′** Q0 §4(b′) — super-family count, applicable only when the primary family is §3.1.2, §3.1.3, or §3.1.4 (cross-sectional factor sub-families). The super-family count is the sum of priors across §3.1.2 + §3.1.3 + §3.1.4. (NEW.)

**6.7** Q0 §4(c) — if the relevant count (sub-family per §6.6, or super-family per §6.6′ when applicable) is ≥ 3, written justification for what new evidence this candidate will surface. (NEW, conditional.)

**6.8** Q1 → Q2 → Q3 as currently required.

The cluster check adds at most four lines of routine output (§4(a) classification, §4(b) sub-family count, §4(b′) super-family count where applicable, §4(c) justification) and one paragraph of justification *only when the count triggers*. The marginal cost is small. The forcing function it creates is large.

If candidate #5 stays in the cross-sectional factor super-family (any of §3.1.2 / §3.1.3 / §3.1.4), the super-family count is 4 (regardless of which sub-family #5 picks), §4(b′) applies, and §4(c) fires. If candidate #5 selects from any other family, both sub-family and super-family counts are 0 or 1 and no §4(c) requirement applies.

---

## 7. Budget impact

The cluster-diversity check consumes operator selection time, not Sleeve B research budget. Q0 is pre-selection; it does not draw against the 41-day candidate budget. The §4 sub-criterion adds approximately 10-15 minutes of operator drafting time to the selection memo when triggered, and approximately 2 minutes (the classification entry alone) when not triggered.

No engineering work, no infrastructure build, no data acquisition is required by this memo. It is a discipline addition, not a capability addition.

---

## 8. Implications for the cumulative Q0 screen

After this memo, Q0 consists of:

```
Q0 §1   — Point-in-time data availability
Q0 §2   — Vendor independence (operator-approved acquisition only)
Q0 §3   — Reconstruction feasibility under available infrastructure
Q0 §3.5 — Survivorship and temporal stability under candidate eligibility rule
Q0 §4   — Cluster-diversity check (family classification + count + justification)
```

§1, §2, §3, §3.5 are pass/fail screens that can decline a candidate at Q0 without pre-registration. §4 is a narrative-forcing sub-criterion that does not decline candidates.

The Q0 screen as a whole now operates on three distinct concerns:

1. **Can this candidate be evaluated?** (§1, §2, §3)
2. **Is the candidate's universe-and-eligibility construction internally consistent?** (§3.5)
3. **Is the candidate's family choice explicit or drifted-into?** (§4)

The three concerns are independent. A candidate can fail #1 without affecting #2 or #3. A candidate can trigger #3 without affecting #1 or #2.

---

## 9. References

- Master Sleeve B pre-registration: `docs/strategies/sleeve_b_research_preregistration.md` (commit `fe909bb`)
- Q0 Data Viability Gate memo: `docs/strategies/sleeve_b_framework_evolution_q0_data_viability.md` (commit `cb9d975`)
- Gate-inheritance memo: `docs/strategies/sleeve_b_framework_evolution_stage_a_gate_inheritance.md` (commit `39970f1`)
- Sleeve B framework review (this memo's analytical basis): `docs/strategies/sleeve_b_framework_review_2026_05.md` (commit `7c10ca0`)
- Prior kill actions (corpus the cluster framing draws from):
  - A2 basis: `docs/strategies/a2_kill_action.md` (commit `924a930`)
  - xs-momentum: `docs/strategies/sleeve_b_xs_momentum_kill_action.md` (commit `f3e078e`)
  - Quality: `docs/strategies/sleeve_b_quality_kill_action.md` (commit `bf642d1`)
  - Candidate #3: `docs/strategies/sleeve_b_candidate_3_kill_action.md` (commit `bf0a23e`)
  - Candidate #4: `docs/strategies/sleeve_b_candidate_4_kill_action.md` (commit `5619d09`)
- Master roadmap §10 (operator authority): governing document

---

*Framework evolution memo for Sleeve B Q0 — cluster-diversity sub-criterion. Binding for candidate #5 onward. Adds Q0 §4 (family classification + count + justification when count ≥ 3). Not a kill criterion; a narrative-forcing sub-criterion. Initial family taxonomy in §3.1, extensible by future framework evolutions. Analytical basis: framework review at `7c10ca0`, verdict B2.*
