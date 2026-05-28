"""Unit tests for PerpOrderLeg and PerpOrderIntent.

Single-leg perp intent. Direction (strategy) and leg.side (OMS) must be
consistent: LONG<->BUY, SHORT<->SELL. FLAT never produces an intent.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from strategies.vol_event_persistence.signal.evaluate import EventDirection
from strategies.vol_event_persistence.sizing.order_intent import (
    ORDER_INTENT_SCHEMA_VERSION,
    OrderSide,
    PerpOrderIntent,
    PerpOrderLeg,
)

_AS_OF = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def _leg(side: OrderSide = OrderSide.BUY, qty: str = "1.0") -> PerpOrderLeg:
    return PerpOrderLeg(
        venue="binance", instrument="BTCUSDT", side=side, quantity=Decimal(qty)
    )


# ===== OrderSide / schema =====


def test_order_side_values():
    assert OrderSide.BUY.value == "buy"
    assert OrderSide.SELL.value == "sell"


def test_schema_version_value():
    assert ORDER_INTENT_SCHEMA_VERSION == "perp_order_intent.v0"


# ===== PerpOrderLeg validation =====


def test_leg_valid():
    leg = _leg()
    assert leg.venue == "binance"
    assert leg.quantity == Decimal("1.0")


def test_leg_rejects_non_lowercase_venue():
    with pytest.raises(ValueError, match="lowercase"):
        PerpOrderLeg(venue="Binance", instrument="BTCUSDT",
                     side=OrderSide.BUY, quantity=Decimal("1"))


def test_leg_rejects_empty_instrument():
    with pytest.raises(ValueError, match="non-empty"):
        PerpOrderLeg(venue="binance", instrument="",
                     side=OrderSide.BUY, quantity=Decimal("1"))


def test_leg_rejects_non_decimal_quantity():
    with pytest.raises(TypeError, match="Decimal"):
        PerpOrderLeg(venue="binance", instrument="BTCUSDT",
                     side=OrderSide.BUY, quantity=1.0)  # float


def test_leg_rejects_zero_quantity():
    with pytest.raises(ValueError, match="positive"):
        PerpOrderLeg(venue="binance", instrument="BTCUSDT",
                     side=OrderSide.BUY, quantity=Decimal("0"))


def test_leg_rejects_negative_quantity():
    with pytest.raises(ValueError, match="positive"):
        PerpOrderLeg(venue="binance", instrument="BTCUSDT",
                     side=OrderSide.BUY, quantity=Decimal("-1"))


# ===== PerpOrderIntent validation =====


def test_intent_valid_long_is_buy():
    intent = PerpOrderIntent(
        as_of=_AS_OF,
        leg=_leg(OrderSide.BUY),
        direction=EventDirection.LONG,
        sizing_config_hash="abc123",
        event_decision_schema_version="event_decision.v0",
    )
    assert intent.direction is EventDirection.LONG
    assert intent.leg.side is OrderSide.BUY
    assert intent.schema_version == ORDER_INTENT_SCHEMA_VERSION
    assert intent.intent_uuid is None


def test_intent_valid_short_is_sell():
    intent = PerpOrderIntent(
        as_of=_AS_OF,
        leg=_leg(OrderSide.SELL),
        direction=EventDirection.SHORT,
        sizing_config_hash="abc123",
        event_decision_schema_version="event_decision.v0",
    )
    assert intent.direction is EventDirection.SHORT
    assert intent.leg.side is OrderSide.SELL


def test_intent_rejects_naive_as_of():
    with pytest.raises(ValueError, match="timezone-aware"):
        PerpOrderIntent(
            as_of=datetime(2026, 1, 1, 0, 0, 0),  # naive
            leg=_leg(OrderSide.BUY),
            direction=EventDirection.LONG,
            sizing_config_hash="abc123",
            event_decision_schema_version="event_decision.v0",
        )


def test_intent_rejects_flat_direction():
    with pytest.raises(ValueError, match="FLAT"):
        PerpOrderIntent(
            as_of=_AS_OF,
            leg=_leg(OrderSide.BUY),
            direction=EventDirection.FLAT,
            sizing_config_hash="abc123",
            event_decision_schema_version="event_decision.v0",
        )


def test_intent_rejects_long_with_sell_side():
    with pytest.raises(ValueError, match="inconsistent"):
        PerpOrderIntent(
            as_of=_AS_OF,
            leg=_leg(OrderSide.SELL),  # SELL but direction LONG
            direction=EventDirection.LONG,
            sizing_config_hash="abc123",
            event_decision_schema_version="event_decision.v0",
        )


def test_intent_rejects_short_with_buy_side():
    with pytest.raises(ValueError, match="inconsistent"):
        PerpOrderIntent(
            as_of=_AS_OF,
            leg=_leg(OrderSide.BUY),  # BUY but direction SHORT
            direction=EventDirection.SHORT,
            sizing_config_hash="abc123",
            event_decision_schema_version="event_decision.v0",
        )


def test_intent_accepts_explicit_uuid():
    intent = PerpOrderIntent(
        as_of=_AS_OF,
        leg=_leg(OrderSide.BUY),
        direction=EventDirection.LONG,
        sizing_config_hash="abc123",
        event_decision_schema_version="event_decision.v0",
        intent_uuid="11111111-1111-1111-1111-111111111111",
    )
    assert intent.intent_uuid == "11111111-1111-1111-1111-111111111111"
