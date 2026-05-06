"""OrderIntent — the sizer's output type.

Carries every piece of lineage needed to trace this intent back through
the signal evaluator, the cost model, and the canonical funding-rate
window that produced it. Reconciliation reads this to prove "the order
that was submitted matches the intent that was generated from this signal."

This is the strategy-layer OrderIntent. The Day 8 runner translates it
into whatever the 0007 OMS path expects on its side. Keeping the strategy
type separate from the OMS type lets both evolve independently.

Two-leg by construction: an A1 OrderIntent always represents the perp
leg + the spot leg of one funding-capture pair. A bare single-leg intent
is a sizing bug, not a feature. The two-leg invariant is enforced at
construction time.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Final


ORDER_INTENT_SCHEMA_VERSION: Final[str] = "order_intent.v0"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class InstrumentKind(str, Enum):
    PERP = "perp"
    SPOT = "spot"


@dataclass(frozen=True)
class OrderLeg:
    """One leg of a two-leg funding-capture intent.

    Fields:
        venue: lowercase venue
        instrument: vendor canonical code
        kind: PERP or SPOT
        side: BUY or SELL
        quantity: absolute quantity to trade (always positive). Direction
            is encoded in `side`.
    """

    venue: str
    instrument: str
    kind: InstrumentKind
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
class OrderIntent:
    """The full two-leg intent emitted by the sizer.

    Fields:
        as_of: when the intent was generated. Copied from SignalEvaluation.
        perp_leg: perp side of the pair
        spot_leg: spot side of the pair
        cost_model_hash: lineage to the cost model that produced the
            decision. Copied from SignalEvaluation.cost_model_hash.
        sizing_config_hash: lineage to the sizing bounds in force.
        signal_decision: the SignalDecision string this intent implements.
        intent_uuid: optional caller-provided UUID for idempotency. The
            runner uses this when threading into 0007's idempotency_key.
            None means "let the runner generate one".
        schema_version: this intent's schema version
    """

    as_of: datetime
    perp_leg: OrderLeg
    spot_leg: OrderLeg
    cost_model_hash: str
    sizing_config_hash: str
    signal_decision: str
    intent_uuid: str | None = None
    schema_version: str = ORDER_INTENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        if self.perp_leg.kind != InstrumentKind.PERP:
            raise ValueError(
                f"perp_leg must be PERP kind, got {self.perp_leg.kind}"
            )
        if self.spot_leg.kind != InstrumentKind.SPOT:
            raise ValueError(
                f"spot_leg must be SPOT kind, got {self.spot_leg.kind}"
            )
        # Two legs must be on the same venue (single-venue first per
        # roadmap §3.1.1).
        if self.perp_leg.venue != self.spot_leg.venue:
            raise ValueError(
                f"perp and spot legs must share venue: "
                f"perp={self.perp_leg.venue} spot={self.spot_leg.venue}"
            )
        # Two legs must hedge: one buys, one sells.
        if self.perp_leg.side == self.spot_leg.side:
            raise ValueError(
                f"perp and spot legs must hedge (one buy + one sell); "
                f"got perp={self.perp_leg.side} spot={self.spot_leg.side}"
            )
        # Two legs must have equal quantity (equal-nominal hedge — at P0
        # we don't model contract-multiplier differences; that becomes
        # important if/when we add a non-USDT-margined perp).
        if self.perp_leg.quantity != self.spot_leg.quantity:
            raise ValueError(
                f"perp and spot legs must have equal quantity at P0; "
                f"got perp={self.perp_leg.quantity} spot={self.spot_leg.quantity}"
            )
        if not self.cost_model_hash:
            raise ValueError("cost_model_hash is required for lineage")
        if not self.sizing_config_hash:
            raise ValueError("sizing_config_hash is required for lineage")
        if not self.signal_decision:
            raise ValueError("signal_decision is required for lineage")
