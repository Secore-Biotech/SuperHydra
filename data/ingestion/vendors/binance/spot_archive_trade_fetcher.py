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

import csv
import io
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Iterator

from data.ingestion.vendors.binance.archive_trade_fetcher import (
    BINANCE_VISION_BASE,
    DEFAULT_TIMEOUT_SECONDS,
    INITIAL_BACKOFF_SECONDS,
    MAX_RETRIES,
    MIN_INTERVAL_SECONDS,
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


def _iter_spot_trades_in_window(
    archive_bytes: bytes,
    *,
    symbol: str,
    start_ms: int,
    end_ms: int,
    ingested_at: datetime,
) -> Iterator[BinanceTrade]:
    """Stream the inner CSV of a Binance Vision SPOT aggTrades zip,
    yielding BinanceTrade for rows with timestamp in [start_ms, end_ms).

    Spot CSV schema (8 columns, vs perp's 7):
        0: agg_trade_id (int)
        1: price (Decimal)
        2: quantity (Decimal)
        3: first_trade_id (int)         [unused]
        4: last_trade_id (int)          [unused]
        5: transact_time_ms (int)
        6: is_buyer_maker (bool string)
        7: is_best_match (bool string)  [unused; spot-specific]

    The column-count gate is strict at 8 to catch schema drift. The
    is_best_match column is read but not propagated into BinanceTrade
    (which has no field for it).

    This parser is intentionally separate from the perp parser
    (data.ingestion.vendors.binance.archive_trade_fetcher._iter_trades_in_window)
    per the Day 26.5 reviewer decision: spot-local parser preserves the
    Day 26.1 firewall that A1's perp fetcher path is bit-for-bit
    unmodified by Day 26 work.
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

                if len(row) != 8:
                    raise PermanentFetcherError(
                        f"expected 8 columns in spot CSV row, got {len(row)}: {row}"
                    )

                try:
                    agg_id = int(row[0])
                    price = Decimal(row[1])
                    qty = Decimal(row[2])
                    time_ms = int(row[5])
                    is_buyer_maker_str = row[6].strip().lower()
                except (ValueError, InvalidOperation) as e:
                    raise PermanentFetcherError(
                        f"malformed spot CSV row {row!r}: {e}"
                    ) from e

                if is_buyer_maker_str == "true":
                    is_buyer_maker = True
                elif is_buyer_maker_str == "false":
                    is_buyer_maker = False
                else:
                    raise PermanentFetcherError(
                        f"unexpected is_buyer_maker value in spot row "
                        f"{row!r}: {row[6]!r}"
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
                        f"record validation failed for spot row {row!r}: {e}"
                    ) from e


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
            for trade in _iter_spot_trades_in_window(
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
                return self.transport.get(url, timeout_seconds=self.timeout_seconds)
            except TransientFetcherError as e:
                last_exc = e
                if attempt < MAX_RETRIES:
                    self._sleep(backoff)
                    backoff *= 2

        assert last_exc is not None
        raise last_exc
