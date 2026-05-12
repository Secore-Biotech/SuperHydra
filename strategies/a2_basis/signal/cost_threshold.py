"""A2 round-trip cost-threshold computation.

Day 22 deliverable. Computes the round-trip economic threshold A2's
signal evaluator must clear before firing an intent.

Per Day 22 reviewer-locked decisions:
  - 22.1: perp leg uses existing perp slippage tier; explicit 2x
    multiplier (entry + exit) is applied here
  - 22.4: entry and exit costs are symmetric (same slippage tier
    applied at both ends of the trade)
  - 22.5: uncertainty margin is an EXPLICIT fraction of the round-
    trip subtotal, NOT a hardcoded 1.2x multiplier. Reviewer
    requirement: `uncertainty_margin = X × total_round_trip_cost`
    with X stored/configured explicitly.

Per Day 22 reviewer requirement (structured decomposition):
  - Helper returns A2RoundTripCost dataclass with all four leg costs,
    subtotal, margin, and total separately. Not a scalar. This
    matters enormously during calibration and debugging.

The threshold computation does NOT consume funding rates or borrow
costs in this Day. Funding tailwind/headwind during the hold is
deferred to Day 23 per Day 22 reviewer decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from core.config.cost_model import CostModelConfig
from strategies.a2_basis.config.profile_selector import A2CostBundle


# Convert internal Decimal-fraction representation (e.g. 0.00027 = 2.7
# bps) to a bps-Decimal scale for the structured cost output. Internally
# fees and slippage are stored as fractions of notional (Decimal
# 0.0001 = 1 bp). The A2RoundTripCost reports values in bps for
# readability and to match the rest of the codebase's bps conventions.
_BPS_SCALE: Decimal = Decimal("10000")


@dataclass(frozen=True)
class A2RoundTripCost:
    """Structured decomposition of A2's round-trip cost threshold.

    All fields are bps (basis points). The decomposition shows EXACTLY
    which leg contributes which cost and how the uncertainty margin
    is applied. Calibration and debugging consume this structure
    directly; downstream code that wants a single number reads
    `.total_threshold_bps`.

    Invariant: total_threshold_bps = subtotal_bps + uncertainty_margin_bps
               subtotal_bps = perp_entry_bps + perp_exit_bps
                            + spot_entry_bps + spot_exit_bps

    These are enforced at __post_init__.
    """

    perp_entry_bps: Decimal
    perp_exit_bps: Decimal
    spot_entry_bps: Decimal
    spot_exit_bps: Decimal
    subtotal_bps: Decimal
    uncertainty_margin_bps: Decimal
    total_threshold_bps: Decimal

    def __post_init__(self) -> None:
        for name in ("perp_entry_bps", "perp_exit_bps",
                     "spot_entry_bps", "spot_exit_bps",
                     "subtotal_bps", "uncertainty_margin_bps",
                     "total_threshold_bps"):
            v = getattr(self, name)
            if not isinstance(v, Decimal):
                raise TypeError(f"{name} must be Decimal, got {type(v).__name__}")
            if v < 0:
                raise ValueError(f"{name} must be non-negative, got {v}")
        # Subtotal must equal sum of legs.
        expected_subtotal = (self.perp_entry_bps + self.perp_exit_bps
                             + self.spot_entry_bps + self.spot_exit_bps)
        if self.subtotal_bps != expected_subtotal:
            raise ValueError(
                f"subtotal_bps ({self.subtotal_bps}) must equal sum "
                f"of leg costs ({expected_subtotal})"
            )
        # Total must equal subtotal + margin.
        expected_total = self.subtotal_bps + self.uncertainty_margin_bps
        if self.total_threshold_bps != expected_total:
            raise ValueError(
                f"total_threshold_bps ({self.total_threshold_bps}) must "
                f"equal subtotal_bps + uncertainty_margin_bps ({expected_total})"
            )


def compute_a2_round_trip_threshold_bps(
    bundle: A2CostBundle,
    *,
    perp_slippage_tier_name: str,
    spot_slippage_tier_name: str,
    uncertainty_margin_fraction: Decimal = Decimal("0.2"),
) -> A2RoundTripCost:
    """Compute the A2 round-trip cost threshold as structured A2RoundTripCost.

    Cost components per leg (one direction):
        leg_cost = taker_fee + slippage

    Round-trip cost (entry + exit on both legs):
        subtotal = perp_entry + perp_exit + spot_entry + spot_exit
                 = 2 * (perp_taker + perp_slippage)
                   + 2 * (spot_taker + spot_slippage)

    Per Day 22 reviewer-locked 22.5 amendment:
        uncertainty_margin = uncertainty_margin_fraction × subtotal
        total_threshold    = subtotal + uncertainty_margin

    The function uses TAKER fees on all four legs (conservative; no
    claim of maker fills). Future Days may relax this if execution
    evidence supports it.

    Args:
        bundle: A2CostBundle from select_research_profile_for_a2 (or
            constructed directly for tests).
        perp_slippage_tier_name: name of the slippage tier in the
            perp profile that applies to this trade. E.g.
            "btc_eth_top_tier" for BTC under binance_vip5_btc_v1.
        spot_slippage_tier_name: name of the slippage tier in the
            spot profile. E.g. "spot_btc_eth_top_tier" for BTC under
            binance_vip5_spot_placeholder_v0.
        uncertainty_margin_fraction: fraction of subtotal added as
            safety margin. Default 0.2 (20%) per Day 22 lock. Must
            be Decimal >= 0.

    Returns:
        A2RoundTripCost with all four legs, subtotal, margin, and
        total decomposed.

    Raises:
        ValueError: invalid margin fraction or unknown slippage tier.
        KeyError-equivalent: tier name not found is raised as
            ValueError with a clear message.
    """
    if not isinstance(uncertainty_margin_fraction, Decimal):
        raise TypeError(
            f"uncertainty_margin_fraction must be Decimal, "
            f"got {type(uncertainty_margin_fraction).__name__}"
        )
    if uncertainty_margin_fraction < 0:
        raise ValueError(
            f"uncertainty_margin_fraction must be >= 0, "
            f"got {uncertainty_margin_fraction}"
        )

    perp_taker_bps = _binance_taker_bps(bundle.perp_profile)
    spot_taker_bps = _binance_taker_bps(bundle.spot_profile)

    perp_slip_bps = _slippage_tier_bps(
        bundle.perp_profile, perp_slippage_tier_name, leg="perp"
    )
    spot_slip_bps = _slippage_tier_bps(
        bundle.spot_profile, spot_slippage_tier_name, leg="spot"
    )

    # Per-leg single-direction cost.
    perp_one_way = perp_taker_bps + perp_slip_bps
    spot_one_way = spot_taker_bps + spot_slip_bps

    # Symmetric entry/exit per 22.4 lock.
    perp_entry = perp_one_way
    perp_exit = perp_one_way
    spot_entry = spot_one_way
    spot_exit = spot_one_way

    subtotal = perp_entry + perp_exit + spot_entry + spot_exit
    margin = subtotal * uncertainty_margin_fraction
    total = subtotal + margin

    return A2RoundTripCost(
        perp_entry_bps=perp_entry,
        perp_exit_bps=perp_exit,
        spot_entry_bps=spot_entry,
        spot_exit_bps=spot_exit,
        subtotal_bps=subtotal,
        uncertainty_margin_bps=margin,
        total_threshold_bps=total,
    )


def _binance_taker_bps(profile: CostModelConfig) -> Decimal:
    """Extract the binance venue taker fee from a profile, converted to bps."""
    fee_schedule = next(
        (fs for fs in profile.fee_schedules if fs.venue == "binance"),
        None,
    )
    if fee_schedule is None:
        venues = sorted({fs.venue for fs in profile.fee_schedules})
        raise ValueError(
            f"profile {profile.profile_name!r} has no FeeSchedule for "
            f"venue 'binance'; known venues: {venues}"
        )
    return fee_schedule.taker_bps * _BPS_SCALE


def _slippage_tier_bps(
    profile: CostModelConfig, tier_name: str, *, leg: str
) -> Decimal:
    """Extract a named slippage tier from a profile, converted to bps."""
    tier = next(
        (t for t in profile.slippage_tiers if t.tier_name == tier_name),
        None,
    )
    if tier is None:
        available = sorted(t.tier_name for t in profile.slippage_tiers)
        raise ValueError(
            f"{leg} profile {profile.profile_name!r} has no slippage "
            f"tier {tier_name!r}; available tiers: {available}"
        )
    return tier.slippage_bps * _BPS_SCALE
