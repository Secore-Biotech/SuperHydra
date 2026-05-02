# Allocator Policy

**Version:** 1.0
**Effective:** 2026-05-02
**Author:** Wasseem Katt + external reviewer
**Source:** External review 2026-05-02 identifying missing portfolio-construction governance; SuperHydra Enhanced Plan multi-sleeve architecture

This policy defines how SuperHydra constructs a portfolio across multiple strategy sleeves, sizes capital between sleeves, monitors correlation, and scales sleeves up or down based on contribution. The five other policies govern individual strategies; this policy governs how strategies combine.

## Why this policy exists

Five policies (measurement, risk, deployment_gates, data, model) define how individual strategies behave. None of them defines what happens when multiple strategies run simultaneously: how capital is split, what correlation thresholds prevent over-correlation, how a struggling sleeve is reduced before it drags portfolio Sharpe.

Without allocator governance, each strategy can be individually disciplined while the portfolio is still poorly constructed. Two anti-patterns this policy prevents:

1. **Hidden correlation cascade:** five sleeves each show low standalone Sharpe drift but co-move during BTC stress, producing portfolio drawdown larger than any individual sleeve's drawdown.
2. **Capital concentration drift:** the strongest-performing sleeve gradually accumulates a larger fraction of NAV via discretionary additions until it dominates the portfolio without a recorded promotion event.

## Scope

This policy applies whenever two or more strategy sleeves run simultaneously. During Phase 1 (single L/S engine) the allocator is trivial -- 100% to that engine. The policy still applies, with most rules vacuous when sleeve count is 1.

## 1. Sleeve roles

Every strategy is assigned a sleeve role at admission. Roles determine how the sleeve contributes to portfolio construction and what success metrics apply.

| Role | Examples | Success metric | Allocator behavior |
|---|---|---|---|
| **Alpha** | Market-neutral L/S, predictive ML | Standalone Sharpe + portfolio Sharpe contribution | Sized by Kelly (1/4 Kelly default) |
| **Carry** | Funding/basis, cross-exchange dispersion | Net carry net of unwind, hedge stability | Sized by capacity, not Kelly (carry is capacity-limited) |
| **Hedge** | Options tail hedge, protective puts | Drawdown reduction, expected shortfall reduction | Sized by cost budget, not return target |
| **Execution** | Microstructure filter, smart routing | Slippage reduction across other sleeves | No standalone capital; modifies fills of other sleeves |
| **Overlay** | Regime detection, on-chain liquidity | False positive/negative rate, portfolio Sharpe with-vs-without | No standalone capital; modifies sizing of other sleeves |
| **Product** | BTC/ETH long-flat, EBTC vault | Drawdown vs benchmark, capital preservation | Operates as separate portfolio with own NAV trajectory |

A sleeve can have only one role. Reassigning a role requires a re-promotion event per measurement_policy.

Phase 1 has one Alpha sleeve (market-neutral L/S). All allocator rules below assume eventual multi-sleeve composition.

## 2. Initial active-risk allocation (when 2-3 sleeves clear canary)

When the portfolio first contains two or more canary-cleared sleeves, the active-risk allocation defaults to:

| Sleeve role | Active-risk weight | Notes |
|---|---|---|
| Alpha (market-neutral L/S) | 50-60% | Primary Sharpe engine |
| Carry / basis | 15-25% | Mechanically uncorrelated stabilizer |
| Execution filter | 5-10% | Improves Alpha and Carry fills (no separate capital) |
| Overlay (regime) | Controls all sleeves | No separate capital; scales gross exposure |
| Hedge | Cost budget 5% NAV/year | Cost ceiling, not return target |
| Product (long-flat) | Separate portfolio | Own NAV, separate from MN portfolio |

Active risk = volatility of returns attributable to the sleeve. Weights sum to 100% across sleeves with active risk; overlay and execution don't get explicit weights since they modify other sleeves' behavior.

## 3. Mature active-risk allocation (when 4-6 sleeves operational, post-Scale)

If/when more sleeves clear canary:

| Sleeve role | Active-risk weight |
|---|---|
| Alpha (market-neutral L/S) | 40-50% |
| Carry / basis | 10-20% |
| Microstructure alpha (if standalone) | 5-10% |
| Sentiment/news/tokenomics overlay | 5-15% (overlay influence, not direct capital) |
| Hedge | Cost budget 5-10% NAV/year |
| BTC/ETH long-flat | Separate portfolio |
| EBTC | 5-15% after multi-phase canary |

These are caps, not targets. The allocator may run with lower weights if risk conditions warrant.

## 4. Capital allocation rules

**Capital is allocated, not earned.** A sleeve that performs well does not automatically receive more capital. Capital changes are explicit decisions by the allocator at scheduled review points.

**Allocator review cadence:**
- Weekly: rebalance within active-risk weight bands (drift correction)
- Monthly: review weight band changes (small adjustments based on realized contribution)
- Quarterly: full allocation review with policy revision if needed

**Drift correction (weekly):**
- If sleeve weight drifts > 20% above target, rebalance toward target via reducing new entries
- If sleeve weight drifts > 20% below target, rebalance via allowing larger entries (no forced entries -- strategy must have valid signal)
- Drift correction does not increase total capital deployed; it shifts within existing allocation

**Weight adjustments (monthly):**
- A sleeve that has produced positive marginal Sharpe contribution for 60 days may have its target weight increased by up to 5 percentage points
- A sleeve that has produced negative marginal contribution for 30 days has its target weight decreased by up to 10 percentage points
- Weight changes must remain within the active-risk allocation tables above
- Changes outside the table require quarterly policy revision

**Quarterly full review:**
- Reassess sleeve roles
- Reassess active-risk allocation table
- Reassess correlation matrix (see section 5)
- Reassess Kelly sizing parameters (1/4 Kelly is default; can be adjusted with rationale)

## 5. Correlation limits

The single largest portfolio-construction failure mode in multi-strategy crypto is hidden correlation during stress. Two sleeves with low correlation in calm regimes can co-draw-down severely during BTC liquidations.

**Correlation thresholds:**

| Threshold | Action |
|---|---|
| Pairwise sleeve correlation \|rho\| >= 0.5 over rolling 60-day window | Flag for review at next monthly cycle; consider reducing one sleeve's weight |
| Pairwise sleeve correlation \|rho\| >= 0.7 over rolling 60-day window | Reduce smaller sleeve to 50% of target weight; quarterly review must address |
| Stress-conditional correlation \|rho\| >= 0.8 (correlation in BTC -10%+ days) | Sleeves are not independent under stress; portfolio-contribution criterion fails; one sleeve loses canary status until decorrelation demonstrated |

**Correlation is computed against:**
- Daily REALIZED returns per sleeve (per measurement_policy v1.1)
- Rolling 60-day window for routine monitoring
- BTC-stress-day subset (days when BTC moved >10%) for stress correlation

**For the 3.5 stretch target (per deployment_gates v1.1):** all sleeve pairs must have rho < 0.3 to credibly claim diversification benefits. The rho < 0.3 threshold is aspirational and not strictly enforced by the allocator -- it's the bar the portfolio must reach to plausibly achieve 3.5 sustained Sharpe.

## 6. Drawdown co-movement limits

Beyond correlation, the allocator monitors drawdown co-movement explicitly.

| Metric | Threshold | Action |
|---|---|---|
| Two or more sleeves simultaneously in YELLOW state (cons NAV) | Flag | Increase monitoring; no automatic action |
| Two or more sleeves simultaneously in ORANGE state | Halt new entries across all flagged sleeves | Manual review required |
| Two or more sleeves simultaneously in RED state | Portfolio reduce-only mode | All new entries halted; positions managed only |
| Any sleeve in BLACK state | Strategy-level halt per risk_policy; allocator removes that sleeve from active allocation pending re-promotion | |

These rules supplement risk_policy section 5 drawdown state machine -- risk_policy governs per-strategy state, allocator_policy governs portfolio-level co-movement.

## 7. Cash buffer and gross exposure budget

**Minimum cash buffer:** 5% of conservative NAV at all times. Cash buffer is unallocated stablecoin or USD held outside of any sleeve, available for margin top-ups, opportunistic sleeve scaling, or stress-event response.

**Gross exposure budget:** total long + short notional across all sleeves cannot exceed 200% of conservative NAV (per risk_policy section 3). Sleeves contend for this budget; the allocator does not let one sleeve crowd out another by exceeding its share.

**Per-venue exposure cap:** no single venue holds > 100% of conservative NAV in Phase 1 (single-venue) or > 60% post multi-venue rollout. EBTC vault exposure (Phase 7+) does not count against the per-venue cap of trading venues but has its own DeFi exposure cap per risk_policy section 11.

## 8. Sleeve scaling and de-scaling

**When to scale a sleeve up:**
- 60+ days continuous operation in current allocation
- Realized Sharpe contribution within 30% of expected (per validation report)
- No P0 incidents or repeated risk-event rejections
- Capacity test re-passed at proposed new size
- Correlation and drawdown co-movement within thresholds
- Operator promotion event recorded

**When to scale a sleeve down:**
- Realized Sharpe contribution < 50% of expected for 30+ days
- Capacity ceiling approached (alpha degradation observed at current size)
- Correlation threshold breached
- Repeated risk-event rejections suggesting strategy stress
- Cost model drift > 30% sustained

**Scaling decisions are not optional human discretion.** They are triggered by quantitative criteria above. Discretionary capital additions outside these rules are forbidden.

**Scaling steps:**
- Up: increment by 25% of current weight per cycle (e.g., 20% weight -> 25% -> 31% -> 39%)
- Down: decrement by 50% per cycle if criterion is breached (faster down than up -- protects portfolio)

## 9. Sleeve removal

A sleeve is removed from active allocation when:
- Sunset criterion met per deployment_gates.md
- Sustained negative portfolio contribution for 60+ days
- Correlation > 0.7 with another sleeve and the smaller sleeve cannot be decorrelated through redesign
- Operator decision with documented rationale

Removed sleeves can be re-admitted via fresh promotion through full deployment gates. Removal is not "pause" -- it's "deallocate and reclaim capital."

## 10. Multi-product portfolio handling

SuperHydra has multiple products (per registry.portfolios in ledger schema v0.2):
- `mn_ls_phase1` (market-neutral fund)
- `long_flat_certificate` (BTC/ETH long-flat product)
- `ebtc_vault` (EBTC enhanced BTC product)
- `paper_research`

**Each product has its own:**
- NAV trajectory (computed independently)
- Sharpe target (per deployment_gates.md)
- Risk limits (per risk_policy.md, with product-specific calibration in section 11)
- Investor-facing reporting

**The allocator within each product** governs sleeve composition within that product. Cross-product capital flows happen only via explicit operator transfer, not via allocator decision. A market-neutral product with excess cash does not lend it to EBTC; investors deposit into specific products.

For the operator's internal portfolio (combining all products into a personal NAV view), a meta-allocator may exist for personal capital allocation decisions across products. This is not part of SuperHydra-as-a-business and is outside this policy.

## 11. Allocator audit and provenance

Every allocator decision is logged to the `registry.allocator_runs` and `registry.target_weights` tables (per ledger schema v0.2). Each run records:
- Input signal batch IDs from each sleeve
- Active-risk weights at decision time
- Correlation matrix used
- Drawdown states at decision time
- Output target weights per instrument
- Solve status (optimal / suboptimal / infeasible / failed)

This provides full audit trail: every order intent traces back to a target weight, which traces back to an allocator run, which traces back to the policy version active at decision time.

## 12. Quarterly allocator review

A allocator review runs quarterly alongside other policy reviews. It:
- Reviews sleeve performance vs allocation
- Reviews correlation matrix evolution
- Reviews scaling decisions made over the quarter
- Reviews any drawdown co-movement events
- Reviews policy hierarchy interactions (allocator decisions overriding or being overridden by other policies)
- Updates this policy if calibration is needed

**Sign-off:** Operator (Wasseem Katt). Both signatures required if/when a second operator joins.

**First quarterly review scheduled:** 2026-08-02

## 13. Policy hierarchy

This policy is part of the SuperHydra Policy Pack. When policies conflict:

1. Safety/compliance/venue permission requirements
2. Risk policy
3. Measurement policy
4. Deployment gates policy
5. Data policy
6. Model policy
7. Allocator policy (this document)
8. Incident severity policy

The stricter safety/risk interpretation applies until policies are amended and re-signed. The allocator never overrides risk-kernel rejections -- a sleeve in BLACK state is removed from allocation regardless of allocator preference.

## Revision log

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-05-02 | Wasseem Katt + external reviewer | Initial policy, addressing missing portfolio-construction governance identified in external review of v1.0 policy pack |
