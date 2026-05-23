"""OKX 1h klines REST fetcher (minimum scope).

OKX does not publish a public bulk archive equivalent to Binance Vision.
Historical klines must be fetched via REST. The `history-candles` endpoint
returns 300 records per call, newest-first, with `before`/`after` cursors
for pagination. (Note: OKX's naming is counter-intuitive — `after` means
"older bound", `before` means "newer bound". A window query uses
`after=upper_ts before=lower_ts` and returns records with
`lower_ts < ts < upper_ts`.)

This fetcher:
- Supports BOTH BTC-USDT-SWAP (perp) and BTC-USDT (spot) via inst_id param
- Fetches 1h klines only (other intervals can be added if needed)
- Caches each page response keyed by the cursor used to fetch it, so
  reruns are deterministic
- Returns BinanceKline-shaped records (the underlying dataclass is named
  BinanceKline but its module docstring declares it vendor-agnostic; we
  treat it as the canonical kline shape) with venue="okx"
- KNOWN LIMITATION: OKX history-candles does not expose trade_count,
  taker_buy_volume, or taker_buy_quote_volume. These fields are set to
  zero on OKX klines and should be treated as "not measured", not as
  "zero trades / zero taker buys". Downstream code that depends on
  these for OKX data must either use a different OKX endpoint or
  exclude OKX from such analytics

Scope locked tonight:
- BTC-USDT (spot) and BTC-USDT-SWAP (perp) only
- 1h interval only
- No funding rate fetcher (separate file when needed)
- No multi-instrument abstraction
- No live-update mode

Not part of the production data pipeline yet. Untracked-script-style
exploration tonight; if the basis simulation justifies it, the fetcher
graduates into committed infrastructure.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterator

# Reuse the Binance kline shape for now. Rename to a venue-agnostic
# location if/when a third venue arrives.
from data.ingestion.vendors.binance.kline import BinanceKline


OKX_HISTORY_CANDLES_URL = "https://www.okx.com/api/v5/market/history-candles"
MAX_RECORDS_PER_CALL = 300
DEFAULT_THROTTLE_SECONDS = 0.30  # 3 req/sec, well under any reasonable limit
DEFAULT_CACHE_ROOT = Path("artifacts/cache")


def _default_cache_dir_for(inst_id: str, interval: str) -> Path:
    """Per-(inst_id, interval) cache directory."""
    # Slashes-or-other-trouble in inst_id are unlikely (uppercase + dash only)
    # but sanitize lightly to be safe.
    safe = inst_id.replace("/", "_").replace(":", "_")
    return DEFAULT_CACHE_ROOT / f"okx_klines_{safe}_{interval}"


# ─── Errors ──────────────────────────────────────────────────────────────

class OkxFetcherError(Exception):
    """Base error from OkxKlinesFetcher."""


class OkxTransientError(OkxFetcherError):
    """Retry-eligible (network, 5xx, transient API error code)."""


class OkxPermanentError(OkxFetcherError):
    """Do-not-retry (validation, schema mismatch, 4xx other than rate limit)."""


# ─── Fetcher ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class OkxRawPage:
    """One page of 300 (or fewer) raw kline rows from OKX as returned by the
    history-candles endpoint. Stored to cache verbatim for determinism."""
    inst_id: str
    interval: str
    after_cursor_ms: int  # the `after` parameter used to fetch this page
    fetched_at_utc: str   # ISO-8601 string
    raw_data: list[list[str]]  # list of [ts_ms, open, high, low, close, vol, ...]


class OkxKlinesFetcher:
    """Minimum OKX 1h klines fetcher.

    Usage:
        fetcher = OkxKlinesFetcher(inst_id="BTC-USDT-SWAP", interval="1H")
        klines = fetcher.fetch_window(start_utc, end_utc)
    """

    def __init__(
        self,
        inst_id: str,
        interval: str = "1H",
        cache_dir: Path | None = None,
        throttle_seconds: float = DEFAULT_THROTTLE_SECONDS,
        transport: callable = None,  # for tests
    ):
        if not inst_id:
            raise ValueError("inst_id must be non-empty")
        if interval not in ("1H",):
            raise ValueError(
                f"interval {interval!r} not supported tonight; "
                f"only '1H' is implemented"
            )

        self.inst_id = inst_id
        self.interval = interval
        self.cache_dir = cache_dir or _default_cache_dir_for(inst_id, interval)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.throttle_seconds = throttle_seconds
        # Transport is an injectable function for tests. Default uses urllib.
        self._transport = transport or _default_urllib_transport

    # ─── Public API ──────────────────────────────────────────────────

    def fetch_window(
        self, start_utc: datetime, end_utc: datetime,
    ) -> list[BinanceKline]:
        """Fetch all 1h klines in [start_utc, end_utc).

        Both bounds must be timezone-aware UTC. Returns klines in chronological
        order (oldest first), deduplicated, sorted by open_time.
        """
        self._validate_window(start_utc, end_utc)

        start_ms = int(start_utc.timestamp() * 1000)
        end_ms = int(end_utc.timestamp() * 1000)

        # Paginate backward from end_ms. OKX `after` parameter returns records
        # with ts < after, newest-first. We stop once the oldest record in a
        # page is at-or-before start_ms.
        all_rows: list[list[str]] = []
        cursor_after = end_ms

        while True:
            page = self._fetch_or_load_page(cursor_after=cursor_after)
            if not page.raw_data:
                # Empty response — no more data available before this cursor.
                break
            all_rows.extend(page.raw_data)

            # OKX returns newest-first; the oldest row in this page is at end.
            oldest_in_page_ms = int(page.raw_data[-1][0])
            if oldest_in_page_ms <= start_ms:
                # We've fetched past the start of the window. Done.
                break
            # Next page: advance cursor to the oldest ts in this page.
            cursor_after = oldest_in_page_ms

        # Convert raw rows to BinanceKline, filter to window, dedupe, sort.
        klines = self._rows_to_klines(all_rows, start_ms, end_ms)
        return klines

    # ─── Page fetch (cached) ─────────────────────────────────────────

    def _fetch_or_load_page(self, cursor_after: int) -> OkxRawPage:
        """Return one page of raw kline rows for the given `after` cursor.

        Cached: if the cache file exists, return its contents without hitting
        the network. Otherwise fetch, cache, return.
        """
        cache_path = self.cache_dir / f"after_{cursor_after}.json"
        if cache_path.exists():
            with cache_path.open() as f:
                cached = json.load(f)
            return OkxRawPage(
                inst_id=cached["inst_id"],
                interval=cached["interval"],
                after_cursor_ms=cached["after_cursor_ms"],
                fetched_at_utc=cached["fetched_at_utc"],
                raw_data=cached["raw_data"],
            )

        # Fetch from REST
        raw_data = self._fetch_from_rest(cursor_after=cursor_after)
        page = OkxRawPage(
            inst_id=self.inst_id,
            interval=self.interval,
            after_cursor_ms=cursor_after,
            fetched_at_utc=datetime.now(timezone.utc).isoformat(),
            raw_data=raw_data,
        )

        # Write cache
        with cache_path.open("w") as f:
            json.dump({
                "inst_id": page.inst_id,
                "interval": page.interval,
                "after_cursor_ms": page.after_cursor_ms,
                "fetched_at_utc": page.fetched_at_utc,
                "raw_data": page.raw_data,
            }, f)

        # Throttle before returning so the caller's next call is naturally
        # paced. This is intentionally "trailing-edge" throttling — the cost
        # of the wait is paid per fetch, not per cache hit.
        time.sleep(self.throttle_seconds)
        return page

    def _fetch_from_rest(self, cursor_after: int) -> list[list[str]]:
        """Single REST call to OKX history-candles. Returns the raw data array.

        Raises OkxTransientError on retry-eligible failures.
        Raises OkxPermanentError on schema/validation failures.
        """
        params = f"instId={self.inst_id}&bar={self.interval}" \
                 f"&after={cursor_after}&limit={MAX_RECORDS_PER_CALL}"
        url = f"{OKX_HISTORY_CANDLES_URL}?{params}"

        try:
            response_text = self._transport(url)
        except urllib.error.HTTPError as e:
            if 500 <= e.code < 600:
                raise OkxTransientError(f"HTTP {e.code} from OKX: {e}") from e
            raise OkxPermanentError(f"HTTP {e.code} from OKX: {e}") from e
        except urllib.error.URLError as e:
            raise OkxTransientError(f"Network error: {e}") from e

        try:
            payload = json.loads(response_text)
        except json.JSONDecodeError as e:
            raise OkxPermanentError(
                f"Non-JSON response from OKX: {response_text[:200]!r}"
            ) from e

        code = payload.get("code")
        if code != "0":
            msg = payload.get("msg", "")
            # OKX uses code='50011' for rate limit
            if code == "50011":
                raise OkxTransientError(f"OKX rate limit: {msg}")
            raise OkxPermanentError(f"OKX error code={code} msg={msg!r}")

        data = payload.get("data")
        if not isinstance(data, list):
            raise OkxPermanentError(
                f"OKX response 'data' is not a list: {type(data).__name__}"
            )
        # Schema check: each row should be a list of strings, ts in row[0]
        for i, row in enumerate(data[:3]):  # spot-check first 3
            if not isinstance(row, list) or len(row) < 5:
                raise OkxPermanentError(
                    f"row {i} has unexpected shape: {row!r}"
                )

        return data

    # ─── Conversion ──────────────────────────────────────────────────

    def _rows_to_klines(
        self, rows: list[list[str]], start_ms: int, end_ms: int,
    ) -> list[BinanceKline]:
        """Convert raw OKX rows to BinanceKline objects, filter to window,
        deduplicate by open_time, and sort chronologically."""
        # Use a dict keyed by open_time_ms to dedupe; pages can overlap if a
        # cursor was used twice (shouldn't happen but be safe).
        by_open_time: dict[int, BinanceKline] = {}

        # Strip the symbol of the perp suffix so the BinanceKline.instrument
        # field is comparable across venues. OKX "BTC-USDT-SWAP" → "BTC-USDT"
        # would be misleading too; we keep the raw inst_id for now.
        instrument = self.inst_id

        for row in rows:
            try:
                ts_ms = int(row[0])
            except (TypeError, ValueError):
                continue  # skip malformed rows silently — they'd have shown
                          # up in the schema check earlier if widespread
            if ts_ms < start_ms or ts_ms >= end_ms:
                continue
            if ts_ms in by_open_time:
                continue  # already have this kline, skip

            try:
                open_p = Decimal(row[1])
                high = Decimal(row[2])
                low = Decimal(row[3])
                close = Decimal(row[4])
            except (TypeError, ValueError, IndexError) as e:
                raise OkxPermanentError(
                    f"failed to parse OHLC for ts={ts_ms}: {row!r}"
                ) from e

            # OKX history-candles row format:
            #   [ts, open, high, low, close, vol_base, vol_quote_ccy, vol_quote_ccy_quote, confirm]
            #    0    1     2     3    4      5         6              7                    8
            #
            # OKX does NOT provide trade_count, taker_buy_volume, or
            # taker_buy_quote_volume on this endpoint. Those would require
            # the per-trade endpoint and aggregation. For now, set to zero
            # and document this as a known limitation.
            try:
                volume = Decimal(row[5]) if len(row) > 5 else Decimal("0")
                quote_volume = Decimal(row[7]) if len(row) > 7 else Decimal("0")
            except (TypeError, ValueError, IndexError) as e:
                raise OkxPermanentError(
                    f"failed to parse volume for ts={ts_ms}: {row!r}"
                ) from e

            kline = BinanceKline(
                venue="okx",
                instrument=instrument,
                interval=self.interval.lower(),  # "1h" not "1H"
                open_time=datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc),
                open=open_p,
                high=high,
                low=low,
                close=close,
                volume=volume,
                quote_volume=quote_volume,
                trade_count=0,                       # OKX history-candles does not expose
                taker_buy_volume=Decimal("0"),       # OKX history-candles does not expose
                taker_buy_quote_volume=Decimal("0"), # OKX history-candles does not expose
            )
            by_open_time[ts_ms] = kline

        sorted_klines = sorted(by_open_time.values(), key=lambda k: k.open_time)
        return sorted_klines

    # ─── Validation helpers ──────────────────────────────────────────

    def _validate_window(self, start_utc: datetime, end_utc: datetime) -> None:
        if start_utc.tzinfo is None:
            raise ValueError("start_utc must be timezone-aware")
        if end_utc.tzinfo is None:
            raise ValueError("end_utc must be timezone-aware")
        if end_utc <= start_utc:
            raise ValueError(
                f"end_utc ({end_utc}) must be after start_utc ({start_utc})"
            )


# ─── Default transport ───────────────────────────────────────────────────

def _default_urllib_transport(url: str, timeout: float = 30.0) -> str:
    """Plain urllib GET. Returns response body as string. Lets HTTPError and
    URLError propagate so the fetcher can classify them."""
    req = urllib.request.Request(url, headers={"User-Agent": "hydra-okx-fetcher/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")
