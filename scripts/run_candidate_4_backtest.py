#!/usr/bin/env python3
"""Sleeve B candidate #4 — OOS backtest runner.

Volatility-scaled momentum on the frozen top-30 Binance USDT-perps universe.

Per pre-registration at commit 59c1156 and the portfolio interpretation memo
at commit 689ddd9 (Reading A locked: inherit xs-momentum's portfolio-level
vol-targeting overlay).

Hardcoded parameters (all from pre-registration §2.6):
  OOS window:           2023-04-15 to 2026-04-15
  Universe:             tests/fixtures/sleeve_b/universe_top30_20260415.json
  Momentum lookback:    30 days simple return
  Vol lookback:         45 days, sample stdev of daily log returns,
                        annualized by sqrt(365)
  Bucketing:            top-third long, bottom-third short, equal weight
  Rebalance cadence:    weekly (Monday 00:00 UTC)
  Listing-age delay:    45 days (binding lookback)
  Min eligible:         4 (operational floor inherited from xs-momentum)
  Vol target:           15% annualized (portfolio-level, per 689ddd9 Reading A)
  Cold start:           4 weeks (gross_scale = 1.0)
  Trailing vol window:  4 weeks
  Fees:                 14.5 bps round-trip per asset
  Holding:              7 days
  No leverage cap (inherited)

D2 scope: backtest execution, artifact persistence, raw metrics summary.
D2 does NOT compute F1 (D3) or F3 (D4) sub-gates and does NOT classify
the candidate against Stage B promotion thresholds (D5's job).

Run ID: candidate_4_v1 (stable; re-runs produce identical outputs).
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from strategies.sleeve_b.vol_scaled_momentum.backtest import (  # noqa: E402
    BacktestResult,
    RebalanceLog,
    run_backtest,
)
from strategies.sleeve_b.xs_momentum.backtest import WeeklyPnL  # noqa: E402
from strategies.sleeve_b.xs_momentum.prices import (  # noqa: E402
    PriceBar,
    PriceSeries,
)
from strategies.sleeve_b.xs_momentum.universe import (  # noqa: E402
    UniverseAsset,
    load_universe,
)
from data.ingestion.vendors.binance.klines_archive_fetcher import (  # noqa: E402
    BinanceKlinesArchiveFetcher,
)


# --- Pre-registration constants (locked) ---
RUN_ID = "candidate_4_v1"
OOS_START = date(2023, 4, 15)
OOS_END = date(2026, 4, 15)
WEEKS_PER_YEAR = Decimal("52")

# 45-day vol window means we need 46 daily closes back from OOS start.
# Use a 60-day buffer to be safe (matches the operational discipline of
# fetching slightly more than strictly required).
PRICE_BUFFER_DAYS = 60

# --- Paths ---
UNIVERSE_FIXTURE = REPO_ROOT / "tests/fixtures/sleeve_b/universe_top30_20260415.json"
LOG_PATH = REPO_ROOT / "tests/fixtures/sleeve_b/vol_scaled_momentum_run_log.jsonl"
PNL_PATH = REPO_ROOT / "tests/fixtures/sleeve_b/vol_scaled_momentum_weekly_pnl.jsonl"


# --- Price loading ---

def _fetch_window_for_klines(
    symbol: str,
    fetcher: BinanceKlinesArchiveFetcher,
) -> list:
    """Fetch klines for one symbol over OOS window plus vol-buffer."""
    start_dt = datetime.combine(
        OOS_START - timedelta(days=PRICE_BUFFER_DAYS), time(0, 0),
        tzinfo=timezone.utc,
    )
    end_dt = datetime.combine(
        OOS_END + timedelta(days=14), time(0, 0), tzinfo=timezone.utc,
    )
    return fetcher.fetch_window(symbol, start_dt, end_dt)


def _build_price_series(symbol: str, klines: list) -> PriceSeries:
    bars = []
    for k in klines:
        bars.append(PriceBar(
            bar_date=k.open_time.date(),
            open_price=k.open,
            close_price=k.close,
        ))
    return PriceSeries(symbol, bars)


def _load_price_map(universe: list[UniverseAsset]) -> dict:
    fetcher = BinanceKlinesArchiveFetcher(interval="1d")
    prices = {}
    for i, asset in enumerate(universe):
        print(f"  [{i+1}/{len(universe)}] {asset.symbol}...", flush=True)
        klines = _fetch_window_for_klines(asset.symbol, fetcher)
        prices[asset.symbol] = _build_price_series(asset.symbol, klines)
        ps = prices[asset.symbol]
        print(
            f"    {len(klines)} klines, range: {ps.first_date} → {ps.last_date}"
        )
    return prices


# --- Aggregate metrics (raw numbers only; gate classification is D5) ---

def _annualized_sharpe(weekly_pnl_bps: list[Decimal]) -> Decimal | None:
    if len(weekly_pnl_bps) < 2:
        return None
    as_floats = [float(b) / 10000 for b in weekly_pnl_bps]
    mean_w = statistics.mean(as_floats)
    stdev_w = statistics.stdev(as_floats)
    if stdev_w == 0:
        return None
    return Decimal(str((mean_w / stdev_w) * math.sqrt(52)))


def _annualized_return(weekly_pnl_bps: list[Decimal]) -> Decimal:
    if not weekly_pnl_bps:
        return Decimal("0")
    nav = Decimal("1")
    for b in weekly_pnl_bps:
        nav = nav * (Decimal("1") + b / Decimal("10000"))
    n_weeks = Decimal(len(weekly_pnl_bps))
    if n_weeks == 0:
        return Decimal("0")
    years = n_weeks / WEEKS_PER_YEAR
    if years == 0:
        return Decimal("0")
    nav_f = float(nav)
    if nav_f <= 0:
        return Decimal("-1")
    return Decimal(str(nav_f ** (1.0 / float(years)) - 1.0))


def _annualized_volatility(weekly_pnl_bps: list[Decimal]) -> Decimal | None:
    if len(weekly_pnl_bps) < 2:
        return None
    as_floats = [float(b) / 10000 for b in weekly_pnl_bps]
    return Decimal(str(statistics.stdev(as_floats) * math.sqrt(52)))


def _hit_rate(weekly_pnl_bps: list[Decimal]) -> Decimal:
    if not weekly_pnl_bps:
        return Decimal("0")
    wins = sum(1 for b in weekly_pnl_bps if b > 0)
    return Decimal(wins) / Decimal(len(weekly_pnl_bps))


def _compute_max_drawdown(equity_curve_bps: list[Decimal]) -> Decimal:
    """Maximum peak-to-trough drawdown over the equity curve.

    Same NAV-compounding convention as xs-momentum runner.
    """
    if not equity_curve_bps:
        return Decimal("0")
    nav = Decimal("1")
    peak = nav
    max_dd = Decimal("0")
    prev_cum = Decimal("0")
    for cum_bps in equity_curve_bps:
        weekly_bps = cum_bps - prev_cum
        nav = nav * (Decimal("1") + weekly_bps / Decimal("10000"))
        if nav > peak:
            peak = nav
        if peak > 0:
            dd = (peak - nav) / peak
            if dd > max_dd:
                max_dd = dd
        prev_cum = cum_bps
    return max_dd


def _cost_drag_as_pct_of_gross_alpha(
    weekly_pnls: list[WeeklyPnL],
) -> Decimal | None:
    gross_alpha = sum(
        (abs(w.gross_pnl_bps) for w in weekly_pnls), Decimal("0"),
    )
    if gross_alpha == 0:
        return None
    cost_drag = sum((w.fee_drag_bps for w in weekly_pnls), Decimal("0"))
    return cost_drag / gross_alpha


def _compute_btc_eth_weekly_returns(
    prices, rebalance_dates: list[date],
) -> tuple[list, list]:
    btc = prices.get("BTCUSDT")
    eth = prices.get("ETHUSDT")
    if btc is None or eth is None:
        return [], []
    btc_returns = []
    eth_returns = []
    for i in range(1, len(rebalance_dates)):
        prev = rebalance_dates[i - 1]
        curr = rebalance_dates[i]
        btc_prev = btc.close_at(prev)
        btc_curr = btc.close_at(curr)
        eth_prev = eth.close_at(prev)
        eth_curr = eth.close_at(curr)
        if (btc_prev and btc_curr and btc_prev > 0
                and eth_prev and eth_curr and eth_prev > 0):
            btc_returns.append(float((btc_curr - btc_prev) / btc_prev))
            eth_returns.append(float((eth_curr - eth_prev) / eth_prev))
        else:
            btc_returns.append(None)
            eth_returns.append(None)
    return btc_returns, eth_returns


def _univariate_beta(y: list[float], x: list) -> float | None:
    pairs = [(yi, xi) for yi, xi in zip(y, x)
             if yi is not None and xi is not None]
    if len(pairs) < 2:
        return None
    y_arr = [p[0] for p in pairs]
    x_arr = [p[1] for p in pairs]
    x_mean = statistics.mean(x_arr)
    y_mean = statistics.mean(y_arr)
    x_var = sum((xi - x_mean) ** 2 for xi in x_arr)
    if x_var == 0:
        return None
    cov_xy = sum(
        (xi - x_mean) * (yi - y_mean) for xi, yi in zip(x_arr, y_arr)
    )
    return cov_xy / x_var


# --- Output persistence ---

def _persist_run_log(logs: list[RebalanceLog]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("w") as f:
        for log in logs:
            row = {
                "run_id": RUN_ID,
                "rebalance_at": log.rebalance_at.isoformat(),
                "eligible_symbols": log.eligible_symbols,
                "eligible_count": log.eligible_count,
                "skipped": log.skipped,
                "skip_reason": log.skip_reason,
                "long_bucket": log.long_bucket,
                "short_bucket": log.short_bucket,
                "scores": {k: str(v) for k, v in log.scores.items()},
                "momentum_components": {
                    k: str(v) for k, v in log.momentum_components.items()
                },
                "vol_components": {
                    k: str(v) for k, v in log.vol_components.items()
                },
                "long_bucket_size": log.long_bucket_size,
                "short_bucket_size": log.short_bucket_size,
                "portfolio_scale": str(log.portfolio_scale),
                "realized_vol_input": (
                    str(log.realized_vol_input)
                    if log.realized_vol_input is not None else None
                ),
                "gross_notional": str(log.gross_notional),
                "turnover": str(log.turnover),
                "excluded_symbols": log.excluded_symbols,
            }
            f.write(json.dumps(row) + "\n")


def _persist_weekly_pnl(weekly_pnls: list[WeeklyPnL]) -> None:
    PNL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PNL_PATH.open("w") as f:
        for w in weekly_pnls:
            row = {
                "run_id": RUN_ID,
                "week_start": w.week_start.isoformat(),
                "week_end": w.week_end.isoformat(),
                "long_pnl_bps": str(w.long_pnl_bps),
                "short_pnl_bps": str(w.short_pnl_bps),
                "gross_pnl_bps": str(w.gross_pnl_bps),
                "fee_drag_bps": str(w.fee_drag_bps),
                "net_pnl_bps": str(w.net_pnl_bps),
            }
            f.write(json.dumps(row) + "\n")


# --- Main ---

def _format_decimal(v: Decimal | None, precision: int = 4) -> str:
    if v is None:
        return "undefined"
    return f"{float(v):.{precision}f}"


def _format_pct(v: Decimal | None) -> str:
    if v is None:
        return "undefined"
    return f"{float(v):.2%}"


def main() -> int:
    print("=" * 60)
    print("Sleeve B candidate #4 — OOS backtest")
    print("=" * 60)
    print(f"Run ID: {RUN_ID}")
    print(f"OOS window: {OOS_START} → {OOS_END}")
    print()

    print("Loading universe...")
    universe = load_universe(UNIVERSE_FIXTURE)
    print(f"  {len(universe)} assets loaded.")
    print()

    print("Fetching 1d klines for each asset over OOS window + buffer...")
    print(f"(buffer = {PRICE_BUFFER_DAYS} days for 45-day vol window)")
    print("(may take a few minutes depending on cache state)")
    prices = _load_price_map(universe)
    print()

    print("Running backtest...")
    result = run_backtest(
        universe=universe,
        prices=prices,
        start=OOS_START,
        end=OOS_END,
    )
    skipped = sum(1 for log in result.rebalance_logs if log.skipped)
    print(
        f"  {len(result.rebalance_logs)} rebalance dates, "
        f"{skipped} skipped, {len(result.weekly_pnls)} weekly P&L rows."
    )
    print()

    print("Persisting audit logs...")
    _persist_run_log(result.rebalance_logs)
    _persist_weekly_pnl(result.weekly_pnls)
    print(f"  {LOG_PATH.relative_to(REPO_ROOT)}")
    print(f"  {PNL_PATH.relative_to(REPO_ROOT)}")
    print()

    print("Computing raw aggregate metrics (no gate classification — D5's job)...")
    weekly_pnl_bps = [w.net_pnl_bps for w in result.weekly_pnls]
    sharpe = _annualized_sharpe(weekly_pnl_bps)
    ann_return = _annualized_return(weekly_pnl_bps)
    ann_vol = _annualized_volatility(weekly_pnl_bps)
    hit_rate = _hit_rate(weekly_pnl_bps)
    max_dd = _compute_max_drawdown(result.equity_curve_bps())
    cost_drag_pct = _cost_drag_as_pct_of_gross_alpha(result.weekly_pnls)

    rebalance_dates = [log.rebalance_at for log in result.rebalance_logs]
    btc_weekly_returns, eth_weekly_returns = _compute_btc_eth_weekly_returns(
        prices, rebalance_dates,
    )
    strategy_returns_f = [float(b) / 10000 for b in weekly_pnl_bps]
    strategy_for_beta = strategy_returns_f[1:]
    btc_beta = _univariate_beta(strategy_for_beta, btc_weekly_returns)
    eth_beta = _univariate_beta(strategy_for_beta, eth_weekly_returns)

    print()
    print("-" * 60)
    print("Raw OOS metrics (candidate #4):")
    print("-" * 60)
    print(f"  Annualized Sharpe (net):       {_format_decimal(sharpe)}")
    print(f"  Annualized return (net):       {_format_pct(ann_return)}")
    print(f"  Annualized volatility:         {_format_pct(ann_vol)}")
    print(f"  Max drawdown:                  {_format_pct(max_dd)}")
    print(f"  Hit rate (weeks > 0):          {_format_pct(hit_rate)}")
    print(f"  Cost drag (% of gross alpha):  {_format_pct(cost_drag_pct)}")
    print(f"  BTC beta (univariate weekly):  "
          f"{btc_beta:+.4f}" if btc_beta is not None else "  BTC beta: undefined")
    print(f"  ETH beta (univariate weekly):  "
          f"{eth_beta:+.4f}" if eth_beta is not None else "  ETH beta: undefined")
    print()
    print("-" * 60)
    print(f"Total weeks of P&L: {len(weekly_pnl_bps)}")
    print(f"Skipped rebalances: {skipped}")
    print("-" * 60)
    print()
    print("D2 complete. Raw metrics above are not a verdict.")
    print("F1 (D3), F3 (D4), and final gate classification (D5) are")
    print("separate downstream deliverables. Per candidate #4 pre-reg")
    print("§4.B3, promotion under PASS_WARNING requires Sharpe ≥ 1.75")
    print("AND drawdown ≤ 20% AND F1/F3 compliance. Do NOT classify here.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
