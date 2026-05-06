"""Unit tests for strategies.a1_funding.sizing.sizer.

Coverage:
  - Decision → target mapping (LONG/SHORT/FLAT)
  - Position deltas: open from flat, flip, close, partial adjust
  - No-trade cases: target == current
  - Suppression: |delta| < min_quantity
  - Hedge invariants: leg sides hedge correctly, quantities equal
  - Lineage: cost_model_hash and sizing_config_hash threaded through
  - Validation: float current_quantity, missing rule, venue mismatch
  - Reproducibility: same inputs → byte-equal OrderIntent
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from core.config.cost_model import conservative_default_v0 as cost_default
from strategies.a1_funding.config.sizing import (
    InstrumentSizingRule,
    SizingConfig,
    SIZING_CONFIG_SCHEMA_VERSION,
    conservative_default_v0,
)
from strategies.a1_funding.signal.evaluate import (
    SIGNAL_EVALUATION_SCHEMA_VERSION,
    SignalDecision,
    SignalEvaluation,
)
from strategies.a1_funding.sizing.order_intent import (
    InstrumentKind,
    OrderSide,
)
from strategies.a1_funding.sizing.sizer import (
    SizerError,
    size_intent,
)


UTC = timezone.utc


def _signal(
    decision: SignalDecision,
    instrument: str = "BTCUSDT",
    venue: str = "binance",
) -> SignalEvaluation:
    return SignalEvaluation(
        venue=venue,
        instrument=instrument,
        as_of=datetime(2026, 1, 5, tzinfo=UTC),
        forecast_rate=Decimal("0.0005"),
        per_period_cost_rate=Decimal("0.0001"),
        net_edge_rate=Decimal("0.0004"),
        decision=decision,
        cost_model_hash="c" * 64,
    )


# ─── Open from flat ──────────────────────────────────────────────────────


def test_long_signal_from_flat_opens_long_perp():
    signal = _signal(SignalDecision.LONG_PERP_SHORT_SPOT)
    cfg = conservative_default_v0()
    intent = size_intent(signal, current_perp_quantity=Decimal("0"), sizing_config=cfg)

    assert intent is not None
    rule = cfg.rule_for_perp("BTCUSDT")
    # Target is +max_quantity; current is 0 → buy max_quantity
    assert intent.perp_leg.side == OrderSide.BUY
    assert intent.perp_leg.quantity == rule.max_quantity
    assert intent.spot_leg.side == OrderSide.SELL
    assert intent.spot_leg.quantity == rule.max_quantity


def test_short_signal_from_flat_opens_short_perp():
    signal = _signal(SignalDecision.SHORT_PERP_LONG_SPOT)
    cfg = conservative_default_v0()
    intent = size_intent(signal, current_perp_quantity=Decimal("0"), sizing_config=cfg)

    assert intent is not None
    rule = cfg.rule_for_perp("BTCUSDT")
    assert intent.perp_leg.side == OrderSide.SELL
    assert intent.perp_leg.quantity == rule.max_quantity
    assert intent.spot_leg.side == OrderSide.BUY
    assert intent.spot_leg.quantity == rule.max_quantity


# ─── No-trade cases ──────────────────────────────────────────────────────


def test_flat_signal_with_flat_position_no_trade():
    signal = _signal(SignalDecision.FLAT)
    cfg = conservative_default_v0()
    intent = size_intent(signal, current_perp_quantity=Decimal("0"), sizing_config=cfg)
    assert intent is None


def test_long_signal_with_position_already_at_target_no_trade():
    signal = _signal(SignalDecision.LONG_PERP_SHORT_SPOT)
    cfg = conservative_default_v0()
    rule = cfg.rule_for_perp("BTCUSDT")
    intent = size_intent(
        signal,
        current_perp_quantity=rule.max_quantity,  # already long max
        sizing_config=cfg,
    )
    assert intent is None


def test_short_signal_with_position_already_at_target_no_trade():
    signal = _signal(SignalDecision.SHORT_PERP_LONG_SPOT)
    cfg = conservative_default_v0()
    rule = cfg.rule_for_perp("BTCUSDT")
    intent = size_intent(
        signal,
        current_perp_quantity=-rule.max_quantity,
        sizing_config=cfg,
    )
    assert intent is None


# ─── Position flips and closes ───────────────────────────────────────────


def test_short_signal_with_long_position_sells_full_flip():
    """Currently long max; signal is short → sell 2*max to reach -max."""
    signal = _signal(SignalDecision.SHORT_PERP_LONG_SPOT)
    cfg = conservative_default_v0()
    rule = cfg.rule_for_perp("BTCUSDT")
    intent = size_intent(
        signal,
        current_perp_quantity=rule.max_quantity,
        sizing_config=cfg,
    )
    assert intent is not None
    assert intent.perp_leg.side == OrderSide.SELL
    assert intent.perp_leg.quantity == Decimal("2") * rule.max_quantity


def test_flat_signal_with_long_position_closes():
    signal = _signal(SignalDecision.FLAT)
    cfg = conservative_default_v0()
    rule = cfg.rule_for_perp("BTCUSDT")
    intent = size_intent(
        signal,
        current_perp_quantity=rule.max_quantity,
        sizing_config=cfg,
    )
    assert intent is not None
    assert intent.perp_leg.side == OrderSide.SELL
    assert intent.perp_leg.quantity == rule.max_quantity


def test_flat_signal_with_short_position_closes():
    signal = _signal(SignalDecision.FLAT)
    cfg = conservative_default_v0()
    rule = cfg.rule_for_perp("BTCUSDT")
    intent = size_intent(
        signal,
        current_perp_quantity=-rule.max_quantity,
        sizing_config=cfg,
    )
    assert intent is not None
    assert intent.perp_leg.side == OrderSide.BUY
    assert intent.perp_leg.quantity == rule.max_quantity


def test_partial_adjust_when_below_target():
    """Currently +0.005; signal long → buy 0.005 to reach +0.01."""
    signal = _signal(SignalDecision.LONG_PERP_SHORT_SPOT)
    cfg = conservative_default_v0()
    rule = cfg.rule_for_perp("BTCUSDT")
    half = rule.max_quantity / Decimal("2")
    intent = size_intent(signal, current_perp_quantity=half, sizing_config=cfg)
    assert intent is not None
    assert intent.perp_leg.side == OrderSide.BUY
    assert intent.perp_leg.quantity == rule.max_quantity - half


# ─── Min-quantity suppression ────────────────────────────────────────────


def test_delta_below_min_quantity_suppressed():
    """Signal long + position just below max → tiny delta < min_quantity → None."""
    signal = _signal(SignalDecision.LONG_PERP_SHORT_SPOT)
    cfg = conservative_default_v0()
    rule = cfg.rule_for_perp("BTCUSDT")
    # Delta = max_quantity - (max_quantity - half_min) = half_min < min
    half_min = rule.min_quantity / Decimal("2")
    current = rule.max_quantity - half_min
    intent = size_intent(signal, current_perp_quantity=current, sizing_config=cfg)
    assert intent is None


def test_delta_at_min_quantity_emitted():
    """Delta exactly at min_quantity is allowed (boundary is inclusive
    on the trade side)."""
    signal = _signal(SignalDecision.LONG_PERP_SHORT_SPOT)
    cfg = conservative_default_v0()
    rule = cfg.rule_for_perp("BTCUSDT")
    current = rule.max_quantity - rule.min_quantity
    intent = size_intent(signal, current_perp_quantity=current, sizing_config=cfg)
    assert intent is not None
    assert intent.perp_leg.quantity == rule.min_quantity


# ─── Hedge invariants ────────────────────────────────────────────────────


def test_perp_and_spot_legs_always_hedge():
    """For every non-None intent: perp side != spot side, quantities equal."""
    cfg = conservative_default_v0()
    rule = cfg.rule_for_perp("BTCUSDT")

    for decision in (SignalDecision.LONG_PERP_SHORT_SPOT,
                     SignalDecision.SHORT_PERP_LONG_SPOT,
                     SignalDecision.FLAT):
        for current in (Decimal("0"),
                        rule.max_quantity,
                        -rule.max_quantity,
                        rule.max_quantity / Decimal("2")):
            intent = size_intent(_signal(decision),
                                 current_perp_quantity=current,
                                 sizing_config=cfg)
            if intent is not None:
                assert intent.perp_leg.side != intent.spot_leg.side
                assert intent.perp_leg.quantity == intent.spot_leg.quantity
                assert intent.perp_leg.kind == InstrumentKind.PERP
                assert intent.spot_leg.kind == InstrumentKind.SPOT


# ─── Lineage ──────────────────────────────────────────────────────────────


def test_intent_carries_cost_model_hash_from_signal():
    signal = _signal(SignalDecision.LONG_PERP_SHORT_SPOT)
    cfg = conservative_default_v0()
    intent = size_intent(signal, current_perp_quantity=Decimal("0"), sizing_config=cfg)
    assert intent is not None
    assert intent.cost_model_hash == signal.cost_model_hash
    assert intent.cost_model_hash == "c" * 64  # from the signal fixture


def test_intent_carries_sizing_config_hash():
    signal = _signal(SignalDecision.LONG_PERP_SHORT_SPOT)
    cfg = conservative_default_v0()
    intent = size_intent(signal, current_perp_quantity=Decimal("0"), sizing_config=cfg)
    assert intent is not None
    assert intent.sizing_config_hash == cfg.content_hash


def test_intent_records_signal_decision_string():
    signal = _signal(SignalDecision.LONG_PERP_SHORT_SPOT)
    cfg = conservative_default_v0()
    intent = size_intent(signal, current_perp_quantity=Decimal("0"), sizing_config=cfg)
    assert intent is not None
    assert intent.signal_decision == "long_perp_short_spot"


def test_intent_carries_signal_as_of():
    signal = _signal(SignalDecision.LONG_PERP_SHORT_SPOT)
    cfg = conservative_default_v0()
    intent = size_intent(signal, current_perp_quantity=Decimal("0"), sizing_config=cfg)
    assert intent is not None
    assert intent.as_of == signal.as_of


# ─── Validation errors ───────────────────────────────────────────────────


def test_float_current_quantity_raises():
    signal = _signal(SignalDecision.LONG_PERP_SHORT_SPOT)
    cfg = conservative_default_v0()
    with pytest.raises(SizerError, match="Decimal"):
        size_intent(signal, current_perp_quantity=0.0, sizing_config=cfg)


def test_unknown_instrument_raises():
    signal = _signal(SignalDecision.LONG_PERP_SHORT_SPOT, instrument="DOGEUSDT")
    cfg = conservative_default_v0()
    with pytest.raises(SizerError, match="DOGEUSDT"):
        size_intent(signal, current_perp_quantity=Decimal("0"), sizing_config=cfg)


def test_venue_mismatch_raises():
    signal = _signal(SignalDecision.LONG_PERP_SHORT_SPOT, venue="okx")
    cfg = conservative_default_v0()  # binance only
    with pytest.raises(SizerError, match="venue"):
        size_intent(signal, current_perp_quantity=Decimal("0"), sizing_config=cfg)


# ─── Reproducibility ─────────────────────────────────────────────────────


def test_reproducibility_byte_equal():
    """Same signal + same current position + same config → byte-equal intent."""
    signal_a = _signal(SignalDecision.LONG_PERP_SHORT_SPOT)
    signal_b = _signal(SignalDecision.LONG_PERP_SHORT_SPOT)
    cfg = conservative_default_v0()

    a = size_intent(signal_a, current_perp_quantity=Decimal("0.005"), sizing_config=cfg)
    b = size_intent(signal_b, current_perp_quantity=Decimal("0.005"), sizing_config=cfg)

    assert a == b
    assert a is not b
    # Decimal comparison is value-based; also check string repr.
    assert str(a.perp_leg.quantity) == str(b.perp_leg.quantity)
    assert a.cost_model_hash == b.cost_model_hash
    assert a.sizing_config_hash == b.sizing_config_hash


def test_reproducibility_no_trade_returns_consistent_none():
    """Same flat-out conditions → both calls return None (no hidden state)."""
    signal = _signal(SignalDecision.FLAT)
    cfg = conservative_default_v0()
    a = size_intent(signal, current_perp_quantity=Decimal("0"), sizing_config=cfg)
    b = size_intent(signal, current_perp_quantity=Decimal("0"), sizing_config=cfg)
    assert a is None and b is None
