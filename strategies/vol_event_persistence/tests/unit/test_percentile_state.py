"""Unit tests for evaluate_percentile_event.

Percentile method is nearest-rank (no interpolation), so the P95 of a
known distribution can be hand-checked exactly. For sigmas 1..90 sorted
ascending, rank = ceil(0.95 * 90) = 86, index = 85, percentile = 86.

Trigger is strict: current > percentile fires; current == percentile
does not.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from strategies.vol_event_persistence.config import pre_lock
from strategies.vol_event_persistence.signal.percentile_state import (
    PERCENTILE_EVENT_SCHEMA_VERSION,
    PercentileEvent,
    PercentileEventError,
    evaluate_percentile_event,
)
from strategies.vol_event_persistence.signal.realised_vol import RealisedVol

_DEFAULT_START = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def _make_rv(
    sigma: str,
    window_end: datetime,
    *,
    venue: str = "binance",
    instrument: str = "BTCUSDT",
) -> RealisedVol:
    """Build a RealisedVol carrying a controlled sigma and window_end.
    Fields the percentile detector does not read (mean/stdev log return)
    are placeholders.
    """
    return RealisedVol(
        venue=venue,
        instrument=instrument,
        window_start=window_end - timedelta(hours=24),
        window_end=window_end,
        window_size=25,
        return_count=24,
        mean_log_return=Decimal("0"),
        stdev_log_return=Decimal("0"),
        sigma_24h_annualised=Decimal(sigma),
        schema_version="realised_vol.v0",
    )


def _build_history(
    sigmas,
    *,
    start: datetime = _DEFAULT_START,
    venue: str = "binance",
    instrument: str = "BTCUSDT",
):
    """Build a daily-contiguous, strictly-ascending history."""
    return [
        _make_rv(s, start + timedelta(days=i), venue=venue, instrument=instrument)
        for i, s in enumerate(sigmas)
    ]


# sigmas "1".."90"; nearest-rank P95 = the 86th smallest = "86"
_SIGMAS_1_TO_90 = [str(i) for i in range(1, 91)]
_AFTER_HISTORY = _DEFAULT_START + timedelta(days=90)


# ===== Drift guard =====


def test_constants_match_pre_lock():
    assert pre_lock.PERCENTILE_LOOKBACK_DAYS == 90
    assert pre_lock.PERCENTILE_THRESHOLD == Decimal("0.95")
    assert pre_lock.PERCENTILE_EXCLUDES_CURRENT is True


def test_schema_version_value():
    assert PERCENTILE_EVENT_SCHEMA_VERSION == "percentile_event.v0"


# ===== Length validation =====


def test_exactly_90_accepted():
    history = _build_history(_SIGMAS_1_TO_90)
    current = _make_rv("100", _AFTER_HISTORY)
    result = evaluate_percentile_event(history, current, as_of=_AFTER_HISTORY)
    assert isinstance(result, PercentileEvent)
    assert result.lookback_size == 90


def test_89_rejected():
    history = _build_history(_SIGMAS_1_TO_90[:89])
    current = _make_rv("100", _DEFAULT_START + timedelta(days=89))
    with pytest.raises(PercentileEventError, match="exactly 90"):
        evaluate_percentile_event(history, current, as_of=current.window_end)


def test_91_rejected():
    history = _build_history(_SIGMAS_1_TO_90 + ["91"])
    current = _make_rv("100", _DEFAULT_START + timedelta(days=91))
    with pytest.raises(PercentileEventError, match="exactly 90"):
        evaluate_percentile_event(history, current, as_of=current.window_end)


# ===== Timestamp-order validation =====


def test_current_equal_to_last_history_rejected():
    history = _build_history(_SIGMAS_1_TO_90)
    # current.window_end == history[-1].window_end
    last_end = history[-1].window_end
    current = _make_rv("100", last_end)
    with pytest.raises(PercentileEventError, match="strictly after"):
        evaluate_percentile_event(history, current, as_of=last_end)


def test_current_inside_history_rejected():
    history = _build_history(_SIGMAS_1_TO_90)
    mid_end = history[45].window_end
    current = _make_rv("100", mid_end)
    with pytest.raises(PercentileEventError, match="strictly after"):
        evaluate_percentile_event(history, current, as_of=mid_end)


def test_unsorted_history_rejected():
    history = _build_history(_SIGMAS_1_TO_90)
    # Swap two adjacent window_end timestamps to break strict ascending
    swapped = list(history)
    swapped[10], swapped[11] = swapped[11], swapped[10]
    current = _make_rv("100", _AFTER_HISTORY)
    with pytest.raises(PercentileEventError, match="strictly ascending"):
        evaluate_percentile_event(swapped, current, as_of=_AFTER_HISTORY)


# ===== Identity validation =====


def test_multiple_instruments_rejected():
    history = _build_history(_SIGMAS_1_TO_90)
    current = _make_rv("100", _AFTER_HISTORY, instrument="ETHUSDT")
    with pytest.raises(PercentileEventError, match="single instrument"):
        evaluate_percentile_event(history, current, as_of=_AFTER_HISTORY)


def test_multiple_venues_rejected():
    history = _build_history(_SIGMAS_1_TO_90)
    current = _make_rv("100", _AFTER_HISTORY, venue="okx")
    with pytest.raises(PercentileEventError, match="single venue"):
        evaluate_percentile_event(history, current, as_of=_AFTER_HISTORY)


def test_history_internal_instrument_mismatch_rejected():
    history = _build_history(_SIGMAS_1_TO_90)
    bad = list(history)
    bad[30] = _make_rv(_SIGMAS_1_TO_90[30], bad[30].window_end, instrument="SOLUSDT")
    current = _make_rv("100", _AFTER_HISTORY)
    with pytest.raises(PercentileEventError, match="single instrument"):
        evaluate_percentile_event(bad, current, as_of=_AFTER_HISTORY)


# ===== Nearest-rank percentile value =====


def test_p95_nearest_rank_value():
    """sigmas 1..90 -> P95 = 86th smallest = 86. No interpolation."""
    history = _build_history(_SIGMAS_1_TO_90)
    current = _make_rv("100", _AFTER_HISTORY)
    result = evaluate_percentile_event(history, current, as_of=_AFTER_HISTORY)
    assert result.percentile_value == Decimal("86")
    assert result.percentile_threshold == Decimal("0.95")


def test_p95_value_independent_of_input_order():
    """Percentile is on sorted sigmas; history order (beyond ascending
    timestamps) does not change the value."""
    # Reverse the sigma assignment but keep timestamps ascending.
    reversed_sigmas = [str(i) for i in range(90, 0, -1)]
    history = _build_history(reversed_sigmas)
    current = _make_rv("100", _AFTER_HISTORY)
    result = evaluate_percentile_event(history, current, as_of=_AFTER_HISTORY)
    # Same set of sigmas {1..90}, so P95 is still 86.
    assert result.percentile_value == Decimal("86")


# ===== Strict trigger =====


def test_trigger_fires_above_percentile():
    history = _build_history(_SIGMAS_1_TO_90)  # P95 = 86
    current = _make_rv("86.5", _AFTER_HISTORY)
    result = evaluate_percentile_event(history, current, as_of=_AFTER_HISTORY)
    assert result.is_event is True
    assert result.current_sigma == Decimal("86.5")


def test_trigger_does_not_fire_at_percentile():
    """Strict: current == percentile does NOT fire."""
    history = _build_history(_SIGMAS_1_TO_90)  # P95 = 86
    current = _make_rv("86", _AFTER_HISTORY)
    result = evaluate_percentile_event(history, current, as_of=_AFTER_HISTORY)
    assert result.is_event is False


def test_trigger_does_not_fire_below_percentile():
    history = _build_history(_SIGMAS_1_TO_90)  # P95 = 86
    current = _make_rv("85", _AFTER_HISTORY)
    result = evaluate_percentile_event(history, current, as_of=_AFTER_HISTORY)
    assert result.is_event is False


# ===== Output integrity =====


def test_output_carries_lineage():
    history = _build_history(_SIGMAS_1_TO_90)
    current = _make_rv("100", _AFTER_HISTORY)
    as_of = _AFTER_HISTORY + timedelta(hours=1)
    result = evaluate_percentile_event(history, current, as_of=as_of)
    assert result.venue == "binance"
    assert result.instrument == "BTCUSDT"
    assert result.as_of == as_of
    assert result.lookback_start == history[0].window_end
    assert result.lookback_end == history[-1].window_end
    assert result.lookback_size == 90
    assert result.current_sigma == Decimal("100")
    assert result.schema_version == PERCENTILE_EVENT_SCHEMA_VERSION
