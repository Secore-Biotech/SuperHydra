"""Pair perp + spot trades into BasisObservation records.

Day 26 deliverable. Pure-function pairing logic: takes lists of perp
and spot trades, buckets them by cadence_seconds, emits one
BasisObservation per bucket present in BOTH markets with the last
trade in that bucket per market.

Per Day 26.2 reviewer lock: per-minute snapshots, configurable cadence,
default 60s.

Sampled-at convention:
  observation.sampled_at = max(last_perp_trade.time, last_spot_trade.time)
  This is the actual moment we had both prices. NOT bucket-start
  (which would lose the within-bucket timing detail).

Bucket alignment:
  bucket_start = floor(epoch_seconds / cadence_seconds) * cadence_seconds
  Bucket key is a UTC datetime; identical buckets across markets pair.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Sequence

from data.ingestion.vendors.binance.trade import BinanceTrade
from strategies.a2_basis.signal.evaluate import BasisObservation


@dataclass(frozen=True)
class BasisPairingStats:
    """Counters describing the pairing operation.

    perp_trades_in: trades passed to pairer (perp side)
    spot_trades_in: trades passed to pairer (spot side)
    perp_buckets: distinct cadence buckets that had at least one perp trade
    spot_buckets: distinct cadence buckets that had at least one spot trade
    common_buckets: buckets present in BOTH markets (one observation per)
    perp_only_buckets: buckets in perp only (no spot trade in same bucket)
    spot_only_buckets: buckets in spot only
    cadence_seconds: the cadence parameter
    """

    perp_trades_in: int
    spot_trades_in: int
    perp_buckets: int
    spot_buckets: int
    common_buckets: int
    perp_only_buckets: int
    spot_only_buckets: int
    cadence_seconds: int


def _bucket_start(trade_time: datetime, cadence_seconds: int) -> datetime:
    """Floor a trade time to its cadence-bucket start (UTC)."""
    epoch = int(trade_time.timestamp())
    bucket_epoch = (epoch // cadence_seconds) * cadence_seconds
    return datetime.fromtimestamp(bucket_epoch, tz=timezone.utc)


def _last_trade_per_bucket(
    trades: Sequence[BinanceTrade],
    cadence_seconds: int,
) -> dict[datetime, BinanceTrade]:
    """Build a dict mapping bucket_start -> last trade in that bucket.

    'Last' is defined as max by (time, id) — id breaks ties for trades
    with identical millisecond timestamps.
    """
    buckets: dict[datetime, BinanceTrade] = {}
    for t in trades:
        key = _bucket_start(t.time, cadence_seconds)
        existing = buckets.get(key)
        if existing is None or (t.time, t.id) > (existing.time, existing.id):
            buckets[key] = t
    return buckets


def pair_perp_spot_to_basis(
    perp_trades: Sequence[BinanceTrade],
    spot_trades: Sequence[BinanceTrade],
    *,
    cadence_seconds: int = 60,
) -> tuple[list[BasisObservation], BasisPairingStats]:
    """Pair perp + spot trades into BasisObservation records.

    Args:
        perp_trades: perp-side trades, any order. Expected venue/instrument
            consistency is the caller's responsibility.
        spot_trades: spot-side trades, any order.
        cadence_seconds: bucket size (default 60s = per-minute snapshots).

    Returns:
        (observations, stats)

    Raises:
        ValueError: cadence_seconds <= 0.
    """
    if cadence_seconds <= 0:
        raise ValueError(
            f"cadence_seconds must be positive, got {cadence_seconds}"
        )

    perp_by_bucket = _last_trade_per_bucket(perp_trades, cadence_seconds)
    spot_by_bucket = _last_trade_per_bucket(spot_trades, cadence_seconds)

    common = sorted(set(perp_by_bucket) & set(spot_by_bucket))

    observations: list[BasisObservation] = []
    for bucket_key in common:
        perp_t = perp_by_bucket[bucket_key]
        spot_t = spot_by_bucket[bucket_key]
        observations.append(BasisObservation(
            sampled_at=max(perp_t.time, spot_t.time),
            perp_price=perp_t.price,
            spot_price=spot_t.price,
        ))

    stats = BasisPairingStats(
        perp_trades_in=len(perp_trades),
        spot_trades_in=len(spot_trades),
        perp_buckets=len(perp_by_bucket),
        spot_buckets=len(spot_by_bucket),
        common_buckets=len(common),
        perp_only_buckets=len(perp_by_bucket) - len(common),
        spot_only_buckets=len(spot_by_bucket) - len(common),
        cadence_seconds=cadence_seconds,
    )

    return observations, stats
