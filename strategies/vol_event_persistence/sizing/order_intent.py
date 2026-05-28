"""PerpOrderIntent — the sizer's output type.

Single-leg by construction. This engine takes discrete directional perp
positions on volatility events (spec §7), so an intent represents exactly
one perp order. This is the opposite of A1, whose OrderIntent is two-leg
(perp + spot hedge) by construction. The shapes are deliberately NOT
shared: per the lift-to-shared pattern, common OMS plumbing migrates to
execution/ when pressure is real; sibling strategies do not import each
other's intent types.

Carries lineage so reconciliation can trace an order back through the
event decision and the sizing config that produced it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Final

from strategies.vol_event_persistence.signal.evaluate import EventDirection

ORDER_INTENT_SCHEMA_VERSION: Final[str] = "perp_order_intent.v0"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


# Direction (strategy semantic) maps to side (OMS semantic) one-to-one.
# LONG -> BUY, SHORT -> SELL. FLAT never produces an intent.
_DIRECTION_TO_SIDE = {
    EventDirection.LONG: OrderSide.BUY,
    EventDirection.SHORT: OrderSide.SELL,
}


@dataclass(frozen=True)
class PerpOrderLeg:
    """The single perp leg of an intent.

    The instrument is always a perpetual for this engine, so there is no
    InstrumentKind field; perp is implicit. Direction is encoded in side;
    quantity is always positive.

    Fields:
        venue: lowercase venue code
        instrument: vendor-canonical perp code (e.g. "BTCUSDT")
        side: BUY or SELL
        quantity: absolute base-asset quantity (always positive)
    """

    venue: str
    instrument: str
    side: OrderSide
    quantity: Decimal

    def __post_init__(self) -> None:
        if not self.venue or not self.venue.islower():
            raise ValueError(f"venue must be lowercase non-empty, got {self.venue!r}")
        if not self.instrument:
            raise ValueError("instrument must be non-empty")
        if not isinstance(self.quantity, Decimal):
            raise TypeError("quantity must be Decimal")
        if self.quantity <= Decimal("0"):
            raise ValueError(
                f"quantity must be positive (direction encoded in side), "
                f"got {self.quantity}"
            )


@dataclass(frozen=True)
class PerpOrderIntent:
    """A single-leg perp intent emitted by the sizer.

    Fields:
        as_of: when the intent was generated. Copied from the EventDecision.
        leg: the single perp leg.
        direction: the strategy-semantic direction (LONG or SHORT; never
            FLAT — a FLAT decision produces no intent at all). Carried
            alongside leg.side for lineage; the two must be consistent.
        sizing_config_hash: lineage to the sizing config in force.
        event_decision_schema_version: lineage tag from the EventDecision.
        intent_uuid: optional caller-provided UUID for idempotency. None
            means "let the runner generate one."
        schema_version: this intent's schema version.
    """

    as_of: datetime
    leg: PerpOrderLeg
    direction: EventDirection
    sizing_config_hash: str
    event_decision_schema_version: str
    intent_uuid: str | None = None
    schema_version: str = ORDER_INTENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        if self.direction is EventDirection.FLAT:
            raise ValueError(
                "FLAT direction does not produce an intent; the sizer must "
                "return None for FLAT decisions, not construct an intent"
            )
        expected_side = _DIRECTION_TO_SIDE.get(self.direction)
        if expected_side is None:
            raise ValueError(f"unhandled direction: {self.direction!r}")
        if self.leg.side != expected_side:
            raise ValueError(
                f"leg.side {self.leg.side.value!r} inconsistent with "
                f"direction {self.direction.value!r}; expected "
                f"{expected_side.value!r}"
            )


# ===== Close intent (exit) =====
#
# A close is a distinct type, not an overloaded entry. An entry carries a
# direction whose side it must match; a close carries the ORIGINAL
# direction plus the OPPOSITE side, explicitly marked as an exit. Modeling
# the close as its own type keeps entry validation strict and prevents a
# close (e.g. SELL to exit a LONG) from being mis-attributed as a fresh
# SHORT signal in gates/attribution.

CLOSE_INTENT_SCHEMA_VERSION: Final[str] = "perp_close_intent.v0"

# The side that CLOSES a position opened in a given direction.
_DIRECTION_TO_CLOSE_SIDE = {
    EventDirection.LONG: OrderSide.SELL,   # close a long by selling
    EventDirection.SHORT: OrderSide.BUY,   # close a short by buying
}


def event_id_for(venue: str, instrument: str, as_of: datetime) -> str:
    """Deterministic natural key identifying one event.

    One event occurs per (venue, instrument) per evaluation day, so the
    triple (venue, instrument, as_of) uniquely identifies it. Used to pair
    an entry with its close in attribution, independent of whether an
    intent_uuid has been assigned yet.

    Readable rather than hashed: a human-legible key is easier to debug,
    and any malformed as_of (e.g. stray microseconds) surfaces directly
    in the key rather than being hidden behind a digest.
    """
    return f"{venue}:{instrument}:{as_of.isoformat()}"


@dataclass(frozen=True)
class PerpCloseIntent:
    """A single-leg perp exit, closing a previously opened entry.

    Distinct from PerpOrderIntent: this is explicitly an exit, never a new
    directional signal. It retains the original direction for attribution
    and carries the opposite side to flatten the position.

    Fields:
        entry_intent_uuid: the entry's intent_uuid if one was assigned;
            may be None. Secondary linkage to the entry order.
        original_event_id: the event natural key (see event_id_for). The
            primary, always-present linkage between entry and close.
        original_direction: the entry's direction (LONG or SHORT). Retained
            so attribution knows which way the position was held.
        close_side: the side that flattens the position. Must be the
            opposite of the side implied by original_direction.
        quantity: absolute base-asset quantity to close (matches the entry).
        venue, instrument: identity (mirror the entry).
        as_of: when the close is generated (the holding-horizon timestamp).
        sizing_config_hash: lineage, carried from the entry.
        schema_version: this intent's schema version.
    """

    entry_intent_uuid: str | None
    original_event_id: str
    original_direction: EventDirection
    close_side: OrderSide
    quantity: Decimal
    venue: str
    instrument: str
    as_of: datetime
    sizing_config_hash: str
    schema_version: str = CLOSE_INTENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        if not self.original_event_id:
            raise ValueError("original_event_id must be non-empty")
        if self.original_direction not in (EventDirection.LONG, EventDirection.SHORT):
            raise ValueError(
                f"original_direction must be LONG or SHORT (a FLAT decision "
                f"never opened a position), got {self.original_direction!r}"
            )
        if not isinstance(self.quantity, Decimal):
            raise TypeError("quantity must be Decimal")
        if self.quantity <= Decimal("0"):
            raise ValueError(f"quantity must be positive, got {self.quantity}")
        if not self.venue or not self.venue.islower():
            raise ValueError(f"venue must be lowercase non-empty, got {self.venue!r}")
        if not self.instrument:
            raise ValueError("instrument must be non-empty")
        expected_close_side = _DIRECTION_TO_CLOSE_SIDE[self.original_direction]
        if self.close_side != expected_close_side:
            raise ValueError(
                f"close_side {self.close_side.value!r} does not flatten a "
                f"{self.original_direction.value!r} position; expected "
                f"{expected_close_side.value!r}"
            )
