# Cross-venue feasibility scoping

Date: 2026-05-23
Scope: identify which venue/data path can support the next real basis
simulation, given that same-venue Binance basis (the prior arc's finding)
is too efficiently arbed at 1h+ resolution to generate meaningful
convergence P&L.

NOT building fetchers tonight. NOT designing simulators. NOT a candidate
memo. Output is a feasibility table plus one venue-pair recommendation.

## Method

Direct unauthenticated REST probes from `curl` against each venue's
public API. Probed for: recent trades (does the endpoint return data
at all?), 1h klines (the right cadence for funding-event alignment),
3-year-back historical depth, and funding rate history where applicable.

## Probe results

### Deribit
- **Endpoint:** `https://www.deribit.com/api/v2/public/*`
- **Auth:** None required.
- **Instruments:** BTC-PERPETUAL (USD-margined, inverse), BTC-{date}
  expiring futures, BTC options.
- **Historical depth:** Confirmed 2023-05-24 1h candles returned.
- **Intervals available:** 1m, 60m (1h), and other resolutions via
  the TradingView chart data endpoint.
- **Funding rate access:** Not probed tonight; Deribit has a separate
  funding rate endpoint per perp.
- **Quote unit:** USD (not USDC, not USDT).
- **Notes:** Returns OHLC+volume as separate parallel arrays, not row-
  of-fields. Different ingestion shape from Binance archive CSVs.

### OKX
- **Endpoint:** `https://www.okx.com/api/v5/*`
- **Auth:** None required for market data.
- **Instruments:** BTC-USDT-SWAP (USDT-margined perpetual, MATCHES
  Binance BTCUSDT denomination), BTC-USDT (spot), various dated
  futures.
- **Historical depth:** Confirmed 2023-05-24 1h candles returned via
  `history-candles` endpoint (NOT regular `candles` which caps at
  recent data).
- **Intervals available:** 1m, 5m, 15m, 30m, 1H, others.
- **Funding rate access:** `public/funding-rate-history` returns 8h
  funding events. SAME cadence as Binance.
- **Quote unit:** USDT.
- **Notes:** Same row format as Binance (timestamp ms, OHLCV, etc.).
  Easiest "drop-in" alongside existing Binance ingestion.

### Coinbase
- **Endpoints:**
  - Legacy spot: `https://api.exchange.coinbase.com/products/*`
  - International (perps): `https://api.international.coinbase.com/api/v1/*`
- **Auth:** None required for market data on either.
- **Instruments:**
  - Legacy: BTC-USD spot only. NO perpetuals on this API.
  - International: BTC-PERP (USDC-margined). NEW platform, separate
    matching engine.
- **Historical depth:** Legacy spot confirmed 2023-05-24 1h candles
  returned. International perp historical depth NOT probed (newer
  product, may have shorter history).
- **Intervals available:** Legacy spot has fixed granularities (60s,
  300s, 900s, 3600s, 21600s, 86400s). 1h works.
- **Funding cadence (International perp):** 1 HOUR (not 8h like
  Binance/OKX). 8x more funding events per day.
- **Quote unit:** Spot is USD, perp is USDC.
- **Notes:** Coinbase Intl perp launched late 2023 — historical depth
  prior to that doesn't exist. USDC vs USD adds a non-trivial third
  factor (stablecoin discount) to any basis calculation involving
  Coinbase across both legs.

## Comparison table

| Venue           | Data available                   | Historical depth (3y back) | Key needed | Fetcher difficulty       | Suitability for basis sim                       |
|-----------------|----------------------------------|----------------------------|------------|--------------------------|-------------------------------------------------|
| Deribit         | BTC-PERPETUAL klines, funding    | YES                        | NO         | MEDIUM (different shape) | HIGH for USD-denominated cross-Binance basis     |
| OKX             | BTC-USDT-SWAP + BTC-USDT klines + funding | YES               | NO         | LOW (Binance-similar)    | HIGHEST — drop-in alongside existing Binance     |
| Coinbase legacy | BTC-USD spot klines              | YES                        | NO         | LOW                      | MEDIUM — spot leg only, no perp                  |
| Coinbase Intl   | BTC-PERP                         | partial (post-launch only) | NO         | MEDIUM                    | LOW for 3y backtest — depth limited              |

## Already-visible cross-venue basis (single sanity snapshot)

Probed within ~30 seconds at ~17:00 UTC on 2026-05-23:

| Source                          | Price       |
|---------------------------------|-------------|
| Deribit BTC-PERPETUAL (USD)     | $74,632.00  |
| Coinbase BTC-USD spot           | $74,640.84  |
| OKX BTC-USDT-SWAP perp          | $74,687.90  |
| Coinbase Intl BTC-PERP (USDC)   | $74,675.50  |
| OKX BTC-USDT spot               | $74,734.50  |

**Cross-venue range:** $74,632 to $74,735 = **$103 = ~14 bps**.

That's **7x wider** than the same-Binance basis range (±2 bps at 1h
boundaries from the prior arc). Cross-venue basis is real and likely
testable. The challenge is variable across legs: USDT-USDT pairs are
direct basis; USD-USDT pairs include a stablecoin discount; USDC-USDT
pairs include a different stablecoin discount.

3-year-back snapshot (2023-05-24, ~23:00 UTC):
- OKX BTC-USDT-SWAP: $26,729.9
- Coinbase BTC-USD: $26,291.76
- Δ: $438 = **~166 bps** USDT-vs-USD divergence at that point in
  time.

This is consistent with the broader USDT discount regime that
prevailed for periods in 2023. It is NOT basis in the traditional
sense — it's stablecoin peg divergence. A simulator using
OKX-USDT vs Coinbase-USD as its two legs would be measuring both.

## Recommendation: easiest first cross-venue simulation

**Binance BTCUSDT spot + OKX BTC-USDT-SWAP perp.**

Reasoning:

1. **Same denomination (USDT on both sides).** No stablecoin discount
   to model. Cleanest possible cross-venue basis test.
2. **OKX fetcher is the closest infrastructure analog to the existing
   Binance fetchers.** Same kline row shape (timestamp ms, OHLCV).
   Same funding event cadence (8h). Public REST, no key.
3. **3-year historical depth confirmed** via OKX `history-candles`
   endpoint.
4. **OKX BTC-USDT-SWAP is heavily traded** — likely $1B+ daily volume,
   which means basis variation reflects real positioning, not thin-book
   noise.
5. **Both legs would carry funding** — Binance BTCUSDT perp + OKX BTC-
   USDT-SWAP perp could also be simulated as a double-perp pair (long
   one perp, short other perp, capture differential funding). That's
   a different strategy class but the same data substrate.

## What NOT to do based on this scoping

- Don't pick Coinbase legacy spot as the second leg first. The USD-USDT
  crossing is interesting but it's a different problem class — a
  stablecoin-peg-trade rather than a basis-trade. Conflates two
  hypotheses.
- Don't pick Deribit BTC-PERPETUAL first. It's USD-margined and
  inverse — adds margin mechanics and quote-unit conversion on top of
  the basis question. Worthwhile eventually but harder to scope.
- Don't pick Coinbase Intl perp first. Insufficient historical depth
  for a 3-year backtest.

## Engineering cost estimate (NOT a commitment to build)

If/when the decision is made to extend to OKX:

- New fetcher class: `OkxKlinesArchiveFetcher` (or REST equivalent —
  OKX may or may not provide a Binance-Vision-style archive; tonight's
  probe used the REST endpoint, didn't verify archive). ~300 lines
  mirroring the Binance shape, plus tests.
- New funding-rate fetcher for OKX. ~150 lines.
- Symbol-mapping layer to align Binance "BTCUSDT" with OKX
  "BTC-USDT-SWAP" semantically.
- Cross-venue basis calculator and simulator. Architecturally similar
  to sim_hedged_carry_v2 but with two venue-routing layers instead
  of one.

Rough scope: 1-2 sessions of focused engineering. Smaller than the
candidate-#5 governance arc; bigger than the spot-fetcher work.

## Boundary preserved

This memo is feasibility data, not a build commitment. Decision on
whether/when to actually extend the system to OKX is a separate question
that requires:

- Confirming the underlying hypothesis (cross-venue basis generates
  decision-grade Sharpe net of costs) is the right thing to test next
- Comparing the engineering opportunity cost against other paths
  (live paper trading on existing Binance work, fresh strategy
  exploration, etc.)
- Deciding whether the test is worth ~1-2 sessions of focused work
  given everything else open

That decision happens next session or later, not tonight.

## End of H1 scope.

## Correction — OKX funding-rate history retention

A follow-up pagination test against OKX funding-rate-history showed that
historical funding retention is approximately three months, not multi-year.

Empirical result:
- Pagination backward reached oldest available funding around 2026-02-19
- Requesting earlier history returned zero records
- This confirms the endpoint retention floor is real, not a pagination bug

Implication:
- OKX klines have sufficient historical depth for cross-venue price/basis work
- OKX funding history does NOT support a 3-year funding-aware cross-venue carry backtest
- Any OKX funding-based historical test is limited to roughly the most recent 3 months
- Cross-venue basis simulation remains possible using price data, but funding-aware carry
  simulation over the full OOS window is not supported by public OKX funding history

Status:
- Do not build OKX funding fetcher yet as a backtest dependency
- OKX funding fetcher may still be useful later for live monitoring or short-window paper trading
- Cross-venue direction remains plausible but must be rescoped around available data
