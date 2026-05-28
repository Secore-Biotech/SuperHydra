"""Unit tests for the probe harness.

The fixture parser and report wiring are sandbox-testable; the only I/O is
load_fixture (file read), exercised via tmp_path. Gate PASS requires huge
samples, so the run_probe structural test asserts report shape + wiring,
not a passing verdict.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from data.ingestion.vendors.binance.kline import BinanceKline
from data.ingestion.vendors.binance.funding_rate import FundingRate
from strategies.vol_event_persistence.runner.harness import (
    FIXTURE_SCHEMA_VERSION,
    HARNESS_SCHEMA_VERSION,
    HarnessError,
    load_fixture,
    main,
    parse_fixture,
    run_probe,
)

_UTC = timezone.utc
_REPO_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures" / "example_vol_event_fixture.json"
)


def _kline_dict(open_time: str, instrument="BTCUSDT", close="42050.0"):
    return {
        "venue": "binance", "instrument": instrument, "interval": "1h",
        "open_time": open_time, "open": "42000.0", "high": "42100.0",
        "low": "41900.0", "close": close, "volume": "1.0",
        "quote_volume": "1.0", "trade_count": 1,
        "taker_buy_base_volume": "0.5", "taker_buy_quote_volume": "1.0",
    }


def _funding_dict(funding_time: str, instrument="BTCUSDT"):
    return {
        "venue": "binance", "instrument": instrument,
        "funding_time": funding_time, "funding_rate": "0.0001",
        "mark_price": "42050.0",
    }


def _fixture_obj(klines=None, funding=None):
    return {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "klines": klines if klines is not None else [
            _kline_dict("2024-01-01T00:00:00+00:00")],
        "funding": funding if funding is not None else [
            _funding_dict("2024-01-01T08:00:00+00:00")],
    }


# ===== parse_fixture =====


def test_parse_fixture_valid():
    klines, funding = parse_fixture(_fixture_obj())
    assert len(klines) == 1 and len(funding) == 1
    assert isinstance(klines[0], BinanceKline)
    assert isinstance(funding[0], FundingRate)


def test_parse_kline_maps_taker_buy_base_to_taker_buy_volume():
    klines, _ = parse_fixture(_fixture_obj())
    # fixture field taker_buy_base_volume=0.5 -> canonical taker_buy_volume
    assert klines[0].taker_buy_volume == Decimal("0.5")


def test_parse_fixture_wrong_schema_version():
    obj = _fixture_obj()
    obj["schema_version"] = "vol_event_fixture.v0"
    with pytest.raises(HarnessError, match="schema_version"):
        parse_fixture(obj)


def test_parse_fixture_missing_arrays():
    with pytest.raises(HarnessError, match="klines"):
        parse_fixture({"schema_version": FIXTURE_SCHEMA_VERSION})


def test_parse_kline_missing_field():
    bad = _kline_dict("2024-01-01T00:00:00+00:00")
    del bad["close"]
    with pytest.raises(HarnessError, match="kline missing field"):
        parse_fixture(_fixture_obj(klines=[bad]))


def test_parse_funding_missing_field():
    bad = _funding_dict("2024-01-01T08:00:00+00:00")
    del bad["funding_rate"]
    with pytest.raises(HarnessError, match="funding missing field"):
        parse_fixture(_fixture_obj(funding=[bad]))


def test_parse_funding_optional_mark_price():
    f = _funding_dict("2024-01-01T08:00:00+00:00")
    del f["mark_price"]
    _, funding = parse_fixture(_fixture_obj(funding=[f]))
    assert funding[0].mark_price is None


# ===== shipped example fixture =====


def test_example_fixture_parses():
    assert _REPO_FIXTURE.exists(), f"missing {_REPO_FIXTURE}"
    klines, funding = load_fixture(_REPO_FIXTURE)
    assert len(klines) >= 1
    assert all(isinstance(k, BinanceKline) for k in klines)


# ===== load_fixture I/O errors =====


def test_load_fixture_missing_file(tmp_path):
    with pytest.raises(HarnessError, match="cannot read fixture"):
        load_fixture(tmp_path / "nope.json")


def test_load_fixture_bad_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    with pytest.raises(HarnessError, match="not valid JSON"):
        load_fixture(p)


# ===== run_probe structural wiring (with an engineered spike) =====


def _spike_close(i: int, spike_start: int) -> str:
    j = i - spike_start
    if 0 <= j < 25:
        return f"{100 + 0.5 * j + (8 if j % 2 == 1 else 0):.4f}"
    return f"{100 + (i % 2) * 0.01:.4f}"


def _spike_klines_and_funding(instrument: str):
    base = datetime(2026, 1, 1, tzinfo=_UTC)
    anchor = base + timedelta(days=95)
    total_hours = int(((anchor + timedelta(days=8)) - (anchor - timedelta(days=95)))
                      .total_seconds() // 3600)
    start = anchor - timedelta(days=95)
    spike_start_idx = int((anchor - timedelta(hours=25) - start).total_seconds() // 3600)

    klines = []
    for i in range(total_hours):
        c = Decimal(_spike_close(i, spike_start_idx))
        ot = start + timedelta(hours=i)
        klines.append(BinanceKline(
            venue="binance", instrument=instrument, interval="1h", open_time=ot,
            open=c, high=c, low=c, close=c, volume=Decimal("1"),
            quote_volume=Decimal("1"), trade_count=1,
            taker_buy_volume=Decimal("0"), taker_buy_quote_volume=Decimal("0")))
    last = start + timedelta(hours=total_hours - 1)
    funding = []
    t = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while t <= last + timedelta(hours=8):
        for hh in (0, 8, 16):
            ft = t + timedelta(hours=hh)
            if start <= ft <= last:
                funding.append(FundingRate(
                    venue="binance", instrument=instrument, funding_time=ft,
                    funding_rate=Decimal("0.0001")))
        t = t + timedelta(days=1)
    return klines, funding


def test_run_probe_report_shape():
    klines, funding = _spike_klines_and_funding("BTCUSDT")
    report = run_probe(klines, funding)
    for key in ("schema_version", "symbols", "events_by_horizon",
                "gate_verdict_by_horizon", "probe_pass", "skip_summary",
                "data_quality_status"):
        assert key in report, f"missing report key {key}"
    assert report["schema_version"] == HARNESS_SCHEMA_VERSION
    assert report["symbols"] == ["BTCUSDT"]
    assert isinstance(report["probe_pass"], bool)
    # verdict present for each locked horizon
    assert set(report["gate_verdict_by_horizon"].keys()) == {"1", "3", "7"}
    # the engineered spike produced events
    assert sum(int(v) for v in report["events_by_horizon"].values()) >= 1
    assert "BTCUSDT" in report["skip_summary"]
    assert "BTCUSDT" in report["data_quality_status"]


def test_run_probe_multi_instrument():
    kb, fb = _spike_klines_and_funding("BTCUSDT")
    ke, fe = _spike_klines_and_funding("ETHUSDT")
    report = run_probe(kb + ke, fb + fe)
    assert report["symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert set(report["skip_summary"].keys()) == {"BTCUSDT", "ETHUSDT"}


# ===== CLI =====


def test_main_success(tmp_path, capsys):
    p = tmp_path / "fix.json"
    p.write_text(json.dumps(_fixture_obj()))
    rc = main(["--fixture", str(p)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["schema_version"] == HARNESS_SCHEMA_VERSION
    assert out["fixture_path"] == str(p)
    assert "probe_pass" in out


def test_main_pretty(tmp_path, capsys):
    p = tmp_path / "fix.json"
    p.write_text(json.dumps(_fixture_obj()))
    rc = main(["--fixture", str(p), "--pretty"])
    assert rc == 0
    assert "\n  " in capsys.readouterr().out  # indented


def test_main_bad_fixture_returns_2(tmp_path, capsys):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    rc = main(["--fixture", str(p)])
    assert rc == 2
    err = json.loads(capsys.readouterr().err)
    assert "error" in err
