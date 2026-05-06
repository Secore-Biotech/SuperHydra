"""Net-edge signal evaluator.

Takes an `ExpectedFunding` forecast plus a `CostModelConfig` and produces
a `SignalEvaluation`: the decision shape the Day 6-7 sizer consumes.

This is where the strategy's economic logic lives. The forecast says
"funding is expected to be X for the next interval." The evaluator says:
"after fees + slippage + borrow over one interval, the net carry is Y;
the position direction we'd want is Z."

Properties:
  - Pure. No I/O, no clock dependency. Same inputs → same SignalEvaluation.
  - Hashable lineage. The output records the cost-model content hash and
    the forecast schema version so reconciliation can prove "this evaluation
    was produced under this exact cost model."
  - Conservative. The forecast is already discounted by uncertainty. Costs
    are computed against worst-case assumptions (taker on entry + exit,
    full borrow accrual). The strategy only signals a position when the
    sign of expected funding is consistent and the magnitude clears costs.

What this module DOES NOT do:
  - Sizing (Day 6-7).
  - Position-state awareness (lives in the sizer + runner layers).
  - Multi-venue routing (single-venue first per roadmap §3.1.1).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Final

from core.config.cost_model import CostModelConfig
from strategies.a1_funding.signal.expected_funding import (
    EXPECTED_FUNDING_SCHEMA_VERSION,
    ExpectedFunding,
)


SIGNAL_EVALUATION_SCHEMA_VERSION: Final[str] = "signal_evaluation.v0"


# ─── Decision enum ────────────────────────────────────────────────────────


class SignalDecision(str, Enum):
    """The sizer's input directive.

    LONG_PERP_SHORT_SPOT: collect funding paid by longs to shorts.
        Used when expected funding is negative (longs pay shorts on perp).

    SHORT_PERP_LONG_SPOT: collect funding paid by shorts to longs.
        Used when expected funding is positive (shorts pay longs on perp).

    FLAT: no position; net edge is non-positive after costs, OR the
        forecast confidence is too low for an intent to be safe.

    Note on Binance perp convention:
      - Positive funding rate → longs pay shorts → we want to be SHORT
        the perp and hedge with LONG spot. So `SHORT_PERP_LONG_SPOT`.
      - Negative funding rate → shorts pay longs → we want to be LONG
        the perp and hedge with SHORT spot. So `LONG_PERP_SHORT_SPOT`.
    """

    LONG_PERP_SHORT_SPOT = "long_perp_short_spot"
    SHORT_PERP_LONG_SPOT = "short_perp_long_spot"
    FLAT = "flat"


# ─── Errors ───────────────────────────────────────────────────────────────


class SignalEvaluationError(Exception):
    pass


# ─── Output type ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SignalEvaluation:
    """Full record of why the signal said what it said.

    Carries every input that fed the decision, plus the decision itself.
    The Day 6-7 sizer reads `decision` to choose direction; this object
    is also written to lineage so reconciliation can audit decisions
    after the fact.

    Fields:
        venue, instrument, as_of: copied from ExpectedFunding for
            convenience (sizer doesn't have to thread the forecast object
            forward).
        forecast_rate: the discounted-mean forecast.
        per_period_cost_rate: round-trip cost expressed as a fraction
            of notional, normalised to one funding interval. Compared
            directly to forecast_rate.
        net_edge_rate: forecast_rate (signed) minus per_period_cost_rate
            (always positive). Positive net_edge means the strategy
            captures carry above costs.
        decision: SignalDecision direction.
        cost_model_hash: lineage. Two evaluations with the same hash
            used the same cost model.
        expected_funding_schema_version: lineage tag.
        schema_version: this evaluation's schema tag.
    """

    venue: str
    instrument: str
    as_of: object  # datetime; loose typing avoids redundant import
    forecast_rate: Decimal
    per_period_cost_rate: Decimal
    net_edge_rate: Decimal
    decision: SignalDecision
    cost_model_hash: str
    expected_funding_schema_version: str = EXPECTED_FUNDING_SCHEMA_VERSION
    schema_version: str = SIGNAL_EVALUATION_SCHEMA_VERSION


# ─── The evaluator ────────────────────────────────────────────────────────


def evaluate_signal(
    forecast: ExpectedFunding,
    cost_model: CostModelConfig,
    *,
    slippage_tier_name: str,
    funding_intervals_per_day: int = 3,
) -> SignalEvaluation:
    """Decide direction (or flat) for one instrument.

    Args:
        forecast: ExpectedFunding produced by expected_next_funding().
        cost_model: CostModelConfig governing fees / slippage / borrow.
        slippage_tier_name: which SlippageTier in the cost model applies
            to this instrument. Caller picks based on instrument liquidity.
        funding_intervals_per_day: how many funding settlements per day.
            Binance perps default to 3 (every 8 hours). Used to amortise
            the borrow rate (which is bps/day) into per-interval cost.

    Returns:
        SignalEvaluation with decision and full lineage.

    Raises:
        SignalEvaluationError on configuration mismatches.
    """
    if funding_intervals_per_day < 1:
        raise SignalEvaluationError(
            f"funding_intervals_per_day must be >= 1, got {funding_intervals_per_day}"
        )

    # Resolve fees by venue.
    fee_schedule = next(
        (fs for fs in cost_model.fee_schedules if fs.venue == forecast.venue),
        None,
    )
    if fee_schedule is None:
        venues = sorted({fs.venue for fs in cost_model.fee_schedules})
        raise SignalEvaluationError(
            f"cost model has no FeeSchedule for venue {forecast.venue!r}; "
            f"known venues: {venues}"
        )

    # Resolve slippage by tier name.
    slippage_tier = next(
        (t for t in cost_model.slippage_tiers if t.tier_name == slippage_tier_name),
        None,
    )
    if slippage_tier is None:
        tiers = sorted(t.tier_name for t in cost_model.slippage_tiers)
        raise SignalEvaluationError(
            f"cost model has no SlippageTier {slippage_tier_name!r}; "
            f"known tiers: {tiers}"
        )

    # Conservative cost components, expressed as fraction of notional, per
    # one funding interval:
    #
    #   - Fees: round-trip = entry + exit. Worst-case = taker on both sides.
    #     A maker fill on one or both sides reduces this; we don't assume it.
    #
    #   - Slippage: round-trip = entry + exit slippage at the configured tier.
    #
    #   - Borrow: bps/day on the spot leg, divided by funding_intervals_per_day
    #     to amortise into one funding interval.
    #
    # We sum into a single per-period cost rate that's directly comparable
    # to the forecast funding rate.
    fees = Decimal("2") * fee_schedule.taker_bps
    slip = Decimal("2") * slippage_tier.slippage_bps
    borrow_per_period = (
        cost_model.borrow_cost.daily_bps / Decimal(funding_intervals_per_day)
    )
    per_period_cost_rate = fees + slip + borrow_per_period

    # Decision rule:
    #   - If |forecast| <= per_period_cost: FLAT (insufficient edge)
    #   - Else direction follows the sign of the forecast.
    abs_forecast = abs(forecast.forecast_rate)
    if abs_forecast <= per_period_cost_rate:
        decision = SignalDecision.FLAT
        net_edge_rate = abs_forecast - per_period_cost_rate  # negative or zero
    else:
        net_edge_rate = abs_forecast - per_period_cost_rate
        if forecast.forecast_rate > Decimal("0"):
            # Positive funding → shorts collect → SHORT_PERP_LONG_SPOT
            decision = SignalDecision.SHORT_PERP_LONG_SPOT
        else:
            # Negative funding → longs collect → LONG_PERP_SHORT_SPOT
            decision = SignalDecision.LONG_PERP_SHORT_SPOT

    return SignalEvaluation(
        venue=forecast.venue,
        instrument=forecast.instrument,
        as_of=forecast.as_of,
        forecast_rate=forecast.forecast_rate,
        per_period_cost_rate=per_period_cost_rate,
        net_edge_rate=net_edge_rate,
        decision=decision,
        cost_model_hash=cost_model.content_hash,
    )
