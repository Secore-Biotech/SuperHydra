"""Unit tests for cross-sectional momentum signal."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from strategies.sleeve_b.xs_momentum.prices import PriceBar, PriceSeries
from strategies.sleeve_b.xs_momentum.signal import (
    DECILE_FRACTION,
    LOOKBACK_DAYS,
    MIN_ELIGIBLE_FOR_REBALANCE,
    compute_signal,
)
from strategies.sleeve_b.xs_momentum.universe import UniverseAsset


def _make_price_series(
    symbol: str, start: date, days: int,
    *,
    return_per_day: float = 0.0,
    initial: float = 100.0,
) -> PriceSeries:
    """Build a price series with constant daily compounding return."""
    bars = []
    price = Decimal(str(initial))
    for i in range(days):
        bars.append(PriceBar(
            bar_date=start + timedelta(days=i),
            open_price=price,
            close_price=price,
        ))
        price = price * (Decimal("1") + Decimal(str(return_per_day)))
    return PriceSeries(symbol, bars)


def _make_universe(n: int, listing: date) -> list[UniverseAsset]:
    """Build a universe of n assets, all listed on `listing`."""
    return [
        UniverseAsset(
            rank=i + 1, symbol=f"S{i:02d}", base_asset=f"B{i}",
            onboard_date=listing,
            adv_usdt=Decimal(str(1000000000 - i * 1000000)),
        )
        for i in range(n)
    ]


class TestRanking:
    def test_returns_ranked_descending(self):
        """Top decile = highest returns, bottom decile = lowest."""
        rebalance = date(2024, 6, 17)  # Monday
        listing = date(2024, 1, 1)
        universe = _make_universe(30, listing)
        prices = {}
        # Each asset has a different 14-day return:
        # S00 highest, S29 lowest
        for i, asset in enumerate(universe):
            rpd = (30 - i) * 0.001
            series = _make_price_series(
                asset.symbol, listing, days=200, return_per_day=rpd,
            )
            prices[asset.symbol] = series
        out = compute_signal(
            rebalance_at=rebalance, universe=universe, prices=prices,
        )
        assert not out.skipped
        assert out.long_bucket == ["S00", "S01", "S02"]  # top-3 of 30
        assert out.short_bucket == ["S27", "S28", "S29"]  # bottom-3


class TestVariableDeciles:
    """D9: decile_size = ceil(0.10 * N), min 1."""

    def test_n_30_yields_3(self):
        rebalance = date(2024, 6, 17)
        listing = date(2024, 1, 1)
        universe = _make_universe(30, listing)
        prices = {
            a.symbol: _make_price_series(
                a.symbol, listing, days=200,
                return_per_day=(i + 1) * 0.001,
            )
            for i, a in enumerate(universe)
        }
        out = compute_signal(
            rebalance_at=rebalance, universe=universe, prices=prices,
        )
        assert out.long_decile_size == 3
        assert out.short_decile_size == 3

    def test_n_18_yields_2(self):
        rebalance = date(2024, 6, 17)
        listing = date(2024, 1, 1)
        universe = _make_universe(18, listing)
        prices = {
            a.symbol: _make_price_series(
                a.symbol, listing, days=200,
                return_per_day=(i + 1) * 0.001,
            )
            for i, a in enumerate(universe)
        }
        out = compute_signal(
            rebalance_at=rebalance, universe=universe, prices=prices,
        )
        # ceil(0.10 * 18) = 2
        assert out.long_decile_size == 2
        assert out.short_decile_size == 2

    def test_n_16_yields_2(self):
        rebalance = date(2024, 6, 17)
        listing = date(2024, 1, 1)
        universe = _make_universe(16, listing)
        prices = {
            a.symbol: _make_price_series(
                a.symbol, listing, days=200,
                return_per_day=(i + 1) * 0.001,
            )
            for i, a in enumerate(universe)
        }
        out = compute_signal(
            rebalance_at=rebalance, universe=universe, prices=prices,
        )
        # ceil(0.10 * 16) = 2
        assert out.long_decile_size == 2
        assert out.short_decile_size == 2

    def test_minimum_decile_is_1(self):
        """With small N, ceil(0.10 * N) could be 1 - never 0."""
        rebalance = date(2024, 6, 17)
        listing = date(2024, 1, 1)
        universe = _make_universe(5, listing)
        prices = {
            a.symbol: _make_price_series(
                a.symbol, listing, days=200,
                return_per_day=(i + 1) * 0.001,
            )
            for i, a in enumerate(universe)
        }
        out = compute_signal(
            rebalance_at=rebalance, universe=universe, prices=prices,
        )
        # ceil(0.10 * 5) = 1
        assert out.long_decile_size == 1
        assert out.short_decile_size == 1


class TestEligibilityIntegration:
    """D10: 14-day listing eligibility."""

    def test_recently_listed_asset_excluded(self):
        rebalance = date(2024, 6, 17)
        # Mix: 10 assets listed long ago, 5 assets listed 7 days ago
        old_listing = date(2024, 1, 1)
        new_listing = rebalance - timedelta(days=7)
        old_universe = _make_universe(10, old_listing)
        new_universe = [
            UniverseAsset(
                rank=10 + i, symbol=f"N{i:02d}", base_asset=f"NB{i}",
                onboard_date=new_listing,
                adv_usdt=Decimal("500000000"),
            )
            for i in range(5)
        ]
        universe = old_universe + new_universe
        prices = {
            a.symbol: _make_price_series(
                a.symbol, old_listing, days=200,
                return_per_day=0.001,
            )
            for a in old_universe
        }
        for a in new_universe:
            prices[a.symbol] = _make_price_series(
                a.symbol, new_listing, days=20, return_per_day=0.001,
            )
        out = compute_signal(
            rebalance_at=rebalance, universe=universe, prices=prices,
        )
        # Only the 10 old assets should be eligible
        assert out.eligible_count == 10
        for new_asset in new_universe:
            assert new_asset.symbol not in out.eligible
        # New assets should appear in excluded_symbols with the correct reason
        excluded_listing = [
            e for e in out.excluded_symbols
            if e["reason"] == "listing_age_insufficient"
        ]
        assert len(excluded_listing) == 5


class TestSkipRebalance:
    """D11: skip if eligible < 4."""

    def test_eligible_3_skips(self):
        rebalance = date(2024, 6, 17)
        listing = date(2024, 1, 1)
        universe = _make_universe(3, listing)
        prices = {
            a.symbol: _make_price_series(
                a.symbol, listing, days=200, return_per_day=0.001,
            )
            for a in universe
        }
        out = compute_signal(
            rebalance_at=rebalance, universe=universe, prices=prices,
        )
        assert out.skipped is True
        assert out.skip_reason is not None
        assert "3" in out.skip_reason
        assert out.long_bucket == []
        assert out.short_bucket == []

    def test_eligible_4_does_not_skip(self):
        rebalance = date(2024, 6, 17)
        listing = date(2024, 1, 1)
        universe = _make_universe(4, listing)
        prices = {
            a.symbol: _make_price_series(
                a.symbol, listing, days=200,
                return_per_day=(i + 1) * 0.001,
            )
            for i, a in enumerate(universe)
        }
        out = compute_signal(
            rebalance_at=rebalance, universe=universe, prices=prices,
        )
        assert out.skipped is False
        # ceil(0.10 * 4) = 1
        assert out.long_decile_size == 1
        assert out.short_decile_size == 1


class TestDataExclusion:
    def test_missing_price_series_excluded(self):
        rebalance = date(2024, 6, 17)
        listing = date(2024, 1, 1)
        universe = _make_universe(5, listing)
        # Drop the price series for S02
        prices = {
            a.symbol: _make_price_series(
                a.symbol, listing, days=200, return_per_day=0.001,
            )
            for a in universe if a.symbol != "S02"
        }
        out = compute_signal(
            rebalance_at=rebalance, universe=universe, prices=prices,
        )
        assert "S02" not in out.eligible
        excluded = [e for e in out.excluded_symbols if e["symbol"] == "S02"]
        assert len(excluded) == 1
        assert excluded[0]["reason"] == "no_price_series"
