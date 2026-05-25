"""24h realised-volatility estimator.

A pure function over a window of canonical BinanceKline observations.
Returns annualised realised vol computed from hourly close-to-close
log returns.

Design properties (matches A1 expected_funding.py):

  - Pure. Same inputs → same outputs. No I/O, no clocks, no global state.
    This is what makes paper-Sharpe reproducibility provable.

  - Deterministic statistics. Mean, variance, stdev, and sqrt are all
    computed in Decimal under a locked-precision context. Float arithmetic
    would make two byte-equal inputs produce different sigma values and
    corrupt reproducibility.

  - No look-ahead. The function takes a window of bars and returns sigma
    for that window. Window contents must be strictly older than the
    decision moment the caller will use them for. The caller enforces
    this; the function does not check timestamps against any clock.

  - Validation. Window must be exactly 25 bars, single (venue, instrument),
    all 1h interval, strictly ascending by open_time, contiguous with no
    gaps (each open_time = prev + 3600 seconds), all closes strictly
    positive. Anything else raises RealisedVolError with specific context.

Window-vs-return-count convention (per spec §2):
  - A 24h realised-vol window measures 24 hourly close-to-close log
    returns. That requires 25 closes (n returns require n+1 closes).
  - _WINDOW_BAR_COUNT = 25, _RETURN_COUNT = 24.
  - Changing this would alter event counts under the percentile machinery
    in commit 3 and is forbidden under the spec §8 immutability contract.
  - Drift between these constants and config.pre_lock is caught by
    tests.unit.test_realised_vol.test_constants_match_pre_lock.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from typing import Final, Sequence

from data.ingestion.vendors.binance.kline import BinanceKline

REALISED_VOL_SCHEMA_VERSION: Final[str] = "realised_vol.v0"

# Pre-locked under spec §2. Self-contained literals; drift-guard test
# verifies consistency with config.pre_lock.
_WINDOW_BAR_COUNT: Final[int] = 25
_RETURN_COUNT: Final[int] = 24
_INTERVAL: Final[str] = "1h"
_HOUR_SECONDS: Final[int] = 3600
_DECIMAL_PRECISION: Final[int] = 28


class RealisedVolError(Exception):
    """Raised when inputs to the realised-vol estimator are structurally invalid."""


@dataclass(frozen=True)
class RealisedVol:
    """A single 24h realised-vol observation for one (venue, instrument).

    Carries inputs alongside the output so post-hoc reconciliation can
    audit "why did sigma come out at this value." Matches the A1
    ExpectedFunding pattern.

    Fields:
        venue: lowercase venue code (e.g. "binance")
        instrument: vendor-canonical instrument code (e.g. "BTCUSDT")
        window_start: open_time of the earliest bar in the 25-bar window
        window_end: open_time of the latest bar in the 25-bar window
        window_size: number of bars consumed (always 25)
        return_count: number of log-returns computed (always 24;
            between 25 bars there are 24 return intervals)
        mean_log_return: arithmetic mean of hourly log-returns
        stdev_log_return: sample stdev (N-1 denominator) of hourly log-returns
        sigma_24h_annualised: stdev_log_return * sqrt(24 * 365)
        schema_version: version tag of the estimator
    """
    venue: str
    instrument: str
    window_start: datetime
    window_end: datetime
    window_size: int
    return_count: int
    mean_log_return: Decimal
    stdev_log_return: Decimal
    sigma_24h_annualised: Decimal
    schema_version: str


def compute_realised_vol(window: Sequence[BinanceKline]) -> RealisedVol:
    """Compute 24h annualised realised vol from a 25-bar hourly window.

    Pure. Deterministic. Decimal throughout.

    Args:
        window: exactly 25 contiguous 1h klines from one (venue, instrument),
            strictly ascending by open_time, no gaps. The caller is
            responsible for selecting the window; this function does not
            check the window against any clock.

    Returns:
        RealisedVol carrying inputs and the annualised sigma.

    Raises:
        RealisedVolError if:
            - window length is not 25
            - bars span multiple venues or instruments
            - any bar's interval is not "1h"
            - bars are not strictly ascending by open_time
            - bars are not contiguous at hourly intervals
            - any close price is non-positive
    """
    bars = list(window)

    # ===== Validation =====
    if len(bars) != _WINDOW_BAR_COUNT:
        raise RealisedVolError(
            f"window must contain exactly {_WINDOW_BAR_COUNT} bars, got {len(bars)}"
        )

    venues = {b.venue for b in bars}
    if len(venues) != 1:
        raise RealisedVolError(
            f"window must contain a single venue, got {sorted(venues)}"
        )

    instruments = {b.instrument for b in bars}
    if len(instruments) != 1:
        raise RealisedVolError(
            f"window must contain a single instrument, got {sorted(instruments)}"
        )

    intervals = {b.interval for b in bars}
    if intervals != {_INTERVAL}:
        raise RealisedVolError(
            f"window must contain only {_INTERVAL!r} bars, got {sorted(intervals)}"
        )

    for i in range(1, len(bars)):
        prev_t = bars[i - 1].open_time
        curr_t = bars[i].open_time
        if curr_t <= prev_t:
            raise RealisedVolError(
                f"bars must be strictly ascending by open_time; "
                f"got {prev_t} >= {curr_t} at index {i}"
            )
        expected = prev_t + timedelta(seconds=_HOUR_SECONDS)
        if curr_t != expected:
            raise RealisedVolError(
                f"bars must be contiguous at hourly intervals; "
                f"expected {expected} at index {i}, got {curr_t}"
            )

    for i, b in enumerate(bars):
        if b.close <= 0:
            raise RealisedVolError(
                f"close prices must be strictly positive; "
                f"got {b.close} at index {i}"
            )

    # ===== Computation =====
    with localcontext() as ctx:
        ctx.prec = _DECIMAL_PRECISION

        log_returns: list[Decimal] = []
        for i in range(1, _WINDOW_BAR_COUNT):
            ratio = bars[i].close / bars[i - 1].close
            log_returns.append(ratio.ln())

        n = Decimal(_RETURN_COUNT)
        mean = sum(log_returns, Decimal(0)) / n
        # Sample stdev: N-1 denominator
        variance = sum((r - mean) ** 2 for r in log_returns) / (n - Decimal(1))
        stdev = variance.sqrt()
        annualisation = (Decimal(24) * Decimal(365)).sqrt()
        sigma_annualised = stdev * annualisation

    return RealisedVol(
        venue=bars[0].venue,
        instrument=bars[0].instrument,
        window_start=bars[0].open_time,
        window_end=bars[-1].open_time,
        window_size=_WINDOW_BAR_COUNT,
        return_count=_RETURN_COUNT,
        mean_log_return=mean,
        stdev_log_return=stdev,
        sigma_24h_annualised=sigma_annualised,
        schema_version=REALISED_VOL_SCHEMA_VERSION,
    )
