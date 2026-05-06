"""Canonical funding-rate representation.

Vendor-agnostic. Any venue's raw funding-rate feed must be normalized into
this shape before it enters the strategy layer. The shape is deliberately
narrow: just the facts a carry/funding strategy needs to make a sizing
decision, plus the lineage facts a paper-vs-canary reconciliation needs to
prove "same input → same verdict."

Identity: (venue, instrument, funding_time). A canonical record is uniquely
identified by where it came from, what instrument it covers, and the funding
interval it represents. Two records with the same identity but different
rates indicate either a vendor restatement (legitimate) or a bug (must be
caught).

Content hash: stable SHA-256 over the canonical fields. Used to detect
restatement vs. fresh data and to feed reconciliation lineage. The hash
deliberately excludes ingested_at so identical content produces identical
hashes regardless of when ingestion ran.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Final


# Schema version. Bump on any change to the canonical shape. Persisted with
# every record so future code can detect and migrate old rows.
CANONICAL_SCHEMA_VERSION: Final[str] = "funding_rate.v1"


@dataclass(frozen=True)
class FundingRate:
    """One funding-rate observation for one perp instrument at one interval.

    Frozen to make instances hashable and to prevent accidental mutation
    after content_hash is computed.

    Fields:
        venue: lower-case venue identifier, e.g. "binance".
        instrument: vendor-canonical instrument code, e.g. "BTCUSDT".
        funding_time: UTC timestamp at which this funding interval applies.
            For Binance perps this is the settlement instant of the funding
            payment. Must be timezone-aware UTC.
        funding_rate: per-interval rate as a Decimal. Positive means longs
            pay shorts. Stored as Decimal because float rounding produces
            non-determinism in cost models.
        mark_price: vendor mark price at funding_time, if available. Used by
            paper runners that need to size in USD terms; None when the
            vendor doesn't publish it.
        next_funding_time: UTC timestamp of the next funding interval, if
            the vendor publishes a forward schedule. None otherwise.
        ingested_at: UTC timestamp at which this record was written into the
            local canonical store. Excluded from the content hash.
        schema_version: version tag of the canonical shape. Always set to
            CANONICAL_SCHEMA_VERSION at construction time.
    """

    venue: str
    instrument: str
    funding_time: datetime
    funding_rate: Decimal
    mark_price: Decimal | None = None
    next_funding_time: datetime | None = None
    ingested_at: datetime | None = None
    schema_version: str = CANONICAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        # Validate at construction time. Frozen dataclass means we can't
        # set defaults, so we raise instead.
        if not self.venue or not self.venue.islower():
            raise ValueError(
                f"venue must be a non-empty lowercase string, got {self.venue!r}"
            )
        if not self.instrument:
            raise ValueError("instrument must be non-empty")
        if self.funding_time.tzinfo is None:
            raise ValueError(
                f"funding_time must be timezone-aware, got naive {self.funding_time!r}"
            )
        if self.funding_time.tzinfo.utcoffset(self.funding_time) != timezone.utc.utcoffset(
            self.funding_time
        ):
            raise ValueError(
                f"funding_time must be UTC, got tzinfo={self.funding_time.tzinfo!r}"
            )
        if not isinstance(self.funding_rate, Decimal):
            raise TypeError(
                f"funding_rate must be Decimal (not float), got {type(self.funding_rate).__name__}"
            )
        if self.mark_price is not None and not isinstance(self.mark_price, Decimal):
            raise TypeError(
                f"mark_price must be Decimal or None, got {type(self.mark_price).__name__}"
            )
        if self.next_funding_time is not None:
            if self.next_funding_time.tzinfo is None:
                raise ValueError("next_funding_time must be timezone-aware")
            if self.next_funding_time <= self.funding_time:
                raise ValueError(
                    f"next_funding_time ({self.next_funding_time}) must be strictly "
                    f"after funding_time ({self.funding_time})"
                )
        if self.ingested_at is not None and self.ingested_at.tzinfo is None:
            raise ValueError("ingested_at must be timezone-aware")
        if self.schema_version != CANONICAL_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {CANONICAL_SCHEMA_VERSION!r}, "
                f"got {self.schema_version!r}"
            )

    @property
    def identity(self) -> tuple[str, str, datetime]:
        """Stable identity tuple: (venue, instrument, funding_time).

        Two records with the same identity refer to the same real-world
        funding interval at the same venue. They may legitimately differ
        in rate (vendor restatement) but must reconcile.
        """
        return (self.venue, self.instrument, self.funding_time)

    @property
    def content_hash(self) -> str:
        """Stable SHA-256 hex digest of the canonical content.

        Excludes ingested_at so identical content produces identical hashes
        regardless of when ingestion ran. Used by reconciliation lineage.
        """
        payload = {
            "schema_version": self.schema_version,
            "venue": self.venue,
            "instrument": self.instrument,
            "funding_time": self.funding_time.isoformat(),
            "funding_rate": str(self.funding_rate),
            "mark_price": str(self.mark_price) if self.mark_price is not None else None,
            "next_funding_time": (
                self.next_funding_time.isoformat()
                if self.next_funding_time is not None
                else None
            ),
        }
        canonical_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        return hashlib.sha256(canonical_bytes).hexdigest()

    def to_dict(self) -> dict:
        """Plain-dict representation suitable for JSONB persistence.

        Decimal values become strings (lossless). Datetimes become
        ISO-8601 strings.
        """
        d = asdict(self)
        d["funding_time"] = self.funding_time.isoformat()
        d["funding_rate"] = str(self.funding_rate)
        d["mark_price"] = str(self.mark_price) if self.mark_price is not None else None
        d["next_funding_time"] = (
            self.next_funding_time.isoformat()
            if self.next_funding_time is not None
            else None
        )
        d["ingested_at"] = (
            self.ingested_at.isoformat() if self.ingested_at is not None else None
        )
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "FundingRate":
        """Reconstruct from to_dict() output."""
        return cls(
            venue=d["venue"],
            instrument=d["instrument"],
            funding_time=datetime.fromisoformat(d["funding_time"]),
            funding_rate=Decimal(d["funding_rate"]),
            mark_price=Decimal(d["mark_price"]) if d.get("mark_price") is not None else None,
            next_funding_time=(
                datetime.fromisoformat(d["next_funding_time"])
                if d.get("next_funding_time") is not None
                else None
            ),
            ingested_at=(
                datetime.fromisoformat(d["ingested_at"])
                if d.get("ingested_at") is not None
                else None
            ),
            schema_version=d.get("schema_version", CANONICAL_SCHEMA_VERSION),
        )
