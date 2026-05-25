"""Unit tests for compute_realised_vol on a synthetic 25-bar window.

Two layers of correctness checks per the spec §5 reproducibility property:

  1. Exact-Decimal regression: each statistic is quantised to 20 decimal
     places and compared against a baked value. If the implementation
     drifts, this fails loudly. Updating the baked value must be a
     conscious commit decision, not silent absorption.

  2. Float-reference cross-check: the same statistic is recomputed in
     float using math.log + statistics.stdev, and the Decimal output
     must match within 1e-12. This catches the rare case where the
     baked Decimal happens to be wrong but consistent across runs
     (e.g. if the math itself is wrong in a way both implementations
     would share — impossible here, but the principle is to never
     trust a single reference).

Validation rules per spec §2 are exercised one rule per test.
"""
from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterable

import pytest

from data.ingestion.vendors.binance.kline import BinanceKline
from strategies.vol_event_persistence.config import pre_lock
from strategies.vol_event_persistence.signal.realised_vol import (
    REALISED_VOL_SCHEMA_VERSION,
    RealisedVol,
    RealisedVolError,
    compute_realised_vol,
)

# ===== Fixture helpers =====

_DEFAULT_START = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def _make_kline(
    close: str,
    open_time: datetime,
    *,
    venue: str = "binance",
    instrument: str = "BTCUSDT",
    interval: str = "1h",
) -> BinanceKline:
    """Minimal kline builder. The estimator only reads venue, instrument,
    interval, open_time, and close. The other required fields (volume,
    trade_count, etc.) are set to zero/dummy values just to satisfy
    BinanceKline's constructor.
    """
    c = Decimal(close)
    zero = Decimal("0")
    return BinanceKline(
        venue=venue,
        instrument=instrument,
        interval=interval,
        open_time=open_time,
        open=c,
        high=c,
        low=c,
        close=c,
        volume=zero,
        quote_volume=zero,
        trade_count=0,
        taker_buy_volume=zero,
        taker_buy_quote_volume=zero,
    )


def _build_window(
    closes: Iterable[str],
    *,
    start: datetime = _DEFAULT_START,
    venue: str = "binance",
    instrument: str = "BTCUSDT",
    interval: str = "1h",
) -> list[BinanceKline]:
    return [
        _make_kline(c, start + timedelta(hours=i),
                    venue=venue, instrument=instrument, interval=interval)
        for i, c in enumerate(closes)
    ]


# ===== Inline synthetic fixture (25 closes, hand-picked, two-digit scale) =====

_SYNTHETIC_25 = [
    "100.00", "100.50", "100.30", "100.80", "101.20",
    "100.90", "101.50", "101.10", "100.70", "101.30",
    "101.80", "102.20", "101.90", "102.50", "102.10",
    "102.80", "103.20", "102.90", "103.50", "103.10",
    "103.80", "104.20", "103.90", "104.50", "104.30",
]

# Baked values, quantised to 20 decimal places, computed by the
# implementation at commit time. Any change to these requires an explicit
# commit. See module docstring for the two-layer correctness check.
_SYNTHETIC_EXPECTED_MEAN = Decimal("0.00175421566744314142")
_SYNTHETIC_EXPECTED_STDEV = Decimal("0.00431751591944520267")
_SYNTHETIC_EXPECTED_SIGMA = Decimal("0.40409734834621932165")

_QUANT = Decimal("1e-20")


def _q20(x: Decimal) -> Decimal:
    """Quantise to 20 decimal places for regression comparison."""
    return x.quantize(_QUANT)


# ===== Drift guard: module literals must match config.pre_lock =====


def test_constants_match_pre_lock():
    """If config.pre_lock changes a value, this test catches the drift.

    Per spec §8 these constants are frozen. If they need to change,
    v1 dies and v2 starts with a new pre-lock. There is no amendment
    path; this test exists to force that discipline at commit time.
    """
    # spec §2: 24h window of hourly returns
    assert pre_lock.VOL_WINDOW_HOURS == 24
    assert pre_lock.VOL_RETURN_BAR == "1h"
    # 25 bars yields 24 returns: spec §3.1.2 of section_a_probe_spec_v1.md
    # (locked at "25 bars -> 24 returns" per operator decision).
    # If VOL_WINDOW_HOURS changes, this assertion must also change.
    assert pre_lock.VOL_ANNUALISATION_FACTOR == 24 * 365


def test_schema_version_attached():
    result = compute_realised_vol(_build_window(_SYNTHETIC_25))
    assert result.schema_version == REALISED_VOL_SCHEMA_VERSION
    assert REALISED_VOL_SCHEMA_VERSION == "realised_vol.v0"


# ===== Math correctness =====


def test_flat_prices_produce_zero_sigma():
    """All-equal closes: zero log returns, zero stdev, zero sigma."""
    window = _build_window(["100.00"] * 25)
    result = compute_realised_vol(window)
    assert result.mean_log_return == Decimal("0")
    assert result.stdev_log_return == Decimal("0")
    assert result.sigma_24h_annualised == Decimal("0")
    assert result.window_size == 25
    assert result.return_count == 24


def test_synthetic_window_produces_baked_sigma():
    """Exact-Decimal regression against baked values."""
    result = compute_realised_vol(_build_window(_SYNTHETIC_25))
    assert _q20(result.mean_log_return) == _SYNTHETIC_EXPECTED_MEAN
    assert _q20(result.stdev_log_return) == _SYNTHETIC_EXPECTED_STDEV
    assert _q20(result.sigma_24h_annualised) == _SYNTHETIC_EXPECTED_SIGMA


def test_synthetic_window_matches_float_reference():
    """Cross-check the Decimal result against math.log + statistics.stdev."""
    result = compute_realised_vol(_build_window(_SYNTHETIC_25))

    float_returns = [
        math.log(float(_SYNTHETIC_25[i]) / float(_SYNTHETIC_25[i - 1]))
        for i in range(1, 25)
    ]
    float_mean = statistics.mean(float_returns)
    float_stdev = statistics.stdev(float_returns)
    float_sigma = float_stdev * math.sqrt(24 * 365)

    assert abs(float(result.mean_log_return) - float_mean) < 1e-12
    assert abs(float(result.stdev_log_return) - float_stdev) < 1e-12
    assert abs(float(result.sigma_24h_annualised) - float_sigma) < 1e-12


def test_output_carries_window_bounds():
    start = datetime(2026, 3, 15, 0, 0, 0, tzinfo=timezone.utc)
    result = compute_realised_vol(_build_window(_SYNTHETIC_25, start=start))
    assert result.window_start == start
    assert result.window_end == start + timedelta(hours=24)
    assert result.window_size == 25
    assert result.return_count == 24


def test_output_carries_venue_and_instrument():
    result = compute_realised_vol(
        _build_window(_SYNTHETIC_25, venue="binance", instrument="ETHUSDT")
    )
    assert result.venue == "binance"
    assert result.instrument == "ETHUSDT"


# ===== Validation =====


def test_wrong_window_size_raises():
    with pytest.raises(RealisedVolError, match="exactly 25 bars"):
        compute_realised_vol(_build_window(_SYNTHETIC_25[:20]))
    with pytest.raises(RealisedVolError, match="exactly 25 bars"):
        compute_realised_vol(_build_window(_SYNTHETIC_25 + ["104.50"]))


def test_mixed_venues_raises():
    window = _build_window(_SYNTHETIC_25)
    bad = window[:24] + [
        _make_kline(_SYNTHETIC_25[24],
                    window[-1].open_time, venue="okx")
    ]
    with pytest.raises(RealisedVolError, match="single venue"):
        compute_realised_vol(bad)


def test_mixed_instruments_raises():
    window = _build_window(_SYNTHETIC_25)
    bad = window[:24] + [
        _make_kline(_SYNTHETIC_25[24],
                    window[-1].open_time, instrument="ETHUSDT")
    ]
    with pytest.raises(RealisedVolError, match="single instrument"):
        compute_realised_vol(bad)


def test_non_1h_interval_raises():
    window = _build_window(_SYNTHETIC_25)
    bad = window[:24] + [
        _make_kline(_SYNTHETIC_25[24],
                    window[-1].open_time, interval="5m")
    ]
    with pytest.raises(RealisedVolError, match="'1h' bars"):
        compute_realised_vol(bad)


def test_non_ascending_open_time_raises():
    """Two bars with the same open_time."""
    window = _build_window(_SYNTHETIC_25)
    duplicated_time = window[12].open_time
    bad = list(window)
    bad[13] = _make_kline(_SYNTHETIC_25[13], duplicated_time)
    with pytest.raises(RealisedVolError, match="strictly ascending"):
        compute_realised_vol(bad)


def test_gap_in_window_raises():
    """One bar is shifted forward by 2 hours instead of 1."""
    window = _build_window(_SYNTHETIC_25)
    gap_time = window[13].open_time + timedelta(hours=1)
    bad = list(window)
    bad[13] = _make_kline(_SYNTHETIC_25[13], gap_time)
    with pytest.raises(RealisedVolError, match="contiguous"):
        compute_realised_vol(bad)


def test_zero_close_raises():
    closes = ["100.00"] * 12 + ["0.00"] + ["100.00"] * 12
    with pytest.raises(RealisedVolError, match="strictly positive"):
        compute_realised_vol(_build_window(closes))


def test_negative_close_raises():
    closes = ["100.00"] * 12 + ["-1.00"] + ["100.00"] * 12
    with pytest.raises(RealisedVolError, match="strictly positive"):
        compute_realised_vol(_build_window(closes))
