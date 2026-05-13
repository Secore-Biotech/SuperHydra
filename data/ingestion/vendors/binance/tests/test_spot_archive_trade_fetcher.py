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



# ═══════════════════════════════════════════════════════════════════════
# Day 26.5: Parser tests for 8-column spot aggTrades schema
# ═══════════════════════════════════════════════════════════════════════


import csv as _csv  # local alias to avoid shadowing other imports
import io as _io
import zipfile as _zipfile
from datetime import datetime as _datetime, timezone as _timezone
from decimal import Decimal as _Decimal

from data.ingestion.vendors.binance.spot_archive_trade_fetcher import (
    _iter_spot_trades_in_window,
)


def _make_spot_csv_zip(
    rows: list[list[str]],
    *,
    with_header: bool = True,
    csv_name: str = "SOLUSDT-aggTrades-2024-03.csv",
) -> bytes:
    """Build an in-memory ZIP with a single spot aggTrades CSV."""
    csv_buf = _io.StringIO()
    writer = _csv.writer(csv_buf)
    if with_header:
        writer.writerow([
            "agg_trade_id", "price", "quantity",
            "first_trade_id", "last_trade_id",
            "transact_time", "is_buyer_maker", "is_best_match",
        ])
    for row in rows:
        writer.writerow(row)

    zip_buf = _io.BytesIO()
    with _zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr(csv_name, csv_buf.getvalue())
    return zip_buf.getvalue()


class TestSpotCsvParser:
    """Parser-level tests for the spot 8-column aggTrades schema."""

    INGEST_TS = _datetime(2024, 4, 1, tzinfo=_timezone.utc)

    def test_8_column_row_parses(self):
        # The exact row shape from the empirical Day 26 run
        rows = [
            ["299723016", "125.68000000", "19.98000000",
             "472398630", "472398634", "1709251200006",
             "False", "True"],
        ]
        archive = _make_spot_csv_zip(rows)
        trades = list(_iter_spot_trades_in_window(
            archive,
            symbol="SOLUSDT",
            start_ms=0,
            end_ms=2_000_000_000_000,
            ingested_at=self.INGEST_TS,
        ))
        assert len(trades) == 1
        t = trades[0]
        assert t.id == 299723016
        assert t.price == _Decimal("125.68000000")
        assert t.qty == _Decimal("19.98000000")
        assert t.is_buyer_maker is False
        assert t.instrument == "SOLUSDT"
        assert t.venue == "binance"
        # is_best_match (col 7) is ignored; BinanceTrade has no field for it
        assert not hasattr(t, "is_best_match")

    def test_7_column_row_raises(self):
        # If the schema were perp (7 cols), spot parser must reject
        rows = [
            ["299723016", "125.68", "19.98", "472398630",
             "472398634", "1709251200006", "False"],
        ]
        archive = _make_spot_csv_zip(rows, with_header=False)
        with pytest.raises(
            PermanentFetcherError, match="expected 8 columns",
        ):
            list(_iter_spot_trades_in_window(
                archive,
                symbol="SOLUSDT",
                start_ms=0,
                end_ms=2_000_000_000_000,
                ingested_at=self.INGEST_TS,
            ))

    def test_9_column_row_raises(self):
        # Forward-defense: if Binance ever adds a 9th column, fail loud
        rows = [
            ["1", "100.00", "1.0", "10", "20", "1709251200006",
             "True", "False", "extra"],
        ]
        archive = _make_spot_csv_zip(rows, with_header=False)
        with pytest.raises(
            PermanentFetcherError, match="expected 8 columns",
        ):
            list(_iter_spot_trades_in_window(
                archive,
                symbol="SOLUSDT",
                start_ms=0,
                end_ms=2_000_000_000_000,
                ingested_at=self.INGEST_TS,
            ))

    def test_header_row_skipped(self):
        rows = [
            ["1", "100.00", "1.0", "10", "20", "1709251200006",
             "True", "True"],
        ]
        # with_header=True (default): writes header before data row
        archive = _make_spot_csv_zip(rows, with_header=True)
        trades = list(_iter_spot_trades_in_window(
            archive,
            symbol="SOLUSDT",
            start_ms=0,
            end_ms=2_000_000_000_000,
            ingested_at=self.INGEST_TS,
        ))
        assert len(trades) == 1
        assert trades[0].id == 1

    def test_is_buyer_maker_true_parses(self):
        rows = [
            ["1", "100.00", "1.0", "10", "20", "1709251200006",
             "True", "False"],
        ]
        archive = _make_spot_csv_zip(rows, with_header=False)
        trades = list(_iter_spot_trades_in_window(
            archive,
            symbol="SOLUSDT",
            start_ms=0,
            end_ms=2_000_000_000_000,
            ingested_at=self.INGEST_TS,
        ))
        assert trades[0].is_buyer_maker is True

    def test_is_buyer_maker_invalid_raises(self):
        rows = [
            ["1", "100.00", "1.0", "10", "20", "1709251200006",
             "Yes", "True"],  # "Yes" is not "true"/"false"
        ]
        archive = _make_spot_csv_zip(rows, with_header=False)
        with pytest.raises(
            PermanentFetcherError, match="unexpected is_buyer_maker",
        ):
            list(_iter_spot_trades_in_window(
                archive,
                symbol="SOLUSDT",
                start_ms=0,
                end_ms=2_000_000_000_000,
                ingested_at=self.INGEST_TS,
            ))

    def test_extra_column_ignored(self):
        """is_best_match (col 7) is consumed but not propagated."""
        rows = [
            ["1", "100.00", "1.0", "10", "20", "1709251200006",
             "False", "False"],
        ]
        archive = _make_spot_csv_zip(rows, with_header=False)
        trades = list(_iter_spot_trades_in_window(
            archive,
            symbol="SOLUSDT",
            start_ms=0,
            end_ms=2_000_000_000_000,
            ingested_at=self.INGEST_TS,
        ))
        assert len(trades) == 1
        # No is_best_match-like attribute leaked onto BinanceTrade
        for attr in ["is_best_match", "best_match", "best"]:
            assert not hasattr(trades[0], attr)

    def test_window_filters_out_of_range_trades(self):
        rows = [
            ["1", "100.00", "1.0", "10", "20", "1000",
             "False", "False"],
            ["2", "101.00", "1.0", "10", "20", "2000",
             "False", "False"],
            ["3", "102.00", "1.0", "10", "20", "3000",
             "False", "False"],
        ]
        archive = _make_spot_csv_zip(rows, with_header=False)
        # Window [1500, 2500): only trade with time_ms=2000 included
        trades = list(_iter_spot_trades_in_window(
            archive,
            symbol="SOLUSDT",
            start_ms=1500,
            end_ms=2500,
            ingested_at=self.INGEST_TS,
        ))
        assert len(trades) == 1
        assert trades[0].id == 2

    def test_malformed_price_raises(self):
        rows = [
            ["1", "not_a_number", "1.0", "10", "20", "1709251200006",
             "False", "True"],
        ]
        archive = _make_spot_csv_zip(rows, with_header=False)
        with pytest.raises(
            PermanentFetcherError, match="malformed spot CSV row",
        ):
            list(_iter_spot_trades_in_window(
                archive,
                symbol="SOLUSDT",
                start_ms=0,
                end_ms=2_000_000_000_000,
                ingested_at=self.INGEST_TS,
            ))

    def test_multiple_entries_in_zip_raises(self):
        zip_buf = _io.BytesIO()
        with _zipfile.ZipFile(zip_buf, "w") as zf:
            zf.writestr("first.csv", "a,b,c\n")
            zf.writestr("second.csv", "x,y,z\n")
        archive = zip_buf.getvalue()
        with pytest.raises(
            PermanentFetcherError, match="expected exactly 1 entry",
        ):
            list(_iter_spot_trades_in_window(
                archive,
                symbol="SOLUSDT",
                start_ms=0,
                end_ms=2_000_000_000_000,
                ingested_at=self.INGEST_TS,
            ))
