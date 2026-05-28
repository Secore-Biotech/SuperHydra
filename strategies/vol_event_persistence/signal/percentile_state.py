"""95th-percentile event detector over a trailing realised-vol window.

A pure function over a window of prior RealisedVol observations plus the
current observation. Fires an event when current realised vol exceeds the
nearest-rank P95 of the trailing window.

Design properties (matches realised_vol.py and A1 expected_funding.py):

  - Pure. Same inputs -> same outputs. No I/O, no clocks, no global state.
  - Deterministic. Percentile via nearest-rank (no interpolation), Decimal
    throughout. No float anywhere in the comparison path.
  - Excludes current by construction. The current observation is passed
    separately from history and validated to be strictly after the last
    history element; it never enters the percentile computation.
  - No look-ahead. History must be strictly older than current. The caller
    selects the window; this function does not check against any clock.

Nearest-rank percentile (spec §2, locked):
    rank  = ceil(p * n)
    index = rank - 1   (0-based into the ascending-sorted sigma list)
  For n = 90, p = 0.95: rank = ceil(85.5) = 86, index = 85.
  No interpolation: the percentile value is exactly one observed sigma.

Trigger is strict:
    is_event = current_sigma > percentile_value
  Equality does NOT fire. A current sigma exactly equal to the P95 value
  is not an event.

Constants are local literals; the drift-guard test
tests.unit.test_percentile_state.test_constants_match_pre_lock verifies
consistency with config.pre_lock, so a spec change fails loudly rather
than being silently adopted.

NOT validated here (caller responsibility, flagged in review):
  - Daily contiguity of history. Only strict-ascending order is enforced;
    a gapped 90-observation window would span more than 90 calendar days.
    The runner is responsible for assembling a contiguous daily window.
  - Relationship between as_of and current.window_end. Carried for lineage,
    not checked, matching the A1 expected_funding contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_CEILING, Decimal
from typing import Final, Sequence

from strategies.vol_event_persistence.signal.realised_vol import RealisedVol

PERCENTILE_EVENT_SCHEMA_VERSION: Final[str] = "percentile_event.v0"

# Pre-locked under spec §2. Local literals; drift-guard test verifies
# consistency with config.pre_lock.
_LOOKBACK: Final[int] = 90
_PERCENTILE_P: Final[Decimal] = Decimal("0.95")


class PercentileEventError(Exception):
    """Raised when inputs to the percentile-event detector are structurally invalid."""


@dataclass(frozen=True)
class PercentileEvent:
    """Result of evaluating whether current realised vol is a P95 event.

    Carries inputs alongside the output so post-hoc reconciliation can
    audit "why did (or didn't) this fire."

    Fields:
        venue: lowercase venue code
        instrument: vendor-canonical instrument code
        as_of: decision moment supplied by the caller
        lookback_start: window_end of the earliest history observation
        lookback_end: window_end of the latest history observation
        lookback_size: number of history observations (always 90)
        percentile_threshold: the p used (0.95)
        percentile_value: the nearest-rank P95 sigma from history
        current_sigma: current.sigma_24h_annualised
        is_event: True iff current_sigma strictly exceeds percentile_value
        schema_version: version tag of the detector
    """
    venue: str
    instrument: str
    as_of: datetime
    lookback_start: datetime
    lookback_end: datetime
    lookback_size: int
    percentile_threshold: Decimal
    percentile_value: Decimal
    current_sigma: Decimal
    is_event: bool
    schema_version: str


def evaluate_percentile_event(
    history: Sequence[RealisedVol],
    current: RealisedVol,
    as_of: datetime,
) -> PercentileEvent:
    """Evaluate whether current realised vol exceeds the trailing P95.

    Pure. Deterministic. Decimal throughout.

    Args:
        history: exactly 90 prior RealisedVol observations from a single
            (venue, instrument), strictly ascending by window_end. Must
            not include the current observation.
        current: the RealisedVol being tested. Must share venue/instrument
            with history and have window_end strictly after the last
            history element.
        as_of: the decision moment. Carried into the output for lineage;
            not validated against the windows (caller's responsibility,
            matching the A1 expected_funding contract).

    Returns:
        PercentileEvent carrying inputs, the P95 value, and is_event.

    Raises:
        PercentileEventError if:
            - history length is not 90
            - history + current span multiple venues or instruments
            - history is not strictly ascending by window_end
            - current.window_end is not strictly after history[-1].window_end
    """
    hist = list(history)

    # ===== Validation =====
    if len(hist) != _LOOKBACK:
        raise PercentileEventError(
            f"history must contain exactly {_LOOKBACK} observations, got {len(hist)}"
        )

    venues = {h.venue for h in hist} | {current.venue}
    if len(venues) != 1:
        raise PercentileEventError(
            f"history and current must share a single venue, got {sorted(venues)}"
        )

    instruments = {h.instrument for h in hist} | {current.instrument}
    if len(instruments) != 1:
        raise PercentileEventError(
            f"history and current must share a single instrument, "
            f"got {sorted(instruments)}"
        )

    for i in range(1, len(hist)):
        if hist[i].window_end <= hist[i - 1].window_end:
            raise PercentileEventError(
                f"history must be strictly ascending by window_end; "
                f"got {hist[i - 1].window_end} >= {hist[i].window_end} at index {i}"
            )

    if current.window_end <= hist[-1].window_end:
        raise PercentileEventError(
            f"current.window_end ({current.window_end}) must be strictly after "
            f"the last history window_end ({hist[-1].window_end}); current must "
            f"not be included in history"
        )

    # ===== Nearest-rank percentile =====
    n = len(hist)
    sorted_sigmas = sorted(h.sigma_24h_annualised for h in hist)
    rank = int((_PERCENTILE_P * Decimal(n)).to_integral_value(rounding=ROUND_CEILING))
    # Guard: rank in [1, n]. For locked p=0.95, n=90 -> rank=86. Defensive
    # only; cannot trigger under the locked constants.
    if rank < 1 or rank > n:
        raise PercentileEventError(
            f"computed rank {rank} out of bounds for n={n}; "
            f"check percentile threshold {_PERCENTILE_P}"
        )
    index = rank - 1
    percentile_value = sorted_sigmas[index]

    is_event = current.sigma_24h_annualised > percentile_value

    return PercentileEvent(
        venue=current.venue,
        instrument=current.instrument,
        as_of=as_of,
        lookback_start=hist[0].window_end,
        lookback_end=hist[-1].window_end,
        lookback_size=n,
        percentile_threshold=_PERCENTILE_P,
        percentile_value=percentile_value,
        current_sigma=current.sigma_24h_annualised,
        is_event=is_event,
        schema_version=PERCENTILE_EVENT_SCHEMA_VERSION,
    )
