"""Unit tests for the Binance Vision archive trade fetcher."""
from __future__ import annotations

import csv
import io
import zipfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from data.ingestion.vendors.binance.archive_trade_fetcher import (
    ARCHIVE_PATH_TEMPLATE,
    BINANCE_VISION_BASE,
    BinanceArchiveTradeFetcher,
    _months_overlapping,
    _sort_and_dedupe,
)
from data.ingestion.vendors.binance.trade import BinanceTrade
from data.ingestion.vendors.binance.trade_fetcher import (
    PermanentFetcherError,
    TransientFetcherError,
)


def _make_archive(
    rows: list[list],
    *,
    csv_name: str = "SOLUSDT-aggTrades-2024-03.csv",
    has_header: bool = False,
    n_csv_files: int = 1,
) -> bytes:
    """Build an in-memory zip with one CSV containing the given rows."""
    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf, lineterminator="\n")
    if has_header:
        writer.writerow([
            "agg_trade_id", "price", "quantity",
            "first_trade_id", "last_trade_id",
            "transact_time", "is_buyer_maker",
        ])
    for row in rows:
        writer.writerow(row)
    csv_text = csv_buf.getvalue()

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(csv_name, csv_text)
        for i in range(1, n_csv_files):
            zf.writestr(f"extra_{i}.csv", "")
    return zip_buf.getvalue()


def _row(
    agg_id: int = 100,
    price: str = "150.00",
    qty: str = "1.5",
    time_ms: int = 1709251200000,  # 2024-03-01T00:00:00Z
    is_buyer_maker: str = "false",
) -> list:
    """Build a CSV row with all 7 columns."""
    return [
        str(agg_id), price, qty,
        str(agg_id), str(agg_id),  # first/last trade ids placeholder
        str(time_ms), is_buyer_maker,
    ]


class FakeTransport:
    """Maps URL → bytes (or Exception). Records every URL."""

    def __init__(self, url_to_response: dict | None = None):
        self.url_to_response = dict(url_to_response or {})
        self.urls: list[str] = []

    def get(self, url: str, *, timeout_seconds: float) -> bytes:
        self.urls.append(url)
        if url not in self.url_to_response:
            raise AssertionError(f"unexpected URL: {url}")
        r = self.url_to_response[url]
        if isinstance(r, Exception):
            raise r
        return r


def _make_fetcher(
    transport: FakeTransport,
    cache_dir: Path,
) -> BinanceArchiveTradeFetcher:
    return BinanceArchiveTradeFetcher(
        transport=transport,
        cache_dir=cache_dir,
        min_interval_seconds=0.0,
        _now=lambda: 0.0,
        _sleep=lambda s: None,
        _utcnow=lambda: datetime(2026, 5, 9, tzinfo=timezone.utc),
    )


def _archive_url(symbol: str, year: int, month: int) -> str:
    path = ARCHIVE_PATH_TEMPLATE.format(symbol=symbol, year=year, month=month)
    return f"{BINANCE_VISION_BASE}{path}"


# ─── _months_overlapping helper ─────────────────────────────────────────


class TestMonthsOverlapping:
    def test_within_one_month(self):
        result = list(_months_overlapping(
            datetime(2024, 3, 1, tzinfo=timezone.utc),
            datetime(2024, 3, 15, tzinfo=timezone.utc),
        ))
        assert result == [(2024, 3)]

    def test_crosses_two_months(self):
        result = list(_months_overlapping(
            datetime(2024, 2, 28, tzinfo=timezone.utc),
            datetime(2024, 3, 5, tzinfo=timezone.utc),
        ))
        assert result == [(2024, 2), (2024, 3)]

    def test_crosses_year(self):
        result = list(_months_overlapping(
            datetime(2024, 12, 15, tzinfo=timezone.utc),
            datetime(2025, 1, 15, tzinfo=timezone.utc),
        ))
        assert result == [(2024, 12), (2025, 1)]

    def test_end_at_first_of_month_excludes_that_month(self):
        result = list(_months_overlapping(
            datetime(2024, 3, 1, tzinfo=timezone.utc),
            datetime(2024, 4, 1, tzinfo=timezone.utc),
        ))
        assert result == [(2024, 3)]


# ─── Single-month happy path ────────────────────────────────────────────


class TestSingleMonth:
    def test_single_month_window_returns_filtered_trades(self, tmp_path):
        rows = [
            _row(agg_id=100, time_ms=1709251200000),  # 00:00:00 (in)
            _row(agg_id=101, time_ms=1709251350000),  # 00:02:30 (in)
            _row(agg_id=102, time_ms=1709251501000),  # 00:05:01 (out)
        ]
        archive = _make_archive(rows)
        url = _archive_url("SOLUSDT", 2024, 3)
        transport = FakeTransport({url: archive})
        fetcher = _make_fetcher(transport, tmp_path)

        result = fetcher.fetch_window(
            "SOLUSDT",
            datetime(2024, 3, 1, tzinfo=timezone.utc),
            datetime(2024, 3, 1, 0, 5, tzinfo=timezone.utc),
        )
        assert [t.id for t in result] == [100, 101]
        assert result[0].price == Decimal("150.00")
        assert result[0].is_buyer_maker is False

    def test_window_endpoint_exclusive(self, tmp_path):
        rows = [
            _row(agg_id=100, time_ms=1709251200000),
            _row(agg_id=101, time_ms=1709251500000),  # exactly 00:05:00
        ]
        archive = _make_archive(rows)
        url = _archive_url("SOLUSDT", 2024, 3)
        transport = FakeTransport({url: archive})
        fetcher = _make_fetcher(transport, tmp_path)

        result = fetcher.fetch_window(
            "SOLUSDT",
            datetime(2024, 3, 1, tzinfo=timezone.utc),
            datetime(2024, 3, 1, 0, 5, tzinfo=timezone.utc),
        )
        assert [t.id for t in result] == [100]


# ─── Multi-month ─────────────────────────────────────────────────────────


class TestMultiMonth:
    def test_window_crosses_two_months(self, tmp_path):
        feb_rows = [
            _row(agg_id=100, time_ms=1709164620000),  # Feb 28 23:57:00
        ]
        mar_rows = [
            _row(agg_id=200, time_ms=1709251260000),  # Mar 01 00:01:00
        ]
        feb_archive = _make_archive(
            feb_rows, csv_name="SOLUSDT-aggTrades-2024-02.csv",
        )
        mar_archive = _make_archive(
            mar_rows, csv_name="SOLUSDT-aggTrades-2024-03.csv",
        )
        transport = FakeTransport({
            _archive_url("SOLUSDT", 2024, 2): feb_archive,
            _archive_url("SOLUSDT", 2024, 3): mar_archive,
        })
        fetcher = _make_fetcher(transport, tmp_path)

        result = fetcher.fetch_window(
            "SOLUSDT",
            datetime(2024, 2, 28, 23, 55, tzinfo=timezone.utc),
            datetime(2024, 3, 1, 0, 5, tzinfo=timezone.utc),
        )
        assert [t.id for t in result] == [100, 200]
        assert len(transport.urls) == 2


# ─── Header detection ───────────────────────────────────────────────────


class TestHeaderDetection:
    def test_header_skipped_when_first_cell_non_numeric(self, tmp_path):
        archive = _make_archive(
            [_row(agg_id=100, time_ms=1709251200000)],
            has_header=True,
        )
        url = _archive_url("SOLUSDT", 2024, 3)
        transport = FakeTransport({url: archive})
        fetcher = _make_fetcher(transport, tmp_path)
        result = fetcher.fetch_window(
            "SOLUSDT",
            datetime(2024, 3, 1, tzinfo=timezone.utc),
            datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
        )
        assert [t.id for t in result] == [100]

    def test_no_header_when_first_cell_numeric(self, tmp_path):
        archive = _make_archive(
            [
                _row(agg_id=100, time_ms=1709251200000),
                _row(agg_id=101, time_ms=1709251260000),
            ],
            has_header=False,
        )
        url = _archive_url("SOLUSDT", 2024, 3)
        transport = FakeTransport({url: archive})
        fetcher = _make_fetcher(transport, tmp_path)
        result = fetcher.fetch_window(
            "SOLUSDT",
            datetime(2024, 3, 1, tzinfo=timezone.utc),
            datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
        )
        assert [t.id for t in result] == [100, 101]


# ─── Cache behavior ─────────────────────────────────────────────────────


class TestCache:
    def test_cache_hit_avoids_http(self, tmp_path):
        cache_file = tmp_path / "SOLUSDT-aggTrades-2024-03.zip"
        archive = _make_archive([_row(agg_id=100, time_ms=1709251200000)])
        cache_file.write_bytes(archive)

        transport = FakeTransport({})
        fetcher = _make_fetcher(transport, tmp_path)
        result = fetcher.fetch_window(
            "SOLUSDT",
            datetime(2024, 3, 1, tzinfo=timezone.utc),
            datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
        )
        assert [t.id for t in result] == [100]
        assert transport.urls == []

    def test_cache_miss_downloads_and_writes(self, tmp_path):
        archive = _make_archive([_row(agg_id=100, time_ms=1709251200000)])
        url = _archive_url("SOLUSDT", 2024, 3)
        transport = FakeTransport({url: archive})
        fetcher = _make_fetcher(transport, tmp_path)

        fetcher.fetch_window(
            "SOLUSDT",
            datetime(2024, 3, 1, tzinfo=timezone.utc),
            datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
        )
        assert len(transport.urls) == 1

        cache_file = tmp_path / "SOLUSDT-aggTrades-2024-03.zip"
        assert cache_file.exists()
        assert cache_file.read_bytes() == archive

        transport.url_to_response = {}
        fetcher.fetch_window(
            "SOLUSDT",
            datetime(2024, 3, 1, tzinfo=timezone.utc),
            datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
        )
        assert len(transport.urls) == 1


# ─── Sort + dedupe ──────────────────────────────────────────────────────


class TestSortAndDedupe:
    def test_sort_by_time_then_id(self, tmp_path):
        rows = [
            _row(agg_id=102, time_ms=1709251260000),
            _row(agg_id=100, time_ms=1709251200000),
            _row(agg_id=101, time_ms=1709251200000),
        ]
        archive = _make_archive(rows)
        url = _archive_url("SOLUSDT", 2024, 3)
        transport = FakeTransport({url: archive})
        fetcher = _make_fetcher(transport, tmp_path)
        result = fetcher.fetch_window(
            "SOLUSDT",
            datetime(2024, 3, 1, tzinfo=timezone.utc),
            datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
        )
        assert [t.id for t in result] == [100, 101, 102]

    def test_dedupe_silent_when_content_matches(self):
        ingested = datetime(2026, 5, 9, tzinfo=timezone.utc)
        t1 = BinanceTrade(
            venue="binance", instrument="SOLUSDT", id=100,
            price=Decimal("150"), qty=Decimal("1"),
            time=datetime(2024, 3, 1, tzinfo=timezone.utc),
            is_buyer_maker=False, ingested_at=ingested,
        )
        t2 = BinanceTrade(
            venue="binance", instrument="SOLUSDT", id=100,
            price=Decimal("150"), qty=Decimal("1"),
            time=datetime(2024, 3, 1, tzinfo=timezone.utc),
            is_buyer_maker=False, ingested_at=ingested,
        )
        result = _sort_and_dedupe([t1, t2])
        assert len(result) == 1
        assert result[0].id == 100

    def test_dedupe_raises_on_conflicting_content(self):
        ingested = datetime(2026, 5, 9, tzinfo=timezone.utc)
        t1 = BinanceTrade(
            venue="binance", instrument="SOLUSDT", id=100,
            price=Decimal("150"), qty=Decimal("1"),
            time=datetime(2024, 3, 1, tzinfo=timezone.utc),
            is_buyer_maker=False, ingested_at=ingested,
        )
        t2 = BinanceTrade(
            venue="binance", instrument="SOLUSDT", id=100,
            price=Decimal("151"),  # different price
            qty=Decimal("1"),
            time=datetime(2024, 3, 1, tzinfo=timezone.utc),
            is_buyer_maker=False, ingested_at=ingested,
        )
        with pytest.raises(PermanentFetcherError, match="conflicting content"):
            _sort_and_dedupe([t1, t2])


# ─── Validation ─────────────────────────────────────────────────────────


class TestValidation:
    def test_naive_start_raises(self, tmp_path):
        fetcher = _make_fetcher(FakeTransport({}), tmp_path)
        with pytest.raises(PermanentFetcherError, match="timezone-aware"):
            fetcher.fetch_window(
                "SOLUSDT",
                datetime(2024, 3, 1),
                datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
            )

    def test_end_before_start_raises(self, tmp_path):
        fetcher = _make_fetcher(FakeTransport({}), tmp_path)
        with pytest.raises(PermanentFetcherError, match="strictly after"):
            fetcher.fetch_window(
                "SOLUSDT",
                datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
                datetime(2024, 3, 1, tzinfo=timezone.utc),
            )

    def test_empty_symbol_raises(self, tmp_path):
        fetcher = _make_fetcher(FakeTransport({}), tmp_path)
        with pytest.raises(PermanentFetcherError, match="non-empty"):
            fetcher.fetch_window(
                "",
                datetime(2024, 3, 1, tzinfo=timezone.utc),
                datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
            )


# ─── Archive / CSV malformed ─────────────────────────────────────────────


class TestArchiveErrors:
    def test_archive_with_two_csvs_raises(self, tmp_path):
        archive = _make_archive([_row()], n_csv_files=2)
        url = _archive_url("SOLUSDT", 2024, 3)
        transport = FakeTransport({url: archive})
        fetcher = _make_fetcher(transport, tmp_path)
        with pytest.raises(PermanentFetcherError, match="exactly 1 entry"):
            fetcher.fetch_window(
                "SOLUSDT",
                datetime(2024, 3, 1, tzinfo=timezone.utc),
                datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
            )

    def test_csv_row_with_wrong_column_count_raises(self, tmp_path):
        bad_row = ["100", "150", "1", "100", "1709251200000"]  # only 5
        archive = _make_archive([bad_row])
        url = _archive_url("SOLUSDT", 2024, 3)
        transport = FakeTransport({url: archive})
        fetcher = _make_fetcher(transport, tmp_path)
        with pytest.raises(PermanentFetcherError, match="7 columns"):
            fetcher.fetch_window(
                "SOLUSDT",
                datetime(2024, 3, 1, tzinfo=timezone.utc),
                datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
            )

    def test_invalid_is_buyer_maker_raises(self, tmp_path):
        rows = [_row(agg_id=100, time_ms=1709251200000, is_buyer_maker="maybe")]
        archive = _make_archive(rows)
        url = _archive_url("SOLUSDT", 2024, 3)
        transport = FakeTransport({url: archive})
        fetcher = _make_fetcher(transport, tmp_path)
        with pytest.raises(PermanentFetcherError, match="is_buyer_maker"):
            fetcher.fetch_window(
                "SOLUSDT",
                datetime(2024, 3, 1, tzinfo=timezone.utc),
                datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
            )


# ─── HTTP error handling ────────────────────────────────────────────────


class TestHttpErrors:
    def test_http_404_raises_permanent(self, tmp_path):
        url = _archive_url("ZZZUSDT", 2024, 3)
        transport = FakeTransport({
            url: PermanentFetcherError("HTTP 404: Not Found"),
        })
        fetcher = _make_fetcher(transport, tmp_path)
        with pytest.raises(PermanentFetcherError, match="404"):
            fetcher.fetch_window(
                "ZZZUSDT",
                datetime(2024, 3, 1, tzinfo=timezone.utc),
                datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
            )
        assert len(transport.urls) == 1

    def test_transient_error_retried(self, tmp_path):
        archive = _make_archive([_row(agg_id=100, time_ms=1709251200000)])

        class CountingTransport:
            def __init__(self):
                self.calls = 0

            def get(self, u, *, timeout_seconds):
                self.calls += 1
                if self.calls < 3:
                    raise TransientFetcherError("network glitch")
                return archive

        transport = CountingTransport()
        fetcher = BinanceArchiveTradeFetcher(
            transport=transport,
            cache_dir=tmp_path,
            min_interval_seconds=0.0,
            _now=lambda: 0.0,
            _sleep=lambda s: None,
            _utcnow=lambda: datetime(2026, 5, 9, tzinfo=timezone.utc),
        )

        result = fetcher.fetch_window(
            "SOLUSDT",
            datetime(2024, 3, 1, tzinfo=timezone.utc),
            datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
        )
        assert [t.id for t in result] == [100]
        assert transport.calls == 3
