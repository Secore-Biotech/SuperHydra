"""Binance Vision archive trade fetcher.

Pulls historical aggregate trades from data.binance.vision monthly
archives. The companion to trade_fetcher.py: where the REST
/fapi/v1/aggTrades endpoint serves recent history only (operational
TTL discovered in Day 19b closing), this archive fetcher serves
arbitrary historical depth back to the symbol's listing date.

Mirrors BinanceTradeFetcher's public API:

    fetcher = BinanceArchiveTradeFetcher()
    trades = fetcher.fetch_window(
        "SOLUSDT",
        datetime(2024, 3, 1, tzinfo=timezone.utc),
        datetime(2024, 3, 1, 1, tzinfo=timezone.utc),
    )

Design properties:

  - Reuses HttpTransport, FetcherError hierarchy, and
    default_urllib_transport from trade_fetcher.py. No duplication.

  - Streaming decompression. zipfile.ZipFile.open() yields a binary
    stream; io.TextIOWrapper wraps it as text; csv.reader iterates
    line-by-line. Only rows whose Timestamp falls in [start_ms, end_ms)
    are materialized into BinanceTrade. A monthly archive can hold
    50M+ trades; we never load the full CSV into memory.

  - Multi-month support. Windows crossing month boundaries enumerate
    (year, month) tuples overlapping [start, end), fetch each archive,
    filter+merge.

  - Cache at artifacts/cache/binance_archive/ by default (gitignored
    via the artifacts/ rule). Cache filename is
    {symbol}-aggTrades-{YYYY}-{MM}.zip. Cache hit avoids HTTP entirely.
    Cache filenames preserved per Day 19c reviewer amendment so future
    .CHECKSUM verification can be added without changing API or
    filenames (TODO below).

  - Header sniffing. Pre-2022 archives have no header row; post-2022
    archives sometimes do. Sniff first row's first cell: if int()
    parses, treat as data; if not, skip as header.

  - Sort + dedupe by (time, id). Within a single fetch_window across
    one or more months, the same aggregate trade id must not appear
    with different content. If it does, raise PermanentFetcherError.

Day 19c scope: research-quality archive ingestion for tape-based
effective-spread estimation in deep history. Not for live execution.

# TODO (deferred from Day 19c per reviewer amendment to Q2):
# Add optional .CHECKSUM verification. Each archive has a sibling
# {symbol}-aggTrades-{YYYY}-{MM}.zip.CHECKSUM file at data.binance.vision
# with SHA-256. Cache layout already supports this: store alongside as
# {filename}.CHECKSUM. Fetcher gains a `verify_checksum` kwarg
# (default False); when True, fetches the .CHECKSUM file, computes
# sha256 of the .zip, raises on mismatch.
"""
from __future__ import annotations

import csv
import io
import time
import urllib.parse
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Iterator

from .trade import BinanceTrade
from .trade_fetcher import (
    FetcherError,
    HttpTransport,
    PermanentFetcherError,
    TransientFetcherError,
    default_urllib_transport,
)


BINANCE_VISION_BASE = "https://data.binance.vision"
ARCHIVE_PATH_TEMPLATE = (
    "/data/futures/um/monthly/aggTrades/{symbol}/"
    "{symbol}-aggTrades-{year:04d}-{month:02d}.zip"
)
DEFAULT_CACHE_DIR = Path("artifacts/cache/binance_archive")

MIN_INTERVAL_SECONDS = 0.5
DEFAULT_TIMEOUT_SECONDS = 120.0
MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 2.0


@dataclass
class BinanceArchiveTradeFetcher:
    """Pulls historical aggregate trades from data.binance.vision archives.

    Stateless across calls except for the throttle clock and the
    injected transport. A single instance can serve many symbols and
    months.
    """

    transport: HttpTransport = field(default_factory=default_urllib_transport)
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    cache_dir: Path = field(default_factory=lambda: DEFAULT_CACHE_DIR)
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
        """Return all aggregate trades whose `time` is in [start, end).

        Enumerates calendar months overlapping the window, fetches each
        archive (cache or HTTP), streams trades matching the window
        from each archive's CSV, accumulates, sorts by (time, id),
        dedupes by id (raising on conflicting content_hash), returns.
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

    def _fetch_archive(self, symbol: str, year: int, month: int) -> bytes:
        filename = f"{symbol}-aggTrades-{year:04d}-{month:02d}.zip"
        cache_path = self.cache_dir / filename

        if cache_path.exists():
            return cache_path.read_bytes()

        url_path = ARCHIVE_PATH_TEMPLATE.format(
            symbol=symbol, year=year, month=month,
        )
        url = f"{BINANCE_VISION_BASE}{url_path}"
        body = self._get_with_retry(url)

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


# ─── Module-level helpers (pure functions; testable in isolation) ───────


def _months_overlapping(start: datetime, end: datetime) -> Iterator[tuple[int, int]]:
    """Yield (year, month) tuples for each calendar month overlapping
    [start, end).

    `end` is exclusive: a window ending exactly at midnight first of a
    month does NOT include that month.

    Examples:
      [2024-03-01, 2024-03-15) → [(2024, 3)]
      [2024-02-28, 2024-03-05) → [(2024, 2), (2024, 3)]
      [2024-12-15, 2025-01-15) → [(2024, 12), (2025, 1)]
      [2024-03-01, 2024-04-01) → [(2024, 3)]
    """
    last_inst = end - timedelta(microseconds=1)
    cur_year, cur_month = start.year, start.month
    last_year, last_month = last_inst.year, last_inst.month
    while (cur_year, cur_month) <= (last_year, last_month):
        yield (cur_year, cur_month)
        if cur_month == 12:
            cur_year += 1
            cur_month = 1
        else:
            cur_month += 1


def _iter_trades_in_window(
    archive_bytes: bytes,
    *,
    symbol: str,
    start_ms: int,
    end_ms: int,
    ingested_at: datetime,
) -> Iterator[BinanceTrade]:
    """Stream the inner CSV of a Binance Vision aggTrades zip,
    yielding BinanceTrade for rows with Timestamp in [start_ms, end_ms).
    """
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zf:
        names = zf.namelist()
        if len(names) != 1:
            raise PermanentFetcherError(
                f"expected exactly 1 entry in archive, got {len(names)}: {names}"
            )
        csv_name = names[0]

        with zf.open(csv_name) as raw:
            text_stream = io.TextIOWrapper(raw, encoding="utf-8", newline="")
            reader = csv.reader(text_stream)

            header_check_done = False
            for row in reader:
                if not header_check_done:
                    header_check_done = True
                    if not row:
                        continue
                    try:
                        int(row[0])
                    except ValueError:
                        # Non-numeric first cell — header row, skip it.
                        continue
                    # Numeric first cell — first row is data; fall through.

                if len(row) != 7:
                    raise PermanentFetcherError(
                        f"expected 7 columns in CSV row, got {len(row)}: {row}"
                    )

                try:
                    agg_id = int(row[0])
                    price = Decimal(row[1])
                    qty = Decimal(row[2])
                    time_ms = int(row[5])
                    is_buyer_maker_str = row[6].strip().lower()
                except (ValueError, InvalidOperation) as e:
                    raise PermanentFetcherError(
                        f"malformed CSV row {row!r}: {e}"
                    ) from e

                if is_buyer_maker_str == "true":
                    is_buyer_maker = True
                elif is_buyer_maker_str == "false":
                    is_buyer_maker = False
                else:
                    raise PermanentFetcherError(
                        f"unexpected is_buyer_maker value in row {row!r}: "
                        f"{row[6]!r}"
                    )

                if time_ms < start_ms or time_ms >= end_ms:
                    continue

                try:
                    yield BinanceTrade(
                        venue="binance",
                        instrument=symbol,
                        id=agg_id,
                        price=price,
                        qty=qty,
                        time=datetime.fromtimestamp(time_ms / 1000, tz=timezone.utc),
                        is_buyer_maker=is_buyer_maker,
                        ingested_at=ingested_at,
                    )
                except (ValueError, TypeError) as e:
                    raise PermanentFetcherError(
                        f"record validation failed for row {row!r}: {e}"
                    ) from e


def _sort_and_dedupe(trades: list[BinanceTrade]) -> list[BinanceTrade]:
    """Sort by (time, id); dedupe by id.

    Same id with same content_hash → silently dedupe.
    Same id with different content_hash → PermanentFetcherError.
    """
    sorted_trades = sorted(trades, key=lambda t: (t.time, t.id))
    seen: dict[int, BinanceTrade] = {}
    deduped: list[BinanceTrade] = []
    for t in sorted_trades:
        existing = seen.get(t.id)
        if existing is None:
            seen[t.id] = t
            deduped.append(t)
            continue
        if existing.content_hash != t.content_hash:
            raise PermanentFetcherError(
                f"aggregate trade id {t.id} appears with conflicting "
                f"content across archives: existing price={existing.price}, "
                f"qty={existing.qty}, time={existing.time}, "
                f"is_buyer_maker={existing.is_buyer_maker}; "
                f"new price={t.price}, qty={t.qty}, time={t.time}, "
                f"is_buyer_maker={t.is_buyer_maker}"
            )
        # Same content — silently dedupe.
    return deduped
