# Sleeve B Candidate #4 — Kill action

**Candidate:** Volatility-scaled momentum (governance re-attempt under corrected Stage A)
**Kill date:** 2026-05-21
**Stage at kill:** Stage B, D4 complete (full F1 / F3 / B3 evidence pack)
**Kill mode:** Construction fragility — parameter-fragile interaction effect
**Killing gates:** F1.4 (window sensitivity) + B3 (Sharpe + drawdown)
**Subordinate to:** `docs/strategies/sleeve_b_candidate_4_preregistration.md` (commit `59c1156`)

---

## 0. Summary

Candidate #4 is formally shelved at Stage B with the full pre-registered evidence pack on record. Unlike candidate #3, which was killed at Stage A before signal evaluation, candidate #4 cleared Stage A under the corrected gate-inheritance framework (commit `39970f1`) and proceeded through the full Stage B engineering protocol: D1 signal module, D2 backtest, D3 F1 evaluator, D4 F3 evaluator.

The kill is locked under three pre-registered gates that fired independently:

- **F1.4 — Window sensitivity:** 0.711 vs 0.30 FAIL threshold. Kill-capable per §5 of the pre-registration.
- **B3 — Sharpe (PASS_WARNING tightening):** 1.2511 vs 1.75 required. Failure to clear promotion threshold.
- **B3 — Drawdown (PASS_WARNING tightening):** 26.67% vs 20% required. Failure to clear promotion threshold.

The candidate cleared six of nine pre-registered gates (F1.1, F1.2, F1.3, F3.1, F3.2, F3.3). The strategy is not disguised low-vol carry. The strategy is not a blue-chip portfolio. The strategy did produce real OOS returns (+218% arithmetic / +503% NAV over 36 months). What the strategy *is*, on the data, is a parameter-fragile interaction effect between momentum and vol-scaling — neither factor alone produced the returns, and minor perturbations of the locked parameters break the result.

This is the fifth kill in the SuperHydra Sleeve B program and the fourth distinct failure class:

| Sleeve | Stage of kill | Kill mode |
|---|---|---|
| A2 (perp-vs-spot basis) | Paper (`924a930`) | Signal absence |
| Sleeve B #1 (xs-momentum) | OOS backtest (`f3e078e`) | Construction fragility (drawdown) |
| Sleeve B #2 (fee-yield quality) | Stage A Phase 1 (`bf642d1`) | Data governance (PIT) |
| Sleeve B #3 (vol-scaled momentum) | Stage A pre-computation (`bf0a23e`) | Governance-design mismatch |
| **Sleeve B #4 (vol-scaled momentum)** | **Stage B D4 (this kill)** | **Construction fragility — parameter-fragile interaction** |

The framework operating under pre-registered anti-cherry-pick discipline produces the kill cleanly. The evidence pack is complete. No interpretive rescue is attempted.

---

## 1. Sequence of evidence

**1.1** Candidate #4 cleared Q0 with PASS_CLEAN (commit `bdedeed`) and was pre-registered with full §2–§9 lock at commit `59c1156`. The pre-registration was the program's first to use the corrected Stage A gate-inheritance framework committed at `39970f1`, addressing the governance-design mismatch that killed candidate #3.

**1.2** Stage A cleared with verdict A1=PASS_WARNING + A2=PASS_CLEAN (commit `479238f`). The PASS_WARNING tightened Stage B promotion thresholds to Sharpe ≥ 1.75 and drawdown ≤ 20%, per §4.B3 of the pre-registration. This was the first-ever Stage A clearance in the Sleeve B program.

**1.3** Stage B engineering ran in five deliverables (D1–D5) per the pre-registered protocol:

| Deliverable | Commit | Output |
|---|---|---|
| D1 signal module | `8cc69fc` | `strategies/sleeve_b/vol_scaled_momentum/signal.py` |
| Portfolio interpretation memo | `689ddd9` | Reading A locked: inherit xs-momentum portfolio-level vol-targeting |
| D2 backtest code | `3e06210` | Backtest engine + runner |
| D2 backtest artifacts | `ef788b7` | 157-row OOS audit log + weekly P&L |
| D3 F1 evaluator code | `a9a4c82` | `scripts/run_candidate_4_f1.py` |
| D3 F1 verdict | `78f746b` | F1 family FAIL on F1.4 |
| D4 F3 evaluator code | `ba37fce` | `scripts/run_candidate_4_f3.py` |
| D4 F3 verdict | `ad8415f` | F3 family PASS_CLEAN |
| D5 kill action | this commit | This document |

**1.4** D2 raw OOS metrics against pre-registered B3 thresholds (PASS_WARNING tightening per §4.B3):

| Metric | Threshold (PASS_WARNING) | Realised | Outcome |
|---|---|---|---|
| Annualised Sharpe (net) | ≥ 1.75 | 1.2511 | FAIL |
| Drawdown (peak-to-trough) | ≤ 20% | 26.67% | FAIL |
| BTC beta (mandatory diagnostic) | ±0.15 | +0.092 | within band |
| ETH beta (mandatory diagnostic) | ±0.15 | +0.061 | within band |

Both Sharpe and drawdown also fail the clean thresholds (1.5 and 25% respectively).

**1.5** D3 F1 family results:

| Sub-gate | Threshold (CLEAN) | Realised | Verdict |
|---|---|---|---|
| F1.1 vol estimator stability | ≤ 0.4 (xs median vol-of-vol) | 0.1380 | PASS_CLEAN |
| F1.2 rank churn | ≥ 0.55 (median retention) | 0.7143 | PASS_CLEAN |
| F1.3 numerator variance contribution | > 0.65 (median fraction) | 1.6160 | PASS_CLEAN |
| F1.4 window sensitivity | ≤ 0.15 (max-min)/median | 0.7109 | FAIL |

**1.6** D4 F3 family results, with F3.3 reported on the arithmetic gating basis per the operationalization committed at `ba37fce`:

| Sub-gate | Threshold (CLEAN) | Realised | Verdict |
|---|---|---|---|
| F3.1 long-bucket vol concentration | ≥ 0.80 (mean ratio) | 1.1073 | PASS_CLEAN |
| F3.2 BTC/ETH joint dominance | ≤ 0.40 (joint fraction) | 0.2293 | PASS_CLEAN |
| F3.3 pure low-vol attribution (arithmetic) | ≤ 0.30 (low-vol fraction) | -0.7194 | PASS_CLEAN |

---

## 2. Verdict

Per the candidate #4 pre-registration at commit `59c1156`:

> **§5 (F1 family):** Any F1 sub-gate FAIL is candidate-kill-capable regardless of Sharpe gate outcome.
>
> **§4.B3 (Stage B promotion):** Under A1 PASS_WARNING, promotion requires Sharpe ≥ 1.75 AND drawdown ≤ 20% AND F1/F3 compliance.

**Verdict: Stage B FAIL. Candidate #4 is shelved.**

Three pre-registered conditions independently produce the kill:

- **F1.4 FAIL is kill-capable on its own** under §5. Sensitivity 0.711 vs threshold 0.30. Single sub-gate is sufficient.
- **B3 Sharpe gate is not cleared** (1.25 < 1.75 tightened; also < 1.5 clean). Promotion threshold not met.
- **B3 drawdown gate is not cleared** (26.67% > 20% tightened; also > 25% clean). Promotion threshold not met.

Three independent kills, none requiring the others. Anti-cherry-pick discipline applies cleanly: the gates were specified before evidence was collected, the evidence was collected exactly as specified, the gates fired exactly as specified. No interpretive rescue is offered or required.

The candidate cleared every gate that tested misattribution (F3.1, F3.2, F3.3) and every gate that tested signal-instability of the cross-sectional ranking process (F1.1, F1.2, F1.3). What killed the candidate was the specific axis the pre-registration was designed to probe: parameter robustness.

---

## 3. What the data taught

Candidate #4's evidence pack contains real research findings beyond the kill verdict. Three observations are worth preserving for future candidates in this signal family.

### 3.1 The vol denominator reduced cross-sectional differentiation rather than adding to it

F1.3 measured the fraction of cross-sectional score variance attributable to the momentum numerator via counterfactual decomposition:

```
var_actual         = Var(momentum_i / vol_i across i)
var_constant_vol   = Var(momentum_i / mean(vol) across i)
fraction_momentum  = var_constant_vol / var_actual
```

Median across rebalances: **1.6160**. A fraction greater than 1.0 means: replacing each asset's individual vol with the cross-sectional mean *increases* score variance. The vol denominator is *compressing* the cross-section, not expanding it.

This contradicts the naive economic thesis behind the candidate. Volatility scaling was hypothesised to enhance cross-sectional differentiation by penalising high-vol names and elevating low-vol ones. The data shows the opposite: the vol denominator was reducing the dispersion of the final score relative to what raw momentum alone produced. Whatever the construction extracted in terms of returns, it did not extract them by improving cross-sectional ranking quality.

### 3.2 Neither pure component explains the returns

F3.3 attribution via parallel long-short backtests (arithmetic gating basis):

| Component | Fraction of total | Arithmetic sum return |
|---|---|---|
| Pure momentum (long-short top-bottom by 30d return) | +0.2361 | +51.56% |
| Pure low-vol (long-short bottom-top by 45d vol) | -0.7194 | -157.08% |
| Interaction (residual) | +1.4833 | +323.86% |
| **Total (candidate #4)** | **+1.0000** | **+218.34%** |

Pure cross-sectional momentum on this universe earned only ~24% of candidate #4's total arithmetic return. Pure low-vol *lost* ~72% (the long-short low-vol portfolio was meaningfully short over a sustained risk-on regime). The interaction term — what neither factor explains in isolation — accounts for ~148% of the candidate's total.

That interaction is real. It is also opaque: there is no clean factor decomposition that says "candidate #4 is X% momentum + Y% low-vol." The candidate's edge lives in the specific interaction between *which assets currently have positive momentum* and *what their realised vol happens to be at the same time*, in a way that neither input describes on its own.

### 3.3 The interaction is parameter-fragile on the momentum axis

F1.4 ran the same construction with four parameter variants:

| (momentum, vol) | Annualised Sharpe |
|---|---|
| (15, 45) | 1.4708 |
| (30, 30) | 0.8073 |
| (30, 45) (baseline reference) | ~1.25 |
| (30, 60) | 0.9831 |
| (45, 45) | 0.8832 |

Sensitivity `(max - min) / median = (1.47 - 0.81) / 0.93 = 0.71`. The strategy's Sharpe is highly sensitive to the momentum lookback specifically. Halving the momentum window from 30d to 15d nearly doubles the Sharpe. Lengthening it to 45d cuts Sharpe by ~30%.

This is the failure mode F1.4 was pre-registered to detect. The interaction effect identified in §3.2 is real, but it is realised only at specific parameter combinations. The locked (30, 45) parameters sit on a knife-edge — closer to the bad side of the sensitivity surface than the good side. A research-stage construction whose Sharpe depends this sharply on a single parameter is not promotable into live capital regardless of what its headline backtest reads.

### 3.4 The candidate is not disguised low-vol carry, and not a blue-chip portfolio

F3 family cleared cleanly:

- **F3.1** Long-bucket vol concentration ratio is 1.107 (long bucket is slightly *higher* vol than universe median, not lower). The construction is not implicitly tilting low-vol.
- **F3.2** BTC and ETH appear jointly in the long bucket only 22.9% of the time. The strategy is not a market-cap-weighted blue-chip portfolio in disguise.
- **F3.3** Pure low-vol contribution is strongly negative (-0.72 of arithmetic total). Low-vol carry is not the source of returns.

These clearances matter for the kill action. They establish that the kill is on construction fragility, not on misattribution. A future candidate in this signal family — or a future operator reviewing this kill — can know with evidence that "vol-scaled momentum is just disguised low-vol carry" is not the correct interpretation.

---

## 4. Classification — construction fragility (parameter-fragile interaction)

This is the second construction-fragility kill in the program (xs-momentum at `f3e078e` was the first), but the failure mode is distinct enough to warrant its own classification:

| Kill | Construction failure mode |
|---|---|
| Sleeve B #1 (xs-momentum, `f3e078e`) | Drawdown exceeded gate (25.92%) at acceptable Sharpe (1.38). Generic construction-level brittleness. |
| **Sleeve B #4 (vol-scaled momentum, this kill)** | **Parameter-fragile interaction. The strategy works only at exact parameter pairs and breaks under standard window perturbation.** |

Three properties of candidate #4's failure that distinguish it from xs-momentum's:

**4.1** The candidate produces *real* OOS returns at its locked parameters (+218% arithmetic / +503% NAV). It is not a strategy that "doesn't work." It is a strategy that works under exactly one parameter combination and breaks under nearby ones.

**4.2** The fragility is localised to one axis (momentum lookback), not distributed across the parameter surface. Vol-window perturbation (30/30, 30/60) produced moderate Sharpe degradation (~30%). Momentum-window perturbation (15/45, 45/45) produced both the best (+1.47) and worst-of-momentum-perturbation (+0.88) results, spanning a Sharpe range of 0.59. This is interpretable: the strategy is most sensitive to *how* it defines "momentum" and less sensitive to *how* it measures volatility.

**4.3** The economic thesis behind the candidate (vol-scaling enhances cross-sectional differentiation) is empirically contradicted (§3.1). The strategy's returns come from a real but opaque interaction effect (§3.2), not from the mechanism the construction was nominally designed to exploit.

This classification matters for future candidate selection. A future signal proposal in the form "ratio of A over B where A is the alpha numerator and B is a risk-adjustment denominator" should treat parameter-fragility as a *primary* risk, not a secondary one. F1.4 as pre-registered did its job here; future similar candidates should keep F1.4 as a kill-capable gate without weakening.

---

## 5. What this kill does NOT establish

**It does NOT establish that vol-scaled momentum is universally a poor signal family.** The candidate produced real OOS returns at locked parameters. The failure mode is parameter-fragility, not signal absence. A future candidate in this family could conceivably clear the gates with a more robust construction (e.g., longer windows, ensembled parameters, or a different vol estimator).

**It does NOT establish that interaction effects are unfit for Sleeve B.** Many real strategies extract returns from interactions that don't decompose cleanly into named factors. The kill here is parameter-fragility, not the existence of an interaction component.

**It does NOT establish that the corrected Stage A gate-inheritance framework (`39970f1`) was unnecessary.** Candidate #4 cleared Stage A under the corrected framework, then died at Stage B on signal-level fragility — exactly the kind of failure the framework is supposed to surface at Stage B rather than at Stage A. The framework operated as designed.

**It does NOT close the door on a re-attempt with a different construction.** A future vol-scaled-momentum candidate using a parameter-ensembled signal, or a different operationalization of vol-scaling, could face fresh gates. The kill of #4 does not pre-empt #5.

**It does NOT amend any prior governance artifact.** The master pre-registration at `fe909bb`, the Q0 memo at `cb9d975`, the framework evolution at `39970f1`, and the candidate #4 pre-registration at `59c1156` all remain binding as the historical record. This kill action is the close of candidate #4 under those rules.

---

## 6. Budget accounting

| Item | Budget | Consumed | Result |
|---|---|---|---|
| Stage A | 2 days | ~1.5 days | On-target |
| Stage B (D1–D5) | ~3 weeks | ~5 days (engineering) | Substantial underrun |
| Candidate #4 total | 41 days | ~6.5 days | ~34.5 days returned to Sleeve B |
| Master Sleeve B budget | Per `fe909bb`, kill date 2026-06-27 | Substantively intact | — |

This is the longest-running candidate in the program (the only one that cleared Stage A and produced Stage B evidence), but it still completed inside its allotted budget. Stage B engineering ran in five clean deliverables across five sessions with one mid-session methodology correction (F3.3 arithmetic vs NAV attribution caught and patched before the verdict commit at `ad8415f`).

---

## 7. Lessons made explicit

**7.1 Pre-registered F1.4 is kill-capable and the program should keep it that way.** Candidate #4 cleared every other F1 sub-gate by wide margins, then died on F1.4. If F1.4 had been weakened or removed in response to candidate #4's edge-of-promotion Sharpe and drawdown, the program would have promoted a parameter-fragile strategy into canary. F1.4 caught exactly what it was designed to catch.

**7.2 Arithmetic attribution is the right gating basis for F3.3.** During D4 review, NAV-endpoint subtraction was identified as a known-flawed input for the F3.3 interaction term. The methodology was corrected before commit (`ba37fce`). For future candidates in this family or related families, F3.3 should be operationalised on arithmetic weekly-summed returns by default, with NAV-endpoint reported only as descriptive context. The arithmetic decomposition is mathematically additive; the NAV decomposition is not.

**7.3 Stage A clearance does not pre-commit to Stage B clearance.** Candidate #4 cleared Stage A under the corrected framework (a meaningful achievement — first Stage A pass in the program) and then died at Stage B. The framework correctly separates "this candidate is eligible to be evaluated" (Stage A) from "this candidate has demonstrated edge" (Stage B). Future operators should not read a Stage A pass as a precursor signal about Stage B outcomes.

**7.4 Cross-sectional momentum on this universe is weak in isolation.** F3.3 showed that the pure long-short momentum portfolio (top-third vs bottom-third by 30d return) earned only ~24% of candidate #4's arithmetic total. This is a finding about *this universe over this OOS window*, not a finding about momentum in general. But it is a data point: future cross-sectional momentum candidates on the same universe should not assume pure momentum will carry the strategy on its own.

**7.5 Five candidates have produced four distinct failure classes (construction fragility appears twice in different sub-flavors — drawdown brittleness in #1, parameter-fragile interaction in #4).** The framework's gates are independently informative — they are not collapsing to a single proxy. That is the structural justification for keeping the gate stack at its current breadth rather than streamlining. Each gate has now caught at least one failure that the others did not catch.

**7.6 Stage B engineering can be done in well-bounded sessions.** D1 through D4 ran in five engineering sessions (D1, D2, D3, D4 code, D4 verdict), each producing one or two atomic commits, with one mid-session methodology correction. Future Stage B engineering for candidate #5+ can be planned on this cadence with reasonable confidence. The pattern is reproducible.

---

## 8. Decision-log entry

**Decision:** Shelve Sleeve B candidate #4 (volatility-scaled momentum, governance re-attempt).
**Authority:** Operator (Wasseem), single-operator governance per `SuperHydra_FreshStart_Roadmap_v2.2.docx` §10.
**Gate references:**
- Pre-registration §5 (F1 family kill-capable): F1.4 = 0.711 vs 0.30 FAIL threshold.
- Pre-registration §4.B3 (Stage B Sharpe gate, PASS_WARNING tightening): 1.2511 vs 1.75 required.
- Pre-registration §4.B3 (Stage B drawdown gate, PASS_WARNING tightening): 26.67% vs 20% required.
**Evidence artifacts:**
- D2 backtest artifacts: commit `ef788b7`
- D3 F1 verdict: commit `78f746b`
- D4 F3 verdict: commit `ad8415f`
**Closeout:** Vol-scaled-momentum research direction not closed; specific candidate #4 construction at locked parameters (mom=30d, vol=45d) retired. Stage B engineering protocol (D1–D5) demonstrated reproducible; carry forward to candidate #5+.
**Budget impact:** ~34.5 days returned to Sleeve B against the 2026-06-27 master kill date.
