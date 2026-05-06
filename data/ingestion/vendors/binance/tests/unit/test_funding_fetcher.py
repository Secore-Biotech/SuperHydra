"""Unit tests for data.ingestion.vendors.binance.funding_fetcher.

Coverage:
  - Successful fetch: chronological sort, ingested_at stamp, correct venue
  - Throttle: enforces min interval; first call unthrottled
  - Retry: transient errors retried with backoff; permanent errors bubble
    immediately; retry exhaustion raises last transient error
  - Validation: empty symbol, naive timestamps, end<=start, bad limit
  - Parsing: malformed JSON, wrong shape, missing fields, type errors,
    symbol mismatch, missing markPrice tolerated as None
  - Endpoint URL: correct base, correct path, correct query params
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from data.ingestion.vendors.binance.funding_fetcher import (
    BACKOFF_MULTIPLIER,
    BINANCE_FAPI_BASE,
    FUNDING_RATE_PATH,
    INITIAL_BACKOFF_SECONDS,
    MAX_RETRIES,
    MIN_INTERVAL_SECONDS,
    VENUE,
    FundingRateFetcher,
    PermanentFetcherError,
    TransientFetcherError,
    _to_ms,
)
from data.ingestion.vendors.binance.funding_rate import FundingRate


UTC = timezone.utc

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"


# ─── Fake transport ───────────────────────────────────────────────────────


@dataclass
class FakeTransport:
    """Test double for HttpTransport.

    `responses` is a list of either:
      - bytes  → returned on the next get() call
      - Exception instance → raised on the next get() call

    Calls are recorded in `calls` for assertions on URL / params.
    """

    responses: list = field(default_factory=list)
    calls: list[tuple[str, float]] = field(default_factory=list)

    def get(self, url: str, *, timeout_seconds: float) -> bytes:
        self.calls.append((url, timeout_seconds))
        if not self.responses:
            raise AssertionError(
                f"FakeTransport received unexpected call #{len(self.calls)} to {url!r}"
            )
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def _load_fixture(name: str) -> bytes:
    return (FIXTURE_DIR / name).read_text().encode("utf-8")


# ─── Synthetic clock + sleep ──────────────────────────────────────────────


@dataclass
class FakeClock:
    """Monotonic clock + sleep for deterministic throttle/backoff tests."""

    t: float = 0.0
    sleeps: list[float] = field(default_factory=list)

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


# ─── Test fixtures (helpers) ──────────────────────────────────────────────


def _make_fetcher(
    *,
    transport: FakeTransport,
    clock: FakeClock | None = None,
    min_interval: float = MIN_INTERVAL_SECONDS,
    pinned_ingested_at: datetime | None = None,
) -> FundingRateFetcher:
    clock = clock or FakeClock()
    if pinned_ingested_at is None:
        pinned_ingested_at = datetime(2026, 1, 16, 0, 0, 0, tzinfo=UTC)

    return FundingRateFetcher(
        transport=transport,
        min_interval_seconds=min_interval,
        _now=clock.now,
        _sleep=clock.sleep,
        _utcnow=lambda: pinned_ingested_at,
    )


# ─── Successful fetch ─────────────────────────────────────────────────────


def test_fetch_window_returns_canonical_records():
    transport = FakeTransport(responses=[_load_fixture("btcusdt_3records.json")])
    fetcher = _make_fetcher(transport=transport)

    start = datetime(2026, 1, 14, 0, 0, 0, tzinfo=UTC)
    end = datetime(2026, 1, 16, 0, 0, 0, tzinfo=UTC)
    records = fetcher.fetch_window("BTCUSDT", start, end)

    assert len(records) == 3
    assert all(isinstance(r, FundingRate) for r in records)
    assert all(r.venue == VENUE for r in records)
    assert all(r.instrument == "BTCUSDT" for r in records)


def test_fetch_window_records_sorted_by_funding_time():
    """Sort is defensive even though Binance returns oldest-first by default."""
    transport = FakeTransport(responses=[_load_fixture("btcusdt_3records.json")])
    fetcher = _make_fetcher(transport=transport)

    records = fetcher.fetch_window(
        "BTCUSDT",
        datetime(2026, 1, 14, tzinfo=UTC),
        datetime(2026, 1, 16, tzinfo=UTC),
    )

    times = [r.funding_time for r in records]
    assert times == sorted(times)


def test_fetch_window_stamps_ingested_at():
    pinned = datetime(2026, 5, 6, 21, 0, 0, tzinfo=UTC)
    transport = FakeTransport(responses=[_load_fixture("btcusdt_3records.json")])
    fetcher = _make_fetcher(transport=transport, pinned_ingested_at=pinned)

    records = fetcher.fetch_window(
        "BTCUSDT",
        datetime(2026, 1, 14, tzinfo=UTC),
        datetime(2026, 1, 16, tzinfo=UTC),
    )

    for r in records:
        assert r.ingested_at == pinned


def test_fetch_window_correct_endpoint_and_params():
    transport = FakeTransport(responses=[b"[]"])
    fetcher = _make_fetcher(transport=transport)

    start = datetime(2026, 1, 14, 0, 0, 0, tzinfo=UTC)
    end = datetime(2026, 1, 16, 0, 0, 0, tzinfo=UTC)
    fetcher.fetch_window("BTCUSDT", start, end, limit=500)

    assert len(transport.calls) == 1
    url, _timeout = transport.calls[0]
    assert url.startswith(f"{BINANCE_FAPI_BASE}{FUNDING_RATE_PATH}?")
    assert "symbol=BTCUSDT" in url
    assert f"startTime={_to_ms(start)}" in url
    assert f"endTime={_to_ms(end)}" in url
    assert "limit=500" in url


def test_fetch_window_empty_response_yields_empty_list():
    transport = FakeTransport(responses=[b"[]"])
    fetcher = _make_fetcher(transport=transport)

    records = fetcher.fetch_window(
        "BTCUSDT",
        datetime(2026, 1, 14, tzinfo=UTC),
        datetime(2026, 1, 16, tzinfo=UTC),
    )

    assert records == []


# ─── Argument validation ──────────────────────────────────────────────────


def test_rejects_empty_symbol():
    fetcher = _make_fetcher(transport=FakeTransport())
    with pytest.raises(PermanentFetcherError, match="symbol"):
        fetcher.fetch_window(
            "",
            datetime(2026, 1, 14, tzinfo=UTC),
            datetime(2026, 1, 16, tzinfo=UTC),
        )


def test_rejects_naive_start():
    fetcher = _make_fetcher(transport=FakeTransport())
    with pytest.raises(PermanentFetcherError, match="timezone-aware"):
        fetcher.fetch_window(
            "BTCUSDT",
            datetime(2026, 1, 14),  # naive
            datetime(2026, 1, 16, tzinfo=UTC),
        )


def test_rejects_naive_end():
    fetcher = _make_fetcher(transport=FakeTransport())
    with pytest.raises(PermanentFetcherError, match="timezone-aware"):
        fetcher.fetch_window(
            "BTCUSDT",
            datetime(2026, 1, 14, tzinfo=UTC),
            datetime(2026, 1, 16),  # naive
        )


def test_rejects_end_not_after_start():
    fetcher = _make_fetcher(transport=FakeTransport())
    same = datetime(2026, 1, 14, tzinfo=UTC)
    with pytest.raises(PermanentFetcherError, match="strictly after"):
        fetcher.fetch_window("BTCUSDT", same, same)
    with pytest.raises(PermanentFetcherError, match="strictly after"):
        fetcher.fetch_window("BTCUSDT", same, same - timedelta(seconds=1))


def test_rejects_bad_limit():
    fetcher = _make_fetcher(transport=FakeTransport())
    with pytest.raises(PermanentFetcherError, match="limit"):
        fetcher.fetch_window(
            "BTCUSDT",
            datetime(2026, 1, 14, tzinfo=UTC),
            datetime(2026, 1, 16, tzinfo=UTC),
            limit=0,
        )
    with pytest.raises(PermanentFetcherError, match="limit"):
        fetcher.fetch_window(
            "BTCUSDT",
            datetime(2026, 1, 14, tzinfo=UTC),
            datetime(2026, 1, 16, tzinfo=UTC),
            limit=1001,
        )


# ─── Retry behaviour ──────────────────────────────────────────────────────


def test_transient_error_retried_with_backoff():
    """Two transient errors followed by success → 3 transport calls,
    2 backoff sleeps with exponential growth."""
    body = b"[]"
    transport = FakeTransport(responses=[
        TransientFetcherError("network 1"),
        TransientFetcherError("network 2"),
        body,
    ])
    clock = FakeClock()
    fetcher = _make_fetcher(transport=transport, clock=clock)

    fetcher.fetch_window(
        "BTCUSDT",
        datetime(2026, 1, 14, tzinfo=UTC),
        datetime(2026, 1, 16, tzinfo=UTC),
    )

    assert len(transport.calls) == 3
    # Backoff sleeps: INITIAL, INITIAL*MULTIPLIER (in addition to throttle
    # waits, which are zero on the first call and then enforced after each
    # subsequent call). We filter for the backoff sleeps specifically.
    assert INITIAL_BACKOFF_SECONDS in clock.sleeps
    assert INITIAL_BACKOFF_SECONDS * BACKOFF_MULTIPLIER in clock.sleeps


def test_permanent_error_not_retried():
    """A 4xx-ish PermanentFetcherError must surface immediately, no retry."""
    transport = FakeTransport(responses=[
        PermanentFetcherError("HTTP 400"),
        # If retried, this would be hit:
        b"[]",
    ])
    fetcher = _make_fetcher(transport=transport)

    with pytest.raises(PermanentFetcherError, match="400"):
        fetcher.fetch_window(
            "BTCUSDT",
            datetime(2026, 1, 14, tzinfo=UTC),
            datetime(2026, 1, 16, tzinfo=UTC),
        )

    assert len(transport.calls) == 1


def test_retry_exhaustion_raises_last_transient():
    """MAX_RETRIES + 1 failed attempts → last error is raised."""
    transport = FakeTransport(responses=[
        TransientFetcherError(f"network {i}") for i in range(MAX_RETRIES + 1)
    ])
    fetcher = _make_fetcher(transport=transport)

    with pytest.raises(TransientFetcherError, match=f"network {MAX_RETRIES}"):
        fetcher.fetch_window(
            "BTCUSDT",
            datetime(2026, 1, 14, tzinfo=UTC),
            datetime(2026, 1, 16, tzinfo=UTC),
        )

    assert len(transport.calls) == MAX_RETRIES + 1


# ─── Throttle ─────────────────────────────────────────────────────────────


def test_first_call_unthrottled():
    """No sleep on the first call — throttle has no prior reference point."""
    transport = FakeTransport(responses=[b"[]"])
    clock = FakeClock()
    fetcher = _make_fetcher(transport=transport, clock=clock)

    fetcher.fetch_window(
        "BTCUSDT",
        datetime(2026, 1, 14, tzinfo=UTC),
        datetime(2026, 1, 16, tzinfo=UTC),
    )
    assert clock.sleeps == []


def test_second_call_enforces_min_interval():
    """If the second call comes <min_interval after the first, throttle
    sleeps the difference."""
    transport = FakeTransport(responses=[b"[]", b"[]"])
    clock = FakeClock()
    fetcher = _make_fetcher(
        transport=transport, clock=clock, min_interval=0.5
    )

    # First fetch — no throttle.
    fetcher.fetch_window(
        "BTCUSDT",
        datetime(2026, 1, 14, tzinfo=UTC),
        datetime(2026, 1, 16, tzinfo=UTC),
    )
    sleeps_after_first = list(clock.sleeps)
    assert sleeps_after_first == []

    # Advance clock by 0.1s (less than 0.5s interval) and fetch again.
    clock.t += 0.1
    fetcher.fetch_window(
        "BTCUSDT",
        datetime(2026, 1, 14, tzinfo=UTC),
        datetime(2026, 1, 16, tzinfo=UTC),
    )
    # Expected: throttle slept 0.5 - 0.1 = 0.4s before the second call.
    assert pytest.approx(clock.sleeps[0], rel=1e-9) == 0.4


# ─── Parsing errors ───────────────────────────────────────────────────────


def test_malformed_json_raises_permanent():
    transport = FakeTransport(responses=[b"not json"])
    fetcher = _make_fetcher(transport=transport)

    with pytest.raises(PermanentFetcherError, match="JSON"):
        fetcher.fetch_window(
            "BTCUSDT",
            datetime(2026, 1, 14, tzinfo=UTC),
            datetime(2026, 1, 16, tzinfo=UTC),
        )


def test_response_not_list_raises_permanent():
    transport = FakeTransport(responses=[b'{"unexpected": "object"}'])
    fetcher = _make_fetcher(transport=transport)

    with pytest.raises(PermanentFetcherError, match="list"):
        fetcher.fetch_window(
            "BTCUSDT",
            datetime(2026, 1, 14, tzinfo=UTC),
            datetime(2026, 1, 16, tzinfo=UTC),
        )


def test_venue_error_response_raises_permanent():
    body = json.dumps({"code": -1121, "msg": "Invalid symbol."}).encode("utf-8")
    transport = FakeTransport(responses=[body])
    fetcher = _make_fetcher(transport=transport)

    with pytest.raises(PermanentFetcherError, match="Invalid symbol"):
        fetcher.fetch_window(
            "BTCUSDT",
            datetime(2026, 1, 14, tzinfo=UTC),
            datetime(2026, 1, 16, tzinfo=UTC),
        )


def test_symbol_mismatch_raises_permanent():
    """Record symbol differs from request symbol → fail loudly, not silently
    ingest under the wrong instrument."""
    body = json.dumps([{
        "symbol": "ETHUSDT",  # ← mismatch
        "fundingTime": 1736870400000,
        "fundingRate": "0.00010000",
        "markPrice": "3500.00000000",
    }]).encode("utf-8")
    transport = FakeTransport(responses=[body])
    fetcher = _make_fetcher(transport=transport)

    with pytest.raises(PermanentFetcherError, match="symbol mismatch"):
        fetcher.fetch_window(
            "BTCUSDT",
            datetime(2026, 1, 14, tzinfo=UTC),
            datetime(2026, 1, 16, tzinfo=UTC),
        )


def test_missing_funding_time_raises_permanent():
    body = json.dumps([{
        "symbol": "BTCUSDT",
        "fundingRate": "0.00010000",
        # fundingTime missing
    }]).encode("utf-8")
    transport = FakeTransport(responses=[body])
    fetcher = _make_fetcher(transport=transport)

    with pytest.raises(PermanentFetcherError, match="malformed record at index 0"):
        fetcher.fetch_window(
            "BTCUSDT",
            datetime(2026, 1, 14, tzinfo=UTC),
            datetime(2026, 1, 16, tzinfo=UTC),
        )


def test_funding_rate_not_string_raises_permanent():
    body = json.dumps([{
        "symbol": "BTCUSDT",
        "fundingTime": 1736870400000,
        "fundingRate": 0.0001,  # ← number not string; vendor always sends string
    }]).encode("utf-8")
    transport = FakeTransport(responses=[body])
    fetcher = _make_fetcher(transport=transport)

    with pytest.raises(PermanentFetcherError, match="fundingRate"):
        fetcher.fetch_window(
            "BTCUSDT",
            datetime(2026, 1, 14, tzinfo=UTC),
            datetime(2026, 1, 16, tzinfo=UTC),
        )


def test_missing_mark_price_tolerated_as_none():
    """markPrice is sometimes absent or empty; treat as None, not an error."""
    body = json.dumps([
        {
            "symbol": "BTCUSDT",
            "fundingTime": 1736870400000,
            "fundingRate": "0.00010000",
            # markPrice absent
        },
        {
            "symbol": "BTCUSDT",
            "fundingTime": 1736899200000,
            "fundingRate": "0.00012000",
            "markPrice": "",  # empty string — also tolerated
        },
    ]).encode("utf-8")
    transport = FakeTransport(responses=[body])
    fetcher = _make_fetcher(transport=transport)

    records = fetcher.fetch_window(
        "BTCUSDT",
        datetime(2026, 1, 14, tzinfo=UTC),
        datetime(2026, 1, 16, tzinfo=UTC),
    )

    assert len(records) == 2
    assert all(r.mark_price is None for r in records)


def test_decimal_precision_preserved_through_pipeline():
    body = json.dumps([{
        "symbol": "BTCUSDT",
        "fundingTime": 1736870400000,
        "fundingRate": "-0.00012345",
        "markPrice": "98765.43210000",
    }]).encode("utf-8")
    transport = FakeTransport(responses=[body])
    fetcher = _make_fetcher(transport=transport)

    records = fetcher.fetch_window(
        "BTCUSDT",
        datetime(2026, 1, 14, tzinfo=UTC),
        datetime(2026, 1, 16, tzinfo=UTC),
    )

    assert records[0].funding_rate == Decimal("-0.00012345")
    assert records[0].mark_price == Decimal("98765.43210000")
