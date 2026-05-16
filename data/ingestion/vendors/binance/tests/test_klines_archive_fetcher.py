"""Unit tests for BinanceKlinesArchiveFetcher.

Synthetic in-memory archives; no network. Tests:
  - Window filtering
  - Multi-month enumeration
  - Header sniffing (with and without header row)
  - Sort + dedupe on open_time
  - 404 handling returns None (cached via .notfound marker)
  - Validation: timezone-aware, end > start, non-empty symbol
"""
from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from data.ingestion.vendors.binance.klines_archive_fetcher import (
    BinanceKlinesArchiveFetcher,
    _months_overlapping,
    _sort_and_dedupe,
)
from data.ingestion.vendors.binance.kline import BinanceKline
from data.ingestion.vendors.binance.trade_fetcher import (
    PermanentFetcherError,
    TransientFetcherError,
)


def _make_kline_csv_row(
    *, open_time_ms: int, open_p: str, high: str, low: str, close: str,
    volume: str, quote_volume: str, trade_count: int,
) -> list[str]:
    """Build one CSV row in Binance futures klines format."""
    close_time_ms = open_time_ms + 86_400_000 - 1  # 1d bar
    return [
        str(open_time_ms), open_p, high, low, close, volume,
        str(close_time_ms), quote_volume, str(trade_count),
        volume, quote_volume, "0",
    ]


def _make_archive_bytes(rows: list[list[str]], *, with_header: bool = False) -> bytes:
    """Build a ZIP archive containing a single CSV with the given rows."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        csv_lines = []
        if with_header:
            csv_lines.append(
                "open_time,open,high,low,close,volume,close_time,"
                "quote_volume,count,taker_buy_volume,"
                "taker_buy_quote_volume,ignore"
            )
        for row in rows:
            csv_lines.append(",".join(row))
        zf.writestr("BTCUSDT-1d-2026-03.csv", "\n".join(csv_lines))
    return buf.getvalue()


class _StubTransport:
    """Records GET calls; returns canned responses by URL."""

    def __init__(self, responses: dict[str, bytes | Exception]):
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str, *, timeout_seconds: float) -> bytes:
        self.calls.append(url)
        resp = self.responses.get(url)
        if isinstance(resp, Exception):
            raise resp
        if resp is None:
            raise PermanentFetcherError(f"404 not found: {url}")
        return resp


def _ts_ms(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp() * 1000)


class TestConstruction:
    def test_default_interval(self):
        f = BinanceKlinesArchiveFetcher()
        assert f.interval == "1d"

    def test_custom_interval(self, tmp_path):
        f = BinanceKlinesArchiveFetcher(interval="1h", cache_dir=tmp_path)
        assert f.interval == "1h"

    def test_empty_interval_raises(self):
        with pytest.raises(ValueError, match="interval must be non-empty"):
            BinanceKlinesArchiveFetcher(interval="")

    def test_default_cache_dir_includes_interval(self):
        f = BinanceKlinesArchiveFetcher(interval="5m")
        assert "5m" in str(f.cache_dir)


class TestValidation:
    def test_empty_symbol_raises(self, tmp_path):
        f = BinanceKlinesArchiveFetcher(cache_dir=tmp_path)
        with pytest.raises(PermanentFetcherError, match="non-empty"):
            f.fetch_window(
                "",
                datetime(2026, 3, 15, tzinfo=timezone.utc),
                datetime(2026, 3, 16, tzinfo=timezone.utc),
            )

    def test_naive_start_raises(self, tmp_path):
        f = BinanceKlinesArchiveFetcher(cache_dir=tmp_path)
        with pytest.raises(PermanentFetcherError, match="timezone-aware"):
            f.fetch_window(
                "BTCUSDT",
                datetime(2026, 3, 15),  # naive
                datetime(2026, 3, 16, tzinfo=timezone.utc),
            )

    def test_end_before_start_raises(self, tmp_path):
        f = BinanceKlinesArchiveFetcher(cache_dir=tmp_path)
        with pytest.raises(PermanentFetcherError, match="strictly after"):
            f.fetch_window(
                "BTCUSDT",
                datetime(2026, 3, 16, tzinfo=timezone.utc),
                datetime(2026, 3, 15, tzinfo=timezone.utc),
            )


class TestWindowFiltering:
    def test_filters_to_window(self, tmp_path):
        rows = [
            _make_kline_csv_row(
                open_time_ms=_ts_ms(2026, 3, day),
                open_p="100", high="110", low="90", close="105",
                volume="1000", quote_volume="105000", trade_count=500,
            )
            for day in range(1, 32)
        ]
        archive = _make_archive_bytes(rows)
        url = (
            "https://data.binance.vision/data/futures/um/monthly/klines/"
            "BTCUSDT/1d/BTCUSDT-1d-2026-03.zip"
        )
        f = BinanceKlinesArchiveFetcher(
            cache_dir=tmp_path,
            transport=_StubTransport({url: archive}),
        )
        result = f.fetch_window(
            "BTCUSDT",
            datetime(2026, 3, 15, tzinfo=timezone.utc),
            datetime(2026, 3, 18, tzinfo=timezone.utc),
        )
        # Open times 15, 16, 17 are in [15, 18). Day 18 is not.
        assert len(result) == 3
        assert result[0].open_time.day == 15
        assert result[1].open_time.day == 16
        assert result[2].open_time.day == 17

    def test_returns_empty_when_no_klines_in_window(self, tmp_path):
        rows = [
            _make_kline_csv_row(
                open_time_ms=_ts_ms(2026, 3, day),
                open_p="100", high="110", low="90", close="105",
                volume="1000", quote_volume="105000", trade_count=500,
            )
            for day in (1, 2, 3)
        ]
        archive = _make_archive_bytes(rows)
        url = (
            "https://data.binance.vision/data/futures/um/monthly/klines/"
            "BTCUSDT/1d/BTCUSDT-1d-2026-03.zip"
        )
        f = BinanceKlinesArchiveFetcher(
            cache_dir=tmp_path,
            transport=_StubTransport({url: archive}),
        )
        # Window covers days 20-25; archive only has 1-3
        result = f.fetch_window(
            "BTCUSDT",
            datetime(2026, 3, 20, tzinfo=timezone.utc),
            datetime(2026, 3, 25, tzinfo=timezone.utc),
        )
        assert result == []


class TestHeaderSniffing:
    def test_with_header_row(self, tmp_path):
        rows = [
            _make_kline_csv_row(
                open_time_ms=_ts_ms(2026, 3, 15),
                open_p="100", high="110", low="90", close="105",
                volume="1000", quote_volume="105000", trade_count=500,
            ),
        ]
        archive = _make_archive_bytes(rows, with_header=True)
        url = (
            "https://data.binance.vision/data/futures/um/monthly/klines/"
            "BTCUSDT/1d/BTCUSDT-1d-2026-03.zip"
        )
        f = BinanceKlinesArchiveFetcher(
            cache_dir=tmp_path,
            transport=_StubTransport({url: archive}),
        )
        result = f.fetch_window(
            "BTCUSDT",
            datetime(2026, 3, 15, tzinfo=timezone.utc),
            datetime(2026, 3, 16, tzinfo=timezone.utc),
        )
        assert len(result) == 1
        assert result[0].close == Decimal("105")

    def test_without_header_row(self, tmp_path):
        rows = [
            _make_kline_csv_row(
                open_time_ms=_ts_ms(2026, 3, 15),
                open_p="100", high="110", low="90", close="105",
                volume="1000", quote_volume="105000", trade_count=500,
            ),
        ]
        archive = _make_archive_bytes(rows, with_header=False)
        url = (
            "https://data.binance.vision/data/futures/um/monthly/klines/"
            "BTCUSDT/1d/BTCUSDT-1d-2026-03.zip"
        )
        f = BinanceKlinesArchiveFetcher(
            cache_dir=tmp_path,
            transport=_StubTransport({url: archive}),
        )
        result = f.fetch_window(
            "BTCUSDT",
            datetime(2026, 3, 15, tzinfo=timezone.utc),
            datetime(2026, 3, 16, tzinfo=timezone.utc),
        )
        assert len(result) == 1


class TestMultiMonth:
    def test_enumerates_months(self):
        months = list(_months_overlapping(
            datetime(2026, 3, 15, tzinfo=timezone.utc),
            datetime(2026, 5, 5, tzinfo=timezone.utc),
        ))
        assert months == [(2026, 3), (2026, 4), (2026, 5)]

    def test_year_boundary(self):
        months = list(_months_overlapping(
            datetime(2025, 12, 15, tzinfo=timezone.utc),
            datetime(2026, 1, 15, tzinfo=timezone.utc),
        ))
        assert months == [(2025, 12), (2026, 1)]

    def test_single_month(self):
        months = list(_months_overlapping(
            datetime(2026, 3, 1, tzinfo=timezone.utc),
            datetime(2026, 3, 31, tzinfo=timezone.utc),
        ))
        assert months == [(2026, 3)]


class TestDedupeAndSort:
    def test_sort_by_open_time(self):
        ingested = datetime(2026, 5, 16, tzinfo=timezone.utc)
        k1 = BinanceKline(
            venue="binance", instrument="BTCUSDT", interval="1d",
            open_time=datetime(2026, 3, 17, tzinfo=timezone.utc),
            open=Decimal("100"), high=Decimal("110"), low=Decimal("90"),
            close=Decimal("105"), volume=Decimal("1000"),
            quote_volume=Decimal("105000"), trade_count=500,
            taker_buy_volume=Decimal("500"),
            taker_buy_quote_volume=Decimal("52500"),
            ingested_at=ingested,
        )
        k2 = BinanceKline(
            venue="binance", instrument="BTCUSDT", interval="1d",
            open_time=datetime(2026, 3, 15, tzinfo=timezone.utc),
            open=Decimal("100"), high=Decimal("110"), low=Decimal("90"),
            close=Decimal("105"), volume=Decimal("1000"),
            quote_volume=Decimal("105000"), trade_count=500,
            taker_buy_volume=Decimal("500"),
            taker_buy_quote_volume=Decimal("52500"),
            ingested_at=ingested,
        )
        result = _sort_and_dedupe([k1, k2])
        assert result[0].open_time.day == 15
        assert result[1].open_time.day == 17

    def test_dedupe_identical(self):
        ingested = datetime(2026, 5, 16, tzinfo=timezone.utc)
        k = BinanceKline(
            venue="binance", instrument="BTCUSDT", interval="1d",
            open_time=datetime(2026, 3, 15, tzinfo=timezone.utc),
            open=Decimal("100"), high=Decimal("110"), low=Decimal("90"),
            close=Decimal("105"), volume=Decimal("1000"),
            quote_volume=Decimal("105000"), trade_count=500,
            taker_buy_volume=Decimal("500"),
            taker_buy_quote_volume=Decimal("52500"),
            ingested_at=ingested,
        )
        result = _sort_and_dedupe([k, k, k])
        assert len(result) == 1

    def test_dedupe_conflict_raises(self):
        ingested = datetime(2026, 5, 16, tzinfo=timezone.utc)
        k1 = BinanceKline(
            venue="binance", instrument="BTCUSDT", interval="1d",
            open_time=datetime(2026, 3, 15, tzinfo=timezone.utc),
            open=Decimal("100"), high=Decimal("110"), low=Decimal("90"),
            close=Decimal("105"), volume=Decimal("1000"),
            quote_volume=Decimal("105000"), trade_count=500,
            taker_buy_volume=Decimal("500"),
            taker_buy_quote_volume=Decimal("52500"),
            ingested_at=ingested,
        )
        k2 = BinanceKline(
            venue="binance", instrument="BTCUSDT", interval="1d",
            open_time=datetime(2026, 3, 15, tzinfo=timezone.utc),
            open=Decimal("100"), high=Decimal("110"), low=Decimal("90"),
            close=Decimal("999"),  # different close
            volume=Decimal("1000"),
            quote_volume=Decimal("105000"), trade_count=500,
            taker_buy_volume=Decimal("500"),
            taker_buy_quote_volume=Decimal("52500"),
            ingested_at=ingested,
        )
        with pytest.raises(PermanentFetcherError, match="different content"):
            _sort_and_dedupe([k1, k2])


class TestArchiveAbsent:
    def test_404_returns_empty(self, tmp_path):
        """When the archive 404s, fetch_window should return [] and
        cache the absence so subsequent calls don't retry."""
        f = BinanceKlinesArchiveFetcher(
            cache_dir=tmp_path,
            transport=_StubTransport({}),  # all URLs 404
        )
        result = f.fetch_window(
            "FAKESYMBOL",
            datetime(2026, 3, 15, tzinfo=timezone.utc),
            datetime(2026, 3, 16, tzinfo=timezone.utc),
        )
        assert result == []
        # Subsequent call should hit cached .notfound marker (no HTTP)
        result2 = f.fetch_window(
            "FAKESYMBOL",
            datetime(2026, 3, 15, tzinfo=timezone.utc),
            datetime(2026, 3, 16, tzinfo=timezone.utc),
        )
        assert result2 == []
