# Replay slippage methodology (Day 20.3)

This memo documents the methodology and operational rules of the
replay-observation infrastructure that produces `observed_slippage_bps`
values in `paper.fills` from historical trade data.

## Position in the evidence ladder

Day 20.3 establishes the third rung of the slippage-evidence ladder for
A1:

| Rung | Method | Source | Day | Status |
| --- | --- | --- | --- | --- |
| 1 | Profile placeholder | Reviewer judgment | 18a | Governance (active) |
| 2 | Research calibration | Kaiko + Amberdata third-party | 19a | Research-only (firewalled) |
| 3 | Roll's effective spread on tape | Direct aggTrades | 19c | Research artifact |
| 4 | Replay-observed slippage | Historical trades around fill timestamp | **20.3** | Research-grade (this) |
| 5 | Live A1 paper-fill recording | Live venue or testnet | Future | Promotion-grade target |

The Day 20.3 replay observation is the strongest research-grade
evidence we can produce without venue interaction. It is NOT
promotion-grade because (a) it does not capture A1-clip-size impact,
(b) it does not capture cancellation behavior or partial fills, (c)
it does not capture latency between signal and fill.

## Effective spread vs observed replay slippage

These are related but distinct quantities. They should not be
confused in reporting.

**Effective spread (Day 19b/c Roll estimator).** Estimates the
market-wide bid-ask spread experienced by all participants over a
window, derived from the autocovariance of trade-price changes (Roll
1984). Output: a single spread number for the window. Captures the
average frictional cost of crossing the book in either direction.

**Observed replay slippage (Day 20.3).** Measures the cost A1 would
have paid had it crossed at a specific moment, against a specific
reference price, in a specific direction. Output: a per-fill slippage
number. Captures the worst-case fill within a small window around the
intended fill timestamp.

Both are bps. Both use the same tape (aggTrades). Both are research-only.
But they answer different questions:

| Quantity | Question answered |
| --- | --- |
| Effective spread | "What is the market's spread over this window?" |
| Observed replay slippage | "What is the worst price A1 could have hit if it crossed right now?" |

The replay slippage is by construction at least as large as the
effective half-spread, often larger if the window contains a directional
move. The two should be reported separately.

## Definitions

### Reference price

The `decision_reference_price` is the price at signal-evaluation time —
the moment the strategy decided to fire an order. In live trading this
is typically the mark price or top-of-book at the strategy's tick. In
Day 20.3 replay it is supplied by the caller (Day 20.4 A1 wiring will
fill this in).

The reference is **NOT** the intended fill price. It is the price the
strategy thought was available when it decided to act. Slippage is
measured against this reference, capturing the cost of acting on stale
information plus the cost of crossing.

### Window

±5 seconds around `intended_fill_at`. Hardcoded for Day 20.3; reviewer
explicitly prohibited optimization at this stage.

Rationale for ±5s: long enough to capture realistic execution latency
(network round-trip plus venue processing), short enough that the
midpoint hasn't materially drifted from the decision reference.
Real-world execution often resolves in 100-500 ms; ±5s is a generous
upper bound that still produces tight windows.

Future research extensions might calibrate this window per regime
(quiet vs volatile) or per instrument. Not done in Day 20.3.

### Side handling

| Side | Extreme | Convention |
| --- | --- | --- |
| buy | `max(trade_price)` in window | Adverse: paid the highest price observed |
| sell | `min(trade_price)` in window | Adverse: received the lowest price observed |

This is the **conservative extreme-price convention**. It assumes A1
hit the worst price available in the window. Equivalent A1 actual fills
would typically be better than this; the metric is therefore an upper
bound on adverse slippage.

Alternative conventions worth noting (not implemented):

- **Midpoint at fill timestamp.** Use the volume-weighted midprice at
  exactly `intended_fill_at`. Closer to "expected" fill but ignores
  intra-window variance.
- **VWAP over window.** Volume-weighted average; smooths out single
  outlier prints.
- **Random uniform.** Sample a random trade from the window; produces
  a distribution rather than a point estimate.

The conservative convention is preferred for Day 20.3 because it makes
research-grade evidence harder to misinterpret as overly optimistic.
If the conservative number lands within Day 19a's 0.5-1.5 bps band,
the band is more credible. If it exceeds 1.5 bps, that is meaningful
falsification of the band.

### Trade inclusion rules

All trades returned by the fetcher within `[intended_fill_at - 5s,
intended_fill_at + 5s]` are included. The fetcher is responsible for
windowing; this module does not filter further.

No filtering by trade size (`quantity`). No filtering by
`is_buyer_maker`. The reasoning: Roll's estimator does not use side
information (its limitation); replay slippage's conservative extreme is
already side-aware via the buy/sell distinction. No further filtering
is needed for Day 20.3's research-grade purpose.

### Undefined handling

Three outcomes per intent, all of which produce a `paper.fills` row:

| Status | observed_slippage_bps | Metadata |
| --- | --- | --- |
| `success` | computed slippage | `replay_status=success`, `trade_count>0`, `extreme_price` |
| `empty_window` | NULL | `replay_status=empty_window`, `trade_count=0`, no extreme_price |
| `fetch_error` | NULL | `replay_status=fetch_error`, `error_type`, `error_message`, `trade_count=0` |

Every intent writes one row. No silent skips. Empty windows and fetch
errors are explicit, auditable, and distinguishable in metadata.

The Day 20.2 aggregator excludes NULL `observed_slippage_bps` rows
from its statistics but counts them as `n_excluded_null`. Reporting
should always surface both `n` and `n_excluded_null` together so the
denominator is visible.

## Promotion firewall

All replay-observation output is bound by the Day 20.1 schema:

- `source_mode = 'PAPER_RESEARCH'` (DB CHECK enforces no other value)
- `promotion_eligible = false` (DB CHECK forbids `true` for PAPER_RESEARCH)
- `paper.fills` is append-only (DB triggers)
- Writes go to `paper.fills`, never `trading.fills`

Replay-observed slippage **remains research-grade evidence only**. It
is not promotion-grade execution evidence. Promotion still requires
live A1 paper fills with adverse-fill cost recorded per fill (Day 20.5+
or equivalent).

## Day 20.4 next

Day 20.4 wires A1 to produce `PaperReplayIntent` records and call
`replay_intents()`. The reviewer scope explicitly defers A1 runner
changes; Day 20.3 is strategy-agnostic infrastructure.

## Sources

- Roll, R. (1984). "A Simple Implicit Measure of the Effective Bid-Ask
  Spread in an Efficient Market." Journal of Finance, 39(4), 1127-1139.
- Day 19a memo (docs/research/sol_slippage_calibration_memo.md)
- Day 19c.3 memo (docs/research/sol_roll_spread_estimation_memo.md)
- Day 20.1 commit (`9193b65`): paper.fills writer
- Day 20.2 commit (`b2b17bc`): slippage calibration aggregator
