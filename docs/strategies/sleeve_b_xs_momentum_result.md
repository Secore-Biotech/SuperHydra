# Sleeve B Cross-Sectional Momentum — OOS Backtest Result

Generated: 2026-05-16T10:50:06.169068+00:00
Run ID: `sleeve_b_xs_momentum_v1`
Pre-registration: `docs/strategies/sleeve_b_research_preregistration.md` (commit fe909bb)
Universe fixture: `tests/fixtures/sleeve_b/universe_top30_20260415.json` (commit 2af9981)
Engine: commit 11fa64b

## Survivorship-bias disclosure

The universe is the top-30 by ADV **as of 2026-04-15**, applied retroactively to a 36-month OOS window. Assets that were top-30 earlier in the window but had failed by 2026 are not in this test. This is survivorship bias by construction. The result answers: *would the assets that became top-30 by 2026-04-15 have exhibited momentum alpha historically?* It does not answer *what was the real tradeable top-30 at every historical point*.

## Configuration

- OOS window: 2023-04-15 → 2026-04-15 (36 months)
- Universe: top-30 Binance USDT-perps by ADV (frozen)
- Lookback: 14 days close-to-close at 00:00 UTC
- Rebalance: Monday 00:00 UTC, weekly
- Decile fraction: 10%, variable, min 1 (D9)
- Listing-age delay: 14 days (D10)
- Min eligible: 4 (D11)
- Vol target: 15% annualized
- Cold start: 4 weeks (uniform scale = 1.0)
- Fees: 14.5 bps round-trip per asset
- Holding: 7 days
- No leverage cap (documented)

## Run summary

- Total rebalance dates: 157
- Rebalances executed: 157
- Rebalances skipped (eligible < 4): 0
- Total weeks of P&L: 157

## Primary metrics

| Metric | Value |
|---|---|
| **Annualized Sharpe (net)** | **1.381** |
| Annualized return (net) | 85.09% |
| Annualized volatility | 54.59% |
| Max drawdown | 25.92% |
| Hit rate (weeks > 0) | 56.05% |
| Cost drag (% of gross alpha) | 5.28% |
| Beta to BTC (univariate weekly) | +0.133 |
| Beta to ETH (univariate weekly) | +0.042 |

## Gate outcome

**Classification: `RESEARCH_KILL`**

Sharpe 1.381 clears the Sharpe gate but the following simultaneous constraints failed: max_drawdown. Family shelved due to construction fragility per pre-registration Section 5.

### Primary Sharpe gate result

| Gate | Threshold | Actual | Pass |
|---|---|---|---|
| Research kill (must clear) | Sharpe >= 0.75 | 1.381 | YES |
| Promotion eligibility | Sharpe >= 1.5 | 1.381 | NO |

### Constraint pass/fail table

| Constraint | Limit | Actual | Pass |
|---|---|---|---|
| btc_beta | within +/- 0.15 | +0.133 | YES |
| eth_beta | within +/- 0.15 | +0.042 | YES |
| max_drawdown | <= 25% | 25.92% | **NO** |
| cost_drag_pct_of_gross_alpha | <= 30% | 5.28% | YES |
| hit_rate | >= 45% | 56.05% | YES |

### Final classification

**`RESEARCH_KILL`**

Per pre-registration anti-cherry-pick rule, this result is binding. No further work on cross-sectional momentum under this specification. Alternate hypotheses (different lookback, different universe, different construction) constitute separately pre-registered hypotheses with their own budgets and kill criteria, and they cannot use this run's data as in-sample evidence.

## Artifacts

- Run log: `tests/fixtures/sleeve_b/xs_momentum_run_log.jsonl`
- Weekly P&L: `tests/fixtures/sleeve_b/xs_momentum_weekly_pnl.jsonl`

---

*This result is binding per the pre-registration. The clock continues for the remaining Sleeve B research budget (default kill date 2026-06-27).*