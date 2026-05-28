"""Unit tests for the sizer.

size_intent: FLAT -> None; LONG -> BUY entry; SHORT -> SELL entry.
make_close_intent: flips side, retains original direction, links via
event_id, enforces close_as_of strictly after entry.as_of.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from strategies.vol_event_persistence.config.sizing import (
    PerpSizingRule,
    SizingConfig,
)
from strategies.vol_event_persistence.signal.evaluate import (
    EventDecision,
    EventDirection,
)
from strategies.vol_event_persistence.sizing.order_intent import (
    OrderSide,
    PerpCloseIntent,
    PerpOrderIntent,
    event_id_for,
)
from strategies.vol_event_persistence.sizing.sizer import (
    SizerError,
    make_close_intent,
    size_intent,
)

_AS_OF = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def _decision(
    direction: EventDirection,
    *,
    venue: str = "binance",
    instrument: str = "BTCUSDT",
    as_of: datetime = _AS_OF,
) -> EventDecision:
    return EventDecision(
        venue=venue,
        instrument=instrument,
        as_of=as_of,
        current_sigma=Decimal("100"),
        percentile_value=Decimal("86"),
        is_event=direction is not EventDirection.FLAT,
        pre_event_log_return=Decimal("0.01"),
        direction=direction,
        realised_vol_schema_version="realised_vol.v0",
        percentile_event_schema_version="percentile_event.v0",
        schema_version="event_decision.v0",
    )


def _config(qty: str = "0.01") -> SizingConfig:
    return SizingConfig(rules=(
        PerpSizingRule(venue="binance", instrument="BTCUSDT",
                       quantity_per_event=Decimal(qty)),
        PerpSizingRule(venue="binance", instrument="ETHUSDT",
                       quantity_per_event=Decimal("0.1")),
    ))


# ===== size_intent =====


def test_flat_returns_none():
    result = size_intent(_decision(EventDirection.FLAT), _config())
    assert result is None


def test_long_produces_buy_entry():
    intent = size_intent(_decision(EventDirection.LONG), _config())
    assert isinstance(intent, PerpOrderIntent)
    assert intent.direction is EventDirection.LONG
    assert intent.leg.side is OrderSide.BUY
    assert intent.leg.instrument == "BTCUSDT"
    assert intent.leg.quantity == Decimal("0.01")
    assert intent.as_of == _AS_OF


def test_short_produces_sell_entry():
    intent = size_intent(_decision(EventDirection.SHORT), _config())
    assert intent.direction is EventDirection.SHORT
    assert intent.leg.side is OrderSide.SELL


def test_entry_carries_lineage():
    cfg = _config()
    intent = size_intent(_decision(EventDirection.LONG), cfg)
    assert intent.sizing_config_hash == cfg.content_hash()
    assert intent.event_decision_schema_version == "event_decision.v0"


def test_per_instrument_quantity_resolved():
    eth = size_intent(_decision(EventDirection.LONG, instrument="ETHUSDT"), _config())
    assert eth.leg.instrument == "ETHUSDT"
    assert eth.leg.quantity == Decimal("0.1")


def test_missing_rule_raises():
    with pytest.raises(SizerError, match="no sizing rule"):
        size_intent(_decision(EventDirection.LONG, instrument="SOLUSDT"), _config())


def test_venue_mismatch_raises():
    with pytest.raises(SizerError, match="does not match sizing rule"):
        size_intent(_decision(EventDirection.LONG, venue="okx"), _config())


# ===== make_close_intent =====


def _entry(direction: EventDirection = EventDirection.LONG) -> PerpOrderIntent:
    return size_intent(_decision(direction), _config())


def test_close_long_entry_sells():
    entry = _entry(EventDirection.LONG)
    close = make_close_intent(entry, _AS_OF + timedelta(days=3))
    assert isinstance(close, PerpCloseIntent)
    assert close.close_side is OrderSide.SELL
    assert close.original_direction is EventDirection.LONG
    assert close.quantity == entry.leg.quantity
    assert close.venue == "binance"
    assert close.instrument == "BTCUSDT"


def test_close_short_entry_buys():
    entry = _entry(EventDirection.SHORT)
    close = make_close_intent(entry, _AS_OF + timedelta(days=1))
    assert close.close_side is OrderSide.BUY
    assert close.original_direction is EventDirection.SHORT


def test_close_event_id_matches_entry_coords():
    entry = _entry(EventDirection.LONG)
    close = make_close_intent(entry, _AS_OF + timedelta(days=7))
    expected = event_id_for(entry.leg.venue, entry.leg.instrument, entry.as_of)
    assert close.original_event_id == expected


def test_close_carries_sizing_hash():
    entry = _entry(EventDirection.LONG)
    close = make_close_intent(entry, _AS_OF + timedelta(days=3))
    assert close.sizing_config_hash == entry.sizing_config_hash


def test_close_carries_entry_uuid_when_present():
    base = _entry(EventDirection.LONG)
    # rebuild entry with an explicit uuid (size_intent leaves it None)
    entry = PerpOrderIntent(
        as_of=base.as_of,
        leg=base.leg,
        direction=base.direction,
        sizing_config_hash=base.sizing_config_hash,
        event_decision_schema_version=base.event_decision_schema_version,
        intent_uuid="22222222-2222-2222-2222-222222222222",
    )
    close = make_close_intent(entry, _AS_OF + timedelta(days=3))
    assert close.entry_intent_uuid == "22222222-2222-2222-2222-222222222222"


def test_close_as_of_must_be_after_entry():
    entry = _entry(EventDirection.LONG)
    with pytest.raises(SizerError, match="strictly after"):
        make_close_intent(entry, entry.as_of)  # equal
    with pytest.raises(SizerError, match="strictly after"):
        make_close_intent(entry, entry.as_of - timedelta(hours=1))  # before


def test_close_at_each_horizon():
    """1d / 3d / 7d horizons all produce valid closes."""
    entry = _entry(EventDirection.LONG)
    for days in (1, 3, 7):
        close = make_close_intent(entry, entry.as_of + timedelta(days=days))
        assert close.as_of == entry.as_of + timedelta(days=days)
        assert close.close_side is OrderSide.SELL
