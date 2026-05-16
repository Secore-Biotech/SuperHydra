"""Binance Vision archive klines (OHLCV bars) fetcher.

Companion to BinanceArchiveTradeFetcher: where that module fetches
tick-level aggTrades, this fetches OHLCV bars at configurable intervals.

Use cases:
  - Universe construction (ADV from 1d quote_volume).
  - Factor return computation (1d close-to-close returns).
  - Coarse historical price reconstruction without ingesting tick data.

Mirrors BinanceArchiveTradeFetcher's structure: monthly archives,
streaming CSV parsing, throttled HTTP with retry, on-disk cache,
sort + dedupe by (open_time).

Archive URL pattern:
  https://data.binance.vision/data/futures/um/monthly/klines/
      {symbol}/{interval}/{symbol}-{interval}-{YYYY}-{MM}.zip

Interval is fetcher-instance state (not per-call). Construct one
fetcher per interval ("1d", "1h", etc.). This matches the natural
caller pattern: a universe-computation script wants 1d klines; a
factor backtest wants 1d klines for returns; an intraday strategy
might want 5m klines. Mixing intervals in one fetcher would complicate
caching keys and serve no real use case.

Cache location: artifacts/cache/binance_klines_{interval}/.
"""
from __future__ import annotations

import csv
import io
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Iterator

from .kline import BinanceKline
from .trade_fetcher import (
    HttpTransport,
    PermanentFetcherError,
    TransientFetcherError,
    default_urllib_transport,
)


BINANCE_VISION_BASE = "https://data.binance.vision"
ARCHIVE_PATH_TEMPLATE = (
    "/data/futures/um/monthly/klines/{symbol}/{interval}/"
    "{symbol}-{interval}-{year:04d}-{month:02d}.zip"
)

MIN_INTERVAL_SECONDS = 0.5
DEFAULT_TIMEOUT_SECONDS = 60.0
MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 2.0


def _default_cache_dir_for(interval: str) -> Path:
    return Path(f"artifacts/cache/binance_klines_{interval}")


@dataclass
class BinanceKlinesArchiveFetcher:
    """Pulls historical klines from data.binance.vision monthly archives.

    interval: bar interval string per Binance convention ("1d", "1h",
        "15m", "5m", "1m"). Locked at construction time.
    """

    interval: str = "1d"
    transport: HttpTransport = field(default_factory=default_urllib_transport)
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    cache_dir: Path | None = None
    min_interval_seconds: float = MIN_INTERVAL_SECONDS

    _now: Callable[[], float] = field(default=time.monotonic)
    _sleep: Callable[[float], None] = field(default=time.sleep)
    _utcnow: Callable[[], datetime] = field(
        default=lambda: datetime.now(tz=timezone.utc)
    )

    _last_request_at: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self):
        if not self.interval:
            raise ValueError("interval must be non-empty")
        if self.cache_dir is None:
            self.cache_dir = _default_cache_dir_for(self.interval)

    def fetch_window(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> list[BinanceKline]:
        """Return all klines whose open_time is in [start, end).

        Multi-month windows enumerate (year, month) tuples, fetch each
        archive (cache or HTTP), stream-parse, filter by open_time,
        accumulate, sort+dedupe.
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

        all_klines: list[BinanceKline] = []
        for year, month in _months_overlapping(start, end):
            archive_bytes = self._fetch_archive(symbol, year, month)
            if archive_bytes is None:
                # 404 - month not yet archived or symbol not active that month.
                # Continue; do not raise. Caller can detect absence via empty
                # return.
                continue
            for kline in _iter_klines_in_window(
                archive_bytes,
                symbol=symbol,
                interval=self.interval,
                start_ms=start_ms,
                end_ms=end_ms,
                ingested_at=ingested_at,
            ):
                all_klines.append(kline)

        return _sort_and_dedupe(all_klines)

    def _fetch_archive(self, symbol: str, year: int, month: int) -> bytes | None:
        """Fetch one monthly archive. Returns None on 404 (not yet archived
        or symbol not active that month)."""
        filename = (
            f"{symbol}-{self.interval}-{year:04d}-{month:02d}.zip"
        )
        cache_path = self.cache_dir / filename
        not_found_marker = cache_path.with_suffix(".zip.notfound")

        if cache_path.exists():
            return cache_path.read_bytes()
        if not_found_marker.exists():
            return None

        url_path = ARCHIVE_PATH_TEMPLATE.format(
            symbol=symbol, interval=self.interval,
            year=year, month=month,
        )
        url = f"{BINANCE_VISION_BASE}{url_path}"
        try:
            body = self._get_with_retry(url)
        except PermanentFetcherError as e:
            # 404 = archive not present. Cache the absence so we don't
            # re-request on subsequent calls (universe-computation runs
            # many candidates; a missing month for one symbol shouldn't
            # be re-requested).
            if "404" in str(e) or "not found" in str(e).lower():
                not_found_marker.parent.mkdir(parents=True, exist_ok=True)
                not_found_marker.write_text("")
                return None
            raise

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(body)
        return body

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
                return self.transport.get(
                    url, timeout_seconds=self.timeout_seconds,
                )
            except PermanentFetcherError:
                raise
            except TransientFetcherError as e:
                last_err = e
                if attempt < MAX_RETRIES - 1:
                    self._sleep(backoff)
                    backoff *= 2
        assert last_err is not None
        raise last_err


def _months_overlapping(start: datetime, end: datetime) -> Iterator[tuple[int, int]]:
    """Yield (year, month) tuples for every calendar month that overlaps
    [start, end). end is exclusive."""
    cursor = datetime(start.year, start.month, 1, tzinfo=timezone.utc)
    while cursor < end:
        yield (cursor.year, cursor.month)
        if cursor.month == 12:
            cursor = datetime(cursor.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            cursor = datetime(cursor.year, cursor.month + 1, 1, tzinfo=timezone.utc)


def _iter_klines_in_window(
    archive_bytes: bytes,
    *,
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
    ingested_at: datetime,
) -> Iterator[BinanceKline]:
    """Stream klines from one monthly ZIP archive, yielding only those
    with open_time in [start_ms, end_ms)."""
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zf:
        names = zf.namelist()
        csv_names = [n for n in names if n.lower().endswith(".csv")]
        if not csv_names:
            raise PermanentFetcherError(
                f"no CSV in archive: {names}"
            )
        with zf.open(csv_names[0]) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
            reader = csv.reader(text)
            first = True
            for row in reader:
                if not row:
                    continue
                if first:
                    first = False
                    # Header sniff: try int on first cell. If it fails,
                    # this is a header row (post-2022 archives sometimes
                    # have one). Otherwise treat as data.
                    try:
                        int(row[0])
                    except (ValueError, IndexError):
                        continue
                try:
                    kline = _parse_kline_row(
                        row, symbol=symbol, interval=interval,
                        ingested_at=ingested_at,
                    )
                except (ValueError, IndexError, InvalidOperation) as e:
                    raise PermanentFetcherError(
                        f"failed to parse kline row {row[:4]}...: {e}"
                    )
                open_time_ms = int(kline.open_time.timestamp() * 1000)
                if start_ms <= open_time_ms < end_ms:
                    yield kline


def _parse_kline_row(
    row: list[str],
    *,
    symbol: str,
    interval: str,
    ingested_at: datetime,
) -> BinanceKline:
    """Parse one CSV row from a Binance futures kline archive.

    Column order (Binance futures klines):
      0: open_time (ms)
      1: open
      2: high
      3: low
      4: close
      5: volume (base)
      6: close_time (ms)
      7: quote_volume
      8: trade_count
      9: taker_buy_volume (base)
      10: taker_buy_quote_volume
      11: ignore
    """
    if len(row) < 11:
        raise ValueError(f"expected >= 11 columns, got {len(row)}")
    return BinanceKline(
        venue="binance",
        instrument=symbol,
        interval=interval,
        open_time=datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc),
        open=Decimal(row[1]),
        high=Decimal(row[2]),
        low=Decimal(row[3]),
        close=Decimal(row[4]),
        volume=Decimal(row[5]),
        quote_volume=Decimal(row[7]),
        trade_count=int(row[8]),
        taker_buy_volume=Decimal(row[9]),
        taker_buy_quote_volume=Decimal(row[10]),
        ingested_at=ingested_at,
    )


def _sort_and_dedupe(klines: list[BinanceKline]) -> list[BinanceKline]:
    """Sort by open_time; dedupe by open_time, raising on content mismatch."""
    sorted_klines = sorted(klines, key=lambda k: k.open_time)
    deduped: list[BinanceKline] = []
    seen: dict[datetime, str] = {}
    for k in sorted_klines:
        prior_hash = seen.get(k.open_time)
        if prior_hash is None:
            seen[k.open_time] = k.content_hash
            deduped.append(k)
            continue
        if prior_hash != k.content_hash:
            raise PermanentFetcherError(
                f"duplicate open_time {k.open_time.isoformat()} with "
                f"different content hashes: {prior_hash} vs {k.content_hash}"
            )
        # Same content hash - silent dedupe (idempotent).
    return deduped
