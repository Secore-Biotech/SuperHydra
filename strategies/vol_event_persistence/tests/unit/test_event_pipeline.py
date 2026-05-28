"""Unit + integration tests for the probe event pipeline.

Stage helpers (build_vol_series, detect_events, build_forward_returns) are
tested with controlled inputs; one integration test exercises run_pipeline
end-to-end on an engineered volatility spike. The outcome-independence of
skips is verified structurally: skip classification is asserted from data
presence alone, never from the resulting return.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from data.ingestion.vendors.binance.funding_rate import FundingRate
from data.ingestion.vendors.binance.kline import BinanceKline
from strategies.vol_event_persistence.signal.evaluate import (
    EventDecision,
    EventDirection,
)
from strategies.vol_event_persistence.runner.event_pipeline import (
    DATA_QUALITY_SUSPECT_THRESHOLD,
    EventPipelineError,
    build_forward_returns,
    build_vol_series,
    daily_anchors,
    detect_events,
    expected_funding_times,
    run_pipeline,
    sigma_window_open_times,
    _sum_funding_bps,
)

_UTC = timezone.utc
_V = "binance"
_I = "BTCUSDT"


def _t(days=0, hours=0, base=datetime(2026, 1, 1, tzinfo=_UTC)) -> datetime:
    return base + timedelta(days=days, hours=hours)


def _kline(open_time: datetime, close: str) -> BinanceKline:
    c = Decimal(close)
    return BinanceKline(
        venue=_V, instrument=_I, interval="1h", open_time=open_time,
        open=c, high=c, low=c, close=c, volume=Decimal("1"),
        quote_volume=Decimal("1"), trade_count=1,
        taker_buy_volume=Decimal("0"), taker_buy_quote_volume=Decimal("0"),
    )


def _funding(funding_time: datetime, rate: str) -> FundingRate:
    return FundingRate(venue=_V, instrument=_I, funding_time=funding_time,
                       funding_rate=Decimal(rate))


def _decision(as_of: datetime, direction: EventDirection,
              is_event: bool = True) -> EventDecision:
    return EventDecision(
        venue=_V, instrument=_I, as_of=as_of,
        current_sigma=Decimal("1.0"), percentile_value=Decimal("0.5"),
        is_event=is_event, pre_event_log_return=Decimal("0.05"),
        direction=direction,
        realised_vol_schema_version="realised_vol.v0",
        percentile_event_schema_version="percentile_event.v0",
        schema_version="event_decision.v0",
    )


# ===== time helpers =====


def test_sigma_window_25_bars_ending_at_anchor_minus_1h():
    a = _t(days=5)
    times = sigma_window_open_times(a)
    assert len(times) == 25
    assert times == sorted(times)  # ascending
    assert times[-1] == a - timedelta(hours=1)
    assert times[0] == a - timedelta(hours=25)


def test_expected_funding_times_per_horizon():
    a = _t(days=10)
    assert expected_funding_times(a, 1) == [
        a + timedelta(hours=8), a + timedelta(hours=16), a + timedelta(hours=24)]
    assert len(expected_funding_times(a, 3)) == 9
    assert len(expected_funding_times(a, 7)) == 21
    # last is exactly the close instant
    assert expected_funding_times(a, 7)[-1] == a + timedelta(days=7)


def test_daily_anchors_range_and_spacing():
    anchors = daily_anchors(_t(days=0), _t(days=10))
    assert all(x.hour == 0 and x.minute == 0 for x in anchors)
    for i in range(1, len(anchors)):
        assert anchors[i] - anchors[i - 1] == timedelta(days=1)
    # need A-25h >= min and A-1h <= max
    assert anchors[0] - timedelta(hours=25) >= _t(days=0)
    assert anchors[-1] - timedelta(hours=1) <= _t(days=10)


def test_daily_anchors_naive_raises():
    with pytest.raises(EventPipelineError, match="timezone-aware"):
        daily_anchors(datetime(2026, 1, 1), _t(days=5))


# ===== _sum_funding_bps =====


def test_sum_funding_all_present():
    a = _t(days=2)
    times = expected_funding_times(a, 1)  # 3 times
    fmap = {t: _funding(t, "0.0001") for t in times}
    total = _sum_funding_bps(fmap, times)
    assert total == Decimal("0.0001") * 3 * Decimal("10000")  # = 3 bps


def test_sum_funding_missing_returns_none():
    a = _t(days=2)
    times = expected_funding_times(a, 1)
    fmap = {t: _funding(t, "0.0001") for t in times[:-1]}  # drop last
    assert _sum_funding_bps(fmap, times) is None


# ===== build_vol_series =====


def _contiguous_hourly(n: int, base: datetime, close_fn) -> list[BinanceKline]:
    return [_kline(base + timedelta(hours=i), close_fn(i)) for i in range(n)]


def test_build_vol_series_contiguous():
    # 49 contiguous bars -> anchors at +24h and +48h both have full windows
    bars = _contiguous_hourly(49, _t(0), lambda i: f"{100 + (i % 2) * 0.01:.2f}")
    vol = build_vol_series(bars, _V, _I)
    assert vol.windows_skipped_gap == 0
    assert vol.windows_valid == vol.windows_total
    assert vol.windows_valid >= 1


def test_build_vol_series_gap_skips():
    bars = _contiguous_hourly(49, _t(0), lambda i: f"{100 + (i % 2) * 0.01:.2f}")
    # the only valid anchor is Jan 3 00:00; its window is [Jan 1 23:00, Jan 2 23:00]
    bars = [b for b in bars if b.open_time != _t(days=1, hours=10)]
    vol = build_vol_series(bars, _V, _I)
    assert vol.windows_skipped_gap >= 1


def test_build_vol_series_rejects_mixed_instrument():
    bars = _contiguous_hourly(30, _t(0), lambda i: "100.00")
    bad = BinanceKline(
        venue=_V, instrument="ETHUSDT", interval="1h", open_time=_t(hours=30),
        open=Decimal("1"), high=Decimal("1"), low=Decimal("1"),
        close=Decimal("1"), volume=Decimal("1"), quote_volume=Decimal("1"),
        trade_count=1, taker_buy_volume=Decimal("0"),
        taker_buy_quote_volume=Decimal("0"))
    with pytest.raises(EventPipelineError, match="homogeneous"):
        build_vol_series(bars + [bad], _V, _I)


# ===== detect_events insufficient history =====


def test_detect_events_insufficient_history_skips():
    # Only a handful of contiguous days -> never 90 prior anchors.
    bars = _contiguous_hourly(24 * 5, _t(0), lambda i: f"{100 + (i % 2) * 0.01:.2f}")
    vol = build_vol_series(bars, _V, _I)
    detect = detect_events(vol, _V, _I)
    assert detect.percentile_events_total == 0
    assert detect.anchors_skipped_insufficient_history == len(vol.sigma_by_anchor)


# ===== build_forward_returns (core skip logic, fully controlled) =====


def _full_klines_and_funding(a: datetime):
    """Entry bar + all three horizon exit bars + full funding for h=7."""
    klines = [_kline(a - timedelta(hours=1), "100")]  # entry
    for h in (1, 3, 7):
        klines.append(_kline(a + timedelta(days=h) - timedelta(hours=1),
                             f"{100 + h}"))
    funding = [_funding(t, "0.0001") for t in expected_funding_times(a, 7)]
    return klines, funding


def test_all_three_horizons_build():
    a = _t(days=100)
    klines, funding = _full_klines_and_funding(a)
    d = _decision(a, EventDirection.LONG)
    r = build_forward_returns([d], klines, funding, _V, _I)
    assert r.event_candidates == 1
    assert r.forward_returns_built == 3
    assert r.events_valid == 1
    assert r.suspect_candidates == 0
    assert {fr.horizon_days for fr in r.forward_returns} == {1, 3, 7}
    assert all(fr.direction is EventDirection.LONG for fr in r.forward_returns)


def test_flat_event_no_trade():
    a = _t(days=100)
    klines, funding = _full_klines_and_funding(a)
    d = _decision(a, EventDirection.FLAT)
    r = build_forward_returns([d], klines, funding, _V, _I)
    assert r.event_candidates == 0
    assert r.events_flat == 1
    assert r.forward_returns_built == 0


def test_missing_entry_skips_all_and_is_suspect():
    a = _t(days=100)
    klines, funding = _full_klines_and_funding(a)
    klines = [k for k in klines if k.open_time != a - timedelta(hours=1)]
    d = _decision(a, EventDirection.LONG)
    r = build_forward_returns([d], klines, funding, _V, _I)
    assert r.skipped_missing_entry == 1
    assert r.forward_returns_built == 0
    assert r.events_valid == 0
    assert r.suspect_candidates == 1  # entry gap is a real gap, not truncation


def test_missing_exit_within_range_is_gap_not_truncation():
    a = _t(days=100)
    klines, funding = _full_klines_and_funding(a)
    # drop the h=3 exit; h=7 exit still present so h=3 is a mid-series gap
    klines = [k for k in klines
              if k.open_time != a + timedelta(days=3) - timedelta(hours=1)]
    d = _decision(a, EventDirection.LONG)
    r = build_forward_returns([d], klines, funding, _V, _I)
    assert r.skipped_missing_exit == 1
    assert r.forward_returns_built == 2  # h=1, h=7
    assert r.events_valid == 1           # >=1 built
    assert r.suspect_candidates == 0     # built>0, not suspect


def test_truncated_horizon_not_suspect():
    a = _t(days=100)
    # only provide entry + h=1 exit; h=3/h=7 exits are beyond series end
    klines = [_kline(a - timedelta(hours=1), "100"),
              _kline(a + timedelta(days=1) - timedelta(hours=1), "101")]
    funding = [_funding(t, "0.0001") for t in expected_funding_times(a, 7)]
    d = _decision(a, EventDirection.LONG)
    r = build_forward_returns([d], klines, funding, _V, _I)
    assert r.forward_returns_built == 1            # h=1
    assert r.skipped_truncated == 2                # h=3, h=7 beyond last bar
    assert r.skipped_missing_exit == 0
    assert r.suspect_candidates == 0               # truncation is expected


def test_funding_gap_skips_horizon():
    a = _t(days=100)
    klines, funding = _full_klines_and_funding(a)
    # drop A+8h funding -> present in all three horizon windows -> all gap
    funding = [f for f in funding if f.funding_time != a + timedelta(hours=8)]
    d = _decision(a, EventDirection.LONG)
    r = build_forward_returns([d], klines, funding, _V, _I)
    assert r.skipped_funding_gap == 3
    assert r.forward_returns_built == 0
    assert r.suspect_candidates == 1


# ===== run_pipeline integration: engineered spike =====


def _spike_close(i: int, spike_start: int) -> str:
    """Low-vol baseline except a high-vol up-drifting 25-bar window."""
    j = i - spike_start
    if 0 <= j < 25:
        # j=0 ~ baseline (small boundary return), then big alternating swings
        return f"{100 + 0.5 * j + (8 if j % 2 == 1 else 0):.4f}"
    return f"{100 + (i % 2) * 0.01:.4f}"


def _build_spike_series(event_anchor: datetime, total_hours: int):
    base = event_anchor - timedelta(days=95)  # plenty of history before anchor
    # spike window is the 25 bars ending at anchor-1h
    spike_start_time = event_anchor - timedelta(hours=25)
    spike_start_idx = int((spike_start_time - base).total_seconds() // 3600)
    klines = [
        _kline(base + timedelta(hours=i), _spike_close(i, spike_start_idx))
        for i in range(total_hours)
    ]
    last_open = base + timedelta(hours=total_hours - 1)
    funding = [_funding(t, "0.0001")
               for t in _all_funding_times(base, last_open)]
    return klines, funding


def _all_funding_times(start: datetime, end: datetime) -> list[datetime]:
    times = []
    t = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while t <= end + timedelta(hours=8):
        for hh in (0, 8, 16):
            ft = t + timedelta(hours=hh)
            if start <= ft <= end:
                times.append(ft)
        t = t + timedelta(days=1)
    return sorted(set(times))


def test_run_pipeline_fires_event_and_builds_returns():
    anchor = datetime(2026, 1, 1, tzinfo=_UTC) + timedelta(days=95)
    # need bars through anchor + 7d for h=7 exit
    total_hours = int(((anchor + timedelta(days=8)) -
                       (anchor - timedelta(days=95))).total_seconds() // 3600)
    klines, funding = _build_spike_series(anchor, total_hours)
    result = run_pipeline(klines, funding, _V, _I)
    s = result.summary
    assert s.bars_total == len(klines)
    assert s.event_candidates >= 1
    assert s.forward_returns_built >= 1
    # counter reconciliation: built + all skips accounted, no negatives
    assert s.sigma_windows_valid + s.sigma_windows_skipped_gap == s.sigma_windows_total
    assert len(result.forward_returns) == s.forward_returns_built
    assert s.data_quality_suspect is False
    # the engineered window drifts up -> at least one LONG decision fired
    assert any(fr.direction is EventDirection.LONG for fr in result.forward_returns)


def test_run_pipeline_suspect_flag_on_funding_gap():
    anchor = datetime(2026, 1, 1, tzinfo=_UTC) + timedelta(days=95)
    total_hours = int(((anchor + timedelta(days=8)) -
                       (anchor - timedelta(days=95))).total_seconds() // 3600)
    klines, funding = _build_spike_series(anchor, total_hours)
    # strip ALL funding -> every candidate's horizons hit funding gaps
    result = run_pipeline(klines, [], _V, _I)
    s = result.summary
    if s.event_candidates > 0:
        assert s.forward_returns_built == 0
        assert s.suspect_skip_rate > DATA_QUALITY_SUSPECT_THRESHOLD
        assert s.data_quality_suspect is True
