"""Canonical aggregate-trade representation.

Vendor-agnostic. Any venue's raw trade feed must be normalized into this
shape before it enters the analytics layer. The shape is deliberately
narrow: just the facts an effective-spread / impact / Roll-style
estimator needs, plus the lineage facts a research-vs-empirical
reconciliation needs to prove "same input -> same estimate."

Identity: (venue, instrument, id). A canonical record is uniquely
identified by where it came from, what instrument it covers, and the
vendor's aggregate-trade id. Two records with the same identity but
different prices indicate either a vendor restatement or a bug.

Content hash: stable SHA-256 over the canonical fields. Used to detect
restatement vs. fresh data. The hash deliberately excludes ingested_at
so identical content produces identical hashes regardless of when
ingestion ran.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Final


CANONICAL_SCHEMA_VERSION: Final[str] = "binance_trade.v1"


@dataclass(frozen=True)
class BinanceTrade:
    """One aggregate trade from Binance USDM-Futures.

    Fields:
        venue: lower-case venue identifier, "binance".
        instrument: vendor-canonical instrument code, e.g. "SOLUSDT".
        id: vendor aggregate-trade id (Binance: aggTrade `a` field).
        price: trade price as a Decimal.
        qty: trade quantity in contract units.
        time: UTC timestamp of the trade, at millisecond precision.
        is_buyer_maker: True if the buyer was the maker.
        ingested_at: UTC timestamp at which this record was written.
            Excluded from the content hash.
        schema_version: version tag.
    """

    venue: str
    instrument: str
    id: int
    price: Decimal
    qty: Decimal
    time: datetime
    is_buyer_maker: bool
    ingested_at: datetime | None = None
    schema_version: str = CANONICAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.venue or self.venue != self.venue.lower():
            raise ValueError(
                f"venue must be lowercase non-empty, got {self.venue!r}"
            )
        if not self.instrument:
            raise ValueError(f"instrument must be non-empty, got {self.instrument!r}")
        if not isinstance(self.id, int) or self.id < 0:
            raise ValueError(f"id must be non-negative int, got {self.id!r}")
        if not isinstance(self.price, Decimal):
            raise TypeError(f"price must be Decimal, got {type(self.price).__name__}")
        if self.price <= 0:
            raise ValueError(f"price must be positive, got {self.price}")
        if not isinstance(self.qty, Decimal):
            raise TypeError(f"qty must be Decimal, got {type(self.qty).__name__}")
        if self.qty < 0:
            raise ValueError(f"qty must be non-negative, got {self.qty}")
        if self.time.tzinfo is None:
            raise ValueError("time must be timezone-aware UTC")
        if self.ingested_at is not None and self.ingested_at.tzinfo is None:
            raise ValueError("ingested_at must be timezone-aware UTC")
        if not isinstance(self.is_buyer_maker, bool):
            raise TypeError(
                f"is_buyer_maker must be bool, got {type(self.is_buyer_maker).__name__}"
            )
        if self.schema_version != CANONICAL_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {CANONICAL_SCHEMA_VERSION!r}, "
                f"got {self.schema_version!r}"
            )

    @property
    def content_hash(self) -> str:
        """SHA-256 over canonical content fields. Excludes ingested_at."""
        d = asdict(self)
        d.pop("ingested_at", None)
        d["price"] = str(self.price)
        d["qty"] = str(self.qty)
        d["time"] = self.time.isoformat()
        payload = json.dumps(d, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(payload).hexdigest()
