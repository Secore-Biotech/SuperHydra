# Combination-Portfolio Screen — Sleeve B rescue-by-assembly

**Status:** Final — screen, not a spec. Closes the "combine the surviving Sleeve B signals" direction. Verdict: **survives §6 novelty, FAILS eligibility.** No probe, no code.
**Author:** Wasseem Katt
**Date:** 2026-06-03
**Question:** The direction map killed Sleeve B candidates as *individual signals*. Does a *market-neutral portfolio* of those signals — proper sizing, fixed weights, fixed rebalance — clear the gates the constituents failed individually? This is the "family-office version of a multi-signal market-neutral book" hypothesis: 3–5 signals, weekly rebalance, single venue — explicitly NOT a thousand-factor pipeline.
**Inputs:** `sleeve_b_xs_momentum_result.md`, `sleeve_b_candidate_4_{f1,f3,stage_a}_verdict.md`, `sleeve_b_candidate_{2,3,5}_kill_action.md`, `direction_map.md` (`3264ae7`).

---

## 1. Eligibility — which killed signals can be combination constituents?

Portfolio construction reduces **diversifiable risk** — concentration, correlation, volatility, drawdown — by combining decorrelated signals. It does **not** repair upstream defects in a constituent: a biased signal stays biased in a portfolio, a fragile signal stays fragile, a signal that was never validly computed cannot be weighted. So a constituent is eligible only if it died from **diversifiable risk while carrying clean, real edge.** Reviewing the corpus against that bar:

| Candidate | Failure class | Clean surviving signal? | Eligible? |
|---|---|---|---|
| #1 xs-momentum | Drawdown gate (25.92% > 25%); Sharpe 1.381 cleared the research floor | **No — survivorship bias by construction.** The result memo states the universe is top-30 ADV *as of 2026-04-15 applied retroactively* over a 36-month OOS window; assets that failed by 2026 are excluded. The 1.381 answers "would the 2026 survivors have shown momentum historically," not the tradeable question. The edge is partly look-ahead artifact. | **No** — bias is upstream; a portfolio inherits it |
| #2 fee-yield quality | Data governance — point-in-time fee data structurally unavailable | No signal could be cleanly built | **No** — the data to construct the constituent does not exist |
| #3 vol-scaled momentum v1 | Stage A construction (frozen-universe vs A2 temporal-stability) | Never validly computed | **No** — cannot weight a signal that was never validly produced |
| #4 vol-scaled momentum v2 | F1.4 window-sensitivity (0.711 > 0.30); cleared A1/A2/A4/A5 and the full F3 family clean | **Real signal, clean attribution — but parameter-fragile.** F3.3 confirms returns are genuine momentum, not low-vol carry. F1.4 confirms the edge swings hard with lookback choice. | **No** — fragility is upstream; diversification reduces risk, not parameter-dependence |
| #5 regime detector | Governance collapse — six artifacts, zero engineering | Never built | **No** — no signal exists |

**Eligible-clean set: empty.** The two candidates with any surviving signal (#1, #4) carry defects — survivorship bias and parameter fragility respectively — that are **upstream of portfolio construction and inherited by any portfolio that includes them.** The other three never produced a validated signal at all.

## 2. The fixed portfolio object (cannot be specified)

A combination screen requires a pre-locked object: exact constituents, exact weights, exact rebalance rule, fixed risk model — no iterative assembly, no adding a factor after seeing results (that path is the immunization the gate exists to block). But the object cannot be specified, because **the constituent set is empty.** A portfolio needs ≥2–3 decorrelated *clean* signals for the diversification mechanism to operate; the corpus offers zero. There is nothing to assemble.

## 3. §6 novelty test — PASSES

The measured object "risk-adjusted return of a fixed multi-signal portfolio" is genuinely distinct from "risk-adjusted return of each constituent signal." The map killed the latter; it never tested the former. So the hypothesis is **not** a re-description of an already-killed direction — it survives the §6 same-object test cleanly. This is what distinguishes it from "another momentum/funding/basis variant": the assembly is a real new object.

**But novelty is necessary, not sufficient.** A novel object with no constructible instance is not a live direction.

## 4. §4 envelope test — would pass IF constituents existed

A 3–5 signal, weekly-rebalanced, single-venue, market-neutral book is genuinely in-envelope: that is two-people-in-months work, not institutional infrastructure. So the *deployment shape* is fine. The problem is upstream of §4: since the existing corpus yields no eligible constituents, pursuing this direction would require **generating new signals specifically engineered to survive bias, fragility, governance, and construction validity** — i.e. building a signal-research pipeline that reliably produces combination-grade factors. That is a fundamentally larger project than "rescue the existing corpus," and it trends toward the signal-research-factory the envelope was defined to exclude. The in-envelope version (assemble what we have) is empty; the non-empty version (manufacture clean constituents) is a different, larger project.

## 5. Verdict

> **Combination-portfolio rescue of the Sleeve B corpus — FAILS at the eligibility gate.**
> The portfolio object is novel (survives §6) and would be in-envelope if it could be built (passes §4 in shape). It fails because **no eligible constituents exist:** every Sleeve B signal died from a defect — survivorship bias (#1), parameter fragility (#4), missing PIT data (#2), invalid construction (#3), or non-existence (#5) — that is **upstream of portfolio construction and inherited by any portfolio containing it.** Diversification repairs concentration, correlation, volatility, and drawdown. It repairs none of the defects that actually killed these signals.

## 6. Why this is recorded — the distinction that matters

This closes the direction with a reason the direction map did not previously contain. The map said the Sleeve B *signals* were killed. It did not address "but did you try *combining* them?" — the sophisticated escape hatch that sounds like it might bypass individual kills. The answer is now on record:

> We screened it. The portfolio object was novel — a genuinely different measured object than any single signal, not a re-description of a killed direction. But the constituent set failed eligibility: the signals didn't die from the diversifiable risk that portfolio construction fixes; they died from bias, fragility, invalidity, and unavailability, which a portfolio inherits. Therefore no valid portfolio can be constructed from the existing corpus.

Not "already tested" — **"no eligible constituents exist."** That distinction is the result. It means the family-office multi-signal-book path is not "assemble the Sleeve B survivors" (there are none clean enough); it is "manufacture new combination-grade signals," which is a different project against a different envelope question.

## 7. Status for the direction map

> **Combination-portfolio (Sleeve B rescue-by-assembly) — Closed (eligibility).** Object novel (§6 pass), shape in-envelope (§4 pass), but zero eligible constituents in the existing corpus — every candidate carries an upstream defect (bias/fragility/governance/non-computation) that portfolio construction cannot repair. Re-eligible only if clean, robust, unbiased constituent signals are generated first — a separate signal-research project, not a rescue of this corpus.

— end —
