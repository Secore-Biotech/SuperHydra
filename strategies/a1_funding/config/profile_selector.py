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
        raise NotImplementedError(
            f"No A1 cost profile for instrument_code={instrument_code!r} "
            f"on venue {venue!r}. Currently supported: "
            f"{sorted(_BINANCE_BTC_ETH_INSTRUMENTS)} on \"binance\". "
            f"Adding altcoin support requires calibrating a separate "
            f"slippage tier and fee schedule (deferred to a later Day)."
        )

    raise NotImplementedError(
        f"No A1 cost profile for venue {venue!r}. Currently supported: "
        f"\"binance\" only. Multi-venue support is deferred to a later "
        f"Day."
    )
