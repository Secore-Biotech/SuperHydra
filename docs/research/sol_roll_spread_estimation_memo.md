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


## Results — Day 19b execution attempt (2026-05-09)

### Run 1: quiet regime (Jan 2025)

```
python3 scripts/estimate_binance_roll_spread.py \
    --symbol SOLUSDT --regime quiet --output artifacts/sol_quiet_jan2025.json
```

**Result: 0 trades returned across all 5 windows.** Aggregate JSON:

```json
{
  "n_windows_total": 5,
  "n_windows_valid": 0,
  "n_windows_undefined": 0,
  "n_windows_skipped": 5
}
```

Every window was skipped with reason `too_few_trades_for_estimator`
because the venue returned zero records.

### Diagnostic: direct REST probe

To rule out a fetcher bug, the same URL pattern was issued via raw
stdlib `urllib`, bypassing `BinanceTradeFetcher`:

```
GET https://fapi.binance.com/fapi/v1/aggTrades
    ?symbol=SOLUSDT&startTime=1735732800000&endTime=1735736400000&limit=5
```

This is `2025-01-01T12:00:00Z` to `2025-01-01T13:00:00Z`, expanded
to a 1-hour window. The endpoint returned `[]` — zero records.

A second probe against a recent window (`now - 2h` for 5 minutes)
returned 5 records cleanly with realistic prices and timestamps.

### Finding

**Binance `/fapi/v1/aggTrades` REST endpoint is operationally
recent-history only.** The TTL is not documented in the public API
reference but is consistently observed: any window more than a few
weeks back returns empty arrays without erroring. This makes the
endpoint unsuitable for deep historical microstructure
reconstruction.

The fetcher infrastructure (`BinanceTradeFetcher`) is correct and
works as designed for recent windows. The estimator
(`estimate_roll`) is correct and tested. The harness
(`estimate_binance_roll_spread.py`) wires them together correctly.
The gap is venue data-availability, not implementation.

### What this changes for the calibration question

The Day 19b plan was to compare Roll-tape estimates from Mar 2024
(volatile, the regime A1 most wants to trade in) and Jan 2025
(quiet) against Day 19a's 1 bp/leg research calibration. The
volatile regime is exactly the calibration target where execution
costs matter most, because it's the regime that delivers the funding
A1 would harvest. Recent-only data does not address this question:
recent SOL liquidity may be quite different from March 2024 SOL
liquidity (different trader base, different volatility regime,
different market-making capital).

### Honest research stance

Three options were considered:

1. **Reframe to recent-window estimation.** Quick and produces
   numbers, but the numbers are not comparable to the actually-
   interesting volatile regime calibration. **Rejected.**
2. **Document the finding and stop.** The TTL discovery is itself
   a valuable research result. Day 19b's infrastructure is correct
   and reusable; the historical-data ingestion is identified as
   a separate sub-arc. **Adopted.**
3. **Implement Binance Vision archive ingestion now.** Significant
   new work (S3-style fetcher, gzip/zip decompression, monthly file
   parsing). Deferred to Day 19c.

This is the same discipline applied to Day 17c (BTCUSDT structurally
untradeable) and Day 18b (SOL slippage-bound under conservative
calibration): falsified hypotheses become tested findings, not
manufactured passes.

### Day 19c plan

Add `data/ingestion/vendors/binance/archive_trade_fetcher.py` that
ingests from `data.binance.vision` monthly trade archives:

- Fetch `https://data.binance.vision/data/futures/um/monthly/aggTrades/SOLUSDT/SOLUSDT-aggTrades-YYYY-MM.zip`
- Decompress without loading the full archive into memory (stream
  through `zipfile.ZipFile` + `csv.reader`)
- Normalize each row into the canonical `BinanceTrade` dataclass
- Optional local cache to avoid re-downloading the same month
- Validate row count and date range against archive metadata

Once Day 19c lands, this harness can be re-run with the predefined
`quiet` and `volatile` regimes producing meaningful estimates, and
the comparison-to-Day-19a question can finally be answered.

### Status of the Roll-tape estimate

**Not produced.** Day 19b sub-arc closed at "infrastructure complete,
historical-data gap identified." Day 19c will produce the actual
estimate.

The reviewer-locked discipline holds: no fake numbers committed; the
research profile (`binance_vip5_alt_research_v1`) remains research-
only with Kaiko + Amberdata as its single evidence basis until either
Day 19c (Roll on archive data) or Day 20+ (live A1 fills) provides
a second independent calibration.
