"""Binance funding-rate REST fetcher.

Pulls historical funding-rate observations from Binance's USDM-Futures REST
endpoint and normalises each record into the canonical FundingRate shape
defined in funding_rate.py.

Design properties:

  - Injectable HTTP transport. Tests inject a fake transport with canned
    responses; production passes the real urllib-backed transport. The
    fetcher itself never touches the network directly.

  - No new dependencies. Uses stdlib urllib so the fetcher works without
    adding `requests` or `httpx` to pyproject. Switching to a richer HTTP
    client is a one-file change later if needed.

  - Strict parsing. Every response field is validated; malformed records
    raise with specific context rather than producing a partial canonical
    object. Better to fail loudly at ingestion than silently corrupt the
    canonical store.

  - Throttle + retry. Binance's /fapi/v1/fundingRate rate limit is 500/min.
    The fetcher enforces a minimum 0.2s interval between calls (60% headroom)
    and retries transient errors (5xx, network) with exponential backoff.
    Permanent errors (4xx, malformed payloads) raise immediately.

  - In-memory only. The fetcher returns a list of FundingRate; persistence
    is a separate concern handled by the paper runner / canonical-store
    layer. Keeping ingestion stateless keeps it testable.

Endpoint reference:
  https://binance-docs.github.io/apidocs/futures/en/#get-funding-rate-history
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
from typing import Callable, Final, Protocol

from data.ingestion.vendors.binance.funding_rate import FundingRate


# ─── Constants ────────────────────────────────────────────────────────────

BINANCE_FAPI_BASE: Final[str] = "https://fapi.binance.com"
FUNDING_RATE_PATH: Final[str] = "/fapi/v1/fundingRate"

VENUE: Final[str] = "binance"

# Binance USDM-Futures public-endpoint rate limit is ~500 requests/minute.
# 0.2s minimum interval = 300 req/min, 60% headroom.
MIN_INTERVAL_SECONDS: Final[float] = 0.2
RATE_LIMIT_REQUESTS_PER_MINUTE: Final[int] = 300

# Transient error retry policy.
MAX_RETRIES: Final[int] = 3
INITIAL_BACKOFF_SECONDS: Final[float] = 1.0
BACKOFF_MULTIPLIER: Final[float] = 2.0

# Endpoint pagination.
DEFAULT_LIMIT: Final[int] = 1000  # Binance max per request
MAX_LIMIT: Final[int] = 1000


# ─── Errors ───────────────────────────────────────────────────────────────


class FetcherError(Exception):
    """Base class for fetcher errors."""


class TransientFetcherError(FetcherError):
    """Network error or 5xx — caller may retry. Internally retried up
    to MAX_RETRIES with exponential backoff before being raised."""


class PermanentFetcherError(FetcherError):
    """4xx error or malformed response — caller must NOT retry; the
    request is structurally wrong or the venue refuses it."""


# ─── HTTP transport contract ──────────────────────────────────────────────


class HttpTransport(Protocol):
    """Minimal HTTP-GET contract.

    Production transport wraps urllib. Tests inject a fake.
    Returns the raw response body bytes; the fetcher parses JSON itself.
    """

    def get(self, url: str, *, timeout_seconds: float) -> bytes:
        ...


def default_urllib_transport() -> HttpTransport:
    """Stdlib-urllib-backed transport for production use."""

    class _UrllibTransport:
        def get(self, url: str, *, timeout_seconds: float) -> bytes:
            req = urllib.request.Request(
                url, headers={"User-Agent": "superhydra-funding-fetcher/0.1"}
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                    body = resp.read()
                    return body
            except urllib.error.HTTPError as e:
                # 4xx vs 5xx semantics handled by the fetcher; here we
                # surface the status by re-raising with a wrapped message.
                if 400 <= e.code < 500:
                    raise PermanentFetcherError(
                        f"HTTP {e.code} from {url}: {e.reason}"
                    ) from e
                raise TransientFetcherError(
                    f"HTTP {e.code} from {url}: {e.reason}"
                ) from e
            except urllib.error.URLError as e:
                raise TransientFetcherError(f"network error fetching {url}: {e.reason}") from e
            except TimeoutError as e:
                raise TransientFetcherError(f"timeout fetching {url}") from e

    return _UrllibTransport()


# ─── Fetcher ──────────────────────────────────────────────────────────────


@dataclass
class FundingRateFetcher:
    """Pulls funding-rate history for one venue (Binance USDM-Futures).

    Stateless across calls except for the throttle clock and the injected
    transport. A single instance can be used across many symbols and
    windows; the throttle ensures the rate-limit headroom holds.
    """

    transport: HttpTransport = field(default_factory=default_urllib_transport)
    timeout_seconds: float = 10.0
    min_interval_seconds: float = MIN_INTERVAL_SECONDS

    # Internal: monotonic clock + sleep are injected so tests can advance
    # deterministically without real wall time.
    _now: Callable[[], float] = field(default=time.monotonic)
    _sleep: Callable[[float], None] = field(default=time.sleep)

    # Internal: wall clock for ingested_at. Separately injectable so tests
    # can pin ingested_at without affecting the throttle clock.
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
    ) -> list[FundingRate]:
        """Return all funding-rate records for `symbol` whose funding_time
        is in [start, end). Results are sorted by funding_time ascending.

        Raises:
          PermanentFetcherError: invalid arguments, 4xx, malformed payload
          TransientFetcherError: 5xx or network errors that survived all
            internal retries.
        """
        if not symbol or not isinstance(symbol, str):
            raise PermanentFetcherError(f"symbol must be a non-empty string, got {symbol!r}")
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

        params = {
            "symbol": symbol,
            "startTime": _to_ms(start),
            "endTime": _to_ms(end),
            "limit": limit,
        }
        url = f"{BINANCE_FAPI_BASE}{FUNDING_RATE_PATH}?{urllib.parse.urlencode(params)}"

        body = self._get_with_retry(url)
        ingested_at = self._utcnow()
        records = self._parse_response(body, expected_symbol=symbol, ingested_at=ingested_at)

        # Binance returns oldest→newest ordering, but documentation does not
        # promise it. Sort defensively. Sorting is stable on funding_time.
        records.sort(key=lambda r: r.funding_time)
        return records

    # ─── Internal: throttle, retry, parse ────────────────────────────────

    def _throttle(self) -> None:
        """Block until min_interval_seconds has elapsed since the last
        request. First call is unthrottled."""
        if self._last_request_at is None:
            self._last_request_at = self._now()
            return

        elapsed = self._now() - self._last_request_at
        wait = self.min_interval_seconds - elapsed
        if wait > 0:
            self._sleep(wait)
        self._last_request_at = self._now()

    def _get_with_retry(self, url: str) -> bytes:
        """GET with exponential-backoff retry on transient errors.

        Permanent errors (4xx, parse-side problems) bubble out immediately.
        Transient errors retry up to MAX_RETRIES; the final retry's error
        is re-raised."""
        last_transient: TransientFetcherError | None = None
        backoff = INITIAL_BACKOFF_SECONDS

        for attempt in range(MAX_RETRIES + 1):
            self._throttle()
            try:
                return self.transport.get(url, timeout_seconds=self.timeout_seconds)
            except PermanentFetcherError:
                # Don't retry — caller's input or venue's response is the
                # problem and won't change with another attempt.
                raise
            except TransientFetcherError as e:
                last_transient = e
                if attempt < MAX_RETRIES:
                    self._sleep(backoff)
                    backoff *= BACKOFF_MULTIPLIER
                    continue
                # Exhausted retries.
                raise

        # Defensive — should never reach here.
        assert last_transient is not None
        raise last_transient

    def _parse_response(
        self, body: bytes, expected_symbol: str, ingested_at: datetime
    ) -> list[FundingRate]:
        """Parse the JSON body into canonical FundingRate records.

        Binance shape (one record):
          {
            "symbol": "BTCUSDT",
            "fundingRate": "0.00010000",
            "fundingTime": 1597392000000,
            "markPrice": "11700.00000000"   (sometimes present, sometimes not)
          }
        """
        try:
            data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise PermanentFetcherError(f"malformed JSON response: {e}") from e

        # Binance returns a top-level error object for some failures (e.g.
        # invalid symbol) with HTTP 400 — those become PermanentFetcherError
        # before we get here. But defensively, also handle the case where
        # the body is a dict with {"code": ..., "msg": ...}.
        if isinstance(data, dict) and "code" in data and "msg" in data:
            raise PermanentFetcherError(
                f"venue error response: code={data['code']} msg={data['msg']}"
            )

        if not isinstance(data, list):
            raise PermanentFetcherError(
                f"expected list response, got {type(data).__name__}"
            )

        records: list[FundingRate] = []
        for i, raw in enumerate(data):
            try:
                record = self._parse_record(raw, expected_symbol, ingested_at)
            except PermanentFetcherError:
                raise  # already context-attributed
            except (KeyError, ValueError, TypeError) as e:
                raise PermanentFetcherError(
                    f"malformed record at index {i}: {e}; raw={raw!r}"
                ) from e
            records.append(record)
        return records

    def _parse_record(
        self, raw: dict, expected_symbol: str, ingested_at: datetime
    ) -> FundingRate:
        """Convert one Binance record dict into a canonical FundingRate.

        Cross-checks the record's symbol against expected_symbol — Binance
        is reliable here, but a mismatch indicates either an upstream bug
        or a venue defect we should refuse to ingest silently.
        """
        if not isinstance(raw, dict):
            raise PermanentFetcherError(f"record is not a dict: {type(raw).__name__}")

        record_symbol = raw.get("symbol")
        if record_symbol != expected_symbol:
            raise PermanentFetcherError(
                f"record symbol mismatch: expected {expected_symbol!r}, "
                f"got {record_symbol!r}"
            )

        funding_time_ms = raw["fundingTime"]
        if not isinstance(funding_time_ms, (int, float)):
            raise PermanentFetcherError(
                f"fundingTime must be numeric, got {type(funding_time_ms).__name__}"
            )
        funding_time = datetime.fromtimestamp(int(funding_time_ms) / 1000, tz=timezone.utc)

        funding_rate_str = raw["fundingRate"]
        if not isinstance(funding_rate_str, str):
            raise PermanentFetcherError(
                f"fundingRate must be a string, got {type(funding_rate_str).__name__}"
            )
        try:
            funding_rate = Decimal(funding_rate_str)
        except Exception as e:
            raise PermanentFetcherError(
                f"fundingRate not parseable as Decimal: {funding_rate_str!r} ({e})"
            ) from e

        # markPrice is optional; some endpoints/older snapshots don't include
        # it. Treat missing as None; treat present-but-empty-string as None
        # (rare, observed in some historical exports).
        mark_price: Decimal | None = None
        raw_mark = raw.get("markPrice")
        if raw_mark is not None and raw_mark != "":
            if not isinstance(raw_mark, str):
                raise PermanentFetcherError(
                    f"markPrice must be a string, got {type(raw_mark).__name__}"
                )
            try:
                mark_price = Decimal(raw_mark)
            except Exception as e:
                raise PermanentFetcherError(
                    f"markPrice not parseable as Decimal: {raw_mark!r} ({e})"
                ) from e

        return FundingRate(
            venue=VENUE,
            instrument=expected_symbol,
            funding_time=funding_time,
            funding_rate=funding_rate,
            mark_price=mark_price,
            next_funding_time=None,  # not in this endpoint's response
            ingested_at=ingested_at,
        )


# ─── Helpers ──────────────────────────────────────────────────────────────


def _to_ms(dt: datetime) -> int:
    """UTC datetime → milliseconds since epoch (Binance convention)."""
    return int(dt.timestamp() * 1000)
