"""Unit tests for forward-return attribution.

Worked examples (entry=100):
  LONG, exit=101, funding=0   -> gross=100, exec=10, net=90
  LONG, exit=101, funding=3   -> gross=100, funding=-3, net=87
  SHORT, exit=99, funding=3   -> gross=100, funding=+3, net=93
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from strategies.vol_event_persistence.attribution.cost_model import (
    COST_MODEL_SCHEMA_VERSION,
)
from strategies.vol_event_persistence.attribution.forward_returns import (
    FORWARD_RETURN_SCHEMA_VERSION,
    ForwardReturn,
    ForwardReturnError,
    compute_forward_return,
    gross_return_bps,
)
from strategies.vol_event_persistence.signal.evaluate import EventDirection


def _q(x: Decimal, places: str = "1e-9") -> Decimal:
    return x.quantize(Decimal(places))


# ===== gross_return_bps =====


def test_gross_long_profit():
    g = gross_return_bps(Decimal("100"), Decimal("101"), EventDirection.LONG)
    assert g == Decimal("100")  # (101-100)/100 * 10000


def test_gross_long_loss():
    g = gross_return_bps(Decimal("100"), Decimal("99"), EventDirection.LONG)
    assert g == Decimal("-100")


def test_gross_short_profit():
    g = gross_return_bps(Decimal("100"), Decimal("99"), EventDirection.SHORT)
    assert g == Decimal("100")  # (100-99)/100 * 10000


def test_gross_short_loss():
    g = gross_return_bps(Decimal("100"), Decimal("101"), EventDirection.SHORT)
    assert g == Decimal("-100")


def test_gross_flat_raises():
    with pytest.raises(ForwardReturnError, match="FLAT never trades"):
        gross_return_bps(Decimal("100"), Decimal("101"), EventDirection.FLAT)


def test_gross_non_positive_price_raises():
    with pytest.raises(ForwardReturnError, match="positive"):
        gross_return_bps(Decimal("0"), Decimal("101"), EventDirection.LONG)
    with pytest.raises(ForwardReturnError, match="positive"):
        gross_return_bps(Decimal("100"), Decimal("-1"), EventDirection.LONG)


def test_gross_non_decimal_price_raises():
    with pytest.raises(ForwardReturnError, match="Decimal"):
        gross_return_bps(100.0, Decimal("101"), EventDirection.LONG)


# ===== compute_forward_return: worked examples =====


def _compute(direction, entry, exit_, funding, horizon=1):
    return compute_forward_return(
        venue="binance",
        instrument="BTCUSDT",
        event_id="binance:BTCUSDT:2026-01-01T00:00:00+00:00",
        direction=direction,
        horizon_days=horizon,
        entry_price=Decimal(entry),
        exit_price=Decimal(exit_),
        realised_funding_bps=Decimal(funding),
    )


def test_long_no_funding_net_90():
    r = _compute(EventDirection.LONG, "100", "101", "0")
    assert r.gross_bps == Decimal("100")
    assert r.funding_pnl_bps == Decimal("0")
    assert r.execution_cost_bps == Decimal("10")
    assert r.net_bps == Decimal("90")


def test_long_with_funding_cost_net_87():
    r = _compute(EventDirection.LONG, "100", "101", "3")
    assert r.gross_bps == Decimal("100")
    assert r.funding_pnl_bps == Decimal("-3")  # long pays
    assert r.net_bps == Decimal("87")  # 100 - 3 - 10


def test_short_with_funding_credit_net_93():
    r = _compute(EventDirection.SHORT, "100", "99", "3")
    assert r.gross_bps == Decimal("100")
    assert r.funding_pnl_bps == Decimal("3")  # short receives
    assert r.net_bps == Decimal("93")  # 100 + 3 - 10


def test_losing_trade_negative_net():
    r = _compute(EventDirection.LONG, "100", "99", "0")
    assert r.gross_bps == Decimal("-100")
    assert r.net_bps == Decimal("-110")  # -100 + 0 - 10


# ===== compute_forward_return: structure =====


def test_output_carries_all_components():
    r = _compute(EventDirection.LONG, "100", "101", "2", horizon=3)
    assert isinstance(r, ForwardReturn)
    assert r.venue == "binance"
    assert r.instrument == "BTCUSDT"
    assert r.event_id == "binance:BTCUSDT:2026-01-01T00:00:00+00:00"
    assert r.direction is EventDirection.LONG
    assert r.horizon_days == 3
    assert r.entry_price == Decimal("100")
    assert r.exit_price == Decimal("101")
    assert r.realised_funding_bps == Decimal("2")
    assert r.cost_model_schema_version == COST_MODEL_SCHEMA_VERSION
    assert r.schema_version == FORWARD_RETURN_SCHEMA_VERSION


def test_net_is_gross_plus_funding_minus_exec():
    """Identity check across a non-round example."""
    r = _compute(EventDirection.SHORT, "65000", "64500", "1.5", horizon=7)
    assert _q(r.net_bps) == _q(r.gross_bps + r.funding_pnl_bps - r.execution_cost_bps)


def test_all_horizons_accepted():
    for h in (1, 3, 7):
        r = _compute(EventDirection.LONG, "100", "101", "0", horizon=h)
        assert r.horizon_days == h


# ===== validation =====


def test_flat_raises():
    with pytest.raises(ForwardReturnError, match="FLAT never trades"):
        _compute(EventDirection.FLAT, "100", "101", "0")


def test_non_positive_horizon_raises():
    with pytest.raises(ForwardReturnError, match="horizon_days must be positive"):
        _compute(EventDirection.LONG, "100", "101", "0", horizon=0)


def test_non_decimal_funding_raises():
    with pytest.raises(ForwardReturnError, match="realised_funding_bps must be Decimal"):
        compute_forward_return(
            venue="binance",
            instrument="BTCUSDT",
            event_id="x",
            direction=EventDirection.LONG,
            horizon_days=1,
            entry_price=Decimal("100"),
            exit_price=Decimal("101"),
            realised_funding_bps=3.0,  # float
        )
