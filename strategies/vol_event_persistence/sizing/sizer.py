"""Sizer for vol_event_persistence.

Two pure functions:

  - size_intent: EventDecision -> PerpOrderIntent | None. Produces the
    ENTRY order for an event. Returns None when there is no trade (FLAT
    direction, which covers both non-events and zero-directional-signal
    events).

  - make_close_intent: PerpOrderIntent + close timestamp -> PerpCloseIntent.
    Produces the EXIT that flattens an entry at the holding horizon.

Discrete model (spec §7): each event is an independent open-and-close
trade. There is no delta-to-target rebalancing and no current-position
input, unlike A1's funding-capture sizer.

What this module does NOT do:
  - Choose the holding horizon (the runner passes the close timestamp).
  - Enforce portfolio-level caps (runner concern; the sizer sees one
    instrument at a time).
  - Compute P&L or costs (attribution + gates layer).
"""
from __future__ import annotations

from datetime import datetime
from typing import Final

from strategies.vol_event_persistence.config.sizing import (
    SizingConfig,
    SizingConfigError,
)
from strategies.vol_event_persistence.signal.evaluate import (
    EventDecision,
    EventDirection,
)
from strategies.vol_event_persistence.sizing.order_intent import (
    OrderSide,
    PerpCloseIntent,
    PerpOrderIntent,
    PerpOrderLeg,
    event_id_for,
)

SIZER_SCHEMA_VERSION: Final[str] = "sizer.v0"

# Entry side for a direction. LONG opens with a BUY, SHORT with a SELL.
_DIRECTION_TO_ENTRY_SIDE = {
    EventDirection.LONG: OrderSide.BUY,
    EventDirection.SHORT: OrderSide.SELL,
}


class SizerError(Exception):
    """Raised on sizing configuration mismatch or invariant violation."""


def size_intent(
    decision: EventDecision,
    sizing_config: SizingConfig,
) -> PerpOrderIntent | None:
    """Produce the entry intent for one event decision, or None.

    Args:
        decision: the EventDecision from evaluate_event().
        sizing_config: the per-instrument sizing rules in force.

    Returns:
        PerpOrderIntent for LONG/SHORT decisions; None for FLAT (no trade).

    Raises:
        SizerError if no sizing rule exists for the instrument, or the
        decision's venue does not match the rule's venue.
    """
    if decision.direction is EventDirection.FLAT:
        # No trade: covers non-events and zero-directional-signal events.
        return None

    entry_side = _DIRECTION_TO_ENTRY_SIDE.get(decision.direction)
    if entry_side is None:
        raise SizerError(f"unhandled direction: {decision.direction!r}")

    try:
        rule = sizing_config.rule_for(decision.instrument)
    except SizingConfigError as e:
        raise SizerError(str(e)) from e

    if decision.venue != rule.venue:
        raise SizerError(
            f"decision venue {decision.venue!r} does not match sizing rule "
            f"venue {rule.venue!r} for instrument {decision.instrument!r}"
        )

    leg = PerpOrderLeg(
        venue=rule.venue,
        instrument=rule.instrument,
        side=entry_side,
        quantity=rule.quantity_per_event,
    )

    return PerpOrderIntent(
        as_of=decision.as_of,
        leg=leg,
        direction=decision.direction,
        sizing_config_hash=sizing_config.content_hash(),
        event_decision_schema_version=decision.schema_version,
    )


def make_close_intent(
    entry: PerpOrderIntent,
    close_as_of: datetime,
) -> PerpCloseIntent:
    """Produce the close that flattens an entry at the holding horizon.

    Args:
        entry: the PerpOrderIntent that opened the position.
        close_as_of: the horizon timestamp at which the position is closed.
            Must be strictly after the entry's as_of.

    Returns:
        PerpCloseIntent carrying the opposite side, the original direction
        for attribution, and the event linkage.

    Raises:
        SizerError if close_as_of is not strictly after entry.as_of.
    """
    if close_as_of <= entry.as_of:
        raise SizerError(
            f"close_as_of ({close_as_of}) must be strictly after entry.as_of "
            f"({entry.as_of})"
        )

    close_side = (
        OrderSide.SELL if entry.leg.side is OrderSide.BUY else OrderSide.BUY
    )

    return PerpCloseIntent(
        entry_intent_uuid=entry.intent_uuid,
        original_event_id=event_id_for(
            entry.leg.venue, entry.leg.instrument, entry.as_of
        ),
        original_direction=entry.direction,
        close_side=close_side,
        quantity=entry.leg.quantity,
        venue=entry.leg.venue,
        instrument=entry.leg.instrument,
        as_of=close_as_of,
        sizing_config_hash=entry.sizing_config_hash,
    )
