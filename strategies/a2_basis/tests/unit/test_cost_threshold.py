"""Unit tests for compute_a2_round_trip_threshold_bps + A2RoundTripCost."""
from __future__ import annotations

from decimal import Decimal

import pytest

from strategies.a2_basis.config.profile_selector import (
    select_research_profile_for_a2,
)
from strategies.a2_basis.signal.cost_threshold import (
    A2RoundTripCost,
    compute_a2_round_trip_threshold_bps,
)


class TestComputeRoundTripBTC:
    """Expected math for BTCUSDT under the Day 22 placeholders:
        perp taker (binance VIP5 USDM) = 2.7 bps
        perp slippage (btc_eth_top_tier) = 1 bp
        perp one-way = 3.7 bps; round-trip = 7.4 bps

        spot taker (Binance Spot VIP5 with BNB) = 3.4 bps
        spot slippage (spot_btc_eth_top_tier) = 3 bps
        spot one-way = 6.4 bps; round-trip = 12.8 bps

        subtotal = 7.4 + 12.8 = 20.2 bps
        margin (0.2 fraction) = 4.04 bps
        total = 24.24 bps
    """

    def setup_method(self):
        self.bundle = select_research_profile_for_a2("BTCUSDT", "binance")

    def test_returns_a2_round_trip_cost(self):
        result = compute_a2_round_trip_threshold_bps(
            self.bundle,
            perp_slippage_tier_name="btc_eth_top_tier",
            spot_slippage_tier_name="spot_btc_eth_top_tier",
        )
        assert isinstance(result, A2RoundTripCost)

    def test_perp_entry_and_exit_each_at_3_7_bps(self):
        result = compute_a2_round_trip_threshold_bps(
            self.bundle,
            perp_slippage_tier_name="btc_eth_top_tier",
            spot_slippage_tier_name="spot_btc_eth_top_tier",
        )
        assert result.perp_entry_bps == Decimal("3.7")
        assert result.perp_exit_bps == Decimal("3.7")

    def test_spot_entry_and_exit_each_at_6_4_bps(self):
        result = compute_a2_round_trip_threshold_bps(
            self.bundle,
            perp_slippage_tier_name="btc_eth_top_tier",
            spot_slippage_tier_name="spot_btc_eth_top_tier",
        )
        assert result.spot_entry_bps == Decimal("6.4")
        assert result.spot_exit_bps == Decimal("6.4")

    def test_subtotal_at_20_2_bps(self):
        result = compute_a2_round_trip_threshold_bps(
            self.bundle,
            perp_slippage_tier_name="btc_eth_top_tier",
            spot_slippage_tier_name="spot_btc_eth_top_tier",
        )
        assert result.subtotal_bps == Decimal("20.2")

    def test_default_margin_is_20_percent(self):
        result = compute_a2_round_trip_threshold_bps(
            self.bundle,
            perp_slippage_tier_name="btc_eth_top_tier",
            spot_slippage_tier_name="spot_btc_eth_top_tier",
        )
        # 0.2 × 20.2 = 4.04
        assert result.uncertainty_margin_bps == Decimal("4.04")

    def test_total_at_24_24_bps(self):
        result = compute_a2_round_trip_threshold_bps(
            self.bundle,
            perp_slippage_tier_name="btc_eth_top_tier",
            spot_slippage_tier_name="spot_btc_eth_top_tier",
        )
        assert result.total_threshold_bps == Decimal("24.24")


class TestComputeRoundTripSOL:
    """Expected math for SOLUSDT under the Day 22 placeholders:
        perp taker (binance VIP5 USDM) = 2.7 bps
        perp slippage (liquid_alt_tier) = 3 bps
        perp one-way = 5.7 bps; round-trip = 11.4 bps

        spot taker = 3.4 bps
        spot slippage (spot_liquid_alt_tier) = 5 bps
        spot one-way = 8.4 bps; round-trip = 16.8 bps

        subtotal = 11.4 + 16.8 = 28.2 bps
        margin (0.2 fraction) = 5.64 bps
        total = 33.84 bps
    """

    def test_subtotal_at_28_2_bps(self):
        bundle = select_research_profile_for_a2("SOLUSDT", "binance")
        result = compute_a2_round_trip_threshold_bps(
            bundle,
            perp_slippage_tier_name="liquid_alt_tier",
            spot_slippage_tier_name="spot_liquid_alt_tier",
        )
        assert result.subtotal_bps == Decimal("28.2")
        assert result.uncertainty_margin_bps == Decimal("5.64")
        assert result.total_threshold_bps == Decimal("33.84")


class TestUncertaintyMarginParameterization:
    def test_zero_margin_means_total_equals_subtotal(self):
        bundle = select_research_profile_for_a2("BTCUSDT", "binance")
        result = compute_a2_round_trip_threshold_bps(
            bundle,
            perp_slippage_tier_name="btc_eth_top_tier",
            spot_slippage_tier_name="spot_btc_eth_top_tier",
            uncertainty_margin_fraction=Decimal("0"),
        )
        assert result.uncertainty_margin_bps == Decimal("0")
        assert result.total_threshold_bps == result.subtotal_bps

    def test_fifty_percent_margin(self):
        bundle = select_research_profile_for_a2("BTCUSDT", "binance")
        result = compute_a2_round_trip_threshold_bps(
            bundle,
            perp_slippage_tier_name="btc_eth_top_tier",
            spot_slippage_tier_name="spot_btc_eth_top_tier",
            uncertainty_margin_fraction=Decimal("0.5"),
        )
        # 0.5 × 20.2 = 10.1
        assert result.uncertainty_margin_bps == Decimal("10.1")
        # 20.2 + 10.1 = 30.3
        assert result.total_threshold_bps == Decimal("30.3")

    def test_negative_margin_raises(self):
        bundle = select_research_profile_for_a2("BTCUSDT", "binance")
        with pytest.raises(ValueError, match=">= 0"):
            compute_a2_round_trip_threshold_bps(
                bundle,
                perp_slippage_tier_name="btc_eth_top_tier",
                spot_slippage_tier_name="spot_btc_eth_top_tier",
                uncertainty_margin_fraction=Decimal("-0.1"),
            )

    def test_non_decimal_margin_raises(self):
        bundle = select_research_profile_for_a2("BTCUSDT", "binance")
        with pytest.raises(TypeError, match="Decimal"):
            compute_a2_round_trip_threshold_bps(
                bundle,
                perp_slippage_tier_name="btc_eth_top_tier",
                spot_slippage_tier_name="spot_btc_eth_top_tier",
                uncertainty_margin_fraction=0.2,
            )


class TestUnknownSlippageTierRaises:
    def test_unknown_perp_tier(self):
        bundle = select_research_profile_for_a2("BTCUSDT", "binance")
        with pytest.raises(ValueError, match="perp profile"):
            compute_a2_round_trip_threshold_bps(
                bundle,
                perp_slippage_tier_name="nonexistent",
                spot_slippage_tier_name="spot_btc_eth_top_tier",
            )

    def test_unknown_spot_tier(self):
        bundle = select_research_profile_for_a2("BTCUSDT", "binance")
        with pytest.raises(ValueError, match="spot profile"):
            compute_a2_round_trip_threshold_bps(
                bundle,
                perp_slippage_tier_name="btc_eth_top_tier",
                spot_slippage_tier_name="nonexistent",
            )


class TestA2RoundTripCostInvariants:
    def test_subtotal_mismatch_raises(self):
        with pytest.raises(ValueError, match="subtotal_bps"):
            A2RoundTripCost(
                perp_entry_bps=Decimal("1"),
                perp_exit_bps=Decimal("1"),
                spot_entry_bps=Decimal("1"),
                spot_exit_bps=Decimal("1"),
                subtotal_bps=Decimal("999"),  # wrong
                uncertainty_margin_bps=Decimal("0"),
                total_threshold_bps=Decimal("999"),
            )

    def test_total_mismatch_raises(self):
        with pytest.raises(ValueError, match="total_threshold_bps"):
            A2RoundTripCost(
                perp_entry_bps=Decimal("1"),
                perp_exit_bps=Decimal("1"),
                spot_entry_bps=Decimal("1"),
                spot_exit_bps=Decimal("1"),
                subtotal_bps=Decimal("4"),
                uncertainty_margin_bps=Decimal("1"),
                total_threshold_bps=Decimal("999"),  # wrong
            )

    def test_negative_leg_cost_raises(self):
        with pytest.raises(ValueError, match="must be non-negative"):
            A2RoundTripCost(
                perp_entry_bps=Decimal("-1"),
                perp_exit_bps=Decimal("1"),
                spot_entry_bps=Decimal("1"),
                spot_exit_bps=Decimal("1"),
                subtotal_bps=Decimal("2"),
                uncertainty_margin_bps=Decimal("0"),
                total_threshold_bps=Decimal("2"),
            )
