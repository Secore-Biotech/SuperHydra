# Deployment Gates Policy

**Version:** 1.1
**Effective:** 2026-05-02 (revised from v1.0 same date)
**Author:** Wasseem Katt
**Goal:** Live portfolio Sharpe 2.4 sustained over 6 months by November 2027 (minimum institutional success); 3.5 stretch target dependent on multi-sleeve diversification
**Capital ceiling:** $50,000 USD at full Phase 6 scale
**Source:** SuperHydra Enhanced Plan; calibrated to QAnalytics live benchmark (2.31) and HYDRA postmortem lessons; v1.1 incorporates external review 2026-05-02
**Supersedes:** v1.0 (same date)

This policy defines the four-stage promotion path from research to scale. Each stage has explicit numeric pass criteria, kill criteria, and minimum duration. Strategies that do not clear a gate stay at the prior stage or are sunset. Gate criteria cannot be waived; revisions require this policy doc to be updated and re-signed.

## Why v1.1

v1.0 gates were strategy-level only. v1.1 adds portfolio-contribution criteria for when multiple engines run simultaneously (Phase 7+). v1.0 implicitly assumed L2 data would be available by Phase 4 but did not make verified L2 data a hard prerequisite for Research->Shadow promotion; v1.1 makes it explicit. v1.0 canary criterion "zero kill-switch engagements" was too strict -- a kill switch firing correctly during a venue outage is the system working, not failing; v1.1 distinguishes strategy malfunction from external events. v1.0 targeted 2.4 Sharpe; v1.1 acknowledges 3.5 as aspirational stretch while keeping 2.4 as the minimum success criterion. v1.1 adds conservative NAV gate criteria alongside realized-Sharpe criteria per measurement_policy v1.1.

## Sharpe targets -- minimum vs stretch

**Minimum institutional success target:** Live portfolio Sharpe >= 2.4 sustained over 6 months at $50K. This is the v1.0 target and remains the baseline.

**Stretch target:** Live portfolio Sharpe >= 3.5 sustained over 6 months. Achievable only via multi-sleeve diversification -- no individual strategy is expected to deliver 3.5 standalone. The stretch target requires:
- 2-3 uncorrelated sleeves (correlation |rho| < 0.3 between sleeves)
- Each sleeve at live Sharpe >= 1.8
- Allocator-driven combination (per allocator_policy.md)
- 6 months sustained verification at full $50K

**Realistic distribution per the Enhanced Plan:**
- 5% probability of clearing 3.5 stretch by November 2027
- 15-25% probability of clearing 2.4 minimum by November 2027
- 60-75% probability of partial success (one sleeve canary-cleared but below 2.0 sustained, or research-cleared but no canary)
- Remaining probability: full sunset

Strategies are evaluated against the minimum target. The stretch is a portfolio-level outcome that emerges (or doesn't) from multiple successful sleeves combined.

## Gate philosophy

Three principles, all derived from the HYDRA failure pattern:

1. **No advancement without measurement.** Every gate evaluation uses REALIZED PnL for promotion Sharpe AND conservative NAV for drawdown/risk per measurement_policy v1.1.

2. **No advancement without time.** Each stage has a minimum duration. Cleared-on-paper-Sharpe with insufficient sample size is not cleared.

3. **Sunset is a valid outcome.** A strategy that fails gates cleanly is not a failed project -- it is information.

## Stage 1: Research

**Purpose:** Validate that the strategy hypothesis has theoretical merit and the underlying game is structurally winnable at intended size.

**Entry criteria:**
- Game expected-value gate cleared per measurement_policy v1.1 section 11
- Hypothesis written and committed to `research/hypotheses/<strategy_name>.md`
- Data sources identified and freshness-budget agreed
- Cost model parameters drafted (modeled spread, fees, slippage, funding)

**Activities permitted:**
- Backtest research using validated data (per data_policy.md)
- Walk-forward training and combinatorial purged cross-validation
- Feature engineering and selection
- Model training and selection
- Cost-modeled simulation against historical L2 data (when available; lower-fidelity OHLCV-only research is admissible at Research stage but cannot satisfy Shadow admission criteria)

**Pass criteria for advancement to Shadow (v1.1: now includes L2 data prerequisite and conservative NAV criteria):**
- Cost-modeled OOS Sharpe >= 3.0 over walk-forward periods of at least 12 months (REALIZED basis, BACKTEST environment, MODELED_FILL settlement)
- Conservative NAV drawdown over walk-forward <= 15%
- Deflated Sharpe Ratio (DSR) > 0
- Probabilistic Sharpe Ratio (PSR) >= 0.95 against null Sharpe of 1.0
- Combinatorial purged CV: median fold Sharpe >= 2.5, no fold < 1.0
- Capacity estimate >= $100,000
- Lookahead-bias test passed
- Survivorship-bias controls verified
- Cost model assumptions documented and challenged by adversarial simulation
- **Hard prerequisite (v1.1):** A VERIFIED L2 order book data source per data_policy.md section on vendor verification status. Without verified L2 data, no strategy can advance to Shadow. Top-of-book or OHLCV-only research is acceptable at Research stage but does not satisfy Shadow admission.

**Kill criteria:**
- Cost-modeled OOS Sharpe < 1.5 after honest walk-forward -- sunset
- DSR < 0 (alpha is likely overfitting artifact) -- sunset
- Capacity estimate < $25,000 -- sunset (alpha exists but cannot scale)
- Game-EV gate fails on re-evaluation at realistic costs -- sunset

**Minimum duration:** None. Some hypotheses are rejected within days.

**Maximum duration:** 6 months. A strategy that has not advanced or sunset within 6 months is reviewed for either commitment to advance or formal sunset.

## Stage 2: Shadow

**Purpose:** Validate that the strategy works against live market conditions with realistic execution modeling, before any capital is at risk.

**Entry criteria:**
- All Stage 1 pass criteria met (including verified L2 prerequisite)
- Validation report committed to `research/reports/<strategy_name>_shadow_admission.md`
- Live data feeds for the strategy operational and verified per data_policy.md
- Cost model finalized and signed off
- Strategy code passes 100% behavioral coverage on order-touching paths per measurement_policy.md

**Activities permitted:**
- Strategy generates signals against live data feeds
- Orders routed through paper adapter with realistic-fill modeling against live order book (Tardis L2 data or equivalent VERIFIED source)
- All orders go through full OMS chain including risk kernel
- Daily PnL recorded to ledger (environment=SHADOW, settlement_type=MODELED_FILL per measurement_policy v1.1)
- All risk limits from risk_policy.md applied as if live; rejected orders logged

**Pass criteria for advancement to Canary:**
- 90 calendar days minimum continuous shadow operation
- Cost-modeled paper Sharpe >= 2.5 over the 90-day window (SHADOW + MODELED_FILL, REALIZED basis)
- Conservative NAV drawdown <= 12% over the 90-day window (SHADOW + UNREALIZED_MTM included)
- Realized cost (in modeled fills) within 20% of model prediction (validates the cost model itself)
- Zero P0 measurement integrity bugs during the window
- Zero reconciliation breaks unresolved beyond the 60-second SLA
- At least one adverse market event (BTC -10%+ in 24h, vol spike, or funding spike) sampled in the window with strategy behaving correctly
- Capacity test re-validated: simulated fills at 3x intended canary size show no Sharpe degradation
- Behavioral coverage maintained at 100% on order-touching paths
- **Portfolio-contribution criterion (v1.1, applies when other strategies are running):** Strategy must show positive marginal contribution to portfolio Sharpe, OR demonstrate value as hedge sleeve (drawdown reduction), execution sleeve (slippage reduction), or risk overlay (false-positive/negative metrics). See model_policy.md strategy-class taxonomy.

**Kill criteria:**
- Cost-modeled paper Sharpe < 1.5 over any 60-day rolling window -- sunset
- Conservative NAV drawdown > 18% -- sunset
- Cost model error > 50% on any 7-day window -- return to Research for cost-model rework
- Any P0 measurement integrity bug -- halt, postmortem, optional re-entry to Shadow with restart of 90-day clock
- Negative portfolio contribution sustained for 30 days when other strategies are running -- return to Research

**Minimum duration:** 90 days. No exceptions.

**Maximum duration:** 9 months.

## Stage 3: Canary

**Purpose:** Validate that paper Sharpe survives contact with real fills and real slippage at small live capital. Measure the paper-to-live drift directly.

**Entry criteria:**
- All Stage 2 pass criteria met
- Validation report committed to `research/reports/<strategy_name>_canary_admission.md`
- Operator promotion event recorded per measurement_policy v1.1, with hardware-key signature (Yubikey or equivalent)
- Initial canary capital allocated: $500-$2,000 per the canary phase row in risk_policy.md
- Daily loss limit, weekly loss limit, max drawdown set per risk_policy.md (using conservative NAV per v1.1)
- All canary risk limits half the corresponding paper limits (extra conservatism with real money)

**Activities permitted:**
- Live trading at canary scale only (environment=LIVE, settlement_type=CONFIRMED_SETTLED)
- Same OMS chain, same risk kernel as paper
- Real fills, real fees, real funding, real slippage
- Paper-to-live drift measurement on every fill: predicted price vs actual fill price, predicted slippage vs actual, predicted PnL contribution vs actual

**Pass criteria for advancement to Scale:**
- 90 calendar days minimum continuous canary operation
- Live Sharpe (REALIZED) within 30% of preceding shadow Sharpe (paper-to-live haircut quantified and acceptable)
- Live Sharpe >= 1.5 absolute over the 90-day window
- Conservative NAV drawdown <= 10% over the 90-day window
- Realized cost within 30% of model prediction
- Zero P0 measurement integrity bugs
- Zero reconciliation breaks unresolved beyond 60s SLA
- Zero unauthorized live trades (no L9-class incidents)
- **Kill-switch criterion (v1.1, refined):** No manual emergency kill switches caused by strategy malfunction. Auto-triggered kill switches due to external venue/data outage are acceptable provided: the kill switch fired correctly, no unauthorized trade occurred, positions were reconciled, postmortem confirms expected behavior. A canary that correctly halted during a Binance/Tardis outage and resumed cleanly afterward does not fail this criterion.
- Drawdown state never entered RED during the window (cons NAV)
- **Portfolio-contribution criterion (v1.1, applies when other strategies are running):** Same as Shadow stage -- positive marginal contribution OR demonstrated value in non-alpha role.

**Kill criteria:**
- Live Sharpe < 1.0 over any 60-day rolling window -- sunset
- Live Sharpe < 50% of shadow Sharpe -- return to Shadow for cost-model rework
- Conservative NAV drawdown > 12% -- sunset
- Any unauthorized live trade -- halt entire strategy, full postmortem, sunset
- Any P0 measurement integrity bug -- halt, postmortem, optional re-entry to Shadow with restart of clock
- Manual emergency kill switch caused by strategy malfunction -- sunset

**Minimum duration:** 90 days.

**Maximum duration:** 6 months.

## Stage 4: Scale

**Purpose:** Sustained live operation at meaningful capital, with continuous monitoring against degradation.

**Entry criteria:**
- All Stage 3 pass criteria met
- Scale promotion event recorded per measurement_policy v1.1
- Capital allocation per risk_policy.md (Phase 6 early: $5K-$15K, mid: $15K-$50K)
- Kelly sizing applied with conservative fraction (1/4 Kelly default)

**Activities permitted:**
- Live trading at scale capital
- All Stage 3 monitoring continues
- Capital scaling decisions evaluated monthly

**Pass criteria for sustained scale (the 2.4 minimum target):**
- 6 calendar months minimum continuous scale operation at $50K
- Live Sharpe (REALIZED) >= 2.0 over the 6-month window (sustained verification)
- Live Sharpe >= 2.4 over the 6-month window meets the minimum success criterion
- Conservative NAV drawdown <= 12% over the 6-month window
- All canary kill criteria continue to apply

**Pass criteria for stretch (the 3.5 stretch target):**
- All minimum criteria met
- Portfolio (multiple sleeves combined) live Sharpe >= 3.5 over the 6-month window
- Sleeve correlation |rho| < 0.3 sustained
- Each sleeve at live Sharpe >= 1.8 standalone
- Allocator-driven combination (per allocator_policy.md)

The stretch target is a portfolio-level outcome and depends on multiple sleeves clearing canary. It is not a target individual strategies are evaluated against.

**Kill criteria:**
- Live Sharpe < 1.5 over any 60-day rolling window -- reduce capital by 50%, postmortem, decide continue-or-sunset within 30 days
- Live Sharpe < 1.0 over any 60-day rolling window -- sunset
- Conservative NAV drawdown > 15% -- sunset
- Any unauthorized live trade -- sunset

**Minimum duration:** 6 months at full $50K to claim minimum target achieved.

## Failure criteria for the project as a whole

Independent of any individual strategy gate, SuperHydra has its own failure criteria:

| Checkpoint | Trigger | Action |
|---|---|---|
| Phase 1 complete (Jun 15 2026) | Ledger does not pass acceptance criteria | Pause, fix, or abandon |
| Phase 4 (Dec 15 2026) | No engine has reached Shadow | Reduce scope to single engine, extend timeline |
| Phase 4 (Dec 15 2026) | Engine in Shadow has paper Sharpe < 2.5 | Postmortem, decide pivot or sunset |
| Phase 5 (Mar 15 2027) | No engine has cleared Canary admission | Sunset crypto quant for now; lessons remain |
| Phase 6 (Jun 15 2027) | Engine in Scale has live Sharpe < 1.5 over 90 days | Wind down, postmortem |
| Phase 6 (Nov 2027) | Engine has cleared 6-month sustained at >= 2.0 but not 2.4 | Hold position, decide whether to continue toward minimum or accept current Sharpe |
| Any time | SeCore or PenCore demand more attention than available | Pause cleanly, document state |

Sunset is documented in `docs/postmortems/<strategy>_sunset.md`.

## Policy hierarchy

This policy is part of the SuperHydra Policy Pack. When policies conflict:

1. Safety/compliance/venue permission requirements
2. Risk policy
3. Measurement policy
4. Deployment gates policy (this document)
5. Data policy
6. Model policy
7. Allocator policy
8. Incident severity policy

The stricter safety/risk interpretation applies until policies are amended and re-signed.

## Revision log

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-05-02 | Wasseem Katt | Initial policy with 4-stage path calibrated to 2.4 live Sharpe target |
| 1.1 | 2026-05-02 | Wasseem Katt + external reviewer | Added conservative NAV drawdown criteria alongside REALIZED Sharpe per measurement_policy v1.1. Added VERIFIED L2 data as hard prerequisite for Shadow admission. Added portfolio-contribution criteria for Shadow/Canary when multiple engines run. Refined kill-switch criterion to distinguish strategy malfunction from external venue/data outage. Added 3.5 stretch target as portfolio-level aspirational outcome alongside 2.4 minimum. Added probabilistic distribution of outcomes. Added policy hierarchy. |
