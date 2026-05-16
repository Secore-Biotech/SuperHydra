# Sleeve B Candidate #3 — Volatility-scaled momentum pre-registration

**Status:** Pre-registration, binding
**Subordinate to:**
- `docs/strategies/sleeve_b_research_preregistration.md` (commit `fe909bb`) — master
- `docs/strategies/sleeve_b_framework_evolution_q0_data_viability.md` (commit `cb9d975`) — Q0 gate
**Q0 verdict:** PASS_CLEAN, logged at `docs/strategies/sleeve_b_candidate_3_selection_memo.md` (commit `78b110d`)
**Candidate identity:** Sleeve B candidate #3
**Primary construction:** Volatility-scaled momentum (signal-level scaling)
**Rebalance cadence:** weekly
**OOS window:** 2023-04-15 → 2026-04-15
**Frozen universe reference:** `tests/fixtures/sleeve_b/universe_top30_20260415.json` (commit `2af9981`)
**Prior candidates:** A2 (`924a930`, signal absence) · #1 xs-momentum (`f3e078e`, construction fragility) · #2 fee-yield quality (`bf642d1`, data governance)

---

## 0. Governance inheritance

This document inherits all governance constraints, anti-cherry-pick rules, budget limits, and promotion semantics from:

- Master Sleeve B pre-registration at commit `fe909bb`
- Q0 Data Viability Gate memo at commit `cb9d975`

This document specifies only the candidate-specific additions:

- Volatility-scaled momentum metric definition (Q1 lock)
- F1 (vol-estimation instability) and F3 (low-vol concentration / attribution) gate families (Q2 lock)
- Stage B threshold structure tightened on F1/F3 warnings (Q3 lock)
- Candidate-specific diagnostics

Nothing in this document amends or relaxes the master or Q0 memo. Where this document is silent, those govern. Where this document is more restrictive, this document governs.

---

## 1. Candidate identity and primary construction

**Candidate framing:** Risk-adjusted cross-sectional momentum. Specifically, volatility-scaled momentum with signal-level scaling — momentum is divided by realized volatility per asset *before* ranking, not after.

**Hypothesis (falsifiable):** Within the frozen top-30 USDT-perp universe, cross-sectional ranking of momentum-divided-by-realized-volatility produces positive risk-adjusted returns over weekly rebalance horizons, with construction-attributable signal (the vol denominator does meaningful work) and economic-attributable signal (the strategy is genuinely momentum, not pseudo-defensive low-vol carry).

**Primary signal:**

```
score_i = trailing_30d_return_i / realized_45d_vol_i
```

Where:
- `trailing_30d_return_i` is the simple return of asset `i` over the prior 30 trading days, computed from Binance daily close prices
- `realized_45d_vol_i` is the annualized standard deviation of daily log returns over the prior 45 trading days

**Why this metric (not other risk-adjusted constructions):**

- (A) signal-level scaling preserved the cleanest economic story (risk-adjustment as integrated metric, single-step ranking)
- (B) sizing-level scaling rejected: signal still selects fragile names, weakens attribution
- (C) volatility filter rejected: threshold boundary is a high-overfit surface
- (D) residual / beta-neutralized momentum rejected: regression design choices and residual-estimation instability are candidate #4 territory, not #3

Selection rationale logged in the Q1 conversation that produced this pre-registration.

---

## 2. Construction lock (B0 parameters)

These parameters are locked at pre-registration commit. No mid-window adjustment under anti-cherry-pick discipline. Any change requires a successor pre-registration with a new candidate number.

| Parameter | Value | Rationale |
|---|---|---|
| Momentum lookback | 30 days | Jegadeesh-Titman analog; crypto-appropriate horizon |
| Volatility lookback | 45 days | Reviewer-locked: smoother than 30d, more adaptive than 60d, avoids quarterly regime accidents |
| Rebalance cadence | Weekly | Inherited from xs-momentum and master pre-registration |
| Bucket construction | Top-third long, bottom-third equal-weight short | Inherited from xs-momentum |
| Position sizing | Equal weight within bucket | No vol scaling at sizing level (locked by Q1 selection of (A) over (B)) |
| Universe | Frozen top-30 per `universe_top30_20260415.json` | Inherited from master pre-registration |
| Cost model | Same as xs-momentum cost model | Inherited from candidate #1 pre-registration |

**Volatility lookback rationale (reviewer-locked):** The dominant failure mode F1 is vol-estimation instability. The choice of 45d is the explicit reviewer position that 60d is too slow for crypto regime transitions while 30d is too noisy. 45d is the smoothness-vs-adaptiveness optimum given the primary failure mode the candidate is being tested against.

---

## 3. Stage A — Coverage / metric definition gate

Stage A is preserved in full from candidate #2's template for structural consistency across candidates, even though most sub-gates are expected to pass trivially. The structural value of running Stage A is operator-confirmed cross-candidate parallelism and explicit verification that the candidate's data infrastructure is what it claims to be.

**Budget:** ≤ 2 calendar days (abbreviated from candidate #2's 10 days due to trivially-clean data infrastructure).

**Evaluation cadence:** All Stage A sub-gates evaluated at rebalance dates (weekly), not month-end snapshots.

### A1 — Static coverage

Eligible universe = top-30 frozen-universe names with available Binance OHLCV at each rebalance date. Names not yet listed at a given rebalance date are excluded for that date, with explicit survivorship disclosure per master pre-registration.

| Min eligible universe at any rebalance date | Classification |
|---|---|
| < 15 | **FAIL** — shelve |
| 15–17 | **PASS_WARNING** — Stage B constrained |
| ≥ 18 | **PASS_CLEAN** |

Expected outcome for vol-scaled momentum: PASS_CLEAN or PASS_WARNING depending on early-OOS listing dates for newer perp pairs.

### A2 — Temporal stability

| Spread (max − min) of eligible count across rebalance dates | Classification |
|---|---|
| > 6 | **FAIL** — shelve |
| ≤ 6 | **PASS** |

Expected: PASS once listing-date handling is verified.

### A3 — Source agreement

**Documented as inapplicable.** Single-venue construction (Binance), no cross-source comparison required. Candidate #2's A3 reformulation does not apply here.

### A4 — Point-in-time discipline

| PIT availability | Classification |
|---|---|
| Binance kline endpoint immutable historical, no backfill mechanism documented | **PASS_CLEAN** (expected) |

If any evidence of Binance kline revision is surfaced during Stage A, classification revisits.

### A5 — Taxonomy sensitivity

The metric `momentum / realized_vol` has no reasonable taxonomy alternatives. Window-length choices are parameters locked at §2, not taxonomy decisions.

Expected: PASS with no sensitivity test required.

### Stage A verdict logic

| Condition | Verdict |
|---|---|
| Any sub-gate FAIL | **SHELVE** — draft kill action |
| All sub-gates pass, A1 PASS_WARNING | **Stage B CONSTRAINED** (A1-warning consequence per candidate #2 template) |
| All sub-gates PASS_CLEAN or PASS | **Stage B UNCONSTRAINED** |

A Stage A PASS_WARNING does not relax anti-cherry-pick restrictions. It alters the required burden of evidence in Stage B per the candidate #2 precedent.

---

## 4. Stage B — Performance and construction-identity gate

**Purpose:** Standard performance gates (B1–B3) plus two parallel gate families addressing the dominant failure mode F1 (vol-estimation instability) and the kill-capable secondary structural risk F3 (low-vol concentration as alternative explanation).

**Budget:** Remainder of Sleeve B budget after Stage A completes. Hard ceiling: combined Stage A + Stage B ≤ 38 days from candidate-#3 start (per Sleeve B budget remaining after prior candidates).

### B1 — Research kill

| OOS Sharpe | Classification |
|---|---|
| < 0.75 | **RESEARCH KILL** — shelve |

### B2 — Candidate status

| OOS Sharpe | Classification |
|---|---|
| 0.75 ≤ Sharpe < 1.5 | Continued candidate — no promotion eligibility |

### B3 — Promotion eligibility

| Gate state | Sharpe gate | Drawdown gate |
|---|---|---|
| F1 all PASS_CLEAN + F3 all PASS_CLEAN | ≥ 1.5 | ≤ 25% |
| F1 or F3 any PASS_WARNING | ≥ 1.75 | ≤ 20% |
| F1 or F3 any FAIL | candidate shelved regardless of metrics | — |

**Warning-tightening rationale:** Weaker construction integrity (F1 PASS_WARNING) or weaker attribution clarity (F3 PASS_WARNING) requires stronger performance evidence. F1 and F3 FAILs are kill-capable regardless of Sharpe — this is the Q2 lock.

### B4 — Paper → canary

Per master Sleeve B pre-registration at `fe909bb`. Unchanged. F1/F3 warnings do not relax paper-stage requirements.

---

## 5. F1 gate family — Vol-estimation instability (dominant failure mode)

F1 is the load-bearing test for candidate #3's dominant failure mode. Four sub-gates.

### F1.1 — Vol estimator stability

For each asset, compute the rolling 60d realized standard deviation of the 45d realized-vol time series. The metric is "how variable is the vol estimator itself."

Cross-sectional median across all eligible assets:

| `vol(45d_vol) / mean(45d_vol)` | Classification |
|---|---|
| > 0.6 | **FAIL** |
| 0.4 – 0.6 | **PASS_WARNING** |
| ≤ 0.4 | **PASS_CLEAN** |

Reviewer-locked bands acknowledge that crypto realized vol is inherently unstable; thresholds are calibrated to crypto, not equities.

### F1.2 — Rank churn

Cross-sectional rank stability across consecutive rebalance dates. Computed as the fraction of top-third bucket members retained from one rebalance to the next, averaged across all rebalance transitions in the OOS window.

| Median top-third retention week-over-week | Classification |
|---|---|
| < 0.40 | **FAIL** — > 60% weekly turnover in top bucket; signal is noise |
| 0.40 – 0.55 | **PASS_WARNING** |
| ≥ 0.55 | **PASS_CLEAN** |

### F1.3 — Numerator-vs-denominator variance contribution

Decompose the variance of the ranked score across the cross-section at each rebalance date into:
- Contribution from the momentum numerator (variance if vol were held constant)
- Contribution from the vol denominator (variance if momentum were held constant)
- Interaction

Compute the fraction of total cross-sectional score variance attributable to the momentum numerator (median across rebalance dates).

| Momentum-numerator contribution | Classification |
|---|---|
| < 0.5 | **FAIL** — vol denominator dominates the signal; construction is not actually momentum |
| 0.5 – 0.65 | **PASS_WARNING** |
| > 0.65 | **PASS_CLEAN** |

**This is the intellectual center of candidate #3.** If the vol denominator drives more than half the cross-sectional signal variance, the strategy is not volatility-scaled momentum — it is volatility-rank carry with a momentum cosmetic. The kill threshold reflects that economic reality.

### F1.4 — Window-sensitivity robustness

Re-run the backtest with parameter variants:
- (momentum=15d, vol=45d)
- (momentum=45d, vol=45d)
- (momentum=30d, vol=30d)
- (momentum=30d, vol=60d)

Compute Sharpe for each variant. Window-sensitivity metric:

```
sensitivity = (max_Sharpe − min_Sharpe) / median_Sharpe
```

(Median, not mean, per reviewer lock — robust against single-variant distortion.)

| Sensitivity | Classification |
|---|---|
| > 0.30 | **FAIL** — Sharpe is window-fragile; result is parameter-luck |
| 0.15 – 0.30 | **PASS_WARNING** |
| ≤ 0.15 | **PASS_CLEAN** |

---

## 6. F3 gate family — Low-vol concentration / attribution (kill-capable secondary)

F3 catches the most insidious failure mode: a strategy that passes performance gates while being economically misidentified. Per Q2 lock, F3 sub-gates are kill-capable.

### F3.1 — Long-bucket vol concentration

Median realized 45d vol of the long bucket vs median realized 45d vol of the full eligible universe, averaged across rebalance dates.

| `median_long_bucket_vol / median_universe_vol` | Classification |
|---|---|
| < 0.60 | **FAIL** — long bucket systematically loaded with lowest-vol names |
| 0.60 – 0.80 | **PASS_WARNING** — some construction-driven tilt expected; quantify |
| ≥ 0.80 | **PASS_CLEAN** |

### F3.2 — BTC / ETH dominance in long bucket

Fraction of rebalance dates where both BTC and ETH appear in the long bucket simultaneously.

| Joint BTC+ETH presence frequency | Classification |
|---|---|
| > 0.70 | **FAIL** — long bucket structurally a long-majors bet |
| 0.40 – 0.70 | **PASS_WARNING** |
| ≤ 0.40 | **PASS_CLEAN** |

### F3.3 — Low-vol attribution decomposition

Decompose the strategy's total OOS return into:
- **Pure momentum component:** return of xs-momentum baseline (no vol scaling) with same universe and cadence
- **Pure low-vol component:** return of "long bottom-third by 45d vol, short top-third by 45d vol" portfolio with same universe and cadence
- **Interaction component:** total return minus pure momentum minus pure low-vol

Fraction of total return attributable to the pure low-vol component:

| Pure low-vol return contribution | Classification |
|---|---|
| > 0.5 | **FAIL** — low-vol explains more than half the return; economic story broken |
| 0.3 – 0.5 | **PASS_WARNING** |
| ≤ 0.3 | **PASS_CLEAN** |

**This is the kill-capable F3 gate.** A strategy whose returns are mostly explained by what a pure low-vol portfolio would have earned cannot honestly be promoted as volatility-scaled momentum. The kill threshold (0.5) reflects the economic reality that anything above half is misattribution.

---

## 7. Mandatory non-gating diagnostics

Required outputs of Stage B regardless of verdict. Non-gating but mandatory in the Stage B report.

### 7.1 BTC-beta and size collinearity

- Realized BTC beta of long-short portfolio across OOS
- Rank correlation of score vs market-cap rank, per rebalance date
- Flag for review if BTC beta exceeds ±0.15

### 7.2 Sector concentration

- Fraction of long-leg and short-leg from each ecosystem cluster
- Flag if any single cluster > 50% of either leg at any rebalance date

### 7.3 Turnover decomposition

- Gross turnover, annualized, two-way
- Per-rebalance turnover distribution
- Per-asset turnover concentration ranking
- Per-asset turnover-vs-alpha contribution table (catches F5 directly)

### 7.4 Per-asset Sharpe contribution

For each universe asset, contribution to total OOS Sharpe. Catches hidden 1-2-name dominance not visible from bucket-level metrics. Related to F3.2 but operating on Sharpe attribution rather than presence frequency.

### 7.5 Rolling 90d Sharpe series

Time series of rolling 90d Sharpe across the OOS window. Catches F4 (regime collapse) if it manifests as a specific time window. Flag if any rolling 90d Sharpe falls below 0 for more than 6 weeks.

### 7.6 Excluded-names report

For each rebalance date, names excluded from eligible universe with reason. Survivorship disclosure per master pre-registration.

---

## 8. Anti-cherry-pick discipline

Restated for clarity. No part of this candidate-#3 specification relaxes any of these:

- All thresholds in §3, §4, §5, §6 are pre-registered at this commit. Mid-window adjustment is prohibited.
- All parameters in §2 are pre-registered. The momentum window, vol window, rebalance cadence, bucket construction, and position sizing are locked.
- An F1 or F3 PASS_WARNING does not relax anti-cherry-pick restrictions. It only alters the required burden of evidence in Stage B per §4.B3.
- Stage B performance numbers are reported as computed, regardless of whether they cross gates.
- No post-hoc construction redefinition. If volatility-scaled momentum fails, switching to volatility-filtered momentum (or any other variant) is candidate #4, not a candidate-#3 rescue.
- F1.4 window sensitivity runs only against the four pre-registered variant sets. No additional window combinations may be tested post-hoc.

---

## 9. Kill modes

Terminal kill modes for candidate #3:

| Kill mode | Trigger | Required artifact |
|---|---|---|
| Coverage kill | Stage A FAIL | Kill action document |
| Stage A budget kill | Stage A unresolved at 2 days | Kill action document |
| Research kill | B1 (Sharpe < 0.75) | Kill action document |
| Construction-instability kill | Any F1 sub-gate FAIL | Kill action document |
| Misattribution kill | Any F3 sub-gate FAIL | Kill action document |
| Performance-fragility kill | B3 fail post-warning, or DD exceeds gate | Kill action document |
| Combined budget kill | Total candidate-#3 time > 38 days | Kill action document |

Kill action documents follow the template established by `sleeve_b_xs_momentum_kill_action.md` (commit `f3e078e`) and `sleeve_b_quality_kill_action.md` (commit `bf642d1`).

---

## 10. Budget allocation

| Phase | Budget |
|---|---|
| Stage A | ≤ 2 calendar days |
| Stage B | Remainder |
| Combined (candidate #3 total) | ≤ 38 calendar days |
| Master Sleeve B budget | Per `fe909bb`, default kill date 2026-06-27 |

Budget overrun at any tier is a terminal kill condition.

---

## 11. Required Stage A artifacts (commit checklist)

Before Stage A is declared complete:

- [ ] Stage A verdict memo with rebalance-date series for each sub-gate
- [ ] Listing-date handling memo (which names enter the eligible universe when)
- [ ] Excluded-names list for the OOS window
- [ ] Stage B authorization statement (CONSTRAINED / UNCONSTRAINED / N/A if shelve)
- [ ] If Stage A FAIL: kill action document

---

## 12. Required Stage B artifacts (commit checklist)

Before Stage B is declared complete:

- [ ] OOS performance report (Sharpe, drawdown, hit rate, vol)
- [ ] F1 sub-gate verdicts with raw numbers
- [ ] F3 sub-gate verdicts with raw numbers
- [ ] All §7 diagnostics
- [ ] Stage B verdict against B1 / B2 / B3 / B4
- [ ] Window-sensitivity table (F1.4) with all four parameter variants
- [ ] Pure-momentum, pure-low-vol, and interaction decomposition (F3.3)
- [ ] If Stage B promotion-eligible: promotion memo and paper-stage proposal
- [ ] If Stage B kill: kill action document specifying which gate failed

---

## 13. What candidate #3 is testing

The framework has now reached a level of governance where it is no longer only asking *does it work?* It is asking *does it work for the reason we claim?*

Candidate #3 specifically tests whether volatility-scaled momentum:

- Generates stable signal under realistic crypto vol regimes (F1)
- Is genuinely momentum rather than disguised low-vol carry (F3)
- Survives the Sharpe and drawdown floors that killed candidate #1 (B3)
- Behaves under cost models comparable to live trading (turnover diagnostics)

Pass requires all four. Fail at any of F1, F3, B1, or B3 is terminal. This is the strictest candidate specification SuperHydra has produced.

---

## 14. References

- Master Sleeve B pre-registration: `docs/strategies/sleeve_b_research_preregistration.md` (commit `fe909bb`)
- Q0 Data Viability Gate memo: `docs/strategies/sleeve_b_framework_evolution_q0_data_viability.md` (commit `cb9d975`)
- Candidate #3 Q0 selection memo: `docs/strategies/sleeve_b_candidate_3_selection_memo.md` (commit `78b110d`)
- Candidate #2 pre-registration (Stage A template precedent): `docs/strategies/sleeve_b_quality_preregistration.md` (commit `4d307e6`)
- Candidate #1 kill action (construction-fragility precedent): `docs/strategies/sleeve_b_xs_momentum_kill_action.md` (commit `f3e078e`)
- Candidate #2 kill action (data-governance precedent): `docs/strategies/sleeve_b_quality_kill_action.md` (commit `bf642d1`)

---

*Pre-registration for Sleeve B candidate #3 — volatility-scaled momentum. Construction locked at (A) signal-level scaling per Q1. Dominant failure mode F1 (vol-estimation instability) per Q2. Secondary kill-capable risk F3 (low-vol concentration / misattribution) per Q2. Two-gate-family Stage B structure per Q3, with reviewer-locked thresholds. Subordinate to master at `fe909bb` and Q0 memo at `cb9d975`. No Stage A execution until this document commits.*
