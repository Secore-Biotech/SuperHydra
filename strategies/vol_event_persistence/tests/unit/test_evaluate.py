"""Unit tests for evaluate_event.

Direction logic under the persistence hypothesis:
  event + cumulative return > 0 -> LONG
  event + cumulative return < 0 -> SHORT
  event + cumulative return == 0 -> FLAT
  non-event -> FLAT

History fixture: sigmas 1..90 -> nearest-rank P95 = 86. A current sigma
of 100 is therefore an event; 50 is not.

pre_event_log_return = mean_log_return * return_count (24).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from strategies.vol_event_persistence.signal.evaluate import (
    EVENT_DECISION_SCHEMA_VERSION,
    EventDecision,
    EventDirection,
    evaluate_event,
)
from strategies.vol_event_persistence.signal.percentile_state import (
    PERCENTILE_EVENT_SCHEMA_VERSION,
    PercentileEventError,
)
from strategies.vol_event_persistence.signal.realised_vol import (
    REALISED_VOL_SCHEMA_VERSION,
    RealisedVol,
)

_DEFAULT_START = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
_AFTER_HISTORY = _DEFAULT_START + timedelta(days=90)


def _make_rv(
    sigma: str,
    window_end: datetime,
    *,
    mean_log_return: str = "0",
    venue: str = "binance",
    instrument: str = "BTCUSDT",
) -> RealisedVol:
    return RealisedVol(
        venue=venue,
        instrument=instrument,
        window_start=window_end - timedelta(hours=24),
        window_end=window_end,
        window_size=25,
        return_count=24,
        mean_log_return=Decimal(mean_log_return),
        stdev_log_return=Decimal("0"),
        sigma_24h_annualised=Decimal(sigma),
        schema_version=REALISED_VOL_SCHEMA_VERSION,
    )


def _build_history(venue: str = "binance", instrument: str = "BTCUSDT"):
    """90 daily-contiguous observations, sigmas 1..90. P95 = 86."""
    return [
        _make_rv(str(i + 1), _DEFAULT_START + timedelta(days=i),
                 venue=venue, instrument=instrument)
        for i in range(90)
    ]


# ===== Schema =====


def test_schema_version_value():
    assert EVENT_DECISION_SCHEMA_VERSION == "event_decision.v0"


# ===== Direction logic =====


def test_non_event_is_flat():
    """current sigma 50 < P95 86 -> not an event -> FLAT regardless of return."""
    history = _build_history()
    current = _make_rv("50", _AFTER_HISTORY, mean_log_return="0.01")
    result = evaluate_event(history, current, as_of=_AFTER_HISTORY)
    assert result.is_event is False
    assert result.direction is EventDirection.FLAT
    # pre_event_log_return still recorded even on a non-event day
    assert result.pre_event_log_return == Decimal("0.01") * Decimal("24")


def test_event_positive_return_is_long():
    history = _build_history()
    current = _make_rv("100", _AFTER_HISTORY, mean_log_return="0.001")
    result = evaluate_event(history, current, as_of=_AFTER_HISTORY)
    assert result.is_event is True
    assert result.direction is EventDirection.LONG
    assert result.pre_event_log_return == Decimal("0.024")


def test_event_negative_return_is_short():
    history = _build_history()
    current = _make_rv("100", _AFTER_HISTORY, mean_log_return="-0.001")
    result = evaluate_event(history, current, as_of=_AFTER_HISTORY)
    assert result.is_event is True
    assert result.direction is EventDirection.SHORT
    assert result.pre_event_log_return == Decimal("-0.024")


def test_event_zero_return_is_flat():
    """Event fires but zero directional signal -> FLAT, event still recorded."""
    history = _build_history()
    current = _make_rv("100", _AFTER_HISTORY, mean_log_return="0")
    result = evaluate_event(history, current, as_of=_AFTER_HISTORY)
    assert result.is_event is True
    assert result.direction is EventDirection.FLAT
    assert result.pre_event_log_return == Decimal("0")


def test_event_at_percentile_does_not_fire():
    """Strict trigger inherited from percentile detector: sigma == P95 (86)
    is not an event, so direction is FLAT even with a strong return."""
    history = _build_history()
    current = _make_rv("86", _AFTER_HISTORY, mean_log_return="0.01")
    result = evaluate_event(history, current, as_of=_AFTER_HISTORY)
    assert result.is_event is False
    assert result.direction is EventDirection.FLAT


# ===== pre_event_log_return derivation =====


def test_pre_event_return_equals_mean_times_count():
    history = _build_history()
    current = _make_rv("100", _AFTER_HISTORY, mean_log_return="0.0005")
    result = evaluate_event(history, current, as_of=_AFTER_HISTORY)
    # 0.0005 * 24 = 0.012
    assert result.pre_event_log_return == Decimal("0.012")


# ===== Lineage =====


def test_output_carries_lineage():
    history = _build_history()
    current = _make_rv("100", _AFTER_HISTORY, mean_log_return="0.001")
    as_of = _AFTER_HISTORY + timedelta(hours=2)
    result = evaluate_event(history, current, as_of=as_of)
    assert result.venue == "binance"
    assert result.instrument == "BTCUSDT"
    assert result.as_of == as_of
    assert result.current_sigma == Decimal("100")
    assert result.percentile_value == Decimal("86")
    assert result.realised_vol_schema_version == REALISED_VOL_SCHEMA_VERSION
    assert result.percentile_event_schema_version == PERCENTILE_EVENT_SCHEMA_VERSION
    assert result.schema_version == EVENT_DECISION_SCHEMA_VERSION
    assert isinstance(result, EventDecision)


# ===== Validation passthrough =====


def test_invalid_history_length_raises():
    """Structural validation is delegated to the percentile detector."""
    history = _build_history()[:89]
    current = _make_rv("100", _DEFAULT_START + timedelta(days=89),
                       mean_log_return="0.001")
    with pytest.raises(PercentileEventError, match="exactly 90"):
        evaluate_event(history, current, as_of=current.window_end)


def test_current_not_after_history_raises():
    history = _build_history()
    # current.window_end == last history window_end
    current = _make_rv("100", history[-1].window_end, mean_log_return="0.001")
    with pytest.raises(PercentileEventError, match="strictly after"):
        evaluate_event(history, current, as_of=current.window_end)


def test_instrument_mismatch_raises():
    history = _build_history(instrument="BTCUSDT")
    current = _make_rv("100", _AFTER_HISTORY, mean_log_return="0.001",
                       instrument="ETHUSDT")
    with pytest.raises(PercentileEventError, match="single instrument"):
        evaluate_event(history, current, as_of=_AFTER_HISTORY)
