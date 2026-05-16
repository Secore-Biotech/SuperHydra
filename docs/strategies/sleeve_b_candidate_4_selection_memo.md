# Sleeve B Candidate #4 — Q0 selection memo

**Candidate family:** Volatility-scaled momentum (governance re-attempt)
**Q0 verdict:** PASS_CLEAN
**Date:** 2026-05-16
**Subordinate to:**
- `docs/strategies/sleeve_b_framework_evolution_q0_data_viability.md` (commit `cb9d975`)
- `docs/strategies/sleeve_b_framework_evolution_stage_a_gate_inheritance.md` (commit `39970f1`) — Q0 §3.5 update applies
**Master pre-registration:** `docs/strategies/sleeve_b_research_preregistration.md` (commit `fe909bb`)

---

## 0. Preamble — relationship to candidate #3

Candidate #4 reuses the signal construction from the closed Candidate #3 (volatility-scaled momentum), but is evaluated under the corrected Stage A inheritance framework introduced at commit `39970f1`.

**Candidate #3 remains permanently closed.** The pre-registration at commit `555339e`, the kill action at commit `bf0a23e`, and all associated artifacts are immutable historical records. They are not amended, reopened, or revised by this candidate.

**Candidate #4 is a new candidate with independent governance artifacts.** This memo is candidate #4's Q0 verdict, not candidate #3's. The Q1/Q2/Q3 locks for candidate #4 will be re-stated in candidate #4's own pre-registration document, not inherited live from candidate #3.

The shared signal construction is documented but the candidates are governance-independent. This is consistent with the framework evolution memo at `39970f1`, which allows candidate families to be re-evaluated under corrected governance.

---

## 1. Scope

This is a Q0 verdict memo under the Q0 Data Viability Gate (`cb9d975`) as amended by the Q0 §3.5 update in the Stage A gate-inheritance memo (`39970f1`). Q0 is a pre-Q1 screen. It authorises candidate #4 to enter Q1 metric-selection conversation. It does not authorise pre-registration drafting, Stage A work, or any backtest.

This is the **first Q0 evaluation under the updated framework** — specifically the first application of mandatory §3.5.b (temporal stability under candidate eligibility). The §3.5.b projection is documented in §2 below as the primary new evidence.

---

## 2. §3.5.b projection — temporal stability under candidate eligibility

Per the framework evolution memo §4, Q0 §3.5.b is mandatory and requires explicit demonstration that the candidate's eligibility rule, applied to the master universe construction, produces an eligible-universe trajectory whose endogenous residual would pass the candidate's A2 specification.

### 2.1 Candidate #4 eligibility rule

Inherited from the locked construction (carried from candidate #3 and to be re-locked in candidate #4's pre-registration):

```
Eligible at rebalance date T iff:
  (T − onboard_date).days ≥ 45
```

The 45-day threshold is the binding lookback (longer of momentum 30d and vol 45d).

### 2.2 Deterministic expansion D(t) projection

Computed from the frozen fixture `tests/fixtures/sleeve_b/universe_top30_20260415.json` (commit `2af9981`) by applying the 45-day listing-age rule to each asset's `onboard_date`.

Onboard-date distribution (30 names total):

```
2019-09-25: 16 names (Binance USDT-M perp launch cohort)
2023-05-03: 1 name      (eligible from 2023-06-17)
2023-05-05: 1 name      (eligible from 2023-06-19)
2024-04-02: 1 name      (eligible from 2024-05-17)
2024-04-11: 1 name      (eligible from 2024-05-26)
2025-01-18: 1 name      (eligible from 2025-03-04)
2025-01-24: 1 name      (eligible from 2025-03-10)
2025-03-22: 1 name      (eligible from 2025-05-06)
2025-03-27: 1 name      (eligible from 2025-05-11)
2025-04-12: 1 name      (eligible from 2025-05-27)
2025-05-30: 1 name      (eligible from 2025-07-14)
2025-09-03: 1 name      (eligible from 2025-10-18)
2025-10-01: 1 name      (eligible from 2025-11-15)
2025-10-17: 1 name      (eligible from 2025-12-01)
2025-12-14: 1 name      (eligible from 2026-01-28)
```

D(t) trajectory across OOS window 2023-04-15 → 2026-04-15:

```
D(2023-04-15) = 16   (only the 2019-09-25 cohort is past the 45-day delay)
D(2023-06-19) = 18   (first two 2023 listings become eligible)
D(2024-05-26) = 20   (two 2024 listings cleared)
D(2025-05-27) = 25   (five 2025 listings cleared)
D(2025-07-14) = 26
D(2025-10-18) = 27
D(2025-11-15) = 28
D(2025-12-01) = 29
D(2026-01-28) = 30
D(2026-04-15) = 30
```

D(t) is monotone non-decreasing. Total deterministic expansion across OOS: 30 − 16 = **14 names**.

### 2.3 Projected endogenous residual

At Q0, we do not know the *actual* eligible count C(t) ex-ante because the backtest has not run. But the projection logic is:

- D(t) captures the listing-driven component, computed deterministically from the fixture
- C(t) = D(t) + (any non-listing-driven eligibility changes during OOS)
- Non-listing-driven eligibility changes for a Binance USDT-M perp universe would include: delistings, prolonged trading halts, exchange suspensions, missing OHLCV days at rebalance
- None of these are present in the frozen fixture or known to have occurred for any of the 30 universe names during the OOS window
- Therefore the projected endogenous residual is **E(t) ≈ 0 across all t in OOS**

### 2.4 Projected A2 verdict

Per the corrected A2 in `39970f1` §2.2:

```
A2 — Temporal stability (corrected):
  max E − min E > 6   → FAIL
  max E − min E ≤ 6   → PASS
```

Projected: max E − min E ≈ 0 ≤ 6 → **PASS_CLEAN**.

The candidate passes A2 by construction under the corrected specification. If unexpected delistings occur during Stage A's actual computation of C(t), they will surface as non-zero endogenous residual and be caught at Stage A. The framework now distinguishes deterministic expansion (allowed, expected, 14 names across OOS) from endogenous instability (the actual concern, projected zero, verified at Stage A).

### 2.5 §3.5.b verdict

**§3.5.b PASS_CLEAN.** The deterministic-expansion projection is documented above. The candidate's eligibility rule produces a temporally compatible eligible-universe trajectory under the corrected A2 specification.

---

## 3. Sub-criterion verdicts (full Q0)

| Sub-criterion | Type | Verdict | Rationale |
|---|---|---|---|
| §3.1 PIT-clean data | Mandatory | **PASS_CLEAN** | Binance OHLCV is venue-native, immutable historical. Same as candidate #3 |
| §3.2 Budget feasibility | Mandatory | **PASS_CLEAN** | Zero recurring cost. Signal.py swap inside existing engine plumbing. Same as candidate #3 |
| §3.3 Paid-data exception | Conditional | N/A | Not invoked |
| §3.4 Taxonomy clarity | Mandatory | **PASS_CLEAN** | Momentum and volatility are settled definitions. Same as candidate #3 |
| §3.5.a Survivorship | Preferred | PASS | Frozen top-30 universe, status unchanged from candidates #1, #2, #3 |
| **§3.5.b Temporal stability** | **Mandatory (new)** | **PASS_CLEAN** | **D(t) projected; E(t) ≈ 0; spread of E ≤ 6 by construction (see §2)** |
| §3.6 Simple story | Preferred | PASS | Single mechanism (risk-budgeting); same as candidate #3 |

**Overall Q0 verdict: PASS_CLEAN.**

All four mandatory criteria (§3.1, §3.2, §3.4, §3.5.b) pass without warning. Both preferred criteria pass. No §3.3 exception invoked.

---

## 4. What this verdict authorises

**Authorised by this verdict:**

- Q1 metric-selection conversation for candidate #4 (which will largely re-lock candidate #3's Q1)
- Q2 dominant-failure-mode identification (largely re-lock candidate #3's Q2)
- Q3 kill-criterion structure design (largely re-lock candidate #3's Q3, with corrected A2 per `39970f1`)
- Pre-registration drafting after Q1/Q2/Q3 re-lock
- §2.5 inherited-gate verification table in the pre-registration

**Not authorised by this verdict:**

- Any code work
- Any signal computation
- Any backtest
- Any Stage A or Stage B activity
- Amendment of any prior governance artifact (candidate #3's pre-registration, kill action, or any framework memo)

---

## 5. Skeptical prior

Four kills now logged under pre-registered governance:

| # | Failure class |
|---|---|
| A2 (basis) | Signal absence |
| Candidate #1 (xs-momentum) | Construction fragility |
| Candidate #2 (fee-yield) | Data governance |
| Candidate #3 (vol-scaled momentum) | Governance-design mismatch |

Candidate #4's Q0 PASS_CLEAN confirms the candidate is *evaluable* under the corrected framework. It does not predict Stage A or Stage B success. The corrected A2 removes the governance-design failure mode that killed candidate #3; F1 (vol-estimation instability), F3 (low-vol concentration / misattribution), and standard Sharpe/drawdown gates remain to be cleared.

The skeptical prior on candidate-#4 success is appropriate. Candidate #3's signal construction was never empirically evaluated. Whether it actually works as a Sleeve B factor is now an open question for the first time, under a framework that is structurally capable of giving an honest answer.

---

## 6. References

- Q0 Data Viability Gate memo: `docs/strategies/sleeve_b_framework_evolution_q0_data_viability.md` (commit `cb9d975`)
- Stage A gate-inheritance memo (Q0 §3.5 update): `docs/strategies/sleeve_b_framework_evolution_stage_a_gate_inheritance.md` (commit `39970f1`)
- Master Sleeve B pre-registration: `docs/strategies/sleeve_b_research_preregistration.md` (commit `fe909bb`)
- Candidate #3 pre-registration (signal construction provenance): `docs/strategies/sleeve_b_candidate_3_preregistration.md` (commit `555339e`)
- Candidate #3 kill action (governance-design mismatch precedent): `docs/strategies/sleeve_b_candidate_3_kill_action.md` (commit `bf0a23e`)
- Frozen universe fixture: `tests/fixtures/sleeve_b/universe_top30_20260415.json` (commit `2af9981`)

---

*Q0 verdict memo for Sleeve B candidate #4 — volatility-scaled momentum (governance re-attempt). PASS_CLEAN on all mandatory criteria including the new §3.5.b temporal-stability projection. First Q0 evaluation under the updated framework (`39970f1`). Authorises Q1 metric-selection conversation. Candidate #3 remains permanently closed.*
