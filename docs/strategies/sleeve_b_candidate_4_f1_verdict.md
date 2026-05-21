# Sleeve B Candidate #4 — F1 sub-gate verdict memo

**Status:** D3 of 5 Stage B engineering deliverables
**Date:** 2026-05-21
**Subordinate to:** `docs/strategies/sleeve_b_candidate_4_preregistration.md` (commit `59c1156`)
**Consumes:** `tests/fixtures/sleeve_b/vol_scaled_momentum_run_log.jsonl` (committed at `ef788b7`)
**F1 family verdict:** **FAIL**

---

## 0. Summary

| Sub-gate | Description | Verdict |
|---|---|---|
| F1.1 | Vol estimator stability (vol-of-vol) | **PASS_CLEAN** |
| F1.2 | Rank churn (top-bucket retention) | **PASS_CLEAN** |
| F1.3 | Numerator-vs-denominator variance contribution | **PASS_CLEAN** |
| F1.4 | Window sensitivity | **FAIL** |

**Overall F1 family: FAIL**

Per pre-registration §5: any F1 sub-gate FAIL is candidate-kill-capable regardless of Sharpe gate outcome.

---

## 1. F1.1 — Vol estimator stability

Per pre-reg §5.F1.1: per-asset rolling 60d stdev of 45d realized-vol
time series, divided by rolling mean. Cross-sectional median across assets.

Operationalization: 9 weekly samples per rolling window (≈ 63 days),
stdev/mean per window, median across windows per asset, then median across assets.

| Threshold | Classification |
|---|---|
| > 0.6 | FAIL |
| 0.4–0.6 | PASS_WARNING |
| ≤ 0.4 | PASS_CLEAN |

**Result:** cross-sectional median vol-of-vol = `0.1380`

- Per-asset count: 30
- Per-asset min: 0.0834
- Per-asset max: 0.3165

### Per-asset vol-of-vol (sorted)

| Symbol | vol-of-vol |
|---|---|
| HYPEUSDT | 0.0834 |
| TAOUSDT | 0.0856 |
| ENAUSDT | 0.0884 |
| NEARUSDT | 0.1119 |
| AVAXUSDT | 0.1225 |
| ENJUSDT | 0.1234 |
| SOLUSDT | 0.1278 |
| ZECUSDT | 0.1291 |
| FILUSDT | 0.1304 |
| ETHUSDT | 0.1326 |
| 1000PEPEUSDT | 0.1330 |
| DOGEUSDT | 0.1340 |
| LINKUSDT | 0.1351 |
| DOTUSDT | 0.1361 |
| SUIUSDT | 0.1377 |
| BTCUSDT | 0.1384 |
| ONTUSDT | 0.1401 |
| BCHUSDT | 0.1462 |
| PIPPINUSDT | 0.1485 |
| ADAUSDT | 0.1611 |
| BNBUSDT | 0.1739 |
| RIVERUSDT | 0.1955 |
| SIRENUSDT | 0.1966 |
| ARIAUSDT | 0.2010 |
| XRPUSDT | 0.2033 |
| STOUSDT | 0.2190 |
| PAXGUSDT | 0.2539 |
| TRUMPUSDT | 0.2583 |
| RAVEUSDT | 0.2619 |
| NOMUSDT | 0.3165 |

**F1.1 verdict: PASS_CLEAN**

---

## 2. F1.2 — Rank churn

Per pre-reg §5.F1.2: fraction of long bucket retained week-over-week,
averaged across all rebalance transitions. Uses median for robustness.

| Threshold (median retention) | Classification |
|---|---|
| < 0.40 | FAIL |
| 0.40–0.55 | PASS_WARNING |
| ≥ 0.55 | PASS_CLEAN |

**Result:** median retention = `0.7143`

- Mean retention: 0.7264
- Min retention: 0.3333
- Max retention: 1.0000
- Number of transitions: 156

**F1.2 verdict: PASS_CLEAN**

---

## 3. F1.3 — Numerator-vs-denominator variance contribution

Per pre-reg §5.F1.3: 'Decompose the variance of the ranked score across
the cross-section at each rebalance date into momentum-numerator variance,
vol-denominator variance, and interaction. Compute the fraction of total
cross-sectional score variance attributable to the momentum numerator.'

### Operationalization (not pre-registration-locked, documented here)

Counterfactual decomposition. At each rebalance:

```
var_actual         = Var(momentum_i / vol_i)              cross-sectional
var_constant_vol   = Var(momentum_i / mean(vol))          replace vols with xs-mean
fraction_momentum  = var_constant_vol / var_actual
```

Interpretation: if `fraction_momentum` ≈ 1, varying vol added little
cross-sectional information — momentum alone explains the score dispersion.
If `fraction_momentum` ≈ 0, the vol denominator drove the dispersion and
the construction is not actually momentum.

Median across rebalance dates.

Why this operationalization: the pre-registration framed F1.3 as 'does the
numerator do meaningful work?' The counterfactual directly answers that
question without requiring log-linearization assumptions (which fail when
momentum is negative). Three alternatives considered: log decomposition
(unworkable for negative momentum), delta-method linearization (needed for
ratio statistics in classical stats but harder to interpret), counterfactual
(chosen).

| Threshold (fraction explained by momentum) | Classification |
|---|---|
| < 0.5 | FAIL (vol denominator dominates) |
| 0.5–0.65 | PASS_WARNING |
| > 0.65 | PASS_CLEAN |

**Result:** median fraction explained by momentum = `1.6160`

- Mean fraction: 2.3447
- Min fraction: 0.4100
- Max fraction: 19.7326
- Number of rebalances: 157

**F1.3 verdict: PASS_CLEAN**

---

## 4. F1.4 — Window sensitivity

Per pre-reg §5.F1.4: re-run backtest with four parameter variants and
compute `(max - min) / median` Sharpe across the variants.

Variants:
- (momentum=15d, vol=45d)
- (momentum=45d, vol=45d)
- (momentum=30d, vol=30d)
- (momentum=30d, vol=60d)

Sensitivity computed across the four variants (baseline 30/45 reported separately).

| Threshold | Classification |
|---|---|
| > 0.30 | FAIL |
| 0.15–0.30 | PASS_WARNING |
| ≤ 0.15 | PASS_CLEAN |

**Result:** sensitivity = `0.7109`

### Variant Sharpe table

| (momentum_days, vol_days) | Sharpe |
|---|---|
| (15, 45) | 1.4708 |
| (45, 45) | 0.8832 |
| (30, 30) | 0.8073 |
| (30, 60) | 0.9831 |
| (30, 45) — baseline (reference) | 1.2511 |

- max Sharpe: 1.4708
- min Sharpe: 0.8073
- median Sharpe (across variants): 0.9332

**F1.4 verdict: FAIL**

---

## 5. Implications for D4 and D5

F1 family FAIL is candidate-kill-capable per pre-reg §5/§9.
D5 (verdict memo) must classify this candidate as a kill regardless
of B3 Sharpe gate outcome. D4 (F3 evaluator) still runs to complete
the evidence record, but D5's classification is constrained by this F1 FAIL.

D5 cannot be drafted until D4 has run. F1 evidence alone is not a verdict.

---

## 6. References

- Candidate #4 pre-registration: `docs/strategies/sleeve_b_candidate_4_preregistration.md` (commit `59c1156`)
- D1 signal module: commit `8cc69fc`
- D2 backtest engine: commit `3e06210`
- D2 artifacts (this memo consumes): commit `ef788b7`
- Portfolio interpretation memo: commit `689ddd9`
