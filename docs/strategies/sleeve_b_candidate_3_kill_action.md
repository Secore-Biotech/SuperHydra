# Sleeve B Candidate #3 — Kill action

**Candidate:** Volatility-scaled momentum (signal-level scaling)
**Kill date:** 2026-05-16
**Stage at kill:** Stage A, before A1/A2 numerical computation
**Kill mode:** Governance-design mismatch (Stage A A2 inherited gate incompatibility)
**Killing gate:** A2 — temporal stability of eligible universe
**Subordinate to:** `docs/strategies/sleeve_b_candidate_3_preregistration.md` (commit `555339e`)

---

## 0. Summary

Candidate #3 is formally shelved at Stage A before A1 and A2 are computed numerically. The candidate did not fail on Sharpe, drawdown, signal stability, attribution, or any property of the volatility-scaled momentum construction itself. The volatility-scaled momentum signal was never evaluated. Stage B was never reached.

The candidate failed because the inherited Stage A A2 gate (temporal stability of the eligible universe, spread ≤ 6) is structurally incompatible with the frozen-universe-projected-backward construction defined in the master Sleeve B pre-registration at commit `fe909bb`. The fixture itself proves the kill is unavoidable: the eligible universe grows from 16 names listed by OOS start (2023-04-15) to 30 names listed by OOS end (2026-04-15), implying a minimum spread of 14 — more than 2× the pre-registered A2 kill threshold.

This is a new category of kill in the SuperHydra Sleeve B program:

| Sleeve | Stage of kill | Kill mode |
|---|---|---|
| A2 (perp-vs-spot basis) | Paper (`924a930`) | Signal absence |
| Sleeve B #1 (xs-momentum) | OOS backtest (`f3e078e`) | Construction fragility |
| Sleeve B #2 (fee-yield quality) | Stage A Phase 1 (`bf642d1`) | Data governance |
| Sleeve B #3 (vol-scaled momentum) | Stage A pre-computation (this kill) | **Governance-design mismatch** |

The framework operating correctly under anti-cherry-pick discipline kills the candidate. The framework evolution that follows (committed separately) addresses the design mismatch prospectively.

---

## 1. Sequence of evidence

**1.1** Candidate #3 cleared Q0 with PASS_CLEAN (commit `78b110d`) and was pre-registered with full Q1/Q2/Q3 lock at commit `555339e`. Construction: `score_i = trailing_30d_return_i / realized_45d_vol_i`. The binding lookback for eligibility is 45 days (longer of momentum 30d and vol 45d).

**1.2** The frozen universe fixture at `tests/fixtures/sleeve_b/universe_top30_20260415.json` (commit `2af9981`) contains 30 names with the following onboard-date distribution (all dates ISO 8601):

```
2019-09-25: 16 names (Binance USDT-M perp launch cohort)
2023-05-03: 1 name
2023-05-05: 1 name
2024-04-02: 1 name
2024-04-11: 1 name
2025-01-18: 1 name
2025-01-24: 1 name
2025-03-22: 1 name
2025-03-27: 1 name
2025-04-12: 1 name
2025-05-30: 1 name
2025-09-03: 1 name
2025-10-01: 1 name
2025-10-17: 1 name
2025-12-14: 1 name
```

Names listed by OOS start (2023-04-15): **16**. Names listed by OOS end (2026-04-15): **30**. Implied spread across the OOS window: **14**.

**1.3** Per the candidate #3 pre-registration §3.A2:

| Spread (max − min) of eligible count across rebalance dates | Classification |
|---|---|
| > 6 | **FAIL** — shelve |
| ≤ 6 | **PASS** |

**1.4** The implied spread (14) exceeds the FAIL threshold (6) by a factor of 2.33×. The 45-day listing-age delay applied to each onboard date can only delay an asset's first-eligible date relative to its onboard date — it cannot reduce the total count of names that achieve eligibility during the OOS window. The spread of 14 is therefore a *lower bound* on what A2 would compute against the actual rebalance-date schedule.

**1.5** The conclusion is provable from the fixture alone. Running the rebalance-date schedule through `eligible_at(universe, T, listing_delay_days=45)` would confirm the FAIL but cannot reverse it.

---

## 2. Stage A verdict

Per the candidate #3 pre-registration at commit `555339e`:

> **A2 — Temporal stability:** Spread > 6 → FAIL, shelve.

**Verdict: Stage A FAIL via A2.**

A2 alone is sufficient to fail Stage A under the pre-registered verdict logic. A1, A3, A4, A5 are not computed and are not required for the kill, per the pre-registered single-sub-gate-FAIL rule.

This is a clean pre-registered kill. No anti-cherry-pick concern. No mid-window threshold adjustment. No retroactive interpretation. A2 was specified, A2 failed, the candidate is shelved.

---

## 3. Classification — governance-design mismatch

This kill is **not** a signal invalidation. It is structurally distinct from prior kills:

| Kill | What was invalidated |
|---|---|
| A2 (basis) | The signal — basis didn't generate entries in normal regimes |
| xs-momentum | The construction — drawdown exceeded gate despite acceptable Sharpe |
| Fee-yield quality | The data infrastructure — PIT-grade source unavailable |
| **Vol-scaled momentum (this kill)** | **The governance design** — Stage A inherited gate incompatible with universe construction |

The volatility-scaled momentum signal was never evaluated. The construction was never tested. The data infrastructure was confirmed clean (Q0 PASS_CLEAN). What failed was the *interaction between an inherited Stage A gate and the master pre-registration's frozen-universe construction*.

Three properties of this kill that distinguish it from prior failures:

**3.1** The A2 gate's underlying assumption (quasi-stationary eligible universe) was reasonable for candidate #2's fee-yield coverage problem, where eligible-universe variation arose from *vendor data availability changes*. For candidate #3, eligible-universe variation arises from *deterministic asset listings in a known frozen-universe construction*. These are different mechanisms requiring different governance responses.

**3.2** The implied spread (14) is *intrinsic* to the master pre-registration's frozen-universe construction. It is not a property of volatility-scaled momentum. Any candidate using the same universe with a 30+-day lookback would face the same A2 outcome. The kill therefore reflects a constraint of the framework, not a defect of the signal family.

**3.3** The kill is provable from the fixture alone, without running any code. This is unprecedented in the program — the prior three kills required signal computation (basis), backtest (xs-momentum), or recon (fee-yield). Candidate #3 dies on document inspection. That is a sign the gate was inappropriate for this candidate type, not that the candidate was bad.

---

## 4. Why honor the kill anyway

Despite the framework-design mismatch, the kill is honored:

**4.1 Pre-registered constraints bind even when uncomfortable.** The credibility of the framework depends on this property. If A2 can be reinterpreted after seeing the result, every prior kill becomes suspect. xs-momentum's drawdown gate, fee-yield's A4 PIT gate, and A2's signal-absence verdict were all binding under the same discipline. Candidate #3 must bind under the same rule.

**4.2 Framework bugs still bind candidates until the framework evolves prospectively.** This is the discipline that prevents the failure mode where "the framework was wrong" becomes the default explanation for every kill. If governance can be overridden by post-hoc reinterpretation, the framework collapses into unfalsifiable reasoning. The kill is honored *because* the alternative is worse than the lost candidate.

**4.3 The lesson is preserved by separating the kill from the framework evolution.** The kill action (this document) ends candidate #3 cleanly. The framework evolution memo (committed separately) makes the corrected gate binding for candidate #4 onward. The two are kept distinct to preserve the audit trail: future readers can see exactly what was killed under what rule, and exactly when the framework evolved.

---

## 5. What this kill does NOT establish

**It does NOT establish that volatility-scaled momentum is a poor candidate.** The signal was never computed. F1 (vol-estimation instability) and F3 (low-vol concentration / misattribution) were never tested. The Q3 gate structure that this pre-registration produced may still be the right structure for a future similar candidate.

**It does NOT establish that the frozen-universe construction is wrong.** The master pre-registration's universe construction is appropriate for the program. The mismatch is between *this construction* and *this particular Stage A gate*, not with the universe construction in isolation.

**It does NOT close the door on re-trying volatility-scaled momentum.** A future candidate using a corrected A2 gate (or a different universe scheme that produces a quasi-stationary eligible set) could revisit the construction under the framework evolution memo's updated rules. Past kill does not bypass future gates; future candidate would face all gates fresh.

**It does NOT amend any prior governance artifact.** The master pre-registration at `fe909bb`, the Q0 memo at `cb9d975`, and the candidate #3 pre-registration at `555339e` remain binding as the historical record. This kill action is the close of candidate #3 under those rules.

---

## 6. Budget accounting

| Item | Budget | Consumed | Result |
|---|---|---|---|
| Stage A | 2 days | ~5 minutes (document inspection of fixture) | Underrun |
| Candidate #3 total | 38 days | ~3 hours (Q0 + Q1 + Q2 + Q3 + pre-reg + Stage A pre-computation) | ~37.9 days returned |
| Master Sleeve B budget | Per `fe909bb`, kill date 2026-06-27 | Substantively intact | — |

The fastest kill in the program. The framework's structural payoff: a candidate killed in minutes on document inspection rather than days on computation. Failure was made cheap by the framework's design — which is the principle Stage A and Q0 were created to enforce, even when the failure mode caught is a framework bug rather than a candidate defect.

---

## 7. Lessons made explicit

**7.1 Stage A inherited gates require per-candidate verification.** A2's temporal-stability gate was inherited from candidate #2 without checking whether its underlying assumption (quasi-stationary eligible universe) matched candidate #3's frozen-universe-projected-backward construction. The framework evolution memo (committed separately) addresses this prospectively.

**7.2 Q0 §3.5 (survivorship) is necessary but not sufficient.** Disclosing that survivorship is a known issue does not verify that the candidate's eligibility rule produces a temporally stable working universe. Q0 evolution should add a sub-criterion checking this before pre-registration is drafted.

**7.3 Some kills emerge from governance, not from signals.** The framework now has direct evidence that governance-design failures are real and can dominate signal-evaluation failures in failure-mode frequency. Future candidate selection should treat governance compatibility as a first-class evaluation axis alongside data and economics.

---

## 8. Next actions

**8.1** Commit this kill action document.

**8.2** Stop all candidate #3 work. No further Stage A computation, no Stage B work, no engineering against the candidate #3 pre-registration.

**8.3** Immediately follow with a framework evolution memo at `docs/strategies/sleeve_b_framework_evolution_stage_a_gate_inheritance.md` (filename to be confirmed in the memo session). The memo specifies:

- Stage A inherited gates must be verified per-candidate against the candidate's eligibility logic and the master universe construction
- A2 temporal-stability gate distinguishes endogenous instability (data variation) from deterministic universe expansion (listing growth in frozen-T-projected-backward universes)
- Q0 §3.5 sub-criterion update: survivorship-disclosed is necessary but not sufficient; temporal-stability-under-candidate-eligibility-rule must also be checked at Q0

**8.4** Candidate #4 selection opens in a separate session after the framework evolution memo is committed. Candidate #4 inherits the corrected framework prospectively.

**8.5** Nothing in this kill affects Sleeve A engine development, hydra-next migration work, or legacy strategy operation. Those proceed on their own tracks unchanged.

---

## 9. References

- Master Sleeve B pre-registration: `docs/strategies/sleeve_b_research_preregistration.md` (commit `fe909bb`)
- Q0 Data Viability Gate memo: `docs/strategies/sleeve_b_framework_evolution_q0_data_viability.md` (commit `cb9d975`)
- Candidate #3 Q0 selection memo: `docs/strategies/sleeve_b_candidate_3_selection_memo.md` (commit `78b110d`)
- Candidate #3 pre-registration: `docs/strategies/sleeve_b_candidate_3_preregistration.md` (commit `555339e`)
- Frozen universe fixture: `tests/fixtures/sleeve_b/universe_top30_20260415.json` (commit `2af9981`)
- Prior kill actions:
  - `docs/strategies/sleeve_b_xs_momentum_kill_action.md` (commit `f3e078e`)
  - `docs/strategies/sleeve_b_quality_kill_action.md` (commit `bf642d1`)
- Master roadmap §10 (operator authority): governing document for this kill decision

---

*Kill action for Sleeve B candidate #3 — volatility-scaled momentum. Stage A FAIL via A2 (temporal-stability gate). Classified as governance-design mismatch, not signal invalidation. The volatility-scaled momentum construction was never evaluated. Honored under pre-registered anti-cherry-pick discipline despite the gate-inheritance flaw being prospectively addressable. Framework evolution memo follows separately.*
