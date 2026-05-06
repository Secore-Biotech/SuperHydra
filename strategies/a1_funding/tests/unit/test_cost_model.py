"""Unit tests for core.config.cost_model.

Coverage:
  - Validation: schema version, duplicate venues, duplicate tiers
  - Content hash: deterministic, sensitive to all fields, insensitive to
    fee-schedule list ordering and slippage-tier list ordering
  - conservative_default_v0() boots cleanly and has stable hash
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from core.config.cost_model import (
    COST_MODEL_SCHEMA_VERSION,
    BorrowCost,
    CostModelConfig,
    FeeSchedule,
    FundingUncertainty,
    SlippageTier,
    conservative_default_v0,
)


def _full_config(**overrides) -> CostModelConfig:
    base = dict(
        schema_version=COST_MODEL_SCHEMA_VERSION,
        fee_schedules=(
            FeeSchedule(venue="binance", maker_bps=Decimal("0.0002"),
                        taker_bps=Decimal("0.0005")),
        ),
        slippage_tiers=(
            SlippageTier(tier_name="top", slippage_bps=Decimal("0.0001")),
        ),
        funding_uncertainty=FundingUncertainty(
            lookback_days=30, discount_k=Decimal("1.0")
        ),
        borrow_cost=BorrowCost(daily_bps=Decimal("0.0001")),
        notes="",
    )
    base.update(overrides)
    return CostModelConfig(**base)


# ─── Component validation ────────────────────────────────────────────────


def test_fee_schedule_rejects_uppercase_venue():
    with pytest.raises(ValueError, match="venue"):
        FeeSchedule(venue="Binance", maker_bps=Decimal("0"), taker_bps=Decimal("0"))


def test_fee_schedule_rejects_float_rates():
    with pytest.raises(TypeError):
        FeeSchedule(venue="binance", maker_bps=0.0002, taker_bps=Decimal("0"))


def test_funding_uncertainty_rejects_zero_lookback():
    with pytest.raises(ValueError, match="lookback_days"):
        FundingUncertainty(lookback_days=0, discount_k=Decimal("1"))


def test_funding_uncertainty_rejects_negative_lookback():
    with pytest.raises(ValueError, match="lookback_days"):
        FundingUncertainty(lookback_days=-1, discount_k=Decimal("1"))


def test_funding_uncertainty_rejects_float_discount_k():
    with pytest.raises(TypeError):
        FundingUncertainty(lookback_days=30, discount_k=1.0)


# ─── Config validation ───────────────────────────────────────────────────


def test_config_rejects_wrong_schema_version():
    with pytest.raises(ValueError, match="schema_version"):
        _full_config(schema_version="cost_model.vX")


def test_config_rejects_empty_fee_schedules():
    with pytest.raises(ValueError, match="FeeSchedule"):
        _full_config(fee_schedules=())


def test_config_rejects_empty_slippage_tiers():
    with pytest.raises(ValueError, match="SlippageTier"):
        _full_config(slippage_tiers=())


def test_config_rejects_duplicate_venues():
    with pytest.raises(ValueError, match="duplicate venues"):
        _full_config(fee_schedules=(
            FeeSchedule(venue="binance", maker_bps=Decimal("0.0002"),
                        taker_bps=Decimal("0.0005")),
            FeeSchedule(venue="binance", maker_bps=Decimal("0.0001"),
                        taker_bps=Decimal("0.0004")),
        ))


def test_config_rejects_duplicate_tier_names():
    with pytest.raises(ValueError, match="duplicate tier_names"):
        _full_config(slippage_tiers=(
            SlippageTier(tier_name="top", slippage_bps=Decimal("0.0001")),
            SlippageTier(tier_name="top", slippage_bps=Decimal("0.0002")),
        ))


# ─── Content hash ────────────────────────────────────────────────────────


def test_hash_deterministic():
    a = _full_config()
    b = _full_config()
    assert a.content_hash == b.content_hash


def test_hash_changes_on_maker_bps_change():
    a = _full_config()
    b = _full_config(fee_schedules=(
        FeeSchedule(venue="binance", maker_bps=Decimal("0.0003"),
                    taker_bps=Decimal("0.0005")),
    ))
    assert a.content_hash != b.content_hash


def test_hash_changes_on_borrow_cost_change():
    a = _full_config()
    b = _full_config(borrow_cost=BorrowCost(daily_bps=Decimal("0.0002")))
    assert a.content_hash != b.content_hash


def test_hash_changes_on_funding_uncertainty_change():
    a = _full_config()
    b = _full_config(funding_uncertainty=FundingUncertainty(
        lookback_days=60, discount_k=Decimal("1.0")
    ))
    assert a.content_hash != b.content_hash


def test_hash_changes_on_notes_change():
    """Notes are part of the canonical content. Changing them changes the
    hash. This is intentional: a config with new notes is a new config."""
    a = _full_config(notes="v0 baseline")
    b = _full_config(notes="v0 baseline (annotated)")
    assert a.content_hash != b.content_hash


def test_hash_insensitive_to_fee_schedule_ordering():
    """Two configs with the same fee schedules in different list order
    must produce the same hash. The hash sorts internally."""
    fs_a = FeeSchedule(venue="binance", maker_bps=Decimal("0.0002"),
                      taker_bps=Decimal("0.0005"))
    fs_b = FeeSchedule(venue="okx", maker_bps=Decimal("0.0001"),
                      taker_bps=Decimal("0.0004"))
    a = _full_config(fee_schedules=(fs_a, fs_b))
    b = _full_config(fee_schedules=(fs_b, fs_a))
    assert a.content_hash == b.content_hash


def test_hash_insensitive_to_slippage_tier_ordering():
    t_a = SlippageTier(tier_name="top", slippage_bps=Decimal("0.0001"))
    t_b = SlippageTier(tier_name="mid", slippage_bps=Decimal("0.0003"))
    a = _full_config(slippage_tiers=(t_a, t_b))
    b = _full_config(slippage_tiers=(t_b, t_a))
    assert a.content_hash == b.content_hash


def test_hash_is_hex_sha256():
    h = _full_config().content_hash
    assert len(h) == 64
    int(h, 16)


# ─── conservative_default_v0 ─────────────────────────────────────────────


def test_default_boots_cleanly():
    cfg = conservative_default_v0()
    assert cfg.schema_version == COST_MODEL_SCHEMA_VERSION
    assert len(cfg.fee_schedules) >= 1
    assert len(cfg.slippage_tiers) >= 1


def test_default_hash_stable():
    """The default config must produce a stable hash across two construction
    calls. This is what makes paper Sharpe reproducible across processes."""
    a = conservative_default_v0()
    b = conservative_default_v0()
    assert a.content_hash == b.content_hash


def test_default_includes_binance_venue():
    cfg = conservative_default_v0()
    venues = [fs.venue for fs in cfg.fee_schedules]
    assert "binance" in venues


def test_default_borrow_is_non_zero():
    """Per the roadmap, conservative defaults explicitly avoid free-borrow
    assumptions. The seed value must be > 0."""
    cfg = conservative_default_v0()
    assert cfg.borrow_cost.daily_bps > Decimal("0")
