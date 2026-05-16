#!/usr/bin/env python3
"""Sleeve B OOS backtest: cross-sectional momentum on top-30 Binance USDT-perps.

Per pre-registration (docs/strategies/sleeve_b_research_preregistration.md,
commit fe909bb), engine spec (commit 11fa64b), and reviewer-locked gate
classification.

Hardcoded parameters (all from pre-registration):
  OOS window:           2023-04-15 to 2026-04-15
  Universe:             tests/fixtures/sleeve_b/universe_top30_20260415.json
  Lookback:             14 days
  Rebalance cadence:    weekly (Monday 00:00 UTC)
  Decile fraction:      10% (variable, min 1) per D9
  Listing-age delay:    14 days per D10
  Min eligible:         4 per D11
  Vol target:           15% annualized
  Cold start:           4 weeks
  Trailing vol window:  4 weeks (~30 days)
  Fees:                 14.5 bps round-trip per asset
  Holding:              7 days

Gate classification (reviewer-locked):
  Sharpe < 0.75:                              Research kill
  Sharpe >= 0.75 AND any constraint fails:    Research kill (fragility)
  0.75 <= Sharpe < 1.5 AND all constraints:   Candidate status
  Sharpe >= 1.5 AND all constraints:          Promotion eligibility

Required simultaneous constraints:
  BTC beta within +/-0.15
  ETH beta within +/-0.15
  max drawdown <= 25%
  cost drag <= 30% of gross alpha
  hit rate >= 45%

Run ID: sleeve_b_xs_momentum_v1 (stable; re-runs produce identical outputs).
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

from strategies.sleeve_b.xs_momentum.backtest import (  # noqa: E402
    BacktestResult,
    RebalanceLog,
    WeeklyPnL,
    run_backtest,
)
from strategies.sleeve_b.xs_momentum.prices import PriceBar, PriceSeries  # noqa: E402
from strategies.sleeve_b.xs_momentum.universe import (  # noqa: E402
    UniverseAsset,
    load_universe,
)
from data.ingestion.vendors.binance.klines_archive_fetcher import (  # noqa: E402
    BinanceKlinesArchiveFetcher,
)

# Pre-registration constants (locked)
RUN_ID = "sleeve_b_xs_momentum_v1"
OOS_START = date(2023, 4, 15)
OOS_END = date(2026, 4, 15)
WEEKS_PER_YEAR = Decimal("52")

# Gate thresholds (reviewer-locked)
GATE_RESEARCH_KILL = Decimal("0.75")
GATE_PROMOTION = Decimal("1.5")
CONSTRAINT_BETA_LIMIT = Decimal("0.15")
CONSTRAINT_MAX_DD = Decimal("0.25")
CONSTRAINT_COST_DRAG = Decimal("0.30")
CONSTRAINT_HIT_RATE = Decimal("0.45")

# Output paths
UNIVERSE_FIXTURE = REPO_ROOT / "tests/fixtures/sleeve_b/universe_top30_20260415.json"
LOG_PATH = REPO_ROOT / "tests/fixtures/sleeve_b/xs_momentum_run_log.jsonl"
PNL_PATH = REPO_ROOT / "tests/fixtures/sleeve_b/xs_momentum_weekly_pnl.jsonl"
MEMO_PATH = REPO_ROOT / "docs/strategies/sleeve_b_xs_momentum_result.md"
PREREG_PATH = REPO_ROOT / "docs/strategies/sleeve_b_research_preregistration.md"


def _fetch_window_for_klines(symbol: str, fetcher: BinanceKlinesArchiveFetcher) -> list:
    """Fetch klines for one symbol over the OOS window (plus 14-day lookback buffer)."""
    # Need lookback days BEFORE OOS_START for first rebalance's trailing return
    buffer_days = 21
    start_dt = datetime.combine(
        OOS_START - timedelta(days=buffer_days), time(0, 0), tzinfo=timezone.utc,
    )
    end_dt = datetime.combine(
        OOS_END + timedelta(days=14), time(0, 0), tzinfo=timezone.utc,
    )
    return fetcher.fetch_window(symbol, start_dt, end_dt)


def _build_price_series(symbol: str, klines: list) -> PriceSeries:
    """Convert BinanceKline list into PriceSeries."""
    bars = []
    for k in klines:
        bars.append(PriceBar(
            bar_date=k.open_time.date(),
            open_price=k.open,
            close_price=k.close,
        ))
    return PriceSeries(symbol, bars)


def _load_price_map(universe: list[UniverseAsset]) -> dict:
    """Fetch klines for every universe asset and build a PriceMap."""
    fetcher = BinanceKlinesArchiveFetcher(interval="1d")
    prices = {}
    for i, asset in enumerate(universe):
        print(f"  [{i+1}/{len(universe)}] {asset.symbol}...", flush=True)
        klines = _fetch_window_for_klines(asset.symbol, fetcher)
        prices[asset.symbol] = _build_price_series(asset.symbol, klines)
        print(
            f"    {len(klines)} klines fetched, "
            f"range: {prices[asset.symbol].first_date} → "
            f"{prices[asset.symbol].last_date}"
        )
    return prices


def _compute_btc_eth_weekly_returns(prices, weekly_dates: list[date]) -> tuple[list, list]:
    """Compute weekly close-to-close returns for BTC and ETH on the rebalance grid."""
    btc = prices.get("BTCUSDT")
    eth = prices.get("ETHUSDT")
    if btc is None or eth is None:
        return [], []
    btc_returns = []
    eth_returns = []
    for i in range(1, len(weekly_dates)):
        prev = weekly_dates[i - 1]
        curr = weekly_dates[i]
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


def _univariate_beta(y: list[float], x: list[float]) -> float | None:
    """Beta of y on x via simple OLS: beta = cov(x,y) / var(x).

    Returns None if x has zero variance or insufficient samples.
    """
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
    cov_xy = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x_arr, y_arr))
    return cov_xy / x_var


def _compute_max_drawdown(equity_curve_bps: list[Decimal]) -> Decimal:
    """Maximum peak-to-trough drawdown over the equity curve.

    The equity curve is in bps (cumulative net P&L). Drawdown is expressed
    as a positive fraction of peak equity (which in this representation is
    relative to a notional starting point of 0; equity can go negative).

    For Sharpe / drawdown reporting we treat the equity as a series where
    starting NAV = 1.0 and each weekly net P&L (in bps) compounds:
      NAV_t = NAV_{t-1} * (1 + net_pnl_bps_t / 10000)

    Then max DD = max over t of (peak_NAV_so_far - NAV_t) / peak_NAV_so_far.
    """
    if not equity_curve_bps:
        return Decimal("0")
    nav = Decimal("1")
    peak = nav
    max_dd = Decimal("0")
    # equity_curve_bps is cumulative; need weekly increments
    # Build NAV path from increments
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


def _annualized_sharpe(weekly_pnl_bps: list[Decimal]) -> Decimal | None:
    """Annualized Sharpe from weekly net P&L in bps.

    Sharpe = (mean weekly return / weekly stdev) * sqrt(52).
    Returns None if stdev is zero or insufficient samples.
    """
    if len(weekly_pnl_bps) < 2:
        return None
    as_floats = [float(b) / 10000 for b in weekly_pnl_bps]
    mean_w = statistics.mean(as_floats)
    stdev_w = statistics.stdev(as_floats)
    if stdev_w == 0:
        return None
    weekly_sharpe = mean_w / stdev_w
    return Decimal(str(weekly_sharpe * math.sqrt(52)))


def _annualized_return(weekly_pnl_bps: list[Decimal]) -> Decimal:
    """Annualized net return from weekly P&L bps.

    Compounded: (prod(1 + r_t) - 1) annualized.
    """
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
    # Annualized = (NAV ^ (1/years) - 1)
    nav_f = float(nav)
    years_f = float(years)
    if nav_f <= 0:
        return Decimal("-1")  # total loss; report -100%
    ann = nav_f ** (1.0 / years_f) - 1.0
    return Decimal(str(ann))


def _annualized_volatility(weekly_pnl_bps: list[Decimal]) -> Decimal | None:
    if len(weekly_pnl_bps) < 2:
        return None
    as_floats = [float(b) / 10000 for b in weekly_pnl_bps]
    stdev_w = statistics.stdev(as_floats)
    return Decimal(str(stdev_w * math.sqrt(52)))


def _hit_rate(weekly_pnl_bps: list[Decimal]) -> Decimal:
    if not weekly_pnl_bps:
        return Decimal("0")
    wins = sum(1 for b in weekly_pnl_bps if b > 0)
    return Decimal(wins) / Decimal(len(weekly_pnl_bps))


def _cost_drag_as_pct_of_gross_alpha(
    weekly_pnls: list[WeeklyPnL],
) -> Decimal | None:
    """Cost drag as fraction of gross alpha.

    gross_alpha = sum of |gross_pnl_bps| (the absolute magnitudes attributable
    to signal, before fees). cost_drag = sum of fee_drag_bps.

    Per pre-registration §B.3: cost drag <= 30% of gross alpha.
    """
    gross_alpha = sum(
        (abs(w.gross_pnl_bps) for w in weekly_pnls), Decimal("0"),
    )
    if gross_alpha == 0:
        return None
    cost_drag = sum((w.fee_drag_bps for w in weekly_pnls), Decimal("0"))
    return cost_drag / gross_alpha


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
                "long_returns_bps": {k: str(v) for k, v in log.long_returns_bps.items()},
                "short_returns_bps": {k: str(v) for k, v in log.short_returns_bps.items()},
                "decile_size": log.decile_size,
                "portfolio_scale": str(log.portfolio_scale),
                "realized_vol_input": (
                    str(log.realized_vol_input) if log.realized_vol_input else None
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


def _classify_gate(
    *,
    sharpe: Decimal | None,
    btc_beta: float | None,
    eth_beta: float | None,
    max_dd: Decimal,
    cost_drag_pct: Decimal | None,
    hit_rate: Decimal,
) -> tuple[str, str, dict]:
    """Apply reviewer-locked gate classification.

    Returns (classification, primary_decision_text, constraint_details).
    """
    constraints = {
        "btc_beta": {
            "value": btc_beta,
            "limit": float(CONSTRAINT_BETA_LIMIT),
            "pass": (btc_beta is not None
                     and abs(btc_beta) <= float(CONSTRAINT_BETA_LIMIT)),
        },
        "eth_beta": {
            "value": eth_beta,
            "limit": float(CONSTRAINT_BETA_LIMIT),
            "pass": (eth_beta is not None
                     and abs(eth_beta) <= float(CONSTRAINT_BETA_LIMIT)),
        },
        "max_drawdown": {
            "value": float(max_dd),
            "limit": float(CONSTRAINT_MAX_DD),
            "pass": max_dd <= CONSTRAINT_MAX_DD,
        },
        "cost_drag_pct_of_gross_alpha": {
            "value": float(cost_drag_pct) if cost_drag_pct is not None else None,
            "limit": float(CONSTRAINT_COST_DRAG),
            "pass": (cost_drag_pct is not None
                     and cost_drag_pct <= CONSTRAINT_COST_DRAG),
        },
        "hit_rate": {
            "value": float(hit_rate),
            "limit": float(CONSTRAINT_HIT_RATE),
            "pass": hit_rate >= CONSTRAINT_HIT_RATE,
        },
    }
    all_constraints_pass = all(c["pass"] for c in constraints.values())

    if sharpe is None:
        return (
            "RESEARCH_KILL",
            "Sharpe undefined (insufficient samples or zero variance). "
            "Family shelved.",
            constraints,
        )
    if sharpe < GATE_RESEARCH_KILL:
        return (
            "RESEARCH_KILL",
            f"Sharpe {float(sharpe):.3f} < {float(GATE_RESEARCH_KILL):.2f}. "
            f"Family shelved per pre-registration Gate 1.",
            constraints,
        )
    if not all_constraints_pass:
        failed = [k for k, v in constraints.items() if not v["pass"]]
        return (
            "RESEARCH_KILL",
            f"Sharpe {float(sharpe):.3f} clears the Sharpe gate but the "
            f"following simultaneous constraints failed: {', '.join(failed)}. "
            f"Family shelved due to construction fragility per "
            f"pre-registration Section 5.",
            constraints,
        )
    if sharpe < GATE_PROMOTION:
        return (
            "CANDIDATE_STATUS",
            f"Sharpe {float(sharpe):.3f} in [0.75, 1.5) and all simultaneous "
            f"constraints pass. Candidate status granted per pre-registration "
            f"Gate 2. Constrained-research only per Section 6.",
            constraints,
        )
    return (
        "PROMOTION_ELIGIBLE",
        f"Sharpe {float(sharpe):.3f} >= 1.5 and all simultaneous constraints "
        f"pass. Promotion eligibility cleared per pre-registration Gate 3. "
        f"Initiate Appendix B research-to-paper review.",
        constraints,
    )


def _write_memo(
    *,
    universe: list[UniverseAsset],
    result: BacktestResult,
    metrics: dict,
    classification: str,
    decision_text: str,
    constraints: dict,
    skipped_count: int,
) -> None:
    lines = []
    lines.append("# Sleeve B Cross-Sectional Momentum — OOS Backtest Result")
    lines.append("")
    lines.append(f"Generated: {datetime.now(tz=timezone.utc).isoformat()}")
    lines.append(f"Run ID: `{RUN_ID}`")
    lines.append(f"Pre-registration: `docs/strategies/sleeve_b_research_preregistration.md` (commit fe909bb)")
    lines.append(f"Universe fixture: `tests/fixtures/sleeve_b/universe_top30_20260415.json` (commit 2af9981)")
    lines.append(f"Engine: commit 11fa64b")
    lines.append("")
    lines.append("## Survivorship-bias disclosure")
    lines.append("")
    lines.append(
        "The universe is the top-30 by ADV **as of 2026-04-15**, applied retroactively "
        "to a 36-month OOS window. Assets that were top-30 earlier in the window but "
        "had failed by 2026 are not in this test. This is survivorship bias by "
        "construction. The result answers: *would the assets that became top-30 by "
        "2026-04-15 have exhibited momentum alpha historically?* It does not answer "
        "*what was the real tradeable top-30 at every historical point*."
    )
    lines.append("")
    lines.append("## Configuration")
    lines.append("")
    lines.append(f"- OOS window: {OOS_START} → {OOS_END} (36 months)")
    lines.append(f"- Universe: top-30 Binance USDT-perps by ADV (frozen)")
    lines.append(f"- Lookback: 14 days close-to-close at 00:00 UTC")
    lines.append(f"- Rebalance: Monday 00:00 UTC, weekly")
    lines.append(f"- Decile fraction: 10%, variable, min 1 (D9)")
    lines.append(f"- Listing-age delay: 14 days (D10)")
    lines.append(f"- Min eligible: 4 (D11)")
    lines.append(f"- Vol target: 15% annualized")
    lines.append(f"- Cold start: 4 weeks (uniform scale = 1.0)")
    lines.append(f"- Fees: 14.5 bps round-trip per asset")
    lines.append(f"- Holding: 7 days")
    lines.append(f"- No leverage cap (documented)")
    lines.append("")
    lines.append("## Run summary")
    lines.append("")
    lines.append(f"- Total rebalance dates: {len(result.rebalance_logs)}")
    lines.append(f"- Rebalances executed: {len(result.rebalance_logs) - skipped_count}")
    lines.append(f"- Rebalances skipped (eligible < 4): {skipped_count}")
    lines.append(f"- Total weeks of P&L: {len(result.weekly_pnls)}")
    lines.append("")
    lines.append("## Primary metrics")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    sharpe = metrics["sharpe"]
    sharpe_str = f"{float(sharpe):.3f}" if sharpe is not None else "undefined"
    lines.append(f"| **Annualized Sharpe (net)** | **{sharpe_str}** |")
    lines.append(f"| Annualized return (net) | {float(metrics['ann_return']):.2%} |")
    ann_vol = metrics["ann_vol"]
    ann_vol_str = f"{float(ann_vol):.2%}" if ann_vol is not None else "undefined"
    lines.append(f"| Annualized volatility | {ann_vol_str} |")
    lines.append(f"| Max drawdown | {float(metrics['max_dd']):.2%} |")
    lines.append(f"| Hit rate (weeks > 0) | {float(metrics['hit_rate']):.2%} |")
    cost_drag = metrics["cost_drag_pct"]
    cost_drag_str = (
        f"{float(cost_drag):.2%}" if cost_drag is not None else "undefined"
    )
    lines.append(f"| Cost drag (% of gross alpha) | {cost_drag_str} |")
    btc_beta = metrics["btc_beta"]
    eth_beta = metrics["eth_beta"]
    btc_beta_str = f"{btc_beta:+.3f}" if btc_beta is not None else "undefined"
    eth_beta_str = f"{eth_beta:+.3f}" if eth_beta is not None else "undefined"
    lines.append(f"| Beta to BTC (univariate weekly) | {btc_beta_str} |")
    lines.append(f"| Beta to ETH (univariate weekly) | {eth_beta_str} |")
    lines.append("")
    lines.append("## Gate outcome")
    lines.append("")
    lines.append(f"**Classification: `{classification}`**")
    lines.append("")
    lines.append(decision_text)
    lines.append("")
    lines.append("### Primary Sharpe gate result")
    lines.append("")
    lines.append("| Gate | Threshold | Actual | Pass |")
    lines.append("|---|---|---|---|")
    sharpe_pass_kill = sharpe is not None and sharpe >= GATE_RESEARCH_KILL
    sharpe_pass_promo = sharpe is not None and sharpe >= GATE_PROMOTION
    lines.append(
        f"| Research kill (must clear) | Sharpe >= {float(GATE_RESEARCH_KILL):.2f} | "
        f"{sharpe_str} | {'YES' if sharpe_pass_kill else 'NO'} |"
    )
    lines.append(
        f"| Promotion eligibility | Sharpe >= {float(GATE_PROMOTION):.1f} | "
        f"{sharpe_str} | {'YES' if sharpe_pass_promo else 'NO'} |"
    )
    lines.append("")
    lines.append("### Constraint pass/fail table")
    lines.append("")
    lines.append("| Constraint | Limit | Actual | Pass |")
    lines.append("|---|---|---|---|")
    for key, c in constraints.items():
        val = c["value"]
        if val is None:
            val_str = "undefined"
        elif key in ("btc_beta", "eth_beta"):
            val_str = f"{val:+.3f}"
        elif key in ("max_drawdown", "cost_drag_pct_of_gross_alpha", "hit_rate"):
            val_str = f"{val:.2%}"
        else:
            val_str = str(val)
        if key == "hit_rate":
            limit_str = f">= {c['limit']:.0%}"
        elif key in ("btc_beta", "eth_beta"):
            limit_str = f"within +/- {c['limit']:.2f}"
        else:
            limit_str = f"<= {c['limit']:.0%}"
        pass_str = "YES" if c["pass"] else "**NO**"
        lines.append(f"| {key} | {limit_str} | {val_str} | {pass_str} |")
    lines.append("")
    lines.append("### Final classification")
    lines.append("")
    lines.append(f"**`{classification}`**")
    lines.append("")
    if classification == "RESEARCH_KILL":
        lines.append(
            "Per pre-registration anti-cherry-pick rule, this result is "
            "binding. No further work on cross-sectional momentum under this "
            "specification. Alternate hypotheses (different lookback, different "
            "universe, different construction) constitute separately pre-"
            "registered hypotheses with their own budgets and kill criteria, "
            "and they cannot use this run's data as in-sample evidence."
        )
    elif classification == "CANDIDATE_STATUS":
        lines.append(
            "Candidate status grants constrained-research activities only "
            "(replication, robustness checks, alternate OOS slices, stress "
            "decomposition, implementation realism). Parameter tuning, "
            "universe changes, rebalance changes, threshold changes, and "
            "feature additions are forbidden per Section 6 without a new "
            "pre-registration."
        )
    elif classification == "PROMOTION_ELIGIBLE":
        lines.append(
            "Initiate Appendix B research-to-paper review per roadmap v2.2. "
            "The construction proceeds to paper testing on the production "
            "OMS/risk/ledger path. Note: this is the first such result the "
            "framework has produced; treat with appropriate caution."
        )
    lines.append("")
    lines.append("## Artifacts")
    lines.append("")
    lines.append(f"- Run log: `tests/fixtures/sleeve_b/xs_momentum_run_log.jsonl`")
    lines.append(f"- Weekly P&L: `tests/fixtures/sleeve_b/xs_momentum_weekly_pnl.jsonl`")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        f"*This result is binding per the pre-registration. The clock "
        f"continues for the remaining Sleeve B research budget (default "
        f"kill date 2026-06-27).*"
    )

    MEMO_PATH.parent.mkdir(parents=True, exist_ok=True)
    MEMO_PATH.write_text("\n".join(lines))


def main() -> None:
    print("Sleeve B OOS backtest")
    print("=" * 60)
    print(f"Run ID: {RUN_ID}")
    print(f"OOS window: {OOS_START} → {OOS_END}")
    print()

    print("Loading universe...")
    universe = load_universe(UNIVERSE_FIXTURE)
    print(f"  {len(universe)} assets loaded.")
    print()

    print("Fetching 1d klines for each asset over OOS window...")
    print("(may take 10-40 minutes depending on cache state)")
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
    print(f"  {LOG_PATH}")
    print(f"  {PNL_PATH}")
    print()

    print("Computing aggregate metrics...")
    weekly_pnl_bps = [w.net_pnl_bps for w in result.weekly_pnls]
    sharpe = _annualized_sharpe(weekly_pnl_bps)
    ann_return = _annualized_return(weekly_pnl_bps)
    ann_vol = _annualized_volatility(weekly_pnl_bps)
    max_dd = _compute_max_drawdown(result.equity_curve_bps())
    hit_rate = _hit_rate(weekly_pnl_bps)
    cost_drag_pct = _cost_drag_as_pct_of_gross_alpha(result.weekly_pnls)

    # BTC/ETH beta on weekly grid
    rebalance_dates = [log.rebalance_at for log in result.rebalance_logs]
    btc_weekly_returns, eth_weekly_returns = _compute_btc_eth_weekly_returns(
        prices, rebalance_dates,
    )
    strategy_returns_f = [float(b) / 10000 for b in weekly_pnl_bps]
    # Align: strategy_returns has len == len(weekly_pnls) which == len(rebalance_dates)
    # BTC/ETH returns are len - 1 (first rebalance has no return). Drop first strategy return.
    strategy_for_beta = strategy_returns_f[1:]
    btc_beta = _univariate_beta(strategy_for_beta, btc_weekly_returns)
    eth_beta = _univariate_beta(strategy_for_beta, eth_weekly_returns)

    metrics = {
        "sharpe": sharpe,
        "ann_return": ann_return,
        "ann_vol": ann_vol,
        "max_dd": max_dd,
        "hit_rate": hit_rate,
        "cost_drag_pct": cost_drag_pct,
        "btc_beta": btc_beta,
        "eth_beta": eth_beta,
    }

    print(f"  Sharpe (annualized, net): {sharpe}")
    print(f"  Annualized return:        {ann_return}")
    print(f"  Annualized volatility:    {ann_vol}")
    print(f"  Max drawdown:             {max_dd}")
    print(f"  Hit rate:                 {hit_rate}")
    print(f"  Cost drag pct:            {cost_drag_pct}")
    print(f"  BTC beta:                 {btc_beta}")
    print(f"  ETH beta:                 {eth_beta}")
    print()

    print("Applying gate classification...")
    classification, decision_text, constraints = _classify_gate(
        sharpe=sharpe,
        btc_beta=btc_beta,
        eth_beta=eth_beta,
        max_dd=max_dd,
        cost_drag_pct=cost_drag_pct,
        hit_rate=hit_rate,
    )
    print(f"  Classification: {classification}")
    print(f"  {decision_text}")
    print()

    print(f"Writing memo to {MEMO_PATH.relative_to(REPO_ROOT)}...")
    _write_memo(
        universe=universe,
        result=result,
        metrics=metrics,
        classification=classification,
        decision_text=decision_text,
        constraints=constraints,
        skipped_count=skipped,
    )
    size = MEMO_PATH.stat().st_size
    print(f"  Memo written: {size:,} bytes")
    print()

    print("=" * 60)
    print(f"FINAL: {classification}")
    print("=" * 60)


if __name__ == "__main__":
    main()
