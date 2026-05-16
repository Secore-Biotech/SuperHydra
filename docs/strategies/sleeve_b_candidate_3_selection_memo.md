# Sleeve B Candidate #3 — Q0 selection memo

**Candidate family:** Risk-adjusted momentum / low-volatility hybrid
**Q0 verdict:** PASS_CLEAN
**Date:** 2026-05-16
**Subordinate to:** `docs/strategies/sleeve_b_framework_evolution_q0_data_viability.md` (commit `cb9d975`)
**Master pre-registration:** `docs/strategies/sleeve_b_research_preregistration.md` (commit `fe909bb`)

---

## 0. Scope

This is a Q0 verdict memo under the Q0 Data Viability Gate at commit `cb9d975`. Q0 is a pre-Q1 screen, not a pre-registration. It authorises candidate #3 to enter Q1 metric-selection conversation. It does not authorise pre-registration drafting, Stage A work, or any backtest.

This memo is short by design. The full sub-criterion verdicts are recorded in §2 below. Detailed reasoning lives in the conversation that produced this verdict (session 2026-05-16, after candidate #2 kill at commit `bf642d1`).

---

## 1. Working prior

Risk-adjusted momentum / low-volatility hybrid. Reviewer-locked at end of candidate #2 session. The prior was reverse-engineered from the kill modes of candidates #1 and #2:

- Candidate #1 (xs-momentum) died of construction fragility — Sharpe 1.38 with drawdown 25.92%. The working prior addresses this directly by introducing volatility-aware construction.
- Candidate #2 (fee-yield quality) died of data governance — no PIT-clean source available. The working prior avoids this by using Binance OHLCV exclusively.

This is evolution from failure classes, not overfitting to prior data. Specific hybrid form is a Q1 decision, not a Q0 decision.

---

## 2. Sub-criterion verdicts

| Sub-criterion | Type | Verdict | Rationale |
|---|---|---|---|
| §3.1 PIT-clean data | Mandatory | **PASS_CLEAN** | Binance OHLCV is venue-native, immutable historical, already cached in `data/ingestion/vendors/binance/` |
| §3.2 Budget feasibility | Mandatory | **PASS_CLEAN** | Zero recurring cost. Signal.py swap inside existing Sleeve B engine plumbing |
| §3.3 Paid-data exception | Conditional | N/A | Not invoked |
| §3.4 Taxonomy clarity | Mandatory | **PASS_CLEAN** | Momentum and volatility are settled definitions in finance literature. Hybrid form is a parameter choice (Q1), not a taxonomy ambiguity |
| §3.5 Survivorship | Preferred | PASS | Uses frozen top-30 universe from master pre-registration; survivorship status unchanged from candidates #1 and #2 |
| §3.6 Simple story | Preferred | PASS | Single mechanism (risk-budgeting); direct causal link to candidate #1's failure mode; literature support (Barroso-Santa-Clara 2015 and successors) |

**Overall Q0 verdict: PASS_CLEAN.**

All three mandatory criteria pass without warning. Both preferred criteria pass. No §3.3 exception invoked. Candidate #3 is authorised to enter Q1 metric selection.

---

## 3. What this verdict does and does not authorise

**Authorised by this verdict:**

- Q1 metric-selection conversation (specific hybrid form: volatility-scaled momentum vs regime-gated momentum vs two-factor composite vs residual momentum)
- Q2 dominant-failure-mode identification
- Q3 kill-criterion structure design
- Pre-registration drafting after Q1/Q2/Q3 lock

**Not authorised by this verdict:**

- Any code work
- Any signal computation
- Any backtest
- Any Stage A or Stage B activity
- Amendment of Q0 memo, master pre-registration, or any prior candidate pre-registration

---

## 4. Skeptical prior

Three kills now logged under pre-registered governance. Q0 PASS_CLEAN confirms the candidate is evaluable, not that it will pass downstream gates. Candidate #1 cleared every Q0-equivalent screen and still died at OOS evaluation; candidate #3 might do the same. The framework treats this as expected, not as failure.

---

## 5. References

- Q0 Data Viability Gate memo: `docs/strategies/sleeve_b_framework_evolution_q0_data_viability.md` (commit `cb9d975`)
- Master Sleeve B pre-registration: `docs/strategies/sleeve_b_research_preregistration.md` (commit `fe909bb`)
- Candidate #2 kill action: `docs/strategies/sleeve_b_quality_kill_action.md` (commit `bf642d1`)
- Candidate #1 kill action: `docs/strategies/sleeve_b_xs_momentum_kill_action.md` (commit `f3e078e`)

---

*Q0 verdict memo for Sleeve B candidate #3 — risk-adjusted momentum / low-volatility hybrid. PASS_CLEAN. Authorises Q1 metric-selection conversation. Subordinate to Q0 memo at commit `cb9d975`.*
