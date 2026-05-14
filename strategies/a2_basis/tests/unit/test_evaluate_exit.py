"""Unit tests for A2 exit signal evaluator.

Pure-function tests with synthetic BasisObservation inputs. No DB.
No runner. No fixtures from disk.

Coverage:
  - Each A2ExitReason path
  - Priority semantics (time-forced beats basis-converged)
  - Threshold boundary behavior (exactly at, just under, just over)
  - Lineage field correctness
  - Input validation (bad threshold raises)
  - Window size variation
  - Configurable max_holding_seconds
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from strategies.a2_basis.signal.evaluate import BasisObservation
from strategies.a2_basis.signal.evaluate_exit import (
    A2ExitConfig,
    A2ExitDecision,
    A2ExitEvaluation,
    A2ExitEvaluationError,
    A2ExitReason,
    evaluate_a2_exit_signal,
)


# ─── Test helpers ───────────────────────────────────────────────────────


def _obs(
    *,
    minute_offset: int,
    perp: str,
    spot: str = "100.00",
    base_ts: datetime = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
) -> BasisObservation:
    """Construct a BasisObservation at a given minute offset."""
    return BasisObservation(
        sampled_at=base_ts + timedelta(minutes=minute_offset),
        perp_price=Decimal(perp),
        spot_price=Decimal(spot),
    )


def _stable_window(n: int = 60, perp: str = "100.00", spot: str = "100.00"):
    """Window with all observations at the same basis."""
    return [_obs(minute_offset=i, perp=perp, spot=spot) for i in range(n)]


def _converged_window(threshold_bps: Decimal):
    """Window where current basis is just under the convergence threshold.

    Most observations sit at basis=50 bps; the latest sits at basis just
    inside the convergence threshold of the rolling mean.
    """
    # 59 observations at basis=50 bps (perp 100.50, spot 100.00)
    obs_list = [_obs(minute_offset=i, perp="100.50", spot="100.00")
                for i in range(59)]
    # 1 final observation with dislocation just under threshold.
    # rolling_mean ≈ 50; target dislocation = threshold/2.
    # If threshold = 17 bps, set current = 50 - 8 = 42 (dislocation = 8).
    # We need a price that yields basis ≈ rolling_mean - small_amount.
    half_threshold = threshold_bps / Decimal(2)
    target_dislocation = half_threshold / Decimal(2)  # well under threshold
    # rolling mean of 59 observations at 50 = 50. Target basis = 50 - 4 ≈ 46.
    # bps = (perp - spot) / spot * 10000. spot = 100. So perp - spot = bps/100.
    target_basis = Decimal(50) - target_dislocation
    target_perp = Decimal("100.00") + target_basis / Decimal(100)
    obs_list.append(_obs(minute_offset=59, perp=str(target_perp), spot="100.00"))
    return obs_list


# ─── Configuration ─────────────────────────────────────────────────────


DEFAULT_THRESHOLD = Decimal("16.92")  # SOL half of 33.84 bps round-trip
ENTRY_TIME = datetime(2024, 6, 1, 12, 30, 0, tzinfo=timezone.utc)


# ═══════════════════════════════════════════════════════════════════════
# Time-forced exit
# ═══════════════════════════════════════════════════════════════════════


class TestTimeForced:
    def test_holding_at_max_returns_close_time_forced(self):
        """At exactly max_holding_seconds, CLOSE/TIME_FORCED fires."""
        config = A2ExitConfig(max_holding_seconds=14400)
        as_of = ENTRY_TIME + timedelta(seconds=14400)
        result = evaluate_a2_exit_signal(
            _stable_window(),
            convergence_threshold_bps=DEFAULT_THRESHOLD,
            entry_time=ENTRY_TIME,
            as_of=as_of,
            config=config,
        )
        assert result.decision == A2ExitDecision.CLOSE
        assert result.reason == A2ExitReason.TIME_FORCED
        assert result.holding_duration_seconds == 14400

    def test_holding_past_max_returns_close_time_forced(self):
        """Long after max, still CLOSE/TIME_FORCED."""
        config = A2ExitConfig(max_holding_seconds=14400)
        as_of = ENTRY_TIME + timedelta(seconds=20000)
        result = evaluate_a2_exit_signal(
            _stable_window(),
            convergence_threshold_bps=DEFAULT_THRESHOLD,
            entry_time=ENTRY_TIME,
            as_of=as_of,
            config=config,
        )
        assert result.decision == A2ExitDecision.CLOSE
        assert result.reason == A2ExitReason.TIME_FORCED
        assert result.holding_duration_seconds == 20000

    def test_holding_just_under_max_does_not_time_force(self):
        """At max-1 second, no time-forced exit."""
        config = A2ExitConfig(max_holding_seconds=14400)
        as_of = ENTRY_TIME + timedelta(seconds=14399)
        result = evaluate_a2_exit_signal(
            _stable_window(),
            convergence_threshold_bps=DEFAULT_THRESHOLD,
            entry_time=ENTRY_TIME,
            as_of=as_of,
            config=config,
        )
        assert result.reason != A2ExitReason.TIME_FORCED

    def test_time_forced_priority_over_basis_converged(self):
        """When BOTH conditions could fire, time_forced wins."""
        # Stable window → would be zero_stdev or basis_converged
        # AND holding > max → time_forced should win
        config = A2ExitConfig(max_holding_seconds=14400)
        as_of = ENTRY_TIME + timedelta(seconds=20000)
        result = evaluate_a2_exit_signal(
            _stable_window(),  # would otherwise be zero_stdev
            convergence_threshold_bps=DEFAULT_THRESHOLD,
            entry_time=ENTRY_TIME,
            as_of=as_of,
            config=config,
        )
        assert result.decision == A2ExitDecision.CLOSE
        assert result.reason == A2ExitReason.TIME_FORCED

    def test_time_forced_records_holding_duration(self):
        config = A2ExitConfig(max_holding_seconds=14400)
        as_of = ENTRY_TIME + timedelta(seconds=15030)
        result = evaluate_a2_exit_signal(
            _stable_window(),
            convergence_threshold_bps=DEFAULT_THRESHOLD,
            entry_time=ENTRY_TIME,
            as_of=as_of,
            config=config,
        )
        assert result.holding_duration_seconds == 15030
        assert result.max_holding_seconds == 14400


# ═══════════════════════════════════════════════════════════════════════
# Basis-converged exit
# ═══════════════════════════════════════════════════════════════════════


class TestBasisConverged:
    def test_dislocation_just_under_threshold_returns_close(self):
        observations = _converged_window(DEFAULT_THRESHOLD)
        # holding well under max; expect CLOSE/BASIS_CONVERGED
        as_of = ENTRY_TIME + timedelta(minutes=10)
        result = evaluate_a2_exit_signal(
            observations,
            convergence_threshold_bps=DEFAULT_THRESHOLD,
            entry_time=ENTRY_TIME,
            as_of=as_of,
        )
        assert result.decision == A2ExitDecision.CLOSE
        assert result.reason == A2ExitReason.BASIS_CONVERGED
        assert result.basis_dislocation_bps is not None
        assert result.basis_dislocation_bps < DEFAULT_THRESHOLD

    def test_dislocation_at_threshold_does_not_close(self):
        """Strict less-than: dislocation == threshold should HOLD.

        Uses exact Decimal arithmetic with a small window to avoid
        precision drift. Window is 4 obs at basis=100 bps and 1 obs at
        basis=75 bps. Rolling mean = (4*100 + 75)/5 = 95 bps exactly.
        Dislocation = |75 - 95| = 20 bps exactly. With threshold = 20,
        strict less-than means HOLD/STILL_DISLOCATED.
        """
        threshold = Decimal(20)
        config = A2ExitConfig(min_lookback=5, window_size=5)
        obs_list = [_obs(minute_offset=i, perp="101.00", spot="100.00")
                    for i in range(4)]
        obs_list.append(_obs(minute_offset=4, perp="100.75", spot="100.00"))
        as_of = obs_list[-1].sampled_at + timedelta(seconds=1)
        result = evaluate_a2_exit_signal(
            obs_list,
            convergence_threshold_bps=threshold,
            entry_time=obs_list[0].sampled_at,
            as_of=as_of,
            config=config,
        )
        assert result.basis_dislocation_bps == Decimal(20)
        assert result.decision == A2ExitDecision.HOLD
        assert result.reason == A2ExitReason.STILL_DISLOCATED

    def test_converged_records_full_lineage(self):
        observations = _converged_window(DEFAULT_THRESHOLD)
        as_of = ENTRY_TIME + timedelta(minutes=10)
        result = evaluate_a2_exit_signal(
            observations,
            convergence_threshold_bps=DEFAULT_THRESHOLD,
            entry_time=ENTRY_TIME,
            as_of=as_of,
        )
        assert result.current_basis_bps is not None
        assert result.rolling_mean_basis_bps is not None
        assert result.basis_dislocation_bps is not None
        assert result.convergence_threshold_bps == DEFAULT_THRESHOLD
        assert result.decision == A2ExitDecision.CLOSE


# ═══════════════════════════════════════════════════════════════════════
# Still-dislocated HOLD
# ═══════════════════════════════════════════════════════════════════════


class TestStillDislocated:
    def test_large_dislocation_returns_hold_still_dislocated(self):
        # 59 obs at basis=0; latest at basis=85 bps
        obs_list = [_obs(minute_offset=i, perp="100.00", spot="100.00")
                    for i in range(59)]
        obs_list.append(_obs(minute_offset=59, perp="100.85", spot="100.00"))
        as_of = ENTRY_TIME + timedelta(minutes=10)
        result = evaluate_a2_exit_signal(
            obs_list,
            convergence_threshold_bps=DEFAULT_THRESHOLD,
            entry_time=ENTRY_TIME,
            as_of=as_of,
        )
        assert result.decision == A2ExitDecision.HOLD
        assert result.reason == A2ExitReason.STILL_DISLOCATED
        # Dislocation should be roughly 85 - (85/60) ≈ 83.5 bps
        assert result.basis_dislocation_bps is not None
        assert result.basis_dislocation_bps > DEFAULT_THRESHOLD


# ═══════════════════════════════════════════════════════════════════════
# Diagnostic HOLD reasons
# ═══════════════════════════════════════════════════════════════════════


class TestInsufficientLookback:
    def test_small_window_returns_hold_insufficient_lookback(self):
        # min_lookback default = 30; pass only 10 observations
        observations = _stable_window(n=10)
        as_of = ENTRY_TIME + timedelta(minutes=10)
        result = evaluate_a2_exit_signal(
            observations,
            convergence_threshold_bps=DEFAULT_THRESHOLD,
            entry_time=ENTRY_TIME,
            as_of=as_of,
        )
        assert result.decision == A2ExitDecision.HOLD
        assert result.reason == A2ExitReason.INSUFFICIENT_LOOKBACK
        assert result.current_basis_bps is None
        assert result.rolling_mean_basis_bps is None
        assert result.basis_dislocation_bps is None

    def test_empty_window_returns_hold_insufficient_lookback(self):
        as_of = ENTRY_TIME + timedelta(minutes=10)
        result = evaluate_a2_exit_signal(
            [],
            convergence_threshold_bps=DEFAULT_THRESHOLD,
            entry_time=ENTRY_TIME,
            as_of=as_of,
        )
        assert result.decision == A2ExitDecision.HOLD
        assert result.reason == A2ExitReason.INSUFFICIENT_LOOKBACK

    def test_min_lookback_configurable(self):
        config = A2ExitConfig(min_lookback=5)
        observations = _stable_window(n=10)
        as_of = ENTRY_TIME + timedelta(minutes=10)
        result = evaluate_a2_exit_signal(
            observations,
            convergence_threshold_bps=DEFAULT_THRESHOLD,
            entry_time=ENTRY_TIME,
            as_of=as_of,
            config=config,
        )
        # 10 >= 5: not insufficient_lookback. Stable window → zero_stdev.
        assert result.reason != A2ExitReason.INSUFFICIENT_LOOKBACK


class TestStaleWindow:
    def test_stale_latest_obs_returns_hold_stale_window(self):
        # Latest obs at minute 0; as_of much later than staleness allows
        observations = _stable_window(n=60)
        # observations[-1].sampled_at is base + 59 minutes
        # default staleness = 600 seconds = 10 min
        as_of = observations[-1].sampled_at + timedelta(seconds=700)
        result = evaluate_a2_exit_signal(
            observations,
            convergence_threshold_bps=DEFAULT_THRESHOLD,
            entry_time=observations[0].sampled_at,
            as_of=as_of,
        )
        assert result.decision == A2ExitDecision.HOLD
        assert result.reason == A2ExitReason.STALE_WINDOW

    def test_staleness_configurable(self):
        config = A2ExitConfig(staleness_seconds=30)
        observations = _stable_window(n=60)
        as_of = observations[-1].sampled_at + timedelta(seconds=60)
        result = evaluate_a2_exit_signal(
            observations,
            convergence_threshold_bps=DEFAULT_THRESHOLD,
            entry_time=observations[0].sampled_at,
            as_of=as_of,
            config=config,
        )
        assert result.reason == A2ExitReason.STALE_WINDOW


class TestZeroStdev:
    def test_constant_basis_returns_hold_zero_stdev(self):
        observations = _stable_window(n=60, perp="100.00", spot="100.00")
        as_of = observations[-1].sampled_at + timedelta(seconds=1)
        result = evaluate_a2_exit_signal(
            observations,
            convergence_threshold_bps=DEFAULT_THRESHOLD,
            entry_time=observations[0].sampled_at,
            as_of=as_of,
        )
        assert result.decision == A2ExitDecision.HOLD
        assert result.reason == A2ExitReason.ZERO_OR_NEAR_ZERO_STDEV
        # rolling_mean is computable (all values equal); dislocation not
        assert result.rolling_mean_basis_bps is not None
        assert result.basis_dislocation_bps is None


# ═══════════════════════════════════════════════════════════════════════
# Input validation
# ═══════════════════════════════════════════════════════════════════════


class TestInputValidation:
    def test_zero_threshold_raises(self):
        observations = _stable_window()
        as_of = observations[-1].sampled_at + timedelta(seconds=1)
        with pytest.raises(A2ExitEvaluationError, match="must be positive"):
            evaluate_a2_exit_signal(
                observations,
                convergence_threshold_bps=Decimal(0),
                entry_time=observations[0].sampled_at,
                as_of=as_of,
            )

    def test_negative_threshold_raises(self):
        observations = _stable_window()
        as_of = observations[-1].sampled_at + timedelta(seconds=1)
        with pytest.raises(A2ExitEvaluationError, match="must be positive"):
            evaluate_a2_exit_signal(
                observations,
                convergence_threshold_bps=Decimal("-5"),
                entry_time=observations[0].sampled_at,
                as_of=as_of,
            )


# ═══════════════════════════════════════════════════════════════════════
# Lineage completeness
# ═══════════════════════════════════════════════════════════════════════


class TestLineage:
    def test_all_required_fields_present(self):
        """Reviewer-required lineage fields are populated on every path."""
        observations = _stable_window()
        as_of = observations[-1].sampled_at + timedelta(seconds=1)
        result = evaluate_a2_exit_signal(
            observations,
            convergence_threshold_bps=DEFAULT_THRESHOLD,
            entry_time=observations[0].sampled_at,
            as_of=as_of,
        )
        # convergence_threshold_bps always present
        assert result.convergence_threshold_bps == DEFAULT_THRESHOLD
        # max_holding_seconds always present
        assert result.max_holding_seconds == A2ExitConfig().max_holding_seconds
        # holding_duration_seconds always present
        assert isinstance(result.holding_duration_seconds, int)
        # decision and reason always present
        assert isinstance(result.decision, A2ExitDecision)
        assert isinstance(result.reason, A2ExitReason)

    def test_close_paths_record_convergence_threshold(self):
        """Even in time-forced path, convergence_threshold_bps is recorded."""
        config = A2ExitConfig(max_holding_seconds=1)
        observations = _stable_window()
        as_of = ENTRY_TIME + timedelta(seconds=100)
        result = evaluate_a2_exit_signal(
            observations,
            convergence_threshold_bps=DEFAULT_THRESHOLD,
            entry_time=ENTRY_TIME,
            as_of=as_of,
            config=config,
        )
        assert result.reason == A2ExitReason.TIME_FORCED
        assert result.convergence_threshold_bps == DEFAULT_THRESHOLD


# ═══════════════════════════════════════════════════════════════════════
# Time-forced opportunistic lineage
# ═══════════════════════════════════════════════════════════════════════


class TestTimeForcedLineage:
    def test_time_forced_with_full_window_records_stats(self):
        """When time_forced fires with a full window, the audit record
        includes current_basis_bps + rolling_mean + dislocation if
        computable."""
        # Construct a window with enough observations + some dislocation
        obs_list = [_obs(minute_offset=i, perp="100.00", spot="100.00")
                    for i in range(59)]
        obs_list.append(_obs(minute_offset=59, perp="100.50", spot="100.00"))
        config = A2ExitConfig(max_holding_seconds=10)
        as_of = ENTRY_TIME + timedelta(seconds=100)
        result = evaluate_a2_exit_signal(
            obs_list,
            convergence_threshold_bps=DEFAULT_THRESHOLD,
            entry_time=ENTRY_TIME,
            as_of=as_of,
            config=config,
        )
        assert result.reason == A2ExitReason.TIME_FORCED
        # Opportunistic stats present
        assert result.current_basis_bps is not None
        assert result.rolling_mean_basis_bps is not None
        assert result.basis_dislocation_bps is not None

    def test_time_forced_with_small_window_omits_rolling_stats(self):
        """If time-forced fires with too-small window, rolling_mean stays
        None but current_basis is still recorded."""
        config = A2ExitConfig(max_holding_seconds=10, min_lookback=30)
        observations = _stable_window(n=5)
        as_of = ENTRY_TIME + timedelta(seconds=100)
        result = evaluate_a2_exit_signal(
            observations,
            convergence_threshold_bps=DEFAULT_THRESHOLD,
            entry_time=ENTRY_TIME,
            as_of=as_of,
            config=config,
        )
        assert result.reason == A2ExitReason.TIME_FORCED
        assert result.current_basis_bps is not None
        assert result.rolling_mean_basis_bps is None
        assert result.basis_dislocation_bps is None

    def test_time_forced_with_empty_window(self):
        config = A2ExitConfig(max_holding_seconds=10)
        as_of = ENTRY_TIME + timedelta(seconds=100)
        result = evaluate_a2_exit_signal(
            [],
            convergence_threshold_bps=DEFAULT_THRESHOLD,
            entry_time=ENTRY_TIME,
            as_of=as_of,
            config=config,
        )
        assert result.reason == A2ExitReason.TIME_FORCED
        assert result.current_basis_bps is None
        assert result.rolling_mean_basis_bps is None
        assert result.basis_dislocation_bps is None
