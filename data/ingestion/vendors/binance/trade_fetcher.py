"""Binance aggTrades REST fetcher.

Mirrors funding_fetcher.py conventions: injectable HTTP transport,
strict parsing, throttle + retry, no new dependencies.

Pagination advances by (last_trade_time_ms + 1); same-ms boundary
pages dedupe by aggregate-trade id. The defensive cursor-advance
guard fires only when the cursor would go strictly backward
(next_cursor < cursor_ms), which Binance won't do but the guard
catches malformed responses.

Endpoint reference:
  https://binance-docs.github.io/apidocs/futures/en/#compressed-aggregate-trades-list

Day 19b.1 scope: research-quality fetcher for tape-based effective-
spread estimation. Not for live execution.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Protocol

from .trade import BinanceTrade


BINANCE_FAPI_BASE = "https://fapi.binance.com"
AGG_TRADES_PATH = "/fapi/v1/aggTrades"

MAX_LIMIT = 1000
DEFAULT_LIMIT = 1000
MIN_INTERVAL_SECONDS = 0.5

MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 1.0


# ─── Errors ──────────────────────────────────────────────────────────────


class FetcherError(Exception):
    """Base class for fetcher errors."""


class TransientFetcherError(FetcherError):
    """Network error or 5xx; internally retried up to MAX_RETRIES."""


class PermanentFetcherError(FetcherError):
    """4xx or malformed response; do NOT retry."""


# ─── HTTP transport ──────────────────────────────────────────────────────


class HttpTransport(Protocol):
    def get(self, url: str, *, timeout_seconds: float) -> bytes:
        ...


def default_urllib_transport() -> HttpTransport:
    class _UrllibTransport:
        def get(self, url: str, *, timeout_seconds: float) -> bytes:
            req = urllib.request.Request(
                url, headers={"User-Agent": "superhydra-trade-fetcher/0.1"}
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                    return resp.read()
            except urllib.error.HTTPError as e:
                if 400 <= e.code < 500:
                    raise PermanentFetcherError(
                        f"HTTP {e.code} from {url}: {e.reason}"
                    ) from e
                raise TransientFetcherError(
                    f"HTTP {e.code} from {url}: {e.reason}"
                ) from e
            except urllib.error.URLError as e:
                raise TransientFetcherError(
                    f"network error fetching {url}: {e.reason}"
                ) from e
            except TimeoutError as e:
                raise TransientFetcherError(f"timeout fetching {url}") from e

    return _UrllibTransport()


# ─── Fetcher ─────────────────────────────────────────────────────────────


@dataclass
class BinanceTradeFetcher:
    """Pulls historical aggregate trades from Binance USDM-Futures."""

    transport: HttpTransport = field(default_factory=default_urllib_transport)
    timeout_seconds: float = 10.0
    min_interval_seconds: float = MIN_INTERVAL_SECONDS

    _now: Callable[[], float] = field(default=time.monotonic)
    _sleep: Callable[[float], None] = field(default=time.sleep)
    _utcnow: Callable[[], datetime] = field(
        default=lambda: datetime.now(tz=timezone.utc)
    )

    _last_request_at: float | None = field(default=None, init=False, repr=False)

    def fetch_window(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        limit: int = DEFAULT_LIMIT,
        max_pages: int = 1000,
    ) -> list[BinanceTrade]:
        """Return all aggregate trades whose `time` is in [start, end).

        Paginates across multiple aggTrades calls; each call advances
        the start cursor to (last_trade_time_ms + 1) and dedupes by
        aggregate-trade id across page boundaries. Returns trades
        sorted by (time, id) ascending.
        """
        if not symbol or not isinstance(symbol, str):
            raise PermanentFetcherError(
                f"symbol must be a non-empty string, got {symbol!r}"
            )
        if start.tzinfo is None or end.tzinfo is None:
            raise PermanentFetcherError("start and end must be timezone-aware")
        if end <= start:
            raise PermanentFetcherError(
                f"end ({end}) must be strictly after start ({start})"
            )
        if limit < 1 or limit > MAX_LIMIT:
            raise PermanentFetcherError(
                f"limit must be in [1, {MAX_LIMIT}], got {limit}"
            )
        if max_pages < 1:
            raise PermanentFetcherError(
                f"max_pages must be positive, got {max_pages}"
            )

        end_ms = _to_ms(end)
        cursor_ms = _to_ms(start)

        seen_ids: set[int] = set()
        all_trades: list[BinanceTrade] = []
        ingested_at = self._utcnow()

        for page in range(max_pages):
            if cursor_ms >= end_ms:
                break

            params = {
                "symbol": symbol,
                "startTime": cursor_ms,
                "endTime": end_ms,
                "limit": limit,
            }
            url = (
                f"{BINANCE_FAPI_BASE}{AGG_TRADES_PATH}"
                f"?{urllib.parse.urlencode(params)}"
            )

            body = self._get_with_retry(url)
            page_trades = self._parse_response(
                body, expected_symbol=symbol, ingested_at=ingested_at,
            )

            new_trades = [t for t in page_trades if t.id not in seen_ids]
            for t in new_trades:
                seen_ids.add(t.id)
            all_trades.extend(new_trades)

            if not page_trades:
                break
            if len(page_trades) < limit:
                break

            last_time_ms = _to_ms(page_trades[-1].time)
            next_cursor = last_time_ms + 1
            if next_cursor < cursor_ms:
                # Strictly backward = malformed response.
                # Same-ms boundary (next_cursor == cursor_ms) is
                # legitimate and handled by id-based dedupe.
                raise PermanentFetcherError(
                    f"cursor failed to advance at page {page}: "
                    f"prev={cursor_ms} new={next_cursor}; "
                    f"last_trade_time={last_time_ms}"
                )
            cursor_ms = next_cursor

        all_trades.sort(key=lambda t: (t.time, t.id))
        return all_trades

    def _throttle(self) -> None:
        if self._last_request_at is None:
            self._last_request_at = self._now()
            return
        elapsed = self._now() - self._last_request_at
        wait = self.min_interval_seconds - elapsed
        if wait > 0:
            self._sleep(wait)
        self._last_request_at = self._now()

    def _get_with_retry(self, url: str) -> bytes:
        backoff = INITIAL_BACKOFF_SECONDS
        last_err: Exception | None = None
        for attempt in range(MAX_RETRIES):
            self._throttle()
            try:
                return self.transport.get(url, timeout_seconds=self.timeout_seconds)
            except PermanentFetcherError:
                raise
            except TransientFetcherError as e:
                last_err = e
                if attempt < MAX_RETRIES - 1:
                    self._sleep(backoff)
                    backoff *= 2
        assert last_err is not None
        raise last_err

    def _parse_response(
        self,
        body: bytes,
        *,
        expected_symbol: str,
        ingested_at: datetime,
    ) -> list[BinanceTrade]:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise PermanentFetcherError(f"malformed response body: {e}") from e

        if not isinstance(payload, list):
            raise PermanentFetcherError(
                f"expected JSON array, got {type(payload).__name__}: {payload!r}"
            )

        records: list[BinanceTrade] = []
        for raw in payload:
            if not isinstance(raw, dict):
                raise PermanentFetcherError(
                    f"expected dict in array, got {type(raw).__name__}: {raw!r}"
                )

            try:
                trade_id = int(raw["a"])
                price = Decimal(str(raw["p"]))
                qty = Decimal(str(raw["q"]))
                time_ms = int(raw["T"])
                is_buyer_maker = bool(raw["m"])
            except (KeyError, ValueError, TypeError) as e:
                raise PermanentFetcherError(
                    f"malformed trade record {raw!r}: {e}"
                ) from e

            try:
                trade = BinanceTrade(
                    venue="binance",
                    instrument=expected_symbol,
                    id=trade_id,
                    price=price,
                    qty=qty,
                    time=datetime.fromtimestamp(time_ms / 1000, tz=timezone.utc),
                    is_buyer_maker=is_buyer_maker,
                    ingested_at=ingested_at,
                )
            except (ValueError, TypeError) as e:
                raise PermanentFetcherError(
                    f"record validation failed for {raw!r}: {e}"
                ) from e

            records.append(trade)

        return records


def _to_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)
