"""Unit tests for the Day 20.4 firewall-hole function in profile_selector.

Two test classes:
  - TestResearchProfileFirewallHole: the new explicit-access function
    returns research profiles correctly and refuses unsupported inputs.
  - TestResearchProfileFirewallStillHolds: regression assertion that
    the default selector continues to firewall research profiles
    (no input returns a profile whose name contains 'research').
"""
from __future__ import annotations

import pytest

from strategies.a1_funding.config.profile_selector import (
    select_profile_for_a1,
    select_research_profile_for_a1,
)


class TestResearchProfileFirewallHole:
    def test_returns_research_profile_for_solusdt_binance(self):
        profile = select_research_profile_for_a1("SOLUSDT", "binance")
        assert "research" in profile.profile_name.lower()
        assert profile.profile_name == "binance_vip5_alt_research_v1"

    def test_returns_research_profile_for_solusdt_case_insensitive_venue(self):
        profile = select_research_profile_for_a1("SOLUSDT", "Binance")
        assert profile.profile_name == "binance_vip5_alt_research_v1"

    def test_raises_for_unsupported_instrument(self):
        with pytest.raises(NotImplementedError, match="No A1 research profile"):
            select_research_profile_for_a1("BTCUSDT", "binance")

    def test_raises_for_unknown_venue(self):
        with pytest.raises(NotImplementedError, match="binance"):
            select_research_profile_for_a1("SOLUSDT", "okx")


class TestResearchProfileFirewallStillHolds:
    """The default selector must NEVER return a research-named profile,
    even after adding the explicit firewall-hole function. This is a
    regression test for the Day 19a firewall property."""

    def test_solusdt_default_selector_returns_non_research_profile(self):
        profile = select_profile_for_a1("SOLUSDT", "binance")
        assert "research" not in profile.profile_name.lower()

    def test_btcusdt_default_selector_returns_non_research_profile(self):
        profile = select_profile_for_a1("BTCUSDT", "binance")
        assert "research" not in profile.profile_name.lower()

    def test_ethusdt_default_selector_returns_non_research_profile(self):
        profile = select_profile_for_a1("ETHUSDT", "binance")
        assert "research" not in profile.profile_name.lower()
