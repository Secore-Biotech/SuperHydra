"""Unit tests for basis_pairing.

Pure function tests with synthetic BinanceTrade inputs. No network,
no DB.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from data.ingestion.vendors.binance.trade import BinanceTrade
from strategies.a2_basis.data.basis_pairing import (
    BasisPairingStats,
    pair_perp_spot_to_basis,
)
from strategies.a2_basis.signal.evaluate import BasisObservation


def _ts(seconds: int) -> datetime:
    """Anchor timestamp at 2024-01-01 12:00:00 UTC + offset seconds."""
    return datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc) + timedelta(
        seconds=seconds
    )


def _trade(
    *,
    id_: int,
    time: datetime,
    price: str,
    instrument: str = "SOLUSDT",
    qty: str = "1.0",
    is_buyer_maker: bool = False,
) -> BinanceTrade:
    return BinanceTrade(
        venue="binance",
        instrument=instrument,
        id=id_,
        price=Decimal(price),
        qty=Decimal(qty),
        time=time,
        is_buyer_maker=is_buyer_maker,
        ingested_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )


class TestEmptyInputs:
    def test_both_empty(self):
        obs, stats = pair_perp_spot_to_basis([], [])
        assert obs == []
        assert stats.perp_trades_in == 0
        assert stats.spot_trades_in == 0
        assert stats.common_buckets == 0

    def test_only_perp_no_spot(self):
        perp = [_trade(id_=1, time=_ts(0), price="100.00")]
        obs, stats = pair_perp_spot_to_basis(perp, [])
        assert obs == []
        assert stats.perp_buckets == 1
        assert stats.spot_buckets == 0
        assert stats.perp_only_buckets == 1
        assert stats.common_buckets == 0

    def test_only_spot_no_perp(self):
        spot = [_trade(id_=1, time=_ts(0), price="100.00")]
        obs, stats = pair_perp_spot_to_basis([], spot)
        assert obs == []
        assert stats.spot_only_buckets == 1


class TestSingleBucketPairing:
    def test_one_trade_each_market_same_bucket(self):
        perp = [_trade(id_=1, time=_ts(10), price="100.10")]
        spot = [_trade(id_=1, time=_ts(20), price="100.00")]
        obs, stats = pair_perp_spot_to_basis(perp, spot)
        assert len(obs) == 1
        # sampled_at = max(perp_time, spot_time) = _ts(20)
        assert obs[0].sampled_at == _ts(20)
        assert obs[0].perp_price == Decimal("100.10")
        assert obs[0].spot_price == Decimal("100.00")
        assert stats.common_buckets == 1

    def test_basis_bps_derived_correctly(self):
        # perp 100.10, spot 100.00 → basis = 10 bps
        perp = [_trade(id_=1, time=_ts(10), price="100.10")]
        spot = [_trade(id_=1, time=_ts(20), price="100.00")]
        obs, _ = pair_perp_spot_to_basis(perp, spot)
        assert obs[0].basis_bps == Decimal("10")


class TestMultipleTradesPerBucket:
    def test_uses_last_trade_in_each_bucket(self):
        """Three perp trades within the same minute, latest one wins."""
        perp = [
            _trade(id_=1, time=_ts(10), price="100.10"),
            _trade(id_=2, time=_ts(30), price="100.20"),
            _trade(id_=3, time=_ts(45), price="100.30"),
        ]
        spot = [_trade(id_=10, time=_ts(50), price="100.00")]
        obs, stats = pair_perp_spot_to_basis(perp, spot)
        assert len(obs) == 1
        # Last perp trade in bucket (id_=3, t=_ts(45)) used
        assert obs[0].perp_price == Decimal("100.30")
        # sampled_at = max(45, 50) = 50
        assert obs[0].sampled_at == _ts(50)


class TestSequentialBuckets:
    def test_two_consecutive_buckets(self):
        # Bucket 1 (12:00-12:01): perp at 12:00:30, spot at 12:00:45
        # Bucket 2 (12:01-12:02): perp at 12:01:15, spot at 12:01:50
        perp = [
            _trade(id_=1, time=_ts(30), price="100.10"),
            _trade(id_=2, time=_ts(75), price="100.20"),
        ]
        spot = [
            _trade(id_=10, time=_ts(45), price="100.00"),
            _trade(id_=11, time=_ts(110), price="100.05"),
        ]
        obs, stats = pair_perp_spot_to_basis(perp, spot)
        assert len(obs) == 2
        # Strictly ascending sampled_at
        assert obs[0].sampled_at < obs[1].sampled_at
        assert obs[0].sampled_at == _ts(45)
        assert obs[1].sampled_at == _ts(110)
        assert stats.common_buckets == 2
        assert stats.perp_only_buckets == 0
        assert stats.spot_only_buckets == 0


class TestNonOverlappingBuckets:
    def test_perp_in_bucket_a_spot_in_bucket_b(self):
        # Perp at 12:00 bucket, spot at 12:05 bucket. No common bucket.
        perp = [_trade(id_=1, time=_ts(30), price="100.10")]
        spot = [_trade(id_=10, time=_ts(330), price="100.00")]
        obs, stats = pair_perp_spot_to_basis(perp, spot)
        assert obs == []
        assert stats.perp_only_buckets == 1
        assert stats.spot_only_buckets == 1
        assert stats.common_buckets == 0


class TestCadenceParameterization:
    def test_one_second_cadence(self):
        """At 1s cadence, even same-minute trades end up in distinct buckets."""
        perp = [_trade(id_=1, time=_ts(30), price="100.10")]
        spot = [_trade(id_=10, time=_ts(31), price="100.00")]
        obs, stats = pair_perp_spot_to_basis(
            perp, spot, cadence_seconds=1,
        )
        # Different 1s buckets → no observation
        assert obs == []
        assert stats.cadence_seconds == 1

    def test_one_second_cadence_same_bucket(self):
        """Two trades within the same 1s bucket pair."""
        perp = [_trade(id_=1, time=_ts(30), price="100.10")]
        # Same second: _ts(30) and _ts(30) again
        spot = [_trade(id_=10, time=_ts(30), price="100.00")]
        obs, _ = pair_perp_spot_to_basis(
            perp, spot, cadence_seconds=1,
        )
        assert len(obs) == 1

    def test_zero_cadence_raises(self):
        with pytest.raises(ValueError, match="cadence_seconds"):
            pair_perp_spot_to_basis([], [], cadence_seconds=0)

    def test_negative_cadence_raises(self):
        with pytest.raises(ValueError, match="cadence_seconds"):
            pair_perp_spot_to_basis([], [], cadence_seconds=-60)


class TestStatsCorrectness:
    def test_all_stats_fields_populated(self):
        # 3 perp trades in 2 buckets, 2 spot trades in 2 buckets, 1 common
        perp = [
            _trade(id_=1, time=_ts(10), price="100.10"),   # bucket 0
            _trade(id_=2, time=_ts(20), price="100.20"),   # bucket 0
            _trade(id_=3, time=_ts(70), price="100.30"),   # bucket 1
        ]
        spot = [
            _trade(id_=10, time=_ts(40), price="100.00"),  # bucket 0
            _trade(id_=11, time=_ts(200), price="100.05"), # bucket 3
        ]
        obs, stats = pair_perp_spot_to_basis(perp, spot)
        assert stats.perp_trades_in == 3
        assert stats.spot_trades_in == 2
        assert stats.perp_buckets == 2  # buckets 0 and 1
        assert stats.spot_buckets == 2  # buckets 0 and 3
        assert stats.common_buckets == 1  # only bucket 0
        assert stats.perp_only_buckets == 1  # bucket 1
        assert stats.spot_only_buckets == 1  # bucket 3
        assert stats.cadence_seconds == 60


class TestOrderingInvariants:
    def test_observations_strictly_ascending_by_sampled_at(self):
        """Across many buckets, output is strictly time-ascending."""
        perp = [
            _trade(id_=i, time=_ts(i * 60 + 10), price=f"100.{i:02d}")
            for i in range(10)
        ]
        spot = [
            _trade(id_=100 + i, time=_ts(i * 60 + 20), price="100.00")
            for i in range(10)
        ]
        obs, _ = pair_perp_spot_to_basis(perp, spot)
        assert len(obs) == 10
        for i in range(1, len(obs)):
            assert obs[i].sampled_at > obs[i - 1].sampled_at

    def test_pairing_is_order_independent(self):
        """Shuffling input order produces same output."""
        import random
        rng = random.Random(42)
        perp = [
            _trade(id_=i, time=_ts(i * 60 + 10), price=f"100.{i:02d}")
            for i in range(20)
        ]
        spot = [
            _trade(id_=100 + i, time=_ts(i * 60 + 20), price="100.00")
            for i in range(20)
        ]
        obs1, _ = pair_perp_spot_to_basis(perp, spot)
        rng.shuffle(perp)
        rng.shuffle(spot)
        obs2, _ = pair_perp_spot_to_basis(perp, spot)
        # Same number of observations
        assert len(obs1) == len(obs2)
        # Same sampled_at sequence
        assert [o.sampled_at for o in obs1] == [o.sampled_at for o in obs2]
        # Same prices
        assert [o.perp_price for o in obs1] == [o.perp_price for o in obs2]
        assert [o.spot_price for o in obs1] == [o.spot_price for o in obs2]
