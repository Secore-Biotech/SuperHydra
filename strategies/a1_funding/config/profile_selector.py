"""A1 cost-profile selector.

Policy module: maps (instrument_code, venue) → CostModelConfig for the
A1 funding-rate engine. Lives under the A1 strategy because profile
selection is a policy decision specific to this engine. A2, A3, or
Sleeve B engines may choose differently and should have their own
selectors.

What this module IS:
  - Pure-function policy. No I/O, no side effects, no clock dependency.
  - Engine-scoped. A1's choice of which Binance fee tier to model is
    A1's policy, not the platform's.
  - Forward-compatible. The current implementation only handles
    Binance + BTCUSDT/ETHUSDT because that's all A1 trades in P0.
    Altcoins and other venues will land in later Days as separate
    profiles + selector branches.

What this module IS NOT:
  - A registry of every profile A1 might ever use. Calibrated profiles
    live in core.config.cost_model. This module just decides WHICH one
    to return for a given (instrument, venue) pair.
  - A runtime configuration system. The selector is deterministic given
    its inputs; runtime overrides go through explicit cost_model arguments
    on the runner / harness layer, not through this module.

Day 17b scope: Binance BTCUSDT/ETHUSDT only. Altcoin profiles and
multi-venue selection are deferred to later Days when the calibration
data exists.
"""
from __future__ import annotations

from core.config.cost_model import (
    CostModelConfig,
    binance_vip5_alt_research_v1,
    binance_vip5_alt_v1,
    binance_vip5_btc_v1,
)


# Set of supported BTC/ETH-class instruments on Binance for which
# binance_vip5_btc_v1 is the appropriate profile. ETHUSDT is included
# because its top-of-book liquidity profile is similar enough to BTCUSDT
# that the same slippage tier and fee schedule applies. Altcoins on
# Binance are NOT in this set; they need a different slippage tier and
# possibly different fee assumptions, so they raise NotImplementedError
# until that calibration lands.
_BINANCE_BTC_ETH_INSTRUMENTS: frozenset[str] = frozenset({
    "BTCUSDT",
    "ETHUSDT",
})

# Liquid alt instruments calibrated under binance_vip5_alt_v1.
# SOLUSDT is the initial calibration target. Other alts (DOGE,
# AVAX, etc.) intentionally omitted until each is empirically
# calibrated; defaulting them to liquid_alt_tier without a
# spread/fill-cost check would be calibration-by-assumption.
_BINANCE_LIQUID_ALT_INSTRUMENTS: frozenset[str] = frozenset({
    "SOLUSDT",
})


def select_profile_for_a1(
    instrument_code: str,
    venue: str,
) -> CostModelConfig:
    """Return the appropriate cost-model profile for an A1 trade.

    Args:
        instrument_code: Venue-native instrument symbol (e.g. "BTCUSDT").
            Treated case-sensitively because Binance instrument symbols
            are case-sensitive in their API.
        venue: Venue identifier. Normalized to lowercase before matching.

    Returns:
        A CostModelConfig instance from core.config.cost_model. The
        instance is freshly constructed each call (CostModelConfig is
        a frozen dataclass; identity equality across calls isn't
        guaranteed but content equality is).

    Raises:
        NotImplementedError: when no calibrated profile exists for the
            (instrument_code, venue) pair. The error message includes
            both inputs and the names of currently supported pairs so
            the caller can decide between adding a new profile, picking
            a different instrument, or accepting the no-trade outcome.
    """
    venue_normalized = venue.lower()

    if venue_normalized == "binance":
        if instrument_code in _BINANCE_BTC_ETH_INSTRUMENTS:
            return binance_vip5_btc_v1()
        if instrument_code in _BINANCE_LIQUID_ALT_INSTRUMENTS:
            return binance_vip5_alt_v1()
        raise NotImplementedError(
            f"No A1 cost profile for instrument_code={instrument_code!r} "
            f"on venue {venue!r}. Currently supported on \"binance\": "
            f"BTC/ETH ({sorted(_BINANCE_BTC_ETH_INSTRUMENTS)}) under "
            f"binance_vip5_btc_v1; liquid alts "
            f"({sorted(_BINANCE_LIQUID_ALT_INSTRUMENTS)}) under "
            f"binance_vip5_alt_v1. Other alts need their own slippage "
            f"calibration; SOLUSDT is the calibrated example to follow."
        )

    raise NotImplementedError(
        f"No A1 cost profile for venue {venue!r}. Currently supported: "
        f"\"binance\" only. Multi-venue support is deferred to a later "
        f"Day."
    )



# ─── EXPLICIT FIREWALL HOLE (Day 20.4) ────────────────────────────────────
#
# The function below returns research-firewalled cost profiles for use
# in PAPER_RESEARCH-mode paper.fills writes ONLY. It is named with an
# explicit `_research_` infix so the firewall hole is visible at every
# call site grep would find. The default selector `select_profile_for_a1`
# above continues to refuse research profiles; the firewall regression
# test (TestResearchProfileFirewall) verifies that no input to the
# default selector returns a research-named profile.
#
# Callers using `select_research_profile_for_a1` are responsible for
# ensuring the result flows ONLY into:
#   - paper.fills rows with source_mode='PAPER_RESEARCH'
#   - promotion_eligible = false (enforced by DB CHECK)
#   - Never trading.fills, never accounting.funding_payments
#
# Misuse outside PAPER_RESEARCH mode is the caller's bug; the firewall
# at the schema/DB layer remains in place regardless.


def select_research_profile_for_a1(
    instrument_code: str,
    venue: str,
) -> CostModelConfig:
    """Return the research-firewalled cost profile for a PAPER_RESEARCH
    paper.fills write.

    This function is the ONLY supported way to obtain a research profile
    for use in A1's paper-research flow. It is intentionally NOT the
    default selector; the default `select_profile_for_a1` continues to
    refuse research profiles.

    Args:
        instrument_code: Venue-native instrument symbol (case-sensitive).
        venue: Venue identifier (case-insensitive).

    Returns:
        A research-firewalled CostModelConfig. Caller responsibility:
        the result must only be used for PAPER_RESEARCH paper.fills
        writes, never for live execution, canary, or any record marked
        promotion_eligible=true.

    Raises:
        NotImplementedError: when no research profile exists for the
            (instrument_code, venue) pair.
    """
    venue_normalized = venue.lower()

    if venue_normalized == "binance":
        if instrument_code in _BINANCE_LIQUID_ALT_INSTRUMENTS:
            return binance_vip5_alt_research_v1()
        raise NotImplementedError(
            f"No A1 research profile for instrument_code={instrument_code!r} "
            f"on venue {venue!r}. Currently supported on \"binance\": "
            f"liquid alts ({sorted(_BINANCE_LIQUID_ALT_INSTRUMENTS)}) "
            f"under binance_vip5_alt_research_v1. BTC/ETH research "
            f"profiles do not exist (Day 17c found BTCUSDT structurally "
            f"untradeable across all profiles)."
        )

    raise NotImplementedError(
        f"No A1 research profile for venue {venue!r}. Currently "
        f"supported: \"binance\" only."
    )
