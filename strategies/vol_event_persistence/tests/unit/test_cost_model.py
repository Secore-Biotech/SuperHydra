"""Unit tests for the attribution cost model.

The funding sign convention is load-bearing and encoded here explicitly:
positive funding => longs pay, shorts receive.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from strategies.vol_event_persistence.attribution.cost_model import (
    COST_MODEL_SCHEMA_VERSION,
    execution_cost_bps,
    funding_pnl_bps,
)
from strategies.vol_event_persistence.config import pre_lock
from strategies.vol_event_persistence.signal.evaluate import EventDirection


# ===== Drift guard =====


def test_cost_constants_match_spec():
    """Spec §4: 4 bps taker/side, 1 bp slippage/side, 10 bps round-trip floor."""
    assert pre_lock.TAKER_FEE_BPS_PER_SIDE == Decimal("4")
    assert pre_lock.SLIPPAGE_BPS_PER_SIDE == Decimal("1")
    assert pre_lock.ROUND_TRIP_COST_BPS_FLOOR == Decimal("10")


def test_schema_version_value():
    assert COST_MODEL_SCHEMA_VERSION == "attribution_cost_model.v0"


# ===== Execution cost =====


def test_execution_cost_is_ten_bps():
    assert execution_cost_bps() == Decimal("10")


def test_execution_cost_equals_round_trip_floor():
    """Internal consistency: computed round trip == declared floor."""
    assert execution_cost_bps() == pre_lock.ROUND_TRIP_COST_BPS_FLOOR


# ===== Funding sign convention (load-bearing) =====


def test_long_pays_positive_funding():
    """LONG + positive funding -> negative P&L (paid)."""
    result = funding_pnl_bps(EventDirection.LONG, Decimal("3"))
    assert result == Decimal("-3")


def test_short_receives_positive_funding():
    """SHORT + positive funding -> positive P&L (received)."""
    result = funding_pnl_bps(EventDirection.SHORT, Decimal("3"))
    assert result == Decimal("3")


def test_long_receives_negative_funding():
    """LONG + negative funding -> positive P&L (received)."""
    result = funding_pnl_bps(EventDirection.LONG, Decimal("-2"))
    assert result == Decimal("2")


def test_short_pays_negative_funding():
    """SHORT + negative funding -> negative P&L (paid)."""
    result = funding_pnl_bps(EventDirection.SHORT, Decimal("-2"))
    assert result == Decimal("-2")


def test_zero_funding_is_zero():
    assert funding_pnl_bps(EventDirection.LONG, Decimal("0")) == Decimal("0")
    assert funding_pnl_bps(EventDirection.SHORT, Decimal("0")) == Decimal("0")


def test_funding_flat_raises():
    with pytest.raises(ValueError, match="LONG or SHORT"):
        funding_pnl_bps(EventDirection.FLAT, Decimal("3"))
