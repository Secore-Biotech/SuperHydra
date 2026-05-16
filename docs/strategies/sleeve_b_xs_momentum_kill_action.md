# Sleeve B Cross-Sectional Momentum — Kill Action

**Committed:** 2026-05-16
**Author:** Operator
**Status:** Sleeve B candidate #1 (xs-momentum) is shelved as currently specified.

## Headline

The cross-sectional momentum construction specified in the binding pre-registration (commit `fe909bb`) is shelved as currently specified. The OOS backtest produced annualized Sharpe 1.381 — substantively above the 0.75 research-kill threshold and inside the candidate-status zone. The construction failed the 25% max-drawdown constraint by 0.92 percentage points (realized 25.92%). Per the reviewer-locked simultaneous-constraints rule, this is RESEARCH_KILL on fragility grounds, not on signal grounds.

## Reclassification

The construction's practical status, going forward, is:

- signal-positive
- constraint-failed
- research-killed under this specification

## Why this kill matters

The A2 kill action documented a signal failure: the strategy did not fire when it was supposed to. This kill action documents something different and more important. **The framework successfully rejected a statistically attractive construction because a pre-registered fragility constraint failed.**

Sharpe 1.381 is not noise. Annualized return of 85.09% is not noise. Cost drag of 5.28% is healthy. BTC and ETH betas are within bounds. Hit rate is well above the floor. Without the simultaneous-constraints rule, every natural human impulse would have been to promote this construction. Most quant processes fail exactly there — they look at an attractive Sharpe, gloss over the tail-risk caveat, and discover the cost in live trading.

The pre-registered drawdown limit caught this construction's fragility before any capital was at risk. That is the framework working as designed. The temptation to relax the limit by 0.92 percentage points was real; the discipline that refused to do so is the actual moat.

This is governance success under temptation. The signal failure mode (A2) and the fragility failure mode (this) are distinct, and the framework discriminates between them cleanly.

## Why the strategy was shelved

The construction was shelved because:

1. **Max drawdown 25.92% exceeded the 25.00% pre-registered limit.** The constraint was simultaneous with the Sharpe gate per pre-registration Section 5.
2. **The simultaneous-constraints rule was locked before the result.** The reviewer-locked classification this session made the failure-mode unambiguous: "Sharpe ≥ 0.75 AND any required constraint fails → Research kill (fragility)."
3. **The "no relative attractiveness" clause in Section 8 forbids grading on a curve.** Letting 25.92% slide because the result is Sleeve B's best so far would have made the governance layer negotiable.
4. **The construction therefore failed the pre-registered viability gate**, regardless of Sharpe attractiveness.

The construction is signal-positive on this universe. It is structurally fragile in tail risk. Those facts coexist; the framework binds on the second.

## What was disproven

Cross-sectional momentum as a signal family is **not** disproven. What was disproven is this exact implementation:

- 14-day lookback
- Weekly rebalance (Monday 00:00 UTC)
- 10% deciles (variable, min 1)
- 15% annualized vol target with 4-week cold start and 4-week trailing window
- Top-30 frozen universe as of 2026-04-15
- 14.5 bps round-trip fees
- No leverage cap

This specification produced 54.59% realized annualized volatility despite a 15% target — the vol-target under-reacted to crypto regime shifts — and 25.92% drawdown despite attractive Sharpe. A different specification (different lookback, vol-target window, leverage cap, decile size, or rebalance frequency) may still produce a construction that clears all gates simultaneously. Each such alternate specification is a separately pre-registered hypothesis with its own budget and kill criteria.

Future readers should infer "this specification failed," not "momentum failed."

## Evidence trail

The full empirical record:

- `docs/strategies/sleeve_b_research_preregistration.md` (commit `fe909bb`) — binding pre-registration
- `tests/fixtures/sleeve_b/universe_top30_20260415.json` (commit `2af9981`) — frozen universe, with survivorship disclosure
- `strategies/sleeve_b/xs_momentum/` (commit `11fa64b`) — engine modules + 43 synthetic unit tests
- `docs/strategies/sleeve_b_xs_momentum_result.md` (commit `d63e3c0`) — OOS result memo with Gate outcome
- `tests/fixtures/sleeve_b/xs_momentum_run_log.jsonl` — 157 weekly rebalance audit records
- `tests/fixtures/sleeve_b/xs_momentum_weekly_pnl.jsonl` — 157 weeks of P&L breakdown

## What survives

The infrastructure investment is preserved and directly reusable for Sleeve B candidate #2 (quality/profitability per reviewer recommendation). **Only the signal computation changes; everything else inherits without modification.**

- **Sleeve B pre-registration template**: universe-first ordering, four-gate classification, candidate-status constraints, time budget, no-relative-attractiveness clause
- **Frozen universe fixture pattern**: with survivorship disclosure, `raw_adv_candidates` audit trail, machine-readable freeze policy
- **`BinanceKlinesArchiveFetcher`**: reusable klines fetcher with `.notfound` cache markers, throttled HTTP, sort+dedupe — usable by any klines-based strategy
- **Engine architecture**: `universe.py`, `prices.py`, `portfolio.py`, `backtest.py` are signal-agnostic. The next candidate replaces only `signal.py`.
- **Audit log format**: per-rebalance JSONL with eligibility, deciles, turnover, scale, excluded symbols, P&L breakdown — reusable across constructions
- **Metrics and gate-classification pipeline**: Sharpe, drawdown, hit rate, cost drag, univariate beta, gate application machinery — directly reusable
- **Result-memo template**: explicit Gate outcome section structure with primary Sharpe gate result, constraint pass/fail table, final classification

The framing is: **strategy specification failed; research substrate validated and ready for the next signal family.**

## What is shelved

The xs-momentum-specific components remain in the repo as completed research artifacts but receive no further development:

- `strategies/sleeve_b/xs_momentum/signal.py` — 14-day momentum evaluator with 10% deciles
- `scripts/run_sleeve_b_xs_momentum.py` — hardcoded run script for this specification
- `tests/fixtures/sleeve_b/xs_momentum_run_log.jsonl` and `xs_momentum_weekly_pnl.jsonl` — preserved as audit artifacts

## What this does NOT mean

- It does not invalidate cross-sectional momentum as a signal family. A different specification may still produce a construction that clears all gates.
- It does not invalidate the pre-registration discipline. The discipline is what produced this answer in 5 minutes of compute rather than 5 months of rationalization.
- It does not invalidate the engine architecture. The engine is correct and reusable.
- It does not foreclose a future xs-momentum re-opening under a new pre-registered hypothesis with different parameters.

## Conditions for re-opening

The xs-momentum specification can be re-opened only if:

1. A new pre-registered hypothesis is committed before any new run.
2. The new hypothesis specifies materially different parameters than the current 14-day lookback, weekly rebalance, 10% decile, 15% vol target, no-leverage-cap construction.
3. Threshold tuning alone is not a new hypothesis. Adjusting the 25% drawdown limit to 30% on the existing construction is explicitly forbidden by the anti-cherry-pick rule.
4. The new pre-registration includes its own kill criteria, written before the test runs.

## Implications for Sleeve B

Sleeve B's first candidate (xs-momentum) is shelved. The reviewer-recommended candidate #2 is **quality/profitability-style factor**. That candidate is not yet pre-registered. Per the operating discipline, no implementation work on candidate #2 begins until its pre-registration is committed.

Sleeve B research budget remains: 41 days from this commit (default kill date 2026-06-27). Candidate #2's pre-registration and OOS test must fit within this remaining window, or candidate #2 itself gets shelved by the budget rule.

This memo does not amend the binding Sleeve B pre-registration. The pre-registration governs the entire Sleeve B research effort; this kill action concerns only candidate #1's specific construction.

## What was learned

Four durable lessons from the xs-momentum arc:

1. **Sharpe alone is not promotion-grade evidence.** A Sharpe 1.38 construction was killed because drawdown was 25.92%. Without the simultaneous-constraints rule, the natural impulse would have been to promote. The framework's discrimination — Sharpe-positive but constraint-failed — is exactly what prevents the "great Sharpe, terrible reality" trap. This is the central methodological lesson.

2. **Vol-target alone does not control tail risk.** The 15% annualized vol target produced 54.59% realized annualized volatility. The 4-week cold-start and 4-week trailing window under-reacted to crypto regime shifts. Vol-targeting is a smoothing mechanism, not a tail-risk gate. Drawdown limits exist precisely because vol-targeting can fail at controlling drawdown.

3. **Cost drag was not the binding constraint.** Pre-experiment expectation was that fees would dominate; actual cost drag was 5.28% of gross alpha, well below the 30% ceiling. For cross-sectional momentum on top-30 Binance perps with weekly rebalance, turnover is not what kills the strategy. Tail risk is. This is genuinely informative for future Sleeve B candidates: cost-anchored gating may not be the right primary discipline; volatility-and-drawdown gating is.

4. **The "no relative attractiveness" clause matters in practice, not just in theory.** Sleeve B candidate #1 producing Sharpe 1.38 is structurally better than every prior result in the program. The temptation to grade on a curve was real and the framework refused it. This was the clause's first live test, and it held.

## Source commits

- `fe909bb` Sleeve B research pre-registration (binding)
- `2af9981` Universe fixture frozen with survivorship disclosure
- `11fa64b` Engine + 43 synthetic unit tests
- `d63e3c0` OOS result: RESEARCH_KILL (Sharpe 1.381, drawdown 25.92%)

---

*This construction is shelved. The signal family is not. The engine is preserved. The framework killed a strong-looking but fragile construction — a more sophisticated outcome than killing a weak signal. That is the design intent.*
