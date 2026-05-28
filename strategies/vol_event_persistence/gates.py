"""Probe gates for vol_event_persistence — statistical (§5) + economic (§6).

Pure. Consumes the ForwardReturn series from the event pipeline (commit 8)
and decides, per horizon, whether the probe edge clears the locked gates.

Probe-phase analytics only. No persistence, no OMS/risk, no P1 implication.

Locked interpretations (operator-confirmed):
  - Train/OOS split is by CALENDAR TIME at 80% of the series span, computed
    once (spec OOS_SHOT_COUNT=1). The split is never slid to satisfy counts.
  - Sharpe is unannualised per-event: mean(net_bps) / stdev(net_bps), sample
    stdev (N-1). Events are irregular; annualising would inject a fake
    periods-per-year assumption.
  - INSUFFICIENT_SAMPLE is decided before the statistical/economic checks:
    train events >= 100, OOS events >= 30, OOS span >= 6 months. Any miss
    short-circuits to INSUFFICIENT_SAMPLE (the edge is simply unproven).
  - Rolling-failure check (§5): OOS split into 30-calendar-day windows; a
    window with >= 3 events whose Sharpe is negative OR undefined (zero
    dispersion) is a failure; > OOS_ROLLING_FAILURES_MAX failures fails the
    gate. Windows with < 3 events are ignored (degenerate Sharpe).
  - Cost coverage (§6): mean(gross_bps) / mean(execution_cost_bps -
    min(0, funding_pnl_bps)). Funding credit does not reduce the denominator.
  - final-3-months (§6): the last 3 calendar months of the WHOLE series
    (a recency-decay check, not an OOS sub-check).
  - Zero-dispersion Sharpe is undefined and treated as a FAIL ("must prove
    the edge", not benefit of the doubt).

Gates are per horizon (1d / 3d / 7d are distinct hypotheses; never
aggregated). The probe PASSES if at least one horizon clears BOTH gates.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from enum import Enum
from typing import Final, Sequence

from strategies.vol_event_persistence.attribution.forward_returns import (
    ForwardReturn,
)
from strategies.vol_event_persistence.config import pre_lock

GATES_SCHEMA_VERSION: Final[str] = "gates.v0"

_DECIMAL_PRECISION: Final[int] = 28
_UTC = timezone.utc

# Calendar span helpers. "6 months" and "3 months" are calendar spans; we
# approximate month boundaries with day counts to stay pure (no calendar lib):
# 6 months = 182 days, 3 months = 91 days. Documented so the choice is explicit.
_OOS_MIN_DAYS: Final[int] = 182          # spec OOS_MIN_MONTHS = 6
_FINAL_WINDOW_DAYS: Final[int] = 91      # final-3-months recency check
_ROLLING_WINDOW_DAYS: Final[int] = 30    # §5 rolling-failure window
_ROLLING_MIN_EVENTS: Final[int] = 3      # ignore windows with fewer events
_SPLIT_FRACTION: Final[Decimal] = pre_lock.TRAIN_FRACTION  # 0.80


class GateStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    INSUFFICIENT_SAMPLE = "insufficient_sample"


# ─── Statistics (pure Decimal) ───────────────────────────────────────────────


def mean(xs: Sequence[Decimal]) -> Decimal:
    if not xs:
        raise ValueError("mean of empty sequence")
    with localcontext() as ctx:
        ctx.prec = _DECIMAL_PRECISION
        return sum(xs, Decimal("0")) / Decimal(len(xs))


def sample_stdev(xs: Sequence[Decimal]) -> Decimal:
    """Sample standard deviation (N-1). Returns 0 for n<2 or zero dispersion."""
    n = len(xs)
    if n < 2:
        return Decimal("0")
    with localcontext() as ctx:
        ctx.prec = _DECIMAL_PRECISION
        m = mean(xs)
        ss = sum(((x - m) ** 2 for x in xs), Decimal("0"))
        var = ss / Decimal(n - 1)
        return var.sqrt()


def event_sharpe(net_bps: Sequence[Decimal]) -> Decimal | None:
    """Unannualised per-event Sharpe, or None if undefined (zero dispersion)."""
    if len(net_bps) < 2:
        return None
    sd = sample_stdev(net_bps)
    if sd == 0:
        return None
    with localcontext() as ctx:
        ctx.prec = _DECIMAL_PRECISION
        return mean(net_bps) / sd


def median(xs: Sequence[Decimal]) -> Decimal:
    if not xs:
        raise ValueError("median of empty sequence")
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    with localcontext() as ctx:
        ctx.prec = _DECIMAL_PRECISION
        return (s[mid - 1] + s[mid]) / Decimal("2")


# ─── Result types ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StatisticalGateResult:
    status: GateStatus
    reasons: tuple[str, ...]
    train_events: int
    oos_events: int
    oos_span_days: int
    train_sharpe: Decimal | None
    oos_sharpe: Decimal | None
    oos_rolling_failures: int


@dataclass(frozen=True)
class EconomicGateResult:
    status: GateStatus
    reasons: tuple[str, ...]
    mean_net_bps: Decimal | None
    median_net_bps: Decimal | None
    win_rate: Decimal | None
    cost_coverage: Decimal | None
    final_3mo_net_bps: Decimal | None
    final_3mo_event_count: int


@dataclass(frozen=True)
class HorizonGateResult:
    horizon_days: int
    statistical: StatisticalGateResult
    economic: EconomicGateResult
    passed: bool  # True iff both gates PASS


@dataclass(frozen=True)
class ProbeGateResult:
    per_horizon: tuple[HorizonGateResult, ...]
    probe_passed: bool  # True iff >=1 horizon passed both gates
    schema_version: str = GATES_SCHEMA_VERSION


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _event_time(fr: ForwardReturn) -> datetime:
    """Recover the event anchor time from the event_id natural key.

    event_id is 'venue:instrument:<isoformat>'. The anchor is what orders
    the series chronologically. Parsing it keeps gates independent of any
    extra timestamp plumbing on ForwardReturn.
    """
    iso = fr.event_id.split(":", 2)[2]
    ts = datetime.fromisoformat(iso)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=_UTC)
    return ts


def _split_date(times: Sequence[datetime]) -> datetime:
    start, end = min(times), max(times)
    span = end - start
    with localcontext() as ctx:
        ctx.prec = _DECIMAL_PRECISION
        frac_seconds = (Decimal(span.total_seconds()) * _SPLIT_FRACTION)
    return start + timedelta(seconds=float(frac_seconds))


# ─── Statistical gate (§5) ────────────────────────────────────────────────────


def evaluate_statistical_gate(
    returns: Sequence[ForwardReturn],
) -> StatisticalGateResult:
    if len(returns) < 2:
        return StatisticalGateResult(
            GateStatus.INSUFFICIENT_SAMPLE, ("fewer than 2 events",),
            len(returns), 0, 0, None, None, 0)

    times = [_event_time(r) for r in returns]
    split = _split_date(times)
    train = [r for r, t in zip(returns, times) if t < split]
    oos = [r for r, t in zip(returns, times) if t >= split]

    oos_times = [t for t in times if t >= split]
    oos_span_days = (
        (max(oos_times) - min(oos_times)).days if len(oos_times) >= 1 else 0
    )

    # INSUFFICIENT_SAMPLE short-circuit (before any stat check).
    sample_reasons: list[str] = []
    if len(train) < pre_lock.TRAIN_EVENTS_MIN:
        sample_reasons.append(
            f"train events {len(train)} < {pre_lock.TRAIN_EVENTS_MIN}")
    if len(oos) < pre_lock.OOS_EVENTS_MIN:
        sample_reasons.append(
            f"OOS events {len(oos)} < {pre_lock.OOS_EVENTS_MIN}")
    if oos_span_days < _OOS_MIN_DAYS:
        sample_reasons.append(
            f"OOS span {oos_span_days}d < {_OOS_MIN_DAYS}d")
    if sample_reasons:
        return StatisticalGateResult(
            GateStatus.INSUFFICIENT_SAMPLE, tuple(sample_reasons),
            len(train), len(oos), oos_span_days, None, None, 0)

    train_net = [r.net_bps for r in train]
    oos_net = [r.net_bps for r in oos]
    train_sharpe = event_sharpe(train_net)
    oos_sharpe = event_sharpe(oos_net)
    rolling_failures = _oos_rolling_failures(oos, oos_times)

    reasons: list[str] = []
    if train_sharpe is None or train_sharpe < pre_lock.TRAIN_SHARPE_MIN:
        reasons.append(
            f"train Sharpe {train_sharpe} < {pre_lock.TRAIN_SHARPE_MIN}")
    if oos_sharpe is None or oos_sharpe < pre_lock.OOS_SHARPE_MIN:
        reasons.append(
            f"OOS Sharpe {oos_sharpe} < {pre_lock.OOS_SHARPE_MIN}")
    if rolling_failures > pre_lock.OOS_ROLLING_FAILURES_MAX:
        reasons.append(
            f"OOS rolling failures {rolling_failures} > "
            f"{pre_lock.OOS_ROLLING_FAILURES_MAX}")

    status = GateStatus.PASS if not reasons else GateStatus.FAIL
    return StatisticalGateResult(
        status, tuple(reasons), len(train), len(oos), oos_span_days,
        train_sharpe, oos_sharpe, rolling_failures)


def _oos_rolling_failures(
    oos: Sequence[ForwardReturn], oos_times: Sequence[datetime]
) -> int:
    """Count 30-calendar-day OOS windows (>=3 events) with negative/undefined
    Sharpe. Windows are non-overlapping, tiled from the OOS start."""
    if not oos:
        return 0
    start = min(oos_times)
    end = max(oos_times)
    pairs = sorted(zip(oos_times, [r.net_bps for r in oos]), key=lambda p: p[0])
    failures = 0
    window_start = start
    while window_start <= end:
        window_end = window_start + timedelta(days=_ROLLING_WINDOW_DAYS)
        window_net = [net for t, net in pairs if window_start <= t < window_end]
        if len(window_net) >= _ROLLING_MIN_EVENTS:
            s = event_sharpe(window_net)
            if s is None or s < 0:
                failures += 1
        window_start = window_end
    return failures


# ─── Economic gate (§6) ───────────────────────────────────────────────────────


def evaluate_economic_gate(
    returns: Sequence[ForwardReturn],
) -> EconomicGateResult:
    if not returns:
        return EconomicGateResult(
            GateStatus.INSUFFICIENT_SAMPLE, ("no events",),
            None, None, None, None, None, 0)

    net = [r.net_bps for r in returns]
    gross = [r.gross_bps for r in returns]
    # Cost denominator: execution cost plus funding ONLY when a drag.
    cost = [
        r.execution_cost_bps - min(Decimal("0"), r.funding_pnl_bps)
        for r in returns
    ]

    mean_net = mean(net)
    median_net = median(net)
    wins = sum(1 for x in net if x > 0)
    with localcontext() as ctx:
        ctx.prec = _DECIMAL_PRECISION
        win_rate = Decimal(wins) / Decimal(len(net))
        mean_cost = mean(cost)
        coverage = (mean(gross) / mean_cost) if mean_cost > 0 else None

    final_net, final_count = _final_3mo(returns)

    reasons: list[str] = []
    if mean_net < pre_lock.ECONOMIC_MEAN_NET_BPS_MIN:
        reasons.append(
            f"mean net {mean_net}bps < {pre_lock.ECONOMIC_MEAN_NET_BPS_MIN}")
    if median_net <= pre_lock.ECONOMIC_MEDIAN_NET_BPS_MIN:
        reasons.append(
            f"median net {median_net}bps <= "
            f"{pre_lock.ECONOMIC_MEDIAN_NET_BPS_MIN}")
    if win_rate <= pre_lock.ECONOMIC_WIN_RATE_MIN:
        reasons.append(
            f"win rate {win_rate} <= {pre_lock.ECONOMIC_WIN_RATE_MIN}")
    if coverage is None or coverage < pre_lock.ECONOMIC_COST_COVERAGE_MIN:
        reasons.append(
            f"cost coverage {coverage} < {pre_lock.ECONOMIC_COST_COVERAGE_MIN}")
    if final_net is None or final_net <= pre_lock.ECONOMIC_FINAL_3MO_PNL_MIN:
        reasons.append(
            f"final-3mo net {final_net} <= "
            f"{pre_lock.ECONOMIC_FINAL_3MO_PNL_MIN}")

    status = GateStatus.PASS if not reasons else GateStatus.FAIL
    return EconomicGateResult(
        status, tuple(reasons), mean_net, median_net, win_rate, coverage,
        final_net, final_count)


def _final_3mo(
    returns: Sequence[ForwardReturn],
) -> tuple[Decimal | None, int]:
    """Sum of net_bps over events in the last 91 calendar days of the series."""
    times = [_event_time(r) for r in returns]
    end = max(times)
    cutoff = end - timedelta(days=_FINAL_WINDOW_DAYS)
    window = [r.net_bps for r, t in zip(returns, times) if t >= cutoff]
    if not window:
        return None, 0
    return sum(window, Decimal("0")), len(window)


# ─── Per-horizon orchestration ────────────────────────────────────────────────


def evaluate_gates(returns: Sequence[ForwardReturn]) -> ProbeGateResult:
    """Run §5 + §6 gates per horizon. Probe passes if any horizon clears both."""
    by_horizon: dict[int, list[ForwardReturn]] = {}
    for r in returns:
        by_horizon.setdefault(r.horizon_days, []).append(r)

    per_horizon: list[HorizonGateResult] = []
    for h in pre_lock.HORIZONS_DAYS:
        series = by_horizon.get(h, [])
        stat = evaluate_statistical_gate(series)
        econ = evaluate_economic_gate(series)
        passed = (stat.status is GateStatus.PASS
                  and econ.status is GateStatus.PASS)
        per_horizon.append(HorizonGateResult(h, stat, econ, passed))

    probe_passed = any(hr.passed for hr in per_horizon)
    return ProbeGateResult(tuple(per_horizon), probe_passed)
