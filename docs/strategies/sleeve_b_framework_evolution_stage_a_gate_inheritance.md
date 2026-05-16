# Sleeve B framework evolution — Stage A gate inheritance

**Status:** Framework evolution memo — binding for candidate #4 onward
**Subordinate to:**
- `docs/strategies/sleeve_b_research_preregistration.md` (commit `fe909bb`) — master
- `docs/strategies/sleeve_b_framework_evolution_q0_data_viability.md` (commit `cb9d975`) — Q0 gate
**Date:** 2026-05-16
**Origin:** Candidate #3 governance-design-mismatch kill (`docs/strategies/sleeve_b_candidate_3_kill_action.md`, commit `bf0a23e`)

---

## 0. Scope and authority

This memo is a **subordinate framework evolution**, not an amendment.

- It does not modify the master Sleeve B pre-registration at commit `fe909bb`.
- It does not modify the Q0 Data Viability Gate memo at commit `cb9d975`.
- It does not modify any candidate-specific pre-registration commit (`4d307e6`, `555339e`).
- It does not apply retroactively to candidates #1, #2, or #3 — all closed under their own pre-registrations.
- It is binding for Sleeve B candidate selection from candidate #4 onward.

Where this memo is more restrictive than the master or the Q0 memo, this memo governs for future candidates. Where it is silent, those govern. The master and the Q0 memo remain immutable.

This memo is itself subject to anti-cherry-pick discipline. Once committed, it is binding until a successor framework evolution memo is committed under the same discipline. No mid-candidate amendment.

---

## 1. Why this memo exists

Candidate #3 (volatility-scaled momentum) was killed at Stage A before A1/A2 numerical computation. The kill mechanism was a structural incompatibility between the inherited A2 temporal-stability gate (spread ≤ 6, inherited from candidate #2) and the master pre-registration's frozen-universe-projected-backward construction. The implied spread across the OOS window was 14, more than double the FAIL threshold.

The kill was honored under pre-registered anti-cherry-pick discipline. But the cause was a *framework-design failure*, not a *candidate defect*. The volatility-scaled momentum signal was never evaluated. The construction was never tested.

The structural lesson:

> **A Stage A gate's threshold is meaningful only against the universe construction and eligibility rule the candidate will actually use. Gates inherited across candidates without verification of that compatibility can fail-kill innocent candidates on framework grounds rather than candidate grounds.**

This memo formalizes that lesson into three concrete changes:

1. **A2 specification rewrite** — distinguish endogenous instability from deterministic universe expansion
2. **Inherited-gate verification addendum** — every candidate pre-registration must declare a verification status per Stage A sub-gate
3. **Q0 §3.5 update** — survivorship disclosure is necessary but not sufficient; the temporal trajectory of the eligible universe under the candidate's eligibility rule must be verified at Q0

---

## 2. Component 1 — A2 specification rewrite

### 2.1 The problem with the inherited A2

The candidate #2 A2 gate read:

```
A2 — Temporal stability:
  spread > 6   → FAIL, shelve
  spread ≤ 6   → PASS
```

where spread = max − min of eligible-universe count across rebalance dates.

This was reasonable for candidate #2's eligibility mechanism (data availability across fee-yield protocols at rebalance dates). Endogenous variation in that universe came from *vendor adapter changes and protocol-onboarding lag in DeFiLlama*, which can in principle be small if the data infrastructure is mature.

It was structurally incompatible with candidate #3's eligibility mechanism (listing-age delay applied to a frozen-T-projected-backward universe). Variation in that universe comes from *known, deterministic Binance perp listings during the OOS window*. With 16 names listed by OOS start and 30 by OOS end, the spread cannot be reduced below 14 without changing the universe construction.

The A2 gate was testing for a property (quasi-stationary eligible universe) that the master pre-registration's universe construction *cannot satisfy* under candidate #3's eligibility rule.

### 2.2 The corrected A2 specification

The corrected A2 distinguishes two sources of spread:

**Deterministic expansion (D):** the change in eligible-universe count predicted purely from the frozen fixture's onboard dates and the candidate's eligibility rule. This is computable from the fixture *before any backtest*, deterministically, with no signal computation. For a frozen-T-projected-backward universe, this captures listing-driven growth.

**Endogenous instability (E):** the residual spread *after subtracting the deterministic-expansion trajectory*. This captures any variation that is *not* explained by known listings under the candidate's eligibility rule — e.g., delistings, suspensions, missing OHLCV days, or any other non-listing-driven eligibility change.

The corrected gate:

```
A2 — Temporal stability (corrected):

  Step 1 — Compute deterministic expansion trajectory D(t) for t in rebalance dates,
           using only the frozen fixture's onboard_date field and the candidate's
           eligibility rule (e.g. listing_age_days >= lookback_days).

  Step 2 — Compute actual eligible-universe count C(t) for t in rebalance dates.

  Step 3 — Compute endogenous residual: E(t) = C(t) - D(t).

  Step 4 — Apply threshold to E:
    max E − min E    > 6   → FAIL, shelve
    max E − min E    ≤ 6   → PASS
```

The threshold (≤ 6) is preserved from candidate #2. What changes is *what the threshold is applied to* — the residual after subtracting deterministic expansion, not the raw spread.

### 2.3 What this catches and what it doesn't

**Catches (endogenous, the real concern):**
- Unexplained eligibility-count fluctuation
- Delistings, suspensions, missing OHLCV days
- Vendor data-availability changes (in cases where Stage A depends on external data, e.g., candidate #2's fee-yield)
- Any non-listing-driven shift in the eligible universe

**Does not catch (deterministic, expected):**
- Listing growth in a frozen-T-projected-backward universe
- Any other variation that is *predictable from the fixture before any backtest runs*

The change is conceptually simple: we test for *unexpected* universe instability, not for *all* universe variation. A candidate whose eligible universe grows from 16 to 30 names in a known way over the OOS window is not a candidate with an unstable universe — it is a candidate with a *growing* universe whose growth is fully predictable.

### 2.4 Edge cases

**Edge case 1 — A candidate using a universe construction with no deterministic expansion.** For such a candidate, D(t) is constant across the OOS window, E(t) = C(t) − D(t) = C(t) − constant, and `max E − min E = max C − min C` exactly. The corrected gate reduces to the original gate. Backward-compatible for static universes.

**Edge case 2 — A candidate using a non-frozen universe construction.** D(t) would have to be derived from whatever rule governs the candidate's universe membership, not from a fixture. The inherited-gate verification (Component 2) would require explicit documentation of how D(t) is computed for that candidate. If the candidate cannot compute D(t) deterministically before backtest, the A2 gate cannot be applied as written, and the verification must declare NOT_APPLICABLE.

**Edge case 3 — D(t) is itself unstable.** Possible if the fixture has noisy onboard dates or if the eligibility rule is non-trivially time-dependent. Implementation guidance: D(t) is computed once, at the start of Stage A, from the frozen fixture only. It is not re-computed mid-window. If the implementation cannot produce a stable D(t), that is itself a Stage A failure and must be surfaced before A2 is evaluated.

---

## 3. Component 2 — Inherited-gate verification addendum

### 3.1 The principle

Every candidate pre-registration must include, before Stage A sub-gates are specified, a verification table declaring the inheritance status of each inherited Stage A sub-gate. The verification confirms that the inherited threshold's underlying assumption is appropriate for the candidate's universe construction and eligibility rule.

This addendum applies to A1, A2, A3, A4, A5, and any future Stage A sub-gate added by a successor framework evolution memo. It also applies to F-family gates if they are inherited across candidates (which they should not be by default — F-gates are typically candidate-specific).

### 3.2 The three verification statuses

Each inherited sub-gate is declared as one of:

| Status | Meaning | Required documentation |
|---|---|---|
| **PASS_DIRECT** | The inherited gate's threshold and underlying assumption are unchanged and remain appropriate for this candidate without modification. | One-line confirmation referencing the prior pre-registration the gate was inherited from. |
| **PASS_ADAPTED** | The inherited gate's underlying assumption requires modification for this candidate. The threshold or evaluation method has been adapted. | Brief paragraph (≤ 5 lines) explaining the adaptation and why it is necessary. Adapted threshold or method is specified in the candidate pre-registration's sub-gate section. |
| **NOT_APPLICABLE** | The inherited gate is structurally irrelevant for this candidate. | One-line statement explaining why the gate does not apply. The sub-gate is explicitly omitted from the candidate's Stage A. |

### 3.3 What PASS_DIRECT requires

PASS_DIRECT is the default and the simplest. It declares: *"This gate worked for the prior candidate; nothing in the current candidate's construction or eligibility changes the gate's relevance."*

Example wording:

```
A4 (PIT discipline): PASS_DIRECT
Inherited from candidate #2 pre-registration (commit 4d307e6). Binance OHLCV
is venue-native immutable historical; the PIT discipline gate applies
unchanged.
```

PASS_DIRECT is *not* a free pass. It is an affirmative claim that the operator has considered the gate's underlying assumption against the candidate's construction and confirmed compatibility. The one-line statement is the audit artifact.

### 3.4 What PASS_ADAPTED requires

PASS_ADAPTED declares: *"This gate's underlying assumption does not hold for the current candidate without modification, so the gate has been adapted."*

The adaptation must be:
- Justified by candidate-specific reasoning (not "I want this gate to be friendlier")
- Specified concretely in the candidate's Stage A section
- Backward-compatible with the inherited gate's *purpose* (the new gate must catch the same class of failure the old gate caught, in a way appropriate to the new candidate)

Example wording (for what candidate #3 should have done, retrospectively, had this memo existed):

```
A2 (temporal stability): PASS_ADAPTED
Inherited from candidate #2 pre-registration (commit 4d307e6). The original
gate applies a spread threshold to raw eligible-universe count. For candidate #3's
frozen-universe-projected-backward construction with a 45-day lookback rule,
raw spread reflects deterministic listing growth, not endogenous instability.
The corrected gate applies the threshold to residual spread after subtracting
deterministic expansion. Specification in §3.A2 of this pre-registration.
```

This is the verification step that would have caught candidate #3's mismatch before pre-registration commit.

### 3.5 What NOT_APPLICABLE requires

NOT_APPLICABLE declares: *"This gate is structurally irrelevant for this candidate."*

Example wording (from candidate #3's pre-registration, which got this right for A3):

```
A3 (source agreement): NOT_APPLICABLE
Single-venue construction (Binance), no cross-source comparison required.
The candidate #2 A3 reformulation does not apply here.
```

NOT_APPLICABLE means the sub-gate is omitted from Stage A entirely for that candidate. It does not mean "the gate passes trivially" — that would be PASS_DIRECT. It means "the gate's underlying purpose has no analog in this candidate's construction."

### 3.6 Verification table location

The verification table appears in the candidate pre-registration at a fixed position: **immediately after Section 2 (construction lock / parameters) and before Section 3 (Stage A specification)**.

For consistency, the table format is:

```markdown
## 2.5 Inherited-gate verification

| Sub-gate | Status | Reference / Adaptation note |
|---|---|---|
| A1 | PASS_DIRECT | Inherited from {prior commit}. {one-line confirmation} |
| A2 | PASS_ADAPTED | Inherited from {prior commit}. {one-paragraph adaptation note} |
| A3 | NOT_APPLICABLE | {one-line structural-irrelevance statement} |
| A4 | PASS_DIRECT | Inherited from {prior commit}. {one-line confirmation} |
| A5 | PASS_DIRECT | Inherited from {prior commit}. {one-line confirmation} |
```

This is mechanical, takes minutes per pre-registration, and produces an explicit audit artifact for every inheritance decision.

### 3.7 What this does NOT require

- It does not require re-deriving every gate from first principles
- It does not require new gate proposals
- It does not require code or computation — verification is conceptual
- It does not require operator approval beyond the standard pre-registration commit

It is a *discipline* layer, not a *gate* layer.

---

## 4. Component 3 — Q0 §3.5 update

### 4.1 Current Q0 §3.5 (per cb9d975)

> **§3.5 No hidden survivorship dependence — preferred (not mandatory)**
>
> The universe and the metric should not implicitly require survivorship-adjusted data. Where survivorship is unavoidable (most crypto universes have survivorship issues), the candidate family must have a path to honest survivorship disclosure consistent with the master pre-registration's frozen-universe approach.

### 4.2 Updated Q0 §3.5 (binding for candidate #4 onward)

The §3.5 update splits the current criterion into two parts and elevates the second part to **mandatory**:

**§3.5.a Survivorship disclosure — preferred (unchanged)**

Same as the current §3.5. Disclosed survivorship is acceptable; candidates that worsen the existing survivorship picture are blocked.

**§3.5.b Temporal-stability under candidate eligibility — mandatory (new)**

The candidate's eligibility rule, applied to the master universe construction, must produce an eligible-universe trajectory across the OOS window whose *endogenous residual* (per the corrected A2 specification in §2.2 of this memo) is compatible with the inherited or adapted A2 gate. Compatibility is verified by computing the deterministic expansion D(t) from the frozen fixture, computing the projected residual against the candidate's eligibility rule, and confirming the projected residual would pass the candidate's A2 specification.

This is the check that, had it existed, would have caught candidate #3 at Q0 rather than at Stage A.

### 4.3 What §3.5.b requires in practice

For a candidate selection conversation:

1. State the candidate's eligibility rule (e.g., "listing_age_days ≥ 45")
2. Compute deterministic expansion D(t) from the frozen fixture under that rule
3. Project the eligible-universe count C(t) (which equals D(t) at Q0 — no backtest yet)
4. Confirm C(t) − D(t) = 0 ⇒ projected residual is zero ⇒ A2 passes by construction
5. Document the projection in the Q0 selection memo

The projection in step 3 is honest: at Q0 we don't know what *actual* eligibility events will occur during the OOS window. But for a frozen-fixture-based universe, the deterministic component is fully known, and the residual against it is what A2 tests for. If the projection shows the candidate is going to fail A2 by construction (as candidate #3 would have shown), the candidate is declined at Q0.

### 4.4 Q0 verdict logic update

The updated Q0 §3.5 has two sub-criteria:

| Sub-criterion | Type | Effect |
|---|---|---|
| §3.5.a Survivorship disclosure | Preferred | Failure logged, candidate may still pass |
| §3.5.b Temporal stability under eligibility | **Mandatory** | Failure → Q0 FAIL |

The overall Q0 verdict logic in cb9d975 §4 is updated accordingly: §3.5.b joins the mandatory criteria alongside §3.1, §3.2, §3.4.

---

## 5. Worked example — applying this memo to candidate #3 retrospectively

This is illustrative only. The memo does not apply retroactively to candidate #3, which is closed under its own pre-registration and kill action.

**§2 corrected A2 applied to candidate #3:**

- Deterministic expansion D(t): computable from the fixture. With 45-day listing-age delay, D goes from ~16 (at OOS start) to ~30 (at OOS end), monotone non-decreasing.
- Actual eligible-universe count C(t): equals D(t) for candidate #3 (no delistings or suspensions occurred in the universe during OOS).
- Endogenous residual E(t) = C(t) − D(t) = 0 for all t.
- max E − min E = 0 ≤ 6 → **PASS**

Under the corrected A2, candidate #3 would have passed A2. The kill was correct under the original A2; the corrected A2 would not have killed.

**§3 verification addendum applied to candidate #3:**

Had this memo existed at the time of candidate #3's pre-registration drafting, the verification step would have required:

```
A2 (temporal stability): PASS_ADAPTED
[adaptation note as in §3.4 example above]
```

The act of writing this adaptation note would have forced the operator to confront the spread-of-14 issue *during pre-registration drafting*, before commit. The adaptation note could not have been honestly written without either (a) introducing the corrected A2, or (b) declaring the gate NOT_APPLICABLE. Either way, the mismatch would have been caught.

**§4 Q0 §3.5.b applied to candidate #3:**

Computing D(t) for the candidate #3 eligibility rule, the projection would have shown C(t) − D(t) = 0 with deterministic expansion of 14. Under the original (uncorrected) A2 specification, this projection would have failed Q0 §3.5.b. Under the corrected A2, the projection passes.

Either way, the issue would have surfaced at Q0 rather than at Stage A. This is the structural value of the §4 update.

---

## 6. What this memo does NOT change

- **Master pre-registration unchanged.** Universe construction at `fe909bb` remains binding.
- **Q0 memo unchanged structurally.** The Q0 framework at `cb9d975` is amended only in §3.5; the rest of Q0 (mandatory criteria, exception clauses, paid-data discipline) is unchanged.
- **Candidate-specific pre-registrations unchanged.** Candidates #1, #2, #3 are closed under their own rules. None of those documents are modified.
- **Retroactive judgments excluded.** This memo binds candidate #4 onward only.
- **Stage B unchanged.** This memo is Stage-A-scoped. The two-stage Stage A / Stage B architecture, the F-gate families, and the warning-conditional Stage B thresholds (introduced in candidate #2's pre-reg, carried by candidate #3's pre-reg) remain unchanged.
- **Override convention unchanged.** Session-discipline conventions from earlier in the program remain in effect under their existing soft-stated form.

---

## 7. What this memo protects against

**7.1 Inheritance mismatch** — The exact failure mode that killed candidate #3. Future inherited gates must be verified per-candidate. The PASS_DIRECT / PASS_ADAPTED / NOT_APPLICABLE schema makes the verification explicit and audit-friendly.

**7.2 A2 specifically failing innocent candidates** — The corrected A2 distinguishes endogenous instability from deterministic expansion, eliminating the structural impossibility that killed candidate #3.

**7.3 Q0-stage detection of inheritance problems** — The §3.5.b update catches mismatches at candidate selection time, before pre-registration is drafted. This is the cheapest possible detection point.

**7.4 Future governance bugs of similar shape** — While this memo cannot anticipate every future framework bug, the verification-addendum discipline creates a checkpoint at every pre-registration where the operator must affirmatively confirm gate-assumption compatibility. The next governance-design mismatch in a *different* gate would still be caught (or at least disclosed) before pre-registration commit.

---

## 8. What this memo does NOT protect against

Honest disclosure of limitations:

**8.1** A *new* Stage A sub-gate introduced in a future framework evolution might itself carry hidden inherited assumptions from its design context. The verification addendum only applies to gates *inherited* across candidates; the first instance of any new gate is itself a design act that should be reviewed under the same care as A2 originally was.

**8.2** Verification declarations can be wrong. An operator who writes "PASS_DIRECT" without genuinely considering the gate's assumption produces a flawed audit artifact. The discipline is honest only if the operator engages with it honestly. The framework cannot enforce conscientiousness, only structure.

**8.3** The corrected A2 still depends on the fixture's `onboard_date` field being honest. If the field's semantics change (e.g., a future fixture redefines "onboard" to mean something different), D(t) becomes mis-specified. This is a fixture-design concern outside this memo's scope but worth noting.

---

## 9. Required outputs for candidate #4 onward

Every Sleeve B candidate pre-registration committed after this memo must include:

**9.1** A Q0 selection memo that addresses §3.5.b explicitly, with the deterministic expansion D(t) projection documented.

**9.2** An inherited-gate verification table at §2.5 of the pre-registration, with each Stage A sub-gate declared as PASS_DIRECT, PASS_ADAPTED, or NOT_APPLICABLE.

**9.3** If any sub-gate is PASS_ADAPTED, the adapted specification in the candidate's Stage A section, with the adaptation note in the verification table cross-referencing the section.

**9.4** No code, computation, or backtest before §9.1, §9.2, §9.3 are complete and the pre-registration commits.

---

## 10. Future amendments

This memo binds candidate #4 onward. It may be superseded by a future framework evolution memo only under the same discipline: a separate document, subordinate to the master, committed before the candidate it governs, with explicit non-retroactive scope.

No in-place amendments to this memo. If the verification-addendum needs to change (e.g., a fourth status is needed), it changes via a successor memo.

---

## 11. References

- Master Sleeve B pre-registration: `docs/strategies/sleeve_b_research_preregistration.md` (commit `fe909bb`)
- Q0 Data Viability Gate memo: `docs/strategies/sleeve_b_framework_evolution_q0_data_viability.md` (commit `cb9d975`)
- Candidate #3 pre-registration: `docs/strategies/sleeve_b_candidate_3_preregistration.md` (commit `555339e`)
- Candidate #3 kill action: `docs/strategies/sleeve_b_candidate_3_kill_action.md` (commit `bf0a23e`)
- Candidate #2 pre-registration (source of inherited A2): `docs/strategies/sleeve_b_quality_preregistration.md` (commit `4d307e6`)
- Frozen universe fixture: `tests/fixtures/sleeve_b/universe_top30_20260415.json` (commit `2af9981`)
- Master roadmap §10 (operator authority): governing document for this framework evolution

---

*Sleeve B framework evolution memo addressing the governance-design mismatch surfaced by candidate #3's kill. Hybrid scope: A2 specification rewrite + inherited-gate verification addendum (PASS_DIRECT / PASS_ADAPTED / NOT_APPLICABLE) + Q0 §3.5.b temporal-stability sub-criterion. Subordinate to master (`fe909bb`) and Q0 memo (`cb9d975`). Binding for candidate #4 onward. Non-retroactive. The framework learns from the kill prospectively without reopening past kills.*
