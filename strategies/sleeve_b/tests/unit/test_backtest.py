"""Unit tests for the backtest main loop and audit logs."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from strategies.sleeve_b.xs_momentum.backtest import (
    FEES_BPS_ROUND_TRIP,
    generate_rebalance_dates,
    run_backtest,
)
from strategies.sleeve_b.xs_momentum.prices import PriceBar, PriceSeries
from strategies.sleeve_b.xs_momentum.universe import UniverseAsset


def _make_price_series(
    symbol: str, start: date, days: int,
    *,
    return_per_day: float = 0.0,
    initial: float = 100.0,
) -> PriceSeries:
    bars = []
    price = Decimal(str(initial))
    for i in range(days):
        bars.append(PriceBar(
            bar_date=start + timedelta(days=i),
            open_price=price,
            close_price=price,
        ))
        price = price * (Decimal("1") + Decimal(str(return_per_day)))
    return PriceSeries(symbol, bars)


def _make_universe(n: int, listing: date) -> list[UniverseAsset]:
    return [
        UniverseAsset(
            rank=i + 1, symbol=f"S{i:02d}", base_asset=f"B{i}",
            onboard_date=listing,
            adv_usdt=Decimal("1000000000"),
        )
        for i in range(n)
    ]


class TestRebalanceDates:
    def test_first_monday_at_or_after_start(self):
        # 2024-06-15 is a Saturday; first Monday is 2024-06-17
        dates = generate_rebalance_dates(date(2024, 6, 15), date(2024, 7, 8))
        assert dates[0] == date(2024, 6, 17)

    def test_weekly_spacing(self):
        dates = generate_rebalance_dates(date(2024, 6, 17), date(2024, 7, 8))
        for i in range(1, len(dates)):
            assert (dates[i] - dates[i - 1]).days == 7

    def test_last_within_range(self):
        dates = generate_rebalance_dates(date(2024, 6, 15), date(2024, 7, 8))
        assert dates[-1] <= date(2024, 7, 8)

    def test_empty_when_range_too_small(self):
        # Tuesday to next Sunday — no Monday in range
        dates = generate_rebalance_dates(date(2024, 6, 18), date(2024, 6, 23))
        assert dates == []


class TestBacktestSmoke:
    def test_basic_run_emits_logs(self):
        """End-to-end: 16-asset universe, 8 weeks, every rebalance has a log."""
        listing = date(2024, 1, 1)
        universe = _make_universe(16, listing)
        # Half assets up-trending, half down-trending
        prices = {}
        for i, asset in enumerate(universe):
            rpd = 0.005 if i < 8 else -0.005
            prices[asset.symbol] = _make_price_series(
                asset.symbol, listing, days=180, return_per_day=rpd,
            )
        start = date(2024, 5, 6)  # Monday
        end = date(2024, 6, 30)
        result = run_backtest(
            universe=universe, prices=prices, start=start, end=end,
        )
        assert len(result.rebalance_logs) == 8
        assert len(result.weekly_pnls) == 8
        for log in result.rebalance_logs:
            assert log.skipped is False
            assert log.eligible_count == 16
            assert log.decile_size == 2  # ceil(0.10 * 16) = 2

    def test_universe_membership_never_grows(self):
        """Reviewer requirement (4): backtest must not add new symbols."""
        listing = date(2024, 1, 1)
        universe = _make_universe(10, listing)
        prices = {
            a.symbol: _make_price_series(
                a.symbol, listing, days=180,
                return_per_day=(i + 1) * 0.001,
            )
            for i, a in enumerate(universe)
        }
        # Add a "rogue" series for a symbol NOT in the universe
        rogue_listing = date(2024, 1, 1)
        prices["ROGUE"] = _make_price_series(
            "ROGUE", rogue_listing, days=180, return_per_day=0.1,
        )
        start = date(2024, 5, 6)
        end = date(2024, 6, 30)
        result = run_backtest(
            universe=universe, prices=prices, start=start, end=end,
        )
        # Verify ROGUE never appears in any signal's eligible/long/short
        for log in result.rebalance_logs:
            assert "ROGUE" not in log.eligible_symbols
            assert "ROGUE" not in log.long_bucket
            assert "ROGUE" not in log.short_bucket

    def test_rebalance_log_has_audit_fields(self):
        """Reviewer requirement (5): per-rebalance log emits eligible+long+short+exclusions."""
        listing = date(2024, 1, 1)
        universe = _make_universe(10, listing)
        prices = {
            a.symbol: _make_price_series(
                a.symbol, listing, days=180,
                return_per_day=(i + 1) * 0.001,
            )
            for i, a in enumerate(universe)
        }
        start = date(2024, 5, 6)
        end = date(2024, 5, 20)
        result = run_backtest(
            universe=universe, prices=prices, start=start, end=end,
        )
        assert len(result.rebalance_logs) >= 1
        log = result.rebalance_logs[0]
        # Required audit fields per reviewer
        assert hasattr(log, "rebalance_at")
        assert hasattr(log, "eligible_symbols")
        assert hasattr(log, "long_bucket")
        assert hasattr(log, "short_bucket")
        assert hasattr(log, "excluded_symbols")
        assert hasattr(log, "turnover")
        assert hasattr(log, "portfolio_scale")


class TestCosts:
    def test_first_rebalance_pays_full_turnover_cost(self):
        """Cold start: turnover = gross_notional, fees applied."""
        listing = date(2024, 1, 1)
        universe = _make_universe(10, listing)
        # All assets flat (return = 0) so P&L is zero except for fees
        prices = {
            a.symbol: _make_price_series(
                a.symbol, listing, days=180, return_per_day=0.0,
            )
            for a in universe
        }
        # But returns are different over the trailing window via initial prices
        # Force divergence by varying initial prices
        for i, a in enumerate(universe):
            prices[a.symbol] = _make_price_series(
                a.symbol, listing, days=180,
                return_per_day=(i + 1) * 0.001,
            )
        start = date(2024, 5, 6)
        end = date(2024, 5, 13)  # exactly 2 rebalances
        result = run_backtest(
            universe=universe, prices=prices, start=start, end=end,
        )
        first = result.weekly_pnls[0]
        first_log = result.rebalance_logs[0]
        # Fee drag = turnover * 14.5 bps
        expected_fee_bps = first_log.turnover * FEES_BPS_ROUND_TRIP
        assert abs(first.fee_drag_bps - expected_fee_bps) < Decimal("0.01")


class TestVolTargetIntegration:
    def test_vol_target_kicks_in_after_cold_start(self):
        """First 4 weeks scale=1.0, subsequent weeks use trailing realized vol."""
        listing = date(2024, 1, 1)
        universe = _make_universe(10, listing)
        prices = {
            a.symbol: _make_price_series(
                a.symbol, listing, days=300,
                return_per_day=(i + 1) * 0.002,
            )
            for i, a in enumerate(universe)
        }
        start = date(2024, 5, 6)
        end = date(2024, 7, 22)  # ~11 weeks
        result = run_backtest(
            universe=universe, prices=prices, start=start, end=end,
        )
        # First 4 weeks: scale = 1.0 exactly
        for log in result.rebalance_logs[:4]:
            assert log.portfolio_scale == Decimal("1")
            assert log.realized_vol_input is None
        # Week 5+: scale is computed from realized vol
        assert result.rebalance_logs[4].realized_vol_input is not None


class TestSkipBehavior:
    def test_skip_when_eligible_below_4(self):
        """D11: skip rebalance when eligible count < 4."""
        listing = date(2024, 6, 1)
        # Universe of 5 assets, all listed recently → 0 eligible at first rebalance
        universe = _make_universe(5, listing)
        prices = {
            a.symbol: _make_price_series(
                a.symbol, listing, days=200, return_per_day=0.001,
            )
            for a in universe
        }
        # Rebalance only 7 days after listing → only 0 days of "history"
        start = date(2024, 6, 3)  # Monday
        end = date(2024, 6, 10)
        result = run_backtest(
            universe=universe, prices=prices, start=start, end=end,
        )
        assert len(result.rebalance_logs) >= 1
        # First rebalance(s) should skip
        first_log = result.rebalance_logs[0]
        assert first_log.skipped is True
        assert "min" in first_log.skip_reason or "eligible_count" in first_log.skip_reason

    def test_partial_universe_eligibility(self):
        """Some assets listed early, some late: only old ones eligible."""
        rebalance = date(2024, 6, 17)  # Monday
        old_listing = date(2024, 1, 1)
        new_listing = rebalance - timedelta(days=5)  # too recent
        universe = (
            _make_universe(10, old_listing)
            + [
                UniverseAsset(
                    rank=10 + i, symbol=f"N{i}", base_asset=f"NB{i}",
                    onboard_date=new_listing,
                    adv_usdt=Decimal("500000000"),
                )
                for i in range(5)
            ]
        )
        prices = {}
        for i, asset in enumerate(universe):
            init = old_listing if asset.symbol.startswith("S") else new_listing
            prices[asset.symbol] = _make_price_series(
                asset.symbol, init, days=200,
                return_per_day=(i + 1) * 0.001,
            )
        start = rebalance
        end = rebalance + timedelta(days=6)
        result = run_backtest(
            universe=universe, prices=prices, start=start, end=end,
        )
        assert len(result.rebalance_logs) == 1
        log = result.rebalance_logs[0]
        # Only the 10 old assets eligible
        assert log.eligible_count == 10
        # Decile size = ceil(0.10 * 10) = 1
        assert log.decile_size == 1


class TestEquityCurve:
    def test_equity_curve_is_cumulative_sum(self):
        listing = date(2024, 1, 1)
        universe = _make_universe(10, listing)
        prices = {
            a.symbol: _make_price_series(
                a.symbol, listing, days=180,
                return_per_day=(i + 1) * 0.001,
            )
            for i, a in enumerate(universe)
        }
        start = date(2024, 5, 6)
        end = date(2024, 5, 20)
        result = run_backtest(
            universe=universe, prices=prices, start=start, end=end,
        )
        curve = result.equity_curve_bps()
        assert len(curve) == len(result.weekly_pnls)
        # Each entry is sum of all prior net P&Ls
        cum = Decimal("0")
        for i, w in enumerate(result.weekly_pnls):
            cum += w.net_pnl_bps
            assert curve[i] == cum
