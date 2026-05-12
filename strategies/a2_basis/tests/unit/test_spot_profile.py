"""Unit tests for binance_vip5_spot_placeholder_v0."""
from __future__ import annotations

from decimal import Decimal

import pytest

from core.config.cost_model import (
    COST_MODEL_SCHEMA_VERSION,
    binance_vip5_spot_placeholder_v0,
)


def test_factory_returns_valid_config():
    profile = binance_vip5_spot_placeholder_v0()
    assert profile.schema_version == COST_MODEL_SCHEMA_VERSION
    assert profile.profile_name == "binance_vip5_spot_placeholder_v0"


def test_fees_match_documented_values():
    profile = binance_vip5_spot_placeholder_v0()
    [fee] = profile.fee_schedules
    assert fee.venue == "binance"
    assert fee.maker_bps == Decimal("0.000135")  # 1.35 bps
    assert fee.taker_bps == Decimal("0.00034")   # 3.4 bps


def test_has_both_spot_slippage_tiers():
    profile = binance_vip5_spot_placeholder_v0()
    tier_names = {t.tier_name for t in profile.slippage_tiers}
    assert tier_names == {"spot_btc_eth_top_tier", "spot_liquid_alt_tier"}


def test_btc_eth_top_tier_at_3bps():
    profile = binance_vip5_spot_placeholder_v0()
    tier = next(t for t in profile.slippage_tiers
                if t.tier_name == "spot_btc_eth_top_tier")
    assert tier.slippage_bps == Decimal("0.0003")  # 3 bps


def test_liquid_alt_tier_at_5bps():
    profile = binance_vip5_spot_placeholder_v0()
    tier = next(t for t in profile.slippage_tiers
                if t.tier_name == "spot_liquid_alt_tier")
    assert tier.slippage_bps == Decimal("0.0005")  # 5 bps


def test_profile_carries_placeholder_indicator_in_notes():
    profile = binance_vip5_spot_placeholder_v0()
    assert "PLACEHOLDER" in profile.notes


def test_profile_has_source_attribution():
    profile = binance_vip5_spot_placeholder_v0()
    assert profile.source is not None
    assert "binance.com" in profile.source.source_url


def test_content_hash_is_stable_across_calls():
    p1 = binance_vip5_spot_placeholder_v0()
    p2 = binance_vip5_spot_placeholder_v0()
    assert p1.content_hash == p2.content_hash


def test_content_hash_differs_from_a1_alt_profile():
    """Spot placeholder must have a different hash than the alt-perp profile."""
    from core.config.cost_model import binance_vip5_alt_v1
    spot = binance_vip5_spot_placeholder_v0()
    perp = binance_vip5_alt_v1()
    assert spot.content_hash != perp.content_hash
