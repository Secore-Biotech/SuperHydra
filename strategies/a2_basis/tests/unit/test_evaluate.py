"""Unit tests for evaluate_a2_signal + related types."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from strategies.a2_basis.signal.evaluate import (
    A2_FLAT_REASON_COST_NOT_CLEARED,
    A2_FLAT_REASON_INSUFFICIENT_LOOKBACK,
    A2_FLAT_REASON_STALE_WINDOW,
    A2_FLAT_REASON_Z_BELOW_THRESHOLD,
    A2_FLAT_REASON_ZERO_OR_NEAR_ZERO_STDEV,
    A2_SIGNAL_EVALUATION_SCHEMA_VERSION,
    A2SignalConfig,
    A2SignalDecision,
    A2SignalEvaluation,
    A2SignalEvaluationError,
    BasisObservation,
    evaluate_a2_signal,
)


def _ts(seconds: int = 0) -> datetime:
    return datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc) + timedelta(
        seconds=seconds
    )


def _obs(basis_bps: Decimal, *, t: datetime,
         spot: Decimal = Decimal("100.00")) -> BasisObservation:
    perp = spot + spot * basis_bps / Decimal("10000")
    return BasisObservation(sampled_at=t, perp_price=perp, spot_price=spot)


def _build_window(
    basis_values: list[Decimal],
    *,
    start_seconds: int = 0,
    interval_seconds: int = 60,
) -> list[BasisObservation]:
    return [
        _obs(b, t=_ts(start_seconds + i * interval_seconds))
        for i, b in enumerate(basis_values)
    ]


class TestBasisObservation:
    def test_basis_bps_computed_positive(self):
        obs = _obs(Decimal("10"), t=_ts())
        assert obs.basis_bps == Decimal("10")

    def test_basis_bps_computed_negative(self):
        obs = _obs(Decimal("-15"), t=_ts())
        assert obs.basis_bps == Decimal("-15")

    def test_basis_bps_zero_when_perp_equals_spot(self):
        obs = BasisObservation(
            sampled_at=_ts(),
            perp_price=Decimal("100.00"),
            spot_price=Decimal("100.00"),
        )
        assert obs.basis_bps == Decimal("0")

    def test_naive_timestamp_raises(self):
        with pytest.raises(A2SignalEvaluationError, match="timezone-aware"):
            BasisObservation(
                sampled_at=datetime(2024, 1, 1),
                perp_price=Decimal("100"),
                spot_price=Decimal("100"),
            )

    def test_negative_perp_price_raises(self):
        with pytest.raises(A2SignalEvaluationError, match="perp_price"):
            BasisObservation(
                sampled_at=_ts(),
                perp_price=Decimal("-1"),
                spot_price=Decimal("100"),
            )

    def test_zero_spot_price_raises(self):
        with pytest.raises(A2SignalEvaluationError, match="spot_price"):
            BasisObservation(
                sampled_at=_ts(),
                perp_price=Decimal("100"),
                spot_price=Decimal("0"),
            )

    def test_non_decimal_price_raises(self):
        with pytest.raises(A2SignalEvaluationError, match="Decimal"):
            BasisObservation(
                sampled_at=_ts(),
                perp_price=100.0,
                spot_price=Decimal("100"),
            )


class TestA2SignalConfig:
    def test_defaults_match_reviewer_lock(self):
        config = A2SignalConfig()
        assert config.window_size == 60
        assert config.min_lookback == 30
        assert config.max_staleness_seconds == 600
        assert config.z_threshold == Decimal("2.0")
        assert config.near_zero_stdev_threshold_bps == Decimal("0.01")

    def test_min_lookback_exceeds_window_raises(self):
        with pytest.raises(A2SignalEvaluationError, match="cannot exceed"):
            A2SignalConfig(window_size=10, min_lookback=20)

    def test_zero_window_size_raises(self):
        with pytest.raises(A2SignalEvaluationError, match="window_size"):
            A2SignalConfig(window_size=0, min_lookback=1)

    def test_negative_z_threshold_raises(self):
        with pytest.raises(A2SignalEvaluationError, match="z_threshold"):
            A2SignalConfig(z_threshold=Decimal("-1"))

    def test_non_decimal_z_threshold_raises(self):
        with pytest.raises(TypeError, match="z_threshold"):
            A2SignalConfig(z_threshold=2.0)


class TestInsufficientLookback:
    def test_empty_window_returns_flat_with_no_lineage(self):
        result = evaluate_a2_signal(
            window=[],
            cost_threshold_bps=Decimal("20"),
            as_of=_ts(3600),
        )
        assert result.decision == A2SignalDecision.FLAT
        assert result.reason == A2_FLAT_REASON_INSUFFICIENT_LOOKBACK
        assert result.n_samples == 0
        assert result.window_start is None
        assert result.window_end is None
        assert result.current_basis_bps is None
        assert result.rolling_mean_basis_bps is None
        assert result.rolling_stdev_basis_bps is None
        assert result.basis_dislocation_bps is None
        assert result.z_score is None
        assert result.cost_threshold_bps == Decimal("20")
        assert result.z_threshold == Decimal("2.0")

    def test_below_min_lookback_returns_flat_with_partial_lineage(self):
        window = _build_window([Decimal("10")] * 10)
        result = evaluate_a2_signal(
            window=window,
            cost_threshold_bps=Decimal("20"),
            as_of=window[-1].sampled_at + timedelta(seconds=60),
        )
        assert result.decision == A2SignalDecision.FLAT
        assert result.reason == A2_FLAT_REASON_INSUFFICIENT_LOOKBACK
        assert result.n_samples == 10
        assert result.window_start == window[0].sampled_at
        assert result.window_end == window[-1].sampled_at
        assert result.current_basis_bps == Decimal("10")
        assert result.rolling_mean_basis_bps is None

    def test_custom_min_lookback_threshold(self):
        config = A2SignalConfig(window_size=10, min_lookback=5)
        window = _build_window([Decimal("10")] * 4)
        result = evaluate_a2_signal(
            window=window,
            cost_threshold_bps=Decimal("20"),
            as_of=window[-1].sampled_at + timedelta(seconds=60),
            config=config,
        )
        assert result.reason == A2_FLAT_REASON_INSUFFICIENT_LOOKBACK


class TestStructuralErrors:
    def test_unsorted_window_raises(self):
        window = _build_window([Decimal("10")] * 50)
        window = list(reversed(window))
        with pytest.raises(A2SignalEvaluationError, match="sorted ascending"):
            evaluate_a2_signal(
                window=window,
                cost_threshold_bps=Decimal("20"),
                as_of=_ts(99999),
            )

    def test_look_ahead_raises(self):
        window = _build_window([Decimal("10")] * 50)
        with pytest.raises(A2SignalEvaluationError, match="strictly after"):
            evaluate_a2_signal(
                window=window,
                cost_threshold_bps=Decimal("20"),
                as_of=window[-1].sampled_at,
            )

    def test_negative_cost_threshold_raises(self):
        window = _build_window([Decimal("10")] * 50)
        with pytest.raises(A2SignalEvaluationError, match="cost_threshold_bps"):
            evaluate_a2_signal(
                window=window,
                cost_threshold_bps=Decimal("-1"),
                as_of=window[-1].sampled_at + timedelta(seconds=60),
            )

    def test_naive_as_of_raises(self):
        window = _build_window([Decimal("10")] * 50)
        with pytest.raises(A2SignalEvaluationError, match="timezone-aware"):
            evaluate_a2_signal(
                window=window,
                cost_threshold_bps=Decimal("20"),
                as_of=datetime(2024, 1, 2),
            )


class TestStaleWindow:
    def test_stale_window_returns_flat(self):
        window = _build_window([Decimal("10")] * 50)
        as_of = window[-1].sampled_at + timedelta(seconds=700)
        result = evaluate_a2_signal(
            window=window,
            cost_threshold_bps=Decimal("20"),
            as_of=as_of,
        )
        assert result.decision == A2SignalDecision.FLAT
        assert result.reason == A2_FLAT_REASON_STALE_WINDOW
        assert result.window_end == window[-1].sampled_at
        assert result.current_basis_bps == Decimal("10")
        assert result.rolling_mean_basis_bps is None

    def test_within_staleness_proceeds_to_stats(self):
        window = _build_window([Decimal("10")] * 50)
        as_of = window[-1].sampled_at + timedelta(seconds=500)
        result = evaluate_a2_signal(
            window=window,
            cost_threshold_bps=Decimal("20"),
            as_of=as_of,
        )
        assert result.reason != A2_FLAT_REASON_STALE_WINDOW


class TestNearZeroStdev:
    def test_constant_basis_returns_flat_zero_stdev(self):
        window = _build_window([Decimal("10")] * 50)
        as_of = window[-1].sampled_at + timedelta(seconds=60)
        result = evaluate_a2_signal(
            window=window,
            cost_threshold_bps=Decimal("20"),
            as_of=as_of,
        )
        assert result.decision == A2SignalDecision.FLAT
        assert result.reason == A2_FLAT_REASON_ZERO_OR_NEAR_ZERO_STDEV
        assert result.rolling_mean_basis_bps == Decimal("10")
        assert result.rolling_stdev_basis_bps == Decimal("0")
        assert result.basis_dislocation_bps == Decimal("0")
        assert result.z_score is None


class TestZBelowThreshold:
    def test_low_z_returns_flat(self):
        basis_values = []
        for i in range(30):
            basis_values.append(Decimal("0") if i % 2 == 0 else Decimal("100"))
        basis_values.extend([Decimal("51")] * 20)
        window = _build_window(basis_values)
        as_of = window[-1].sampled_at + timedelta(seconds=60)
        result = evaluate_a2_signal(
            window=window,
            cost_threshold_bps=Decimal("20"),
            as_of=as_of,
        )
        assert result.decision == A2SignalDecision.FLAT
        assert result.reason == A2_FLAT_REASON_Z_BELOW_THRESHOLD
        assert result.z_score is not None
        assert abs(result.z_score) < Decimal("2.0")


class TestCostNotCleared:
    def test_high_z_but_small_dislocation_returns_flat(self):
        """Reviewer amendment: cost-anchoring uses DISLOCATION not raw basis.

        Tight window (small stdev) + small spike:
        - 29 samples at basis = 10.0 bps
        - 1 final sample at basis = 10.5 bps
        - dislocation = 0.483 bps; z ~ 5.3 (clears 2.0 threshold)
        - But |dislocation| = 0.48 bps < cost_threshold 20 bps
        """
        basis_values = [Decimal("10.0")] * 29 + [Decimal("10.5")]
        window = _build_window(basis_values)
        as_of = window[-1].sampled_at + timedelta(seconds=60)
        result = evaluate_a2_signal(
            window=window,
            cost_threshold_bps=Decimal("20"),
            as_of=as_of,
        )
        assert result.decision == A2SignalDecision.FLAT
        assert result.reason == A2_FLAT_REASON_COST_NOT_CLEARED
        assert result.z_score is not None
        assert abs(result.z_score) >= Decimal("2.0")
        assert abs(result.basis_dislocation_bps) < Decimal("20")

    def test_persistent_high_basis_no_dislocation_returns_flat(self):
        """Reviewer's BTC +40 example: 30 samples all at 40 bps.
        mean=40, current=40, dislocation=0.
        """
        window = _build_window([Decimal("40")] * 30)
        as_of = window[-1].sampled_at + timedelta(seconds=60)
        result = evaluate_a2_signal(
            window=window,
            cost_threshold_bps=Decimal("20"),
            as_of=as_of,
        )
        assert result.decision == A2SignalDecision.FLAT
        assert result.reason in (
            A2_FLAT_REASON_ZERO_OR_NEAR_ZERO_STDEV,
            A2_FLAT_REASON_COST_NOT_CLEARED,
        )


class TestDirectionalDecisions:
    def _spike_window(
        self, base_basis: Decimal, spike_basis: Decimal, n: int = 30
    ) -> list[BasisObservation]:
        return _build_window([base_basis] * (n - 1) + [spike_basis])

    def test_positive_dislocation_returns_short_perp(self):
        window = self._spike_window(Decimal("0"), Decimal("50"))
        as_of = window[-1].sampled_at + timedelta(seconds=60)
        result = evaluate_a2_signal(
            window=window,
            cost_threshold_bps=Decimal("20"),
            as_of=as_of,
        )
        assert result.decision == A2SignalDecision.SHORT_PERP_LONG_SPOT
        assert result.reason is None
        assert result.basis_dislocation_bps > 0
        assert result.z_score > Decimal("2.0")

    def test_negative_dislocation_returns_long_perp(self):
        window = self._spike_window(Decimal("0"), Decimal("-50"))
        as_of = window[-1].sampled_at + timedelta(seconds=60)
        result = evaluate_a2_signal(
            window=window,
            cost_threshold_bps=Decimal("20"),
            as_of=as_of,
        )
        assert result.decision == A2SignalDecision.LONG_PERP_SHORT_SPOT
        assert result.reason is None
        assert result.basis_dislocation_bps < 0
        assert result.z_score < Decimal("-2.0")

    def test_decision_has_no_reason_when_non_flat(self):
        window = self._spike_window(Decimal("0"), Decimal("50"))
        as_of = window[-1].sampled_at + timedelta(seconds=60)
        result = evaluate_a2_signal(
            window=window,
            cost_threshold_bps=Decimal("20"),
            as_of=as_of,
        )
        assert result.decision != A2SignalDecision.FLAT
        assert result.reason is None

    def test_schema_version_present_on_evaluation(self):
        window = self._spike_window(Decimal("0"), Decimal("50"))
        as_of = window[-1].sampled_at + timedelta(seconds=60)
        result = evaluate_a2_signal(
            window=window,
            cost_threshold_bps=Decimal("20"),
            as_of=as_of,
        )
        assert result.schema_version == A2_SIGNAL_EVALUATION_SCHEMA_VERSION


class TestA2SignalEvaluationInvariants:
    def test_flat_without_reason_raises(self):
        with pytest.raises(A2SignalEvaluationError, match="FLAT decision requires reason"):
            A2SignalEvaluation(
                decision=A2SignalDecision.FLAT,
                reason=None,
                n_samples=0,
                window_start=None,
                window_end=None,
                current_basis_bps=None,
                rolling_mean_basis_bps=None,
                rolling_stdev_basis_bps=None,
                basis_dislocation_bps=None,
                z_score=None,
                cost_threshold_bps=Decimal("20"),
                z_threshold=Decimal("2.0"),
            )

    def test_invalid_reason_raises(self):
        with pytest.raises(A2SignalEvaluationError, match="not in"):
            A2SignalEvaluation(
                decision=A2SignalDecision.FLAT,
                reason="not_a_real_reason",
                n_samples=0,
                window_start=None,
                window_end=None,
                current_basis_bps=None,
                rolling_mean_basis_bps=None,
                rolling_stdev_basis_bps=None,
                basis_dislocation_bps=None,
                z_score=None,
                cost_threshold_bps=Decimal("20"),
                z_threshold=Decimal("2.0"),
            )

    def test_non_flat_with_reason_raises(self):
        with pytest.raises(A2SignalEvaluationError, match="non-FLAT decision must have reason=None"):
            A2SignalEvaluation(
                decision=A2SignalDecision.SHORT_PERP_LONG_SPOT,
                reason=A2_FLAT_REASON_INSUFFICIENT_LOOKBACK,
                n_samples=30,
                window_start=_ts(),
                window_end=_ts(60),
                current_basis_bps=Decimal("50"),
                rolling_mean_basis_bps=Decimal("0"),
                rolling_stdev_basis_bps=Decimal("9"),
                basis_dislocation_bps=Decimal("50"),
                z_score=Decimal("5.5"),
                cost_threshold_bps=Decimal("20"),
                z_threshold=Decimal("2.0"),
            )
