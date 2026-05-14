"""Integration tests for A2 paper-research harness.

Day 25 deliverable. Verifies:
  - run_harness() returns the JSON-shaped dict per 25.3
  - Nested perp/spot blocks present and structurally correct
  - Round-trip decomposition present and matches A2RoundTripCost output
  - Constant fixture: zero fires, no paper.fills written
  - Spike fixture: one fire, two paper.fills rows, firewall properties hold
  - trading.fills unchanged across all invocations
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from strategies.a2_basis.runner.paper_research_harness import (
    HarnessConfig,
    run_harness,
)
from strategies.a2_basis.signal.cost_threshold import (
    compute_a2_round_trip_threshold_bps,
)
from strategies.a2_basis.config.profile_selector import (
    select_research_profile_for_a2,
)
from tests.integration.test_migrations import (  # noqa: F401
    _alembic,
    _connect,
    fresh_db,
)


FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "a2_basis"


# ═══════════════════════════════════════════════════════════════════════
# Constant fixture: zero fires
# ═══════════════════════════════════════════════════════════════════════


def test_harness_constant_fixture_zero_fires(fresh_db):
    _alembic("upgrade", "0011")

    config = HarnessConfig(
        fixture_path=FIXTURE_DIR / "SOLUSDT_BASIS_60obs_constant.json",
        symbol="SOLUSDT",
        venue="binance",
        quantity_per_intent=Decimal("10.0"),
        suffix=uuid.uuid4().hex[:8],
    )
    result = run_harness(config)

    # Fire counts
    assert result["a2_intents_fired"] == 0
    assert result["paper_fills_before"] == 0
    assert result["paper_fills_after"] == 0

    # Firewall: trading.fills unchanged
    assert result["trading_fills_before"] == result["trading_fills_after"]

    # Source mode declared
    assert result["source_mode"] == "PAPER_RESEARCH"

    # Skip taxonomy matches the constant-fixture expectation
    assert result["evaluations_total"] == 60
    assert result["evaluations_skipped_insufficient_lookback"] == 29
    assert result["evaluations_skipped_zero_or_near_zero_stdev"] == 31
    assert result["evaluations_skipped_z_below_threshold"] == 0
    assert result["evaluations_skipped_cost_not_cleared"] == 0


# ═══════════════════════════════════════════════════════════════════════
# Spike fixture: one fire, structural assertions
# ═══════════════════════════════════════════════════════════════════════


def test_harness_spike_fixture_one_fire_with_two_legs(fresh_db):
    _alembic("upgrade", "0011")

    config = HarnessConfig(
        fixture_path=FIXTURE_DIR / "SOLUSDT_BASIS_60obs_one_spike.json",
        symbol="SOLUSDT",
        venue="binance",
        quantity_per_intent=Decimal("10.0"),
        suffix=uuid.uuid4().hex[:8],
    )
    result = run_harness(config)

    # Fire counts: 1 logical intent → 2 paper.fills rows
    assert result["a2_intents_fired"] == 1
    assert result["paper_fills_before"] == 0
    assert result["paper_fills_after"] == 2

    # Firewall: trading.fills unchanged
    assert result["trading_fills_before"] == result["trading_fills_after"]
    assert result["source_mode"] == "PAPER_RESEARCH"


# ═══════════════════════════════════════════════════════════════════════
# JSON output shape (25.3)
# ═══════════════════════════════════════════════════════════════════════


def test_harness_output_has_required_top_level_keys(fresh_db):
    _alembic("upgrade", "0011")

    config = HarnessConfig(
        fixture_path=FIXTURE_DIR / "SOLUSDT_BASIS_60obs_constant.json",
        symbol="SOLUSDT",
        venue="binance",
        quantity_per_intent=Decimal("10.0"),
        suffix=uuid.uuid4().hex[:8],
    )
    result = run_harness(config)

    required_top_level = {
        "fixture", "symbol", "venue", "source_mode",
        "quantity_per_intent",
        "evaluations_total",
        "evaluations_skipped_insufficient_lookback",
        "evaluations_skipped_stale_window",
        "evaluations_skipped_zero_or_near_zero_stdev",
        "evaluations_skipped_z_below_threshold",
        "evaluations_skipped_cost_not_cleared",
        "a2_intents_fired",
        "paper_fills_before", "paper_fills_after",
        "trading_fills_before", "trading_fills_after",
        "perp", "spot", "round_trip",
    }
    assert required_top_level.issubset(result.keys())


def test_harness_perp_block_has_required_keys(fresh_db):
    _alembic("upgrade", "0011")
    config = HarnessConfig(
        fixture_path=FIXTURE_DIR / "SOLUSDT_BASIS_60obs_constant.json",
        symbol="SOLUSDT",
        venue="binance",
        quantity_per_intent=Decimal("10.0"),
        suffix=uuid.uuid4().hex[:8],
    )
    result = run_harness(config)

    perp_required = {
        "cost_profile_name",
        "slippage_tier_name",
        "modeled_slippage_bps",
        "median_observed_slippage_bps",
        "p90_observed_slippage_bps",
        "observed_slippage_non_null",
        "observed_slippage_null",
    }
    assert perp_required.issubset(result["perp"].keys())
    # Day 22 SOL: perp profile is binance_vip5_alt_v1, tier is liquid_alt_tier
    assert result["perp"]["cost_profile_name"] == "binance_vip5_alt_v1"
    assert result["perp"]["slippage_tier_name"] == "liquid_alt_tier"


def test_harness_spot_block_has_required_keys(fresh_db):
    _alembic("upgrade", "0011")
    config = HarnessConfig(
        fixture_path=FIXTURE_DIR / "SOLUSDT_BASIS_60obs_constant.json",
        symbol="SOLUSDT",
        venue="binance",
        quantity_per_intent=Decimal("10.0"),
        suffix=uuid.uuid4().hex[:8],
    )
    result = run_harness(config)

    spot_required = {
        "cost_profile_name",
        "slippage_tier_name",
        "modeled_slippage_bps",
        "median_observed_slippage_bps",
        "p90_observed_slippage_bps",
        "observed_slippage_non_null",
        "observed_slippage_null",
    }
    assert spot_required.issubset(result["spot"].keys())
    # Day 22 spot profile is binance_vip5_spot_placeholder_v0
    assert (
        result["spot"]["cost_profile_name"]
        == "binance_vip5_spot_placeholder_v0"
    )
    assert result["spot"]["slippage_tier_name"] == "spot_liquid_alt_tier"


# ═══════════════════════════════════════════════════════════════════════
# Round-trip decomposition (reviewer correction: assert against helper)
# ═══════════════════════════════════════════════════════════════════════


def test_harness_round_trip_matches_helper(fresh_db):
    """Per reviewer correction: do not hardcode round-trip numbers.
    The harness's round_trip block must match what
    compute_a2_round_trip_threshold_bps produces."""
    _alembic("upgrade", "0011")

    config = HarnessConfig(
        fixture_path=FIXTURE_DIR / "SOLUSDT_BASIS_60obs_constant.json",
        symbol="SOLUSDT",
        venue="binance",
        quantity_per_intent=Decimal("10.0"),
        suffix=uuid.uuid4().hex[:8],
    )
    result = run_harness(config)

    # Recompute via the helper using the same inputs the harness uses.
    bundle = select_research_profile_for_a2("SOLUSDT", "binance")
    expected = compute_a2_round_trip_threshold_bps(
        bundle,
        perp_slippage_tier_name="liquid_alt_tier",
        spot_slippage_tier_name="spot_liquid_alt_tier",
        uncertainty_margin_fraction=Decimal("0.2"),
    )

    rt = result["round_trip"]
    assert Decimal(rt["perp_entry_bps"]) == expected.perp_entry_bps
    assert Decimal(rt["perp_exit_bps"]) == expected.perp_exit_bps
    assert Decimal(rt["spot_entry_bps"]) == expected.spot_entry_bps
    assert Decimal(rt["spot_exit_bps"]) == expected.spot_exit_bps
    assert Decimal(rt["subtotal_bps"]) == expected.subtotal_bps
    assert Decimal(rt["uncertainty_margin_bps"]) == expected.uncertainty_margin_bps
    assert Decimal(rt["total_threshold_bps"]) == expected.total_threshold_bps


# ═══════════════════════════════════════════════════════════════════════
# JSON-serialization smoke test
# ═══════════════════════════════════════════════════════════════════════


def test_harness_output_is_json_serializable(fresh_db):
    """run_harness's return value must be json.dumps()-able for CLI use."""
    import json

    _alembic("upgrade", "0011")
    config = HarnessConfig(
        fixture_path=FIXTURE_DIR / "SOLUSDT_BASIS_60obs_one_spike.json",
        symbol="SOLUSDT",
        venue="binance",
        quantity_per_intent=Decimal("10.0"),
        suffix=uuid.uuid4().hex[:8],
    )
    result = run_harness(config)
    serialized = json.dumps(result)
    assert len(serialized) > 100  # sanity: non-trivial output


# ═══════════════════════════════════════════════════════════════════════
# Invalid input handling
# ═══════════════════════════════════════════════════════════════════════


def test_harness_missing_fixture_raises():
    config = HarnessConfig(
        fixture_path=Path("/nonexistent/path/to/fixture.json"),
        symbol="SOLUSDT",
        venue="binance",
        quantity_per_intent=Decimal("10.0"),
        suffix=uuid.uuid4().hex[:8],
    )
    with pytest.raises(FileNotFoundError, match="Fixture not found"):
        run_harness(config)


def test_harness_negative_quantity_raises():
    config = HarnessConfig(
        fixture_path=FIXTURE_DIR / "SOLUSDT_BASIS_60obs_constant.json",
        symbol="SOLUSDT",
        venue="binance",
        quantity_per_intent=Decimal("-1.0"),
        suffix=uuid.uuid4().hex[:8],
    )
    with pytest.raises(ValueError, match="quantity_per_intent"):
        run_harness(config)
