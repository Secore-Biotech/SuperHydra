# Sleeve B Candidate #4 — Volatility-scaled momentum pre-registration

**Status:** Pre-registration, binding
**Subordinate to:**
- `docs/strategies/sleeve_b_research_preregistration.md` (commit `fe909bb`) — master
- `docs/strategies/sleeve_b_framework_evolution_q0_data_viability.md` (commit `cb9d975`) — Q0 gate
- `docs/strategies/sleeve_b_framework_evolution_stage_a_gate_inheritance.md` (commit `39970f1`) — Stage A gate-inheritance discipline and Q0 §3.5 update
**Q0 verdict:** PASS_CLEAN, logged at `docs/strategies/sleeve_b_candidate_4_selection_memo.md` (commit `bdedeed`)
**Candidate identity:** Sleeve B candidate #4
**Primary construction:** Volatility-scaled momentum (signal-level scaling)
**Rebalance cadence:** weekly
**OOS window:** 2023-04-15 → 2026-04-15
**Frozen universe reference:** `tests/fixtures/sleeve_b/universe_top30_20260415.json` (commit `2af9981`)
**Prior candidates:** A2 (`924a930`, signal absence) · #1 xs-momentum (`f3e078e`, construction fragility) · #2 fee-yield quality (`bf642d1`, data governance) · #3 vol-scaled momentum (`bf0a23e`, governance-design mismatch)

---

## 0. Preamble — relationship to candidate #3

Candidate #4 reuses the volatility-scaled momentum construction originally specified in Candidate #3.

Candidate #3 was closed due to a governance-design mismatch in inherited Stage A temporal-stability gates, not due to signal invalidation. The volatility-scaled momentum signal was never evaluated empirically.

Candidate #4 operates under the corrected inheritance framework introduced at commit `39970f1` and therefore constitutes a new candidate with independent governance artifacts.

**This pre-registration is fully self-contained.** Candidate #3's pre-registration (`555339e`) and kill action (`bf0a23e`) remain permanently closed and immutable. They are referenced for provenance, not inherited as binding.

---

## 1. Governance inheritance

This document inherits all governance constraints, anti-cherry-pick rules, budget limits, and promotion semantics from:

- Master Sleeve B pre-registration at commit `fe909bb`
- Q0 Data Viability Gate memo at commit `cb9d975`
- Stage A gate-inheritance framework evolution at commit `39970f1`

This document specifies only the candidate-specific additions:

- Volatility-scaled momentum construction definition (Q1)
- F1 (vol-estimation instability) and F3 (low-vol concentration / attribution) gate families (Q2)
- Stage B threshold structure tightened on F1/F3 warnings (Q3)
- Inherited-gate verification table (§2.5, mandatory under `39970f1`)
- Corrected A2 specification (per `39970f1` §2)

Nothing in this document amends or relaxes the master, the Q0 memo, the gate-inheritance memo, or any prior candidate pre-registration. Where this document is silent, the layers above govern. Where this document is more restrictive, this document governs.

---

## 2. Candidate identity and primary construction

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

The Q1 reasoning from candidate #3 carries substantively (per reference-only inheritance under the framework evolution at `39970f1`):

- (A) signal-level scaling preserved the cleanest economic story — risk-adjustment as integrated metric, single-step ranking
- (B) sizing-level scaling rejected — signal still selects fragile names, weakens attribution
- (C) volatility filter rejected — threshold boundary is a high-overfit surface
- (D) residual / beta-neutralized momentum rejected — regression design choices and residual-estimation instability are a separate candidate family

Nothing about candidate #3's closure invalidated this reasoning. Candidate #3 was killed at Stage A before any signal evaluation; the construction-economic argument for (A) over (B/C/D) was not tested empirically and has not been refuted.

---

## 2.5 Inherited-gate verification

Per the gate-inheritance framework evolution at `39970f1` §3, every Stage A sub-gate inherited from a prior pre-registration must be declared with verification status before Stage A is specified.

| Sub-gate | Status | Reference / Adaptation note |
|---|---|---|
| A1 — Static coverage | PASS_DIRECT | Inherited from candidate #2 pre-registration (commit `4d307e6`). Threshold (min eligible universe < 15 = FAIL, 15–17 = PASS_WARNING, ≥ 18 = PASS_CLEAN) is appropriate for candidate #4's eligibility rule under Q0 §3.5.b projection at `bdedeed` §2 (16 eligible at OOS start, 30 at OOS end). |
| A2 — Temporal stability | **PASS_ADAPTED** | Inherited from candidate #2 pre-registration (commit `4d307e6`) with adaptation per `39970f1` §2. The original gate applied the spread threshold to raw eligible-universe count, which conflated deterministic listing growth with endogenous instability for frozen-universe-projected-backward constructions. The corrected gate applies the threshold to the endogenous residual E(t) = C(t) − D(t), where D(t) is the deterministic expansion trajectory computable from the fixture under candidate #4's eligibility rule. Adaptation justified by the candidate #3 kill (`bf0a23e`) and the framework evolution at `39970f1`. Specification in §3.A2 below. |
| A3 — Source agreement | NOT_APPLICABLE | Single-venue construction (Binance USDT-M perps), no cross-source comparison required. Same structural irrelevance as candidate #3. |
| A4 — PIT discipline | PASS_DIRECT | Inherited from candidate #2 pre-registration (commit `4d307e6`). Binance OHLCV is venue-native immutable historical with no documented backfill mechanism; the PIT discipline gate applies unchanged. |
| A5 — Taxonomy sensitivity | PASS_DIRECT | Inherited from candidate #2 pre-registration (commit `4d307e6`). `momentum / realized_vol` has no reasonable taxonomy alternatives. Window-length choices are parameters locked in §3, not taxonomy decisions. |

**Verification summary:** Four sub-gates inherited; one sub-gate adapted (A2); zero sub-gates dropped. The adaptation is the central change relative to candidate #3 and the reason candidate #4 is viable where candidate #3 was not.

---

## 2.6 Construction lock (B0 parameters)

These parameters are locked at this pre-registration's commit. No mid-window adjustment under anti-cherry-pick discipline. Any change requires a successor pre-registration with a new candidate number.

| Parameter | Value | Rationale |
|---|---|---|
| Momentum lookback | 30 days | Jegadeesh-Titman analog; crypto-appropriate horizon. Substantively inherited from candidate #3 (`555339e`). |
| Volatility lookback | 45 days | Reviewer-locked at candidate #3 selection: smoother than 30d, more adaptive than 60d. Substantively inherited. |
| Rebalance cadence | Weekly | Inherited from master pre-registration. |
| Bucket construction | Top-third long, bottom-third equal-weight short | Inherited from xs-momentum precedent. |
| Position sizing | Equal weight within bucket | No vol scaling at sizing level (locked at Q1 of candidate #3). |
| Universe | Frozen top-30 per `universe_top30_20260415.json` | Inherited from master pre-registration. |
| Cost model | Same as xs-momentum cost model | Inherited from candidate #1 pre-registration. |

---

## 3. Stage A — Coverage / metric definition gate

Stage A is preserved in full template form for cross-candidate structural consistency. Per the §2.5 verification table above, A1/A4/A5 inherit directly; A2 is adapted; A3 is not applicable.

**Budget:** ≤ 2 calendar days. Stage A is expected to be quick given clean Binance OHLCV data infrastructure and the §3.5.b Q0 projection already establishing the expected A1/A2 trajectory.

**Evaluation cadence:** All Stage A sub-gates evaluated at rebalance dates (weekly), not month-end snapshots.

### A1 — Static coverage (PASS_DIRECT)

Eligible universe = top-30 frozen-universe names with sufficient listing age at each rebalance date. Per the candidate #4 eligibility rule, an asset is eligible at rebalance date T iff `(T − onboard_date).days ≥ 45`.

| Min eligible universe at any rebalance date | Classification |
|---|---|
| < 15 | **FAIL** — shelve |
| 15–17 | **PASS_WARNING** — Stage B constrained |
| ≥ 18 | **PASS_CLEAN** |

Expected outcome from Q0 §3.5.b projection: min eligible = 16 at OOS start → **PASS_WARNING** with Stage B constrained per §4.B3.

### A2 — Temporal stability (PASS_ADAPTED per §2.5)

The adapted A2 distinguishes deterministic universe expansion from endogenous instability.

**Step 1 — Compute deterministic expansion D(t).** For each rebalance date t in the OOS window, compute the count of universe assets meeting the eligibility rule using only the frozen fixture's `onboard_date` field:

```
D(t) = | { asset in universe : (t − asset.onboard_date).days ≥ 45 } |
```

D(t) is computable before any signal evaluation, deterministically, from the fixture alone.

**Step 2 — Compute actual eligible-universe count C(t).** During Stage A execution, compute the actual count of assets that are both (a) past the listing-age delay and (b) have non-missing OHLCV at rebalance date t and at t − 45 days.

**Step 3 — Compute endogenous residual.** E(t) = C(t) − D(t).

**Step 4 — Apply threshold to E.**

| Spread (max E − min E) across rebalance dates | Classification |
|---|---|
| > 6 | **FAIL** — shelve |
| ≤ 6 | **PASS** |

Expected outcome: E(t) ≈ 0 across all t (no delistings or extended OHLCV gaps known for any of the 30 universe names during OOS). Projected spread ≈ 0 → **PASS_CLEAN**.

If E exceeds expectations at Stage A execution (indicating unexpected delistings, suspensions, or OHLCV gaps), the corrected A2 catches it. This is the mechanism the framework evolution was designed to preserve.

### A3 — Source agreement (NOT_APPLICABLE per §2.5)

Single-venue construction. No cross-source comparison required. Sub-gate explicitly omitted.

### A4 — PIT discipline (PASS_DIRECT)

| PIT availability | Classification |
|---|---|
| Binance kline endpoint immutable historical, no backfill mechanism documented | **PASS_CLEAN** (expected) |

If any evidence of Binance kline revision is surfaced during Stage A, classification revisits.

### A5 — Taxonomy sensitivity (PASS_DIRECT)

The metric `momentum / realized_vol` has no reasonable taxonomy alternatives. Window-length choices are parameters locked at §3, not taxonomy decisions. Expected: PASS with no sensitivity test required.

### Stage A verdict logic

| Condition | Verdict |
|---|---|
| Any sub-gate FAIL | **SHELVE** — draft kill action |
| All sub-gates pass, A1 PASS_WARNING | **Stage B CONSTRAINED** |
| All sub-gates PASS_CLEAN (with A3 N/A) | **Stage B UNCONSTRAINED** |

A Stage A PASS_WARNING does not relax anti-cherry-pick restrictions. It alters the required burden of evidence in Stage B per §4.B3.

---

## 4. Stage B — Performance and construction-identity gate

**Purpose:** Standard performance gates (B1–B3) plus two parallel gate families addressing the dominant failure mode F1 (vol-estimation instability) and the kill-capable secondary structural risk F3 (low-vol concentration as alternative explanation).

**Budget:** Remainder of Sleeve B budget after Stage A completes. Hard ceiling: combined Stage A + Stage B ≤ 36 days from candidate-#4 start. (Master Sleeve B budget remaining as of 2026-05-16 is the substantive constraint; combined ≤ 36 days reflects the program's net consumption to date.)

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
| F1 all PASS_CLEAN + F3 all PASS_CLEAN + A1 PASS_CLEAN | ≥ 1.5 | ≤ 25% |
| Any of F1, F3, A1 PASS_WARNING | ≥ 1.75 | ≤ 20% |
| F1 or F3 any FAIL | candidate shelved regardless of metrics | — |

**Warning-tightening rationale:** Weaker construction integrity (F1 PASS_WARNING) or weaker attribution clarity (F3 PASS_WARNING) or constrained breadth (A1 PASS_WARNING from 16-name eligible-universe floor) requires stronger performance evidence. F1 and F3 FAILs are kill-capable regardless of Sharpe.

### B4 — Paper → canary

Per master Sleeve B pre-registration at `fe909bb`. Unchanged. F1/F3 warnings do not relax paper-stage requirements.

---

## 5. F1 gate family — Vol-estimation instability (dominant failure mode)

F1 is the load-bearing test for candidate #4's dominant failure mode. Substantively inherited from candidate #3 Q3 lock; re-stated here for self-containment per the inheritance model.

### F1.1 — Vol estimator stability

For each asset, compute the rolling 60d realized standard deviation of the 45d realized-vol time series. Cross-sectional median across all eligible assets:

| `vol(45d_vol) / mean(45d_vol)` | Classification |
|---|---|
| > 0.6 | **FAIL** |
| 0.4 – 0.6 | **PASS_WARNING** |
| ≤ 0.4 | **PASS_CLEAN** |

### F1.2 — Rank churn

Cross-sectional rank stability across consecutive rebalance dates. Fraction of top-third bucket members retained week-over-week, averaged across all rebalance transitions in OOS.

| Median top-third retention | Classification |
|---|---|
| < 0.40 | **FAIL** |
| 0.40 – 0.55 | **PASS_WARNING** |
| ≥ 0.55 | **PASS_CLEAN** |

### F1.3 — Numerator-vs-denominator variance contribution

Decompose the variance of the ranked score across the cross-section at each rebalance date into momentum-numerator variance, vol-denominator variance, and interaction. Compute the fraction of total cross-sectional score variance attributable to the momentum numerator (median across rebalance dates).

| Momentum-numerator contribution | Classification |
|---|---|
| < 0.5 | **FAIL** — vol denominator dominates; construction is not actually momentum |
| 0.5 – 0.65 | **PASS_WARNING** |
| > 0.65 | **PASS_CLEAN** |

**This is the intellectual center of candidate #4.** If the vol denominator drives more than half the cross-sectional signal variance, the strategy is not volatility-scaled momentum — it is volatility-rank carry with a momentum cosmetic.

### F1.4 — Window-sensitivity robustness

Re-run the backtest with parameter variants:
- (momentum=15d, vol=45d)
- (momentum=45d, vol=45d)
- (momentum=30d, vol=30d)
- (momentum=30d, vol=60d)

Window-sensitivity metric:

```
sensitivity = (max_Sharpe − min_Sharpe) / median_Sharpe
```

(Median, not mean — robust against single-variant distortion.)

| Sensitivity | Classification |
|---|---|
| > 0.30 | **FAIL** — Sharpe is window-fragile |
| 0.15 – 0.30 | **PASS_WARNING** |
| ≤ 0.15 | **PASS_CLEAN** |

---

## 6. F3 gate family — Low-vol concentration / attribution (kill-capable secondary)

F3 catches the most insidious failure mode: a strategy that passes performance gates while being economically misidentified. F3 sub-gates are kill-capable.

### F3.1 — Long-bucket vol concentration

Median realized 45d vol of the long bucket vs median realized 45d vol of the full eligible universe, averaged across rebalance dates.

| `median_long_bucket_vol / median_universe_vol` | Classification |
|---|---|
| < 0.60 | **FAIL** |
| 0.60 – 0.80 | **PASS_WARNING** |
| ≥ 0.80 | **PASS_CLEAN** |

### F3.2 — BTC / ETH dominance in long bucket

Fraction of rebalance dates where both BTC and ETH appear in the long bucket simultaneously.

| Joint BTC+ETH presence frequency | Classification |
|---|---|
| > 0.70 | **FAIL** |
| 0.40 – 0.70 | **PASS_WARNING** |
| ≤ 0.40 | **PASS_CLEAN** |

### F3.3 — Low-vol attribution decomposition

Decompose total OOS return into pure momentum component, pure low-vol component, and interaction component.

| Pure low-vol return contribution | Classification |
|---|---|
| > 0.5 | **FAIL** — low-vol explains more than half the return; economic story broken |
| 0.3 – 0.5 | **PASS_WARNING** |
| ≤ 0.3 | **PASS_CLEAN** |

**Kill-capable F3 gate.** A strategy whose returns are mostly explained by what a pure low-vol portfolio would have earned cannot honestly be promoted as volatility-scaled momentum.

---

## 7. Mandatory non-gating diagnostics

Required outputs of Stage B regardless of verdict.

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
- Per-asset turnover-vs-alpha contribution table

### 7.4 Per-asset Sharpe contribution

For each universe asset, contribution to total OOS Sharpe. Catches hidden 1-2-name dominance.

### 7.5 Rolling 90d Sharpe series

Time series of rolling 90d Sharpe across the OOS window. Flag if any rolling 90d Sharpe falls below 0 for more than 6 weeks.

### 7.6 Excluded-names report

For each rebalance date, names excluded from eligible universe with reason.

### 7.7 D(t) trajectory (new for candidate #4)

The actual D(t) series computed during Stage A, plotted alongside C(t) and E(t). Documents the deterministic-expansion mechanism the corrected A2 was designed to handle. Audit artifact for future framework reviewers.

---

## 8. Anti-cherry-pick discipline

Restated for clarity. No part of this candidate-#4 specification relaxes any of these:

- All thresholds in §3, §4, §5, §6 are pre-registered at this commit. Mid-window adjustment is prohibited.
- All parameters in §2.6 (the B0 lock) are pre-registered. The momentum window, vol window, rebalance cadence, bucket construction, and position sizing are locked.
- The §2.5 inherited-gate verification statuses are pre-registered. No reclassification of any sub-gate status post-hoc.
- An F1 or F3 PASS_WARNING does not relax anti-cherry-pick restrictions. It only alters the required burden of evidence in Stage B per §4.B3.
- Stage B performance numbers are reported as computed, regardless of whether they cross gates.
- No post-hoc construction redefinition. If volatility-scaled momentum fails at candidate #4, switching to a different construction is a new candidate, not a rescue.
- F1.4 window sensitivity runs only against the four pre-registered variant sets. No additional window combinations may be tested post-hoc.
- The corrected A2 specification is locked. D(t) is computed once at Stage A start, from the frozen fixture only, and is not re-computed mid-window.

---

## 9. Kill modes

Terminal kill modes for candidate #4:

| Kill mode | Trigger | Required artifact |
|---|---|---|
| Coverage kill | Stage A A1 FAIL | Kill action document |
| Stability kill | Stage A A2 FAIL (corrected: spread of E > 6) | Kill action document |
| PIT kill | Stage A A4 FAIL | Kill action document |
| Stage A budget kill | Stage A unresolved at 2 days | Kill action document |
| Research kill | B1 (Sharpe < 0.75) | Kill action document |
| Construction-instability kill | Any F1 sub-gate FAIL | Kill action document |
| Misattribution kill | Any F3 sub-gate FAIL | Kill action document |
| Performance-fragility kill | B3 fail post-warning, or DD exceeds gate | Kill action document |
| Combined budget kill | Total candidate-#4 time > 36 days | Kill action document |

Kill action documents follow the template established by prior kill actions in the program.

---

## 10. Budget allocation

| Phase | Budget |
|---|---|
| Stage A | ≤ 2 calendar days |
| Stage B | Remainder |
| Combined (candidate #4 total) | ≤ 36 calendar days |
| Master Sleeve B budget | Per `fe909bb`, default kill date 2026-06-27 |

Budget overrun at any tier is a terminal kill condition.

---

## 11. Required Stage A artifacts (commit checklist)

Before Stage A is declared complete:

- [ ] Stage A verdict memo with rebalance-date series for each sub-gate
- [ ] D(t) trajectory computed from fixture (deterministic expansion)
- [ ] C(t) trajectory computed during execution
- [ ] E(t) = C(t) − D(t) series and spread
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
- [ ] All §7 diagnostics including the new §7.7 D(t) trajectory plot
- [ ] Stage B verdict against B1 / B2 / B3 / B4
- [ ] Window-sensitivity table (F1.4) with all four parameter variants
- [ ] Pure-momentum, pure-low-vol, and interaction decomposition (F3.3)
- [ ] If Stage B promotion-eligible: promotion memo and paper-stage proposal
- [ ] If Stage B kill: kill action document specifying which gate failed

---

## 13. What candidate #4 is testing

The framework has reached a level of governance where it tests not only *does this signal work?* but *does it work for the reason we claim?* Candidate #4 makes this concrete for the first time under the corrected gate-inheritance framework.

Specifically:

- Whether volatility-scaled momentum generates stable signal under realistic crypto vol regimes (F1)
- Whether it is genuinely momentum rather than disguised low-vol carry (F3)
- Whether it survives the Sharpe and drawdown floors that killed candidate #1 (B3)
- Whether it behaves under cost models comparable to live trading (turnover diagnostics)
- Whether the corrected A2 specification correctly distinguishes deterministic expansion from endogenous instability in actual Stage A computation (§7.7 D(t) trajectory)

Pass requires all five. Fail at any of F1, F3, B1, B3, or A2 is terminal. Candidate #4 is the strictest candidate the program has evaluated, and the first to be evaluated under the program's fourth governance layer (gate-inheritance discipline).

---

## 14. References

- Master Sleeve B pre-registration: `docs/strategies/sleeve_b_research_preregistration.md` (commit `fe909bb`)
- Q0 Data Viability Gate memo: `docs/strategies/sleeve_b_framework_evolution_q0_data_viability.md` (commit `cb9d975`)
- Stage A gate-inheritance memo (Q0 §3.5 update + verification addendum + corrected A2): `docs/strategies/sleeve_b_framework_evolution_stage_a_gate_inheritance.md` (commit `39970f1`)
- Candidate #4 Q0 selection memo: `docs/strategies/sleeve_b_candidate_4_selection_memo.md` (commit `bdedeed`)
- Candidate #3 pre-registration (signal construction provenance): `docs/strategies/sleeve_b_candidate_3_preregistration.md` (commit `555339e`)
- Candidate #3 kill action (governance-design mismatch precedent): `docs/strategies/sleeve_b_candidate_3_kill_action.md` (commit `bf0a23e`)
- Candidate #2 pre-registration (source of inherited A1/A4/A5): `docs/strategies/sleeve_b_quality_preregistration.md` (commit `4d307e6`)
- Frozen universe fixture: `tests/fixtures/sleeve_b/universe_top30_20260415.json` (commit `2af9981`)

---

*Pre-registration for Sleeve B candidate #4 — volatility-scaled momentum (governance re-attempt). First Sleeve B candidate evaluated under the corrected Stage A gate-inheritance framework. Construction substantively inherited from candidate #3; governance is independent. §2.5 inherited-gate verification table makes A2 PASS_ADAPTED explicit. Candidate #3 remains permanently closed; candidate #4 is a new candidate with its own audit trail.*
