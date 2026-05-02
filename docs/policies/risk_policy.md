# Risk Policy

**Version:** 1.0
**Effective:** 2026-05-02
**Author:** Wasseem Katt
**Capital ceiling assumed:** $50,000 USD at full Phase 6 scale
**Source:** SuperHydra Enhanced Plan; calibrated to lessons from HYDRA postmortem 2026-05-01

This policy defines the hard limits enforced by the Risk Kernel. Every order that fails any check below is rejected before reaching the venue adapter. Limits cannot be bypassed by any strategy. Limit changes are policy changes (this file), not code changes (kernel rejects).

## 1. Capital phases and applicable limits

| Phase | Window | Capital | Daily loss | Weekly loss | Max drawdown | Action on breach |
|---|---|---|---|---|---|---|
| Paper (Phase 1-4) | through Sep 15 2026 | $0 (simulated $50K) | 1.0% | 3.0% | 12% | Pause new orders, alert operator |
| Canary (Phase 5) | Sep-Mar 2027 | $500-$2,000 per engine | 0.5% | 1.5% | 10% | Pause new orders, halt strategy, alert |
| Scale-up (Phase 6 early) | Mar-Jun 2027 | $5,000-$15,000 | 0.75% | 2.0% | 12% | Pause new orders, halt strategy, alert |
| Scale-up (Phase 6 mid) | Jun-Sep 2027 | $15,000-$50,000 | 1.0% | 2.5% | 12% | Pause new orders, halt strategy, alert |
| Full scale | Sep 2027+ | $50,000 (ceiling) | 1.0% | 2.5% | 12% | Pause new orders, halt strategy, alert |

Daily loss is computed end-of-day vs previous end-of-day NAV (REALIZED PnL only per measurement_policy.md). Weekly loss is rolling 7-day. Max drawdown is peak-to-trough on rolling NAV from the strategy's go-live date.

A breach at any level triggers a halt, not a slowdown. Re-enabling requires explicit operator promotion (per measurement_policy.md section 6) with written analysis of why the breach occurred and what changed to prevent recurrence.

## 2. Position limits per single asset

For market-neutral L/S engine on top 30-50 altcoin perpetuals:

| Limit | Value |
|---|---|
| Max gross exposure per asset | 4% of NAV |
| Max single-leg position size (long or short) | 2% of NAV |
| Max correlated cluster exposure (e.g., L1 alts, DeFi tokens) | 10% of NAV |
| Min liquidity floor (asset's daily volume / position size) | 200x |

The 200x liquidity floor means: if the position is $1,000, the asset must have at least $200,000 in daily volume on the venue. This protects against slippage on entry and exit. Applies to the venue where the position is held, not aggregated across venues.

Cluster definition is set per asset universe (DeFi, Layer 1, gaming, AI, etc.) and reviewed quarterly. An asset belongs to exactly one cluster.

## 3. Portfolio-level exposure limits

| Limit | Value | Notes |
|---|---|---|
| Net market exposure | <= 1% of NAV | Market-neutral mandate |
| Gross exposure (long + short notional) | <= 200% of NAV | Allows for ~2x gross with 1% net |
| BTC beta | -0.05 to +0.05 | Computed against rolling 30-day BTC returns |
| ETH beta | -0.05 to +0.05 | Computed against rolling 30-day ETH returns |
| Max single venue exposure | 100% of NAV | Single-venue Phase 1; revisit when multi-venue |
| Margin utilization | <= 20% of available margin | Buffer against forced liquidation |
| Stablecoin concentration risk | <= 80% in any single stable | USDC vs USDT diversification when feasible |

Net exposure <= 1% is the QAnalytics market-neutral standard and the structural definition of "market neutral" for this engine. Strategies that drift above 1% net for more than 1 hour trigger an automatic rebalance directive.

## 4. Liquidation distance and margin

| Metric | Threshold | Action |
|---|---|---|
| Liquidation distance (worst position) | >= 35% | Normal operation |
| Liquidation distance | 25-35% | Warning; new entries halted for that asset |
| Liquidation distance | 15-25% | Reduce position size by 50% |
| Liquidation distance | < 15% | Force-close the position regardless of strategy signal |

Liquidation distance is the percentage move in the underlying that would trigger venue liquidation, computed continuously per position.

## 5. Drawdown state machine

The Risk Kernel maintains a portfolio-level state with three values:

| State | Trigger | Effect on new orders |
|---|---|---|
| GREEN | Drawdown < 5% from peak NAV | Normal operation, all checks apply but limits unchanged |
| YELLOW | Drawdown 5-8% from peak NAV | Position size reduced by 50% on new entries; existing positions managed normally |
| RED | Drawdown > 8% from peak NAV | New entries halted; existing positions can only be closed or hedged |
| BLACK | Drawdown > 12% (the gate-trigger threshold) | Full strategy halt, requires explicit operator promotion to re-enable |

State transitions are computed continuously. Recovery from YELLOW to GREEN requires drawdown to fall below 4% (1% hysteresis to prevent flapping). Recovery from RED to YELLOW requires drawdown below 6%. BLACK requires explicit operator action.

## 6. Pre-trade check sequence

Every OrderIntent is evaluated against the following checks in order. Any failure rejects the order:

1. `require_system_healthy()` -- no active P0 incidents, ledger reconciler running, data freshness OK
2. `require_venue_allowed()` -- venue is in approved list, not in known outage
3. `require_strategy_promoted()` -- strategy has current promotion event per measurement_policy section 6
4. `require_data_fresh()` -- all data sources for this signal are within freshness SLA (defined in data_policy.md)
5. `require_no_reconciliation_break()` -- reconciler has confirmed venue <-> ledger consistency within last 60 seconds
6. `require_expected_edge_gt_2x_cost()` -- order's expected edge in bps must exceed 2x the modeled round-trip cost
7. `require_liquidity_sufficient()` -- 200x liquidity floor met
8. `require_position_limit()` -- single-asset gross exposure limit not breached
9. `require_cluster_limit()` -- cluster exposure limit not breached
10. `require_net_exposure_limit()` -- portfolio net exposure <= 1% post-fill
11. `require_gross_exposure_limit()` -- portfolio gross <= 200% post-fill
12. `require_beta_limit()` -- BTC and ETH beta within bounds post-fill
13. `require_funding_limit()` -- funding rate exposure within tolerance
14. `require_margin_limit()` -- margin utilization <= 20% post-fill
15. `require_drawdown_state_allows_risk()` -- drawdown state permits new entries
16. `require_kill_switch_clear()` -- operator kill switch not engaged

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

Before any strategy enters Phase 5 (canary live), it must pass simulated stress tests:

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
- Drawdown state transition to BLACK
- Any P0 measurement integrity bug discovered in production

## 10. Limit override procedure

In rare cases, an operator may need to override a limit (e.g., closing a position that has drifted to 110% gross because the alternative is forced liquidation). Override requires:

- Explicit operator promotion event with override rationale
- Time-bounded scope (default 1 hour, max 24 hours)
- Logged to `override_log` with full context
- Triggers mandatory post-incident review within 7 days

Overrides are not for convenience. A limit that needs to be overridden routinely is a limit that needs to be revised in this document, not bypassed in production.

## 11. Quarterly risk review

A risk audit runs quarterly alongside the measurement review. It:
- Reviews all `risk_events` from the quarter, especially repeated rejections of the same check
- Re-evaluates limits against actual realized volatility and drawdown
- Adjusts cluster definitions for the asset universe
- Updates this policy if calibration is needed

**Sign-off:** Operator (Wasseem Katt). Both signatures required if/when a second operator joins.

**First quarterly review scheduled:** 2026-08-02

## Revision log

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-05-02 | Wasseem Katt | Initial policy, calibrated to $50K capital ceiling and market-neutral L/S engine |
