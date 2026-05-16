"""Unit tests for universe loader and eligibility logic."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from strategies.sleeve_b.xs_momentum.universe import (
    DEFAULT_ELIGIBILITY_DELAY_DAYS,
    UniverseAsset,
    eligible_at,
    load_universe,
)


def _make_minimal_fixture(tmp_path: Path, *, frozen: bool = True,
                          reconst: bool = False) -> Path:
    """Write a minimal universe fixture for testing."""
    fixture = {
        "universe_membership_policy": "frozen" if frozen else "rolling",
        "reconstitution_permitted": reconst,
        "universe": [
            {
                "rank": 1, "symbol": "BTCUSDT", "base_asset": "BTC",
                "onboard_date": "2019-09-25", "adv_usdt": "12000000000",
            },
            {
                "rank": 2, "symbol": "NEWUSDT", "base_asset": "NEW",
                "onboard_date": "2025-12-14", "adv_usdt": "500000000",
            },
        ],
    }
    p = tmp_path / "universe.json"
    p.write_text(json.dumps(fixture))
    return p


class TestLoadUniverse:
    def test_loads_frozen_fixture(self, tmp_path):
        p = _make_minimal_fixture(tmp_path)
        assets = load_universe(p)
        assert len(assets) == 2
        assert assets[0].symbol == "BTCUSDT"
        assert assets[0].onboard_date == date(2019, 9, 25)
        assert assets[0].adv_usdt == Decimal("12000000000")

    def test_rejects_non_frozen_policy(self, tmp_path):
        p = _make_minimal_fixture(tmp_path, frozen=False)
        with pytest.raises(ValueError, match="frozen"):
            load_universe(p)

    def test_rejects_reconstitution_permitted(self, tmp_path):
        p = _make_minimal_fixture(tmp_path, reconst=True)
        with pytest.raises(ValueError, match="reconstitution"):
            load_universe(p)

    def test_loads_real_sleeve_b_fixture(self):
        """The actual Sleeve B fixture committed at 2af9981."""
        fixture_path = Path("tests/fixtures/sleeve_b/universe_top30_20260415.json")
        if not fixture_path.exists():
            pytest.skip("Real fixture not present")
        assets = load_universe(fixture_path)
        assert len(assets) == 30
        symbols = [a.symbol for a in assets]
        assert "BTCUSDT" in symbols
        assert "ETHUSDT" in symbols
        # Ranks should be 1..30
        ranks = sorted(a.rank for a in assets)
        assert ranks == list(range(1, 31))


class TestEligibility:
    def _universe(self):
        return [
            UniverseAsset(
                rank=1, symbol="OLD", base_asset="OLD",
                onboard_date=date(2020, 1, 1),
                adv_usdt=Decimal("1000000000"),
            ),
            UniverseAsset(
                rank=2, symbol="MID", base_asset="MID",
                onboard_date=date(2024, 6, 1),
                adv_usdt=Decimal("500000000"),
            ),
            UniverseAsset(
                rank=3, symbol="NEW", base_asset="NEW",
                onboard_date=date(2025, 12, 14),
                adv_usdt=Decimal("400000000"),
            ),
        ]

    def test_default_delay_is_14_days(self):
        assert DEFAULT_ELIGIBILITY_DELAY_DAYS == 14

    def test_all_eligible_far_future(self):
        u = self._universe()
        elig = eligible_at(u, date(2026, 1, 1))
        assert len(elig) == 3

    def test_recent_listing_not_eligible(self):
        u = self._universe()
        # NEW listed 2025-12-14; at 2025-12-20 it's 6 days old, < 14
        elig = eligible_at(u, date(2025, 12, 20))
        symbols = [a.symbol for a in elig]
        assert "OLD" in symbols
        assert "MID" in symbols
        assert "NEW" not in symbols

    def test_recent_listing_eligible_after_14_days(self):
        u = self._universe()
        # NEW listed 2025-12-14; at 2025-12-28 it's 14 days old, exactly eligible
        elig = eligible_at(u, date(2025, 12, 28))
        symbols = [a.symbol for a in elig]
        assert "NEW" in symbols

    def test_custom_delay(self):
        u = self._universe()
        # With 30-day delay, NEW at 2025-12-28 (14 days) is not eligible
        elig = eligible_at(u, date(2025, 12, 28), listing_delay_days=30)
        symbols = [a.symbol for a in elig]
        assert "NEW" not in symbols

    def test_before_any_listing(self):
        u = self._universe()
        elig = eligible_at(u, date(2019, 1, 1))
        assert elig == []
