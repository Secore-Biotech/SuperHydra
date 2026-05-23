"""Coinbase USDT-USD 1h candles REST fetcher (minimum scope).

Coinbase publishes spot OHLC via its public Exchange API. The historical
candles endpoint returns up to 300 records per call, newest-first, keyed
on start/end timestamps (seconds, ISO 8601, or unix). For deeper history
we paginate backward by stepping the `end` cursor.

This fetcher:
- USDT-USD only (no USDC market on Coinbase; that's a different problem)
- 1h interval only (granularity=3600)
- Caches each page response keyed by the end-cursor used to fetch it,
  so reruns are deterministic
- Returns BinanceKline-shaped records with venue="coinbase"
- KNOWN LIMITATION: Coinbase candle responses contain only
  [time, low, high, open, close, volume]. They do NOT expose
  quote_volume, trade_count, taker_buy_volume, or taker_buy_quote_volume.
  These fields are set to zero on Coinbase klines and should be treated
  as "not measured", not as "zero trades / zero taker buys". This is the
  same pattern the OKX fetcher uses for fields OKX doesn't publish.

Scope locked tonight:
- USDT-USD only
- 1h interval only
- No USDC fetcher (not viable on Coinbase — they don't trade USDC-USD)
- No other product types
- No live-update mode

Engineering hygiene module. Whether the stablecoin direction is worth
escalating depends on what the data shows, which is a measurement
question to be answered AFTER this fetcher is committed.
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
from typing import Callable

# Reuse the canonical kline shape (vendor-agnostic despite the file name).
from data.ingestion.vendors.binance.kline import BinanceKline


COINBASE_CANDLES_URL_TEMPLATE = (
    "https://api.exchange.coinbase.com/products/{product_id}/candles"
)
MAX_RECORDS_PER_CALL = 300       # Coinbase candles endpoint hard cap
DEFAULT_THROTTLE_SECONDS = 0.40  # ~2.5 req/sec, well under Coinbase public limits
DEFAULT_CACHE_ROOT = Path("artifacts/cache")


# ─── Exceptions ──────────────────────────────────────────────────────────

class CoinbaseFetcherError(Exception):
    """Base exception for Coinbase fetcher errors."""


class CoinbaseTransientError(CoinbaseFetcherError):
    """Retryable error: network timeout, 5xx response, rate limit."""


class CoinbasePermanentError(CoinbaseFetcherError):
    """Non-retryable error: 4xx (except 429), schema violation, parse failure."""


# ─── Raw page record ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class CoinbaseRawPage:
    """One page of raw rows from Coinbase, plus the cursor used to fetch it.

    Stored verbatim in the cache so a rerun is byte-identical to the
    original fetch (modulo timestamp on the request itself, which isn't
    persisted).
    """
    end_cursor_unix: int     # the `end` parameter value used to fetch this page
    rows: list[list]         # list of [time, low, high, open, close, volume]


# ─── Cache path helpers ──────────────────────────────────────────────────

def _default_cache_dir_for(product_id: str, interval: str) -> Path:
    """Returns artifacts/cache/coinbase_klines_{product_id}_{interval}."""
    safe = product_id.replace("/", "-").upper()
    return DEFAULT_CACHE_ROOT / f"coinbase_klines_{safe}_{interval}"


# ─── Fetcher ─────────────────────────────────────────────────────────────

class CoinbaseUsdtUsdFetcher:
    """REST fetcher for Coinbase USDT-USD 1h candles.

    Page-level caching: each REST page is cached as JSON under
    artifacts/cache/coinbase_klines_USDT-USD_1h/<end_cursor>.json.
    Once cached, that page is never re-fetched.
    """

    GRANULARITY_SECONDS = 3600  # 1h, locked

    def __init__(
        self,
        product_id: str = "USDT-USD",
        cache_dir: Path | None = None,
        throttle_seconds: float = DEFAULT_THROTTLE_SECONDS,
        transport: Callable[[str], str] | None = None,
        max_retries: int = 3,
    ):
        if product_id != "USDT-USD":
            raise CoinbasePermanentError(
                f"This fetcher is scoped to USDT-USD only; got product_id={product_id!r}"
            )
        self.product_id = product_id
        self.interval = "1h"
        self.cache_dir = cache_dir or _default_cache_dir_for(product_id, self.interval)
        self.throttle_seconds = throttle_seconds
        self.transport = transport or _default_urllib_transport
        self.max_retries = max_retries
        self._last_request_at: float = 0.0

    # ── Public API ────────────────────────────────────────────────────

    def fetch_window(
        self,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[BinanceKline]:
        """Fetch all 1h candles in [start_utc, end_utc).

        Paginates backward from end_utc until start_utc is reached.
        Returns klines sorted ascending by open_time, deduplicated.
        """
        self._validate_window(start_utc, end_utc)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        start_unix = int(start_utc.timestamp())
        end_unix = int(end_utc.timestamp())

        # Paginate backward: each call asks for the slice [page_start, cursor),
        # where cursor starts at end_unix and walks backward by 300 hours each step.
        all_klines: dict[datetime, BinanceKline] = {}
        cursor = end_unix
        page_count = 0

        while cursor > start_unix:
            page_start = max(start_unix, cursor - MAX_RECORDS_PER_CALL * self.GRANULARITY_SECONDS)
            page = self._fetch_or_load_page(
                end_cursor_unix=cursor,
                start_cursor_unix=page_start,
            )
            page_count += 1

            if not page.rows:
                # Empty page — no more data available, stop paginating
                break

            for kline in self._rows_to_klines(page.rows):
                # Inner filter — only keep klines actually within our window
                if start_utc <= kline.open_time < end_utc:
                    all_klines[kline.open_time] = kline

            # Step cursor backward. The oldest row in this page tells us where
            # to resume. If for some reason rows didn't cover the requested
            # range, fall back to subtracting MAX_RECORDS_PER_CALL hours.
            oldest_row_ts = min(int(r[0]) for r in page.rows)
            if oldest_row_ts <= start_unix:
                break
            cursor = oldest_row_ts

        return sorted(all_klines.values(), key=lambda k: k.open_time)

    # ── Page-level fetch with caching ────────────────────────────────

    def _fetch_or_load_page(
        self,
        end_cursor_unix: int,
        start_cursor_unix: int,
    ) -> CoinbaseRawPage:
        """Load a page from cache if available, otherwise fetch from REST."""
        cache_path = self.cache_dir / f"end_{end_cursor_unix}.json"
        if cache_path.exists():
            with cache_path.open() as f:
                cached = json.load(f)
            return CoinbaseRawPage(
                end_cursor_unix=cached["end_cursor_unix"],
                rows=cached["rows"],
            )

        rows = self._fetch_from_rest(
            end_cursor_unix=end_cursor_unix,
            start_cursor_unix=start_cursor_unix,
        )
        page = CoinbaseRawPage(end_cursor_unix=end_cursor_unix, rows=rows)
        with cache_path.open("w") as f:
            json.dump({"end_cursor_unix": end_cursor_unix, "rows": rows}, f)
        return page

    def _fetch_from_rest(
        self,
        end_cursor_unix: int,
        start_cursor_unix: int,
    ) -> list[list]:
        """Make one REST call, with throttle + retry for transient errors."""
        start_iso = datetime.fromtimestamp(start_cursor_unix, tz=timezone.utc).isoformat()
        end_iso = datetime.fromtimestamp(end_cursor_unix, tz=timezone.utc).isoformat()
        url = (
            f"{COINBASE_CANDLES_URL_TEMPLATE.format(product_id=self.product_id)}"
            f"?granularity={self.GRANULARITY_SECONDS}"
            f"&start={start_iso}"
            f"&end={end_iso}"
        )

        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            self._respect_throttle()
            try:
                body = self.transport(url)
            except CoinbaseTransientError as err:
                last_err = err
                time.sleep(self.throttle_seconds * (2 ** attempt))
                continue
            except CoinbasePermanentError:
                raise

            # Parse and validate
            try:
                payload = json.loads(body)
            except json.JSONDecodeError as err:
                raise CoinbasePermanentError(f"Failed to parse JSON: {err}") from err

            # Coinbase returns either an array of arrays (success) or
            # {"message": "..."} (error).
            if isinstance(payload, dict):
                msg = payload.get("message", "unknown error")
                raise CoinbasePermanentError(f"Coinbase error: {msg}")
            if not isinstance(payload, list):
                raise CoinbasePermanentError(
                    f"Unexpected response shape: {type(payload).__name__}"
                )
            return payload

        raise CoinbaseTransientError(
            f"Failed after {self.max_retries} retries; last error: {last_err}"
        )

    # ── Row → kline conversion ───────────────────────────────────────

    def _rows_to_klines(self, rows: list[list]) -> list[BinanceKline]:
        """Convert Coinbase row arrays to BinanceKline records.

        Coinbase row shape: [time, low, high, open, close, volume]
        time is unix-seconds (int), the rest are floats.
        """
        out: list[BinanceKline] = []
        for row in rows:
            if not isinstance(row, list) or len(row) != 6:
                raise CoinbasePermanentError(
                    f"Malformed row (expected 6 elements, got {len(row) if isinstance(row, list) else type(row).__name__})"
                )
            try:
                ts_unix = int(row[0])
                low = Decimal(str(row[1]))
                high = Decimal(str(row[2]))
                open_ = Decimal(str(row[3]))
                close = Decimal(str(row[4]))
                volume = Decimal(str(row[5]))
            except (ValueError, TypeError, ArithmeticError) as err:
                raise CoinbasePermanentError(f"Failed to parse row {row}: {err}") from err

            open_time = datetime.fromtimestamp(ts_unix, tz=timezone.utc)

            kline = BinanceKline(
                venue="coinbase",
                instrument=self.product_id,
                interval=self.interval,
                open_time=open_time,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
                # Fields Coinbase doesn't publish — zero-padded, NOT measured zeros
                quote_volume=Decimal("0"),
                trade_count=0,
                taker_buy_volume=Decimal("0"),
                taker_buy_quote_volume=Decimal("0"),
            )
            out.append(kline)
        return out

    # ── Throttle & validation ────────────────────────────────────────

    def _respect_throttle(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_request_at
        if elapsed < self.throttle_seconds:
            time.sleep(self.throttle_seconds - elapsed)
        self._last_request_at = time.monotonic()

    def _validate_window(self, start_utc: datetime, end_utc: datetime) -> None:
        if start_utc.tzinfo is None or end_utc.tzinfo is None:
            raise CoinbasePermanentError("start_utc and end_utc must be timezone-aware")
        if end_utc <= start_utc:
            raise CoinbasePermanentError(
                f"end_utc ({end_utc}) must be after start_utc ({start_utc})"
            )


# ─── Default transport ───────────────────────────────────────────────────

def _default_urllib_transport(url: str, timeout: float = 30.0) -> str:
    """HTTP GET with classification into transient vs permanent errors.

    Coinbase's edge (Cloudflare) blocks the default Python-urllib User-Agent
    with error code 1010. Sending a conventional UA bypasses the filter.
    """
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "hydra-next/1.0 (research data ingestion)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.getcode()
            body = resp.read().decode("utf-8")
        if status == 200:
            return body
        if status == 429 or 500 <= status < 600:
            raise CoinbaseTransientError(f"HTTP {status}: {body[:200]}")
        raise CoinbasePermanentError(f"HTTP {status}: {body[:200]}")
    except urllib.error.HTTPError as err:
        body_preview = ""
        try:
            body_preview = err.read().decode("utf-8")[:200]
        except Exception:
            pass
        if err.code == 429 or 500 <= err.code < 600:
            raise CoinbaseTransientError(f"HTTP {err.code}: {body_preview}") from err
        raise CoinbasePermanentError(f"HTTP {err.code}: {body_preview}") from err
    except (urllib.error.URLError, TimeoutError) as err:
        raise CoinbaseTransientError(f"Network error: {err}") from err
