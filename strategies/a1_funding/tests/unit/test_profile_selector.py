"""Tests for A1 cost-profile selector.

Validates the Day 17b policy:
    venue normalized to lowercase
    "binance" + BTCUSDT/ETHUSDT → binance_vip5_btc_v1
    "binance" + altcoin → NotImplementedError
    non-binance venue → NotImplementedError
    returned config has stable profile_name + content_hash
"""
from __future__ import annotations

import pytest

from core.config.cost_model import (
    binance_vip5_alt_research_v1,
    binance_vip5_alt_v1,
    binance_vip5_btc_v1,
)
from strategies.a1_funding.config.profile_selector import (
    select_profile_for_a1,
)


# ─── Happy path: BTCUSDT/ETHUSDT on Binance ──────────────────────────────


class TestBinanceBtcEth:
    def test_btcusdt_binance_returns_vip5_btc(self):
        result = select_profile_for_a1("BTCUSDT", "binance")
        assert result.profile_name == "binance_vip5_btc_v1"
        assert result.content_hash == binance_vip5_btc_v1().content_hash

    def test_ethusdt_binance_returns_vip5_btc(self):
        result = select_profile_for_a1("ETHUSDT", "binance")
        assert result.profile_name == "binance_vip5_btc_v1"
        assert result.content_hash == binance_vip5_btc_v1().content_hash

    def test_btcusdt_and_ethusdt_share_profile(self):
        """The slippage-and-fee profile is shared between BTC and ETH on
        Binance because both are in the same liquidity tier. If they
        ever diverge, the shared profile must split."""
        btc = select_profile_for_a1("BTCUSDT", "binance")
        eth = select_profile_for_a1("ETHUSDT", "binance")
        assert btc.content_hash == eth.content_hash


# ─── Venue case insensitivity ────────────────────────────────────────────


class TestVenueCaseInsensitivity:
    def test_lowercase_binance(self):
        result = select_profile_for_a1("BTCUSDT", "binance")
        assert result.profile_name == "binance_vip5_btc_v1"

    def test_uppercase_binance(self):
        result = select_profile_for_a1("BTCUSDT", "BINANCE")
        assert result.profile_name == "binance_vip5_btc_v1"

    def test_mixedcase_binance(self):
        result = select_profile_for_a1("BTCUSDT", "Binance")
        assert result.profile_name == "binance_vip5_btc_v1"

    def test_all_case_variants_return_same_hash(self):
        """Case-insensitive venue matching must produce content-identical
        configs. If a future change normalizes differently, the hash
        comparison will catch it."""
        a = select_profile_for_a1("BTCUSDT", "binance")
        b = select_profile_for_a1("BTCUSDT", "BINANCE")
        c = select_profile_for_a1("BTCUSDT", "Binance")
        assert a.content_hash == b.content_hash == c.content_hash


# ─── Unsupported instrument / venue ──────────────────────────────────────


class TestUnsupportedRaises:
    def test_uncalibrated_altcoin_on_binance_raises(self):
        """DOGEUSDT is uncalibrated. SOLUSDT is now supported, so it
        cannot be the unsupported example."""
        with pytest.raises(NotImplementedError) as ei:
            select_profile_for_a1("DOGEUSDT", "binance")
        msg = str(ei.value)
        assert "DOGEUSDT" in msg
        assert "binance" in msg.lower()
        # Error message points at SOLUSDT as the calibrated example.
        assert "SOLUSDT" in msg
        assert "calibrated example" in msg

    def test_unknown_instrument_on_binance_raises(self):
        """AVAXUSDT is also uncalibrated."""
        with pytest.raises(NotImplementedError) as ei:
            select_profile_for_a1("AVAXUSDT", "binance")
        msg = str(ei.value)
        assert "AVAXUSDT" in msg
        assert "SOLUSDT" in msg  # message still points at calibrated example

    def test_bybit_raises(self):
        with pytest.raises(NotImplementedError) as ei:
            select_profile_for_a1("BTCUSDT", "bybit")
        msg = str(ei.value)
        assert "bybit" in msg
        assert "binance" in msg.lower()  # hint at what IS supported

    def test_okx_raises(self):
        with pytest.raises(NotImplementedError) as ei:
            select_profile_for_a1("BTCUSDT", "okx")
        assert "okx" in str(ei.value)

    def test_empty_venue_raises(self):
        with pytest.raises(NotImplementedError):
            select_profile_for_a1("BTCUSDT", "")


# ─── Returned-config invariants ──────────────────────────────────────────


class TestReturnedConfigInvariants:
    def test_returned_config_has_profile_name_set(self):
        """The selector returns calibrated profiles only, not placeholders.
        Calibrated profiles have profile_name set; placeholders don't.
        If this fails, the selector accidentally fell through to a
        placeholder."""
        result = select_profile_for_a1("BTCUSDT", "binance")
        assert result.profile_name is not None
        assert result.profile_name == "binance_vip5_btc_v1"

    def test_returned_config_has_source_metadata(self):
        result = select_profile_for_a1("BTCUSDT", "binance")
        assert result.source is not None
        assert result.source.source_url.startswith("https://")
        assert len(result.source.source_as_of) == 10  # YYYY-MM-DD

    def test_repeated_calls_return_content_equal_configs(self):
        """The selector is stateless and pure: same inputs always yield
        the same content_hash."""
        a = select_profile_for_a1("BTCUSDT", "binance")
        b = select_profile_for_a1("BTCUSDT", "binance")
        c = select_profile_for_a1("BTCUSDT", "binance")
        assert a.content_hash == b.content_hash == c.content_hash



# ─── Day 18a: SOLUSDT alt branch ─────────────────────────────────────────


class TestBinanceSolUsdt:
    def test_solusdt_binance_returns_vip5_alt(self):
        result = select_profile_for_a1("SOLUSDT", "binance")
        assert result.profile_name == "binance_vip5_alt_v1"
        assert result.content_hash == binance_vip5_alt_v1().content_hash

    def test_solusdt_distinct_from_btcusdt(self):
        btc = select_profile_for_a1("BTCUSDT", "binance")
        sol = select_profile_for_a1("SOLUSDT", "binance")
        assert btc.profile_name != sol.profile_name
        assert btc.content_hash != sol.content_hash

    def test_solusdt_case_insensitive_venue(self):
        for venue in ("binance", "BINANCE", "Binance"):
            result = select_profile_for_a1("SOLUSDT", venue)
            assert result.profile_name == "binance_vip5_alt_v1"



# ─── Day 19a: research-profile firewall ──────────────────────────────────


class TestResearchProfileFirewall:
    """Day 19a added binance_vip5_alt_research_v1 — a research-calibrated
    profile based on third-party spread data, NOT validated by tape
    or live A1 fills. The selector deliberately does NOT return the
    research profile; using it requires calling it directly by name.

    These tests enforce that firewall: any path through select_profile_for_a1
    must return the conservative binance_vip5_alt_v1, never the research
    variant. If a future change extends the selector to return the
    research profile (e.g. as a default), these tests fail and force
    a deliberate decision about whether the research profile has been
    empirically validated."""

    def test_solusdt_does_not_return_research_profile(self):
        result = select_profile_for_a1("SOLUSDT", "binance")
        assert result.profile_name == "binance_vip5_alt_v1", (
            f"SOLUSDT must return alt_v1 (conservative); got "
            f"{result.profile_name}. The research profile is "
            f"available only via direct call."
        )
        assert result.profile_name != "binance_vip5_alt_research_v1"

    def test_research_profile_only_reachable_by_direct_call(self):
        """The research profile is ONLY reachable by importing and
        calling it directly. No (instrument, venue) input to the
        selector returns it."""
        # Try several plausible inputs; none should yield the research profile.
        for instrument in ("SOLUSDT", "BTCUSDT", "ETHUSDT"):
            for venue in ("binance", "BINANCE"):
                result = select_profile_for_a1(instrument, venue)
                assert result.profile_name != "binance_vip5_alt_research_v1", (
                    f"select_profile_for_a1({instrument!r}, {venue!r}) "
                    f"returned research profile; firewall breached."
                )

    def test_research_profile_directly_callable(self):
        """Direct call works (and produces the documented profile)."""
        cm = binance_vip5_alt_research_v1()
        assert cm.profile_name == "binance_vip5_alt_research_v1"
