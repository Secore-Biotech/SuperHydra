# Sleeve B Candidate #4 — F3 sub-gate verdict memo

**Status:** D4 of 5 Stage B engineering deliverables
**Date:** 2026-05-21
**Subordinate to:** `docs/strategies/sleeve_b_candidate_4_preregistration.md` (commit `59c1156`)
**Consumes:** `tests/fixtures/sleeve_b/vol_scaled_momentum_run_log.jsonl` (committed at `ef788b7`)
**F3 family verdict:** **PASS_CLEAN**

---

## 0. Summary

| Sub-gate | Description | Verdict |
|---|---|---|
| F3.1 | Long-bucket vol concentration | **PASS_CLEAN** |
| F3.2 | BTC/ETH joint dominance | **PASS_CLEAN** |
| F3.3 | Pure low-vol return attribution | **PASS_CLEAN** |

**Overall F3 family: PASS_CLEAN**

Per pre-registration §6: any F3 sub-gate FAIL is candidate-kill-capable
regardless of Sharpe gate outcome. F3.3 in particular tests whether the
candidate is economically what it claims to be (volatility-scaled momentum)
or whether returns are explained by an alternative factor (low-vol carry).

---

## 1. F3.1 — Long-bucket vol concentration

Per pre-reg §6.F3.1: `median(long_bucket_vol) / median(universe_vol)`
at each rebalance, mean across rebalance dates.

Low values indicate the long bucket is systematically lower-vol than the
universe — a sign the construction is implicitly tilting low-vol regardless
of its momentum claim.

| Threshold (mean ratio across rebalances) | Classification |
|---|---|
| < 0.60 | FAIL |
| 0.60–0.80 | PASS_WARNING |
| ≥ 0.80 | PASS_CLEAN |

**Result:** mean ratio = `1.1073`

- Median ratio: 1.0639
- Min ratio: 0.7614
- Max ratio: 1.9146
- Number of rebalances: 157

**F3.1 verdict: PASS_CLEAN**

---

## 2. F3.2 — BTC/ETH joint dominance

Per pre-reg §6.F3.2: fraction of rebalance dates where BOTH BTC and ETH
appear in the long bucket simultaneously.

High values indicate the construction systematically favors the two
largest-cap names — a sign the strategy is closer to a market-cap-weighted
blue-chip portfolio than a genuine cross-sectional momentum factor.

| Threshold (joint fraction) | Classification |
|---|---|
| > 0.70 | FAIL |
| 0.40–0.70 | PASS_WARNING |
| ≤ 0.40 | PASS_CLEAN |

**Result:** joint fraction = `0.2293`

- Joint count (BTC AND ETH in long bucket): 36
- BTC only: 51
- ETH only: 25
- Neither: 45
- Total rebalances: 157

**F3.2 verdict: PASS_CLEAN**

---

## 3. F3.3 — Pure low-vol return attribution

Per pre-reg §6.F3.3: decompose total OOS return into pure-momentum,
pure-low-vol, and interaction components.

### Operationalization (not pre-registration-locked, documented here)

Counterfactual attribution via three parallel long-short backtests over
the same OOS window, same eligibility filter, same portfolio construction:

- **Candidate #4 (actual):** long top-third by `momentum/vol`, short bottom-third
- **Pure momentum:** long top-third by 30d simple return alone, short bottom-third
- **Pure low-vol:** long bottom-third by 45d realized vol, short top-third

All three use the same long-short construction (apples-to-apples) and
portfolio-level vol-target overlay per the Reading A lock at `689ddd9`.

### Gating basis — arithmetic weekly-summed returns

F3.3 verdict uses arithmetic attribution because additive decomposition
is mathematically clean across parallel weekly P&L series:

```
arith_total       = Σ_t (weekly_net_return_c4_t)
arith_pure_mom    = Σ_t (weekly_net_return_pure_momentum_t)
arith_pure_lv     = Σ_t (weekly_net_return_pure_low_vol_t)
arith_interaction = arith_total - arith_pure_mom - arith_pure_lv

F3.3 metric = arith_pure_lv / arith_total
```

Fractions sum to exactly 1.0 by construction. The arithmetic sum is
not the same quantity as compounded NAV return (which compounds across
weeks), but for *attribution* the arithmetic sum is the right object
because it preserves additivity across components.

**NAV-endpoint cumulative returns are reported in §3.b as descriptive
context only.** The NAV-endpoint decomposition (subtraction of compounded
endpoints) does not preserve clean additive interaction interpretation
for compounded series and is NOT the gating basis.

| Threshold (pure low-vol fraction of arithmetic total) | Classification |
|---|---|
| > 0.5 | FAIL (low-vol explains > half of returns) |
| 0.3–0.5 | PASS_WARNING |
| ≤ 0.3 | PASS_CLEAN |

### 3.a Arithmetic attribution (gating)

**Result:** pure low-vol contribution = `-0.7194` of arithmetic total

| Component | Fraction of arithmetic total | Arithmetic sum return |
|---|---|---|
| Pure momentum | +0.2361 | +51.5571% |
| Pure low-vol | -0.7194 | -157.0765% |
| Interaction (residual) | +1.4833 | +323.8611% |
| **Total (candidate #4)** | **+1.0000** | **+218.3418%** |

Fractions sum to exactly 1.0 by construction. Negative fractions indicate
a component is offsetting (its contribution to the candidate's total is
negative).

### 3.b NAV-endpoint cumulative returns (descriptive only)

Compounded cumulative returns for each parallel backtest, for context.
These describe what each strategy would have earned on a compounded basis
but are NOT used for the F3.3 verdict — see §3.a for gating.

| Strategy | Cumulative NAV return |
|---|---|
| Candidate #4 (actual) | +503.1584% |
| Pure momentum (long-short) | +28.4213% |
| Pure low-vol (long-short) | -88.3147% |

These cannot be additively decomposed: a subtraction like
`nav_total − nav_pure_mom − nav_pure_lv` produces a number but it is not
a faithful interaction term across compounded series. The qualitative
reading nonetheless agrees with §3.a: pure low-vol's cumulative NAV return
is negative, confirming the candidate is not disguised low-vol carry.

**F3.3 verdict: PASS_CLEAN**

---

## 4. Implications for D5

F3 family PASS_CLEAN. F1 family already FAIL at `78f746b` is the
kill-capable failure. F3 result clears the misattribution concern —
the candidate fails on construction fragility, not on being disguised
low-vol carry.

D5 (final verdict memo + kill action) follows in the next deliverable.
D5 reads this verdict alongside D2 (raw metrics, `ef788b7`) and D3 (F1
verdict, `78f746b`) to produce the binding kill action.

---

## 5. References

- Candidate #4 pre-registration: `docs/strategies/sleeve_b_candidate_4_preregistration.md` (commit `59c1156`)
- Portfolio interpretation memo (Reading A): commit `689ddd9`
- D1 signal module: commit `8cc69fc`
- D2 backtest engine: commit `3e06210`
- D2 artifacts (this memo consumes): commit `ef788b7`
- D3 F1 verdict (FAIL on F1.4 window sensitivity): commit `78f746b`
