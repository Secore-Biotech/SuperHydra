"""Pure replay-observation function.

Day 20.3a deliverable: compute observed slippage from a windowed set of
trades, a side, and a reference price. No fetchers, no clocks, no DB —
just arithmetic. The orchestrator (replay_runner.py) wraps this in
fetch + write logic; this module is testable in isolation.

Conservative extreme-price convention (reviewer-locked):
  - buy:  extreme = max(trade prices); slippage = (extreme - ref) / ref * 10000
  - sell: extreme = min(trade prices); slippage = (ref - extreme) / ref * 10000

Positive slippage = adverse fill (paid worse than reference).
Negative slippage = price improvement (filled better than reference).

The "conservative" framing means: assume the worst price in the window
filled, not the best. This produces an upper bound on adverse slippage,
suitable for research-grade calibration. A future Day could compare
against alternative conventions (median in window, VWAP, etc.) as
sensitivity analysis.

Empty windows produce ReplayObservation with status='empty_window' and
all numeric fields None. The orchestrator records this as a fill row
with NULL observed_slippage_bps so Day 20.2 aggregator can correctly
count it in n_excluded_null.

This module imports only stdlib + BinanceTrade. No side effects.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal, Sequence

from data.ingestion.vendors.binance.trade import BinanceTrade


VALID_SIDES: Final[frozenset[str]] = frozenset({"buy", "sell"})


@dataclass(frozen=True)
class ReplayObservation:
    """Result of compute_observed_slippage over one window.

    status='success':
        observed_slippage_bps and extreme_price both set
        trade_count > 0
    status='empty_window':
        observed_slippage_bps and extreme_price both None
        trade_count == 0

    Invariants enforced at __post_init__.
    """

    observed_slippage_bps: Decimal | None
    extreme_price: Decimal | None
    trade_count: int
    status: Literal["success", "empty_window"]

    def __post_init__(self) -> None:
        if self.status == "success":
            if self.observed_slippage_bps is None or self.extreme_price is None:
                raise ValueError(
                    "status=success requires non-None slippage and extreme_price"
                )
            if self.trade_count <= 0:
                raise ValueError(
                    f"status=success requires trade_count > 0, got {self.trade_count}"
                )
        elif self.status == "empty_window":
            if (self.observed_slippage_bps is not None
                    or self.extreme_price is not None):
                raise ValueError(
                    "status=empty_window requires None slippage and extreme_price"
                )
            if self.trade_count != 0:
                raise ValueError(
                    f"status=empty_window requires trade_count == 0, "
                    f"got {self.trade_count}"
                )
        else:
            raise ValueError(f"unknown status: {self.status!r}")


def compute_observed_slippage(
    *,
    trades: Sequence[BinanceTrade],
    side: str,
    reference_price: Decimal,
) -> ReplayObservation:
    """Compute observed replay slippage from a windowed set of trades.

    The caller is responsible for windowing the trades (i.e. filtering
    by time). This function does not filter; it processes whatever is
    passed in.

    Args:
        trades: pre-windowed trades. Empty sequence is allowed (returns
            status='empty_window').
        side: 'buy' or 'sell'. Determines which extreme is used.
        reference_price: the price slippage is measured relative to.
            Typically the decision-time price (signal-evaluation moment,
            not fill moment).

    Returns:
        ReplayObservation. Fields set per the status invariants.

    Raises:
        ValueError: invalid side or non-positive reference_price.
    """
    if side not in VALID_SIDES:
        raise ValueError(
            f"side must be 'buy' or 'sell', got {side!r}"
        )
    if not isinstance(reference_price, Decimal):
        raise TypeError(
            f"reference_price must be Decimal, got {type(reference_price).__name__}"
        )
    if reference_price <= 0:
        raise ValueError(
            f"reference_price must be positive, got {reference_price}"
        )

    if not trades:
        return ReplayObservation(
            observed_slippage_bps=None,
            extreme_price=None,
            trade_count=0,
            status="empty_window",
        )

    prices = [t.price for t in trades]
    if side == "buy":
        extreme = max(prices)
        slippage_bps = (
            (extreme - reference_price) / reference_price * Decimal("10000")
        )
    else:  # sell (already validated above)
        extreme = min(prices)
        slippage_bps = (
            (reference_price - extreme) / reference_price * Decimal("10000")
        )

    return ReplayObservation(
        observed_slippage_bps=slippage_bps,
        extreme_price=extreme,
        trade_count=len(trades),
        status="success",
    )
