"""Event pipeline for vol_event_persistence — probe-phase analytics.

Probe-phase analytics only. No paper.fills, no OMS/risk route,
no P1 implication. P1 wiring is separate if §5/§6 gates clear.

This module turns a contiguous hourly kline series plus a funding series
(one instrument) into a series of per-event ForwardReturn records, which
the gates (commit 9) consume. The flow:

    build_vol_series   hourly klines -> daily σ at each 00:00 UTC anchor
    detect_events      σ series      -> EventDecision per anchor (P95 test)
    build_forward_returns  candidates -> ForwardReturn per (event, horizon)
    run_pipeline       orchestrates the above + assembles RunSummary

Deferred to P1 (out of probe scope), per the operating split:
    Probe phase: pure historical analytics.   <- this module
    P1 phase:    production OMS/risk/ledger path.
Specifically NOT done here: paper.fills persistence, risk.evaluate_action,
the OMS submission path, trading.fills / SHADOW writes.

SKIP RULE (skip-and-account with outcome-independence guard)
-----------------------------------------------------------
A window is skipped only for data-completeness reasons knowable BEFORE
attribution runs:
    - insufficient trailing bars for sigma
    - non-contiguous 25-bar realised-vol window
    - insufficient percentile history
    - missing entry bar
    - missing exit bar
    - incomplete funding coverage over holding window
    - truncated forward window near series end

HARD GUARD: no skip rule may inspect forward return, net PnL, or whether
the trade would have won/lost. The skip decision is computed purely from
data availability; compute_forward_return is only ever called AFTER the
window has passed every data-completeness check, so no skip path has the
return in scope.

Skip counts are surfaced in RunSummary. If gap-skipped would-trade events
exceed 5% of event candidates, RunSummary.data_quality_suspect is set
(a flag, not an abort — the run completes and the gate layer decides what
to do with a suspect run).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from enum import Enum
from typing import Final, Sequence

from data.ingestion.vendors.binance.funding_rate import FundingRate
from data.ingestion.vendors.binance.kline import BinanceKline
from strategies.vol_event_persistence.attribution.forward_returns import (
    ForwardReturn,
    compute_forward_return,
)
from strategies.vol_event_persistence.config import pre_lock
from strategies.vol_event_persistence.signal.evaluate import (
    EventDecision,
    EventDirection,
    evaluate_event,
)
from strategies.vol_event_persistence.signal.realised_vol import (
    RealisedVol,
    RealisedVolError,
    compute_realised_vol,
)
from strategies.vol_event_persistence.sizing.order_intent import event_id_for

EVENT_PIPELINE_SCHEMA_VERSION: Final[str] = "event_pipeline.v0"

# Derived from the spec constants. 24 hourly returns require 25 bars.
_SIGMA_WINDOW_BARS: Final[int] = pre_lock.VOL_WINDOW_HOURS + 1  # 25
_PERCENTILE_LOOKBACK_DAYS: Final[int] = pre_lock.PERCENTILE_LOOKBACK_DAYS  # 90
_HORIZONS_DAYS: Final[tuple[int, ...]] = pre_lock.HORIZONS_DAYS  # (1, 3, 7)
_BPS: Final[Decimal] = Decimal("10000")
_DECIMAL_PRECISION: Final[int] = 28

# Venue fact, not a spec gate: Binance perps settle funding 3x/day (8h).
_FUNDING_INTERVAL_HOURS: Final[int] = 8

# Pipeline-quality heuristic (not a §5/§6 gate): fraction of would-trade
# events lost to data gaps above which the run is flagged suspect.
DATA_QUALITY_SUSPECT_THRESHOLD: Final[Decimal] = Decimal("0.05")

_UTC = timezone.utc
_ANCHOR_TIME = (0, 0, 0)  # 00:00:00 UTC daily anchor (spec EVAL_TIME_UTC)


class EventPipelineError(Exception):
    """Raised on structurally invalid input (caller bug), never on a data gap."""


# ─── Per-(event, horizon) outcome classification ────────────────────────────


class _HorizonOutcome(str, Enum):
    BUILT = "built"
    SKIP_MISSING_ENTRY = "skip_missing_entry"
    SKIP_MISSING_EXIT = "skip_missing_exit"       # exit within range but absent
    SKIP_FUNDING_GAP = "skip_funding_gap"
    SKIP_TRUNCATED = "skip_truncated"             # exit beyond series end


# ─── Result types ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RunSummary:
    """Audit counters for one pipeline run over one instrument.

    Granularity notes:
      - sigma_windows_* and percentile/anchor counters are per daily anchor.
      - event_candidates / events_valid / events_skipped_missing_entry are
        per would-trade event (is_event AND direction in {LONG, SHORT}).
      - events_skipped_missing_exit / _funding_gap / _truncated_horizon and
        forward_returns_built are per (event, horizon) pair.
      - events_flat counts fired events with a FLAT direction (no trade
        intended; not a data skip).
    data_quality_suspect is set when gap-unevaluable would-trade events
    exceed DATA_QUALITY_SUSPECT_THRESHOLD of event_candidates.
    """

    venue: str
    instrument: str
    bars_total: int
    sigma_windows_total: int
    sigma_windows_valid: int
    sigma_windows_skipped_gap: int
    anchors_skipped_insufficient_history: int
    percentile_events_total: int
    event_candidates: int
    events_flat: int
    events_valid: int
    events_skipped_missing_entry: int
    events_skipped_missing_exit: int
    events_skipped_funding_gap: int
    events_skipped_truncated_horizon: int
    forward_returns_built: int
    data_quality_suspect: bool
    suspect_skip_rate: Decimal
    schema_version: str = EVENT_PIPELINE_SCHEMA_VERSION


@dataclass(frozen=True)
class RunResult:
    summary: RunSummary
    forward_returns: tuple[ForwardReturn, ...]


# ─── Time helpers ────────────────────────────────────────────────────────────


def _floor_to_anchor(ts: datetime) -> datetime:
    """The 00:00:00 UTC anchor on the same UTC day as ts."""
    return ts.astimezone(_UTC).replace(
        hour=_ANCHOR_TIME[0], minute=_ANCHOR_TIME[1],
        second=_ANCHOR_TIME[2], microsecond=0,
    )


def daily_anchors(min_open: datetime, max_open: datetime) -> list[datetime]:
    """Daily 00:00 UTC anchors A for which a σ window MIGHT exist.

    Requires A - 25h >= min_open (room for the trailing window) and
    A - 1h <= max_open (the entry/last-σ bar exists in range). Returns
    anchors ascending; emptiness is valid for short series.
    """
    if min_open.tzinfo is None or max_open.tzinfo is None:
        raise EventPipelineError("kline open_time must be timezone-aware UTC")
    earliest = min_open + timedelta(hours=_SIGMA_WINDOW_BARS)  # A-25h >= min
    first = _floor_to_anchor(earliest)
    if first < earliest:
        first = first + timedelta(days=1)
    last_allowed = max_open + timedelta(hours=1)  # A-1h <= max  => A <= max+1h
    anchors: list[datetime] = []
    a = first
    while a <= last_allowed:
        anchors.append(a)
        a = a + timedelta(days=1)
    return anchors


def sigma_window_open_times(anchor: datetime) -> list[datetime]:
    """The 25 hourly open_times [A-25h, A-1h], ascending."""
    return [
        anchor - timedelta(hours=k)
        for k in range(_SIGMA_WINDOW_BARS, 0, -1)
    ]


def expected_funding_times(anchor: datetime, horizon_days: int) -> list[datetime]:
    """Funding settlement instants in (A, A + horizon·24h], 8h apart."""
    end = anchor + timedelta(days=horizon_days)
    times: list[datetime] = []
    t = anchor + timedelta(hours=_FUNDING_INTERVAL_HOURS)
    while t <= end:
        times.append(t)
        t = t + timedelta(hours=_FUNDING_INTERVAL_HOURS)
    return times


# ─── Input validation ────────────────────────────────────────────────────────


def _check_homogeneous(
    klines: Sequence[BinanceKline], venue: str, instrument: str
) -> None:
    for k in klines:
        if k.venue != venue or k.instrument != instrument:
            raise EventPipelineError(
                f"kline series is not homogeneous: expected "
                f"{venue}/{instrument}, found {k.venue}/{k.instrument}"
            )
        if k.interval != pre_lock.VOL_RETURN_BAR:
            raise EventPipelineError(
                f"kline interval must be {pre_lock.VOL_RETURN_BAR!r}, "
                f"found {k.interval!r}"
            )


# ─── Stage 1: σ series ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _VolSeriesResult:
    sigma_by_anchor: dict[datetime, RealisedVol]
    anchors: list[datetime]
    windows_total: int
    windows_valid: int
    windows_skipped_gap: int


def build_vol_series(
    klines: Sequence[BinanceKline], venue: str, instrument: str
) -> _VolSeriesResult:
    """Build daily σ at each anchor with a contiguous 25-bar trailing window."""
    if not klines:
        return _VolSeriesResult({}, [], 0, 0, 0)
    _check_homogeneous(klines, venue, instrument)

    by_open = {k.open_time: k for k in klines}
    if len(by_open) != len(klines):
        raise EventPipelineError("duplicate kline open_time in series")

    min_open = min(by_open)
    max_open = max(by_open)
    anchors = daily_anchors(min_open, max_open)

    sigma_by_anchor: dict[datetime, RealisedVol] = {}
    valid = 0
    skipped = 0
    for a in anchors:
        open_times = sigma_window_open_times(a)
        window = [by_open[t] for t in open_times if t in by_open]
        if len(window) != _SIGMA_WINDOW_BARS:
            skipped += 1  # non-contiguous / missing trailing bars (data gap)
            continue
        try:
            sigma_by_anchor[a] = compute_realised_vol(window)
            valid += 1
        except RealisedVolError:
            # Defensive: presence check passed but the estimator rejected the
            # window (e.g. an unexpected interval mismatch). Treat as a gap.
            skipped += 1
    return _VolSeriesResult(sigma_by_anchor, anchors, len(anchors), valid, skipped)


# ─── Stage 2: events ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _DetectResult:
    decisions: list[EventDecision]
    percentile_events_total: int
    anchors_skipped_insufficient_history: int


def detect_events(
    vol: _VolSeriesResult, venue: str, instrument: str
) -> _DetectResult:
    """Run the P95 test at each anchor with 90 contiguous prior daily σ."""
    decisions: list[EventDecision] = []
    evaluated = 0
    skipped_history = 0
    for a in vol.anchors:
        current = vol.sigma_by_anchor.get(a)
        if current is None:
            continue  # already counted as a σ gap in stage 1
        prior_anchors = [
            a - timedelta(days=k)
            for k in range(_PERCENTILE_LOOKBACK_DAYS, 0, -1)
        ]
        history = [vol.sigma_by_anchor[p] for p in prior_anchors
                   if p in vol.sigma_by_anchor]
        if len(history) != _PERCENTILE_LOOKBACK_DAYS:
            skipped_history += 1  # holey 90-day window: cannot compute P95
            continue
        decisions.append(evaluate_event(history, current, as_of=a))
        evaluated += 1
    return _DetectResult(decisions, evaluated, skipped_history)


# ─── Stage 3: forward returns ─────────────────────────────────────────────────


@dataclass(frozen=True)
class _BuildResult:
    forward_returns: list[ForwardReturn]
    event_candidates: int
    events_flat: int
    events_valid: int
    skipped_missing_entry: int
    skipped_missing_exit: int
    skipped_funding_gap: int
    skipped_truncated: int
    forward_returns_built: int
    suspect_candidates: int


def _sum_funding_bps(
    funding_by_time: dict[datetime, FundingRate], times: list[datetime]
) -> Decimal | None:
    """Sum funding over the expected times, or None if any is missing."""
    total = Decimal("0")
    for t in times:
        fr = funding_by_time.get(t)
        if fr is None:
            return None
        total += fr.funding_rate
    with localcontext() as ctx:
        ctx.prec = _DECIMAL_PRECISION
        return total * _BPS


def build_forward_returns(
    decisions: Sequence[EventDecision],
    klines: Sequence[BinanceKline],
    funding: Sequence[FundingRate],
    venue: str,
    instrument: str,
) -> _BuildResult:
    """Attribute per-(event, horizon) net P&L for every would-trade event.

    Outcome-independence: every skip below is decided from data presence
    only; compute_forward_return runs strictly after all presence checks.
    """
    by_open = {k.open_time: k for k in klines}
    funding_by_time = {f.funding_time: f for f in funding}
    last_open = max(by_open) if by_open else None

    out: list[ForwardReturn] = []
    candidates = 0
    flat = 0
    valid = 0
    miss_entry = 0
    miss_exit = 0
    fund_gap = 0
    truncated = 0
    built = 0
    suspect = 0

    for d in decisions:
        if not d.is_event:
            continue
        if d.direction is EventDirection.FLAT:
            flat += 1
            continue
        candidates += 1
        a = d.as_of

        # Entry bar (shared across horizons): close of bar open_time A-1h.
        entry_bar = by_open.get(a - timedelta(hours=1))
        if entry_bar is None:
            miss_entry += 1
            suspect += 1  # gap-caused, not truncation: entry is in the past
            continue

        built_this_event = 0
        gap_this_event = False
        for h in _HORIZONS_DAYS:
            outcome = _attempt_horizon(
                d, a, h, entry_bar, by_open, funding_by_time, last_open,
                venue, instrument, out,
            )
            if outcome is _HorizonOutcome.BUILT:
                built += 1
                built_this_event += 1
            elif outcome is _HorizonOutcome.SKIP_MISSING_EXIT:
                miss_exit += 1
                gap_this_event = True
            elif outcome is _HorizonOutcome.SKIP_FUNDING_GAP:
                fund_gap += 1
                gap_this_event = True
            elif outcome is _HorizonOutcome.SKIP_TRUNCATED:
                truncated += 1  # expected near series end; NOT suspect

        if built_this_event > 0:
            valid += 1
        elif gap_this_event:
            # Zero horizons built AND at least one loss was a real gap
            # (not pure end-of-series truncation): a suspect candidate.
            suspect += 1

    return _BuildResult(
        out, candidates, flat, valid, miss_entry, miss_exit, fund_gap,
        truncated, built, suspect,
    )


def _attempt_horizon(
    d: EventDecision,
    anchor: datetime,
    horizon_days: int,
    entry_bar: BinanceKline,
    by_open: dict[datetime, BinanceKline],
    funding_by_time: dict[datetime, FundingRate],
    last_open: datetime | None,
    venue: str,
    instrument: str,
    out: list[ForwardReturn],
) -> _HorizonOutcome:
    """Try to build one (event, horizon) ForwardReturn. Pure data-presence
    gating; attribution runs only after all checks pass."""
    exit_open = anchor + timedelta(days=horizon_days) - timedelta(hours=1)

    # Distinguish truncation (beyond series end) from a mid-series gap.
    if last_open is not None and exit_open > last_open:
        return _HorizonOutcome.SKIP_TRUNCATED
    exit_bar = by_open.get(exit_open)
    if exit_bar is None:
        return _HorizonOutcome.SKIP_MISSING_EXIT

    funding_bps = _sum_funding_bps(
        funding_by_time, expected_funding_times(anchor, horizon_days)
    )
    if funding_bps is None:
        return _HorizonOutcome.SKIP_FUNDING_GAP

    # All data present — only now is attribution allowed to run.
    fr = compute_forward_return(
        venue=venue,
        instrument=instrument,
        event_id=event_id_for(venue, instrument, anchor),
        direction=d.direction,
        horizon_days=horizon_days,
        entry_price=entry_bar.close,
        exit_price=exit_bar.close,
        realised_funding_bps=funding_bps,
    )
    out.append(fr)
    return _HorizonOutcome.BUILT


# ─── Orchestrator ─────────────────────────────────────────────────────────────


def run_pipeline(
    klines: Sequence[BinanceKline],
    funding: Sequence[FundingRate],
    venue: str,
    instrument: str,
) -> RunResult:
    """Run the full probe pipeline for one instrument. Pure; no I/O."""
    vol = build_vol_series(klines, venue, instrument)
    detect = detect_events(vol, venue, instrument)
    build = build_forward_returns(
        detect.decisions, klines, funding, venue, instrument
    )

    if build.event_candidates > 0:
        with localcontext() as ctx:
            ctx.prec = _DECIMAL_PRECISION
            rate = Decimal(build.suspect_candidates) / Decimal(build.event_candidates)
    else:
        rate = Decimal("0")
    suspect = rate > DATA_QUALITY_SUSPECT_THRESHOLD

    summary = RunSummary(
        venue=venue,
        instrument=instrument,
        bars_total=len(klines),
        sigma_windows_total=vol.windows_total,
        sigma_windows_valid=vol.windows_valid,
        sigma_windows_skipped_gap=vol.windows_skipped_gap,
        anchors_skipped_insufficient_history=detect.anchors_skipped_insufficient_history,
        percentile_events_total=detect.percentile_events_total,
        event_candidates=build.event_candidates,
        events_flat=build.events_flat,
        events_valid=build.events_valid,
        events_skipped_missing_entry=build.skipped_missing_entry,
        events_skipped_missing_exit=build.skipped_missing_exit,
        events_skipped_funding_gap=build.skipped_funding_gap,
        events_skipped_truncated_horizon=build.skipped_truncated,
        forward_returns_built=build.forward_returns_built,
        data_quality_suspect=suspect,
        suspect_skip_rate=rate,
    )
    return RunResult(summary=summary, forward_returns=tuple(build.forward_returns))
