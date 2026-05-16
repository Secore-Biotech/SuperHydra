"""Unit tests for vol_scaled_momentum.signal.

Coverage:
  - realized_vol_from_log_returns: hand-computed values, edge cases
  - collect_log_returns_window: window walking, missing-close handling
  - compute_signal: shape, bucketing, exclusion reasons, skip-on-low-eligibility
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal

import pytest

from strategies.sleeve_b.xs_momentum.prices import PriceBar, PriceSeries
from strategies.sleeve_b.xs_momentum.universe import UniverseAsset
from strategies.sleeve_b.vol_scaled_momentum.signal import (
    MOMENTUM_LOOKBACK_DAYS,
    SQRT_365,
    VOL_LOOKBACK_DAYS,
    SignalOutput,
    collect_log_returns_window,
    compute_signal,
    realized_vol_from_log_returns,
)


# --- realized_vol_from_log_returns ---

class TestRealizedVolFromLogReturns:
    def test_constant_returns_zero_vol(self) -> None:
        rs = [Decimal("0.01")] * 10
        vol = realized_vol_from_log_returns(rs)
        assert vol == Decimal(0)

    def test_alternating_returns_known_stdev(self) -> None:
        rs = [Decimal("0.05"), Decimal("-0.05")]
        vol = realized_vol_from_log_returns(rs)
        expected_stdev_squared = Decimal("0.005")
        expected_stdev = expected_stdev_squared.sqrt()
        expected_vol = SQRT_365 * expected_stdev
        assert vol == expected_vol

    def test_four_returns_sample_not_population(self) -> None:
        rs = [Decimal("0.01"), Decimal("0.02"), Decimal("-0.01"), Decimal("-0.02")]
        vol = realized_vol_from_log_returns(rs)
        expected_var = Decimal("0.001") / Decimal(3)
        expected_stdev = expected_var.sqrt()
        expected_vol = SQRT_365 * expected_stdev
        assert vol == expected_vol
        pop_var = Decimal("0.001") / Decimal(4)
        pop_vol = SQRT_365 * pop_var.sqrt()
        assert vol != pop_vol

    def test_too_few_returns_raises(self) -> None:
        with pytest.raises(ValueError, match="requires n >= 2"):
            realized_vol_from_log_returns([Decimal("0.01")])
        with pytest.raises(ValueError, match="requires n >= 2"):
            realized_vol_from_log_returns([])

    def test_annualization_factor_close_to_sqrt_365(self) -> None:
        assert abs(float(SQRT_365) - math.sqrt(365)) < 1e-12


# --- collect_log_returns_window ---

def _make_series(symbol: str, start: date, n_days: int, base_close: Decimal,
                 daily_log_return: Decimal) -> PriceSeries:
    """Build a synthetic PriceSeries with constant daily log return.

    NOTE: with daily_log_return constant across the window, realized vol of
    the resulting series is structurally near zero (only Taylor-truncation
    noise). Use this helper for shape/exclusion tests that don't depend on
    vol magnitude, not for tests that need realistic vol values.
    """
    bars: list[PriceBar] = []
    cur = base_close
    for i in range(n_days):
        d = start + timedelta(days=i)
        bars.append(PriceBar(bar_date=d, open_price=cur, close_price=cur))
        if daily_log_return != Decimal(0):
            r = daily_log_return
            factor = Decimal(1) + r + r * r / Decimal(2) + r * r * r / Decimal(6)
            cur = cur * factor
    return PriceSeries(symbol=symbol, bars=bars)


class TestCollectLogReturnsWindow:
    def test_full_window_returns_correct_count(self) -> None:
        start = date(2024, 1, 1)
        series = _make_series("BTCUSDT", start, n_days=50,
                              base_close=Decimal("100"),
                              daily_log_return=Decimal(0))
        end = start + timedelta(days=49)
        log_returns = collect_log_returns_window(series, as_of=end, lookback_days=45)
        assert log_returns is not None
        assert len(log_returns) == 45
        for r in log_returns:
            assert r == Decimal(0)

    def test_missing_close_in_window_returns_none(self) -> None:
        start = date(2024, 1, 1)
        bars = []
        for i in range(50):
            if i == 25:
                continue
            d = start + timedelta(days=i)
            bars.append(PriceBar(bar_date=d, open_price=Decimal("100"),
                                 close_price=Decimal("100")))
        series = PriceSeries(symbol="BTCUSDT", bars=bars)
        end = start + timedelta(days=49)
        log_returns = collect_log_returns_window(series, as_of=end, lookback_days=45)
        assert log_returns is None

    def test_missing_endpoint_close_returns_none(self) -> None:
        start = date(2024, 1, 1)
        bars = []
        for i in range(50):
            if i == 49:
                continue
            d = start + timedelta(days=i)
            bars.append(PriceBar(bar_date=d, open_price=Decimal("100"),
                                 close_price=Decimal("100")))
        series = PriceSeries(symbol="BTCUSDT", bars=bars)
        end = start + timedelta(days=49)
        log_returns = collect_log_returns_window(series, as_of=end, lookback_days=45)
        assert log_returns is None


# --- compute_signal ---

def _make_universe(symbols_and_onboards: list[tuple[str, date]]) -> list[UniverseAsset]:
    return [
        UniverseAsset(
            rank=i + 1,
            symbol=sym,
            base_asset=sym.replace("USDT", ""),
            onboard_date=onboard,
            adv_usdt=Decimal("1000000"),
        )
        for i, (sym, onboard) in enumerate(symbols_and_onboards)
    ]


def _build_price_map_uniform(symbols: list[str], start: date, n_days: int,
                             daily_log_return: Decimal) -> dict[str, PriceSeries]:
    return {
        sym: _make_series(sym, start, n_days,
                          base_close=Decimal("100"),
                          daily_log_return=daily_log_return)
        for sym in symbols
    }


class TestComputeSignalShape:
    """Basic invariants on SignalOutput structure."""

    def test_output_includes_separate_momentum_and_vol_components(self) -> None:
        start = date(2024, 1, 1)
        symbols = [f"SYM{i}USDT" for i in range(6)]
        universe = _make_universe([(s, start) for s in symbols])
        prices = _build_price_map_uniform(
            symbols, start, n_days=80,
            daily_log_return=Decimal("0.001"),
        )
        rebalance_at = start + timedelta(days=79)
        out = compute_signal(
            rebalance_at=rebalance_at, universe=universe, prices=prices,
        )
        assert not out.skipped
        assert len(out.scores) == 6
        assert len(out.momentum_components) == 6
        assert len(out.vol_components) == 6
        for sym in symbols:
            expected = out.momentum_components[sym] / out.vol_components[sym]
            assert out.scores[sym] == expected

    def test_bucket_size_is_third_rounded_up_min_1(self) -> None:
        start = date(2024, 1, 1)
        symbols = [f"SYM{i}USDT" for i in range(7)]
        universe = _make_universe([(s, start) for s in symbols])
        prices = {}
        for i, sym in enumerate(symbols):
            r = Decimal("0.001") * Decimal(i + 1)
            prices[sym] = _make_series(sym, start, n_days=80,
                                       base_close=Decimal("100"),
                                       daily_log_return=r)
        rebalance_at = start + timedelta(days=79)
        out = compute_signal(
            rebalance_at=rebalance_at, universe=universe, prices=prices,
        )
        # ceil(7/3) = 3
        assert out.long_bucket_size == 3
        assert out.short_bucket_size == 3
        assert set(out.long_bucket).isdisjoint(set(out.short_bucket))

    def test_min_bucket_size_is_1(self) -> None:
        # N=2 with min_eligible=2 to bypass the operational floor and
        # exercise the ceil(N/3) = 1 path.
        start = date(2024, 1, 1)
        symbols = ["AUSDT", "BUSDT"]
        universe = _make_universe([(s, start) for s in symbols])
        prices = {
            "AUSDT": _make_series("AUSDT", start, 80, Decimal("100"), Decimal("0.001")),
            "BUSDT": _make_series("BUSDT", start, 80, Decimal("100"), Decimal("0.002")),
        }
        rebalance_at = start + timedelta(days=79)
        out = compute_signal(
            rebalance_at=rebalance_at, universe=universe, prices=prices,
            min_eligible=2,
        )
        assert not out.skipped
        # ceil(2/3) = 1
        assert out.long_bucket_size == 1
        assert out.short_bucket_size == 1


class TestComputeSignalExclusions:
    """Exclusion reasons should be specific and traceable."""

    def test_listing_age_insufficient(self) -> None:
        start = date(2024, 1, 1)
        rebalance_at = start + timedelta(days=79)
        old = ("OLD_USDT", start)
        new = ("NEW_USDT", rebalance_at - timedelta(days=30))
        olds = [("OLD2_USDT", start), ("OLD3_USDT", start),
                ("OLD4_USDT", start), ("OLD5_USDT", start)]
        universe = _make_universe([old, new] + olds)
        all_old_symbols = [old[0]] + [o[0] for o in olds]
        prices = _build_price_map_uniform(
            all_old_symbols, start, n_days=80, daily_log_return=Decimal("0.001"),
        )
        prices[new[0]] = _make_series(
            new[0], rebalance_at - timedelta(days=30), n_days=31,
            base_close=Decimal("100"), daily_log_return=Decimal("0.001"),
        )
        out = compute_signal(
            rebalance_at=rebalance_at, universe=universe, prices=prices,
        )
        reasons = {x["symbol"]: x["reason"] for x in out.excluded_symbols}
        assert reasons.get("NEW_USDT") == "listing_age_insufficient"
        assert "OLD_USDT" not in reasons
        assert out.eligible_count == len(all_old_symbols)

    def test_zero_realized_vol(self) -> None:
        start = date(2024, 1, 1)
        symbols = [f"FLAT{i}USDT" for i in range(5)]
        universe = _make_universe([(s, start) for s in symbols])
        prices = _build_price_map_uniform(
            symbols, start, n_days=80, daily_log_return=Decimal(0),
        )
        rebalance_at = start + timedelta(days=79)
        out = compute_signal(
            rebalance_at=rebalance_at, universe=universe, prices=prices,
        )
        reasons = {x["symbol"]: x["reason"] for x in out.excluded_symbols}
        for sym in symbols:
            assert reasons.get(sym) == "zero_realized_vol", (
                f"expected zero_realized_vol for {sym}, got {reasons.get(sym)}"
            )

    def test_missing_vol_window_close(self) -> None:
        start = date(2024, 1, 1)
        symbols = ["GAPUSDT"] + [f"FILL{i}USDT" for i in range(4)]
        universe = _make_universe([(s, start) for s in symbols])
        rebalance_at = start + timedelta(days=79)

        gap_bars: list[PriceBar] = []
        for i in range(80):
            if i == 40:
                continue
            d = start + timedelta(days=i)
            gap_bars.append(PriceBar(bar_date=d, open_price=Decimal("100"),
                                     close_price=Decimal("100")))
        prices = {"GAPUSDT": PriceSeries(symbol="GAPUSDT", bars=gap_bars)}
        for sym in symbols[1:]:
            prices[sym] = _make_series(
                sym, start, n_days=80, base_close=Decimal("100"),
                daily_log_return=Decimal("0.001"),
            )

        out = compute_signal(
            rebalance_at=rebalance_at, universe=universe, prices=prices,
        )
        reasons = {x["symbol"]: x["reason"] for x in out.excluded_symbols}
        assert reasons.get("GAPUSDT") == "missing_vol_window_close"


class TestComputeSignalSkip:
    def test_skip_when_eligible_below_min(self) -> None:
        # Only 3 eligible assets; min_eligible default is 4 ⇒ skip.
        start = date(2024, 1, 1)
        rebalance_at = start + timedelta(days=79)
        universe = _make_universe([
            ("A_USDT", start),
            ("B_USDT", start),
            ("C_USDT", start),
        ])
        prices = _build_price_map_uniform(
            ["A_USDT", "B_USDT", "C_USDT"], start, n_days=80,
            daily_log_return=Decimal("0.001"),
        )
        out = compute_signal(
            rebalance_at=rebalance_at, universe=universe, prices=prices,
        )
        assert out.skipped
        assert out.long_bucket == []
        assert out.short_bucket == []
        assert "eligible_count=3" in out.skip_reason
