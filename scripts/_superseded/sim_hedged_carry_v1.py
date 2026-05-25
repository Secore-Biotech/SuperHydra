"""Minimum viable hedged-carry simulator for BTC.

Simulates short BTC perp + long BTC spot, delta-hedged at every funding
event, over the 3-year OOS window. Real strategy backtest with three
P&L sources (funding receipts, perp price moves, spot price moves) and
realistic execution costs.

This is the FIRST real strategy test of the funding-carry thesis.
Prior exploration scripts (explore_stress_state_on_candidate_4.py,
explore_continuous_carry_rules.py) tested simplified models with
known biases. This script removes the "perfect carry capture, free
hedge" idealization that produced misleading Sharpe ~12 in the prior run.

NOT a candidate. NOT pre-registered. NOT governance.

Design

  Universe:        BTC only
  Cadence:         8h funding events (3 per UTC day)
  Price source:    1d klines for both perp and spot (intraday assumed
                   constant within each UTC day — approximation)
  Position rule:   short perp $10k + long spot $10k, rebalanced every
                   funding event to keep notional equal
  Cost model:      12 bps round trip per leg per rebalance (4 bps fee
                   + 2 bps slippage, both sides)
  Window:          2023-04-15 → 2026-04-15 (OOS window)

Decision criteria (LOCKED, same as prior exploration runs)

  Annualized Sharpe         ≥ +1.00
  Max drawdown              ≤ 15% of notional
  Worst single-day return   ≥ -1.5% of notional
  Worst 5-day return        ≥ -3.0% of notional

Caveats

  - Intraday price approximation: within each UTC day, all three
    funding events use the same daily close price. Real intraday
    prices fluctuate; this approximation likely undermeasures
    rebalance gain/loss within a day. Higher-frequency price data
    would refine the result; the directional conclusion should be
    robust to the approximation.
  - Cost model is conservative-realistic, not pessimistic-realistic.
    Adversarial slippage during stress periods is not modeled.
  - Funding-rate prediction error is zero by construction (uses
    actual realized funding). Live strategies face prediction risk.
  - No margin or collateral mechanics. Real strategies face liquidation
    risk on the perp leg during sharp moves.

Usage

    python scripts/sim_hedged_carry_v1.py
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data.ingestion.vendors.binance.klines_archive_fetcher import (
    BinanceKlinesArchiveFetcher,
)
from data.ingestion.vendors.binance.klines_archive_spot_fetcher import (
    BinanceKlinesArchiveSpotFetcher,
)


# ─── Configuration ────────────────────────────────────────────────────────

FUNDING_CACHE = REPO_ROOT / "artifacts" / "cache" / "btc_funding_explore.json"

NOTIONAL_PER_LEG = Decimal("10000")  # $10k per leg = $20k gross exposure
ROUND_TRIP_COST_BPS = Decimal("12")   # 4 bps fee + 2 bps slippage, per side, both directions

WINDOW_START = datetime(2023, 4, 15, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 4, 15, tzinfo=timezone.utc)

DAYS_PER_YEAR = 365


# ─── Load all three data series ───────────────────────────────────────────

def load_funding() -> list[dict]:
    """Load cached BTC funding records, filtered to OOS window."""
    if not FUNDING_CACHE.exists():
        print(f"ERROR: funding cache not found at {FUNDING_CACHE}")
        sys.exit(1)
    with FUNDING_CACHE.open() as f:
        raw = json.load(f)
    records = []
    for r in raw:
        t = datetime.fromisoformat(r["time"])
        if WINDOW_START <= t < WINDOW_END:
            records.append({"time": t, "rate": Decimal(r["rate"])})
    records.sort(key=lambda r: r["time"])
    return records


def load_perp_klines() -> dict[datetime, Decimal]:
    """Load BTC perp 1d closes from cached archive. Returns {date_utc → close_price}."""
    fetcher = BinanceKlinesArchiveFetcher(interval="1d")
    klines = fetcher.fetch_window("BTCUSDT", WINDOW_START, WINDOW_END)
    return {
        k.open_time.replace(hour=0, minute=0, second=0, microsecond=0): k.close
        for k in klines
    }


def load_spot_klines() -> dict[datetime, Decimal]:
    """Load BTC spot 1d closes from cached archive. Returns {date_utc → close_price}."""
    fetcher = BinanceKlinesArchiveSpotFetcher(interval="1d")
    klines = fetcher.fetch_window("BTCUSDT", WINDOW_START, WINDOW_END)
    return {
        k.open_time.replace(hour=0, minute=0, second=0, microsecond=0): k.close
        for k in klines
    }


# ─── Simulator ────────────────────────────────────────────────────────────

def simulate(
    funding: list[dict],
    perp_prices: dict[datetime, Decimal],
    spot_prices: dict[datetime, Decimal],
) -> dict:
    """Walk through funding events. Maintain short perp + long spot legs
    rebalanced to $10k each at every event. Compute P&L across three
    sources plus cost.

    Returns a dict with per-event and aggregate metrics.
    """
    event_records = []  # one row per funding event

    # State
    # Quantities (in BTC) of perp short and spot long. Negative = short, positive = long.
    perp_qty = Decimal("0")
    spot_qty = Decimal("0")
    # Last prices seen (for P&L attribution between events)
    last_perp_price: Decimal | None = None
    last_spot_price: Decimal | None = None

    skipped_events = 0

    for rec in funding:
        event_time = rec["time"]
        rate = rec["rate"]
        day_key = event_time.replace(hour=0, minute=0, second=0, microsecond=0)

        # Price lookup. If a day is missing in either series, skip the event.
        perp_p = perp_prices.get(day_key)
        spot_p = spot_prices.get(day_key)
        if perp_p is None or spot_p is None:
            skipped_events += 1
            continue

        # P&L from price moves on existing position since last event
        if last_perp_price is not None and last_spot_price is not None:
            perp_price_pnl = perp_qty * (perp_p - last_perp_price)
            spot_price_pnl = spot_qty * (spot_p - last_spot_price)
        else:
            perp_price_pnl = Decimal("0")
            spot_price_pnl = Decimal("0")

        # Funding P&L: short receives positive funding.
        # perp_qty < 0 for short. funding_pnl = -perp_qty × notional × rate? No:
        # If short 0.1 BTC perp and rate is +0.01%, funding received in USD =
        # 0.1 × perp_price × 0.0001 = 1 USD per BTC × notional.
        # So funding_pnl = -perp_qty × perp_p × rate (negative perp_qty × +rate = positive P&L)
        funding_pnl = -perp_qty * perp_p * rate

        # Rebalance: target perp short and spot long, each $NOTIONAL_PER_LEG.
        # perp target qty = -NOTIONAL / perp_p   (negative = short)
        # spot target qty = +NOTIONAL / spot_p
        target_perp_qty = -NOTIONAL_PER_LEG / perp_p
        target_spot_qty = NOTIONAL_PER_LEG / spot_p

        # Cost from quantity changes (each side full round-trip cost is bps_per_side × 2)
        # Cost on each leg's change is: abs(qty_change) × price × bps / 10000 / 2
        # (full round trip = both directions; size of change = 1.0 of notional = 1 round trip)
        perp_qty_change = target_perp_qty - perp_qty
        spot_qty_change = target_spot_qty - spot_qty

        perp_rebalance_cost = (
            abs(perp_qty_change) * perp_p * ROUND_TRIP_COST_BPS
            / Decimal("10000") / Decimal("2")
        )
        spot_rebalance_cost = (
            abs(spot_qty_change) * spot_p * ROUND_TRIP_COST_BPS
            / Decimal("10000") / Decimal("2")
        )
        total_cost = perp_rebalance_cost + spot_rebalance_cost

        # Apply rebalance
        perp_qty = target_perp_qty
        spot_qty = target_spot_qty

        # Total event P&L
        event_pnl = funding_pnl + perp_price_pnl + spot_price_pnl - total_cost

        event_records.append({
            "time": event_time,
            "perp_price": perp_p,
            "spot_price": spot_p,
            "funding_rate": rate,
            "funding_pnl": funding_pnl,
            "perp_price_pnl": perp_price_pnl,
            "spot_price_pnl": spot_price_pnl,
            "total_cost": total_cost,
            "event_pnl": event_pnl,
        })

        last_perp_price = perp_p
        last_spot_price = spot_p

    return {
        "event_records": event_records,
        "skipped_events": skipped_events,
    }


# ─── Aggregation and metrics ──────────────────────────────────────────────

def aggregate_to_daily(event_records: list[dict]) -> list[tuple[datetime, dict]]:
    """Aggregate 8h events to per-day totals. Returns sorted list of
    (day, {funding_pnl, perp_pnl, spot_pnl, cost, total})."""
    by_day: dict[datetime, dict] = {}
    for rec in event_records:
        day = rec["time"].replace(hour=0, minute=0, second=0, microsecond=0)
        if day not in by_day:
            by_day[day] = {
                "funding_pnl": Decimal("0"), "perp_pnl": Decimal("0"),
                "spot_pnl": Decimal("0"), "cost": Decimal("0"),
                "total": Decimal("0"),
            }
        d = by_day[day]
        d["funding_pnl"] += rec["funding_pnl"]
        d["perp_pnl"] += rec["perp_price_pnl"]
        d["spot_pnl"] += rec["spot_price_pnl"]
        d["cost"] += rec["total_cost"]
        d["total"] += rec["event_pnl"]
    return sorted(by_day.items())


def annualized_sharpe(daily_total_pnl: list[Decimal]) -> float:
    if len(daily_total_pnl) < 2:
        return float("nan")
    # Express as fraction of GROSS notional ($20k = $10k each leg)
    gross_notional = float(NOTIONAL_PER_LEG * 2)
    fracs = [float(p) / gross_notional for p in daily_total_pnl]
    n = len(fracs)
    mean = sum(fracs) / n
    var = sum((x - mean) ** 2 for x in fracs) / (n - 1)
    if var <= 0:
        return float("nan")
    std = math.sqrt(var)
    return (mean / std) * math.sqrt(DAYS_PER_YEAR)


def annualized_return(daily_total_pnl: list[Decimal]) -> float:
    gross_notional = float(NOTIONAL_PER_LEG * 2)
    total = float(sum(daily_total_pnl, Decimal("0"))) / gross_notional
    n_days = len(daily_total_pnl)
    if n_days == 0:
        return float("nan")
    return total * DAYS_PER_YEAR / n_days


def max_drawdown(daily_total_pnl: list[Decimal]) -> float:
    gross_notional = float(NOTIONAL_PER_LEG * 2)
    cum = Decimal("0")
    peak = Decimal("0")
    max_dd = Decimal("0")
    for p in daily_total_pnl:
        cum += p
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd
    return float(max_dd) / gross_notional


def worst_n_day(daily_total_pnl: list[Decimal], n: int) -> float:
    gross_notional = float(NOTIONAL_PER_LEG * 2)
    if len(daily_total_pnl) < n:
        return float("nan")
    running = sum(daily_total_pnl[:n], Decimal("0"))
    worst = running
    for i in range(n, len(daily_total_pnl)):
        running = running - daily_total_pnl[i - n] + daily_total_pnl[i]
        if running < worst:
            worst = running
    return float(worst) / gross_notional


# ─── Main ─────────────────────────────────────────────────────────────────

def main() -> int:
    print("=" * 88)
    print("Minimum viable hedged-carry simulator")
    print("=" * 88)
    print()
    print(f"Window:               {WINDOW_START.date()} → {WINDOW_END.date()}")
    print(f"Notional per leg:     ${NOTIONAL_PER_LEG}")
    print(f"Gross exposure:       ${NOTIONAL_PER_LEG * 2}")
    print(f"Round-trip cost/leg:  {ROUND_TRIP_COST_BPS} bps per rebalance")
    print(f"Rebalance frequency:  every funding event (3x daily)")
    print()

    print("Loading data...")
    funding = load_funding()
    print(f"  Funding events:    {len(funding)}")
    perp_prices = load_perp_klines()
    print(f"  Perp daily bars:   {len(perp_prices)}")
    spot_prices = load_spot_klines()
    print(f"  Spot daily bars:   {len(spot_prices)}")
    print()

    if not (len(perp_prices) > 1000 and len(spot_prices) > 1000):
        print("ERROR: insufficient price data. Run prefetch first.")
        return 1

    print("Running simulation...")
    result = simulate(funding, perp_prices, spot_prices)
    n_events = len(result["event_records"])
    n_skipped = result["skipped_events"]
    print(f"  Events processed:  {n_events}")
    print(f"  Events skipped:    {n_skipped} (missing price data)")
    print()

    daily = aggregate_to_daily(result["event_records"])
    n_days = len(daily)
    daily_total = [d["total"] for _, d in daily]
    daily_funding = [d["funding_pnl"] for _, d in daily]
    daily_perp = [d["perp_pnl"] for _, d in daily]
    daily_spot = [d["spot_pnl"] for _, d in daily]
    daily_cost = [d["cost"] for _, d in daily]

    gross_notional = float(NOTIONAL_PER_LEG * 2)
    total_funding = float(sum(daily_funding, Decimal("0")))
    total_perp = float(sum(daily_perp, Decimal("0")))
    total_spot = float(sum(daily_spot, Decimal("0")))
    total_cost = float(sum(daily_cost, Decimal("0")))
    total_net = float(sum(daily_total, Decimal("0")))

    ann_ret = annualized_return(daily_total)
    sharpe = annualized_sharpe(daily_total)
    mdd = max_drawdown(daily_total)
    w1d = worst_n_day(daily_total, 1)
    w5d = worst_n_day(daily_total, 5)

    print("P&L attribution (dollar amounts, full window)")
    print(f"  Funding receipts:      ${total_funding:+,.2f}  "
          f"({total_funding/gross_notional*100:+.2f}% of gross)")
    print(f"  Perp leg price P&L:    ${total_perp:+,.2f}  "
          f"({total_perp/gross_notional*100:+.2f}% of gross)")
    print(f"  Spot leg price P&L:    ${total_spot:+,.2f}  "
          f"({total_spot/gross_notional*100:+.2f}% of gross)")
    print(f"  Basis convergence:     ${total_perp + total_spot:+,.2f}  "
          f"(perp + spot, what hedge leaves behind)")
    print(f"  Execution costs:       ${-total_cost:,.2f}  "
          f"({-total_cost/gross_notional*100:.2f}% of gross)")
    print(f"  ───────────────────────────────")
    print(f"  Net total:             ${total_net:+,.2f}  "
          f"({total_net/gross_notional*100:+.2f}% of gross)")
    print()
    print(f"Aggregate metrics ({n_days} trading days)")
    print(f"  Annualized return:     {ann_ret*100:+.2f}%")
    print(f"  Annualized Sharpe:     {sharpe:+.3f}")
    print(f"  Max drawdown:          {mdd*100:+.2f}% of gross notional")
    print(f"  Worst 1-day:           {w1d*100:+.3f}% of gross notional")
    print(f"  Worst 5-day:           {w5d*100:+.3f}% of gross notional")
    print()
    print("Decision criteria (locked from prior exploration runs):")
    bar_sharpe = sharpe >= 1.0
    bar_dd = mdd <= 0.15
    bar_w1 = w1d >= -0.015
    bar_w5 = w5d >= -0.030
    check = lambda b: "PASS" if b else "FAIL"
    print(f"  Annualized Sharpe ≥ +1.00:    {sharpe:+.3f}  {check(bar_sharpe)}")
    print(f"  Max drawdown ≤ 15%:           {mdd*100:+.2f}%  {check(bar_dd)}")
    print(f"  Worst 1-day ≥ -1.5%:          {w1d*100:+.3f}%  {check(bar_w1)}")
    print(f"  Worst 5-day ≥ -3.0%:          {w5d*100:+.3f}%  {check(bar_w5)}")
    print()
    all_clear = bar_sharpe and bar_dd and bar_w1 and bar_w5
    if all_clear:
        print("All bars cleared. Hedged carry survives realistic costs at the")
        print("base configuration. Next steps would be: parameter robustness")
        print("(rebalance frequency, cost sensitivity), then if surviving,")
        print("a real selection memo + pre-registration.")
    else:
        print("Decision criteria not all met. The realistic hedged carry P&L")
        print("does NOT clear the same bar that the idealized funding-only")
        print("simulation cleared. This is the expected directional result —")
        print("idealized models overstate executable carry edge because they")
        print("zero out hedge friction. Specific failures above tell us where.")
    print()
    print("Comparison with idealized run (explore_continuous_carry_rules.py):")
    print(f"  Idealized Rule 1 Sharpe:    +12.633  (funding receipt only, no hedge)")
    print(f"  Realistic hedged Sharpe:    {sharpe:+8.3f}  (this script)")
    print(f"  Cost of realism:            {12.633 - sharpe:+.3f} Sharpe points")
    print()
    print("Caveats: 1d-close price granularity (intraday moves not modeled),")
    print("no margin/liquidation, no funding prediction error, conservative")
    print("cost model. Real live execution would face additional frictions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
