"""Cost model for vol_event_persistence attribution.

Pure functions over the spec §4 cost constants in config.pre_lock. Two
costs apply to each event trade, both in basis points (matching the spec
§6 economic gate):

  - execution cost: round-trip taker fees + slippage. Always a positive
    drag, paid on entry and exit.
  - funding P&L: realised funding over the holding window, SIGNED by
    position direction.

FUNDING SIGN CONVENTION (load-bearing — encoded in tests):
  On Binance perps, positive funding means longs pay shorts. So over a
  window with positive realised funding:
    - a LONG position PAYS it       -> negative P&L contribution
    - a SHORT position RECEIVES it  -> positive P&L contribution
  Formula: funding_pnl_bps = -direction_sign * realised_funding_bps,
  with LONG sign = +1, SHORT sign = -1.

Cost assumptions are floor-not-ceiling (spec §4): they may be raised if
realised friction is worse than modelled, never lowered to make a result
pass. The numbers live in config.pre_lock; this module consumes them.
Drift is caught by tests.unit.test_cost_model.test_cost_constants_match_spec.
"""
from __future__ import annotations

from decimal import Decimal, localcontext
from typing import Final

from strategies.vol_event_persistence.config.pre_lock import (
    SLIPPAGE_BPS_PER_SIDE,
    TAKER_FEE_BPS_PER_SIDE,
)
from strategies.vol_event_persistence.signal.evaluate import EventDirection

COST_MODEL_SCHEMA_VERSION: Final[str] = "attribution_cost_model.v0"

_DECIMAL_PRECISION: Final[int] = 28

# Position sign for funding. LONG = +1, SHORT = -1.
_DIRECTION_SIGN = {
    EventDirection.LONG: Decimal("1"),
    EventDirection.SHORT: Decimal("-1"),
}


def execution_cost_bps() -> Decimal:
    """Round-trip execution cost in bps: taker fee + slippage, each side.

        = 2 * TAKER_FEE_BPS_PER_SIDE + 2 * SLIPPAGE_BPS_PER_SIDE

    This equals ROUND_TRIP_COST_BPS_FLOOR by construction; the equality is
    asserted in tests as an internal consistency check.
    """
    return (
        Decimal("2") * TAKER_FEE_BPS_PER_SIDE
        + Decimal("2") * SLIPPAGE_BPS_PER_SIDE
    )


def funding_pnl_bps(
    direction: EventDirection,
    realised_funding_bps: Decimal,
) -> Decimal:
    """Signed funding P&L in bps for a held position.

    Args:
        direction: LONG or SHORT (FLAT has no position; raises).
        realised_funding_bps: sum of funding rates that settled over the
            holding window, expressed in bps. Positive = longs pay shorts.

    Returns:
        Signed funding contribution to P&L in bps.
          Positive => the position RECEIVED funding.
          Negative => the position PAID funding.
        Concretely:
          LONG  + positive funding -> negative (paid)
          SHORT + positive funding -> positive (received)
          LONG  + negative funding -> positive (received)
          SHORT + negative funding -> negative (paid)
    """
    sign = _DIRECTION_SIGN.get(direction)
    if sign is None:
        raise ValueError(
            f"funding_pnl_bps requires LONG or SHORT, got {direction!r}"
        )
    with localcontext() as ctx:
        ctx.prec = _DECIMAL_PRECISION
        return -sign * realised_funding_bps
