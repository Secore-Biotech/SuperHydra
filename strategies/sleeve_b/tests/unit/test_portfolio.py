"""Unit tests for portfolio construction, vol-target, turnover."""
from __future__ import annotations

import math
import statistics
from datetime import date
from decimal import Decimal

import pytest

from strategies.sleeve_b.xs_momentum.portfolio import (
    COLD_START_WEEKS,
    Portfolio,
    Position,
    TARGET_WEEKLY_VOL,
    TRAILING_VOL_WEEKS,
    build_portfolio,
    compute_turnover,
)
from strategies.sleeve_b.xs_momentum.signal import SignalOutput


def _signal_output(*, skipped: bool = False, n_long: int = 3, n_short: int = 3):
    """Build a synthetic SignalOutput."""
    long_bucket = [f"L{i}" for i in range(n_long)]
    short_bucket = [f"S{i}" for i in range(n_short)]
    return SignalOutput(
        rebalance_at=date(2024, 6, 17),
        eligible=long_bucket + short_bucket,
        eligible_count=n_long + n_short,
        returns={s: Decimal("0.01") for s in long_bucket + short_bucket},
        long_bucket=long_bucket,
        short_bucket=short_bucket,
        long_decile_size=n_long,
        short_decile_size=n_short,
        skipped=skipped,
        skip_reason="forced skip" if skipped else None,
        excluded_symbols=[],
    )


class TestEqualWeight:
    def test_equal_weight_within_bucket(self):
        signal = _signal_output(n_long=3, n_short=3)
        pf = build_portfolio(signal=signal, trailing_weekly_pnl_bps=[])
        assert pf is not None
        long_weights = [p.weight for p in pf.positions if p.weight > 0]
        short_weights = [p.weight for p in pf.positions if p.weight < 0]
        assert len(long_weights) == 3
        assert len(short_weights) == 3
        # Each long = 1/3 (cold-start scale = 1.0)
        for w in long_weights:
            assert w == Decimal("1") / Decimal("3")
        for w in short_weights:
            assert w == -Decimal("1") / Decimal("3")

    def test_dollar_neutral(self):
        signal = _signal_output(n_long=2, n_short=2)
        pf = build_portfolio(signal=signal, trailing_weekly_pnl_bps=[])
        assert pf is not None
        assert pf.long_notional() == pf.short_notional()


class TestColdStart:
    def test_first_4_weeks_uniform_scale(self):
        """Cold start: scale = 1.0 for first 4 weeks (no realized vol input)."""
        signal = _signal_output()
        for i in range(COLD_START_WEEKS):
            pf = build_portfolio(
                signal=signal,
                trailing_weekly_pnl_bps=[Decimal("100")] * i,
            )
            assert pf is not None
            assert pf.gross_notional_scale == Decimal("1")
            assert pf.realized_vol_input is None

    def test_post_cold_start_uses_realized_vol(self):
        signal = _signal_output()
        # 4 weeks of trailing P&L with varied returns
        trailing = [
            Decimal("50"), Decimal("-30"), Decimal("80"), Decimal("-20"),
        ]
        pf = build_portfolio(
            signal=signal, trailing_weekly_pnl_bps=trailing,
        )
        assert pf is not None
        assert pf.realized_vol_input is not None
        assert pf.gross_notional_scale != Decimal("1")

    def test_post_cold_start_vol_target_math(self):
        """Verify the scaler equals target/realized."""
        signal = _signal_output()
        # Construct trailing P&L with known stdev
        trailing_bps = [
            Decimal("100"), Decimal("-100"), Decimal("100"), Decimal("-100"),
        ]
        pf = build_portfolio(
            signal=signal, trailing_weekly_pnl_bps=trailing_bps,
        )
        assert pf is not None
        # stdev of [0.01, -0.01, 0.01, -0.01] = sqrt(4/3 * 0.01^2) using stdev
        expected_realized = Decimal(str(statistics.stdev(
            [0.01, -0.01, 0.01, -0.01],
        )))
        expected_scale = TARGET_WEEKLY_VOL / expected_realized
        # Allow tiny floating-point tolerance
        diff = abs(pf.gross_notional_scale - expected_scale)
        assert diff < Decimal("0.00001"), (
            f"Expected scale ~{expected_scale}, got {pf.gross_notional_scale}"
        )


class TestNoLeverageCap:
    """Documented behavior: there is no cap on the vol-target scaler."""

    def test_zero_realized_vol_falls_back_to_unity(self):
        signal = _signal_output()
        # All returns identical → stdev = 0 → fall back to scale=1
        trailing = [Decimal("100")] * 4
        pf = build_portfolio(
            signal=signal, trailing_weekly_pnl_bps=trailing,
        )
        assert pf is not None
        assert pf.gross_notional_scale == Decimal("1")

    def test_low_realized_vol_produces_high_scale(self):
        """If realized vol is very low, scaler becomes very high. Documented."""
        signal = _signal_output()
        # Very low realized vol
        trailing = [
            Decimal("1"), Decimal("-1"), Decimal("1"), Decimal("-1"),
        ]
        pf = build_portfolio(
            signal=signal, trailing_weekly_pnl_bps=trailing,
        )
        assert pf is not None
        # stdev of [0.0001, -0.0001, 0.0001, -0.0001] is ~0.000115
        # Scaler should be much greater than 1
        assert pf.gross_notional_scale > Decimal("100")


class TestTurnover:
    def test_cold_start_turnover(self):
        signal = _signal_output()
        pf = build_portfolio(signal=signal, trailing_weekly_pnl_bps=[])
        assert pf is not None
        t = compute_turnover(previous=None, current=pf)
        assert t == pf.gross_notional()

    def test_identical_portfolios_zero_turnover(self):
        signal = _signal_output()
        pf1 = build_portfolio(signal=signal, trailing_weekly_pnl_bps=[])
        pf2 = build_portfolio(signal=signal, trailing_weekly_pnl_bps=[])
        t = compute_turnover(previous=pf1, current=pf2)
        assert t == Decimal("0")

    def test_completely_different_portfolios(self):
        sig1 = _signal_output(n_long=3, n_short=3)
        sig2 = SignalOutput(
            rebalance_at=date(2024, 6, 17),
            eligible=["X0", "X1", "Y0", "Y1"],
            eligible_count=4,
            returns={"X0": Decimal("0.01"), "X1": Decimal("0.01"),
                     "Y0": Decimal("-0.01"), "Y1": Decimal("-0.01")},
            long_bucket=["X0", "X1"],
            short_bucket=["Y0", "Y1"],
            long_decile_size=2, short_decile_size=2,
            skipped=False, skip_reason=None, excluded_symbols=[],
        )
        pf1 = build_portfolio(signal=sig1, trailing_weekly_pnl_bps=[])
        pf2 = build_portfolio(signal=sig2, trailing_weekly_pnl_bps=[])
        t = compute_turnover(previous=pf1, current=pf2)
        # Closing all of pf1 + opening all of pf2 = gross1 + gross2
        expected = pf1.gross_notional() + pf2.gross_notional()
        # Decimal arithmetic at 27-digit precision; tolerance for last-digit rounding
        assert abs(t - expected) < Decimal("0.00001")

    def test_skipped_signal_yields_none_portfolio(self):
        signal = _signal_output(skipped=True)
        pf = build_portfolio(signal=signal, trailing_weekly_pnl_bps=[])
        assert pf is None

    def test_turnover_skip_after_held(self):
        """If we held a portfolio and then skip, turnover = closing out prev."""
        signal = _signal_output()
        prev = build_portfolio(signal=signal, trailing_weekly_pnl_bps=[])
        t = compute_turnover(previous=prev, current=None)
        assert t == prev.gross_notional()
