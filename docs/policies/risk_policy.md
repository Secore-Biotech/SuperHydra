# Risk Policy

**Version:** 1.1
**Effective:** 2026-05-02 (revised from v1.0 same date)
**Author:** Wasseem Katt
**Capital ceiling assumed:** $50,000 USD at full Phase 6 scale
**Source:** SuperHydra Enhanced Plan; calibrated to lessons from HYDRA postmortem 2026-05-01; v1.1 incorporates external review 2026-05-02
**Supersedes:** v1.0 (same date)

This policy defines the hard limits enforced by the Risk Kernel. Every order that fails any check below is rejected before reaching the venue adapter. Limits cannot be bypassed by any strategy. Limit changes are policy changes (this file), not code changes (kernel rejects).

## Why v1.1

v1.0 used REALIZED PnL for daily/weekly loss limits, which would allow open-position drawdown to grow unmonitored. v1.1 switches loss limits and drawdown state to conservative NAV (REALIZED + UNREALIZED MTM at conservative_exit mark prices). v1.1 also adds order-book-depth checks beyond the daily-volume liquidity floor, defines future-engine risk limit categories, makes BTC/ETH long-flat product constraints schema-enforceable, and refines the canary kill-switch criterion to distinguish strategy malfunction from external venue/data outage.

## 1. Capital phases and applicable limits

Loss limits below are computed against **conservative NAV** (REALIZED + UNREALIZED MTM, marked at conservative_exit prices per data_policy section on mark types). This is the v1.1 corrective for the REALIZED-only blind spot.

| Phase | Window | Capital | Daily loss (cons NAV) | Weekly loss (cons NAV) | Max drawdown (cons NAV) | Action on breach |
|---|---|---|---|---|---|---|
| Paper (Phase 1-4) | through Sep 15 2026 | $0 (simulated $50K) | 1.0% | 3.0% | 12% | Pause new orders, alert operator |
| Canary (Phase 5) | Sep-Mar 2027 | $500-$2,000 per engine | 0.5% | 1.5% | 10% | Pause new orders, halt strategy, alert |
| Scale-up (Phase 6 early) | Mar-Jun 2027 | $5,000-$15,000 | 0.75% | 2.0% | 12% | Pause new orders, halt strategy, alert |
| Scale-up (Phase 6 mid) | Jun-Sep 2027 | $15,000-$50,000 | 1.0% | 2.5% | 12% | Pause new orders, halt strategy, alert |
| Full scale | Sep 2027+ | $50,000 (ceiling) | 1.0% | 2.5% | 12% | Pause new orders, halt strategy, alert |

Daily loss is computed end-of-day vs previous end-of-day conservative NAV. Weekly loss is rolling 7-day. Max drawdown is peak-to-trough on rolling conservative NAV from the strategy's go-live date. Per measurement_policy v1.1: REALIZED-only is for promotion Sharpe, not for risk monitoring.

A breach at any level triggers a halt, not a slowdown. Re-enabling requires explicit operator promotion (per measurement_policy.md section 8) with written analysis of why the breach occurred and what changed to prevent recurrence.

## 2. Position limits per single asset

For market-neutral L/S engine on top 30-50 altcoin perpetuals (Phase 1):

| Limit | Value |
|---|---|
| Max gross exposure per asset | 4% of conservative NAV |
| Max single-leg position size (long or short) | 2% of conservative NAV |
| Max correlated cluster exposure (e.g., L1 alts, DeFi tokens) | 10% of conservative NAV |
| Min daily-volume liquidity floor | 200x position size |
| Max position vs 1% order-book depth | 25% (position can exit through 1% depth without consuming all of it) |
| Max position vs 5-minute traded volume | 30% (can exit within 5 minutes at no worse than modeled slippage) |
| Modeled exit slippage in stress regime | <= 50 bps |

The 200x daily-volume rule is a coarse first filter. The order-book-depth and traded-volume rules are the v1.1 additions and matter more in practice -- daily volume can be misleading when liquidity is concentrated on another venue or thin at the moment of execution.

Cluster definition is set per asset universe (DeFi, Layer 1, gaming, AI, etc.) and reviewed quarterly. An asset belongs to exactly one cluster.

## 3. Portfolio-level exposure limits

| Limit | Value | Notes |
|---|---|---|
| Net market exposure | <= 1% of conservative NAV | Market-neutral mandate |
| Gross exposure (long + short notional) | <= 200% of conservative NAV | Allows for ~2x gross with 1% net |
| BTC beta | -0.05 to +0.05 | Computed against rolling 30-day BTC returns |
| ETH beta | -0.05 to +0.05 | Computed against rolling 30-day ETH returns |
| Max single venue exposure | 100% of conservative NAV | Single-venue Phase 1; revisit when multi-venue |
| Margin utilization | <= 20% of available margin | Buffer against forced liquidation |
| Stablecoin concentration risk | <= 80% in any single stable | USDC vs USDT diversification when feasible |

Net exposure <= 1% is the QAnalytics market-neutral standard. Strategies that drift above 1% net for more than 1 hour trigger an automatic rebalance directive.

## 4. Liquidation distance and margin

| Metric | Threshold | Action |
|---|---|---|
| Liquidation distance (worst position) | >= 35% | Normal operation |
| Liquidation distance | 25-35% | Warning; new entries halted for that asset |
| Liquidation distance | 15-25% | Reduce position size by 50% |
| Liquidation distance | < 15% | Force-close the position regardless of strategy signal |

Liquidation distance is the percentage move in the underlying that would trigger venue liquidation, computed continuously per position.

## 5. Drawdown state machine

The Risk Kernel maintains a portfolio-level state with five values (v1.1 adds ORANGE between YELLOW and RED for finer granularity):

| State | Trigger (cons NAV drawdown) | Effect on new orders |
|---|---|---|
| GREEN | < 5% from peak | Normal operation, all checks apply |
| YELLOW | 5-7% from peak | Position size reduced by 30% on new entries |
| ORANGE | 7-9% from peak | Position size reduced by 50%; weak strategies (those underperforming standalone Sharpe by >50%) suspended |
| RED | 9-12% from peak | New entries halted; existing positions can only be closed or hedged |
| BLACK | > 12% from peak | Full strategy halt; explicit operator promotion required to re-enable |

State transitions are computed continuously against conservative NAV. Recovery requires drawdown to fall 1% below the entry threshold (hysteresis to prevent flapping). BLACK requires explicit operator action.

## 6. Pre-trade check sequence

Every OrderIntent is evaluated against the following checks in order. Any failure rejects the order:

1. `require_system_healthy()` -- no active P0 incidents, ledger reconciler running, data freshness OK
2. `require_venue_allowed()` -- venue is in approved list, not in known outage
3. `require_strategy_promoted()` -- strategy has current promotion event per measurement_policy section 8
4. `require_data_fresh()` -- all data sources for this signal are within freshness SLA (defined in data_policy.md)
5. `require_no_reconciliation_break()` -- reconciler has confirmed venue <-> ledger consistency within last 60 seconds
6. `require_expected_edge_gt_2x_cost()` -- order's expected edge in bps must exceed 2x the modeled round-trip cost
7. `require_daily_volume_liquidity()` -- 200x daily-volume floor met
8. `require_orderbook_depth_sufficient()` -- position <= 25% of 1% depth (v1.1 addition)
9. `require_exit_liquidity_sufficient()` -- position exitable within 5 min at modeled slippage (v1.1 addition)
10. `require_stress_exit_cost_within_budget()` -- modeled stress exit slippage <= 50 bps (v1.1 addition)
11. `require_position_limit()` -- single-asset gross exposure limit not breached
12. `require_cluster_limit()` -- cluster exposure limit not breached
13. `require_net_exposure_limit()` -- portfolio net exposure <= 1% post-fill
14. `require_gross_exposure_limit()` -- portfolio gross <= 200% post-fill
15. `require_beta_limit()` -- BTC and ETH beta within bounds post-fill
16. `require_funding_limit()` -- funding rate exposure within tolerance
17. `require_margin_limit()` -- margin utilization <= 20% post-fill
18. `require_drawdown_state_allows_risk()` -- drawdown state permits new entries
19. `require_strategy_constraints_met()` -- strategy's allow_leverage / allow_shorts / allowed_instrument_types respected (v1.1 addition; reads from risk.strategy_constraints table)
20. `require_kill_switch_clear()` -- operator kill switch not engaged

Each check logs its result to the `risk_events` table. Rejected orders log the failing check.

## 7. Funding rate limits

For perpetual positions:

| Metric | Threshold |
|---|---|
| Max funding burden per position | 30% APY annualized cost |
| Max funding burden per portfolio | 5% APY weighted average |
| Reverse-funding entry signal | If funding > 50% APY against the position direction, halt new entries that side |

Funding rates are evaluated at signal generation and re-checked at order submission. A position whose funding cost has spiked above 30% APY since entry is flagged for review.

## 8. Stress test requirements

Before any strategy enters Phase 5 (canary live), it must pass simulated stress tests against conservative NAV:

- BTC -20% in 24 hours: portfolio survives without liquidation, drawdown <= 12%
- BTC +20% in 24 hours: portfolio survives, no margin-call cascade
- Single asset -50% gap (delisting/exploit): position loss <= 2x position size (no margin spillover)
- Venue outage 4 hours: existing positions can be managed via fallback (manual or alternative venue)
- Stablecoin depeg 5%: portfolio loss <= 3% NAV
- Funding spike to 200% APY: portfolio cost <= 0.5% NAV per day

Strategy that fails any stress test is rejected for canary admission until the failure mode is addressed.

## 9. Kill switches

Three kill switches exist, accessible to operator (Wasseem Katt):

- **STRATEGY_HALT** (per-strategy): rejects all new orders for one strategy, existing positions managed normally
- **VENUE_HALT** (per-venue): rejects all new orders to one venue, attempts to flatten existing positions through alternative paths
- **PORTFOLIO_HALT** (system-wide): rejects all new orders across all strategies and venues, alerts operator, requires operator action to re-enable

Each kill switch is implemented as an explicit flag in a config file readable by the Risk Kernel on every order check. Engagement is logged to `kill_switch_log` with timestamp, operator, reason.

The PORTFOLIO_HALT kill switch is also engaged automatically by:
- Any reconciliation break unresolved after 5 minutes
- Drawdown state transition to BLACK (per cons NAV)
- Any P0 measurement integrity bug discovered in production
- Any P0 incident per incident_severity_policy.md

Auto-triggered kill switches do not require operator signature at engagement time but require operator review within the deadline specified in incident_severity_policy.md (default 24 hours for auto-triggered halts).

## 10. Limit override procedure

In rare cases, an operator may need to override a limit (e.g., closing a position that has drifted to 110% gross because the alternative is forced liquidation). Override requires:

- Explicit operator promotion event with override rationale
- Time-bounded scope (default 1 hour, max 24 hours)
- Logged to `override_log` with full context
- Triggers mandatory post-incident review within 7 days

Overrides are not for convenience. A limit that needs to be overridden routinely is a limit that needs to be revised in this document, not bypassed in production.

## 11. Future-engine risk limit categories (v1.1 addition)

The risk limits above are calibrated for Phase 1 market-neutral altcoin perpetuals. Future engines (Phase 7+) require separately calibrated limits before any code is written. The categories below define the minimum dimensions that must be calibrated; specific values are determined at engine-scoping time and added to this policy via revision.

**Carry / basis / funding strategies:**
- Max unhedged leg exposure (delta drift between spot and perp legs)
- Max basis unwind loss (cost to close both legs in stress)
- Max funding reversal loss
- Max margin utilization per hedge pair
- Max venue imbalance (one leg on Binance, other on OKX, etc.)
- Max time between hedge-leg fills (delta exposure window)
- Max stablecoin depeg exposure

**Options / volatility:**
- Max delta (net directional exposure)
- Max gamma (delta sensitivity)
- Max vega (volatility exposure)
- Max short gamma (forbidden initially)
- Max expiry concentration
- Max premium spent per month
- Naked short options forbidden until canary-proven

**EBTC / DeFi looping:**
- Max leverage ratio
- Min health factor
- Max LTV
- Max borrow APY
- Max smart-contract exposure (per protocol)
- Max collateral concentration
- DeFi looping forbidden before smart-contract audit

**BTC/ETH long-flat product:**
- allow_leverage = false (enforced via risk.strategy_constraints)
- allow_shorts = false (enforced via risk.strategy_constraints)
- allowed_instrument_types = ['spot', 'cash'] (enforced via risk.strategy_constraints)
- This is enforced as a schema constraint at strategy-creation time and verified by `require_strategy_constraints_met` in pre-trade checks

**Sentiment / news / tokenomics overlays:**
- Cannot place orders directly (advisory signals only)
- Risk modifier amplitude bounded (cannot zero out a position based on sentiment alone)
- Source credibility threshold required before signal contributes

## 12. Quarterly risk review

A risk audit runs quarterly alongside the measurement review. It:
- Reviews all `risk_events` from the quarter, especially repeated rejections of the same check
- Re-evaluates limits against actual realized volatility and drawdown
- Adjusts cluster definitions for the asset universe
- Validates conservative-NAV vs realized-only usage matches v1.1 specification
- Updates this policy if calibration is needed

**Sign-off:** Operator (Wasseem Katt). Both signatures required if/when a second operator joins.

**First quarterly review scheduled:** 2026-08-02

## 13. Policy hierarchy

This policy is part of the SuperHydra Policy Pack. When policies conflict:

1. Safety/compliance/venue permission requirements
2. Risk policy (this document)
3. Measurement policy
4. Deployment gates policy
5. Data policy
6. Model policy
7. Allocator policy
8. Incident severity policy

The stricter safety/risk interpretation applies until policies are amended and re-signed.

## Revision log

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-05-02 | Wasseem Katt | Initial policy, calibrated to $50K capital ceiling and market-neutral L/S engine |
| 1.1 | 2026-05-02 | Wasseem Katt + external reviewer | Daily/weekly loss limits and drawdown state changed to conservative NAV (was REALIZED-only). Added orderbook-depth and stress-exit-liquidity checks to pre-trade sequence. Added ORANGE state to drawdown state machine. Added strategy_constraints check to pre-trade sequence. Added section 11 future-engine risk limit categories for carry, options, EBTC/DeFi, long-flat, sentiment overlays. Added auto-triggered kill switch handling reference. Added policy hierarchy. |
