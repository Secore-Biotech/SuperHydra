"""Unit tests for strategies.a1_funding.sizing.order_intent."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from strategies.a1_funding.sizing.order_intent import (
    ORDER_INTENT_SCHEMA_VERSION,
    InstrumentKind,
    OrderIntent,
    OrderLeg,
    OrderSide,
)


UTC = timezone.utc


def _leg(**overrides) -> OrderLeg:
    base = dict(
        venue="binance",
        instrument="BTCUSDT",
        kind=InstrumentKind.PERP,
        side=OrderSide.BUY,
        quantity=Decimal("0.01"),
    )
    base.update(overrides)
    return OrderLeg(**base)


def _intent(**overrides) -> OrderIntent:
    base = dict(
        as_of=datetime(2026, 1, 5, tzinfo=UTC),
        perp_leg=_leg(kind=InstrumentKind.PERP, side=OrderSide.BUY),
        spot_leg=_leg(kind=InstrumentKind.SPOT, side=OrderSide.SELL),
        cost_model_hash="a" * 64,
        sizing_config_hash="b" * 64,
        signal_decision="long_perp_short_spot",
    )
    base.update(overrides)
    return OrderIntent(**base)


# ─── Leg validation ──────────────────────────────────────────────────────


def test_leg_rejects_uppercase_venue():
    with pytest.raises(ValueError, match="venue"):
        _leg(venue="Binance")


def test_leg_rejects_empty_instrument():
    with pytest.raises(ValueError, match="instrument"):
        _leg(instrument="")


def test_leg_rejects_zero_quantity():
    with pytest.raises(ValueError, match="quantity"):
        _leg(quantity=Decimal("0"))


def test_leg_rejects_negative_quantity():
    with pytest.raises(ValueError, match="quantity"):
        _leg(quantity=Decimal("-0.01"))


def test_leg_rejects_float_quantity():
    with pytest.raises(TypeError):
        _leg(quantity=0.01)


# ─── Intent invariants ───────────────────────────────────────────────────


def test_intent_rejects_naive_as_of():
    with pytest.raises(ValueError, match="timezone-aware"):
        _intent(as_of=datetime(2026, 1, 5))


def test_intent_rejects_perp_leg_with_spot_kind():
    with pytest.raises(ValueError, match="perp_leg must be PERP"):
        _intent(perp_leg=_leg(kind=InstrumentKind.SPOT))


def test_intent_rejects_spot_leg_with_perp_kind():
    with pytest.raises(ValueError, match="spot_leg must be SPOT"):
        _intent(spot_leg=_leg(kind=InstrumentKind.PERP, side=OrderSide.SELL))


def test_intent_rejects_legs_on_different_venues():
    with pytest.raises(ValueError, match="share venue"):
        _intent(spot_leg=_leg(
            venue="okx", kind=InstrumentKind.SPOT, side=OrderSide.SELL,
        ))


def test_intent_rejects_legs_with_same_side():
    """Both legs buy or both sell = not a hedge."""
    with pytest.raises(ValueError, match="hedge"):
        _intent(
            perp_leg=_leg(kind=InstrumentKind.PERP, side=OrderSide.BUY),
            spot_leg=_leg(kind=InstrumentKind.SPOT, side=OrderSide.BUY),
        )


def test_intent_rejects_unequal_quantities():
    with pytest.raises(ValueError, match="equal quantity"):
        _intent(
            perp_leg=_leg(
                kind=InstrumentKind.PERP, side=OrderSide.BUY, quantity=Decimal("0.01"),
            ),
            spot_leg=_leg(
                kind=InstrumentKind.SPOT, side=OrderSide.SELL, quantity=Decimal("0.02"),
            ),
        )


def test_intent_requires_cost_model_hash():
    with pytest.raises(ValueError, match="cost_model_hash"):
        _intent(cost_model_hash="")


def test_intent_requires_sizing_config_hash():
    with pytest.raises(ValueError, match="sizing_config_hash"):
        _intent(sizing_config_hash="")


def test_intent_requires_signal_decision():
    with pytest.raises(ValueError, match="signal_decision"):
        _intent(signal_decision="")


# ─── Schema version ──────────────────────────────────────────────────────


def test_schema_version_constant():
    assert ORDER_INTENT_SCHEMA_VERSION == "order_intent.v0"


def test_intent_carries_schema_version():
    intent = _intent()
    assert intent.schema_version == ORDER_INTENT_SCHEMA_VERSION


# ─── Valid construction ──────────────────────────────────────────────────


def test_valid_long_perp_short_spot_intent():
    intent = _intent(
        perp_leg=_leg(kind=InstrumentKind.PERP, side=OrderSide.BUY,
                      quantity=Decimal("0.01")),
        spot_leg=_leg(kind=InstrumentKind.SPOT, side=OrderSide.SELL,
                      quantity=Decimal("0.01")),
        signal_decision="long_perp_short_spot",
    )
    assert intent.perp_leg.side == OrderSide.BUY
    assert intent.spot_leg.side == OrderSide.SELL
    assert intent.perp_leg.quantity == intent.spot_leg.quantity


def test_valid_short_perp_long_spot_intent():
    intent = _intent(
        perp_leg=_leg(kind=InstrumentKind.PERP, side=OrderSide.SELL),
        spot_leg=_leg(kind=InstrumentKind.SPOT, side=OrderSide.BUY),
        signal_decision="short_perp_long_spot",
    )
    assert intent.perp_leg.side == OrderSide.SELL
    assert intent.spot_leg.side == OrderSide.BUY
