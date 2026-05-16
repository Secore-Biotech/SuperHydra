# Sleeve B — Research Pre-Registration

**Committed:** 2026-05-16
**Author:** Operator
**Status:** Binding pre-registration. Anti-cherry-pick rules apply per Section 9.
**Research budget clock starts:** 2026-05-16
**Default kill date if no definitive result:** 2026-06-27 (6 weeks)

## 0. Operating philosophy

SuperHydra is a governed signal-validation framework. Portfolio construction is downstream of signal validity. A signal must independently survive cost-realistic, anti-cherry-pick, OOS-disciplined testing before any portfolio question is asked about it.

Sleeve B is the first test of whether the framework can produce a single survivable signal after the A1/A2 arc. The pre-registration is the governance instrument; the research is what it bounds.

The single rule that takes precedence over everything else in this document:

*Signals are not promoted based on relative attractiveness versus other failed signals. They are promoted only against absolute pre-registered criteria.*

## 1. Universe (locked first)

Universe specification is pre-registered *before* signal mechanics because universe selection is the largest single overfitting surface in cross-sectional crypto strategies. Locking universe rules upfront is the difference between testing a hypothesis and fitting one.

- **Exchange:** Binance USDT-margined perpetual futures (single venue)
- **Asset class:** Perpetual contracts only; no spot, no dated futures
- **Universe size:** Top-30 by ADV
- **ADV window:** Fixed 30 calendar days ending 2026-04-15 (i.e., 2026-03-15 to 2026-04-15)
- **ADV metric:** Sum of taker volume in USDT over the ADV window, divided by 30
- **Stablecoins:** Excluded (USDC, DAI, FDUSD, etc. and any USDT-quoted stable-stable pair)
- **Wrapped/derivative tokens:** Treated as their underlying for inclusion; the underlying must clear the listing-age rule (e.g., WBTC counts as BTC if BTC clears, not as a separate name)
- **Minimum listing age:** 90 days from listing date as of 2026-04-15
- **Minimum continuous trading days in ADV window:** 60 out of the 30-day window — i.e., the asset must have continuously traded for the prior 60+ days at ADV-window start (this prevents brief listings or recently-relisted tokens from entering)

  *(Note: this is a 60-day continuous-history requirement *prior* to the ADV window, not a within-window day count. Stated this way to remove ambiguity.)*

- **Delisted or halted during research window:** Excluded retroactively from research outputs; the universe is fixed once computed but assets that delist or halt during the research window are dropped from forward-looking returns starting at the delisting/halting timestamp
- **Survivorship handling:** The universe is computed once at pre-registration commit time using only data available as of 2026-04-15. No look-ahead. No re-computation. No additions for new listings during the research window.
- **Computation timing:** Universe is computed and frozen no later than 2026-05-23 (one week after pre-registration commit). The frozen list is committed to the repo as `tests/fixtures/sleeve_b/universe_top30_20260415.json` with the ADV value for each asset, committed in the same commit as the first backtest run.

## 2. Signal mechanics (locked)

- **Family:** Cross-sectional momentum
- **Lookback:** 14 days of trailing total return
- **Return measurement:** Close-to-close return over 14 calendar days, using Binance USDT-perp close at 00:00 UTC
- **Rebalance cadence:** Weekly
- **Rebalance day-of-week:** Monday 00:00 UTC
- **Ranking:** All 30 universe assets ranked by 14-day trailing return at each rebalance
- **Position construction:** Long top decile, short bottom decile
- **Decile definition:** With universe size 30, decile = 3 names. Top decile = top 3 by trailing return; bottom decile = bottom 3.
- **Weighting:** Equal-weighted within each decile. Each long position = 1/3 of long capital; each short position = 1/3 of short capital.
- **Beta-neutral construction:** Long-short equal-notional (gross-balanced, dollar-neutral). Beta neutrality is structural, not optimized.
- **Portfolio volatility target:** 15% annualized
- **Vol-target mechanism:** Position sizing scaled inversely to trailing 30-day realised portfolio volatility (computed on the previous week's actual realised P&L; first 4 weeks use uniform 15% assumption)
- **Holding period between rebalances:** 7 days (one full week); positions held passively between Mondays

## 3. Costs and execution model

- **Round-trip fees:** 14.5 bps per round-trip per asset (Binance taker 4.5 bps perp × 2 ≈ 9.0 bps; conservative round-up to match A2 Step 3 convention is 14.5 bps to also absorb spread crossing)
  
  *(Note: A2 used 14.5 bps = 4.5 perp + 10.0 spot taker. Sleeve B is perp-only on both legs, so the fee is structurally lower at ~9 bps round-trip; the 14.5 bps figure is retained for conservatism and consistency with A2's cost baseline. If results are sensitive to fee assumption, that sensitivity must be reported.)*

- **Slippage model:** Per Sleeve A profile (same cost model used in A1/A2 P1 paper testing) — applied per fill at the modeled bps
- **Realised slippage observation:** If/when paper stage is reached, observed slippage via the existing replay machinery (compute_observed_slippage on real Binance archive trades around each rebalance fill). OOS backtest uses modeled-only slippage by necessity.
- **Cost drag calculation:** For each rebalance, the turnover-weighted cost = (turnover bps × fee_bps). Annualized cost drag = weekly cost × 52.

## 4. OOS evaluation

- **OOS window:** 36 months — 2023-04-15 to 2026-04-15
- **OOS data source:** Binance archive (perp aggregate trades) — same source as A2 Step 3 fixture refresh
- **In-sample:** None. There is no parameter-fitting phase. The construction is fully specified above before any backtest is run; the entire 36-month window is treated as one OOS test. This is unusual but justified: every parameter is mechanically derived from academic-standard momentum literature (14-day lookback, weekly rebalance, decile construction) rather than from data-fitted optimization.
- **Backtest mechanics:** For each Monday 00:00 UTC in the OOS window where the universe is fully tradable, compute trailing 14-day returns for all 30 universe assets, rank, select top-3 and bottom-3 deciles, size per vol-targeting rule, compute realized P&L over the following week using close prices, accrue cost drag at 14.5 bps × turnover.
- **Performance metric:** Annualized Sharpe ratio of weekly P&L net of costs
- **Secondary metrics required in research output:**
  - Annualized return (net)
  - Annualized volatility
  - Maximum drawdown
  - Hit rate (% of weeks with positive P&L)
  - Turnover (% of book traded per week)
  - Cost drag as % of gross alpha
  - Beta to BTC and ETH over the full window
  - Rolling 12-month Sharpe (for stability assessment)

## 5. Gates and classification

The four-gate classification structure is the central governance addition over A1/A2. Binary "alive/dead" was insufficient; this structure recognizes that a signal can be informative without being deployable.

| Gate | Threshold | Meaning |
|---|---|---|
| **Research kill** | OOS Sharpe < 0.75 net of costs | Family shelved. No further work under this specification. |
| **Candidate status** | 0.75 ≤ OOS Sharpe < 1.5 net of costs | Interesting but unproven. Constrained-research-only per Section 6. |
| **Promotion eligibility** | OOS Sharpe ≥ 1.5 net of costs | Earns research → paper review per roadmap v2.2 Appendix B. |
| **Paper → canary** | Paper Sharpe ≥ 2.0 over ≥ 60 days | Operational viability gate per roadmap v2.2 §2. |

The first three gates are evaluated at the end of OOS backtest. The fourth is downstream and out of scope for this pre-registration; it applies only if Gate 3 (promotion eligibility) is cleared and the construction proceeds through Appendix B and into paper.

### Additional gate conditions (must hold simultaneously with Sharpe threshold)

Even with Sharpe ≥ 0.75, the following must hold for candidate status:

- Beta to BTC within ±0.15 over the full OOS window
- Beta to ETH within ±0.15 over the full OOS window
- Maximum drawdown ≤ 25% (peak-to-trough on equity curve)
- Cost drag ≤ 30% of gross alpha (roadmap v2.2 §B.3)
- Hit rate ≥ 45% on weekly P&L

If any of these conditions fails, the signal does not reach candidate status even if Sharpe clears 0.75. This prevents a high-Sharpe-but-fragile construction (concentrated bets, levered alpha, extreme drawdowns) from being promoted on Sharpe alone.

## 6. Candidate status — permitted and forbidden activities

If the construction lands at 0.75 ≤ Sharpe < 1.5, it earns candidate status. Candidate status is not a promotion. It is a constrained-research zone that permits *falsification activities* but forbids *modification activities*.

**Permitted under candidate status:**
- Replication runs (re-run the locked construction on the same OOS window, verify reproducibility)
- Robustness checks: alternate OOS time slices (sub-windows of the 36-month OOS window), different starting Mondays for the rebalance grid (verify no day-of-week artifact), exclusion-leave-one-out tests on individual universe assets
- Stress decomposition: condition the OOS Sharpe on regime markers (BTC vol terciles, total crypto market cap regimes, BTC drawdown periods) to characterize when the strategy works and when it doesn't
- Implementation realism improvements: better cost models, observed-slippage measurement on a paper run (if paper stage is reached), more conservative fill assumptions
- Documentation of failure modes, regime dependence, capacity constraints

**Forbidden under candidate status (without a new pre-registration):**
- Parameter tuning (lookback ≠ 14 days, rebalance day ≠ Monday, decile size ≠ 3, lookback variants like 7/21/30-day blend, weighted-average ranking)
- Universe changes (top-50 instead of top-30, sector filters, exchange additions, listing-age adjustments)
- Rebalance cadence changes (daily, monthly, biweekly)
- Threshold or filter changes (z-score gates, momentum-strength filters, volatility filters on individual assets)
- Feature additions (long-only variants, sector-neutral overlays, BTC-hedge overlays, regime-conditional sizing)
- Construction changes (long-top-tercile/short-bottom-tercile, weighted-by-strength, leveraged variants)

The asymmetry: permitted activities can only *reveal weaknesses*. Forbidden activities can *manufacture strength* by overfitting. Any forbidden activity is a new hypothesis and requires its own pre-registration with its own kill criterion.

## 7. Time budget

Research budget: **6 weeks from pre-registration commit (2026-05-16 to 2026-06-27)**.

If by 2026-06-27 the OOS backtest has not produced a definitive Gate-1/2/3 classification, the family is shelved by default.

Rationale: research drift is the dominant failure mode of programs that have already solved engineering, infrastructure, and idea-generation. The A2 arc consumed roughly 90 days from Day 21 design brief to Step 3 kill action. Most of that was correct engineering work, but the absence of an explicit time budget meant there was no forcing function for "the test isn't producing an answer." A 6-week budget on Sleeve B makes the absence of a result *itself* a result.

This budget covers research only. Promotion through Appendix B (research → paper) and §2 (paper → canary) is downstream and not bounded by this clock.

## 8. Anti-cherry-pick (binding)

Per the A2 Step 3 pre-registration's anti-cherry-pick rule, applied analogously here:

1. **All parameters in Sections 1, 2, 3, 4, 5 are locked at pre-registration commit time.** No parameter may be modified after the first OOS backtest is run. Any change constitutes a new pre-registered hypothesis.

2. **Alternate universes, lookbacks, rebalance cadences, weightings, or constructions are separately pre-registered hypotheses.** They are not modifications of this hypothesis. They cannot use Sleeve B's research budget; each requires its own pre-registration with its own budget and kill criterion.

3. **A null or negative result is the answer, not an invitation to retest.** If OOS Sharpe < 0.75, the family is shelved per Gate 1; no further work under this specification is permitted regardless of how close the result came to clearing.

4. **Relative attractiveness is not a promotion mechanism.** Signals are promoted only against absolute pre-registered criteria (Section 5 gates). A construction that lands at Sharpe 0.6 does not earn candidate status because A1 and A2 were worse. It earns the kill criterion of this pre-registration. After enough failed signals, the psychological temptation to grade on a curve is real; this clause makes the rule explicit.

5. **The 6-week time budget is not extendable.** Extensions require operator-logged decision per §10 of roadmap v2.2 with written justification, and they cannot exceed 2 additional weeks. Beyond 8 weeks total, the family is shelved regardless.

## 9. What success and failure each look like

**If OOS Sharpe < 0.75 (most likely outcome by a priori expectation):**
- Family shelved per Gate 1
- Kill-action memo written at `docs/strategies/sleeve_b_xs_momentum_kill_action.md`
- Sleeve B re-opens with a different signal family (quality, mean-reversion, or other) under a new pre-registration
- No further cross-sectional momentum work under this specification

**If 0.75 ≤ OOS Sharpe < 1.5:**
- Candidate status granted
- Constrained-research activities permitted per Section 6
- Time budget remains 6 weeks total from original commit; candidate-status research consumes the budget
- Re-evaluation at week 6 with all candidate-research findings in hand

**If OOS Sharpe ≥ 1.5 with all secondary conditions met:**
- Promotion eligibility cleared
- Appendix B research-to-paper checklist initiated
- Paper run on production OMS/risk/ledger path (same plumbing as A1/A2 paper runs)
- The signal does not enter "the portfolio" because there is no portfolio yet. It enters its own paper canary track, same as any other engine.

## 10. What this pre-registration deliberately does NOT contain

- No portfolio construction plan. Portfolio is downstream; built only after at least one Sleeve B candidate (and ideally a second) has independently cleared promotion eligibility.
- No multi-signal framework. This pre-registration concerns one signal family. Adding more is a separate decision.
- No QAnalytics-comparison framing. Whatever QAnalytics does, this signal succeeds or fails on its own pre-registered criteria.
- No claim that cross-sectional momentum is "the right" Sleeve B candidate beyond "it is the first one being tested under this framework." If it fails, the framework remains intact and the next candidate is tested under its own pre-registration.

## 11. Source commits and references

- Roadmap v2.2: `SuperHydra_FreshStart_Roadmap_v2_2.docx` (project files)
- A2 Step 3 pre-registration template: `docs/strategies/a2_step3_preregistration.md` (commit `8ee5ecb`)
- A2 kill action: `docs/strategies/a2_kill_action.md` (commit `924a930`)
- Cost baseline: 14.5 bps round-trip established in A2 Step 3 (commit `75ca27d`)

## 12. Operator sign-off

Pre-registration committed under §10 authority of roadmap v2.2. Logged as a phase decision (Sleeve B P0 entry).

Decision-log entry:
- Date: 2026-05-16
- Phase: Sleeve B → P0 Research & Build
- Evidence reference: This pre-registration
- Justification: Per A2 Step 3 kill action (commit `924a930`), Sleeve B is next per reviewer-locked direction. Cross-sectional momentum selected as first candidate per the comparative pass against five candidate families, with reviewer concurrence. Pre-registration follows the A2 Step 3 governance template extended with four-gate classification, universe-first ordering, candidate-status constraints, and 6-week time budget.

---

*This pre-registration is binding. All parameters above are locked at commit time. Modification requires a new pre-registration with its own kill criteria. The time budget is the forcing function; the four gates are the discipline; the universe-first ordering closes the largest overfitting surface; the candidate-status constraint closes the silent-optimization loophole. None of this guarantees the signal works. All of it guarantees the answer will be honest.*
