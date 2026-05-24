# Next session: funding-capture execution-friction simulator

Status: SCOPE LOCKED, NOT YET IMPLEMENTED.
Locked at end of session 2026-05-24, to be written fresh next session.

## The single question

Does persistent positive BTC funding survive realistic executable friction?

This is the unresolved bottleneck. The phenomenon (persistent positive funding
drift, ~7.5% annualized in our cached data) is real. What's unknown is whether
a real strategy capturing it survives:

- Maker/taker fees
- Funding-event timing slippage
- Bid-ask spread on position entry/exit
- Position-flip costs when funding sign changes
- Rebalance cadence

Until we know that, the "funding-related execution/carry" direction the
reframe document recommended as a deployment lane is not actually validated
as a deployment candidate. It's a candidate to BE validated.

## Scope (LOCKED before next session)

One asset:    BTC
One venue:    Binance USDT-margined perp (BTCUSDT)
One position structure: delta-neutral positive-funding capture:
  - long spot BTC + short perp BTC when in positive-funding regime
  - flat otherwise
  - NEVER long perp + short spot in v1; spot-borrow cost makes this structurally different
One rebalance cadence: evaluate state at each funding event (every 8 hours)
One implementation: no leverage optimization, no portfolio logic, no overlays

Data dependencies:
- Binance BTCUSDT perp 1h klines — cached
- Binance BTCUSDT spot 1h klines — VERIFY cache before implementation; fetch if missing
- Binance BTCUSDT funding history — cached
- All three must align on timestamps

The prior "no new fetches" rule is relaxed only for missing Binance BTCUSDT spot 1h klines, because true delta-neutral funding capture requires the spot leg.

## What the simulator must include

Funding accrual:
- Position size × funding_rate per 8-hour interval, paid at the funding instant
- Sign convention: long pays positive funding, short receives positive funding
  (so if expected funding > 0, we SHORT to receive funding)

Fee model (REVISED):
- Round-trip = 4 fills: spot open, perp open, spot close, perp close
- Spot taker: 10 bps per side (verify before implementation)
- Spot maker: 1 bp per side
- Perp taker: 5 bps per side (verify before implementation)
- Perp maker: 2 bps per side
- Conservative default: all taker on all 4 fills = ~30 bps per round trip
- Sensitivity: all maker = ~6 bps per round trip
- Apply costs only on transitions: flat→in or in→flat

Spread model:
- Assume realized fill is at next-bar open (no foreknowledge)
- Optional bid-ask penalty: 0.5-1 bp of mid (small for BTC, but real)

Position-state logic:
- State is IN only during a positive-funding regime; otherwise FLAT
- No negative-funding capture in v1 because it would require long perp + short spot
- Entry friction is large (~30 bps taker round-trip), so per-event sign flipping is not acceptable
- Compare three rules:
  (1) always-in: enter at start, hold through full window
  (2) simple regime gate: IN when 7-day rolling funding mean > threshold, otherwise FLAT
  (3) naive 1-period sign rule: included as a diagnostic baseline, expected to overtrade
- Drop EWMA from v1

Sizing:
- Notional capital: $50,000 (matches V2.1 roadmap canary scale)
- Spot leg notional ≈ $50,000 and perp short notional ≈ $50,000 matched to within rounding
- Position is delta-neutral net exposure, not $50,000 total gross across both legs
- No hedge-ratio adjustment in v1; constant 1:1 notional hedge
- Margin requirements ignored in v1; this is feasibility, not live margin simulation

PnL accounting:
- Spot MTM PnL from price movement on long spot leg
- Perp MTM PnL from price movement on short perp leg
- Spot + perp MTM should net to approximately zero except for basis drift and sizing/rounding
- Plus funding received/paid on the perp leg at each funding instant
- Minus fees on every position transition
- Minus spread/slippage on every position transition
- Large MTM/basis PnL is a simulator bug signal unless explicitly explained

Output:
- Total return over OOS window
- Sharpe ratio (annualized, using hourly returns)
- Max drawdown
- gross_funding_income
- spot_mtm_pnl
- perp_mtm_pnl
- mtm_pnl / basis_pnl = spot_mtm_pnl + perp_mtm_pnl
- fee_drag
- total_net_pnl = gross_funding_income + mtm_pnl - fee_drag
- n_round_trips
- days_in_position vs days_flat
- Fee drag as fraction of gross funding income
- Comparison runs: taker vs maker, always-in vs 7-day regime gate vs naive sign rule

## Known failure modes to watch for

1. SIGN ERRORS on funding accrual. The convention is: positive funding rate
   means longs pay shorts. A funding rate of +0.0001 (1 bp per 8h) means the
   short perp leg gains 1 bp of perp notional. The long spot leg has no funding
   cashflow. Test this against a single hand-computed delta-neutral event.

2. TIMING ERRORS on funding-event marks. Funding payment occurs at the
   funding instant (00:00, 08:00, 16:00 UTC). The perp position MUST be held
   AT that instant to receive/pay. A perp position closed at 07:59 misses the
   08:00 funding. Test this against a single hand-computed event.

3. FEE DOUBLE-COUNT or MISS. Delta-neutral round-trip is 4 fills:
   spot open, perp open, spot close, perp close. A v1 transition is only
   flat→in or in→flat; no side flip is supported. Test the 4-fill round-trip
   explicitly.

4. LOOK-AHEAD BIAS. The forecast at time T must use only data available
   BEFORE T. Cached BTC funding has funding times that align to 00:00/08:00/16:00
   UTC. The decision to position for the 08:00 funding event must be made
   BEFORE 08:00 — using funding history through 00:00 at the latest.

5. THE PRIOR HEDGED-CARRY SHARPE 10.7 BUG. That simulator produced
   wildly inflated Sharpe because it had smooth deterministic cashflow.
   Test: are per-event PnL distributions reasonable (e.g., a single
   funding event shouldn't yield more than ~10 bps)? If individual events
   show implausibly low variance, suspect a smoothing artifact.

## Pre-locked decision criteria

Three thresholds, locked now:

After realistic taker-fee + spread/slippage on 4-fill round trips:
  Net annualized return < 2%        → direction killed; friction destroys the edge
  Net annualized return 2-5%        → marginal; characterize before deployment
  Net annualized return > 5%        → real edge survives; sensitivity analysis next

Sharpe ratio (annualized, hourly returns):
  Sharpe < 1.0                     → not interesting; basis noise too large
  Sharpe 1.0-2.0                   → borderline
  Sharpe > 2.0                     → meaningful standalone signal

These are AND criteria. Both return and Sharpe must meet the relevant tier.

Meta-rule (from prior sessions): if the result is syntactically met but
the cost model turns out to underestimate true frictions, the rule can be
overridden in writing, not silently.

## Test coverage required before trusting any output

The simulator MUST have unit tests covering:
- Funding accrual sign convention on a delta-neutral position
- Positive funding event: short perp receives, long spot receives no funding
- Delta-neutral MTM cancellation on synthetic equal spot/perp price paths
- Fee accounting on a 4-fill round-trip
- Transition cost accounting for flat→in and in→flat
- Forecast/state rule does not use future data (look-ahead test)
- Empty / minimal window handling

Run a smoke test on a small known window (e.g., 7 days where we can
hand-verify the funding events received) BEFORE running the full OOS window.

The cost of writing tests before the OOS run is much smaller than the
cost of building strategic conclusions on a buggy simulator.

## What this session is NOT

This document defines a feasibility experiment, not a roadmap deliverable.
Its output is a yes/no/maybe on whether A1-style delta-neutral funding
capture is worth the engineering investment to build through P0 → P1.
The experiment's thresholds are feasibility criteria, not promotion gates.
A1 itself still clears roadmap §2 and Appendix A on its own merits.

NOT a backtester for general use. Single-asset, single-venue, single-position-type.
NOT a paper trading system. No execution, no orders.
NOT a portfolio simulator. One signal, one position.
NOT a strategy escalation. Even if the verdict is "real edge survives,"
the next move is sensitivity analysis, not deployment.

## Repo state at scope-lock

Origin head: e387fea (Coinbase USDT-USD fetcher)
Branch: feature/migrations-0001-foundation

Cached data ready:
- BTC perp 1h (Binance): 27,024 klines, 2023-04-01 to 2026-05-01
- BTC funding (Binance): 3,340 records covering 2023-04 onward
