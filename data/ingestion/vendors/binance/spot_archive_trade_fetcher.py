"""Binance Spot archive trade fetcher.

Day 26 deliverable. Mirror of BinanceArchiveTradeFetcher (perp) with
the SPOT URL path. Per Day 26.1 reviewer lock: new class, not a
refactor of the perp fetcher path.

URL pattern (perp vs spot):
  perp: /data/futures/um/monthly/aggTrades/{symbol}/{symbol}-aggTrades-{YYYY}-{MM}.zip
  spot: /data/spot/monthly/aggTrades/{symbol}/{symbol}-aggTrades-{YYYY}-{MM}.zip

Both archives have the same CSV schema (7 columns: aggId, price, qty,
firstTradeId, lastTradeId, timestamp, isBuyerMaker), so the parsing
helpers from archive_trade_fetcher.py are reused as-is.

Recon (Day 26 precondition):
  HTTP/2 200, 321MB ZIP for SOLUSDT-aggTrades-2024-03.zip
  Confirmed spot archive is accessible and structurally parallel to
  the perp archive.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from data.ingestion.vendors.binance.archive_trade_fetcher import (
    BINANCE_VISION_BASE,
    DEFAULT_TIMEOUT_SECONDS,
    INITIAL_BACKOFF_SECONDS,
    MAX_RETRIES,
    MIN_INTERVAL_SECONDS,
    _iter_trades_in_window,
    _months_overlapping,
    _sort_and_dedupe,
)
from data.ingestion.vendors.binance.trade import BinanceTrade
from data.ingestion.vendors.binance.trade_fetcher import (
    HttpTransport,
    PermanentFetcherError,
    TransientFetcherError,
    default_urllib_transport,
)


# Spot-specific URL pattern. Verified via curl recon (Day 26).
SPOT_ARCHIVE_PATH_TEMPLATE = (
    "/data/spot/monthly/aggTrades/{symbol}/"
    "{symbol}-aggTrades-{year:04d}-{month:02d}.zip"
)

# Separate cache directory so spot ZIPs do not collide with perp ZIPs
# (same filename pattern; different contents).
DEFAULT_SPOT_CACHE_DIR = Path("artifacts/cache/binance_archive_spot")


def _build_spot_archive_url(symbol: str, year: int, month: int) -> str:
    """Construct the Binance Vision URL for one symbol/year/month."""
    path = SPOT_ARCHIVE_PATH_TEMPLATE.format(
        symbol=symbol, year=year, month=month,
    )
    return f"{BINANCE_VISION_BASE}{path}"


@dataclass
class BinanceSpotArchiveTradeFetcher:
    """Pulls historical aggregate trades from Binance Spot archives.

    Structural twin of BinanceArchiveTradeFetcher (perp). Same window
    semantics, same throttle, same parsing helpers — only the URL
    template and default cache directory differ.
    """

    transport: HttpTransport = field(default_factory=default_urllib_transport)
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    cache_dir: Path = field(default_factory=lambda: DEFAULT_SPOT_CACHE_DIR)
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
    ) -> list[BinanceTrade]:
        """Return all aggregate spot trades whose `time` is in [start, end).

        Mirrors BinanceArchiveTradeFetcher.fetch_window semantics: enumerate
        calendar months overlapping the window, fetch each archive (cache
        or HTTP), stream trades matching the window from each archive's
        CSV, accumulate, sort by (time, id), dedupe by id.
        """
        if not symbol or not isinstance(symbol, str):
            raise PermanentFetcherError(
                f"symbol must be a non-empty string, got {symbol!r}"
            )
        if start.tzinfo is None or end.tzinfo is None:
            raise PermanentFetcherError(
                "start and end must be timezone-aware"
            )
        if end <= start:
            raise PermanentFetcherError(
                f"end ({end}) must be strictly after start ({start})"
            )

        ingested_at = self._utcnow()
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)

        all_trades: list[BinanceTrade] = []

        for year, month in _months_overlapping(start, end):
            archive_bytes = self._fetch_archive(symbol, year, month)
            for trade in _iter_trades_in_window(
                archive_bytes,
                symbol=symbol,
                start_ms=start_ms,
                end_ms=end_ms,
                ingested_at=ingested_at,
            ):
                all_trades.append(trade)

        return _sort_and_dedupe(all_trades)

    def _fetch_archive(
        self, symbol: str, year: int, month: int,
    ) -> bytes:
        """Fetch one archive ZIP (cache or HTTP). Mirror of perp helper."""
        filename = f"{symbol}-aggTrades-{year:04d}-{month:02d}.zip"
        cache_path = self.cache_dir / symbol / filename

        if cache_path.exists():
            return cache_path.read_bytes()

        url = _build_spot_archive_url(symbol, year, month)
        archive_bytes = self._throttled_get(url)

        # Persist to cache for future calls.
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(archive_bytes)
        return archive_bytes

    def _throttled_get(self, url: str) -> bytes:
        """Apply throttle + retry policy to a single HTTP GET."""
        if self._last_request_at is not None:
            elapsed = self._now() - self._last_request_at
            wait = self.min_interval_seconds - elapsed
            if wait > 0:
                self._sleep(wait)

        backoff = INITIAL_BACKOFF_SECONDS
        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self._last_request_at = self._now()
                response = self.transport(url, timeout=self.timeout_seconds)
                # response: bytes (the archive)
                return response
            except TransientFetcherError as e:
                last_exc = e
                if attempt < MAX_RETRIES:
                    self._sleep(backoff)
                    backoff *= 2

        assert last_exc is not None
        raise last_exc
