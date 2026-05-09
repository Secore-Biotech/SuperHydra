"""Cost-threshold structural invariant tests.

These tests document a NARROW invariant:
    Under the placeholder_v0 cost model (alias: conservative_default_v0), the
    per-funding-interval breakeven threshold for A1's signal evaluator
    exceeds Binance BTCUSDT's structural 0.01% per-8h funding cap.

This is NOT a universal A1 invariant. It is a finding about the
specific combination of:
  - the placeholder_v0 cost model (placeholder values
    explicitly documented as "pending empirical calibration"), and
  - Binance BTCUSDT (whose funding rate is structurally capped at
    0.01% per 8-hour funding interval).

The structural consequence: A1 + placeholder_v0 + Binance
BTCUSDT can never produce a non-flat signal under any historical
funding regime, because even a maximally favorable single interval
falls short of breaking even after fees, slippage, and borrow.

If a future change recalibrates the cost model below the BTCUSDT
0.01% cap (e.g. VIP-tier maker rebates lowering round-trip costs),
this test will fail. That is the desired behavior: it forces a
deliberate decision to either
  - rename the test to reflect the new cost regime,
  - split it into multiple tests for different cost profiles, or
  - delete it because the invariant no longer holds.

Do NOT silently lower the assertion threshold to make the test pass
under a new cost model. Doing so would erase the structural finding
this test is here to record.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from core.config.cost_model import placeholder_v0


# Binance BTCUSDT funding rate is structurally capped at 0.01% per 8h
# interval. Documented in Binance's USDM-Futures funding-rate spec.
# This is a venue/instrument fact, independent of any cost model.
BINANCE_BTCUSDT_FUNDING_CAP_PER_INTERVAL = Decimal("0.0001")

# Binance BTCUSDT funding cadence: 3 intervals per day (every 8 hours).
# Also independent of any cost model.
BINANCE_FUNDING_INTERVALS_PER_DAY = 3


def _per_period_cost_rate_from_default() -> Decimal:
    """Replicate the cost-threshold computation from
    strategies.a1_funding.signal.evaluate.evaluate_signal so this test
    asserts on the SAME math the strategy uses, not a parallel hand-rolled
    formula. If evaluate_signal's cost computation changes, this test
    must change with it (and the failure tells the implementer to
    re-evaluate the structural invariant)."""
    cost_model = placeholder_v0()

    # The default config has a single fee schedule and a single slippage
    # tier. If that ever changes, the test should re-pick the same way
    # evaluate_signal does (by venue and tier_name). For now we read
    # them by index because the placeholder config is intentionally
    # minimal.
    fee_schedule = cost_model.fee_schedules[0]
    slippage_tier = cost_model.slippage_tiers[0]

    # Same formula as evaluate_signal:
    #   fees = 2 * taker_bps    (entry + exit)
    #   slip = 2 * slippage_bps (entry + exit)
    #   borrow_per_period = daily_bps / intervals_per_day
    fees = Decimal("2") * fee_schedule.taker_bps
    slip = Decimal("2") * slippage_tier.slippage_bps
    borrow_per_period = (
        cost_model.borrow_cost.daily_bps
        / Decimal(BINANCE_FUNDING_INTERVALS_PER_DAY)
    )
    return fees + slip + borrow_per_period


def test_btcusdt_funding_cap_below_placeholder_cost_threshold():
    """PRIMARY INVARIANT: placeholder_v0's per-period cost
    threshold exceeds Binance BTCUSDT's 0.01% structural funding cap.

    Under the placeholder cost model, A1 cannot produce a non-flat signal
    on Binance BTCUSDT regardless of the actual funding-rate observation,
    because even the structural maximum funding rate (0.01% per interval)
    is below the per-period cost threshold.

    If this test fails, the placeholder cost model has been recalibrated
    below 0.01% per interval. That changes the structural BTCUSDT
    behavior. Rename, split, or delete this test rather than relaxing it
    to make it pass.
    """
    threshold = _per_period_cost_rate_from_default()

    # The threshold should comfortably exceed the BTCUSDT cap. With the
    # placeholder values we expect ~0.001233 vs the cap of 0.0001 — an
    # order of magnitude gap.
    assert threshold > BINANCE_BTCUSDT_FUNDING_CAP_PER_INTERVAL, (
        f"Placeholder cost threshold ({threshold}) is no longer above "
        f"Binance BTCUSDT's structural 0.01% funding cap "
        f"({BINANCE_BTCUSDT_FUNDING_CAP_PER_INTERVAL}). The cost model "
        f"may have been recalibrated. Rename or split this test rather "
        f"than silently changing its meaning."
    )


def test_dec_2024_fixture_max_rate_below_placeholder_cost_threshold():
    """CORROBORATING EVIDENCE: the strongest historical-funding window
    we have data for (Dec 2024) does not even approach the placeholder
    cost threshold.

    This is not a separate invariant from the primary test — it's
    real-data corroboration that the structural inequality matters
    in practice. The Dec 2024 fixture was deliberately probed for
    Day 16b.2 because published analysis flagged it as a high-funding
    window for BTCUSDT. Even there, the maximum single-interval rate
    was 0.0001 (= the cap) and the rolling 12-interval mean topped out
    at ~0.0001.

    If this test fails (real funding exceeded the threshold), either
    the fixture data has been corrupted or Binance has changed its
    BTCUSDT funding-cap convention. Either case warrants investigation
    rather than test relaxation.
    """
    fixture_path = (
        Path(__file__).resolve().parents[4]
        / "tests" / "fixtures" / "binance_funding"
        / "BTCUSDT_14d_20241217T000000_20241231T000000.json"
    )
    if not fixture_path.exists():
        pytest.skip(
            f"Dec 2024 fixture not present at {fixture_path}; corroborating "
            f"test cannot run. The primary invariant test still applies."
        )

    with fixture_path.open() as f:
        payload = json.load(f)

    rates = [Decimal(r["funding_rate"]) for r in payload["records"]]
    assert rates, "fixture has no records"

    max_rate = max(rates)
    threshold = _per_period_cost_rate_from_default()

    assert max_rate < threshold, (
        f"Dec 2024 BTCUSDT fixture's max funding_rate ({max_rate}) is "
        f"no longer below the placeholder cost threshold ({threshold}). "
        f"Either the fixture data has been corrupted, the cost model has "
        f"been recalibrated, or Binance has changed its BTCUSDT funding "
        f"cap. Investigate rather than relaxing this assertion."
    )

    # Also confirm the cap-as-observed: every single rate respects the
    # structural Binance cap. If this fails, the venue has changed how
    # it caps BTCUSDT funding, and the primary test's assumption needs
    # revisiting.
    over_cap = [r for r in rates if r > BINANCE_BTCUSDT_FUNDING_CAP_PER_INTERVAL]
    assert not over_cap, (
        f"Dec 2024 BTCUSDT fixture has {len(over_cap)} rate(s) exceeding "
        f"the documented 0.01% Binance funding cap. This indicates the "
        f"venue has changed its cap, which invalidates the assumption "
        f"underlying the primary invariant test. Investigate."
    )
