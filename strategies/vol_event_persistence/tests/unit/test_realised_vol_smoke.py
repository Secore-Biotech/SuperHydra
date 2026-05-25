"""Smoke test for compute_realised_vol on a BTC-scale 25-bar window.

Distinct from test_realised_vol.py: this test uses 5-digit prices in
the realistic BTCUSDT range to exercise Decimal precision behaviour at
real-world scale. Same two-layer correctness pattern (baked Decimal +
float reference cross-check).

The closes below are constructed at realistic BTCUSDT scale and with
realistic intra-day move magnitudes (~0.05%-0.4% hourly). They are NOT
from any specific historical window and should not be treated as
ground-truth market data — the purpose is precision-at-scale, not
backtest signal.
"""
from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterable

from data.ingestion.vendors.binance.kline import BinanceKline
from strategies.vol_event_persistence.signal.realised_vol import (
    compute_realised_vol,
)

# ===== Inline BTC-scale fixture (25 closes) =====

_BTC_SCALE_25 = [
    "65000.00", "65120.50", "64980.30", "65200.80", "65180.40",
    "65050.10", "65300.20", "65250.90", "65100.40", "65400.10",
    "65550.30", "65480.20", "65620.80", "65750.40", "65680.10",
    "65900.20", "65820.30", "66050.40", "65980.10", "66150.20",
    "66280.40", "66120.30", "66350.10", "66480.50", "66400.20",
]

# Baked values quantised to 20 decimal places. See test_realised_vol.py
# module docstring for the two-layer correctness contract.
_BTC_EXPECTED_MEAN = Decimal("0.00088803327626698417")
_BTC_EXPECTED_STDEV = Decimal("0.00230472584493565173")
_BTC_EXPECTED_SIGMA = Decimal("0.21571051965528649000")

_QUANT = Decimal("1e-20")


def _make_kline(close: str, open_time: datetime) -> BinanceKline:
    """Minimal kline builder; estimator reads only close + identity fields.
    Other required BinanceKline fields take zero/dummy values."""
    c = Decimal(close)
    zero = Decimal("0")
    return BinanceKline(
        venue="binance",
        instrument="BTCUSDT",
        interval="1h",
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


def _build_window(closes: Iterable[str]) -> list[BinanceKline]:
    start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    return [_make_kline(c, start + timedelta(hours=i)) for i, c in enumerate(closes)]


def _q20(x: Decimal) -> Decimal:
    return x.quantize(_QUANT)


def test_btc_scale_window_produces_baked_sigma():
    """Exact-Decimal regression at 5-digit price scale."""
    result = compute_realised_vol(_build_window(_BTC_SCALE_25))
    assert _q20(result.mean_log_return) == _BTC_EXPECTED_MEAN
    assert _q20(result.stdev_log_return) == _BTC_EXPECTED_STDEV
    assert _q20(result.sigma_24h_annualised) == _BTC_EXPECTED_SIGMA


def test_btc_scale_window_matches_float_reference():
    """Decimal output must agree with float reference to 1e-12 at this scale."""
    result = compute_realised_vol(_build_window(_BTC_SCALE_25))

    float_returns = [
        math.log(float(_BTC_SCALE_25[i]) / float(_BTC_SCALE_25[i - 1]))
        for i in range(1, 25)
    ]
    float_mean = statistics.mean(float_returns)
    float_stdev = statistics.stdev(float_returns)
    float_sigma = float_stdev * math.sqrt(24 * 365)

    assert abs(float(result.mean_log_return) - float_mean) < 1e-12
    assert abs(float(result.stdev_log_return) - float_stdev) < 1e-12
    assert abs(float(result.sigma_24h_annualised) - float_sigma) < 1e-12


def test_btc_scale_sigma_in_plausible_range():
    """Sanity check: σ for this constructed 24h window lands in a
    plausible annualised-vol range. Constructed moves are small, so
    σ should be roughly 0.1–0.5 annualised."""
    result = compute_realised_vol(_build_window(_BTC_SCALE_25))
    assert Decimal("0.1") < result.sigma_24h_annualised < Decimal("0.5"), (
        f"sigma {result.sigma_24h_annualised} outside plausible range "
        f"for the constructed fixture; either the fixture or the math "
        f"has changed."
    )
