"""Forward-return attribution: per-event net P&L in basis points.

Pure. Price-in, bps-out. No data fetching — the runner supplies entry and
exit prices from the kline series and realised funding from the funding
series; this module only does the arithmetic.

Net P&L decomposition (all bps):
    gross_bps           directional price return in the position's favour
    funding_pnl_bps     signed funding over the hold (+ received, - paid)
    execution_cost_bps  round-trip fees + slippage (always positive)
    net_bps = gross_bps + funding_pnl_bps - execution_cost_bps

Components are carried separately so the economic gate (spec §6) can
compute the cost-coverage ratio without re-deriving them.

Direction handling: only LONG and SHORT are attributable. A FLAT decision
never produces a trade (the sizer returns None), so attribution never
sees FLAT; passing it raises.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Final

from strategies.vol_event_persistence.attribution.cost_model import (
    COST_MODEL_SCHEMA_VERSION,
    execution_cost_bps,
    funding_pnl_bps,
)
from strategies.vol_event_persistence.signal.evaluate import EventDirection

FORWARD_RETURN_SCHEMA_VERSION: Final[str] = "forward_return.v0"

_DECIMAL_PRECISION: Final[int] = 28
_BPS: Final[Decimal] = Decimal("10000")


class ForwardReturnError(Exception):
    """Raised when attribution inputs are structurally invalid."""


@dataclass(frozen=True)
class ForwardReturn:
    """Per-event net P&L at one horizon.

    Carries every component of the decomposition so the economic gate can
    compute coverage ratios and win rates without re-deriving anything.

    Fields:
        venue, instrument: identity.
        event_id: the event natural key (links to the triggering event).
        direction: LONG or SHORT.
        horizon_days: holding horizon (spec locks the set to {1, 3, 7};
            this module accepts any positive horizon and records it, the
            runner enforces which horizons are run).
        entry_price, exit_price: the prices used (Decimal, positive).
        realised_funding_bps: summed funding over the hold, in bps.
        gross_bps: directional price return in the position's favour.
        funding_pnl_bps: signed funding contribution.
        execution_cost_bps: round-trip fees + slippage.
        net_bps: gross + funding_pnl - execution_cost.
        cost_model_schema_version: lineage tag from the cost model.
        schema_version: this attribution's schema tag.
    """

    venue: str
    instrument: str
    event_id: str
    direction: EventDirection
    horizon_days: int
    entry_price: Decimal
    exit_price: Decimal
    realised_funding_bps: Decimal
    gross_bps: Decimal
    funding_pnl_bps: Decimal
    execution_cost_bps: Decimal
    net_bps: Decimal
    cost_model_schema_version: str
    schema_version: str


def gross_return_bps(
    entry_price: Decimal,
    exit_price: Decimal,
    direction: EventDirection,
) -> Decimal:
    """Directional price return in the position's favour, in bps.

        LONG:  (exit - entry) / entry * 10000
        SHORT: (entry - exit) / entry * 10000

    Positive means the price moved in the position's favour.

    Raises:
        ForwardReturnError if direction is FLAT, or either price is
        non-positive.
    """
    if direction is EventDirection.FLAT:
        raise ForwardReturnError(
            "gross_return_bps requires LONG or SHORT; FLAT never trades"
        )
    if not isinstance(entry_price, Decimal) or not isinstance(exit_price, Decimal):
        raise ForwardReturnError("entry_price and exit_price must be Decimal")
    if entry_price <= 0 or exit_price <= 0:
        raise ForwardReturnError(
            f"prices must be positive, got entry={entry_price} exit={exit_price}"
        )

    with localcontext() as ctx:
        ctx.prec = _DECIMAL_PRECISION
        if direction is EventDirection.LONG:
            move = (exit_price - entry_price) / entry_price
        else:  # SHORT
            move = (entry_price - exit_price) / entry_price
        return move * _BPS


def compute_forward_return(
    *,
    venue: str,
    instrument: str,
    event_id: str,
    direction: EventDirection,
    horizon_days: int,
    entry_price: Decimal,
    exit_price: Decimal,
    realised_funding_bps: Decimal,
) -> ForwardReturn:
    """Compute the full per-event net P&L decomposition for one horizon.

    Pure. Decimal throughout.

    Raises:
        ForwardReturnError on invalid direction, non-positive prices, or
        non-positive horizon.
    """
    if direction is EventDirection.FLAT:
        raise ForwardReturnError(
            "compute_forward_return requires LONG or SHORT; FLAT never trades"
        )
    if horizon_days <= 0:
        raise ForwardReturnError(f"horizon_days must be positive, got {horizon_days}")
    if not isinstance(realised_funding_bps, Decimal):
        raise ForwardReturnError("realised_funding_bps must be Decimal")

    gross = gross_return_bps(entry_price, exit_price, direction)
    funding = funding_pnl_bps(direction, realised_funding_bps)
    exec_cost = execution_cost_bps()

    with localcontext() as ctx:
        ctx.prec = _DECIMAL_PRECISION
        net = gross + funding - exec_cost

    return ForwardReturn(
        venue=venue,
        instrument=instrument,
        event_id=event_id,
        direction=direction,
        horizon_days=horizon_days,
        entry_price=entry_price,
        exit_price=exit_price,
        realised_funding_bps=realised_funding_bps,
        gross_bps=gross,
        funding_pnl_bps=funding,
        execution_cost_bps=exec_cost,
        net_bps=net,
        cost_model_schema_version=COST_MODEL_SCHEMA_VERSION,
        schema_version=FORWARD_RETURN_SCHEMA_VERSION,
    )
