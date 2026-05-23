"""Unit tests for Coinbase USDT-USD fetcher.

Uses injected transport to avoid network calls. Real-data smoke test
lives separately (in a one-shot probe, not in this test file).
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from data.ingestion.vendors.coinbase.usdt_usd_fetcher import (
    CoinbaseUsdtUsdFetcher,
    CoinbaseFetcherError,
    CoinbasePermanentError,
    CoinbaseTransientError,
)


# ─── Helpers ─────────────────────────────────────────────────────────────

def _make_coinbase_row(ts_unix: int, price: str = "1.0") -> list:
    """One Coinbase candle row in the [time, low, high, open, close, volume] shape."""
    p = float(price)
    return [ts_unix, p - 0.0001, p + 0.0001, p, p, 1000.0]


def _stub_transport_returning(payloads: list):
    """Return a transport callable that yields each payload in order on
    successive calls. Each payload is a Python object that gets JSON-serialized."""
    calls = {"count": 0}
    def _t(url, timeout=30.0):
        idx = calls["count"]
        calls["count"] += 1
        if idx >= len(payloads):
            raise CoinbasePermanentError(f"Unexpected extra call #{idx + 1}")
        return json.dumps(payloads[idx])
    _t._calls = calls
    return _t


# ─── Tests ──────────────────────────────────────────────────────────────

class TestValidation:
    def test_rejects_naive_start(self):
        f = CoinbaseUsdtUsdFetcher()
        with pytest.raises(CoinbasePermanentError, match="timezone-aware"):
            f._validate_window(
                datetime(2024, 1, 1),
                datetime(2024, 1, 2, tzinfo=timezone.utc),
            )

    def test_rejects_naive_end(self):
        f = CoinbaseUsdtUsdFetcher()
        with pytest.raises(CoinbasePermanentError, match="timezone-aware"):
            f._validate_window(
                datetime(2024, 1, 1, tzinfo=timezone.utc),
                datetime(2024, 1, 2),
            )

    def test_rejects_end_before_start(self):
        f = CoinbaseUsdtUsdFetcher()
        with pytest.raises(CoinbasePermanentError, match="must be after"):
            f._validate_window(
                datetime(2024, 1, 2, tzinfo=timezone.utc),
                datetime(2024, 1, 1, tzinfo=timezone.utc),
            )

    def test_rejects_non_usdt_usd_product(self):
        with pytest.raises(CoinbasePermanentError, match="scoped to USDT-USD"):
            CoinbaseUsdtUsdFetcher(product_id="BTC-USD")


class TestRowParsing:
    def test_basic_row_parses_to_kline(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = CoinbaseUsdtUsdFetcher(cache_dir=Path(tmp))
            rows = [_make_coinbase_row(1704067200, price="1.0008")]
            klines = f._rows_to_klines(rows)
        assert len(klines) == 1
        k = klines[0]
        assert k.venue == "coinbase"
        assert k.instrument == "USDT-USD"
        assert k.interval == "1h"
        assert k.open_time == datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        assert k.close == Decimal("1.0008")
        # Unavailable fields are zero-padded
        assert k.trade_count == 0
        assert k.quote_volume == Decimal("0")
        assert k.taker_buy_volume == Decimal("0")

    def test_malformed_row_length_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = CoinbaseUsdtUsdFetcher(cache_dir=Path(tmp))
            with pytest.raises(CoinbasePermanentError, match="Malformed row"):
                f._rows_to_klines([[1, 2, 3]])  # only 3 elements

    def test_garbage_row_value_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = CoinbaseUsdtUsdFetcher(cache_dir=Path(tmp))
            with pytest.raises(CoinbasePermanentError, match="Failed to parse row"):
                f._rows_to_klines([[1704067200, "not-a-number", 1.1, 1.0, 1.05, 100.0]])

    def test_returned_klines_have_proper_decimal_precision(self):
        """Float parsing through Decimal(str(...)) preserves the literal value."""
        with tempfile.TemporaryDirectory() as tmp:
            f = CoinbaseUsdtUsdFetcher(cache_dir=Path(tmp))
            rows = [[1704067200, 1.00012, 1.00089, 1.00081, 1.00089, 1249433.97]]
            klines = f._rows_to_klines(rows)
        assert klines[0].close == Decimal("1.00089")
        assert klines[0].low == Decimal("1.00012")


class TestFetchWindowSingleCall:
    def test_single_page_response(self):
        """Window small enough to fit in one Coinbase page (< 300 hours)."""
        with tempfile.TemporaryDirectory() as tmp:
            # Build 5 rows covering hours 0..4 of 2024-01-01
            rows = [
                _make_coinbase_row(1704067200 + h * 3600, price=str(1.0 + h * 0.001))
                for h in range(5)
            ]
            # Coinbase returns newest-first
            rows.reverse()
            transport = _stub_transport_returning([rows])

            f = CoinbaseUsdtUsdFetcher(
                cache_dir=Path(tmp),
                transport=transport,
                throttle_seconds=0.0,
            )
            klines = f.fetch_window(
                datetime(2024, 1, 1, 0, tzinfo=timezone.utc),
                datetime(2024, 1, 1, 5, tzinfo=timezone.utc),
            )

        assert len(klines) == 5
        # Verify ascending sort
        for i in range(1, len(klines)):
            assert klines[i].open_time > klines[i - 1].open_time
        # Verify content
        assert klines[0].close == Decimal("1.0")
        assert klines[-1].close == Decimal("1.004")

    def test_window_filter_excludes_rows_outside_range(self):
        """If the API returns rows outside the requested window, the fetcher
        must filter them out."""
        with tempfile.TemporaryDirectory() as tmp:
            # Rows span hours 0..10, but we'll only request 2..5
            rows = [
                _make_coinbase_row(1704067200 + h * 3600, price=str(1.0 + h * 0.001))
                for h in range(11)
            ]
            rows.reverse()
            transport = _stub_transport_returning([rows])

            f = CoinbaseUsdtUsdFetcher(
                cache_dir=Path(tmp),
                transport=transport,
                throttle_seconds=0.0,
            )
            klines = f.fetch_window(
                datetime(2024, 1, 1, 2, tzinfo=timezone.utc),
                datetime(2024, 1, 1, 5, tzinfo=timezone.utc),
            )

        # Should be hours 2, 3, 4 (start inclusive, end exclusive)
        assert len(klines) == 3
        assert klines[0].open_time == datetime(2024, 1, 1, 2, tzinfo=timezone.utc)
        assert klines[-1].open_time == datetime(2024, 1, 1, 4, tzinfo=timezone.utc)


class TestDeduplication:
    def test_duplicate_timestamps_resolved(self):
        """If consecutive pages overlap (which Coinbase pagination can cause),
        the dedup-by-timestamp logic should keep one entry per hour."""
        with tempfile.TemporaryDirectory() as tmp:
            # Page 1: hours 5, 4, 3
            page1 = [
                _make_coinbase_row(1704067200 + h * 3600, price="1.001")
                for h in [5, 4, 3]
            ]
            # Page 2: hours 3, 2, 1, 0 (overlap on hour 3)
            page2 = [
                _make_coinbase_row(1704067200 + h * 3600, price="1.002")
                for h in [3, 2, 1, 0]
            ]
            transport = _stub_transport_returning([page1, page2])

            f = CoinbaseUsdtUsdFetcher(
                cache_dir=Path(tmp),
                transport=transport,
                throttle_seconds=0.0,
            )
            klines = f.fetch_window(
                datetime(2024, 1, 1, 0, tzinfo=timezone.utc),
                datetime(2024, 1, 1, 6, tzinfo=timezone.utc),
            )

        # 6 distinct hours, no duplicates
        timestamps = [k.open_time for k in klines]
        assert len(timestamps) == len(set(timestamps))
        assert len(klines) == 6


class TestCaching:
    def test_cache_writes_and_reloads_without_network(self):
        """First call writes cache, second call reads from cache without
        invoking the transport."""
        with tempfile.TemporaryDirectory() as tmp:
            rows = [_make_coinbase_row(1704067200, price="1.0")]
            transport = _stub_transport_returning([rows])

            f = CoinbaseUsdtUsdFetcher(
                cache_dir=Path(tmp),
                transport=transport,
                throttle_seconds=0.0,
            )
            klines1 = f.fetch_window(
                datetime(2024, 1, 1, 0, tzinfo=timezone.utc),
                datetime(2024, 1, 1, 1, tzinfo=timezone.utc),
            )

            # Verify a cache file was written
            cache_files = list(Path(tmp).glob("end_*.json"))
            assert len(cache_files) >= 1

            # Re-fetch with a transport that would FAIL if called
            def fail_transport(url, timeout=30.0):
                raise AssertionError("Transport should not be invoked on cache hit")

            f2 = CoinbaseUsdtUsdFetcher(
                cache_dir=Path(tmp),
                transport=fail_transport,
                throttle_seconds=0.0,
            )
            klines2 = f2.fetch_window(
                datetime(2024, 1, 1, 0, tzinfo=timezone.utc),
                datetime(2024, 1, 1, 1, tzinfo=timezone.utc),
            )

        assert len(klines1) == len(klines2) == 1
        assert klines1[0].close == klines2[0].close


class TestErrorHandling:
    def test_error_response_raises_permanent(self):
        """Coinbase {'message': '...'} responses are permanent errors."""
        with tempfile.TemporaryDirectory() as tmp:
            transport = _stub_transport_returning([{"message": "NotFound"}])
            f = CoinbaseUsdtUsdFetcher(
                cache_dir=Path(tmp),
                transport=transport,
                throttle_seconds=0.0,
            )
            with pytest.raises(CoinbasePermanentError, match="NotFound"):
                f.fetch_window(
                    datetime(2024, 1, 1, 0, tzinfo=timezone.utc),
                    datetime(2024, 1, 1, 1, tzinfo=timezone.utc),
                )

    def test_unexpected_shape_raises_permanent(self):
        with tempfile.TemporaryDirectory() as tmp:
            transport = _stub_transport_returning(["just a string"])
            f = CoinbaseUsdtUsdFetcher(
                cache_dir=Path(tmp),
                transport=transport,
                throttle_seconds=0.0,
            )
            with pytest.raises(CoinbasePermanentError, match="Unexpected response shape"):
                f.fetch_window(
                    datetime(2024, 1, 1, 0, tzinfo=timezone.utc),
                    datetime(2024, 1, 1, 1, tzinfo=timezone.utc),
                )

    def test_empty_response_returns_empty(self):
        """An empty rows list (legitimate end-of-data) returns no klines, not error."""
        with tempfile.TemporaryDirectory() as tmp:
            transport = _stub_transport_returning([[]])
            f = CoinbaseUsdtUsdFetcher(
                cache_dir=Path(tmp),
                transport=transport,
                throttle_seconds=0.0,
            )
            klines = f.fetch_window(
                datetime(2024, 1, 1, 0, tzinfo=timezone.utc),
                datetime(2024, 1, 1, 1, tzinfo=timezone.utc),
            )
        assert klines == []
