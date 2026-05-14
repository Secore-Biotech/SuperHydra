"""A2 exit signal evaluator.

Day 28b.1 deliverable. Pure function evaluating whether an open A2
position should close at a given observation.

Per Day 28b.2 reviewer lock: hybrid trigger.

  Primary: basis dislocation has converged below half-threshold.
      |current_basis - rolling_mean| < convergence_threshold_bps

  Secondary: time-forced exit after max_holding_seconds.

Priority: time-forced takes precedence over basis-converged when both
conditions hold simultaneously. In practice these are mutually exclusive
at any single observation (the runner checks every observation, so
basis_converged fires the moment dislocation drops below threshold; by
the time time-forced would also fire, the position is already closed).
The priority is a defensive belt-and-braces: if the runner is somehow
not evaluating each observation, the time cap still trips.

The evaluator is stateless and pure. It takes the rolling window,
the configured threshold, the position's entry time, and the current
evaluation time. It returns a structured A2ExitEvaluation carrying
full lineage so the runner can persist exit decisions with audit
information in paper.fills metadata.

This module does NOT compute realized P&L; that is the runner's
responsibility per Day 28b.2 scope.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, Sequence

from strategies.a2_basis.signal.evaluate import BasisObservation


# Effective-zero threshold for stdev (degenerate window detection).
# Same value the entry evaluator uses; kept independent so future tuning
# can diverge without forcing entry/exit coupling.
_STDEV_EPSILON = Decimal("0.0001")


class A2ExitDecision(Enum):
    """Whether the open position should close at this observation."""
    HOLD = "HOLD"
    CLOSE = "CLOSE"


class A2ExitReason(Enum):
    """Why the evaluator returned its decision.

    CLOSE reasons:
        BASIS_CONVERGED: |current - rolling_mean| < convergence_threshold
        TIME_FORCED:     holding_duration >= max_holding_seconds

    HOLD reasons:
        STILL_DISLOCATED:          dislocation present but above threshold
        INSUFFICIENT_LOOKBACK:     window smaller than min_lookback
        STALE_WINDOW:              latest observation too old vs as_of
        ZERO_OR_NEAR_ZERO_STDEV:   degenerate window; defensive HOLD
    """
    # CLOSE reasons
    BASIS_CONVERGED = "basis_converged"
    TIME_FORCED = "time_forced"
    # HOLD reasons
    STILL_DISLOCATED = "still_dislocated"
    INSUFFICIENT_LOOKBACK = "insufficient_lookback"
    STALE_WINDOW = "stale_window"
    ZERO_OR_NEAR_ZERO_STDEV = "zero_or_near_zero_stdev"


@dataclass(frozen=True)
class A2ExitConfig:
    """Operator-configurable exit-evaluation parameters.

    window_size: how many observations the rolling stats use (matches
        entry evaluator default for consistency).
    min_lookback: minimum observations required before evaluating; below
        this returns HOLD/INSUFFICIENT_LOOKBACK.
    staleness_seconds: latest observation may be at most this far behind
        as_of; otherwise HOLD/STALE_WINDOW.
    max_holding_seconds: time-forced exit threshold (4h = 14400s default
        per Day 28b.2 reviewer lock).
    """
    window_size: int = 60
    min_lookback: int = 30
    staleness_seconds: int = 600
    max_holding_seconds: int = 14400  # 4 hours


@dataclass(frozen=True)
class A2ExitEvaluation:
    """Full lineage of one exit-evaluation call.

    Required reviewer fields:
        current_basis_bps:        latest observation basis (None if window empty)
        rolling_mean_basis_bps:   mean of basis across window (None if not computed)
        basis_dislocation_bps:    |current - rolling_mean| (None if not computed)
        convergence_threshold_bps: the threshold compared against (always set)
        holding_duration_seconds: as_of - entry_time, in seconds
        max_holding_seconds:      time-forced threshold from config
        decision:                 HOLD or CLOSE
        reason:                   one of A2ExitReason values
    """
    current_basis_bps: Optional[Decimal]
    rolling_mean_basis_bps: Optional[Decimal]
    basis_dislocation_bps: Optional[Decimal]
    convergence_threshold_bps: Decimal
    holding_duration_seconds: int
    max_holding_seconds: int
    decision: A2ExitDecision
    reason: A2ExitReason


class A2ExitEvaluationError(Exception):
    """Raised on caller-side input errors (bad threshold, etc.)."""


def _rolling_stats(
    observations: Sequence[BasisObservation],
) -> tuple[Optional[Decimal], Optional[Decimal]]:
    """Compute (mean, stdev) of basis_bps across the window.

    Returns (None, None) for empty input. Returns (mean, 0) for
    constant input; the caller decides whether to treat zero stdev
    as a degenerate-window signal.
    """
    n = len(observations)
    if n == 0:
        return None, None

    total = sum((obs.basis_bps for obs in observations), Decimal(0))
    mean = total / Decimal(n)

    if n == 1:
        return mean, Decimal(0)

    variance_total = Decimal(0)
    for obs in observations:
        diff = obs.basis_bps - mean
        variance_total += diff * diff
    # Sample stdev (n-1 denominator) — matches Decimal-friendly math
    # without sqrt; we'll take sqrt below.
    variance = variance_total / Decimal(n - 1)
    # Decimal lacks built-in sqrt; use float math then back to Decimal.
    # Precision is fine for "is this near zero?" checks.
    stdev = Decimal(str(float(variance) ** 0.5))
    return mean, stdev


def evaluate_a2_exit_signal(
    observations: Sequence[BasisObservation],
    *,
    convergence_threshold_bps: Decimal,
    entry_time: datetime,
    as_of: datetime,
    config: A2ExitConfig = A2ExitConfig(),
) -> A2ExitEvaluation:
    """Evaluate whether an open A2 position should close.

    Decision flow (early returns):
      1. Validate inputs (raise on bad threshold).
      2. Compute holding_duration_seconds.
      3. If holding_duration >= max_holding_seconds → CLOSE/TIME_FORCED.
         (Time-forced has priority by design; see module docstring.)
      4. If len(observations) < min_lookback → HOLD/INSUFFICIENT_LOOKBACK.
      5. If latest observation older than staleness → HOLD/STALE_WINDOW.
      6. Compute (rolling_mean, stdev).
      7. If stdev < _STDEV_EPSILON → HOLD/ZERO_OR_NEAR_ZERO_STDEV.
      8. Compute dislocation = |current_basis - rolling_mean|.
      9. If dislocation < convergence_threshold_bps → CLOSE/BASIS_CONVERGED.
     10. Otherwise → HOLD/STILL_DISLOCATED.

    All paths return an A2ExitEvaluation with as much lineage as could
    be computed at that point. Fields not yet computable are None.
    """
    if convergence_threshold_bps <= 0:
        raise A2ExitEvaluationError(
            f"convergence_threshold_bps must be positive, "
            f"got {convergence_threshold_bps}"
        )

    holding_duration = int((as_of - entry_time).total_seconds())

    # Step 3: time-forced takes priority.
    if holding_duration >= config.max_holding_seconds:
        # Compute basis stats opportunistically for the audit record.
        cb: Optional[Decimal] = None
        rm: Optional[Decimal] = None
        dis: Optional[Decimal] = None
        if observations:
            cb = observations[-1].basis_bps
            if len(observations) >= config.min_lookback:
                rm, _ = _rolling_stats(observations)
                if rm is not None:
                    dis = abs(cb - rm)
        return A2ExitEvaluation(
            current_basis_bps=cb,
            rolling_mean_basis_bps=rm,
            basis_dislocation_bps=dis,
            convergence_threshold_bps=convergence_threshold_bps,
            holding_duration_seconds=holding_duration,
            max_holding_seconds=config.max_holding_seconds,
            decision=A2ExitDecision.CLOSE,
            reason=A2ExitReason.TIME_FORCED,
        )

    # Step 4: insufficient lookback.
    if len(observations) < config.min_lookback:
        return A2ExitEvaluation(
            current_basis_bps=None,
            rolling_mean_basis_bps=None,
            basis_dislocation_bps=None,
            convergence_threshold_bps=convergence_threshold_bps,
            holding_duration_seconds=holding_duration,
            max_holding_seconds=config.max_holding_seconds,
            decision=A2ExitDecision.HOLD,
            reason=A2ExitReason.INSUFFICIENT_LOOKBACK,
        )

    latest_obs = observations[-1]

    # Step 5: stale window.
    staleness = (as_of - latest_obs.sampled_at).total_seconds()
    if staleness > config.staleness_seconds:
        return A2ExitEvaluation(
            current_basis_bps=latest_obs.basis_bps,
            rolling_mean_basis_bps=None,
            basis_dislocation_bps=None,
            convergence_threshold_bps=convergence_threshold_bps,
            holding_duration_seconds=holding_duration,
            max_holding_seconds=config.max_holding_seconds,
            decision=A2ExitDecision.HOLD,
            reason=A2ExitReason.STALE_WINDOW,
        )

    # Step 6: compute rolling stats.
    rolling_mean, stdev = _rolling_stats(observations)

    # Step 7: degenerate-window check.
    if stdev is None or stdev < _STDEV_EPSILON:
        return A2ExitEvaluation(
            current_basis_bps=latest_obs.basis_bps,
            rolling_mean_basis_bps=rolling_mean,
            basis_dislocation_bps=None,
            convergence_threshold_bps=convergence_threshold_bps,
            holding_duration_seconds=holding_duration,
            max_holding_seconds=config.max_holding_seconds,
            decision=A2ExitDecision.HOLD,
            reason=A2ExitReason.ZERO_OR_NEAR_ZERO_STDEV,
        )

    current_basis = latest_obs.basis_bps
    dislocation = abs(current_basis - rolling_mean)

    # Step 9: basis converged → CLOSE.
    if dislocation < convergence_threshold_bps:
        return A2ExitEvaluation(
            current_basis_bps=current_basis,
            rolling_mean_basis_bps=rolling_mean,
            basis_dislocation_bps=dislocation,
            convergence_threshold_bps=convergence_threshold_bps,
            holding_duration_seconds=holding_duration,
            max_holding_seconds=config.max_holding_seconds,
            decision=A2ExitDecision.CLOSE,
            reason=A2ExitReason.BASIS_CONVERGED,
        )

    # Step 10: still dislocated → HOLD.
    return A2ExitEvaluation(
        current_basis_bps=current_basis,
        rolling_mean_basis_bps=rolling_mean,
        basis_dislocation_bps=dislocation,
        convergence_threshold_bps=convergence_threshold_bps,
        holding_duration_seconds=holding_duration,
        max_holding_seconds=config.max_holding_seconds,
        decision=A2ExitDecision.HOLD,
        reason=A2ExitReason.STILL_DISLOCATED,
    )
