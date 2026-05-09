"""Unit tests for analytics.strategy_metrics — pure-function Sharpe."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from analytics.strategy_metrics import (
    IntervalReturn,
    SharpeError,
    SharpeResult,
    compute_sharpe,
)

UTC = timezone.utc


def _make_return(idx: int, pnl: Decimal) -> IntervalReturn:
    """Synthetic IntervalReturn at index idx with given total_pnl_usd
    and zero fee/mark contributions."""
    base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    return IntervalReturn(
        interval_start=base + timedelta(hours=8 * idx),
        interval_end=base + timedelta(hours=8 * (idx + 1)),
        funding_pnl_usd=pnl,
        fee_pnl_usd=Decimal("0"),
        mark_pnl_usd=Decimal("0"),
        total_pnl_usd=pnl,
    )


class TestIntervalReturnInvariants:
    def test_total_must_match_components(self):
        with pytest.raises(ValueError, match="does not match"):
            IntervalReturn(
                interval_start=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
                interval_end=datetime(2026, 1, 1, 8, 0, 0, tzinfo=UTC),
                funding_pnl_usd=Decimal("5"),
                fee_pnl_usd=Decimal("-1"),
                mark_pnl_usd=Decimal("0"),
                total_pnl_usd=Decimal("99"),  # wrong
            )

    def test_end_must_be_after_start(self):
        with pytest.raises(ValueError, match="interval_end must be > interval_start"):
            IntervalReturn(
                interval_start=datetime(2026, 1, 1, 8, 0, 0, tzinfo=UTC),
                interval_end=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
                funding_pnl_usd=Decimal("0"),
                fee_pnl_usd=Decimal("0"),
                mark_pnl_usd=Decimal("0"),
                total_pnl_usd=Decimal("0"),
            )


class TestComputeSharpeBasic:
    def test_positive_constant_returns_zero_stdev_raises(self):
        # All returns identical → stdev == 0 → must raise.
        returns = [_make_return(i, Decimal("5")) for i in range(10)]
        with pytest.raises(SharpeError, match="stdev"):
            compute_sharpe(returns, intervals_per_year=1095)

    def test_known_mean_and_stdev_matches_hand_calc(self):
        # Returns: 1, 2, 3, 4, 5
        # mean = 3
        # stdev (n-1) = sqrt(sum((x-3)^2)/4) = sqrt(10/4) = sqrt(2.5) ≈ 1.581
        # Sharpe (annualized to 1, no scaling) = 3 / 1.581 ≈ 1.897
        returns = [_make_return(i, Decimal(str(v))) for i, v in enumerate([1, 2, 3, 4, 5])]
        result = compute_sharpe(returns, intervals_per_year=1)
        assert result.n_intervals == 5
        assert result.mean_return_usd == Decimal("3")
        # stdev should be very close to sqrt(2.5)
        assert abs(result.stdev_return_usd - Decimal("1.5811388300841896659994467722")) < Decimal("1e-15")
        # Sharpe should be very close to 3 / sqrt(2.5)
        assert abs(result.sharpe - Decimal("1.897366596101027727641830126")) < Decimal("1e-15")

    def test_negative_mean_produces_negative_sharpe(self):
        returns = [_make_return(i, Decimal(str(v))) for i, v in enumerate([-1, -2, -3])]
        result = compute_sharpe(returns, intervals_per_year=1)
        assert result.mean_return_usd == Decimal("-2")
        assert result.sharpe < Decimal("0")

    def test_annualization_factor_is_sqrt_intervals_per_year(self):
        returns = [_make_return(i, Decimal(str(v))) for i, v in enumerate([1, 2, 3, 4, 5])]
        result_1 = compute_sharpe(returns, intervals_per_year=1)
        result_1095 = compute_sharpe(returns, intervals_per_year=1095)
        # Ratio should be sqrt(1095) ≈ 33.09
        ratio = result_1095.sharpe / result_1.sharpe
        assert abs(ratio - Decimal("33.09").quantize(Decimal("0.01"))) < Decimal("0.01")


class TestComputeSharpeErrorPaths:
    def test_n_zero_raises(self):
        with pytest.raises(SharpeError, match="at least 2 observations"):
            compute_sharpe([], intervals_per_year=1095)

    def test_n_one_raises(self):
        with pytest.raises(SharpeError, match="at least 2 observations"):
            compute_sharpe([_make_return(0, Decimal("5"))], intervals_per_year=1095)

    def test_zero_intervals_per_year_raises(self):
        returns = [_make_return(i, Decimal(str(v))) for i, v in enumerate([1, 2, 3])]
        with pytest.raises(SharpeError, match="intervals_per_year"):
            compute_sharpe(returns, intervals_per_year=0)

    def test_negative_intervals_per_year_raises(self):
        returns = [_make_return(i, Decimal(str(v))) for i, v in enumerate([1, 2, 3])]
        with pytest.raises(SharpeError, match="intervals_per_year"):
            compute_sharpe(returns, intervals_per_year=-1)


class TestComputeSharpeRealistic:
    def test_a1_like_returns(self):
        # Mimic the synthetic backfill: 29 returns ranging $4-6 each.
        # All positive but with noticeable variation.
        pnls = [
            Decimal("5.20"), Decimal("4.80"), Decimal("5.30"),
            Decimal("5.00"), Decimal("5.50"), Decimal("4.60"),
            Decimal("5.10"), Decimal("4.90"), Decimal("5.40"),
            Decimal("5.00"), Decimal("5.30"), Decimal("4.70"),
            Decimal("5.20"), Decimal("5.10"), Decimal("4.80"),
            Decimal("5.00"), Decimal("5.40"), Decimal("4.90"),
            Decimal("5.00"), Decimal("4.80"), Decimal("5.20"),
            Decimal("4.50"), Decimal("5.50"), Decimal("5.00"),
            Decimal("5.30"), Decimal("4.70"), Decimal("5.10"),
            Decimal("4.90"), Decimal("5.40"),
        ]
        returns = [_make_return(i, p) for i, p in enumerate(pnls)]
        result = compute_sharpe(returns, intervals_per_year=1095)
        # Mean around 5.0, stdev around 0.27 → Sharpe annualized very high
        # because returns are all positive with low dispersion. This is
        # exactly why synthetic-only backfills produce unrealistic numbers.
        assert result.n_intervals == 29
        assert Decimal("4.9") < result.mean_return_usd < Decimal("5.1")
        assert result.stdev_return_usd > Decimal("0")
        assert result.sharpe > Decimal("0")  # All positive returns → positive Sharpe

    def test_mixed_sign_returns_realistic_sharpe(self):
        # More realistic mixed-sign returns: some intervals lose money.
        pnls = [
            Decimal("5"), Decimal("-3"), Decimal("4"), Decimal("2"),
            Decimal("-1"), Decimal("3"), Decimal("-2"), Decimal("4"),
            Decimal("1"), Decimal("-2"),
        ]
        returns = [_make_return(i, p) for i, p in enumerate(pnls)]
        result = compute_sharpe(returns, intervals_per_year=1095)
        assert result.n_intervals == 10
        # Sharpe should be positive but not absurdly high.
        assert result.sharpe > Decimal("0")
        assert result.sharpe < Decimal("50")
