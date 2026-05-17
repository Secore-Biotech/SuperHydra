"""Unit tests for vol_scaled_momentum.backtest.

Engine-level invariants only. Full OOS performance is tested by the
runner script `scripts/run_candidate_4_backtest.py` against live cache.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from strategies.sleeve_b.vol_scaled_momentum.backtest import (
    BacktestResult,
    RebalanceLog,
    run_backtest,
)
from strategies.sleeve_b.xs_momentum.backtest import WeeklyPnL
from strategies.sleeve_b.xs_momentum.prices import PriceBar, PriceSeries
from strategies.sleeve_b.xs_momentum.universe import UniverseAsset


def _make_series(symbol: str, start: date, n_days: int,
                 daily_log_return: Decimal) -> PriceSeries:
    """Constant-daily-log-return synthetic price series.

    NOTE: realized vol of the resulting series is structurally near zero
    (Taylor-truncation noise). Used here for engine-shape tests that don't
    depend on vol magnitude. Real vol magnitude is tested in signal unit tests.
    """
    bars: list[PriceBar] = []
    cur = Decimal("100")
    for i in range(n_days):
        d = start + timedelta(days=i)
        bars.append(PriceBar(bar_date=d, open_price=cur, close_price=cur))
        if daily_log_return != Decimal(0):
            r = daily_log_return
            factor = Decimal(1) + r + r * r / Decimal(2) + r * r * r / Decimal(6)
            cur = cur * factor
    return PriceSeries(symbol=symbol, bars=bars)


def _make_universe(n_assets: int, onboard: date) -> list[UniverseAsset]:
    return [
        UniverseAsset(
            rank=i + 1,
            symbol=f"SYM{i}USDT",
            base_asset=f"SYM{i}",
            onboard_date=onboard,
            adv_usdt=Decimal("1000000"),
        )
        for i in range(n_assets)
    ]


def _make_prices(universe: list[UniverseAsset], start: date, n_days: int) -> dict:
    """Distinct daily log returns per symbol so scores differ."""
    prices = {}
    for i, asset in enumerate(universe):
        # Each symbol has a different return rate so scores rank distinctly.
        r = Decimal("0.001") * Decimal(i + 1)
        prices[asset.symbol] = _make_series(
            asset.symbol, start, n_days, daily_log_return=r,
        )
    return prices


class TestRunBacktestShape:
    def test_no_rebalance_dates_empty_result(self) -> None:
        result = run_backtest(
            universe=[],
            prices={},
            start=date(2024, 1, 6),  # Saturday
            end=date(2024, 1, 7),    # Sunday — no Monday in window
        )
        assert result.rebalance_logs == []
        assert result.weekly_pnls == []

    def test_one_full_rebalance_produces_log_and_pnl(self) -> None:
        # Universe of 10 assets, onboarded 90 days before OOS start.
        # 80 days of prices ⇒ first Monday at 2024-04-01 is the only
        # rebalance with full vol-window data.
        onboard = date(2024, 1, 1)
        universe = _make_universe(10, onboard)
        # Prices: 100 days starting Jan 1.
        prices = _make_prices(universe, onboard, n_days=100)
        result = run_backtest(
            universe=universe, prices=prices,
            start=date(2024, 3, 25), end=date(2024, 4, 1),
        )
        assert len(result.rebalance_logs) >= 1
        assert len(result.weekly_pnls) == len(result.rebalance_logs)

    def test_rebalance_log_preserves_scores_and_components(self) -> None:
        onboard = date(2024, 1, 1)
        universe = _make_universe(10, onboard)
        prices = _make_prices(universe, onboard, n_days=100)
        result = run_backtest(
            universe=universe, prices=prices,
            start=date(2024, 3, 25), end=date(2024, 4, 1),
        )
        # Find a non-skipped log.
        non_skipped = [log for log in result.rebalance_logs if not log.skipped]
        assert len(non_skipped) >= 1, "expected at least one non-skipped rebalance"
        log = non_skipped[0]
        # candidate-#4-specific fields exist and are non-empty.
        assert log.scores
        assert log.momentum_components
        assert log.vol_components
        # Scores derive from components.
        for sym, score in log.scores.items():
            expected = log.momentum_components[sym] / log.vol_components[sym]
            assert score == expected
        # Bucket sizes recorded.
        assert log.long_bucket_size > 0
        assert log.short_bucket_size > 0
        # Long and short buckets are disjoint.
        assert set(log.long_bucket).isdisjoint(set(log.short_bucket))


class TestBacktestResultEquityCurve:
    def test_equity_curve_is_cumulative(self) -> None:
        # Hand-craft a BacktestResult with known weekly P&Ls and verify
        # equity_curve_bps() returns the running sum.
        weekly = [
            WeeklyPnL(
                week_start=date(2024, 1, 1) + timedelta(days=7 * i),
                week_end=date(2024, 1, 7) + timedelta(days=7 * i),
                long_pnl_bps=Decimal("5"),
                short_pnl_bps=Decimal("3"),
                gross_pnl_bps=Decimal("8"),
                fee_drag_bps=Decimal("1"),
                net_pnl_bps=Decimal(str(net)),
            )
            for i, net in enumerate([10, -5, 20, 15])
        ]
        result = BacktestResult(rebalance_logs=[], weekly_pnls=weekly)
        curve = result.equity_curve_bps()
        assert curve == [Decimal("10"), Decimal("5"), Decimal("25"), Decimal("40")]

    def test_empty_result_empty_curve(self) -> None:
        result = BacktestResult(rebalance_logs=[], weekly_pnls=[])
        assert result.equity_curve_bps() == []


class TestColdStartScale:
    def test_first_rebalance_has_scale_1(self) -> None:
        # Build enough universe so first rebalance is non-skipped.
        onboard = date(2024, 1, 1)
        universe = _make_universe(10, onboard)
        prices = _make_prices(universe, onboard, n_days=100)
        result = run_backtest(
            universe=universe, prices=prices,
            start=date(2024, 3, 25), end=date(2024, 4, 1),
        )
        non_skipped = [log for log in result.rebalance_logs if not log.skipped]
        if non_skipped:
            # First non-skipped rebalance during cold-start period has scale = 1.0
            # (cold_start_weeks=4 ⇒ first 4 rebalances).
            first = non_skipped[0]
            assert first.portfolio_scale == Decimal("1")
            assert first.realized_vol_input is None


class TestSkippedRebalance:
    def test_skipped_rebalance_produces_zero_pnl_and_zero_gross(self) -> None:
        # Universe of 2 assets, default min_eligible is 4 ⇒ skip.
        onboard = date(2024, 1, 1)
        universe = _make_universe(2, onboard)
        prices = _make_prices(universe, onboard, n_days=100)
        result = run_backtest(
            universe=universe, prices=prices,
            start=date(2024, 3, 25), end=date(2024, 4, 1),
        )
        # All rebalances should be skipped.
        for log in result.rebalance_logs:
            assert log.skipped
            assert log.long_bucket == []
            assert log.short_bucket == []
            assert log.portfolio_scale == Decimal("0")
            assert log.gross_notional == Decimal("0")
        # Weekly P&Ls all zero gross / zero net (turnover is also 0
        # because no portfolio was ever opened).
        for w in result.weekly_pnls:
            assert w.long_pnl_bps == Decimal("0")
            assert w.short_pnl_bps == Decimal("0")
            assert w.gross_pnl_bps == Decimal("0")
            assert w.fee_drag_bps == Decimal("0")
            assert w.net_pnl_bps == Decimal("0")
