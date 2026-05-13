"""Unit tests for BinanceSpotArchiveTradeFetcher.

No-network tests: URL construction + input validation. Real-data
fetching is exercised manually via scripts/refresh_a2_basis_fixture.py.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from data.ingestion.vendors.binance.spot_archive_trade_fetcher import (
    BinanceSpotArchiveTradeFetcher,
    _build_spot_archive_url,
)
from data.ingestion.vendors.binance.trade_fetcher import (
    PermanentFetcherError,
)


class TestUrlConstruction:
    def test_solusdt_march_2024(self):
        url = _build_spot_archive_url("SOLUSDT", 2024, 3)
        assert url == (
            "https://data.binance.vision/data/spot/monthly/aggTrades/"
            "SOLUSDT/SOLUSDT-aggTrades-2024-03.zip"
        )

    def test_ethusdt_december_2023(self):
        url = _build_spot_archive_url("ETHUSDT", 2023, 12)
        assert url == (
            "https://data.binance.vision/data/spot/monthly/aggTrades/"
            "ETHUSDT/ETHUSDT-aggTrades-2023-12.zip"
        )

    def test_url_zero_pads_single_digit_month(self):
        url = _build_spot_archive_url("BTCUSDT", 2024, 3)
        assert "2024-03" in url
        assert "2024-3" not in url

    def test_url_uses_spot_path_not_futures(self):
        url = _build_spot_archive_url("SOLUSDT", 2024, 3)
        assert "/data/spot/" in url
        assert "/data/futures/" not in url


class TestInputValidation:
    def test_empty_symbol_raises(self):
        fetcher = BinanceSpotArchiveTradeFetcher()
        with pytest.raises(PermanentFetcherError, match="symbol"):
            fetcher.fetch_window(
                "",
                datetime(2024, 3, 15, tzinfo=timezone.utc),
                datetime(2024, 3, 16, tzinfo=timezone.utc),
            )

    def test_naive_start_raises(self):
        fetcher = BinanceSpotArchiveTradeFetcher()
        with pytest.raises(PermanentFetcherError, match="timezone-aware"):
            fetcher.fetch_window(
                "SOLUSDT",
                datetime(2024, 3, 15),
                datetime(2024, 3, 16, tzinfo=timezone.utc),
            )

    def test_naive_end_raises(self):
        fetcher = BinanceSpotArchiveTradeFetcher()
        with pytest.raises(PermanentFetcherError, match="timezone-aware"):
            fetcher.fetch_window(
                "SOLUSDT",
                datetime(2024, 3, 15, tzinfo=timezone.utc),
                datetime(2024, 3, 16),
            )

    def test_end_before_start_raises(self):
        fetcher = BinanceSpotArchiveTradeFetcher()
        with pytest.raises(PermanentFetcherError, match="strictly after"):
            fetcher.fetch_window(
                "SOLUSDT",
                datetime(2024, 3, 16, tzinfo=timezone.utc),
                datetime(2024, 3, 15, tzinfo=timezone.utc),
            )

    def test_end_equal_to_start_raises(self):
        fetcher = BinanceSpotArchiveTradeFetcher()
        ts = datetime(2024, 3, 15, tzinfo=timezone.utc)
        with pytest.raises(PermanentFetcherError):
            fetcher.fetch_window("SOLUSDT", ts, ts)


class TestFetcherStructure:
    def test_default_cache_dir_is_spot_specific(self):
        fetcher = BinanceSpotArchiveTradeFetcher()
        assert "spot" in str(fetcher.cache_dir).lower()
        assert str(fetcher.cache_dir) != str(
            # Should not collide with perp default
            "artifacts/cache/binance_archive"
        )

    def test_instantiates_with_no_args(self):
        fetcher = BinanceSpotArchiveTradeFetcher()
        assert fetcher.timeout_seconds > 0
        assert fetcher.min_interval_seconds >= 0
