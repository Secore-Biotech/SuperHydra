"""Unit tests for strategies.a1_funding.config.sizing."""
from __future__ import annotations

from decimal import Decimal

import pytest

from strategies.a1_funding.config.sizing import (
    SIZING_CONFIG_SCHEMA_VERSION,
    InstrumentSizingRule,
    SizingConfig,
    SizingConfigError,
    conservative_default_v0,
)


def _rule(**overrides) -> InstrumentSizingRule:
    base = dict(
        venue="binance",
        perp_instrument="BTCUSDT",
        spot_instrument="BTCUSDT",
        max_quantity=Decimal("0.01"),
        min_quantity=Decimal("0.001"),
        slippage_tier_name="btc_eth_top_tier",
    )
    base.update(overrides)
    return InstrumentSizingRule(**base)


def _config(**overrides) -> SizingConfig:
    base = dict(
        schema_version=SIZING_CONFIG_SCHEMA_VERSION,
        rules=(_rule(),),
        max_total_notional_usd=Decimal("2000"),
        notes="",
    )
    base.update(overrides)
    return SizingConfig(**base)


# ─── Rule validation ─────────────────────────────────────────────────────


def test_rule_rejects_uppercase_venue():
    with pytest.raises(SizingConfigError, match="venue"):
        _rule(venue="Binance")


def test_rule_rejects_empty_perp_instrument():
    with pytest.raises(SizingConfigError, match="perp_instrument"):
        _rule(perp_instrument="")


def test_rule_rejects_empty_spot_instrument():
    with pytest.raises(SizingConfigError, match="spot_instrument"):
        _rule(spot_instrument="")


def test_rule_rejects_zero_or_negative_max_quantity():
    with pytest.raises(SizingConfigError, match="max_quantity"):
        _rule(max_quantity=Decimal("0"))
    with pytest.raises(SizingConfigError, match="max_quantity"):
        _rule(max_quantity=Decimal("-0.01"))


def test_rule_rejects_negative_min_quantity():
    with pytest.raises(SizingConfigError, match="min_quantity"):
        _rule(min_quantity=Decimal("-0.001"))


def test_rule_rejects_min_quantity_geq_max_quantity():
    with pytest.raises(SizingConfigError, match="strictly less"):
        _rule(min_quantity=Decimal("0.01"), max_quantity=Decimal("0.01"))
    with pytest.raises(SizingConfigError, match="strictly less"):
        _rule(min_quantity=Decimal("0.02"), max_quantity=Decimal("0.01"))


def test_rule_accepts_zero_min_quantity():
    """min_quantity=0 is the default and means 'never suppress on size'."""
    r = _rule(min_quantity=Decimal("0"))
    assert r.min_quantity == Decimal("0")


def test_rule_rejects_float_quantities():
    with pytest.raises(TypeError):
        _rule(max_quantity=0.01)


def test_rule_rejects_empty_tier_name():
    with pytest.raises(SizingConfigError, match="slippage_tier_name"):
        _rule(slippage_tier_name="")


# ─── Config validation ───────────────────────────────────────────────────


def test_config_rejects_wrong_schema_version():
    with pytest.raises(SizingConfigError, match="schema_version"):
        _config(schema_version="sizing_config.vX")


def test_config_rejects_empty_rules():
    with pytest.raises(SizingConfigError, match="InstrumentSizingRule"):
        _config(rules=())


def test_config_rejects_zero_or_negative_total_notional():
    with pytest.raises(SizingConfigError, match="max_total_notional_usd"):
        _config(max_total_notional_usd=Decimal("0"))
    with pytest.raises(SizingConfigError, match="max_total_notional_usd"):
        _config(max_total_notional_usd=Decimal("-1"))


def test_config_rejects_duplicate_perp_instruments():
    rule_a = _rule(perp_instrument="BTCUSDT", spot_instrument="BTC-A")
    rule_b = _rule(perp_instrument="BTCUSDT", spot_instrument="BTC-B")
    with pytest.raises(SizingConfigError, match="duplicate perp_instrument"):
        _config(rules=(rule_a, rule_b))


def test_config_rejects_duplicate_spot_instruments():
    rule_a = _rule(perp_instrument="BTCUSDT", spot_instrument="X")
    rule_b = _rule(perp_instrument="ETHUSDT", spot_instrument="X")
    with pytest.raises(SizingConfigError, match="duplicate spot_instrument"):
        _config(rules=(rule_a, rule_b))


def test_config_rule_for_perp_finds_match():
    rule = _rule(perp_instrument="BTCUSDT")
    cfg = _config(rules=(rule,))
    assert cfg.rule_for_perp("BTCUSDT") is rule


def test_config_rule_for_perp_raises_when_missing():
    cfg = _config()
    with pytest.raises(SizingConfigError, match="ETHUSDT"):
        cfg.rule_for_perp("ETHUSDT")


# ─── Content hash ────────────────────────────────────────────────────────


def test_hash_deterministic():
    a = _config()
    b = _config()
    assert a.content_hash == b.content_hash


def test_hash_changes_on_max_quantity_change():
    a = _config(rules=(_rule(max_quantity=Decimal("0.01")),))
    b = _config(rules=(_rule(max_quantity=Decimal("0.02")),))
    assert a.content_hash != b.content_hash


def test_hash_changes_on_total_notional_change():
    a = _config(max_total_notional_usd=Decimal("2000"))
    b = _config(max_total_notional_usd=Decimal("3000"))
    assert a.content_hash != b.content_hash


def test_hash_insensitive_to_rule_ordering():
    rule_a = _rule(perp_instrument="BTCUSDT", spot_instrument="BTCUSDT")
    rule_b = _rule(perp_instrument="ETHUSDT", spot_instrument="ETHUSDT",
                   max_quantity=Decimal("0.1"), min_quantity=Decimal("0.01"))
    a = _config(rules=(rule_a, rule_b))
    b = _config(rules=(rule_b, rule_a))
    assert a.content_hash == b.content_hash


def test_hash_changes_on_notes_change():
    a = _config(notes="v0")
    b = _config(notes="v0 (annotated)")
    assert a.content_hash != b.content_hash


def test_hash_is_hex_sha256():
    h = _config().content_hash
    assert len(h) == 64
    int(h, 16)


# ─── Default ──────────────────────────────────────────────────────────────


def test_default_boots_cleanly():
    cfg = conservative_default_v0()
    assert cfg.schema_version == SIZING_CONFIG_SCHEMA_VERSION
    assert len(cfg.rules) >= 2  # BTC + ETH
    assert cfg.max_total_notional_usd > Decimal("0")


def test_default_includes_btc_and_eth():
    cfg = conservative_default_v0()
    perps = sorted(r.perp_instrument for r in cfg.rules)
    assert "BTCUSDT" in perps
    assert "ETHUSDT" in perps


def test_default_hash_stable():
    a = conservative_default_v0()
    b = conservative_default_v0()
    assert a.content_hash == b.content_hash


def test_default_caps_are_tiny():
    """P0 caps should be small enough that early canary won't move
    markets. Sanity-check the seed isn't accidentally large."""
    cfg = conservative_default_v0()
    btc_rule = cfg.rule_for_perp("BTCUSDT")
    eth_rule = cfg.rule_for_perp("ETHUSDT")
    # BTC at $100k: 0.01 BTC = $1k. ETH at $4k: 0.1 ETH = $400. Both small.
    assert btc_rule.max_quantity <= Decimal("0.1")
    assert eth_rule.max_quantity <= Decimal("1")
    assert cfg.max_total_notional_usd <= Decimal("10000")
