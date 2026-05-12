"""A2 cost-profile selector.

Day 22 deliverable. Mirrors A1's profile_selector pattern but returns
a bundle of (perp_profile, spot_profile) because A2 is two-legged.

A2 is currently PAPER_RESEARCH only — there is no governance-tier
profile because no empirical calibration exists yet. Following the
Day 19a firewall-naming discipline, the only public function is
`select_research_profile_for_a2`, named with the explicit `_research_`
infix so the un-calibrated status is visible at every call site.

A future Day will add `select_profile_for_a2` (governance default)
once the spot leg's empirical calibration lands.

What this module IS:
  - Pure-function policy: same inputs → same A2CostBundle outputs
  - Returns a bundle (perp_profile, spot_profile) for A2 cost-threshold
    computation
  - Explicit firewall-hole naming pattern

What this module IS NOT:
  - Not a runtime cost calculator (use compute_a2_round_trip_threshold_bps
    in signal.cost_threshold for that)
  - Not a registry of all possible A2 profiles (only the currently-
    calibrated set; expansions land as new factory functions in
    core.config.cost_model)
"""
from __future__ import annotations

from dataclasses import dataclass

from core.config.cost_model import (
    CostModelConfig,
    binance_vip5_alt_v1,
    binance_vip5_btc_v1,
    binance_vip5_spot_placeholder_v0,
)


# Same instrument sets as A1's selector — A2 inherits the same scope
# for its first calibration pass. BTC/ETH share the BTC profile; SOL
# uses the alt profile. The spot leg currently uses one shared
# placeholder profile that contains both spot_btc_eth_top_tier and
# spot_liquid_alt_tier as separate slippage tiers.
_BINANCE_BTC_ETH_INSTRUMENTS: frozenset[str] = frozenset({
    "BTCUSDT",
    "ETHUSDT",
})

_BINANCE_LIQUID_ALT_INSTRUMENTS: frozenset[str] = frozenset({
    "SOLUSDT",
})


@dataclass(frozen=True)
class A2CostBundle:
    """Cost-model bundle for one A2 trade.

    Contains BOTH the perp-leg profile and the spot-leg profile
    because A2 always trades both. Downstream consumers
    (compute_a2_round_trip_threshold_bps, A2 signal evaluator) take
    a bundle and a pair of slippage tier names.

    The two profiles may have different content_hash values; A2
    fills should record BOTH hashes (one per leg's paper.fills row,
    via cost_profile_hash) so reconciliation can prove which
    profiles were active for each leg of each intent.
    """

    perp_profile: CostModelConfig
    spot_profile: CostModelConfig


def select_research_profile_for_a2(
    instrument_code: str,
    venue: str,
) -> A2CostBundle:
    """Return the A2 cost bundle for one (instrument, venue) pair.

    Args:
        instrument_code: Venue-native perp symbol (e.g. "BTCUSDT").
            The spot leg is assumed to trade the same symbol on the
            same venue's spot market (e.g. BTCUSDT spot on Binance).
            Cross-venue A2 is explicitly out of scope for Day 22.
        venue: Venue identifier (case-insensitive).

    Returns:
        A2CostBundle containing:
          - perp_profile: existing A1 calibrated profile for the perp
            leg (BTC/ETH under binance_vip5_btc_v1; SOL under
            binance_vip5_alt_v1)
          - spot_profile: binance_vip5_spot_placeholder_v0
            (placeholder, awaits empirical calibration)

    Raises:
        NotImplementedError: when no A2 calibration exists for the
            (instrument_code, venue) pair.
    """
    venue_normalized = venue.lower()

    if venue_normalized == "binance":
        if instrument_code in _BINANCE_BTC_ETH_INSTRUMENTS:
            perp = binance_vip5_btc_v1()
        elif instrument_code in _BINANCE_LIQUID_ALT_INSTRUMENTS:
            perp = binance_vip5_alt_v1()
        else:
            raise NotImplementedError(
                f"No A2 cost bundle for instrument_code="
                f"{instrument_code!r} on venue {venue!r}. "
                f"Currently supported on \"binance\": BTC/ETH "
                f"({sorted(_BINANCE_BTC_ETH_INSTRUMENTS)}) "
                f"under binance_vip5_btc_v1; liquid alts "
                f"({sorted(_BINANCE_LIQUID_ALT_INSTRUMENTS)}) under "
                f"binance_vip5_alt_v1. The spot leg uses "
                f"binance_vip5_spot_placeholder_v0 for both."
            )
        spot = binance_vip5_spot_placeholder_v0()
        return A2CostBundle(perp_profile=perp, spot_profile=spot)

    raise NotImplementedError(
        f"No A2 cost bundle for venue {venue!r}. Currently supported: "
        f"\"binance\" only. Multi-venue A2 is deferred indefinitely."
    )
