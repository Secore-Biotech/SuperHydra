"""Unit tests for the Binance aggTrades fetcher."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from data.ingestion.vendors.binance.trade import (
    BinanceTrade,
    CANONICAL_SCHEMA_VERSION,
)
from data.ingestion.vendors.binance.trade_fetcher import (
    BinanceTradeFetcher,
    PermanentFetcherError,
    TransientFetcherError,
)


class FakeTransport:
    """Returns canned bytes per call. Records every URL it sees."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.urls: list[str] = []

    def get(self, url: str, *, timeout_seconds: float) -> bytes:
        self.urls.append(url)
        if not self._responses:
            raise AssertionError(f"unexpected extra GET: {url}")
        r = self._responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _trade_dict(
    a: int = 100,
    p: str = "150.00",
    q: str = "1.5",
    t_ms: int = 1709251200000,  # 2024-03-01T00:00:00Z
    m: bool = False,
) -> dict:
    return {"a": a, "p": p, "q": q, "T": t_ms, "m": m, "f": 1, "l": 1}


def _make_fetcher(transport: FakeTransport) -> BinanceTradeFetcher:
    fixed_now = [0.0]
    return BinanceTradeFetcher(
        transport=transport,
        min_interval_seconds=0.0,
        _now=lambda: fixed_now[0],
        _sleep=lambda s: None,
        _utcnow=lambda: datetime(2026, 5, 9, tzinfo=timezone.utc),
    )


# ─── Single-page parse ──────────────────────────────────────────────────


class TestSinglePageParse:
    def test_empty_response_returns_empty_list(self):
        transport = FakeTransport([b"[]"])
        fetcher = _make_fetcher(transport)
        result = fetcher.fetch_window(
            "SOLUSDT",
            datetime(2024, 3, 1, tzinfo=timezone.utc),
            datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
        )
        assert result == []
        assert len(transport.urls) == 1

    def test_single_record_parses(self):
        body = json.dumps([_trade_dict(a=100, p="150.50", q="2", t_ms=1709251200000)]).encode()
        transport = FakeTransport([body])
        fetcher = _make_fetcher(transport)
        result = fetcher.fetch_window(
            "SOLUSDT",
            datetime(2024, 3, 1, tzinfo=timezone.utc),
            datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
        )
        assert len(result) == 1
        t = result[0]
        assert t.venue == "binance"
        assert t.instrument == "SOLUSDT"
        assert t.id == 100
        assert t.price == Decimal("150.50")
        assert t.qty == Decimal("2")
        assert t.time == datetime(2024, 3, 1, tzinfo=timezone.utc)
        assert t.is_buyer_maker is False
        assert t.schema_version == CANONICAL_SCHEMA_VERSION

    def test_records_sorted_by_time_then_id(self):
        body = json.dumps([
            _trade_dict(a=102, t_ms=1709251202000),
            _trade_dict(a=100, t_ms=1709251200000),
            _trade_dict(a=101, t_ms=1709251200000),
        ]).encode()
        transport = FakeTransport([body])
        fetcher = _make_fetcher(transport)
        result = fetcher.fetch_window(
            "SOLUSDT",
            datetime(2024, 3, 1, tzinfo=timezone.utc),
            datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
        )
        assert [t.id for t in result] == [100, 101, 102]


# ─── Pagination ─────────────────────────────────────────────────────────


class TestPagination:
    def test_two_page_pagination(self):
        page1 = json.dumps([
            _trade_dict(a=100, t_ms=1709251200000),
            _trade_dict(a=101, t_ms=1709251200500),
        ]).encode()
        page2 = json.dumps([
            _trade_dict(a=102, t_ms=1709251300000),
        ]).encode()
        transport = FakeTransport([page1, page2])

        fetcher = _make_fetcher(transport)
        result = fetcher.fetch_window(
            "SOLUSDT",
            datetime(2024, 3, 1, tzinfo=timezone.utc),
            datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
            limit=2,
        )
        assert [t.id for t in result] == [100, 101, 102]
        assert len(transport.urls) == 2
        assert "startTime=1709251200501" in transport.urls[1]

    def test_pagination_dedupes_by_trade_id(self):
        # Page 1 last trade at 1709251200000, cursor advances to ...001.
        # Page 2 returns id=101 again at 1709251200000 (boundary race);
        # dedupe removes the duplicate.
        page1 = json.dumps([
            _trade_dict(a=100, t_ms=1709251199000),
            _trade_dict(a=101, t_ms=1709251200000),
        ]).encode()
        page2 = json.dumps([
            _trade_dict(a=101, t_ms=1709251200000),  # duplicate
        ]).encode()
        transport = FakeTransport([page1, page2])
        fetcher = _make_fetcher(transport)
        result = fetcher.fetch_window(
            "SOLUSDT",
            datetime(2024, 3, 1, tzinfo=timezone.utc),
            datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
            limit=2,
        )
        # Page 2 has 1 record (partial page) so fetcher stops.
        # The duplicate id=101 is filtered by the dedupe path.
        assert [t.id for t in result] == [100, 101]
        assert len(transport.urls) == 2

    def test_pagination_stops_at_max_pages(self):
        # Three full pages with distinct trade times so cursor advances
        # normally; max_pages=3 stops fetcher after 3 calls.
        page1 = json.dumps([
            _trade_dict(a=100, t_ms=1709251200000),
            _trade_dict(a=101, t_ms=1709251201000),
        ]).encode()
        page2 = json.dumps([
            _trade_dict(a=102, t_ms=1709251202000),
            _trade_dict(a=103, t_ms=1709251203000),
        ]).encode()
        page3 = json.dumps([
            _trade_dict(a=104, t_ms=1709251204000),
            _trade_dict(a=105, t_ms=1709251205000),
        ]).encode()
        transport = FakeTransport([page1, page2, page3])

        fetcher = _make_fetcher(transport)
        result = fetcher.fetch_window(
            "SOLUSDT",
            datetime(2024, 3, 1, tzinfo=timezone.utc),
            datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
            limit=2,
            max_pages=3,
        )
        assert len(transport.urls) == 3
        assert [t.id for t in result] == [100, 101, 102, 103, 104, 105]

    def test_same_ms_boundary_does_not_raise(self):
        # Page 1 ends at same ms as cursor-after-advance.
        # next_cursor == cursor_ms is legitimate (handled by id dedupe);
        # must NOT raise.
        page1 = json.dumps([
            _trade_dict(a=100, t_ms=1709251199000),
            _trade_dict(a=101, t_ms=1709251200000),
        ]).encode()
        page2 = json.dumps([
            _trade_dict(a=101, t_ms=1709251200000),  # boundary duplicate
        ]).encode()
        transport = FakeTransport([page1, page2])
        fetcher = _make_fetcher(transport)
        # Should not raise. Page 2 has 1 record (partial), pagination
        # stops naturally; the duplicate is filtered by id dedupe.
        # The key assertion is that the same-ms cursor (next_cursor ==
        # cursor_ms after page 1) does NOT trip the defensive guard.
        result = fetcher.fetch_window(
            "SOLUSDT",
            datetime(2024, 3, 1, tzinfo=timezone.utc),
            datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
            limit=2,
        )
        assert [t.id for t in result] == [100, 101]
        assert len(transport.urls) == 2

    def test_strictly_backward_cursor_raises(self):
        # Trade time strictly BEFORE startTime: next_cursor < cursor_ms.
        # Defensive guard fires.
        page = json.dumps([
            _trade_dict(a=100, t_ms=1709251199000),
            _trade_dict(a=99,  t_ms=1709251199000),
        ]).encode()
        transport = FakeTransport([page])
        fetcher = _make_fetcher(transport)
        with pytest.raises(PermanentFetcherError, match="cursor failed to advance"):
            fetcher.fetch_window(
                "SOLUSDT",
                datetime(2024, 3, 1, tzinfo=timezone.utc),
                datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
                limit=2,
            )


# ─── Validation errors ──────────────────────────────────────────────────


class TestValidation:
    def test_naive_start_raises(self):
        fetcher = _make_fetcher(FakeTransport([]))
        with pytest.raises(PermanentFetcherError, match="timezone-aware"):
            fetcher.fetch_window(
                "SOLUSDT",
                datetime(2024, 3, 1),
                datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
            )

    def test_end_before_start_raises(self):
        fetcher = _make_fetcher(FakeTransport([]))
        with pytest.raises(PermanentFetcherError, match="strictly after"):
            fetcher.fetch_window(
                "SOLUSDT",
                datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
                datetime(2024, 3, 1, tzinfo=timezone.utc),
            )

    def test_empty_symbol_raises(self):
        fetcher = _make_fetcher(FakeTransport([]))
        with pytest.raises(PermanentFetcherError, match="non-empty"):
            fetcher.fetch_window(
                "",
                datetime(2024, 3, 1, tzinfo=timezone.utc),
                datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
            )

    def test_invalid_limit_raises(self):
        fetcher = _make_fetcher(FakeTransport([]))
        with pytest.raises(PermanentFetcherError, match="limit must be"):
            fetcher.fetch_window(
                "SOLUSDT",
                datetime(2024, 3, 1, tzinfo=timezone.utc),
                datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
                limit=0,
            )


# ─── HTTP / parse error handling ────────────────────────────────────────


class TestErrorHandling:
    def test_malformed_json_raises_permanent(self):
        transport = FakeTransport([b"not valid json"])
        fetcher = _make_fetcher(transport)
        with pytest.raises(PermanentFetcherError, match="malformed"):
            fetcher.fetch_window(
                "SOLUSDT",
                datetime(2024, 3, 1, tzinfo=timezone.utc),
                datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
            )

    def test_response_not_array_raises_permanent(self):
        transport = FakeTransport([b'{"error":"Bad Request"}'])
        fetcher = _make_fetcher(transport)
        with pytest.raises(PermanentFetcherError, match="JSON array"):
            fetcher.fetch_window(
                "SOLUSDT",
                datetime(2024, 3, 1, tzinfo=timezone.utc),
                datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
            )

    def test_missing_field_raises_permanent(self):
        body = json.dumps([{"a": 100, "p": "150.0"}]).encode()
        transport = FakeTransport([body])
        fetcher = _make_fetcher(transport)
        with pytest.raises(PermanentFetcherError, match="malformed trade record"):
            fetcher.fetch_window(
                "SOLUSDT",
                datetime(2024, 3, 1, tzinfo=timezone.utc),
                datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
            )

    def test_negative_price_raises_permanent(self):
        body = json.dumps([_trade_dict(p="-1.0")]).encode()
        transport = FakeTransport([body])
        fetcher = _make_fetcher(transport)
        with pytest.raises(PermanentFetcherError, match="validation failed"):
            fetcher.fetch_window(
                "SOLUSDT",
                datetime(2024, 3, 1, tzinfo=timezone.utc),
                datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
            )

    def test_transient_error_retried(self):
        body = json.dumps([_trade_dict()]).encode()
        transport = FakeTransport([
            TransientFetcherError("network glitch"),
            TransientFetcherError("network glitch"),
            body,
        ])
        fetcher = _make_fetcher(transport)
        result = fetcher.fetch_window(
            "SOLUSDT",
            datetime(2024, 3, 1, tzinfo=timezone.utc),
            datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
        )
        assert len(result) == 1
        assert len(transport.urls) == 3

    def test_persistent_transient_error_raises(self):
        transport = FakeTransport([
            TransientFetcherError("network down"),
            TransientFetcherError("network down"),
            TransientFetcherError("network down"),
        ])
        fetcher = _make_fetcher(transport)
        with pytest.raises(TransientFetcherError):
            fetcher.fetch_window(
                "SOLUSDT",
                datetime(2024, 3, 1, tzinfo=timezone.utc),
                datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
            )

    def test_permanent_error_not_retried(self):
        transport = FakeTransport([PermanentFetcherError("HTTP 400: bad symbol")])
        fetcher = _make_fetcher(transport)
        with pytest.raises(PermanentFetcherError):
            fetcher.fetch_window(
                "SOLUSDT",
                datetime(2024, 3, 1, tzinfo=timezone.utc),
                datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
            )
        assert len(transport.urls) == 1


# ─── BinanceTrade dataclass invariants ──────────────────────────────────


class TestTradeDataclass:
    def _trade(self, **overrides) -> BinanceTrade:
        defaults = dict(
            venue="binance",
            instrument="SOLUSDT",
            id=100,
            price=Decimal("150.0"),
            qty=Decimal("1.0"),
            time=datetime(2024, 3, 1, tzinfo=timezone.utc),
            is_buyer_maker=False,
        )
        defaults.update(overrides)
        return BinanceTrade(**defaults)

    def test_content_hash_deterministic(self):
        a = self._trade()
        b = self._trade()
        assert a.content_hash == b.content_hash

    def test_content_hash_excludes_ingested_at(self):
        a = self._trade(ingested_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        b = self._trade(ingested_at=datetime(2026, 6, 1, tzinfo=timezone.utc))
        assert a.content_hash == b.content_hash

    def test_content_hash_changes_on_price_change(self):
        a = self._trade(price=Decimal("150.0"))
        b = self._trade(price=Decimal("150.01"))
        assert a.content_hash != b.content_hash

    def test_uppercase_venue_rejected(self):
        with pytest.raises(ValueError, match="lowercase"):
            self._trade(venue="BINANCE")

    def test_naive_time_rejected(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            self._trade(time=datetime(2024, 3, 1))

    def test_negative_price_rejected(self):
        with pytest.raises(ValueError, match="price must be positive"):
            self._trade(price=Decimal("0"))

    def test_negative_qty_rejected(self):
        with pytest.raises(ValueError, match="qty must be non-negative"):
            self._trade(qty=Decimal("-0.001"))
