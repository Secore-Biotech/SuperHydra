# Sleeve B framework review — May 2026

**Status:** Meta-deliverable. Not a candidate, not a pre-registration, not engineering.
**Date:** 2026-05-21
**Author:** Operator (Wasseem)
**Corpus reviewed:** Five kill actions (A2 basis, xs-momentum, fee-yield quality, vol-scaled momentum #3, vol-scaled momentum #4)
**Scope:** Synthesize the five-kill record. Answer three diagnostic questions. Recommend only from those answers.

---

## 0. Summary

After five candidates and zero clearances, the Sleeve B framework has produced enough evidence to ask whether it is filtering correctly, whether the candidate-generation process has systematic blind spots, and whether Sleeve B's premise is still consistent with the data.

This review answers those three questions independently of any recommendation, then derives recommendations from the answers. The diagnostic-criteria locks were committed before evidence was synthesized. The discipline of the kill actions themselves — pre-registered gates, anti-cherry-pick verdicts, honest disclosures of what each kill does NOT establish — is the discipline this review honors.

The headline finding, anticipating §3–§5: **the gates are filtering correctly, the candidate-generation process has one identifiable blind spot (clustering on cross-sectional crypto factor research), and Sleeve B's premise is too soon to assess with confidence.** The recommended next action is candidate #5 with one targeted change to the candidate-selection process (§6), not a framework rewrite.

The review is allowed to conclude "insufficient evidence to update most things." That is approximately the conclusion reached.

---

## 1. The corpus

Five candidates, five distinct kill records, four distinct failure classes. The table below recaps each kill on the actual content of its kill action memo, not summary impressions:

| # | Candidate | Killed at | Killing gate | Class | Sharpe-positive at kill? |
|---|---|---|---|---|---|
| 1 | A2 perp-vs-spot basis | Paper, Step 3 | Zero entries on pre-registered normal-regime window | Signal absence | N/A — never traded normally |
| 2 | Sleeve B #1 xs-momentum | OOS backtest | Drawdown 25.92% > 25% gate (Sharpe 1.38) | Construction fragility (drawdown) | Yes |
| 3 | Sleeve B #2 fee-yield quality | Stage A Phase 1 | A4 PIT availability (DeFiLlama backfills) | Data governance | Never computed |
| 4 | Sleeve B #3 vol-scaled momentum v1 | Stage A pre-computation | A2 temporal-stability spread 14 > 6 | Governance-design mismatch | Never computed |
| 5 | Sleeve B #4 vol-scaled momentum v2 | Stage B D4 | F1.4 window sensitivity 0.711 > 0.30 + B3 Sharpe + B3 drawdown | Construction fragility (parameter-fragile interaction) | Sort of — 1.25 Sharpe at locked params, real interaction effect |

The kills are methodologically heterogeneous in two ways that the table makes visible:

**1.1** Kills span four distinct *pipeline stages*: paper (A2), Stage A Phase 1 (quality), Stage A pre-computation (#3), Stage B D4 (#4), and OOS backtest (xs-momentum). No single stage is doing all the gating work. Every stage has been load-bearing for at least one kill.

**1.2** Kills span the *signal/construction/data/governance* axis. A2 was a signal kill. xs-momentum and #4 were construction kills. Quality was a data kill. #3 was a governance kill. The framework's gates filter on multiple dimensions independently.

What survived across the corpus is also worth recording, because the kill actions made these explicit and they constitute the program's accumulated infrastructure:

- Frozen universe fixture pattern with survivorship disclosure (from xs-momentum)
- `BinanceKlinesArchiveFetcher` and per-asset price cache (from xs-momentum)
- Signal-agnostic engine architecture: universe, prices, portfolio, backtest (from xs-momentum)
- Audit log JSONL format with per-rebalance eligibility and decile records (from xs-momentum)
- Q0 Data Viability Gate (added after quality kill, binding for #3+)
- Stage A gate-inheritance correction (added after #3 kill, binding for #4+)
- F1 / F3 sub-gate families with operationalization specs (locked at #4 pre-registration)
- F3.3 arithmetic-attribution methodology (corrected mid-D4)
- Replay observation machinery and `paper.fills` infrastructure (from A2)

The kill actions repeatedly distinguish *strategy hypothesis rejected* from *research substrate validated*. The substrate has accumulated meaningfully. The substrate is not the failure mode being assessed here.

---

## 2. The pre-existing lessons

Five kill actions contain a total of 17 written lessons. Synthesizing across them surfaces a meta-pattern the review needs to assess. Below are the lessons grouped by theme, not by source memo:

**Theme A — Discipline binding under temptation (4 lessons):**

- A2: "The pre-registration discipline (commit `8ee5ecb`) is what turned an initially positive-looking result into a definitively negative answer."
- xs-momentum: "Sharpe alone is not promotion-grade evidence... A Sharpe 1.38 construction was killed because drawdown was 25.92%. Without the simultaneous-constraints rule, the natural impulse would have been to promote."
- xs-momentum: "The 'no relative attractiveness' clause matters in practice, not just in theory."
- Candidate #3: "Pre-registered constraints bind even when uncomfortable... If A2 can be reinterpreted after seeing the result, every prior kill becomes suspect."

**Theme B — Different failure modes require different gates (5 lessons):**

- A2: "Substrate-only findings are not decision-grade. Counting entries is not measuring performance."
- A2: "Test-stub leakage is a real failure mode."
- xs-momentum: "Vol-target alone does not control tail risk... Drawdown limits exist precisely because vol-targeting can fail."
- xs-momentum: "Cost drag was not the binding constraint... cost-anchored gating may not be the right primary discipline; volatility-and-drawdown gating is."
- Candidate #4 lesson 7.1: "Pre-registered F1.4 is kill-capable and the program should keep it that way."

**Theme C — Data and governance constraints are first-class (4 lessons):**

- Quality §6: "For some candidate families, the bottleneck is not edge — it is data integrity."
- Candidate #3 lesson 7.1: "Stage A inherited gates require per-candidate verification."
- Candidate #3 lesson 7.2: "Q0 §3.5 (survivorship) is necessary but not sufficient."
- Candidate #3 lesson 7.3: "Some kills emerge from governance, not from signals."

**Theme D — Specific findings about crypto cross-sectional research (4 lessons):**

- A2: "Cost-anchored thresholds can create a 'fires-only-when-untradable' pathology."
- xs-momentum: "For cross-sectional momentum on top-30 Binance perps with weekly rebalance, turnover is not what kills the strategy. Tail risk is."
- Candidate #4 lesson 7.4: "Cross-sectional momentum on this universe is weak in isolation... pure long-short momentum portfolio earned only ~24% of candidate #4's arithmetic total."
- Candidate #4 §3.1: "The vol denominator reduced cross-sectional differentiation rather than adding to it."

**Theme E — Process and reproducibility (2 lessons):**

- Candidate #4 lesson 7.2: "Arithmetic attribution is the right gating basis for F3.3."
- Candidate #4 lesson 7.6: "Stage B engineering can be done in well-bounded sessions... five engineering sessions... Pattern is reproducible."

The corpus is dense. Themes A and B (eight of seventeen) are about the framework working. Themes C and D (eight of seventeen) are about specific findings within the program's research domain. Theme E (two of seventeen) is about engineering process. None of the seventeen lessons recommend a *change* to the gate stack itself; several recommend *additions* (Q0, gate-inheritance verification, F3.3 arithmetic methodology), all of which have been made.

The corpus contains substantial directional guidance for future candidate-#5+ selection (Quality §7.3, xs-momentum lesson 4, #4 lesson 7.4) but no recommendation to *retire or weaken* any existing gate.

---

## 3. Q-A — Are the gates filtering correctly?

### 3.1 Coverage analysis

The pre-registered gate stack and which kill each gate has caught:

| Gate / sub-gate | Family | First kill caught | Times fired |
|---|---|---|---|
| Paper Step 3 (zero entries) | Signal-existence | A2 | 1 |
| Q0 (data viability) | Pre-Stage A | None directly; would have caught quality earlier had it existed | 0 (post-hoc) |
| Stage A A2 (temporal stability) | Stage A | #3 (governance mismatch) | 1 |
| Stage A A4 (PIT discipline) | Stage A | Quality (PIT unavailable) | 1 |
| B3 Sharpe gate | Stage B promotion | #4 (1.25 < 1.75 PASS_WARNING) | 1 |
| B3 drawdown gate | Stage B promotion | xs-momentum (25.92% > 25%) and #4 (26.67% > 20%) | 2 |
| F1.4 window sensitivity | Stage B sub-gate | #4 (0.711 > 0.30) | 1 |
| F1.1 / F1.2 / F1.3 | Stage B sub-gate | None | 0 |
| F3.1 / F3.2 / F3.3 | Stage B sub-gate | None | 0 |

**Coverage is broad.** Eight gates fired across five kills; one gate (B3 drawdown) fired twice, on candidates with different signal families. The framework is not concentrating failures into one gate.

**Six pre-registered Stage B sub-gates have never fired.** F1.1, F1.2, F1.3, F3.1, F3.2, F3.3 all PASSED on candidate #4 (the only candidate to reach Stage B sub-gate evaluation). This is a feature of how recently the gates were added, not evidence of redundancy — those sub-gates were specifically designed to catch failure modes the program had not yet seen in evidence form.

### 3.2 False-negative analysis — could anything have slipped through?

For each kill, I ask: was the gate that fired *the right gate* for the failure, or was it a coincidental catch?

**A2** failed on zero entries in normal regime. The pre-registration explicitly anticipated this as a kill criterion. Right gate, designed for this case. Not a coincidental catch.

**xs-momentum** failed on drawdown 25.92% > 25% with Sharpe 1.38. The "simultaneous-constraints" rule was locked before the result. The kill action explicitly notes the rule was specifically designed for the "great Sharpe, terrible tail risk" failure mode. Right gate, designed for this case.

**Quality** failed on A4 PIT discipline. The pre-registration explicitly anticipated DeFiLlama-class backfill as a PIT failure. Right gate, designed for this case.

**#3** failed on A2 temporal stability. The kill action itself classifies this as a governance-design mismatch — the gate was applied correctly under its specification, but the specification was inappropriate for #3's universe construction. *This is a gate-design issue, not a gate-firing issue.* The framework correction at `39970f1` addressed it prospectively. The kill itself was honored under discipline, but the gate-design lesson is real.

**#4** failed on F1.4 window sensitivity (and B3 Sharpe, B3 drawdown). F1.4 was specifically designed to catch parameter-fragility in vol-scaled constructions. Right gate, designed for this case. The kill action notes F1.4 caught exactly what it was designed to catch.

**Conclusion: no false negatives.** Each kill cleared at a gate specifically designed for its failure mode. One kill (#3) revealed a gate-design issue that was subsequently corrected. The framework's gates are well-targeted on the failure space they're meant to cover.

### 3.3 False-positive analysis — could any kill have been a missed promotion?

This is the harder question. For each kill, I ask: under reasonable threshold variations, could the candidate have been promotable?

**A2** — zero entries on the pre-registered window is unambiguous. No threshold variation rescues "zero." False-positive risk: zero.

**xs-momentum** — drawdown 25.92% vs 25.00% gate is the narrowest margin in the corpus (0.92pp). Under a 30% drawdown limit, the candidate would have promoted. The kill action *explicitly* discusses this temptation: "the temptation to relax the limit by 0.92 percentage points was real; the discipline that refused to do so is the actual moat." Whether this was a false positive depends on what the 25% gate is calibrated *to*. The kill action argues 25% was calibrated to live-trading reality, not curve-fit retrospectively. Without independent evidence about appropriate drawdown limits for the program's $50k scale and capital-recovery profile, this kill's calibration is plausible but not provable. False-positive risk: low-to-moderate, but the calibration was pre-registered.

**Quality** — PIT unavailability is binary. No threshold variation makes DeFiLlama PIT-grade. False-positive risk: zero on the gate; non-zero on the meta-decision to decline paid acquisition. The operator decision in Quality §3 was a separate judgment, not a gate firing.

**#3** — the spread of 14 vs 6 gate is unambiguous under the specification, but the kill action itself documents that the gate was inappropriate. The "false positive" framing doesn't apply because the gate-design was the issue, and it was corrected. Under the corrected framework, #3 would not have died at A2.

**#4** — three independent gates fired:
- F1.4 sensitivity 0.711 vs 0.30: at 0.30 → 0.50 the candidate would still fail. At 0.30 → 0.80 it might pass. 0.711 is 2.4× the threshold; this is not a borderline call.
- B3 Sharpe 1.25 vs 1.75 (under PASS_WARNING tightening from 1.5 clean): even at the clean threshold the candidate fails. Not borderline.
- B3 drawdown 26.67% vs 20% (under tightening from 25% clean): at 25% clean the candidate still fails. Not borderline.

Three independent kills, none borderline. False-positive risk: very low.

**Conclusion: only xs-momentum had a margin narrow enough that calibration matters.** Even there, the calibration was pre-registered before the result. The framework is not over-filtering.

### 3.4 Verdict on Q-A

**Verdict A1 — Gates filter correctly.** Every kill cleared at a gate specifically designed for its failure mode. One kill (#3) revealed and corrected a gate-design issue. No kill represents an over-tight constraint that should be loosened. No promotable candidate was missed.

The 17 lessons across the kill actions independently corroborate this verdict: no lesson recommends weakening or removing a gate. Two lessons (xs-momentum #4 and the #4 lesson 7.1) explicitly recommend keeping specific gates ("cost drag was not the binding constraint; vol-and-drawdown gating is" and "keep F1.4 kill-capable").

**Calibration caveat — the xs-momentum drawdown margin.** The verdict A1 is defensible but rests on one calibration choice that is plausible rather than provable: the 25% drawdown gate that killed xs-momentum at 25.92%. If that gate had been calibrated to 30%, xs-momentum would have promoted to canary with a Sharpe-1.38 result on record. That counterfactual is not hypothetical — it is what the same evidence would have produced under a different threshold. The 25% calibration was pre-registered and the kill action defended it on live-trading grounds, but the program does not yet have live-trading evidence about appropriate drawdown limits at its $50k scale. The verdict treats the calibration as correct because it was pre-registered honestly; it does not claim the calibration was provably optimal. A future reviewer with live-trading evidence may legitimately revisit this.

The verdict on Q-A is high-confidence within the corpus. It is not a claim about whether the gate calibration is optimal for the program's eventual capital scale or for assets outside top-30 Binance perps — only that on the corpus collected, the gates are filtering the right things at the right thresholds.

---

## 4. Q-B — Does candidate-generation have blind spots?

### 4.1 What signal families have been tried

Five candidates across two broad categories:

**Inter-instrument relative-value (1 candidate):**
- A2 perp-vs-spot basis (single instrument, multi-venue spread)

**Cross-sectional factor research on top-30 Binance USDT-perps (4 candidates):**
- xs-momentum (return-based ranking)
- Fee-yield quality (fundamental-ratio ranking — never reached evaluation)
- Vol-scaled momentum v1 (risk-adjusted momentum — never reached evaluation)
- Vol-scaled momentum v2 (risk-adjusted momentum, governance re-attempt)

Four of five candidates draw from the same signal family and the same universe construction. The diversity of the corpus is substantially narrower than the kill-class diversity suggests.

### 4.2 What signal families have NOT been tried

Signal families plausible at the program's scale and infrastructure that have *not* been candidates:

- **Time-series momentum / trend** (single-asset directional, not cross-sectional)
- **Calendar / cyclical** (day-of-week, weekend, funding-cycle anchored)
- **Event-driven** (listing, delisting, hard-fork, regulatory announcement windows)
- **Order-book microstructure** (queue position, depth imbalance — separate from execution overlay)
- **Cross-venue arbitrage** (other than A2's specific perp-vs-spot specification)
- **Volatility carry** (vol-of-vol, term-structure on Deribit or similar — infrastructure-blocked without paid data, but conceptually distinct)
- **Mean-reversion on non-factor signals** (RSI-class, bollinger-class, statistical reversion within a basket)
- **Cross-asset correlation regime trading** (BTC-ETH correlation as regime indicator)
- **Liquidation cascade detection / fade** (related to A2's stress-regime finding, but as primary signal not residual)

This is illustrative, not exhaustive. The point is that 80% of the corpus (4/5) is cross-sectional factor research within one specific universe construction.

### 4.3 Pattern in why selection landed where it did

Three structural reasons selection clustered:

**4.3.1** The master Sleeve B pre-registration (`fe909bb`) specifically frames the sleeve as "market-neutral long/short" — a description that biases candidate generation toward cross-sectional constructions. This framing is upstream of every individual candidate selection.

**4.3.2** The frozen-universe fixture (`2af9981`) and the engine architecture built around it (universe → prices → portfolio → backtest) make cross-sectional candidates much cheaper to evaluate than other families. Once xs-momentum was built, every subsequent cross-sectional candidate inherited substantial infrastructure. Other signal families would have required new infrastructure.

**4.3.3** The Q0 Data Viability Gate (`cb9d975`), added after the Quality kill, specifically requires Binance-cacheable data. This filter further biases toward signal families that can express themselves through OHLCV-style data on top-30 perps. Event-driven or microstructure candidates would face Q0 friction.

None of these structural reasons are *wrong*. They are appropriate constraints for the program's stage. But they have a side effect of narrowing the candidate space substantially. The five-kill record is not five draws from "all plausible signal families" — it is five draws from "cross-sectional factor research on a frozen top-30 perp universe with Binance-cacheable data," with one A2 outlier.

### 4.4 Verdict on Q-B

**Verdict B2 — Specific blind spot identified.** The candidate-generation process clusters on cross-sectional factor research within one universe construction. The cluster is rationalized by infrastructure investment, master pre-registration framing, and Q0 data constraints. It is not a generation error — every individual selection was defensible — but it is a systematic bias that the review needs to surface.

The cluster has *substantive consequences* visible in the corpus. Candidate #4's lesson 7.4 ("cross-sectional momentum on this universe is weak in isolation, earning only 24% of candidate #4's arithmetic total") is a finding about *the cluster*, not about momentum in general. If the cluster has structurally limited edge on the universe-and-timeframe combination, every cross-sectional candidate will face the same drag.

This does not mean the cluster is *wrong* as a research direction. It means future candidate-#5+ selection should explicitly *choose* whether to draw from inside the cluster or outside it. Right now, selection drifts inside by default because the infrastructure makes it cheaper.

The verdict is medium-confidence. Five candidates is small for cluster-vs-non-cluster inference; the cluster framing could be reframed as "the four cross-sectional candidates are actually quite different (xs-momentum is return-only, quality is fundamental-ratio, #3/#4 are risk-adjusted return) and the apparent cluster is a coincidence of selection order, not a structural bias." That reframing is defensible but harder to support given the three structural reasons in §4.3.

---

## 5. Q-C — Is Sleeve B's premise consistent with evidence?

### 5.1 What the evidence DOES say

Five candidates, zero clearances, multiple distinct failure modes. The specific things the corpus has demonstrated:

**5.1.1** Crypto cross-sectional momentum on top-30 Binance perps with vol-targeted construction can produce Sharpe 1.38 OOS, but with drawdowns at or above 25%. The signal exists but the tail risk is structural.

**5.1.2** Vol-scaling that signal produces +218% arithmetic / +503% NAV cumulative over 36 months at locked parameters, but with parameter fragility on the momentum axis specifically (sensitivity 0.71).

**5.1.3** Pure cross-sectional momentum on this universe (long top-third by 30d return, short bottom-third) earned only +51.55% arithmetic over 36 months. Pure low-vol *lost* -157.07% (high-vol crypto consistently beat low-vol). The 218% candidate-#4 result came from an interaction effect that is real but parameter-fragile.

**5.1.4** Cross-sectional factor research at this scale (top-30, weekly rebalance, $50k cap) faces specific structural challenges: weak pure factor returns, parameter-fragility on interaction effects, tail-risk that exceeds reasonable promotion gates.

**5.1.5** Data-PIT availability is a binding constraint on multiple candidate families (Quality killed for this reason; future fundamental-ratio candidates would face similar constraints).

**5.1.6** The framework itself works. Five kills at five appropriate stages, no false negatives, no overconstraining false positives, accumulating substrate that survives strategy hypothesis rejection.

### 5.2 What the evidence does NOT say

Equally important — the things the corpus has *not* demonstrated, despite being often implicitly assumed:

**5.2.1** That crypto cross-sectional factor edge does not exist at the program's scale. Five candidates is too few for that inference. The factor literature outside crypto often finds that 5-15 candidates are needed before a clearance pattern emerges; the program is at the low end of that range.

**5.2.2** That the gate stack is too tight for crypto. No kill represents an over-tight constraint (per §3.4). The xs-momentum kill at 0.92pp over the drawdown limit is the narrowest margin and the kill action itself defends the calibration.

**5.2.3** That research-direction pivot is warranted. The corpus is too small and too clustered (per §4.4) to support a "Sleeve B's premise has failed" conclusion. The cluster issue means the program hasn't actually tested Sleeve B's premise broadly — it has tested cross-sectional factor research on a frozen top-30 universe.

**5.2.4** That the program's structural value is "governance, not strategies." This is a tempting reframe that the operator's planning notes raised. The corpus does not support it. The framework's value is *in service of* strategy research, not as a substitute for it. If the program reframes itself as governance-first with strategy research as scaffolding, every kill becomes a "the framework worked" success, and the framework's purpose becomes unfalsifiable. The discipline that makes the kills meaningful is precisely that the framework is *not* the deliverable; the strategies are.

### 5.3 Verdict on Q-C

**Verdict C3 — Premise too soon to assess.** Five candidates is a small sample for Sleeve B's strategic question. Decision-grade evidence about whether crypto cross-sectional factor edge exists at the program's scale would require 8-10 candidates minimum, drawn from across the candidate space rather than clustered.

The corpus demonstrates that the framework works. It demonstrates specific findings about cross-sectional factor research on this universe. It does *not* demonstrate that Sleeve B's premise has failed, and it does *not* demonstrate that the premise holds. The honest answer is that the evidence base for the strategic question is too thin.

This verdict has a specific implication: a premise-level pivot at this stage would be premature. A premise-level continuation without addressing §4.4's cluster issue would be uninformed. The middle path — continue Sleeve B with cluster awareness and accumulate more diverse evidence — is the conditional implied by C3.

---

## 6. Conditional recommendations

§3 verdict: **A1 (gates filter correctly)**. §4 verdict: **B2 (cluster blind spot)**. §5 verdict: **C3 (premise too soon to assess)**. Recommendations follow conditionally from each.

### 6.1 From A1 → no gate changes

Verdict A1 says the gates are filtering correctly. The conditional implication is straightforward: **do not change the gate stack**. No threshold loosening, no gate removal, no rebalance of F1 vs F3 vs B3 weights. The 17 pre-existing lessons across kill actions already concur with this — none recommends gate changes.

Specific items NOT to do under A1:
- Do not relax the 25% drawdown limit because xs-momentum failed by 0.92pp
- Do not relax the F1.4 sensitivity threshold because candidate #4 was the first to fail it
- Do not consolidate F1 / F3 sub-gates; they have different failure-mode coverage
- Do not move B3 Sharpe gate from 1.5 (clean) / 1.75 (PASS_WARNING tightening) downward

### 6.2 From B2 → one targeted change to candidate generation

Verdict B2 identifies a clustering bias in candidate selection. The conditional implication is **add an explicit cluster-diversity check to Q0**, not change the candidate pool retroactively.

Concrete proposal for Q0 evolution (binding for candidate #5 onward, requires its own framework-evolution memo before #5 selection begins):

```
Q0 §X — Cluster diversity check (new sub-criterion)

Before pre-registration, the candidate selection memo must:

(a) Classify the candidate against the corpus by signal family:
    - inter-instrument relative-value
    - cross-sectional factor (sub-categorize: return-based / fundamental-
      ratio / risk-adjusted / other)
    - time-series / trend
    - event-driven
    - microstructure
    - cross-venue arbitrage
    - other (specify)

(b) Note the count of prior candidates in the same family.

(c) If 3+ prior candidates exist in the same family, the selection memo
    must include a written justification for why this candidate is
    expected to surface evidence the prior cluster did not.

This is NOT a kill criterion. It is a forcing function on the selection
narrative. A candidate that draws from the same cluster as 3+ priors can
still proceed, but the operator must write the case for why.
```

The point of the check is not to *forbid* clustered candidates — it is to make the cluster choice visible at selection time. Right now selection drifts toward the cluster because of infrastructure economics; the check makes the drift explicit so it becomes a deliberate decision rather than a default.

### 6.3 From C3 → run candidate #5 with no premise change

Verdict C3 says the premise is too soon to assess. The conditional implication is **continue Sleeve B as scoped, run candidate #5, re-assess premise at candidate #6 or #7**.

Concretely:
- Do not pivot Sleeve B to a different research direction
- Do not reframe the program as "governance-first, strategies-as-scaffolding"
- Do not abandon the master pre-registration's market-neutral-long-short framing
- Do continue accumulating evidence; the strategic answer requires more candidates

The cluster-diversity check from §6.2 will partially address C3 by making the next 1-2 candidates more informative for premise-level assessment than they would otherwise be. If candidate #5 and #6 are deliberately drawn from non-cluster families, then by candidate #7 the corpus would be diverse enough to support a real premise-level verdict.

### 6.4 What the recommendations together amount to

The combined recommendation is conservative: no gate changes, one targeted Q0 addition, candidate #5 proceeds. The framework review concludes that the framework is approximately correct, the candidate generation process has one identified improvement, and the strategic question requires more evidence.

This is not a dramatic conclusion. It is the honest one given the diagnostic verdicts. A more dramatic conclusion — "loosen gates" or "pivot Sleeve B" or "reframe the program" — would have required different §3-§5 verdicts than the evidence supports.

---

## 7. What this review is NOT

**It is NOT a proposal to weaken the framework.** Every diagnostic verdict in §3 says the framework is working. The one change recommended (§6.2 Q0 cluster check) tightens selection discipline; it does not relax any gate.

**It is NOT a kill action for Sleeve B.** Verdict C3 says the premise is too soon to assess, not that the premise has failed. The corpus does not support a sleeve-level shelve decision.

**It is NOT a research-direction pivot.** No structural change to the master Sleeve B pre-registration at `fe909bb` is proposed. The Q0 addition in §6.2 is a sub-criterion, not a framing change.

**It is NOT a substitute for candidate #5 selection.** The next concrete deliverable after this review is the framework-evolution memo for the Q0 cluster check, followed by candidate #5 selection. This review opens those, it does not perform them.

**It is NOT a binding amendment to any prior governance artifact.** The master pre-registration at `fe909bb`, the Q0 memo at `cb9d975`, the gate-inheritance framework at `39970f1`, and the five kill actions all remain binding as the historical record. This review is interpretive synthesis, not governance.

**It does NOT establish that the candidate-cluster blind spot is a defect.** It establishes that the cluster exists and that the selection process did not explicitly choose it. Future candidates may stay in the cluster after deliberate choice; the §6.2 check makes the choice visible, not negative.

---

## 8. Next actions

**8.1** Commit this review.

**8.2** Open a framework-evolution memo session at `docs/strategies/sleeve_b_framework_evolution_q0_cluster_diversity.md` (filename to be confirmed in the memo session). The memo specifies the Q0 cluster-diversity sub-criterion per §6.2 of this review.

**8.3** Candidate #5 selection opens in a separate session after §8.2's evolution memo commits. Candidate #5's selection memo must include the §6.2 cluster classification. Candidate #5 inherits the corrected framework prospectively.

**8.4** No part of this review modifies migration work (hydra-next), legacy strategy operation, Sleeve A development, or the A2 stash preserved for Step 3 work.

**8.5** Re-assessment of Sleeve B's premise (Q-C) is deferred to after candidate #6 or #7. At that point a follow-up framework review may be warranted.

**8.6** The recommendation to keep all gates as currently calibrated (per §6.1) is binding for the next two candidates (#5 and #6) at minimum. Mid-stream gate changes after candidate #6 would require their own framework-evolution memo.

---

## 9. References

- Master Sleeve B pre-registration: `docs/strategies/sleeve_b_research_preregistration.md` (commit `fe909bb`)
- Q0 Data Viability Gate memo: `docs/strategies/sleeve_b_framework_evolution_q0_data_viability.md` (commit `cb9d975`)
- Stage A gate-inheritance correction: `docs/strategies/sleeve_b_framework_evolution_stage_a_gate_inheritance.md` (commit `39970f1`)
- Master roadmap §10 (operator authority): governing document
- Kill actions reviewed (in commit order):
  - A2 basis: `docs/strategies/a2_kill_action.md` (commit `924a930`)
  - Sleeve B #1 xs-momentum: `docs/strategies/sleeve_b_xs_momentum_kill_action.md` (commit `f3e078e`)
  - Sleeve B #2 quality: `docs/strategies/sleeve_b_quality_kill_action.md` (commit `bf642d1`)
  - Sleeve B #3 vol-scaled momentum v1: `docs/strategies/sleeve_b_candidate_3_kill_action.md` (commit `bf0a23e`)
  - Sleeve B #4 vol-scaled momentum v2: `docs/strategies/sleeve_b_candidate_4_kill_action.md` (commit `5619d09`)

---

*Framework review for Sleeve B program, May 2026. Diagnostic verdicts: gates filter correctly (A1), candidate-generation has identified cluster blind spot (B2), premise too soon to assess (C3). Recommendations conditional on verdicts: no gate changes, one Q0 sub-criterion addition, run candidate #5 with cluster awareness. Re-assess premise at candidate #6 or #7. Review is interpretive synthesis, not governance amendment.*
