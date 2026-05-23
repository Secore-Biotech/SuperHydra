"""Unit tests for OkxKlinesFetcher.

Uses an injectable transport stub. No network access.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from data.ingestion.vendors.okx.okx_klines_fetcher import (
    MAX_RECORDS_PER_CALL,
    OkxKlinesFetcher,
    OkxPermanentError,
    OkxTransientError,
    _default_cache_dir_for,
)


# ─── Test helpers ────────────────────────────────────────────────────────

def _make_okx_row(ts_ms: int, close_price: str = "50000.0") -> list[str]:
    """Build one OKX-shaped kline row.

    OKX format: [ts_ms, open, high, low, close, vol, vol_ccy, vol_ccy_quote, confirm]
    """
    return [
        str(ts_ms),
        close_price,           # open
        close_price,           # high
        close_price,           # low
        close_price,           # close
        "100.0",               # volume (base)
        "5000000.0",           # volume (quote ccy)
        "5000000.0",           # volume (quote ccy quote)
        "1",                   # confirm
    ]


def _make_okx_response(rows: list[list[str]], code: str = "0") -> str:
    """Build a JSON OKX REST response body."""
    return json.dumps({
        "code": code,
        "msg": "",
        "data": rows,
    })


def _ts_ms(year: int, month: int, day: int, hour: int = 0) -> int:
    return int(datetime(year, month, day, hour, tzinfo=timezone.utc).timestamp() * 1000)


class _StubTransport:
    """Captures requested URLs and returns canned responses."""

    def __init__(self, responses: dict[str, str] | None = None,
                 default: str | None = None):
        self.responses = responses or {}
        self.default = default
        self.urls_called: list[str] = []

    def __call__(self, url: str, timeout: float = 30.0) -> str:
        self.urls_called.append(url)
        if url in self.responses:
            return self.responses[url]
        # Match by base URL ignoring after= cursor — useful when we don't
        # want to predict the cursor in every test
        for canned_url, response in self.responses.items():
            if canned_url == "*":
                return response
        if self.default is not None:
            return self.default
        raise AssertionError(f"unexpected URL: {url}")


# ─── Construction & validation ──────────────────────────────────────────

class TestConstruction:
    def test_default_interval(self, tmp_path):
        f = OkxKlinesFetcher(inst_id="BTC-USDT-SWAP", cache_dir=tmp_path)
        assert f.interval == "1H"
        assert f.inst_id == "BTC-USDT-SWAP"

    def test_empty_inst_id_raises(self):
        with pytest.raises(ValueError, match="inst_id"):
            OkxKlinesFetcher(inst_id="")

    def test_unsupported_interval_raises(self):
        with pytest.raises(ValueError, match="interval"):
            OkxKlinesFetcher(inst_id="BTC-USDT-SWAP", interval="5m")

    def test_default_cache_dir_includes_inst_id(self):
        cache_dir = _default_cache_dir_for("BTC-USDT-SWAP", "1H")
        assert "BTC-USDT-SWAP" in str(cache_dir)
        assert "1H" in str(cache_dir)
        assert "okx_klines" in str(cache_dir)


class TestValidation:
    def test_naive_start_raises(self, tmp_path):
        f = OkxKlinesFetcher(
            inst_id="BTC-USDT-SWAP", cache_dir=tmp_path,
            transport=_StubTransport(default=_make_okx_response([])),
        )
        with pytest.raises(ValueError, match="timezone-aware"):
            f.fetch_window(
                datetime(2024, 1, 1),  # naive
                datetime(2024, 1, 2, tzinfo=timezone.utc),
            )

    def test_end_before_start_raises(self, tmp_path):
        f = OkxKlinesFetcher(
            inst_id="BTC-USDT-SWAP", cache_dir=tmp_path,
            transport=_StubTransport(default=_make_okx_response([])),
        )
        with pytest.raises(ValueError, match="must be after"):
            f.fetch_window(
                datetime(2024, 1, 2, tzinfo=timezone.utc),
                datetime(2024, 1, 1, tzinfo=timezone.utc),
            )


# ─── Pagination ─────────────────────────────────────────────────────────

class TestPagination:
    def test_single_page_fetch(self, tmp_path):
        """Fetch a window that fits in one page (≤300 records)."""
        rows = [
            _make_okx_row(_ts_ms(2024, 1, 15, h), close_price=f"{40000 + h}")
            for h in (0, 1, 2)
        ]
        # OKX returns newest-first
        rows_descending = list(reversed(rows))

        f = OkxKlinesFetcher(
            inst_id="BTC-USDT-SWAP", cache_dir=tmp_path, throttle_seconds=0,
            transport=_StubTransport(default=_make_okx_response(rows_descending)),
        )
        klines = f.fetch_window(
            datetime(2024, 1, 15, 0, tzinfo=timezone.utc),
            datetime(2024, 1, 15, 3, tzinfo=timezone.utc),
        )
        # We expect 3 klines, oldest first
        assert len(klines) == 3
        assert klines[0].open_time == datetime(2024, 1, 15, 0, tzinfo=timezone.utc)
        assert klines[1].open_time == datetime(2024, 1, 15, 1, tzinfo=timezone.utc)
        assert klines[2].open_time == datetime(2024, 1, 15, 2, tzinfo=timezone.utc)
        assert klines[0].close == Decimal("40000")
        assert klines[2].close == Decimal("40002")
        # All should be tagged venue=okx
        assert all(k.venue == "okx" for k in klines)

    def test_multi_page_pagination(self, tmp_path):
        """When the window spans more than one page, the fetcher paginates
        backward by setting `after` to the oldest ts in the prior page."""
        # Build two pages: page 1 (newer) has 3 rows, page 2 (older) has 3 rows
        page1_rows = [
            _make_okx_row(_ts_ms(2024, 1, 15, h), close_price=f"{40000 + h}")
            for h in (3, 4, 5)  # newer
        ]
        page2_rows = [
            _make_okx_row(_ts_ms(2024, 1, 15, h), close_price=f"{40000 + h}")
            for h in (0, 1, 2)  # older
        ]

        # OKX returns newest-first within each page
        page1_descending = list(reversed(page1_rows))
        page2_descending = list(reversed(page2_rows))

        # First call: after=end_ms=06:00, expect page1 (3,4,5)
        # Second call: after=oldest_in_page1=03:00, expect page2 (0,1,2)
        end_ms = _ts_ms(2024, 1, 15, 6)
        start_ms = _ts_ms(2024, 1, 15, 0)
        page1_oldest_ts = _ts_ms(2024, 1, 15, 3)

        # Build URL-keyed responses
        url_page1 = (
            f"https://www.okx.com/api/v5/market/history-candles"
            f"?instId=BTC-USDT-SWAP&bar=1H&after={end_ms}&limit={MAX_RECORDS_PER_CALL}"
        )
        url_page2 = (
            f"https://www.okx.com/api/v5/market/history-candles"
            f"?instId=BTC-USDT-SWAP&bar=1H&after={page1_oldest_ts}&limit={MAX_RECORDS_PER_CALL}"
        )

        f = OkxKlinesFetcher(
            inst_id="BTC-USDT-SWAP", cache_dir=tmp_path, throttle_seconds=0,
            transport=_StubTransport(responses={
                url_page1: _make_okx_response(page1_descending),
                url_page2: _make_okx_response(page2_descending),
            }),
        )

        klines = f.fetch_window(
            datetime(2024, 1, 15, 0, tzinfo=timezone.utc),
            datetime(2024, 1, 15, 6, tzinfo=timezone.utc),
        )

        # Window is [00:00, 06:00) — should get hours 0,1,2,3,4,5
        assert len(klines) == 6
        assert klines[0].open_time == datetime(2024, 1, 15, 0, tzinfo=timezone.utc)
        assert klines[-1].open_time == datetime(2024, 1, 15, 5, tzinfo=timezone.utc)

    def test_empty_response_stops_pagination(self, tmp_path):
        """If a page returns 0 records, pagination stops immediately."""
        f = OkxKlinesFetcher(
            inst_id="BTC-USDT-SWAP", cache_dir=tmp_path, throttle_seconds=0,
            transport=_StubTransport(default=_make_okx_response([])),
        )
        klines = f.fetch_window(
            datetime(2024, 1, 15, 0, tzinfo=timezone.utc),
            datetime(2024, 1, 15, 3, tzinfo=timezone.utc),
        )
        assert klines == []


# ─── Caching ────────────────────────────────────────────────────────────

class TestCaching:
    def test_second_fetch_uses_cache_not_network(self, tmp_path):
        rows = [_make_okx_row(_ts_ms(2024, 1, 15, 0))]
        stub = _StubTransport(default=_make_okx_response(rows))
        f = OkxKlinesFetcher(
            inst_id="BTC-USDT-SWAP", cache_dir=tmp_path, throttle_seconds=0,
            transport=stub,
        )

        # First fetch hits network
        f.fetch_window(
            datetime(2024, 1, 15, 0, tzinfo=timezone.utc),
            datetime(2024, 1, 15, 1, tzinfo=timezone.utc),
        )
        first_call_count = len(stub.urls_called)
        assert first_call_count >= 1

        # Cache file should exist
        cached_files = list(tmp_path.glob("after_*.json"))
        assert len(cached_files) >= 1

        # Second fetch with same window should NOT hit network again
        f.fetch_window(
            datetime(2024, 1, 15, 0, tzinfo=timezone.utc),
            datetime(2024, 1, 15, 1, tzinfo=timezone.utc),
        )
        assert len(stub.urls_called) == first_call_count, \
            "Second fetch hit network, but cache should have been used"


# ─── Error handling ────────────────────────────────────────────────────

class TestErrorHandling:
    def test_rate_limit_code_raises_transient(self, tmp_path):
        f = OkxKlinesFetcher(
            inst_id="BTC-USDT-SWAP", cache_dir=tmp_path, throttle_seconds=0,
            transport=_StubTransport(default=_make_okx_response([], code="50011")),
        )
        with pytest.raises(OkxTransientError, match="rate limit"):
            f.fetch_window(
                datetime(2024, 1, 15, 0, tzinfo=timezone.utc),
                datetime(2024, 1, 15, 1, tzinfo=timezone.utc),
            )

    def test_okx_error_code_raises_permanent(self, tmp_path):
        f = OkxKlinesFetcher(
            inst_id="BTC-USDT-SWAP", cache_dir=tmp_path, throttle_seconds=0,
            transport=_StubTransport(default=_make_okx_response([], code="51000")),
        )
        with pytest.raises(OkxPermanentError, match="code=51000"):
            f.fetch_window(
                datetime(2024, 1, 15, 0, tzinfo=timezone.utc),
                datetime(2024, 1, 15, 1, tzinfo=timezone.utc),
            )

    def test_non_json_response_raises_permanent(self, tmp_path):
        f = OkxKlinesFetcher(
            inst_id="BTC-USDT-SWAP", cache_dir=tmp_path, throttle_seconds=0,
            transport=_StubTransport(default="<html>Error 500</html>"),
        )
        with pytest.raises(OkxPermanentError, match="Non-JSON"):
            f.fetch_window(
                datetime(2024, 1, 15, 0, tzinfo=timezone.utc),
                datetime(2024, 1, 15, 1, tzinfo=timezone.utc),
            )

    def test_bad_row_shape_raises_permanent(self, tmp_path):
        bad_response = json.dumps({"code": "0", "data": [["only_one_col"]]})
        f = OkxKlinesFetcher(
            inst_id="BTC-USDT-SWAP", cache_dir=tmp_path, throttle_seconds=0,
            transport=_StubTransport(default=bad_response),
        )
        with pytest.raises(OkxPermanentError, match="unexpected shape"):
            f.fetch_window(
                datetime(2024, 1, 15, 0, tzinfo=timezone.utc),
                datetime(2024, 1, 15, 1, tzinfo=timezone.utc),
            )


# ─── Window filtering ───────────────────────────────────────────────────

class TestWindowFiltering:
    def test_klines_outside_window_filtered(self, tmp_path):
        """OKX may return klines slightly outside the requested window
        (the pagination terminator). Those must be filtered out."""
        rows = [
            _make_okx_row(_ts_ms(2024, 1, 15, h))
            for h in (0, 1, 2, 3, 4)
        ]
        f = OkxKlinesFetcher(
            inst_id="BTC-USDT-SWAP", cache_dir=tmp_path, throttle_seconds=0,
            transport=_StubTransport(default=_make_okx_response(list(reversed(rows)))),
        )
        klines = f.fetch_window(
            datetime(2024, 1, 15, 1, tzinfo=timezone.utc),
            datetime(2024, 1, 15, 4, tzinfo=timezone.utc),
        )
        # Window is [01:00, 04:00) — should get hours 1, 2, 3 (NOT 0 or 4)
        assert len(klines) == 3
        assert klines[0].open_time.hour == 1
        assert klines[-1].open_time.hour == 3
