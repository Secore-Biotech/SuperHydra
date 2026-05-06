"""Expected next-period funding model.

A pure function over a window of canonical FundingRate observations.
Returns a forecast of the next funding-interval rate, with explicit
uncertainty discount.

Design properties:

  - Pure. Same inputs → same outputs. No I/O, no clocks, no global state.
    This is what makes paper-Sharpe reproducibility provable.

  - Deterministic statistics. Mean and stdev are computed in Decimal,
    not float. Float rounding would make two byte-equal inputs produce
    different forecasts and corrupt the reproducibility property.

  - Conservative bias. The forecast is `mean - discount_k * stdev`,
    where discount_k comes from the cost-model's FundingUncertainty.
    A high-variance window yields a smaller (more conservative) forecast,
    not a larger one — uncertainty penalises us, not the other way around.

  - No look-ahead. The function takes a window of historical observations
    and returns a forecast for the *next* period. Window contents must
    be strictly older than the period being forecast. The caller enforces
    this; the function does not check timestamps against any clock.

  - Validation. Window must be non-empty, sorted ascending, contiguous in
    schema (single venue, single instrument), and at least `min_lookback`
    long. Otherwise raises with specific context.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final

from data.ingestion.vendors.binance.funding_rate import FundingRate


# Bumped any time the forecast shape or formula changes.
EXPECTED_FUNDING_SCHEMA_VERSION: Final[str] = "expected_funding.v0"


# ─── Errors ───────────────────────────────────────────────────────────────


class ExpectedFundingError(Exception):
    """Raised when inputs to the forecast are structurally invalid."""


# ─── Output type ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ExpectedFunding:
    """A forecast for one (venue, instrument) at one decision moment.

    Carries the inputs to the forecast (window stats) so reconciliation
    can audit "why did the signal say what it said" after the fact.

    Fields:
        venue: lowercase venue code (e.g. "binance")
        instrument: vendor-canonical instrument code (e.g. "BTCUSDT")
        as_of: the moment at which the forecast was computed
        window_start: funding_time of the earliest observation used
        window_end: funding_time of the latest observation used
        window_size: number of observations consumed
        mean_rate: arithmetic mean of funding rates in the window
        stdev_rate: sample stdev of funding rates in the window
            (population stdev if window_size == 1)
        discount_k: uncertainty discount multiple from cost model
        forecast_rate: mean_rate - discount_k * stdev_rate
        schema_version: version tag of the forecast formula
    """

    venue: str
    instrument: str
    as_of: datetime
    window_start: datetime
    window_end: datetime
    window_size: int
    mean_rate: Decimal
    stdev_rate: Decimal
    discount_k: Decimal
    forecast_rate: Decimal
    schema_version: str = EXPECTED_FUNDING_SCHEMA_VERSION


# ─── The forecast ────────────────────────────────────────────────────────


def expected_next_funding(
    window: list[FundingRate],
    *,
    discount_k: Decimal,
    min_lookback: int = 1,
    as_of: datetime,
) -> ExpectedFunding:
    """Compute the expected next-period funding rate for one instrument.

    Args:
        window: list of FundingRate observations, all from the same
            (venue, instrument), sorted by funding_time ascending. Must
            contain at least `min_lookback` records.
        discount_k: uncertainty discount multiple. Forecast is
            `mean - discount_k * stdev`. Must be a non-negative Decimal.
        min_lookback: minimum window length the caller will accept.
            Forecasts below this length raise rather than producing a
            low-confidence answer.
        as_of: the moment the forecast represents. Recorded in the output
            for lineage; must be strictly after every funding_time in the
            window (no look-ahead).

    Returns:
        ExpectedFunding with the forecast and the window stats used to
        produce it.

    Raises:
        ExpectedFundingError on any structural input problem.
    """
    if not isinstance(discount_k, Decimal):
        raise ExpectedFundingError(
            f"discount_k must be Decimal, got {type(discount_k).__name__}"
        )
    if discount_k < Decimal("0"):
        raise ExpectedFundingError(f"discount_k must be >= 0, got {discount_k}")
    if min_lookback < 1:
        raise ExpectedFundingError(f"min_lookback must be >= 1, got {min_lookback}")
    if as_of.tzinfo is None:
        raise ExpectedFundingError("as_of must be timezone-aware")
    if not window:
        raise ExpectedFundingError("window is empty")
    if len(window) < min_lookback:
        raise ExpectedFundingError(
            f"window length {len(window)} below min_lookback {min_lookback}"
        )

    # Single-venue / single-instrument check — the forecast is per-instrument.
    venues = {r.venue for r in window}
    instruments = {r.instrument for r in window}
    if len(venues) != 1:
        raise ExpectedFundingError(f"window spans multiple venues: {sorted(venues)}")
    if len(instruments) != 1:
        raise ExpectedFundingError(
            f"window spans multiple instruments: {sorted(instruments)}"
        )
    venue = next(iter(venues))
    instrument = next(iter(instruments))

    # Sort check — the window contract requires ascending funding_time.
    times = [r.funding_time for r in window]
    if times != sorted(times):
        raise ExpectedFundingError("window must be sorted by funding_time ascending")

    # No look-ahead — every observation must precede as_of.
    if window[-1].funding_time >= as_of:
        raise ExpectedFundingError(
            f"as_of ({as_of}) must be strictly after the latest "
            f"window funding_time ({window[-1].funding_time}); "
            "look-ahead is forbidden"
        )

    rates = [r.funding_rate for r in window]
    mean_rate = _decimal_mean(rates)
    stdev_rate = _decimal_stdev(rates, mean_rate)
    forecast_rate = mean_rate - discount_k * stdev_rate

    return ExpectedFunding(
        venue=venue,
        instrument=instrument,
        as_of=as_of,
        window_start=window[0].funding_time,
        window_end=window[-1].funding_time,
        window_size=len(window),
        mean_rate=mean_rate,
        stdev_rate=stdev_rate,
        discount_k=discount_k,
        forecast_rate=forecast_rate,
    )


# ─── Decimal statistics ──────────────────────────────────────────────────


def _decimal_mean(values: list[Decimal]) -> Decimal:
    """Arithmetic mean over Decimals.

    Uses sum-then-divide; the resulting Decimal carries full precision of
    the divide operation under the active context. Callers needing a
    different precision should set the context before calling.
    """
    if not values:
        raise ExpectedFundingError("cannot compute mean of empty list")
    total = sum(values, Decimal("0"))
    return total / Decimal(len(values))


def _decimal_stdev(values: list[Decimal], mean: Decimal) -> Decimal:
    """Sample standard deviation over Decimals.

    For window_size == 1, returns Decimal('0') by convention — there's no
    spread to measure with one sample. For window_size >= 2, uses the
    Bessel-corrected (n-1) divisor so single-period extremes don't
    artificially shrink the discount.
    """
    n = len(values)
    if n == 0:
        raise ExpectedFundingError("cannot compute stdev of empty list")
    if n == 1:
        return Decimal("0")
    sq_diffs = [(v - mean) * (v - mean) for v in values]
    variance = sum(sq_diffs, Decimal("0")) / Decimal(n - 1)
    return _decimal_sqrt(variance)


def _decimal_sqrt(x: Decimal) -> Decimal:
    """Decimal square root via the standard library's `sqrt` method.

    `Decimal.sqrt()` uses the active context's precision. We rely on the
    default context here; tests asserting determinism must run under
    the same context (which they do, by virtue of pytest's default).
    """
    if x < Decimal("0"):
        raise ExpectedFundingError(f"cannot sqrt negative: {x}")
    return x.sqrt()
