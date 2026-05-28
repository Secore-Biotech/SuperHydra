"""Unit tests for SizingConfig and PerpSizingRule.

Content hash must be deterministic and order-independent so an emitted
intent's sizing_config_hash reliably identifies the values in force.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from strategies.vol_event_persistence.config.sizing import (
    SIZING_CONFIG_SCHEMA_VERSION,
    PerpSizingRule,
    SizingConfig,
    SizingConfigError,
)


def _rule(instrument: str = "BTCUSDT", qty: str = "0.01") -> PerpSizingRule:
    return PerpSizingRule(
        venue="binance", instrument=instrument, quantity_per_event=Decimal(qty)
    )


# ===== PerpSizingRule validation =====


def test_rule_valid():
    r = _rule()
    assert r.quantity_per_event == Decimal("0.01")


def test_rule_rejects_non_lowercase_venue():
    with pytest.raises(SizingConfigError, match="lowercase"):
        PerpSizingRule(venue="Binance", instrument="BTCUSDT",
                       quantity_per_event=Decimal("0.01"))


def test_rule_rejects_empty_instrument():
    with pytest.raises(SizingConfigError, match="non-empty"):
        PerpSizingRule(venue="binance", instrument="",
                       quantity_per_event=Decimal("0.01"))


def test_rule_rejects_non_decimal_quantity():
    with pytest.raises(SizingConfigError, match="Decimal"):
        PerpSizingRule(venue="binance", instrument="BTCUSDT",
                       quantity_per_event=0.01)  # float


def test_rule_rejects_zero_quantity():
    with pytest.raises(SizingConfigError, match="positive"):
        PerpSizingRule(venue="binance", instrument="BTCUSDT",
                       quantity_per_event=Decimal("0"))


# ===== SizingConfig structure =====


def test_config_valid():
    cfg = SizingConfig(rules=(_rule("BTCUSDT"), _rule("ETHUSDT", "0.1")))
    assert len(cfg.rules) == 2


def test_config_rejects_empty():
    with pytest.raises(SizingConfigError, match="at least one rule"):
        SizingConfig(rules=())


def test_config_rejects_duplicate_instrument():
    with pytest.raises(SizingConfigError, match="duplicate"):
        SizingConfig(rules=(_rule("BTCUSDT", "0.01"), _rule("BTCUSDT", "0.02")))


# ===== rule_for =====


def test_rule_for_found():
    cfg = SizingConfig(rules=(_rule("BTCUSDT"), _rule("ETHUSDT", "0.1")))
    r = cfg.rule_for("ETHUSDT")
    assert r.instrument == "ETHUSDT"
    assert r.quantity_per_event == Decimal("0.1")


def test_rule_for_missing_raises():
    cfg = SizingConfig(rules=(_rule("BTCUSDT"),))
    with pytest.raises(SizingConfigError, match="no sizing rule"):
        cfg.rule_for("SOLUSDT")


# ===== content_hash =====


def test_content_hash_deterministic():
    cfg1 = SizingConfig(rules=(_rule("BTCUSDT"), _rule("ETHUSDT", "0.1")))
    cfg2 = SizingConfig(rules=(_rule("BTCUSDT"), _rule("ETHUSDT", "0.1")))
    assert cfg1.content_hash() == cfg2.content_hash()


def test_content_hash_order_independent():
    cfg1 = SizingConfig(rules=(_rule("BTCUSDT"), _rule("ETHUSDT", "0.1")))
    cfg2 = SizingConfig(rules=(_rule("ETHUSDT", "0.1"), _rule("BTCUSDT")))
    assert cfg1.content_hash() == cfg2.content_hash()


def test_content_hash_differs_on_quantity():
    cfg1 = SizingConfig(rules=(_rule("BTCUSDT", "0.01"),))
    cfg2 = SizingConfig(rules=(_rule("BTCUSDT", "0.02"),))
    assert cfg1.content_hash() != cfg2.content_hash()


def test_content_hash_differs_on_instrument():
    cfg1 = SizingConfig(rules=(_rule("BTCUSDT", "0.01"),))
    cfg2 = SizingConfig(rules=(_rule("ETHUSDT", "0.01"),))
    assert cfg1.content_hash() != cfg2.content_hash()


def test_content_hash_is_hex_sha256():
    cfg = SizingConfig(rules=(_rule("BTCUSDT"),))
    h = cfg.content_hash()
    assert len(h) == 64
    int(h, 16)  # raises if not valid hex


def test_schema_version_value():
    assert SIZING_CONFIG_SCHEMA_VERSION == "sizing_config.v0"
