"""A2 z-score signal evaluator.

Day 23 deliverable: pure-function evaluator that takes a rolling window
of BasisObservations and produces an A2SignalEvaluation with decision
and full lineage.

Per Day 23 reviewer-locked decisions:

  23.1 - Window length operator-configurable; default 60 samples
  23.2 - z-threshold 2.0 default; AND cost-anchored using basis
         DISLOCATION (current - rolling_mean), not raw current basis
  23.3 - A2-specific enum (no A1 import)
  23.5 - Staleness configurable, default 10 minutes
  23.6 - min_lookback 30 default, raise on fewer

Pure function: same inputs produce same outputs. No I/O, no clock, no DB.
Runner (Day 24) is responsible for sampling cadence (23.4); the
evaluator is cadence-agnostic.

Signal direction:
  - Positive basis dislocation (current basis > rolling mean): perp
    is at premium relative to recent regime. Expected convergence DOWN.
    Decision: SHORT_PERP_LONG_SPOT (collect convergence).
  - Negative basis dislocation: perp is at discount. Expected
    convergence UP. Decision: LONG_PERP_SHORT_SPOT.

The cost-anchoring uses dislocation magnitude, not raw basis level.
Reviewer amendment to 23.2: A2 is a dislocation strategy, not an
absolute-level strategy. A persistent basis at 40 bps is not
tradable if 40 bps is the regime's normal level.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Final


A2_SIGNAL_EVALUATION_SCHEMA_VERSION: Final[str] = "a2_signal_evaluation.v0"


# Errors


class A2SignalEvaluationError(Exception):
    """Raised when evaluator inputs are structurally invalid."""


# Sample type


@dataclass(frozen=True)
class BasisObservation:
    """One sample of perp+spot prices.

    basis_bps is derived (property), not stored:
        basis_bps = (perp_price - spot_price) / spot_price * 10000

    Caller is responsible for ensuring perp_price and spot_price were
    sampled close enough together to be considered simultaneous.
    """

    sampled_at: datetime
    perp_price: Decimal
    spot_price: Decimal

    def __post_init__(self) -> None:
        if self.sampled_at.tzinfo is None:
            raise A2SignalEvaluationError("sampled_at must be timezone-aware")
        if not isinstance(self.perp_price, Decimal):
            raise A2SignalEvaluationError(
                f"perp_price must be Decimal, got {type(self.perp_price).__name__}"
            )
        if not isinstance(self.spot_price, Decimal):
            raise A2SignalEvaluationError(
                f"spot_price must be Decimal, got {type(self.spot_price).__name__}"
            )
        if self.perp_price <= 0:
            raise A2SignalEvaluationError(
                f"perp_price must be positive, got {self.perp_price}"
            )
        if self.spot_price <= 0:
            raise A2SignalEvaluationError(
                f"spot_price must be positive, got {self.spot_price}"
            )

    @property
    def basis_bps(self) -> Decimal:
        return (self.perp_price - self.spot_price) / self.spot_price * Decimal("10000")


# Decision enum


class A2SignalDecision(str, Enum):
    """A2-specific decision enum per Day 21.3 amendment."""

    FLAT = "FLAT"
    SHORT_PERP_LONG_SPOT = "SHORT_PERP_LONG_SPOT"
    LONG_PERP_SHORT_SPOT = "LONG_PERP_SHORT_SPOT"


# Flat reasons (per reviewer-locked taxonomy)


A2_FLAT_REASON_INSUFFICIENT_LOOKBACK: Final[str] = "insufficient_lookback"
A2_FLAT_REASON_STALE_WINDOW: Final[str] = "stale_window"
A2_FLAT_REASON_ZERO_OR_NEAR_ZERO_STDEV: Final[str] = "zero_or_near_zero_stdev"
A2_FLAT_REASON_Z_BELOW_THRESHOLD: Final[str] = "z_below_threshold"
A2_FLAT_REASON_COST_NOT_CLEARED: Final[str] = "cost_not_cleared"

A2_FLAT_REASONS: Final[frozenset[str]] = frozenset({
    A2_FLAT_REASON_INSUFFICIENT_LOOKBACK,
    A2_FLAT_REASON_STALE_WINDOW,
    A2_FLAT_REASON_ZERO_OR_NEAR_ZERO_STDEV,
    A2_FLAT_REASON_Z_BELOW_THRESHOLD,
    A2_FLAT_REASON_COST_NOT_CLEARED,
})


# Config


@dataclass(frozen=True)
class A2SignalConfig:
    """Operator-configurable parameters for evaluate_a2_signal.

    Defaults from Day 23 reviewer-locked decisions.
    """

    window_size: int = 60
    min_lookback: int = 30
    max_staleness_seconds: int = 600
    z_threshold: Decimal = Decimal("2.0")
    near_zero_stdev_threshold_bps: Decimal = Decimal("0.01")

    def __post_init__(self) -> None:
        if self.window_size < 1:
            raise A2SignalEvaluationError(
                f"window_size must be >= 1, got {self.window_size}"
            )
        if self.min_lookback < 1:
            raise A2SignalEvaluationError(
                f"min_lookback must be >= 1, got {self.min_lookback}"
            )
        if self.min_lookback > self.window_size:
            raise A2SignalEvaluationError(
                f"min_lookback ({self.min_lookback}) cannot exceed "
                f"window_size ({self.window_size})"
            )
        if self.max_staleness_seconds < 0:
            raise A2SignalEvaluationError(
                f"max_staleness_seconds must be >= 0, "
                f"got {self.max_staleness_seconds}"
            )
        if not isinstance(self.z_threshold, Decimal):
            raise TypeError(
                f"z_threshold must be Decimal, "
                f"got {type(self.z_threshold).__name__}"
            )
        if self.z_threshold < 0:
            raise A2SignalEvaluationError(
                f"z_threshold must be >= 0, got {self.z_threshold}"
            )
        if not isinstance(self.near_zero_stdev_threshold_bps, Decimal):
            raise TypeError(
                f"near_zero_stdev_threshold_bps must be Decimal, "
                f"got {type(self.near_zero_stdev_threshold_bps).__name__}"
            )
        if self.near_zero_stdev_threshold_bps < 0:
            raise A2SignalEvaluationError(
                f"near_zero_stdev_threshold_bps must be >= 0, "
                f"got {self.near_zero_stdev_threshold_bps}"
            )


# Evaluation output


@dataclass(frozen=True)
class A2SignalEvaluation:
    """Full lineage of one A2 signal evaluation."""

    decision: A2SignalDecision
    reason: str | None

    n_samples: int
    window_start: datetime | None
    window_end: datetime | None

    current_basis_bps: Decimal | None

    rolling_mean_basis_bps: Decimal | None
    rolling_stdev_basis_bps: Decimal | None
    basis_dislocation_bps: Decimal | None
    z_score: Decimal | None

    cost_threshold_bps: Decimal
    z_threshold: Decimal

    schema_version: str = A2_SIGNAL_EVALUATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.decision == A2SignalDecision.FLAT:
            if self.reason is None:
                raise A2SignalEvaluationError(
                    "FLAT decision requires reason"
                )
            if self.reason not in A2_FLAT_REASONS:
                raise A2SignalEvaluationError(
                    f"reason {self.reason!r} not in "
                    f"{sorted(A2_FLAT_REASONS)}"
                )
        else:
            if self.reason is not None:
                raise A2SignalEvaluationError(
                    f"non-FLAT decision must have reason=None, "
                    f"got {self.reason!r}"
                )


# The evaluator


def evaluate_a2_signal(
    window: list[BasisObservation],
    cost_threshold_bps: Decimal,
    *,
    as_of: datetime,
    config: A2SignalConfig | None = None,
) -> A2SignalEvaluation:
    """Evaluate the A2 z-score signal.

    Decision sequence:
      1. Insufficient lookback -> FLAT
      2. Out-of-order or look-ahead -> raise
      3. Stale window -> FLAT
      4. Near-zero stdev -> FLAT
      5. |z_score| < z_threshold -> FLAT
      6. |dislocation| <= cost_threshold -> FLAT (cost-anchored, amendment)
      7. Else -> non-FLAT decision based on sign of dislocation
    """
    if config is None:
        config = A2SignalConfig()

    if not isinstance(cost_threshold_bps, Decimal):
        raise TypeError(
            f"cost_threshold_bps must be Decimal, "
            f"got {type(cost_threshold_bps).__name__}"
        )
    if cost_threshold_bps < 0:
        raise A2SignalEvaluationError(
            f"cost_threshold_bps must be >= 0, got {cost_threshold_bps}"
        )
    if as_of.tzinfo is None:
        raise A2SignalEvaluationError("as_of must be timezone-aware")

    n_samples = len(window)

    # Step 1: insufficient lookback
    if n_samples < config.min_lookback:
        return A2SignalEvaluation(
            decision=A2SignalDecision.FLAT,
            reason=A2_FLAT_REASON_INSUFFICIENT_LOOKBACK,
            n_samples=n_samples,
            window_start=window[0].sampled_at if n_samples > 0 else None,
            window_end=window[-1].sampled_at if n_samples > 0 else None,
            current_basis_bps=window[-1].basis_bps if n_samples > 0 else None,
            rolling_mean_basis_bps=None,
            rolling_stdev_basis_bps=None,
            basis_dislocation_bps=None,
            z_score=None,
            cost_threshold_bps=cost_threshold_bps,
            z_threshold=config.z_threshold,
        )

    # Step 2: structural validation
    times = [obs.sampled_at for obs in window]
    if times != sorted(times):
        raise A2SignalEvaluationError(
            "window must be sorted ascending by sampled_at"
        )
    if window[-1].sampled_at >= as_of:
        raise A2SignalEvaluationError(
            f"as_of ({as_of}) must be strictly after latest sample "
            f"({window[-1].sampled_at}); look-ahead is forbidden"
        )

    # Step 3: stale window
    latest_sample_age = (as_of - window[-1].sampled_at).total_seconds()
    if latest_sample_age > config.max_staleness_seconds:
        return A2SignalEvaluation(
            decision=A2SignalDecision.FLAT,
            reason=A2_FLAT_REASON_STALE_WINDOW,
            n_samples=n_samples,
            window_start=window[0].sampled_at,
            window_end=window[-1].sampled_at,
            current_basis_bps=window[-1].basis_bps,
            rolling_mean_basis_bps=None,
            rolling_stdev_basis_bps=None,
            basis_dislocation_bps=None,
            z_score=None,
            cost_threshold_bps=cost_threshold_bps,
            z_threshold=config.z_threshold,
        )

    # Step 4: compute rolling stats
    basis_values = [obs.basis_bps for obs in window]
    rolling_mean = statistics.mean(basis_values)
    if n_samples > 1:
        rolling_stdev = statistics.stdev(basis_values)
    else:
        rolling_stdev = Decimal("0")
    current_basis = window[-1].basis_bps
    basis_dislocation = current_basis - rolling_mean

    # Step 5: near-zero stdev
    if rolling_stdev <= config.near_zero_stdev_threshold_bps:
        return A2SignalEvaluation(
            decision=A2SignalDecision.FLAT,
            reason=A2_FLAT_REASON_ZERO_OR_NEAR_ZERO_STDEV,
            n_samples=n_samples,
            window_start=window[0].sampled_at,
            window_end=window[-1].sampled_at,
            current_basis_bps=current_basis,
            rolling_mean_basis_bps=rolling_mean,
            rolling_stdev_basis_bps=rolling_stdev,
            basis_dislocation_bps=basis_dislocation,
            z_score=None,
            cost_threshold_bps=cost_threshold_bps,
            z_threshold=config.z_threshold,
        )

    z_score = basis_dislocation / rolling_stdev

    # Step 6: z below threshold
    if abs(z_score) < config.z_threshold:
        return A2SignalEvaluation(
            decision=A2SignalDecision.FLAT,
            reason=A2_FLAT_REASON_Z_BELOW_THRESHOLD,
            n_samples=n_samples,
            window_start=window[0].sampled_at,
            window_end=window[-1].sampled_at,
            current_basis_bps=current_basis,
            rolling_mean_basis_bps=rolling_mean,
            rolling_stdev_basis_bps=rolling_stdev,
            basis_dislocation_bps=basis_dislocation,
            z_score=z_score,
            cost_threshold_bps=cost_threshold_bps,
            z_threshold=config.z_threshold,
        )

    # Step 7: cost-anchoring (reviewer amendment)
    if abs(basis_dislocation) <= cost_threshold_bps:
        return A2SignalEvaluation(
            decision=A2SignalDecision.FLAT,
            reason=A2_FLAT_REASON_COST_NOT_CLEARED,
            n_samples=n_samples,
            window_start=window[0].sampled_at,
            window_end=window[-1].sampled_at,
            current_basis_bps=current_basis,
            rolling_mean_basis_bps=rolling_mean,
            rolling_stdev_basis_bps=rolling_stdev,
            basis_dislocation_bps=basis_dislocation,
            z_score=z_score,
            cost_threshold_bps=cost_threshold_bps,
            z_threshold=config.z_threshold,
        )

    # Step 8: directional decision
    if basis_dislocation > 0:
        decision = A2SignalDecision.SHORT_PERP_LONG_SPOT
    else:
        decision = A2SignalDecision.LONG_PERP_SHORT_SPOT

    return A2SignalEvaluation(
        decision=decision,
        reason=None,
        n_samples=n_samples,
        window_start=window[0].sampled_at,
        window_end=window[-1].sampled_at,
        current_basis_bps=current_basis,
        rolling_mean_basis_bps=rolling_mean,
        rolling_stdev_basis_bps=rolling_stdev,
        basis_dislocation_bps=basis_dislocation,
        z_score=z_score,
        cost_threshold_bps=cost_threshold_bps,
        z_threshold=config.z_threshold,
    )
