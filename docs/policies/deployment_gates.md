# Deployment Gates Policy

**Version:** 1.0
**Effective:** 2026-05-02
**Author:** Wasseem Katt
**Goal:** Live portfolio Sharpe 2.4 sustained over 6 months by November 2027
**Capital ceiling:** $50,000 USD at full Phase 6 scale
**Source:** SuperHydra Enhanced Plan; calibrated to QAnalytics live benchmark (2.31) and HYDRA postmortem lessons

This policy defines the four-stage promotion path from research to scale. Each stage has explicit numeric pass criteria, kill criteria, and minimum duration. Strategies that do not clear a gate stay at the prior stage or are sunset. Gate criteria cannot be waived; revisions require this policy doc to be updated and re-signed.

## Gate philosophy

Three principles, all derived from the HYDRA failure pattern:

1. **No advancement without measurement.** Every gate evaluation uses REALIZED PnL only (per measurement_policy.md section 1). Unrealized inventory drift does not count toward gate clearance.

2. **No advancement without time.** Each stage has a minimum duration. Cleared-on-paper-Sharpe with insufficient sample size is not cleared. The minimum durations are calibrated against the typical paper-to-live haircut and the time required to sample at least one adverse market event.

3. **Sunset is a valid outcome.** A strategy that fails gates cleanly is not a failed project -- it is information. The kill criteria below are the exit door.

## Stage 1: Research

**Purpose:** Validate that the strategy hypothesis has theoretical merit and the underlying game is structurally winnable at intended size.

**Entry criteria:**
- Game expected-value gate cleared per measurement_policy.md section 9 (EV >= 0.5% per round-trip net of all costs at intended size)
- Hypothesis written and committed to `research/hypotheses/<strategy_name>.md`
- Data sources identified and freshness-budget agreed
- Cost model parameters drafted (modeled spread, fees, slippage, funding)

**Activities permitted:**
- Backtest research using validated data (per data_policy.md)
- Walk-forward training and combinatorial purged cross-validation
- Feature engineering and selection
- Model training and selection
- Cost-modeled simulation against historical L2 data

**Pass criteria for advancement to Shadow:**
- Cost-modeled OOS Sharpe >= 3.0 over walk-forward periods of at least 12 months
- Deflated Sharpe Ratio (DSR) > 0
- Probabilistic Sharpe Ratio (PSR) >= 0.95 against null Sharpe of 1.0
- Combinatorial purged CV: median fold Sharpe >= 2.5, no fold < 1.0
- Max drawdown in walk-forward <= 15%
- Capacity estimate >= $100,000 (alpha does not degrade meaningfully at intended Phase 6 deployment size)
- Lookahead-bias test passed
- Survivorship-bias controls verified
- Cost model assumptions documented and challenged by adversarial simulation

**Kill criteria:**
- Cost-modeled OOS Sharpe < 1.5 after honest walk-forward -- sunset
- DSR < 0 (alpha is likely overfitting artifact) -- sunset
- Capacity estimate < $25,000 -- sunset (alpha exists but cannot scale to deployment size)
- Game-EV gate fails on re-evaluation at realistic costs -- sunset

**Minimum duration:** No minimum. Some hypotheses are rejected within days; others take weeks of careful walk-forward.

**Maximum duration:** 6 months. A strategy that has not advanced or sunset within 6 months of entering Research is reviewed for either commitment to advance or formal sunset.

## Stage 2: Shadow

**Purpose:** Validate that the strategy works against live market conditions with realistic execution modeling, before any capital is at risk.

**Entry criteria:**
- All Stage 1 pass criteria met
- Validation report committed to `research/reports/<strategy_name>_shadow_admission.md`
- Live data feeds for the strategy operational and verified per data_policy.md
- Cost model finalized and signed off
- Strategy code passes 100% behavioral coverage on order-touching paths per measurement_policy.md section 7

**Activities permitted:**
- Strategy generates signals against live data feeds
- Orders routed through paper adapter with realistic-fill modeling against live order book (Tardis L2 data)
- All orders go through full OMS chain including risk kernel
- Daily PnL recorded to ledger as if live (REALIZED column reflects modeled fills)
- All risk limits from risk_policy.md applied as if live; rejected orders logged

**Pass criteria for advancement to Canary:**
- 90 calendar days minimum continuous shadow operation
- Cost-modeled paper Sharpe >= 2.5 over the 90-day window
- Max drawdown <= 12% over the 90-day window
- Realized cost (in modeled fills) within 20% of model prediction (validates the cost model itself)
- Zero P0 measurement integrity bugs during the window
- Zero reconciliation breaks unresolved beyond the 60-second SLA
- At least one adverse market event (BTC -10%+ in 24h, vol spike, or funding spike) sampled in the window with strategy behaving correctly
- Capacity test re-validated: simulated fills at 3x intended canary size show no Sharpe degradation
- Behavioral coverage maintained at 100% on order-touching paths

**Kill criteria:**
- Cost-modeled paper Sharpe < 1.5 over any 60-day rolling window -- sunset
- Max drawdown > 18% -- sunset
- Cost model error > 50% on any 7-day window -- return to Research for cost-model rework
- Any P0 measurement integrity bug -- halt, postmortem, optional re-entry to Shadow with restart of 90-day clock

**Minimum duration:** 90 days. No exceptions. The 90-day minimum samples enough variance to be statistically meaningful and ensures at least one regime change is observed.

**Maximum duration:** 9 months. A strategy in shadow longer than 9 months without advancement is reviewed for either commitment to advance or formal sunset.

## Stage 3: Canary

**Purpose:** Validate that paper Sharpe survives contact with real fills and real slippage at small live capital. Measure the paper-to-live drift directly.

**Entry criteria:**
- All Stage 2 pass criteria met
- Validation report committed to `research/reports/<strategy_name>_canary_admission.md`
- Operator promotion event recorded per measurement_policy.md section 6, including hardware-key signature (Yubikey or equivalent)
- Initial canary capital allocated: $500-$2,000 per the canary phase row in risk_policy.md section 1
- Daily loss limit, weekly loss limit, max drawdown set per risk_policy.md
- All canary risk limits half the corresponding paper limits (extra conservatism with real money)

**Activities permitted:**
- Live trading at canary scale only
- Same OMS chain, same risk kernel as paper
- Real fills, real fees, real funding, real slippage
- Paper-to-live drift measurement on every fill: predicted price vs actual fill price, predicted slippage vs actual, predicted PnL contribution vs actual

**Pass criteria for advancement to Scale:**
- 90 calendar days minimum continuous canary operation
- Live Sharpe within 30% of preceding shadow Sharpe (paper-to-live haircut quantified and acceptable)
- Live Sharpe >= 1.5 absolute over the 90-day window
- Max drawdown <= 10% over the 90-day window
- Realized cost within 30% of model prediction (slightly looser than shadow due to live execution variance)
- Zero P0 measurement integrity bugs
- Zero reconciliation breaks unresolved beyond 60s SLA
- Zero unauthorized live trades (no L9-class incidents)
- Zero kill-switch engagements
- Drawdown state never entered RED during the window

**Kill criteria:**
- Live Sharpe < 1.0 over any 60-day rolling window -- sunset (paper-to-live haircut too severe to recover)
- Live Sharpe < 50% of shadow Sharpe -- return to Shadow for cost-model rework
- Max drawdown > 12% -- sunset
- Any unauthorized live trade -- halt entire strategy, full postmortem, sunset
- Any P0 measurement integrity bug -- halt, postmortem, optional re-entry to Shadow with restart of clock

**Minimum duration:** 90 days. No exceptions.

**Maximum duration:** 6 months. A canary not advanced or sunset within 6 months is reviewed for explicit decision.

## Stage 4: Scale

**Purpose:** Sustained live operation at meaningful capital, with continuous monitoring against degradation.

**Entry criteria:**
- All Stage 3 pass criteria met
- Scale promotion event recorded per measurement_policy.md section 6
- Capital allocation per risk_policy.md section 1 (Phase 6 early: $5K-$15K, mid: $15K-$50K)
- Kelly sizing applied with conservative fraction (1/4 Kelly default)

**Activities permitted:**
- Live trading at scale capital
- All Stage 3 monitoring continues
- Capital scaling decisions evaluated monthly

**Pass criteria for sustained scale (the 2.4 target):**
- 6 calendar months minimum continuous scale operation at $50K
- Live Sharpe >= 2.0 over the 6-month window (sustained verification)
- Live Sharpe >= 2.4 over the 6-month window meets the target threshold (success criterion)
- Max drawdown <= 12% over the 6-month window
- All canary kill criteria continue to apply

**Kill criteria:**
- Live Sharpe < 1.5 over any 60-day rolling window -- reduce capital by 50%, postmortem, decide continue-or-sunset within 30 days
- Live Sharpe < 1.0 over any 60-day rolling window -- sunset
- Max drawdown > 15% -- sunset
- Any unauthorized live trade -- sunset

**Minimum duration:** 6 months at full $50K to claim "2.4 target achieved." Below 6 months is preliminary, not validated.

## Failure criteria for the project as a whole

Independent of any individual strategy gate, SuperHydra as a project has its own failure criteria. These trigger explicit decision points, not necessarily sunset:

| Checkpoint | Trigger | Action |
|---|---|---|
| Phase 1 complete (Jun 15 2026) | Ledger does not pass acceptance criteria | Pause, fix, or abandon |
| Phase 4 (Dec 15 2026) | No engine has reached Shadow | Reduce scope to single engine, extend timeline |
| Phase 4 (Dec 15 2026) | Engine in Shadow has paper Sharpe < 2.5 | Postmortem, decide pivot or sunset |
| Phase 5 (Mar 15 2027) | No engine has cleared Canary admission | Sunset crypto quant for now; lessons remain |
| Phase 6 (Jun 15 2027) | Engine in Scale has live Sharpe < 1.5 over 90 days | Wind down, postmortem |
| Phase 6 (Nov 2027) | Engine has cleared 6-month sustained at >= 2.0 but not 2.4 | Hold position, decide whether to continue toward 2.4 or accept current Sharpe |
| Any time | SeCore or PenCore demand more attention than available | Pause cleanly, document state |

Sunset is documented in `docs/postmortems/<strategy>_sunset.md`. The doc describes what was tried, what failed, what was learned, and where the lessons port to (other strategies, other domains, other ventures).

## Revision log

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-05-02 | Wasseem Katt | Initial policy with 4-stage path calibrated to 2.4 live Sharpe target |
