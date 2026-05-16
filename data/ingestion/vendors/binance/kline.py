"""Canonical kline (OHLCV bar) representation.

Vendor-agnostic. Any venue's raw kline feed must be normalized into
this shape before it enters the analytics layer.

Identity: (venue, instrument, interval, open_time). A canonical record
is uniquely identified by where it came from, which instrument, which
bar interval, and the bar's open timestamp.

Content hash: stable SHA-256 over the canonical fields. Used to detect
restatement vs. fresh data. The hash excludes ingested_at so identical
content produces identical hashes regardless of when ingestion ran.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final


CANONICAL_KLINE_SCHEMA_VERSION: Final[str] = "binance_kline.v1"


@dataclass(frozen=True)
class BinanceKline:
    """One kline (OHLCV bar) from Binance USDM-Futures.

    Fields:
        venue: lowercase venue identifier, "binance".
        instrument: vendor-canonical instrument code, e.g., "BTCUSDT".
        interval: bar interval, e.g., "1d", "1h", "5m".
        open_time: UTC start of the bar, at millisecond precision.
        open, high, low, close: prices as Decimal.
        volume: base-asset volume (contracts traded) as Decimal.
        quote_volume: quote-asset volume (USDT for USDT-perps).
        trade_count: number of trades in the bar.
        taker_buy_volume: base-asset volume bought by takers.
        taker_buy_quote_volume: quote-asset volume bought by takers.
        ingested_at: UTC timestamp at write time. Excluded from hash.
        schema_version: version tag.
    """

    venue: str
    instrument: str
    interval: str
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal
    trade_count: int
    taker_buy_volume: Decimal
    taker_buy_quote_volume: Decimal
    ingested_at: datetime | None = None
    schema_version: str = CANONICAL_KLINE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.venue or self.venue != self.venue.lower():
            raise ValueError(
                f"venue must be lowercase non-empty, got {self.venue!r}"
            )
        if not self.instrument:
            raise ValueError(
                f"instrument must be non-empty, got {self.instrument!r}"
            )
        if not self.interval:
            raise ValueError(
                f"interval must be non-empty, got {self.interval!r}"
            )
        if self.open_time.tzinfo is None:
            raise ValueError("open_time must be timezone-aware UTC")
        if self.ingested_at is not None and self.ingested_at.tzinfo is None:
            raise ValueError("ingested_at must be timezone-aware UTC")
        for field_name in ("open", "high", "low", "close", "volume",
                           "quote_volume", "taker_buy_volume",
                           "taker_buy_quote_volume"):
            value = getattr(self, field_name)
            if not isinstance(value, Decimal):
                raise TypeError(
                    f"{field_name} must be Decimal, "
                    f"got {type(value).__name__}"
                )
        if self.high < self.low:
            raise ValueError(
                f"high ({self.high}) must be >= low ({self.low})"
            )
        if self.volume < 0:
            raise ValueError(f"volume must be non-negative, got {self.volume}")
        if self.quote_volume < 0:
            raise ValueError(
                f"quote_volume must be non-negative, got {self.quote_volume}"
            )
        if not isinstance(self.trade_count, int) or self.trade_count < 0:
            raise ValueError(
                f"trade_count must be non-negative int, got {self.trade_count!r}"
            )
        if self.schema_version != CANONICAL_KLINE_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {CANONICAL_KLINE_SCHEMA_VERSION!r}, "
                f"got {self.schema_version!r}"
            )

    @property
    def content_hash(self) -> str:
        """SHA-256 over canonical content fields. Excludes ingested_at."""
        d = asdict(self)
        d.pop("ingested_at", None)
        for k in ("open", "high", "low", "close", "volume",
                  "quote_volume", "taker_buy_volume",
                  "taker_buy_quote_volume"):
            d[k] = str(d[k])
        d["open_time"] = self.open_time.isoformat()
        payload = json.dumps(d, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(payload).hexdigest()
