"""Cross-sectional momentum signal computation.

Per pre-registration Section 2 (locked):
  - 14-day lookback
  - Weekly rebalance on Monday 00:00 UTC
  - Long top decile / short bottom decile

Per D9 (variable deciles): decile_size = ceil(0.10 * eligible_count),
minimum 1. This is the most faithful percentile interpretation of "top
decile / bottom decile" when the eligible universe size varies over time
(2025 listings entering, etc.).

Per D11: if eligible < 4, skip rebalance and emit skip_reason in the audit
log. Skipped rebalances produce no portfolio; the backtest holds cash (or
the previous portfolio, depending on engine policy — see backtest.py).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .prices import PriceMap
from .universe import UniverseAsset, eligible_at


# Pre-registration-locked defaults; engine accepts as parameters for testing
LOOKBACK_DAYS = 14
DECILE_FRACTION = Decimal("0.10")
MIN_ELIGIBLE_FOR_REBALANCE = 4  # D11


@dataclass(frozen=True)
class SignalOutput:
    """Result of one rebalance's signal computation."""
    rebalance_at: date
    eligible: list[str]                # symbols with complete data
    eligible_count: int
    returns: dict[str, Decimal]        # symbol -> trailing return
    long_bucket: list[str]             # top-decile symbols (best returns)
    short_bucket: list[str]            # bottom-decile symbols (worst returns)
    long_decile_size: int
    short_decile_size: int
    skipped: bool
    skip_reason: str | None
    excluded_symbols: list[dict]       # [{symbol, reason}, ...]


def compute_signal(
    *,
    rebalance_at: date,
    universe: list[UniverseAsset],
    prices: PriceMap,
    lookback_days: int = LOOKBACK_DAYS,
    decile_fraction: Decimal = DECILE_FRACTION,
    min_eligible: int = MIN_ELIGIBLE_FOR_REBALANCE,
) -> SignalOutput:
    """Compute the signal at one rebalance date.

    Pipeline:
      1. Listing-age eligibility per D10 (lookback_days delay)
      2. Data eligibility: require trailing return present (close at
         rebalance_at and at rebalance_at - lookback_days)
      3. If eligible_count < min_eligible: skip rebalance (D11)
      4. Rank by trailing return descending
      5. Top decile = ceil(decile_fraction * N), min 1 (D9)
      6. Bottom decile = ceil(decile_fraction * N), min 1 (D9)

    All exclusions logged in excluded_symbols for audit.
    """
    excluded: list[dict] = []

    # Step 1: listing-age eligibility
    age_eligible = eligible_at(
        universe, rebalance_at, listing_delay_days=lookback_days,
    )
    age_eligible_symbols = {a.symbol for a in age_eligible}
    for asset in universe:
        if asset.symbol not in age_eligible_symbols:
            excluded.append({
                "symbol": asset.symbol,
                "reason": "listing_age_insufficient",
            })

    # Step 2: data eligibility
    returns: dict[str, Decimal] = {}
    for asset in age_eligible:
        series = prices.get(asset.symbol)
        if series is None:
            excluded.append({
                "symbol": asset.symbol,
                "reason": "no_price_series",
            })
            continue
        r = series.trailing_return(
            as_of=rebalance_at, lookback_days=lookback_days,
        )
        if r is None:
            excluded.append({
                "symbol": asset.symbol,
                "reason": "missing_close_data",
            })
            continue
        returns[asset.symbol] = r

    eligible_symbols = sorted(returns.keys())

    # Step 3: minimum-eligible check (D11)
    if len(returns) < min_eligible:
        return SignalOutput(
            rebalance_at=rebalance_at,
            eligible=eligible_symbols,
            eligible_count=len(returns),
            returns=returns,
            long_bucket=[],
            short_bucket=[],
            long_decile_size=0,
            short_decile_size=0,
            skipped=True,
            skip_reason=(
                f"eligible_count={len(returns)} < min={min_eligible}"
            ),
            excluded_symbols=excluded,
        )

    # Step 4-6: rank and decile-construct (D9)
    ranked = sorted(returns.items(), key=lambda kv: kv[1], reverse=True)
    n = len(ranked)
    decile_size = max(1, math.ceil(float(decile_fraction) * n))
    long_bucket = [symbol for symbol, _ in ranked[:decile_size]]
    short_bucket = [symbol for symbol, _ in ranked[-decile_size:]]

    return SignalOutput(
        rebalance_at=rebalance_at,
        eligible=eligible_symbols,
        eligible_count=n,
        returns=returns,
        long_bucket=long_bucket,
        short_bucket=short_bucket,
        long_decile_size=decile_size,
        short_decile_size=decile_size,
        skipped=False,
        skip_reason=None,
        excluded_symbols=excluded,
    )
