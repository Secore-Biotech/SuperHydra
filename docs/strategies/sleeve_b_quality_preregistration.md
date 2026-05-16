# Sleeve B Candidate #2 — Revenue-bearing quality (fee-yield) pre-registration

**Status:** Committed, binding
**Subordinate to:** `docs/strategies/sleeve_b_research_preregistration.md` (commit `fe909bb`)
**Candidate identity:** Sleeve B candidate #2
**Primary metric:** annualized protocol fee yield / circulating market cap
**Rebalance cadence:** weekly
**OOS window:** 2023-04-15 → 2026-04-15
**Frozen universe reference:** `tests/fixtures/sleeve_b/universe_top30_20260415.json` (commit `2af9981`)
**Prior candidates:** A2 (shelved, commit `924a930`, signal failure) · xs-momentum (shelved, commit `f3e078e`, construction fragility)

---

## 0. Governance inheritance

This document inherits all governance constraints, anti-cherry-pick rules, budget limits, and promotion semantics from the master Sleeve B pre-registration at commit `fe909bb`.

This document specifies only the candidate-specific additions:

- Fee-yield metric definition
- Stage A coverage gate
- Stage B warning-conditioned thresholds
- Candidate-specific diagnostics

Nothing in this document amends or relaxes the master pre-registration. Where this document is silent, the master governs. Where this document is more restrictive, this document governs.

---

## 1. Candidate identity and primary metric

**Candidate framing:** Revenue-bearing quality. This is not "quality" in the unqualified sense — crypto lacks a settled quality definition the way equities have ROE / earnings stability / debt-to-equity. This candidate is specifically a **fee-yield quality proxy**.

**Hypothesis (falsifiable):** Within the frozen top-30 USDT-perp universe, protocols with higher annualized fee yield (protocol fees / circulating market cap) earn positive cross-sectional risk-adjusted returns over weekly rebalance horizons, independent of size and BTC beta.

**Primary metric:**

```
fee_yield = (trailing 30-day annualized protocol fees) / circulating_mcap
```

**Why fee yield is the chosen metric (not other "quality" candidates):**

- Strongest economic analogy to equity earnings yield
- Direct measurement, not narrative-derived
- Rank-stable on weekly horizons for protocols with real usage
- Avoids the wash-trading corruption that affects on-chain usage metrics
- Avoids the gamability of developer-activity metrics
- Avoids the deterministic-schedule character of supply-discipline metrics (which is closer to tokenomics carry than quality)

**Supply discipline is a robustness diagnostic, not the primary signal.** Specified in §6.

---

## 2. Universe construction

**Master universe:** Frozen top-30 reference at `tests/fixtures/sleeve_b/universe_top30_20260415.json`. Unchanged.

**Eligible universe:** Subset of master universe with reliable fee-data classification at a given rebalance date.

**Eligibility criteria (per asset, per rebalance date):**

- Asset has TT or DeFiLlama fee data available at that rebalance date
- Fee classification is non-trivial under the canonical taxonomy locked in A5 (§3.A5)
- Data is point-in-time consistent with publication state at the rebalance date (subject to A4)

**Excluded names handling:** Names not in the eligible universe at a given rebalance date are **documented, not zero-ranked**. Zero-bucketing is prohibited by reviewer decision because it creates a false statement (missing fee data ≠ low fee yield). The excluded-names report is mandatory Stage B diagnostic (§6).

**Promotion universe (forward-looking, not Stage A concern):** If candidate ever reaches promotion, the operator decides whether to exclude non-revenue assets operationally or build a separate sleeve. This decision is out of scope for the research pre-registration.

---

## 3. Stage A — Coverage / metric definition gate

**Purpose:** Establish whether the fee-yield metric can be defined cleanly and consistently across enough of the universe to support a cross-sectional factor at all. If Stage A fails, no return backtest is computed — the candidate is shelved without consuming Stage B budget.

**Budget:** ≤ 10 calendar days from Stage A start to Stage A verdict. Budget overrun is itself a kill condition (§5).

**Evaluation cadence:** All Stage A sub-gates are evaluated **at rebalance dates** (weekly), not at calendar month-end snapshots. This keeps governance aligned with trading cadence.

### A1 — Static coverage

Minimum rebalance-date eligible universe size across the OOS window.

| Min eligible universe | Classification |
|---|---|
| < 15 | **FAIL** — shelve |
| 15–17 | **PASS_WARNING** — Stage B constrained |
| ≥ 18 | **PASS_CLEAN** |

Rationale: top-third / bottom-third construction requires meaningful breadth per leg. 15 names ≈ 5-and-5; below that, single-name risk dominates and the factor is not a factor.

### A2 — Temporal stability

Spread between max and min rebalance-date eligible counts across the OOS window.

| Spread | Classification |
|---|---|
| > 6 | **FAIL** — shelve |
| ≤ 6 | **PASS** |

Rationale: factor that runs on 25 names early in the window and 15 late is not the same factor across the window. Temporal stability prevents hidden character drift.

### A3 — Source agreement

Median rebalance-date rank correlation between Token Terminal and DeFiLlama fee data, computed on the overlap set (names present in both sources at that date).

| Median rank correlation | Classification |
|---|---|
| < 0.6 | **FAIL** — shelve |
| 0.6–0.7 | **PASS_WARNING** — source-reconciliation memo required, Stage B constrained |
| ≥ 0.7 | **PASS_CLEAN** |

**Source-reconciliation memo (required at PASS_WARNING):** Specifies which source is canonical, why, and the failure-mode protocol if the canonical source disagrees with the other in live operation.

**Tertiary check (informational, not gating):** Where on-chain reconstruction is feasible (ETH, major L2s with clean fee mechanics), spot-check against TT/DeFiLlama on 3–5 names. Disagreement here informs the source-reconciliation memo if A3 triggers warning. Does not by itself cause kill or warning.

### A4 — Point-in-time discipline

| PIT availability | Classification |
|---|---|
| Unavailable / no reproducible publication snapshots | **FAIL** — shelve |
| Partial PIT (≥ 80% of rebalance-date eligible observations) | **PASS_WARNING** — Stage B non-decision-grade, see §4 |
| Full PIT timestamps available | **PASS_CLEAN** |

**This is the strictest gate.** Token Terminal and DeFiLlama both backfill coverage as protocols are onboarded. Any factor using backfilled data is contaminated by look-ahead bias. No leniency.

**A4 PASS_WARNING consequence is special:** unlike A1/A3 warnings (which only tighten Stage B thresholds), an A4 warning makes Stage B non-decision-grade regardless of metrics. See §4.B3 special case.

### A5 — Taxonomy sensitivity

Define two reasonable alternative fee-classification taxonomies. Examples:

- Taxonomy alt-1: includes MEV tips and validator priority fees
- Taxonomy alt-2: excludes MEV tips, treats LP fees separately from protocol take

Recompute eligible universe under each at all rebalance dates.

| Max eligible-set delta across alternatives | Classification |
|---|---|
| > 3 names | **FAIL** — shelve |
| ≤ 3 names | **PASS** — canonical taxonomy locked |

**Canonical taxonomy is locked at end of A5, before Stage B begins.** No taxonomy changes during Stage B. Taxonomy memo committed alongside Stage A verdict memo.

### Stage A verdict logic

| Condition | Verdict |
|---|---|
| Any sub-gate FAIL | **SHELVE** — draft kill action |
| All sub-gates pass, ≥ 1 PASS_WARNING | **Stage B CONSTRAINED** |
| All sub-gates PASS_CLEAN | **Stage B UNCONSTRAINED** |

**A Stage A PASS_WARNING does not relax anti-cherry-pick restrictions. It only alters the required burden of evidence in Stage B.** Warning status is not permission to compensate elsewhere — it is a requirement for stronger evidence.

**Stage A verdict memo:** Required output. Includes:

- Raw rebalance-date series for each sub-gate (not summary statistics)
- Per-sub-gate classification with supporting numbers
- Canonical taxonomy specification (from A5)
- Source-reconciliation memo (if A3 PASS_WARNING)
- Excluded-names list with reasons
- Overall Stage A verdict and Stage B authorization

Verdict memo committed to `docs/strategies/` before any Stage B work begins.

---

## 4. Stage B — Performance gate

**Purpose:** Standard four-gate performance evaluation, modified by Stage A warning state.

**Budget:** Remaining Sleeve B budget after Stage A completes. Hard ceiling: combined Stage A + Stage B ≤ 41 days from candidate-#2 start (per master pre-registration budget).

**Invocation:** Only on Stage A PASS_CLEAN or PASS_WARNING. Stage A FAIL → no Stage B.

### B1 — Research kill

| OOS Sharpe | Classification |
|---|---|
| < 0.75 | **RESEARCH KILL** — shelve |

### B2 — Candidate status

| OOS Sharpe | Classification |
|---|---|
| 0.75 ≤ Sharpe < 1.5 | **Continued candidate** — no promotion eligibility |

### B3 — Promotion eligibility

| Stage A state | Sharpe gate | Drawdown gate |
|---|---|---|
| PASS_CLEAN | ≥ 1.5 | ≤ 25% |
| PASS_WARNING (A1 or A3) | ≥ 1.75 | ≤ 20% |
| PASS_WARNING (A4 — PIT partial) | non-decision-grade — **no promotion possible** | — |

**Stage A warning-tightening rationale:** Weaker data robustness requires stronger performance evidence. A factor built on less robust coverage must clear a higher bar to compensate for the additional uncertainty.

**A4 special case:** If Stage A passed with A4 PIT-partial warning, B3 cannot result in promotion eligibility regardless of Sharpe and drawdown. The Stage B output is reclassified as **exploratory memo**, not decision-grade OOS evidence. The factor returns to research for proper PIT data ingestion before any further consideration. Exploratory memo is allowed as informational research output; promotion gate is closed.

### B4 — Paper → canary

Per existing master Sleeve B pre-registration at `fe909bb`. Unchanged. Stage A warnings do not relax paper-stage requirements.

---

## 5. Kill modes

All terminal kill modes for candidate #2:

| Kill mode | Trigger | Required artifact |
|---|---|---|
| Metric-definition kill | Any Stage A sub-gate FAIL | Kill action document |
| Budget kill (Stage A) | Stage A unresolved at 10 days | Kill action document |
| Research kill | Stage B B1 (Sharpe < 0.75) | Kill action document |
| Construction-fragility kill | Stage B B3 fail post-warning, or DD exceeds gate | Kill action document |
| Budget kill (combined) | Total candidate-#2 time > 41 days | Kill action document |

**Kill action documents** follow the pattern of `docs/strategies/sleeve_b_xs_momentum_kill_action.md` (commit `f3e078e`). Committed to `docs/strategies/`. Required content per master pre-registration.

---

## 6. Mandatory non-gating diagnostics

The following diagnostics are required outputs of Stage B regardless of verdict. Non-gating: their results do not by themselves promote or kill the candidate. Their purpose is governance transparency and detection of hidden failure modes.

### 6.1 BTC-beta and size collinearity

- Realized beta of long-short portfolio to BTC across the OOS window
- Rank correlation: fee-yield rank vs market-cap rank, per rebalance date
- Flag for review if BTC beta exceeds ±0.15
- Flag for review if median fee-yield-vs-mcap rank correlation > 0.5

### 6.2 Sector concentration

- Fraction of long-leg capital coming from each ecosystem cluster (Ethereum L2s, Solana ecosystem, BTC-adjacent, etc.)
- Same for short leg
- Flag for review if any single ecosystem > 50% of either leg at any rebalance date

### 6.3 Supply-discipline orthogonality

- Rank correlation: fee-yield rank vs supply-discipline rank (annualized real emission rate), per rebalance date
- Flag for review if median correlation > 0.5 across the window
- Interpretation: high correlation means fee yield may proxy for dilution carry rather than quality

### 6.4 Excluded-names report

For each rebalance date, list of master-universe names excluded from the eligible universe and the reason for exclusion. Additionally:

- Counterfactual zero-bucketed return contribution if excluded names had been ranked at the bottom (sanity check that exclusion did not select for a confounding factor)

### 6.5 Turnover decomposition

- Gross turnover, annualized, two-way
- Per-rebalance turnover distribution across the OOS window
- Per-asset turnover concentration: which names drive turnover, ranked
- Per-asset turnover-vs-alpha contribution table: each asset's share of total turnover alongside its share of total alpha, with ratio

**Operational rationale:** Crypto factors can appear profitable while alpha is concentrated in a handful of very high-turnover names. The turnover-vs-alpha decomposition exposes this. If 70% of alpha comes from 3 names that account for 60% of turnover, the factor's operational character is fundamentally different from a broad-breadth low-turnover construction. Mandatory diagnostic, non-gating.

---

## 7. Anti-cherry-pick discipline

Restated from master pre-registration for clarity. No part of this candidate-#2 specification relaxes any of these:

- Thresholds in §3 and §4 are pre-registered. Mid-window adjustment is prohibited.
- A Stage A PASS_WARNING does not relax anti-cherry-pick restrictions. It only alters the required burden of evidence in Stage B.
- Stage B performance numbers are reported as computed, regardless of whether they cross gates.
- No post-hoc universe redefinition. Universe is the frozen top-30 reference; eligible-universe definition is locked at end of A5.
- No post-hoc taxonomy change. Canonical taxonomy is locked at end of A5.
- No re-running of Stage A with different data sources to seek a more favorable verdict. Source selection is part of the canonical taxonomy lock.

---

## 8. Budget summary

| Phase | Budget |
|---|---|
| Stage A | ≤ 10 calendar days |
| Stage B | Remainder of Sleeve B budget |
| Combined (candidate #2 total) | ≤ 41 calendar days |
| Master Sleeve B budget | Per `fe909bb`, default kill date 2026-06-27 |

Budget overrun at any tier is a terminal kill condition (§5).

---

## 9. Required Stage A artifacts (commit checklist)

Before Stage A is declared complete, the following must exist:

- [ ] Stage A verdict memo (raw rebalance-date series, per-sub-gate classification, overall verdict)
- [ ] Canonical taxonomy specification (from A5)
- [ ] Source-reconciliation memo (if A3 PASS_WARNING)
- [ ] Excluded-names list with reasons
- [ ] Stage B authorization statement (UNCONSTRAINED / CONSTRAINED / N/A if Stage A FAIL)
- [ ] If Stage A FAIL: kill action document

## 10. Required Stage B artifacts (commit checklist)

Before Stage B is declared complete, the following must exist:

- [ ] OOS performance report (Sharpe, drawdown, hit rate, vol)
- [ ] Live-vs-shadow comparison if shadow run was conducted
- [ ] All §6 diagnostics
- [ ] Stage B verdict against B1 / B2 / B3 / B4
- [ ] If Stage B promotion-eligible: promotion memo and paper-stage proposal
- [ ] If Stage B kill: kill action document

---

*Pre-registration for Sleeve B candidate #2 — revenue-bearing quality (fee-yield). Subordinate to master Sleeve B pre-registration at commit `fe909bb`. No code, no data work, no Stage A execution until this document is committed.*
