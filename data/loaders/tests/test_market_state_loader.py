"""Unit tests for market_state_loader.

Uses _venue_loaders_override and _funding_loader_override to inject stub
loaders. No network, no filesystem access.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from data.loaders.market_state_loader import (
    HourlyMarketState,
    load_hourly_market_state,
)


# ─── Test helpers ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _StubKline:
    """Minimal kline shape — only the fields the loader reads."""
    open_time: datetime
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


def _make_kline(year: int, month: int, day: int, hour: int, price: str = "50000") -> _StubKline:
    return _StubKline(
        open_time=datetime(year, month, day, hour, tzinfo=timezone.utc),
        high=Decimal(price) + Decimal("100"),
        low=Decimal(price) - Decimal("100"),
        close=Decimal(price),
        volume=Decimal("123.456"),
    )


def _stub_loader_returning(klines: list[_StubKline]):
    """Return a loader function that ignores args and returns the given klines
    as a {open_time → kline} dict."""
    def _loader(asset, start, end):
        return {k.open_time: k for k in klines}
    return _loader


def _stub_loader_returning_subset(klines_by_asset: dict[str, list[_StubKline]]):
    """Return a loader that returns different klines depending on asset."""
    def _loader(asset, start, end):
        klines = klines_by_asset.get(asset, [])
        return {k.open_time: k for k in klines}
    return _loader


def _stub_empty_funding(asset, start, end):
    return {}


# ─── Tests ──────────────────────────────────────────────────────────────

class TestValidation:
    def test_naive_start_raises(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            load_hourly_market_state(
                datetime(2024, 1, 1),
                datetime(2024, 1, 2, tzinfo=timezone.utc),
            )

    def test_naive_end_raises(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            load_hourly_market_state(
                datetime(2024, 1, 1, tzinfo=timezone.utc),
                datetime(2024, 1, 2),
            )

    def test_end_before_start_raises(self):
        with pytest.raises(ValueError, match="must be after"):
            load_hourly_market_state(
                datetime(2024, 1, 2, tzinfo=timezone.utc),
                datetime(2024, 1, 1, tzinfo=timezone.utc),
            )


class TestSingleLeg:
    def test_one_venue_one_asset_one_type(self):
        klines = [
            _make_kline(2024, 1, 1, h, price=str(50000 + h))
            for h in range(3)
        ]
        loader = _stub_loader_returning(klines)
        venue_loaders = {"binance": {"perp": loader}}

        result = load_hourly_market_state(
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 1, 1, 5, tzinfo=timezone.utc),
            assets=["BTCUSDT"],
            venues=["binance"],
            instrument_types=["perp"],
            _venue_loaders_override=venue_loaders,
            _funding_loader_override=_stub_empty_funding,
        )

        assert len(result) == 3
        assert result[0].timestamp == datetime(2024, 1, 1, 0, tzinfo=timezone.utc)
        assert result[0].prices["binance_BTCUSDT_perp_close"] == Decimal("50000")
        assert result[2].prices["binance_BTCUSDT_perp_close"] == Decimal("50002")
        # Funding should be None for every row (empty funding stub)
        assert all(r.funding["binance_BTCUSDT_funding"] is None for r in result)


class TestMultiLegInnerJoin:
    def test_two_legs_full_overlap(self):
        """Both legs have data at the same timestamps — output has all rows."""
        binance_klines = [_make_kline(2024, 1, 1, h, price="50000") for h in range(3)]
        okx_klines = [_make_kline(2024, 1, 1, h, price="50050") for h in range(3)]

        venue_loaders = {
            "binance": {"perp": _stub_loader_returning(binance_klines)},
            "okx":     {"perp": _stub_loader_returning(okx_klines)},
        }

        result = load_hourly_market_state(
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 1, 1, 5, tzinfo=timezone.utc),
            assets=["BTCUSDT"],
            venues=["binance", "okx"],
            instrument_types=["perp"],
            _venue_loaders_override=venue_loaders,
            _funding_loader_override=_stub_empty_funding,
        )

        assert len(result) == 3
        assert result[0].prices["binance_BTCUSDT_perp_close"] == Decimal("50000")
        assert result[0].prices["okx_BTCUSDT_perp_close"] == Decimal("50050")

    def test_inner_join_drops_unmatched_timestamps(self):
        """Binance has hours 0-4, OKX has hours 2-6. Only 2,3,4 are common."""
        binance_klines = [_make_kline(2024, 1, 1, h) for h in range(5)]
        okx_klines = [_make_kline(2024, 1, 1, h) for h in range(2, 7)]

        venue_loaders = {
            "binance": {"perp": _stub_loader_returning(binance_klines)},
            "okx":     {"perp": _stub_loader_returning(okx_klines)},
        }

        result = load_hourly_market_state(
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 1, 1, 10, tzinfo=timezone.utc),
            assets=["BTCUSDT"],
            venues=["binance", "okx"],
            instrument_types=["perp"],
            _venue_loaders_override=venue_loaders,
            _funding_loader_override=_stub_empty_funding,
        )

        # Only hours 2, 3, 4 should remain (intersection)
        assert len(result) == 3
        hours = [r.timestamp.hour for r in result]
        assert hours == [2, 3, 4]


class TestFunding:
    def test_funding_attached_when_present(self):
        klines = [_make_kline(2024, 1, 1, h) for h in range(3)]
        loader = _stub_loader_returning(klines)
        venue_loaders = {"binance": {"perp": loader}}

        # Stub funding: only hour 1 has data
        def funding_loader(asset, start, end):
            if asset == "BTCUSDT":
                return {datetime(2024, 1, 1, 1, tzinfo=timezone.utc): Decimal("0.0001")}
            return {}

        result = load_hourly_market_state(
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 1, 1, 5, tzinfo=timezone.utc),
            assets=["BTCUSDT"],
            venues=["binance"],
            instrument_types=["perp"],
            _venue_loaders_override=venue_loaders,
            _funding_loader_override=funding_loader,
        )

        assert len(result) == 3
        # Hour 0: no funding
        assert result[0].funding["binance_BTCUSDT_funding"] is None
        # Hour 1: funding present
        assert result[1].funding["binance_BTCUSDT_funding"] == Decimal("0.0001")
        # Hour 2: no funding
        assert result[2].funding["binance_BTCUSDT_funding"] is None

    def test_missing_funding_doesnt_gate_inclusion(self):
        """Even with no funding cache, rows should still be returned."""
        klines = [_make_kline(2024, 1, 1, h) for h in range(3)]
        loader = _stub_loader_returning(klines)
        venue_loaders = {"binance": {"perp": loader}}

        result = load_hourly_market_state(
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 1, 1, 5, tzinfo=timezone.utc),
            assets=["BTCUSDT"],
            venues=["binance"],
            instrument_types=["perp"],
            _venue_loaders_override=venue_loaders,
            _funding_loader_override=_stub_empty_funding,
        )

        assert len(result) == 3


class TestMultiAsset:
    def test_two_assets_inner_joined(self):
        """BTC and ETH legs, both via Binance perp."""
        btc_klines = [_make_kline(2024, 1, 1, h, price="50000") for h in range(3)]
        eth_klines = [_make_kline(2024, 1, 1, h, price="3000") for h in range(3)]

        loader = _stub_loader_returning_subset({
            "BTCUSDT": btc_klines,
            "ETHUSDT": eth_klines,
        })
        venue_loaders = {"binance": {"perp": loader}}

        result = load_hourly_market_state(
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 1, 1, 5, tzinfo=timezone.utc),
            assets=["BTCUSDT", "ETHUSDT"],
            venues=["binance"],
            instrument_types=["perp"],
            _venue_loaders_override=venue_loaders,
            _funding_loader_override=_stub_empty_funding,
        )

        assert len(result) == 3
        assert result[0].prices["binance_BTCUSDT_perp_close"] == Decimal("50000")
        assert result[0].prices["binance_ETHUSDT_perp_close"] == Decimal("3000")

    def test_one_asset_missing_drops_to_empty(self):
        """If ETH has no data at any timestamp common with BTC, result is empty."""
        btc_klines = [_make_kline(2024, 1, 1, h) for h in range(3)]
        eth_klines = [_make_kline(2024, 2, 1, h) for h in range(3)]  # different month

        loader = _stub_loader_returning_subset({
            "BTCUSDT": btc_klines,
            "ETHUSDT": eth_klines,
        })
        venue_loaders = {"binance": {"perp": loader}}

        result = load_hourly_market_state(
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 3, 1, tzinfo=timezone.utc),
            assets=["BTCUSDT", "ETHUSDT"],
            venues=["binance"],
            instrument_types=["perp"],
            _venue_loaders_override=venue_loaders,
            _funding_loader_override=_stub_empty_funding,
        )

        # No common timestamps → empty result
        assert result == []


class TestEmptyResults:
    def test_empty_loader_returns_empty(self):
        """All loaders return empty → result is empty."""
        empty_loader = _stub_loader_returning([])
        venue_loaders = {"binance": {"perp": empty_loader}}

        result = load_hourly_market_state(
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 1, 1, 5, tzinfo=timezone.utc),
            assets=["BTCUSDT"],
            venues=["binance"],
            instrument_types=["perp"],
            _venue_loaders_override=venue_loaders,
            _funding_loader_override=_stub_empty_funding,
        )
        assert result == []

    def test_no_matching_venue_returns_empty(self):
        """Requested venue has no loaders configured → empty result."""
        venue_loaders = {"binance": {"perp": _stub_loader_returning([
            _make_kline(2024, 1, 1, 0)
        ])}}

        result = load_hourly_market_state(
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 1, 1, 5, tzinfo=timezone.utc),
            assets=["BTCUSDT"],
            venues=["nonexistent_venue"],
            instrument_types=["perp"],
            _venue_loaders_override=venue_loaders,
            _funding_loader_override=_stub_empty_funding,
        )
        assert result == []


class TestOutputStructure:
    def test_output_is_sorted_chronologically(self):
        """Output records are sorted by timestamp regardless of input order."""
        # Construct out-of-order klines
        klines = [
            _make_kline(2024, 1, 1, 2),
            _make_kline(2024, 1, 1, 0),
            _make_kline(2024, 1, 1, 4),
            _make_kline(2024, 1, 1, 1),
            _make_kline(2024, 1, 1, 3),
        ]
        loader = _stub_loader_returning(klines)
        venue_loaders = {"binance": {"perp": loader}}

        result = load_hourly_market_state(
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 1, 1, 10, tzinfo=timezone.utc),
            assets=["BTCUSDT"],
            venues=["binance"],
            instrument_types=["perp"],
            _venue_loaders_override=venue_loaders,
            _funding_loader_override=_stub_empty_funding,
        )

        hours = [r.timestamp.hour for r in result]
        assert hours == sorted(hours)
        assert hours == [0, 1, 2, 3, 4]

    def test_each_record_has_high_low_volume(self):
        klines = [_make_kline(2024, 1, 1, h, price="50000") for h in range(2)]
        loader = _stub_loader_returning(klines)
        venue_loaders = {"binance": {"perp": loader}}

        result = load_hourly_market_state(
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 1, 1, 5, tzinfo=timezone.utc),
            assets=["BTCUSDT"],
            venues=["binance"],
            instrument_types=["perp"],
            _venue_loaders_override=venue_loaders,
            _funding_loader_override=_stub_empty_funding,
        )

        for r in result:
            assert "binance_BTCUSDT_perp_high" in r.highs
            assert "binance_BTCUSDT_perp_low" in r.lows
            assert "binance_BTCUSDT_perp_volume" in r.volumes
            assert r.highs["binance_BTCUSDT_perp_high"] == Decimal("50100")
            assert r.lows["binance_BTCUSDT_perp_low"] == Decimal("49900")
            assert r.volumes["binance_BTCUSDT_perp_volume"] == Decimal("123.456")
