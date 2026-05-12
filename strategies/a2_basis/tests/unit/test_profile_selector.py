"""Unit tests for select_research_profile_for_a2 and A2CostBundle."""
from __future__ import annotations

import pytest

from strategies.a2_basis.config.profile_selector import (
    A2CostBundle,
    select_research_profile_for_a2,
)


class TestSelectResearchProfileForA2:
    def test_returns_bundle_for_btcusdt_binance(self):
        bundle = select_research_profile_for_a2("BTCUSDT", "binance")
        assert isinstance(bundle, A2CostBundle)
        assert bundle.perp_profile.profile_name == "binance_vip5_btc_v1"
        assert bundle.spot_profile.profile_name == "binance_vip5_spot_placeholder_v0"

    def test_returns_bundle_for_ethusdt_binance(self):
        bundle = select_research_profile_for_a2("ETHUSDT", "binance")
        assert bundle.perp_profile.profile_name == "binance_vip5_btc_v1"

    def test_returns_bundle_for_solusdt_binance(self):
        bundle = select_research_profile_for_a2("SOLUSDT", "binance")
        assert bundle.perp_profile.profile_name == "binance_vip5_alt_v1"
        assert bundle.spot_profile.profile_name == "binance_vip5_spot_placeholder_v0"

    def test_venue_is_case_insensitive(self):
        bundle = select_research_profile_for_a2("BTCUSDT", "Binance")
        assert bundle.perp_profile.profile_name == "binance_vip5_btc_v1"

    def test_raises_for_unsupported_instrument(self):
        with pytest.raises(NotImplementedError, match="No A2 cost bundle"):
            select_research_profile_for_a2("DOGEUSDT", "binance")

    def test_raises_for_unknown_venue(self):
        with pytest.raises(NotImplementedError, match="binance"):
            select_research_profile_for_a2("BTCUSDT", "okx")


class TestA2CostBundleSemantics:
    def test_perp_and_spot_have_distinct_hashes(self):
        bundle = select_research_profile_for_a2("BTCUSDT", "binance")
        assert bundle.perp_profile.content_hash != bundle.spot_profile.content_hash

    def test_btc_and_sol_bundles_have_different_perp_profiles(self):
        btc_bundle = select_research_profile_for_a2("BTCUSDT", "binance")
        sol_bundle = select_research_profile_for_a2("SOLUSDT", "binance")
        assert (btc_bundle.perp_profile.content_hash
                != sol_bundle.perp_profile.content_hash)

    def test_btc_and_sol_bundles_share_spot_profile(self):
        """The spot placeholder is the same profile for both
        instruments — it carries both spot_btc_eth_top_tier and
        spot_liquid_alt_tier as separate slippage tiers."""
        btc_bundle = select_research_profile_for_a2("BTCUSDT", "binance")
        sol_bundle = select_research_profile_for_a2("SOLUSDT", "binance")
        assert (btc_bundle.spot_profile.content_hash
                == sol_bundle.spot_profile.content_hash)
