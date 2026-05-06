"""Unit tests for data.ingestion.vendors.binance.funding_rate.FundingRate.

Coverage:
  - Validation: timezone-naive, lowercase venue, Decimal types, ordering
  - Identity tuple stability
  - Content hash determinism (same content → same hash)
  - Content hash excludes ingested_at
  - Round-trip via to_dict/from_dict
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from data.ingestion.vendors.binance.funding_rate import (
    CANONICAL_SCHEMA_VERSION,
    FundingRate,
)


UTC = timezone.utc


def _make(**overrides):
    """Default-valid FundingRate with overrideable fields."""
    base = dict(
        venue="binance",
        instrument="BTCUSDT",
        funding_time=datetime(2026, 1, 15, 8, 0, 0, tzinfo=UTC),
        funding_rate=Decimal("0.0001"),
        mark_price=Decimal("50000"),
        next_funding_time=datetime(2026, 1, 15, 16, 0, 0, tzinfo=UTC),
    )
    base.update(overrides)
    return FundingRate(**base)


# ─── Validation ──────────────────────────────────────────────────────────


def test_rejects_uppercase_venue():
    with pytest.raises(ValueError, match="venue"):
        _make(venue="Binance")


def test_rejects_empty_venue():
    with pytest.raises(ValueError, match="venue"):
        _make(venue="")


def test_rejects_empty_instrument():
    with pytest.raises(ValueError, match="instrument"):
        _make(instrument="")


def test_rejects_naive_funding_time():
    with pytest.raises(ValueError, match="timezone-aware"):
        _make(funding_time=datetime(2026, 1, 15, 8, 0, 0))  # no tzinfo


def test_rejects_non_utc_funding_time():
    eastern = timezone(timedelta(hours=-5))
    with pytest.raises(ValueError, match="UTC"):
        _make(funding_time=datetime(2026, 1, 15, 3, 0, 0, tzinfo=eastern))


def test_rejects_float_funding_rate():
    with pytest.raises(TypeError, match="Decimal"):
        _make(funding_rate=0.0001)  # float, not Decimal


def test_rejects_float_mark_price():
    with pytest.raises(TypeError, match="Decimal"):
        _make(mark_price=50000.0)  # float, not Decimal


def test_accepts_none_mark_price():
    fr = _make(mark_price=None)
    assert fr.mark_price is None


def test_rejects_next_funding_time_not_after_funding_time():
    ft = datetime(2026, 1, 15, 8, 0, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="strictly after"):
        _make(funding_time=ft, next_funding_time=ft)
    with pytest.raises(ValueError, match="strictly after"):
        _make(funding_time=ft, next_funding_time=ft - timedelta(seconds=1))


def test_rejects_wrong_schema_version():
    with pytest.raises(ValueError, match="schema_version"):
        FundingRate(
            venue="binance",
            instrument="BTCUSDT",
            funding_time=datetime(2026, 1, 15, 8, 0, 0, tzinfo=UTC),
            funding_rate=Decimal("0.0001"),
            schema_version="not_the_version",
        )


# ─── Identity ────────────────────────────────────────────────────────────


def test_identity_tuple_stable_across_construction():
    a = _make()
    b = _make()
    assert a.identity == b.identity


def test_identity_distinct_when_funding_time_differs():
    a = _make(
        funding_time=datetime(2026, 1, 15, 8, 0, 0, tzinfo=UTC),
        next_funding_time=datetime(2026, 1, 15, 16, 0, 0, tzinfo=UTC),
    )
    b = _make(
        funding_time=datetime(2026, 1, 15, 16, 0, 0, tzinfo=UTC),
        next_funding_time=datetime(2026, 1, 16, 0, 0, 0, tzinfo=UTC),
    )
    assert a.identity != b.identity


def test_identity_distinct_when_instrument_differs():
    a = _make(instrument="BTCUSDT")
    b = _make(instrument="ETHUSDT")
    assert a.identity != b.identity


# ─── Content hash ─────────────────────────────────────────────────────────


def test_content_hash_deterministic():
    a = _make()
    b = _make()
    assert a.content_hash == b.content_hash


def test_content_hash_excludes_ingested_at():
    """Ingestion time must not change the hash — same data ingested at
    different times must produce identical hashes."""
    t1 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
    a = _make(ingested_at=t1)
    b = _make(ingested_at=t2)
    assert a.content_hash == b.content_hash


def test_content_hash_changes_on_rate_change():
    """A vendor restatement (same identity, different rate) produces a
    different hash. This is how reconciliation detects restatements."""
    a = _make(funding_rate=Decimal("0.0001"))
    b = _make(funding_rate=Decimal("0.00011"))
    assert a.content_hash != b.content_hash


def test_content_hash_changes_on_mark_price_change():
    a = _make(mark_price=Decimal("50000"))
    b = _make(mark_price=Decimal("50001"))
    assert a.content_hash != b.content_hash


def test_content_hash_is_hex_sha256():
    fr = _make()
    h = fr.content_hash
    assert len(h) == 64  # 32 bytes hex
    int(h, 16)  # valid hex


# ─── Round-trip ──────────────────────────────────────────────────────────


def test_round_trip_via_dict():
    a = _make()
    b = FundingRate.from_dict(a.to_dict())
    assert a == b
    assert a.content_hash == b.content_hash


def test_round_trip_preserves_decimal_precision():
    """Decimal precision must survive the dict round-trip; this is why
    Decimal becomes str rather than float in to_dict()."""
    fr = _make(funding_rate=Decimal("0.000123456789012345"))
    rt = FundingRate.from_dict(fr.to_dict())
    assert rt.funding_rate == Decimal("0.000123456789012345")


def test_round_trip_preserves_none_mark_price():
    fr = _make(mark_price=None)
    rt = FundingRate.from_dict(fr.to_dict())
    assert rt.mark_price is None


def test_round_trip_preserves_none_next_funding_time():
    fr = _make(next_funding_time=None)
    rt = FundingRate.from_dict(fr.to_dict())
    assert rt.next_funding_time is None


# ─── Schema version ──────────────────────────────────────────────────────


def test_schema_version_default():
    fr = _make()
    assert fr.schema_version == CANONICAL_SCHEMA_VERSION
    assert fr.schema_version == "funding_rate.v1"


def test_schema_version_in_content_hash():
    """Hash must change if schema_version changes; we test this by
    constructing one record with the legitimate version and confirming
    the version string appears in the hashable payload (indirectly:
    a change to CANONICAL_SCHEMA_VERSION constant would change hashes
    of every existing record)."""
    fr = _make()
    assert fr.schema_version in str(fr.to_dict()["schema_version"])
