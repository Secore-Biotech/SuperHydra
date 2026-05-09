# SOL slippage calibration memo (Day 19a research-only)

This memo records the evidence basis for `binance_vip5_alt_research_v1`,
a research-calibrated cost-model profile that lowers SOL slippage from
the conservative 3 bps per leg in `binance_vip5_alt_v1` to 1 bp per
leg. The research profile is intentionally NOT promoted: it does not
participate in `select_profile_for_a1`, and it carries explicit notes
in its `profile_name` and `source` indicating it is research-only.

## Question

What realistic per-leg adverse fill cost should SOLUSDT use for A1
paper fills at the intended trade size (~$1500-$3000 USDT-equivalent
for a 0.01-BTC-class hedged exposure)?

## Day 18a starting assumption

`binance_vip5_alt_v1` uses `liquid_alt_tier = 3 bps per leg`. This was
a conservative initial guess; its threshold (~11.7 bps per interval)
sits above the realized rolling-12 mean in every SOL window we have
probed, including the strong-funding March 2024 regime (rolling-12
max ~7.69 bps).

## Evidence sources

### Kaiko Q1 2024 bid-ask spread cheatsheet

URL: https://research.kaiko.com/insights/a-cheatsheet-for-bid-ask-spreads

Key qualitative findings:

- The SOL-USDT pair has the widest interquartile range (IQR) and the
  most outliers of major pairs surveyed, including on Binance (the
  most liquid venue).
- DOGE has tighter USDT spreads than XRP, SOL, and ADA in this sample.
- Binance leads on BTC and ETH spreads, in tight ranges.
- Kucoin had the lowest non-BTC/ETH spreads among the venues surveyed.
- TUSD SOL spreads "range from 8 bps and above"; USDT counterparts are
  consistently better.

The Kaiko piece does not publish a single numeric spread for
SOLUSDT on Binance, but qualitatively places it as wider than BTC/ETH
yet tightest among venues for SOL.

### Amberdata Digital Asset Snapshot (Jan 2026)

URL: https://blog.amberdata.io/amberdata-digital-asset-snapshot-derivatives-flows-liquidity-insights

Concrete numbers from this snapshot:

- BTC average spread: 0.09 bps; tightest at 0.01 bps (Binance
  BTCUSD_PERP and BTCUSDT pairs).
- ETH average spread: 0.10 bps; tightest at 0.03 bps (OKX
  ETH-USDT-SWAP).
- **SOL average spread: 1.01 bps**, "roughly 10x wider than BTC/ETH
  but consistent with lower liquidity profile".
- **Binance SOLUSDT: tightest at 0.79 bps**; Bybit SOLPERP widest at
  1.78 bps.
- "Institutional-grade execution conditions persist across major
  venues with a negligible transaction cost impact for large orders."

### Academic literature

The market-microstructure literature on perpetual futures (Gornall,
Rinaldi, Xiao 2024; Cornell Business 2025; Ackerer, Hugonnier, Jermann
2023) confirms perp introduction widens spreads, documents U-shaped
funding-cycle liquidity patterns, and discusses adverse-selection
risk — but does not provide instrument-specific numeric fill-cost
estimates. The reviewer's caution is correct: published academic
research is supportive of the method but not sufficient as a single
numeric calibration source.

## Calibration choice

Using the Amberdata Jan 2026 snapshot as the primary numeric source:

- Observed Binance SOLUSDT effective spread: ~0.79 bps.
- Half-spread (passive maker fill cost reference): ~0.4 bps.
- For A1's clip size ($1.5k-$3k), Amberdata's "negligible transaction
  cost impact for large orders" is reassuring — A1 trades much smaller
  than the institutional sizes in that report.
- Conservative cushion for adverse-selection on aggressive fills:
  ~0.6 bps.
- **Per-leg slippage assumption: 1 bp.**

Sensitivity bounds:

- Lower bound: 0.5 bp per leg (matches BTC/ETH at A1 clip sizes
  where impact is negligible). Threshold becomes ~6.7 bps.
- Upper bound: 1.5 bps per leg (full one-spread adverse cost +
  modest impact). Threshold becomes ~8.7 bps.

The 1 bp choice splits the difference and matches BTC/ETH for symmetry,
which simplifies cross-instrument reasoning until empirical data
distinguishes them.

## Why this is research-only

1. **Spread is not the same as effective adverse fill cost.** Spread
   measures the static gap between best bid and best ask. Adverse
   fill cost includes impact (depth-dependent), adverse selection
   (informed-flow signaling), and timing slippage (mid-price drift
   between order placement and fill). Spread is a lower bound.

2. **Aggregated spread data may not capture A1's specific clip size.**
   Amberdata's "tightest" spreads are likely measured at the inside
   quote, not at A1's notional size. For SOL at $1.5k-$3k, impact
   should be small, but unverified.

3. **Spread varies by regime.** A profile derived from quiet-regime
   spread data may understate cost in volatile regimes precisely
   when A1 wants to trade. The March 2024 memecoin frenzy is a
   known volatile regime; spread data from quieter Q1 2024 / Jan
   2026 windows may not characterize it well.

4. **No live A1 fills yet.** The most authoritative number would
   come from A1's own paper-fill records on the venue at A1's actual
   clip size in A1's actual regimes. We do not have that.

For these reasons, the profile is named `_research_v1` and is
NOT returned by `select_profile_for_a1`. Using it requires explicit
import and call by name, which forces a deliberate decision about
research vs. governance context.

## What promotes this to empirical

The reviewer's path forward:

1. **Day 19b/20**: Tape-based effective-spread estimation across
   volatile and quiet regimes. Pull Binance SOLUSDT trade history
   over multiple sample periods, estimate effective spread and
   simple impact via Roll's autocovariance estimator or similar.
2. **Day 20+**: A1 paper fills on the venue at production-equivalent
   clip sizes, with adverse-fill cost recorded per fill.
3. **Promotion**: When tape and live-fill estimates both agree on a
   number within the sensitivity bounds (e.g. 0.5-1.5 bps), promote
   to `binance_vip5_alt_empirical_v1`. Update selector accordingly.

Until then: `binance_vip5_alt_v1` (3 bps conservative) remains the
governance profile. `binance_vip5_alt_research_v1` is available for
research backtests and sensitivity analysis.

## Out-of-scope here

- OKX and Bybit liquid-alt slippage tiers — separate calibration
  effort once Binance is empirically validated.
- Maker-rebate-only research profile — separate path, may complement
  the alt research profile.
- DOGEUSDT / AVAXUSDT calibration — Binance fees are identical at
  VIP5, but slippage tiers may differ; separate per-instrument
  calibration before adding selector branches.

## Sources

| Source | URL | As-of |
| --- | --- | --- |
| Kaiko bid-ask spread cheatsheet | https://research.kaiko.com/insights/a-cheatsheet-for-bid-ask-spreads | Q1 2024 |
| Amberdata Digital Asset Snapshot (derivatives, flows, liquidity) | https://blog.amberdata.io/amberdata-digital-asset-snapshot-derivatives-flows-liquidity-insights | Jan 2026 |
| Gornall, Rinaldi, Xiao - Funding Payments Crisis-Proofed Bitcoin's Perpetual Futures | https://papers.ssrn.com/sol3/Delivery.cfm/5036933.pdf | Nov 2024 |
| Cornell Business - Perpetual Futures Contracts and Cryptocurrency Market Quality | https://business.cornell.edu/article/2025/02/perpetual-futures-contracts-and-cryptocurrency/ | Feb 2025 |
| Ackerer, Hugonnier, Jermann - Perpetual Futures Pricing | https://finance.wharton.upenn.edu/~jermann/AHJ-main-10.pdf | 2023 |
