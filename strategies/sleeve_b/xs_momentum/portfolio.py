"""Portfolio construction: equal-weight, vol-target, turnover.

Per pre-registration Section 2 (locked):
  - Equal-weighted within each decile
  - Portfolio vol-targeted at 15% annualized
  - First 4 weeks use uniform 15% assumption (cold start)
  - After cold start: trailing 30-day realised portfolio vol (~4 weeks of
    weekly P&L) scales the vol-target

NO LEVERAGE CAP. The pre-registration does not specify a cap on the
vol-target scaler. When realized vol is very low, the scaler can produce
arbitrarily large leverage. This is documented behavior, not a bug.
Adding a cap would be a parameter change requiring new pre-registration.

The first-pass spec for "realized portfolio volatility" is intentionally
operationalized as stdev of weekly net P&L (in fraction-of-notional terms)
across the trailing 4 weeks. If a different window length is desired, that
is a separate pre-registered hypothesis.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .signal import SignalOutput


# Pre-registration-locked defaults
TARGET_ANNUAL_VOL = Decimal("0.15")
_SQRT_52 = Decimal(str(math.sqrt(52)))
TARGET_WEEKLY_VOL = TARGET_ANNUAL_VOL / _SQRT_52
COLD_START_WEEKS = 4
TRAILING_VOL_WEEKS = 4  # 30 days approximated as 4 weekly observations


@dataclass(frozen=True)
class Position:
    """One position. Weight is signed: positive=long, negative=short."""
    symbol: str
    weight: Decimal


@dataclass(frozen=True)
class Portfolio:
    """Constructed portfolio at one rebalance.

    Weights are post-vol-target-scaling. Sum of long weights and absolute
    sum of short weights are each equal to gross_notional_scale (the
    vol-target scaler). The portfolio is dollar-neutral by construction:
    long_notional() == short_notional() (modulo floating-point precision).
    """
    rebalance_at: date
    positions: list[Position]
    gross_notional_scale: Decimal
    target_weekly_vol: Decimal
    realized_vol_input: Decimal | None  # None during cold-start

    def long_notional(self) -> Decimal:
        return sum(
            (p.weight for p in self.positions if p.weight > 0),
            Decimal("0"),
        )

    def short_notional(self) -> Decimal:
        return sum(
            (-p.weight for p in self.positions if p.weight < 0),
            Decimal("0"),
        )

    def gross_notional(self) -> Decimal:
        return sum(
            (abs(p.weight) for p in self.positions),
            Decimal("0"),
        )


def build_portfolio(
    *,
    signal: SignalOutput,
    trailing_weekly_pnl_bps: list[Decimal],
    target_weekly_vol: Decimal = TARGET_WEEKLY_VOL,
    cold_start_weeks: int = COLD_START_WEEKS,
    trailing_vol_weeks: int = TRAILING_VOL_WEEKS,
) -> Portfolio | None:
    """Build portfolio from signal output.

    Returns None if signal.skipped or buckets are empty. Caller decides
    whether to close out previous positions or hold cash.

    Vol-target mechanics:
      - First cold_start_weeks of backtest: scale = 1.0 (uniform target)
      - After cold start: scale = target_weekly_vol / realized_weekly_vol
        where realized = stdev of trailing trailing_vol_weeks of net P&L
        (converted from bps to fraction)

    No leverage cap. If realized vol → 0, scaler → infinity. Documented.
    """
    if signal.skipped:
        return None
    if not signal.long_bucket or not signal.short_bucket:
        return None

    # Equal-weight within bucket; pre-scaling, gross notional = 2.0
    # (long_notional = 1.0, short_notional = 1.0).
    n_long = len(signal.long_bucket)
    n_short = len(signal.short_bucket)
    long_unit_weight = Decimal("1") / Decimal(n_long)
    short_unit_weight = -Decimal("1") / Decimal(n_short)

    # Vol-target scaler
    if len(trailing_weekly_pnl_bps) < cold_start_weeks:
        scale = Decimal("1")
        realized_vol_input = None
    elif len(trailing_weekly_pnl_bps) < trailing_vol_weeks:
        scale = Decimal("1")
        realized_vol_input = None
    else:
        trailing = trailing_weekly_pnl_bps[-trailing_vol_weeks:]
        as_floats = [float(b) / 10000 for b in trailing]
        if len(as_floats) < 2:
            scale = Decimal("1")
            realized_vol_input = None
        else:
            realized_weekly_vol = Decimal(str(statistics.stdev(as_floats)))
            realized_vol_input = realized_weekly_vol
            if realized_weekly_vol > 0:
                scale = target_weekly_vol / realized_weekly_vol
            else:
                # Edge case: zero realized vol → no scaling defined; keep 1.0
                scale = Decimal("1")

    positions = [
        Position(symbol=s, weight=long_unit_weight * scale)
        for s in signal.long_bucket
    ] + [
        Position(symbol=s, weight=short_unit_weight * scale)
        for s in signal.short_bucket
    ]

    return Portfolio(
        rebalance_at=signal.rebalance_at,
        positions=positions,
        gross_notional_scale=scale,
        target_weekly_vol=target_weekly_vol,
        realized_vol_input=realized_vol_input,
    )


def compute_turnover(
    *,
    previous: Portfolio | None,
    current: Portfolio | None,
) -> Decimal:
    """Compute turnover: sum of absolute weight changes.

    Conventions:
      - Cold start (previous=None): turnover = current.gross_notional()
      - Skipped rebalance (current=None): turnover = previous.gross_notional()
        (closing out the previous positions)
      - Both None: turnover = 0

    The fee model multiplies turnover by fees_bps; one round-trip on a
    fully-replaced portfolio costs gross_notional × fees_bps.
    """
    if previous is None and current is None:
        return Decimal("0")
    if previous is None:
        return current.gross_notional() if current else Decimal("0")
    if current is None:
        return previous.gross_notional()

    prev_weights = {p.symbol: p.weight for p in previous.positions}
    curr_weights = {p.symbol: p.weight for p in current.positions}
    all_symbols = set(prev_weights.keys()) | set(curr_weights.keys())
    total_change = Decimal("0")
    for s in all_symbols:
        prev_w = prev_weights.get(s, Decimal("0"))
        curr_w = curr_weights.get(s, Decimal("0"))
        total_change += abs(curr_w - prev_w)
    return total_change
