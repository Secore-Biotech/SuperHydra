"""Volatility-scaled momentum signal for Sleeve B candidate #4.

Per candidate #4 pre-registration (commit 59c1156) §2.6 (locked):

    score_i = trailing_30d_return_i / realized_45d_vol_i

Where:
    trailing_30d_return_i = simple return over the prior 30 trading days
        (close-to-close, identical to xs_momentum's lookback semantics
        with lookback_days=30).
    realized_45d_vol_i = annualized standard deviation of daily log returns
        over the prior 45 trading days. Formula:
            log_returns_t = log(close_t / close_{t-1})
            vol = sqrt(365) * stdev_sample(log_returns)
        Sample standard deviation (n-1 denominator).
        sqrt(365) annualization for 24/7 crypto markets.

Bucketing (per §2.6): top-third long, bottom-third short, equal weight
within bucket. Bucket size = max(1, ceil(N / 3)).

Data eligibility (per pre-registration §3.A1 and the corrected A2 at 39970f1):
asset is eligible at rebalance_at iff
  - listing_age_days >= 45 (the binding lookback per §2.6)
  - close exists at rebalance_at
  - close exists at rebalance_at - 30d (for momentum numerator)
  - all 45 daily closes in [rebalance_at - 45d, rebalance_at - 1d]
    exist consecutively (for log-return computation)

Minimum eligible: 4 (inherited from xs_momentum.signal.MIN_ELIGIBLE_FOR_REBALANCE
via the same D11 operational floor; not a pre-registration gate).

Returns SignalOutput dataclass distinct from xs_momentum.signal.SignalOutput
to preserve semantic clarity — vol-scaled momentum has scores (momentum/vol),
not raw returns.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, getcontext
from typing import Iterable

from strategies.sleeve_b.xs_momentum.prices import PriceMap, PriceSeries
from strategies.sleeve_b.xs_momentum.universe import UniverseAsset, eligible_at


# --- Pre-registration-locked defaults (per candidate #4 pre-reg §2.6) ---

MOMENTUM_LOOKBACK_DAYS = 30
VOL_LOOKBACK_DAYS = 45
ELIGIBILITY_DELAY_DAYS = max(MOMENTUM_LOOKBACK_DAYS, VOL_LOOKBACK_DAYS)  # 45
THIRD_FRACTION = Decimal("0.3333333333333333")
MIN_ELIGIBLE_FOR_REBALANCE = 4  # operational floor inherited from xs_momentum D11

# Annualization factor for 24/7 crypto markets.
# Stored as Decimal for precision-consistent multiplication.
# sqrt(365) ≈ 19.1049731745428... (use enough digits to outlast any Decimal context)
SQRT_365 = Decimal("19.1049731745428459315133892307403434")


# --- Output dataclass ---

@dataclass(frozen=True)
class SignalOutput:
    """Result of one rebalance's vol-scaled momentum signal computation.

    Distinct from xs_momentum.signal.SignalOutput. The `scores` field
    contains momentum/realized_vol per asset, not raw returns. The
    `momentum_components` and `vol_components` fields preserve the
    numerator and denominator separately for F1.3 (numerator-vs-
    denominator variance contribution) and F3 attribution analysis.
    """
    rebalance_at: date
    eligible: list[str]                          # symbols with complete data
    eligible_count: int
    scores: dict[str, Decimal]                   # symbol -> momentum / vol
    momentum_components: dict[str, Decimal]      # symbol -> trailing 30d simple return
    vol_components: dict[str, Decimal]           # symbol -> annualized 45d log-return vol
    long_bucket: list[str]                       # top-third by score
    short_bucket: list[str]                      # bottom-third by score
    long_bucket_size: int
    short_bucket_size: int
    skipped: bool
    skip_reason: str | None
    excluded_symbols: list[dict]                 # [{symbol, reason}, ...]


# --- Vol computation ---

def _decimal_ln(x: Decimal) -> Decimal:
    """Natural log of a positive Decimal, using current Decimal context.

    Decimal.ln() is exact-to-context. For our use case (ratios of two
    close prices on consecutive days) precision is dominated by the input
    precision, which is set by the PriceBar Decimal values (typically
    8 sig-figs from Binance kline data). Context precision must be high
    enough that the ln() result isn't truncated below input precision.
    """
    if x <= 0:
        raise ValueError(f"_decimal_ln requires positive input, got {x}")
    return x.ln()


def _decimal_sqrt(x: Decimal) -> Decimal:
    """Square root of a non-negative Decimal."""
    if x < 0:
        raise ValueError(f"_decimal_sqrt requires non-negative input, got {x}")
    return x.sqrt()


def realized_vol_from_log_returns(
    log_returns: Iterable[Decimal],
    annualization_factor: Decimal = SQRT_365,
) -> Decimal:
    """Annualized realized vol from a sequence of daily log returns.

    Formula:
        mean = sum(log_returns) / n
        variance = sum((r - mean)^2) / (n - 1)        # sample stdev
        stdev = sqrt(variance)
        annualized_vol = annualization_factor * stdev

    Requires n >= 2. Returns Decimal.
    """
    rs = list(log_returns)
    n = len(rs)
    if n < 2:
        raise ValueError(
            f"realized_vol_from_log_returns requires n >= 2, got n={n}"
        )
    n_dec = Decimal(n)
    mean = sum(rs, Decimal(0)) / n_dec
    sq_dev_sum = sum((r - mean) * (r - mean) for r in rs)
    variance = sq_dev_sum / (n_dec - Decimal(1))
    stdev = _decimal_sqrt(variance)
    return annualization_factor * stdev


def collect_log_returns_window(
    series: PriceSeries,
    as_of: date,
    lookback_days: int,
) -> list[Decimal] | None:
    """Collect log returns for the window ending at as_of (inclusive on close).

    Computes lookback_days log returns by walking back lookback_days+1
    consecutive daily closes ending at as_of. Returns None if any close
    in the window is missing.

    Specifically:
      - closes needed: as_of, as_of - 1d, ..., as_of - lookback_days
      - that's lookback_days + 1 daily closes
      - log returns produced: lookback_days values
      - log_return_t = ln(close_t / close_{t-1})
    """
    closes: list[Decimal] = []
    for offset in range(lookback_days + 1):
        d = as_of - timedelta(days=lookback_days - offset)
        c = series.close_at(d)
        if c is None or c <= 0:
            return None
        closes.append(c)
    log_returns: list[Decimal] = []
    for i in range(1, len(closes)):
        ratio = closes[i] / closes[i - 1]
        if ratio <= 0:
            return None
        log_returns.append(_decimal_ln(ratio))
    return log_returns


# --- Main signal ---

def compute_signal(
    *,
    rebalance_at: date,
    universe: list[UniverseAsset],
    prices: PriceMap,
    momentum_lookback_days: int = MOMENTUM_LOOKBACK_DAYS,
    vol_lookback_days: int = VOL_LOOKBACK_DAYS,
    third_fraction: Decimal = THIRD_FRACTION,
    min_eligible: int = MIN_ELIGIBLE_FOR_REBALANCE,
) -> SignalOutput:
    """Compute the volatility-scaled momentum signal at one rebalance date.

    Pipeline:
      1. Listing-age eligibility: (rebalance_at - onboard_date).days >= 45
      2. Data eligibility: trailing momentum return AND full 45-day vol
         window both present. Asset excluded with explicit reason if any
         close is missing.
      3. Compute score = momentum / vol per eligible asset.
      4. If eligible_count < min_eligible: skip rebalance (D11).
      5. Rank by score descending.
      6. Bucket: top-third long, bottom-third short. Size = max(1, ceil(N/3)).

    All exclusions logged in excluded_symbols for audit. The momentum and
    vol components are preserved in the output for downstream F1.3 / F3.3
    decomposition analysis.

    The eligibility delay used here is max(momentum_lookback_days,
    vol_lookback_days) — the longer of the two. Per candidate #4 pre-reg,
    this is 45 days.
    """
    eligibility_delay = max(momentum_lookback_days, vol_lookback_days)
    excluded: list[dict] = []

    # Step 1: listing-age eligibility (using the binding 45-day delay)
    age_eligible = eligible_at(
        universe, rebalance_at, listing_delay_days=eligibility_delay,
    )
    age_eligible_symbols = {a.symbol for a in age_eligible}
    for asset in universe:
        if asset.symbol not in age_eligible_symbols:
            excluded.append({
                "symbol": asset.symbol,
                "reason": "listing_age_insufficient",
            })

    # Step 2: data eligibility — momentum return AND vol window
    scores: dict[str, Decimal] = {}
    momentum_components: dict[str, Decimal] = {}
    vol_components: dict[str, Decimal] = {}

    for asset in age_eligible:
        series = prices.get(asset.symbol)
        if series is None:
            excluded.append({
                "symbol": asset.symbol,
                "reason": "no_price_series",
            })
            continue

        # Momentum numerator: trailing 30d simple return.
        momentum = series.trailing_return(
            as_of=rebalance_at, lookback_days=momentum_lookback_days,
        )
        if momentum is None:
            excluded.append({
                "symbol": asset.symbol,
                "reason": "missing_momentum_close",
            })
            continue

        # Vol denominator: 45 daily log returns.
        log_returns = collect_log_returns_window(
            series, as_of=rebalance_at, lookback_days=vol_lookback_days,
        )
        if log_returns is None:
            excluded.append({
                "symbol": asset.symbol,
                "reason": "missing_vol_window_close",
            })
            continue

        try:
            vol = realized_vol_from_log_returns(log_returns)
        except ValueError as exc:
            excluded.append({
                "symbol": asset.symbol,
                "reason": f"vol_computation_error:{exc}",
            })
            continue

        if vol <= 0:
            # Theoretically possible only with constant prices across the
            # window; signal is undefined. Exclude with explicit reason.
            excluded.append({
                "symbol": asset.symbol,
                "reason": "zero_realized_vol",
            })
            continue

        momentum_components[asset.symbol] = momentum
        vol_components[asset.symbol] = vol
        scores[asset.symbol] = momentum / vol

    eligible_symbols = sorted(scores.keys())

    # Step 4: minimum-eligible check (D11)
    if len(scores) < min_eligible:
        return SignalOutput(
            rebalance_at=rebalance_at,
            eligible=eligible_symbols,
            eligible_count=len(scores),
            scores=scores,
            momentum_components=momentum_components,
            vol_components=vol_components,
            long_bucket=[],
            short_bucket=[],
            long_bucket_size=0,
            short_bucket_size=0,
            skipped=True,
            skip_reason=(
                f"eligible_count={len(scores)} < min={min_eligible}"
            ),
            excluded_symbols=excluded,
        )

    # Step 5-6: rank and bucket-construct
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    n = len(ranked)
    bucket_size = max(1, math.ceil(float(third_fraction) * n))
    long_bucket = [symbol for symbol, _ in ranked[:bucket_size]]
    short_bucket = [symbol for symbol, _ in ranked[-bucket_size:]]

    return SignalOutput(
        rebalance_at=rebalance_at,
        eligible=eligible_symbols,
        eligible_count=n,
        scores=scores,
        momentum_components=momentum_components,
        vol_components=vol_components,
        long_bucket=long_bucket,
        short_bucket=short_bucket,
        long_bucket_size=bucket_size,
        short_bucket_size=bucket_size,
        skipped=False,
        skip_reason=None,
        excluded_symbols=excluded,
    )
