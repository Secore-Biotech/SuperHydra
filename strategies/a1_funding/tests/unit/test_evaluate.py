"""Unit tests for strategies.a1_funding.signal.evaluate.

Coverage:
  - Direction logic: positive funding → SHORT_PERP; negative → LONG_PERP
  - FLAT when |forecast| <= per-period costs
  - Cost arithmetic: round-trip fees, slippage, amortised borrow
  - Lineage: cost_model_hash captured; schema versions tagged
  - Validation: missing venue, missing tier, bad funding_intervals
  - Reproducibility: same inputs → byte-equal SignalEvaluation
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from core.config.cost_model import (
    BorrowCost,
    CostModelConfig,
    FeeSchedule,
    FundingUncertainty,
    SlippageTier,
    conservative_default_v0,
)
from strategies.a1_funding.signal.expected_funding import (
    EXPECTED_FUNDING_SCHEMA_VERSION,
    ExpectedFunding,
)
from strategies.a1_funding.signal.evaluate import (
    SIGNAL_EVALUATION_SCHEMA_VERSION,
    SignalDecision,
    SignalEvaluationError,
    evaluate_signal,
)


UTC = timezone.utc


def _forecast(
    rate: str,
    venue: str = "binance",
    instrument: str = "BTCUSDT",
) -> ExpectedFunding:
    return ExpectedFunding(
        venue=venue,
        instrument=instrument,
        as_of=datetime(2026, 1, 5, tzinfo=UTC),
        window_start=datetime(2026, 1, 1, tzinfo=UTC),
        window_end=datetime(2026, 1, 4, tzinfo=UTC),
        window_size=10,
        mean_rate=Decimal(rate),
        stdev_rate=Decimal("0.00001"),
        discount_k=Decimal("1"),
        forecast_rate=Decimal(rate),
    )


def _cheap_cost_model() -> CostModelConfig:
    """A cost model with very low costs so even small forecasts produce
    non-FLAT decisions. Used by direction tests."""
    return CostModelConfig(
        schema_version="cost_model.v0",
        fee_schedules=(
            FeeSchedule(
                venue="binance",
                maker_bps=Decimal("0"),
                taker_bps=Decimal("0.00001"),  # 0.1 bp
            ),
        ),
        slippage_tiers=(
            SlippageTier(tier_name="top", slippage_bps=Decimal("0.00001")),
        ),
        funding_uncertainty=FundingUncertainty(
            lookback_days=30, discount_k=Decimal("1.0")
        ),
        borrow_cost=BorrowCost(daily_bps=Decimal("0.00001")),
        notes="cheap-test",
    )


def _expensive_cost_model() -> CostModelConfig:
    """A cost model with high costs so realistic-sized forecasts produce
    FLAT decisions. Used by FLAT tests."""
    return CostModelConfig(
        schema_version="cost_model.v0",
        fee_schedules=(
            FeeSchedule(
                venue="binance",
                maker_bps=Decimal("0.001"),
                taker_bps=Decimal("0.005"),  # 50 bps — extremely expensive
            ),
        ),
        slippage_tiers=(
            SlippageTier(tier_name="top", slippage_bps=Decimal("0.001")),
        ),
        funding_uncertainty=FundingUncertainty(
            lookback_days=30, discount_k=Decimal("1.0")
        ),
        borrow_cost=BorrowCost(daily_bps=Decimal("0.005")),
        notes="expensive-test",
    )


# ─── Direction logic ──────────────────────────────────────────────────────


def test_positive_forecast_yields_short_perp_long_spot():
    forecast = _forecast("0.001")  # 10 bps positive — clearly above costs
    cost_model = _cheap_cost_model()
    result = evaluate_signal(forecast, cost_model, slippage_tier_name="top")
    assert result.decision == SignalDecision.SHORT_PERP_LONG_SPOT
    assert result.net_edge_rate > Decimal("0")


def test_negative_forecast_yields_long_perp_short_spot():
    forecast = _forecast("-0.001")  # 10 bps negative
    cost_model = _cheap_cost_model()
    result = evaluate_signal(forecast, cost_model, slippage_tier_name="top")
    assert result.decision == SignalDecision.LONG_PERP_SHORT_SPOT
    assert result.net_edge_rate > Decimal("0")


def test_zero_forecast_yields_flat():
    forecast = _forecast("0")
    cost_model = _cheap_cost_model()
    result = evaluate_signal(forecast, cost_model, slippage_tier_name="top")
    assert result.decision == SignalDecision.FLAT


def test_subcost_forecast_yields_flat():
    """|forecast| < per-period costs → FLAT regardless of sign."""
    forecast = _forecast("0.0001")  # 1 bp — way below 50bp+ expensive costs
    cost_model = _expensive_cost_model()
    result = evaluate_signal(forecast, cost_model, slippage_tier_name="top")
    assert result.decision == SignalDecision.FLAT
    assert result.net_edge_rate < Decimal("0")


def test_forecast_exactly_equal_to_costs_is_flat():
    """Edge case: |forecast| == per_period_cost → FLAT (not enough margin)."""
    cost_model = _cheap_cost_model()
    # First evaluate at a small forecast to read the per-period cost.
    probe = evaluate_signal(
        _forecast("0.0001"), cost_model, slippage_tier_name="top"
    )
    cost = probe.per_period_cost_rate

    # Now construct a forecast exactly at the cost threshold.
    boundary = ExpectedFunding(
        venue="binance",
        instrument="BTCUSDT",
        as_of=datetime(2026, 1, 5, tzinfo=UTC),
        window_start=datetime(2026, 1, 1, tzinfo=UTC),
        window_end=datetime(2026, 1, 4, tzinfo=UTC),
        window_size=10,
        mean_rate=cost,
        stdev_rate=Decimal("0"),
        discount_k=Decimal("0"),
        forecast_rate=cost,
    )
    result = evaluate_signal(boundary, cost_model, slippage_tier_name="top")
    assert result.decision == SignalDecision.FLAT


# ─── Cost arithmetic ─────────────────────────────────────────────────────


def test_per_period_cost_includes_round_trip_fees():
    """Per-period cost = 2 * taker + 2 * slippage + borrow/intervals_per_day."""
    cost_model = CostModelConfig(
        schema_version="cost_model.v0",
        fee_schedules=(
            FeeSchedule(
                venue="binance",
                maker_bps=Decimal("0"),
                taker_bps=Decimal("0.0005"),  # 5 bps
            ),
        ),
        slippage_tiers=(
            SlippageTier(tier_name="top", slippage_bps=Decimal("0.0001")),  # 1 bp
        ),
        funding_uncertainty=FundingUncertainty(
            lookback_days=30, discount_k=Decimal("1.0")
        ),
        borrow_cost=BorrowCost(daily_bps=Decimal("0.0003")),  # 3 bps/day
        notes="",
    )

    forecast = _forecast("0.001")
    result = evaluate_signal(
        forecast, cost_model,
        slippage_tier_name="top",
        funding_intervals_per_day=3,
    )

    expected_fees = Decimal("2") * Decimal("0.0005")  # 10 bps round-trip
    expected_slip = Decimal("2") * Decimal("0.0001")  # 2 bps round-trip
    expected_borrow_per_period = Decimal("0.0003") / Decimal("3")  # 1 bp/period
    expected_total = expected_fees + expected_slip + expected_borrow_per_period

    assert result.per_period_cost_rate == expected_total


def test_borrow_amortised_correctly_across_intervals_per_day():
    """Doubling intervals_per_day halves the per-period borrow charge."""
    cost_model = CostModelConfig(
        schema_version="cost_model.v0",
        fee_schedules=(FeeSchedule(
            venue="binance", maker_bps=Decimal("0"), taker_bps=Decimal("0"),
        ),),
        slippage_tiers=(SlippageTier(
            tier_name="top", slippage_bps=Decimal("0"),
        ),),
        funding_uncertainty=FundingUncertainty(
            lookback_days=30, discount_k=Decimal("1.0")
        ),
        borrow_cost=BorrowCost(daily_bps=Decimal("0.0006")),
        notes="",
    )

    forecast = _forecast("0.001")
    a = evaluate_signal(forecast, cost_model, slippage_tier_name="top",
                        funding_intervals_per_day=3)
    b = evaluate_signal(forecast, cost_model, slippage_tier_name="top",
                        funding_intervals_per_day=6)
    # All other components are zero → cost is just amortised borrow.
    assert a.per_period_cost_rate == Decimal("0.0006") / Decimal("3")
    assert b.per_period_cost_rate == Decimal("0.0006") / Decimal("6")
    assert a.per_period_cost_rate == Decimal("2") * b.per_period_cost_rate


# ─── Configuration validation ────────────────────────────────────────────


def test_missing_venue_in_cost_model_raises():
    forecast = _forecast("0.001", venue="binance")
    # Cost model only has 'okx' fee schedule — venue mismatch.
    cost_model = CostModelConfig(
        schema_version="cost_model.v0",
        fee_schedules=(FeeSchedule(
            venue="okx",
            maker_bps=Decimal("0"),
            taker_bps=Decimal("0.0005"),
        ),),
        slippage_tiers=(SlippageTier(
            tier_name="top", slippage_bps=Decimal("0.0001"),
        ),),
        funding_uncertainty=FundingUncertainty(
            lookback_days=30, discount_k=Decimal("1.0")
        ),
        borrow_cost=BorrowCost(daily_bps=Decimal("0.0001")),
        notes="",
    )
    with pytest.raises(SignalEvaluationError, match="binance"):
        evaluate_signal(forecast, cost_model, slippage_tier_name="top")


def test_missing_tier_in_cost_model_raises():
    forecast = _forecast("0.001")
    cost_model = _cheap_cost_model()
    with pytest.raises(SignalEvaluationError, match="not_a_tier"):
        evaluate_signal(forecast, cost_model, slippage_tier_name="not_a_tier")


def test_bad_funding_intervals_per_day_raises():
    forecast = _forecast("0.001")
    cost_model = _cheap_cost_model()
    with pytest.raises(SignalEvaluationError, match="funding_intervals_per_day"):
        evaluate_signal(
            forecast, cost_model,
            slippage_tier_name="top",
            funding_intervals_per_day=0,
        )


# ─── Lineage ──────────────────────────────────────────────────────────────


def test_output_records_cost_model_hash():
    forecast = _forecast("0.001")
    cost_model = _cheap_cost_model()
    result = evaluate_signal(forecast, cost_model, slippage_tier_name="top")
    assert result.cost_model_hash == cost_model.content_hash
    assert len(result.cost_model_hash) == 64  # sha256 hex


def test_output_records_schema_versions():
    forecast = _forecast("0.001")
    cost_model = _cheap_cost_model()
    result = evaluate_signal(forecast, cost_model, slippage_tier_name="top")
    assert result.schema_version == SIGNAL_EVALUATION_SCHEMA_VERSION
    assert result.expected_funding_schema_version == EXPECTED_FUNDING_SCHEMA_VERSION


def test_different_cost_models_yield_different_hashes_in_output():
    forecast = _forecast("0.001")
    a = evaluate_signal(forecast, _cheap_cost_model(), slippage_tier_name="top")
    b = evaluate_signal(forecast, _expensive_cost_model(), slippage_tier_name="top")
    assert a.cost_model_hash != b.cost_model_hash


# ─── Reproducibility ─────────────────────────────────────────────────────


def test_reproducibility_byte_equal_across_calls():
    """Same forecast + same cost model → byte-equal SignalEvaluation."""
    f1 = _forecast("0.0008")
    f2 = _forecast("0.0008")
    cm = conservative_default_v0()

    a = evaluate_signal(f1, cm, slippage_tier_name="btc_eth_top_tier")
    b = evaluate_signal(f2, cm, slippage_tier_name="btc_eth_top_tier")

    assert a == b
    assert a.forecast_rate == b.forecast_rate
    assert a.per_period_cost_rate == b.per_period_cost_rate
    assert a.net_edge_rate == b.net_edge_rate
    assert a.decision == b.decision
    assert a.cost_model_hash == b.cost_model_hash


def test_reproducibility_with_default_cost_model():
    """Boots against the project's seeded default — exercises the
    full end-to-end path including conservative_default_v0()."""
    forecast = _forecast("0.001")
    cm1 = conservative_default_v0()
    cm2 = conservative_default_v0()
    a = evaluate_signal(forecast, cm1, slippage_tier_name="btc_eth_top_tier")
    b = evaluate_signal(forecast, cm2, slippage_tier_name="btc_eth_top_tier")
    assert a == b


# ─── Output forwards forecast metadata ───────────────────────────────────


def test_output_copies_forecast_identity():
    forecast = _forecast("0.001", venue="binance", instrument="ETHUSDT")
    cost_model = _cheap_cost_model()
    result = evaluate_signal(forecast, cost_model, slippage_tier_name="top")
    assert result.venue == "binance"
    assert result.instrument == "ETHUSDT"
    assert result.as_of == forecast.as_of
    assert result.forecast_rate == forecast.forecast_rate
