# SOL Roll-spread estimation memo (Day 19b.3 research-only)

This memo records the methodology and intended use of the
`scripts/estimate_binance_roll_spread.py` harness, which applies
Roll's classical autocovariance estimator (Roll 1984) to short
windows of Binance SOLUSDT aggregate-trade data to produce a second,
independent research-calibrated estimate of effective spread for
comparison with Day 19a's 1 bp/leg slippage assumption.

## Question

Does Roll's tape-based effective-spread estimate corroborate or
contradict Day 19a's research-calibrated 1 bp per leg slippage
assumption (derived from Kaiko + Amberdata third-party spread data)?

## Methodology

For each of two predefined regimes, the harness fetches five
non-overlapping 5-minute windows of SOLUSDT aggregate-trade data
from Binance USDM-Futures `/fapi/v1/aggTrades`, applies Roll's
estimator per window, and writes a JSON artifact summarizing
per-window estimates plus aggregate statistics (median, mean, min,
max across valid windows; count undefined).

### Regime definitions

| Regime | Window | Why |
| --- | --- | --- |
| `quiet` | 2025-01-01 to 2025-01-15, 12:00 UTC at days 1, 4, 7, 10, 13 | Same period as Day 18 Jan 2025 SOL funding probe (mean 0.14 bps funding). Quiet liquidity regime. |
| `volatile` | 2024-03-01 to 2024-03-15, 12:00 UTC at days 1, 4, 7, 10, 13 | Same period as Day 18b SOL Mar 2024 funding fixture (mean 6 bps funding, 100% positive intervals, memecoin frenzy). High-volatility regime. |

Five samples per regime is intentionally small. The goal is a
sanity check across a few representative slices, not a
high-statistical-power calibration.

### Per-window estimator behavior

For each window:
- Fetcher returns N aggregate trades (N varies; SOLUSDT typically
  has 1k-10k trades per 5 minutes).
- Estimator computes first-order sample autocovariance of price
  changes with mean correction.
- If autocov < 0: estimate is defined; half-spread = sqrt(-autocov),
  full-spread = 2 * half-spread, bps = spread / mean_price * 10000.
- If autocov >= 0: estimate is undefined (reason: directional flow
  or trend dominates within the window).
- If N < 3 or estimator raises: window is skipped.

Aggregate statistics are computed over windows with defined
estimates only.

### Raw data is ephemeral

The harness does NOT persist raw trade data. Aggregate trade volume
for SOLUSDT in volatile periods can reach 10k+ trades per 5-minute
window; storing across multiple regimes and windows would bloat the
repo significantly without providing reproducibility benefits beyond
what the timestamp + symbol parameters already give. The harness is
designed so any future re-run with the same parameters reproduces
the same estimate (subject to vendor restatement, which is rare for
historical aggTrades).

## Why this is research-only

1. **Roll's estimator assumes random buy/sell aggressor sequence.**
   Real markets often have asymmetric flow; biased aggressor mix
   inflates or deflates the estimate.

2. **Roll's estimator assumes no information flow.** Trending
   periods produce positive autocovariance and undefined estimates.
   This is honest behavior (the estimator correctly says "I cannot
   measure spread under these conditions"), but it means estimates
   from volatile regimes may be systematically more often undefined
   than from quiet regimes.

3. **Static-spread assumption per window.** A 5-minute window
   averages spread variation within. Spread can spike intra-minute
   on news; we do not capture that here.

4. **Trade-side aware estimators are strictly better when feasible.**
   Lee-Ready (1991) and Glosten-Harris (1988) use aggressor side to
   reduce bias. We use Roll because BinanceTrade.is_buyer_maker only
   tells us aggressor side (not resting side at fill time), and a
   side-aware estimator implementation is out of scope for Day 19b.
   A future Day could add Lee-Ready as a second tape estimator.

5. **No live A1 fills.** This is the most important caveat. The
   most authoritative calibration would come from A1's own paper
   fills on the venue at A1's clip size in A1's actual trading
   regimes. Roll on public aggTrades is one step closer than
   third-party aggregated spread data (Kaiko, Amberdata) but still
   one step away from live execution.

For these reasons, Roll's tape estimate IS NOT sufficient to promote
`binance_vip5_alt_research_v1` to `binance_vip5_alt_empirical_v1`.
The promotion path requires live A1 paper fills (Day 20+).

## Interpretation guide

When the artifact is generated, compare the aggregate
`full_spread_bps_median` to Day 19a's research-calibrated 1 bp per
leg (= 2 bps full spread):

| Median full spread | Interpretation |
| --- | --- |
| 0.5-2 bps | Corroborates Day 19a calibration. Confidence in research profile increases (still not promoted). |
| 2-5 bps | Day 19a may be slightly optimistic. Research profile remains research-only; sensitivity bounds documented in Day 19a memo (0.5-1.5 bps per leg) cover up to ~3 bps full spread. |
| 5+ bps | Day 19a calibration is materially off. Research profile should be flagged in its notes; an updated research profile with the higher number may be added; alternatively, conclude that A1 cannot be tradeable on SOLUSDT under realistic costs and re-pivot. |

A high count of `undefined` windows in volatile regime is itself
a finding: it suggests the estimator is signal-saturated by
directional flow during the regimes A1 most wants to trade in,
which is a methodological argument for moving to side-aware
estimators or live fills.

## What promotes the research profile to empirical

The reviewer-locked path remains:

1. **Day 20+**: Live A1 paper fills on the venue at production-
   equivalent clip sizes, with adverse-fill cost recorded per fill.
2. **Promotion**: When live-fill estimates land within Day 19a's
   sensitivity bounds (0.5-1.5 bps per leg), promote to
   `binance_vip5_alt_empirical_v1` and update selector.

Day 19b results inform but do NOT replace Day 20 live-fill
calibration.

## Out of scope here

- Lee-Ready or Glosten-Harris side-aware estimators (future Day).
- Larger samples (full hours rather than 5-minute snippets).
- Other Binance instruments (BTCUSDT, ETHUSDT, DOGEUSDT) — same
  harness can be re-run with `--symbol`, but interpretation per
  instrument requires its own memo.
- Other venues (OKX, Bybit, Hyperliquid).

## Reproducibility

The harness is deterministic given (symbol, window_start, window_minutes)
inputs. Re-running with the same arguments produces the same estimate
unless Binance restates historical trades (rare for aggTrades). The
artifact records `started_at_utc` / `finished_at_utc` for audit;
the result itself does not depend on wall-clock time of run.

## Sources

| Source | Citation |
| --- | --- |
| Roll, R. (1984) | "A Simple Implicit Measure of the Effective Bid-Ask Spread in an Efficient Market." Journal of Finance, 39(4), 1127-1139. |
| Lee, C. and Ready, M. (1991) | "Inferring Trade Direction from Intraday Data." Journal of Finance, 46(2), 733-746. |
| Glosten, L. and Harris, L. (1988) | "Estimating the components of the bid/ask spread." Journal of Financial Economics, 21(1), 123-142. |
| Day 19a memo | docs/research/sol_slippage_calibration_memo.md |
