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
