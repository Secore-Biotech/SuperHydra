"""Unit tests for the probe gates (§5 statistical, §6 economic).

Sufficient-sample gate series require ~910+ day spans (OOS 20% must be
>= 6 months), so the builders generate many events across a long timeline.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from strategies.vol_event_persistence.attribution.forward_returns import (
    ForwardReturn,
)
from strategies.vol_event_persistence.signal.evaluate import EventDirection
from strategies.vol_event_persistence.gates import (
    GateStatus,
    evaluate_economic_gate,
    evaluate_gates,
    evaluate_statistical_gate,
    event_sharpe,
    mean,
    median,
    sample_stdev,
    _event_time,
    _oos_rolling_failures,
    _split_date,
)

_UTC = timezone.utc
_BASE = datetime(2026, 1, 1, tzinfo=_UTC)


def _fr(event_time, horizon=1, gross="40", funding="0", exec_="10",
        net=None) -> ForwardReturn:
    g, f, e = Decimal(gross), Decimal(funding), Decimal(exec_)
    n = Decimal(net) if net is not None else g + f - e
    return ForwardReturn(
        venue="binance", instrument="BTCUSDT",
        event_id=f"binance:BTCUSDT:{event_time.isoformat()}",
        direction=EventDirection.LONG, horizon_days=horizon,
        entry_price=Decimal("100"), exit_price=Decimal("101"),
        realised_funding_bps=f, gross_bps=g, funding_pnl_bps=f,
        execution_cost_bps=e, net_bps=n,
        cost_model_schema_version="attribution_cost_model.v0",
        schema_version="forward_return.v0")


def _series(horizon=1, train_n=130, oos_n=35, train_span=768,
            oos_span=191, nets=("25", "35"), gross=("35", "45")):
    """Sufficient-sample passing series unless overridden."""
    out = []
    for i in range(train_n):
        t = _BASE + timedelta(days=int(i * train_span / train_n))
        out.append(_fr(t, horizon, gross=gross[i % 2], net=nets[i % 2]))
    for i in range(oos_n):
        t = _BASE + timedelta(days=train_span + int(i * oos_span / max(oos_n - 1, 1)))
        out.append(_fr(t, horizon, gross=gross[i % 2], net=nets[i % 2]))
    return out


# ===== statistics =====


def test_mean_median():
    assert mean([Decimal("2"), Decimal("4")]) == Decimal("3")
    assert median([Decimal("1"), Decimal("2"), Decimal("3")]) == Decimal("2")
    assert median([Decimal("1"), Decimal("3")]) == Decimal("2")


def test_sample_stdev_nminus1():
    # values 2,4,4,4,5,5,7,9 -> sample stdev 2.13809...
    xs = [Decimal(x) for x in (2, 4, 4, 4, 5, 5, 7, 9)]
    sd = sample_stdev(xs)
    assert sd.quantize(Decimal("1e-4")) == Decimal("2.1381")


def test_event_sharpe_basic():
    xs = [Decimal("25"), Decimal("35")]  # mean 30, stdev ~7.07
    s = event_sharpe(xs)
    assert s.quantize(Decimal("1e-2")) == Decimal("4.24")


def test_event_sharpe_undefined_cases():
    assert event_sharpe([Decimal("5")]) is None           # n<2
    assert event_sharpe([Decimal("5"), Decimal("5")]) is None  # zero dispersion


# ===== helpers =====


def test_event_time_parses_event_id():
    t = _BASE + timedelta(days=10)
    fr = _fr(t)
    assert _event_time(fr) == t


def test_split_date_at_80pct():
    times = [_BASE, _BASE + timedelta(days=100)]
    assert _split_date(times) == _BASE + timedelta(days=80)


# ===== statistical gate: sample sufficiency =====


def test_stat_insufficient_train_events():
    s = _series(train_n=50)  # < 100 train
    r = evaluate_statistical_gate(s)
    assert r.status is GateStatus.INSUFFICIENT_SAMPLE
    assert any("train events" in x for x in r.reasons)


def test_stat_insufficient_oos_events():
    s = _series(oos_n=10)  # < 30 OOS
    r = evaluate_statistical_gate(s)
    assert r.status is GateStatus.INSUFFICIENT_SAMPLE
    assert any("OOS events" in x for x in r.reasons)


def test_stat_insufficient_oos_span():
    # compress OOS into < 182 days
    s = _series(oos_span=60)
    r = evaluate_statistical_gate(s)
    assert r.status is GateStatus.INSUFFICIENT_SAMPLE
    assert any("OOS span" in x for x in r.reasons)


# ===== statistical gate: pass / fail =====


def test_stat_gate_pass():
    s = _series()
    r = evaluate_statistical_gate(s)
    assert r.status is GateStatus.PASS, r.reasons
    assert r.train_events >= 100
    assert r.oos_events >= 30
    assert r.oos_span_days >= 182
    assert r.train_sharpe > Decimal("2.0")
    assert r.oos_sharpe > Decimal("1.5")
    assert r.oos_rolling_failures == 0


def test_stat_gate_fail_low_sharpe():
    # mean ~5, stdev ~10 -> Sharpe ~0.5, sample still sufficient
    s = _series(nets=("-5", "15"))
    r = evaluate_statistical_gate(s)
    assert r.status is GateStatus.FAIL
    assert any("Sharpe" in x for x in r.reasons)


# ===== rolling-failure unit =====


def test_rolling_failures_negative_window():
    # 3 events in one 30-day window, all negative -> 1 failure
    times = [_BASE + timedelta(days=d) for d in (1, 5, 10)]
    oos = [_fr(t, net="-20") for t in times]
    assert _oos_rolling_failures(oos, times) == 1


def test_rolling_ignores_small_windows():
    # only 2 events in the window -> ignored despite being negative
    times = [_BASE + timedelta(days=1), _BASE + timedelta(days=5)]
    oos = [_fr(t, net="-20") for t in times]
    assert _oos_rolling_failures(oos, times) == 0


def test_rolling_positive_window_no_failure():
    times = [_BASE + timedelta(days=d) for d in (1, 5, 10, 15)]
    oos = [_fr(t, net="30") if i % 2 == 0 else _fr(t, net="20")
           for i, t in enumerate(times)]
    assert _oos_rolling_failures(oos, times) == 0


# ===== economic gate =====


def test_econ_gate_pass():
    s = _series()
    r = evaluate_economic_gate(s)
    assert r.status is GateStatus.PASS, r.reasons
    # odd total event count -> mean/median aren't exactly round; assert the
    # gate contract (values clear their §6 thresholds) rather than hand-arith.
    assert r.mean_net_bps > Decimal("20")
    assert r.median_net_bps > Decimal("0")
    assert r.win_rate == Decimal("1")
    assert r.cost_coverage > Decimal("2.5")
    assert r.final_3mo_net_bps > 0


def test_econ_fail_low_mean():
    s = _series(nets=("5", "9"), gross=("15", "19"))  # mean net 7 < 20
    r = evaluate_economic_gate(s)
    assert r.status is GateStatus.FAIL
    assert any("mean net" in x for x in r.reasons)


def test_econ_fail_low_coverage():
    # gross barely above cost: gross 11/13 (mean 12), cost 10 -> coverage 1.2
    s = _series(nets=("25", "35"), gross=("11", "13"))
    r = evaluate_economic_gate(s)
    assert r.status is GateStatus.FAIL
    assert any("cost coverage" in x for x in r.reasons)


def test_econ_cost_coverage_funding_drag_increases_denominator():
    # funding -5 (drag) -> denom = 10 - min(0,-5) = 15
    s = [_fr(_BASE + timedelta(days=i), gross="60", funding="-5")
         for i in range(10)]
    r = evaluate_economic_gate(s)
    # mean gross 60 / mean cost 15 = 4.0
    assert r.cost_coverage == Decimal("60") / Decimal("15")


def test_econ_cost_coverage_funding_credit_does_not_reduce_denominator():
    # funding +5 (credit) -> denom = 10 - min(0,+5) = 10 (unchanged)
    s = [_fr(_BASE + timedelta(days=i), gross="60", funding="5")
         for i in range(10)]
    r = evaluate_economic_gate(s)
    assert r.cost_coverage == Decimal("60") / Decimal("10")


def test_econ_empty_is_insufficient():
    r = evaluate_economic_gate([])
    assert r.status is GateStatus.INSUFFICIENT_SAMPLE


# ===== per-horizon orchestration =====


def test_probe_passes_if_one_horizon_clears():
    # horizon 1 passes; horizon 3 fails on low sharpe; horizon 7 absent
    good = _series(horizon=1)
    bad = _series(horizon=3, nets=("-5", "15"))
    result = evaluate_gates(good + bad)
    assert result.probe_passed is True
    by_h = {hr.horizon_days: hr for hr in result.per_horizon}
    assert by_h[1].passed is True
    assert by_h[3].passed is False
    assert by_h[7].statistical.status is GateStatus.INSUFFICIENT_SAMPLE


def test_probe_fails_if_no_horizon_clears():
    bad = _series(horizon=1, nets=("-5", "15"))
    result = evaluate_gates(bad)
    assert result.probe_passed is False


def test_gates_are_per_horizon_independent():
    s1 = _series(horizon=1)
    s7 = _series(horizon=7)
    result = evaluate_gates(s1 + s7)
    by_h = {hr.horizon_days: hr for hr in result.per_horizon}
    assert by_h[1].passed and by_h[7].passed
    assert by_h[3].statistical.status is GateStatus.INSUFFICIENT_SAMPLE
