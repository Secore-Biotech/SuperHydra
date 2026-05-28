"""Per-day event decision: ties realised vol + percentile detection into
a single directional decision under the persistence hypothesis.

Pure orchestration over two structured inputs (current RealisedVol and a
90-observation history), mirroring the A1 evaluate_signal contract:
structured-in, structured-out, no raw data, no I/O, no clock.

Persistence hypothesis (spec §1, locked):
  - If the current observation is a P95 vol event, take a position in the
    SAME direction as the pre-event cumulative return.
  - pre-event cumulative log return = mean_log_return * return_count.
    This equals the sum of the 24 hourly log returns, which telescopes to
    ln(last_close / first_close) over the window. RealisedVol already
    carries mean_log_return, so no recomputation and no raw klines are
    needed here.
  - Positive cumulative return -> LONG. Negative -> SHORT.
  - Zero cumulative return on an event day -> FLAT: vol spiked but there
    is no directional signal to persist. The event is still recorded
    (is_event True) but produces no trade.
  - Non-event days -> FLAT.

Reversal is out of scope for v1 (spec §10). This module never inverts
the direction.

What this module DOES NOT do:
  - Sizing (later commit).
  - Cost / economic-gate logic (harness + gates layer, later commit).
  - Position-state awareness (runner layer).
  - History-window assembly or contiguity enforcement (runner layer).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext
from enum import Enum
from typing import Final, Sequence

from strategies.vol_event_persistence.signal.percentile_state import (
    evaluate_percentile_event,
)
from strategies.vol_event_persistence.signal.realised_vol import RealisedVol

EVENT_DECISION_SCHEMA_VERSION: Final[str] = "event_decision.v0"

_DECIMAL_PRECISION: Final[int] = 28


class EventDirection(str, Enum):
    """Position direction for an evaluated day.

    LONG: event fired, pre-event cumulative return positive (persistence).
    SHORT: event fired, pre-event cumulative return negative (persistence).
    FLAT: either no event, or an event with zero directional signal.
    """

    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


@dataclass(frozen=True)
class EventDecision:
    """Full record of the per-day event decision.

    Carries the inputs that drove the decision plus the decision itself,
    so reconciliation can audit "why did (or didn't) this day trade, and
    in which direction." Mirrors the A1 SignalEvaluation pattern.

    Fields:
        venue, instrument, as_of: identity + decision moment.
        current_sigma: current.sigma_24h_annualised.
        percentile_value: the trailing P95 sigma the current was tested against.
        is_event: True iff current_sigma strictly exceeded percentile_value.
        pre_event_log_return: cumulative log return over the current window
            (mean_log_return * return_count). Always recorded, even on
            non-event days, for downstream analysis.
        direction: LONG / SHORT / FLAT per the persistence rule above.
        realised_vol_schema_version: lineage tag from the current RealisedVol.
        percentile_event_schema_version: lineage tag from the percentile detector.
        schema_version: this decision's schema tag.
    """

    venue: str
    instrument: str
    as_of: datetime
    current_sigma: Decimal
    percentile_value: Decimal
    is_event: bool
    pre_event_log_return: Decimal
    direction: EventDirection
    realised_vol_schema_version: str
    percentile_event_schema_version: str
    schema_version: str


def evaluate_event(
    history: Sequence[RealisedVol],
    current: RealisedVol,
    as_of: datetime,
) -> EventDecision:
    """Decide direction (or flat) for one instrument on one day.

    Pure. Deterministic. Decimal throughout.

    Args:
        history: 90 prior RealisedVol observations (single venue/instrument,
            strictly ascending by window_end). Passed straight through to
            the percentile detector, which validates structure.
        current: the RealisedVol being tested.
        as_of: decision moment, carried for lineage.

    Returns:
        EventDecision carrying inputs, the event flag, and the direction.

    Raises:
        PercentileEventError (from the percentile detector) if the history
        or current/history relationship is structurally invalid.
    """
    percentile_event = evaluate_percentile_event(history, current, as_of)

    with localcontext() as ctx:
        ctx.prec = _DECIMAL_PRECISION
        # sum of the 24 hourly log returns = ln(last_close / first_close)
        pre_event_log_return = current.mean_log_return * Decimal(current.return_count)

    if not percentile_event.is_event:
        direction = EventDirection.FLAT
    elif pre_event_log_return > 0:
        direction = EventDirection.LONG
    elif pre_event_log_return < 0:
        direction = EventDirection.SHORT
    else:
        # Event fired but zero directional signal: nothing to persist.
        direction = EventDirection.FLAT

    return EventDecision(
        venue=current.venue,
        instrument=current.instrument,
        as_of=as_of,
        current_sigma=current.sigma_24h_annualised,
        percentile_value=percentile_event.percentile_value,
        is_event=percentile_event.is_event,
        pre_event_log_return=pre_event_log_return,
        direction=direction,
        realised_vol_schema_version=current.schema_version,
        percentile_event_schema_version=percentile_event.schema_version,
        schema_version=EVENT_DECISION_SCHEMA_VERSION,
    )
