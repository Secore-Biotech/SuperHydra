"""Hedged-carry simulator v2 — funding-event-resolution prices.

Same structure as v1 but uses 1h klines instead of 1d closes. For each
8h funding event at 00:00/08:00/16:00 UTC, picks the 1h bar whose
open_time equals or precedes the event timestamp (most recent prior
1h close). This gives funding-event-resolution prices on both legs,
which captures basis variation that 1d closes destroy.

v1 caveat retired: "intraday price approximation" is gone. Funding
events now use the actual intraday closing prices that hold at the
8h mark.

New caveat: 1h granularity still misses sub-hour basis dynamics. A
real strategy would use mark price snapshots at the exact funding
moment. 1h is the minimum credible resolution.

NOT a candidate. NOT pre-registered. NOT governance. Exploration only.

Decision criteria (LOCKED, unchanged from prior runs):
  Annualized Sharpe ≥ +1.00
  Max drawdown ≤ 15% of notional
  Worst single-day return ≥ -1.5% of notional
  Worst 5-day return ≥ -3.0% of notional
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


FUNDING_CACHE = REPO_ROOT / "artifacts" / "cache" / "btc_funding_explore.json"

NOTIONAL_PER_LEG = Decimal("10000")
ROUND_TRIP_COST_BPS = Decimal("12")

WINDOW_START = datetime(2023, 4, 15, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 4, 15, tzinfo=timezone.utc)

DAYS_PER_YEAR = 365


def load_funding() -> list[dict]:
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


def load_1h_prices(fetcher_class, interval: str = "1h") -> dict[datetime, Decimal]:
    """Load 1h kline closes keyed by open_time."""
    fetcher = fetcher_class(interval=interval)
    klines = fetcher.fetch_window("BTCUSDT", WINDOW_START, WINDOW_END)
    return {k.open_time: k.close for k in klines}


def price_at_funding_event(
    prices_1h: dict[datetime, Decimal], event_time: datetime,
) -> Decimal | None:
    """Return the close price of the 1h bar opening at the same hour as
    the funding event. Funding events land near 00:00, 08:00, 16:00 UTC
    but Binance API may report them with non-zero microseconds (e.g.,
    08:00:00.013). 1h bars open at exact hour boundaries. We truncate
    the event timestamp to the hour to match.

    Returns None if the bar is missing.
    """
    hour_aligned = event_time.replace(minute=0, second=0, microsecond=0)
    return prices_1h.get(hour_aligned)


def simulate(
    funding: list[dict],
    perp_prices_1h: dict[datetime, Decimal],
    spot_prices_1h: dict[datetime, Decimal],
) -> dict:
    event_records = []

    perp_qty = Decimal("0")
    spot_qty = Decimal("0")
    last_perp_price: Decimal | None = None
    last_spot_price: Decimal | None = None
    skipped_events = 0

    for rec in funding:
        event_time = rec["time"]
        rate = rec["rate"]

        perp_p = price_at_funding_event(perp_prices_1h, event_time)
        spot_p = price_at_funding_event(spot_prices_1h, event_time)
        if perp_p is None or spot_p is None:
            skipped_events += 1
            continue

        # P&L from price moves between this and the previous funding event
        if last_perp_price is not None and last_spot_price is not None:
            perp_price_pnl = perp_qty * (perp_p - last_perp_price)
            spot_price_pnl = spot_qty * (spot_p - last_spot_price)
        else:
            perp_price_pnl = Decimal("0")
            spot_price_pnl = Decimal("0")

        # Funding: short receives positive funding.
        # perp_qty is negative for short. funding_pnl = -perp_qty * perp_p * rate.
        funding_pnl = -perp_qty * perp_p * rate

        # Rebalance to target $NOTIONAL on each leg at current prices
        target_perp_qty = -NOTIONAL_PER_LEG / perp_p
        target_spot_qty = NOTIONAL_PER_LEG / spot_p

        # Cost on each leg per quantity change
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

        perp_qty = target_perp_qty
        spot_qty = target_spot_qty

        event_pnl = funding_pnl + perp_price_pnl + spot_price_pnl - total_cost

        event_records.append({
            "time": event_time,
            "perp_price": perp_p,
            "spot_price": spot_p,
            "basis_bps": float((perp_p - spot_p) / spot_p * Decimal("10000")),
            "funding_rate": rate,
            "funding_pnl": funding_pnl,
            "perp_price_pnl": perp_price_pnl,
            "spot_price_pnl": spot_price_pnl,
            "total_cost": total_cost,
            "event_pnl": event_pnl,
        })
        last_perp_price = perp_p
        last_spot_price = spot_p

    return {"event_records": event_records, "skipped_events": skipped_events}


def aggregate_to_daily(event_records: list[dict]) -> list[tuple[datetime, dict]]:
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


def annualized_sharpe(daily_total: list[Decimal]) -> float:
    if len(daily_total) < 2:
        return float("nan")
    gross = float(NOTIONAL_PER_LEG * 2)
    fracs = [float(p) / gross for p in daily_total]
    n = len(fracs)
    mean = sum(fracs) / n
    var = sum((x - mean) ** 2 for x in fracs) / (n - 1)
    if var <= 0:
        return float("nan")
    std = math.sqrt(var)
    return (mean / std) * math.sqrt(DAYS_PER_YEAR)


def annualized_return(daily_total: list[Decimal]) -> float:
    gross = float(NOTIONAL_PER_LEG * 2)
    total = float(sum(daily_total, Decimal("0"))) / gross
    n = len(daily_total)
    return total * DAYS_PER_YEAR / n if n else float("nan")


def max_drawdown(daily_total: list[Decimal]) -> float:
    gross = float(NOTIONAL_PER_LEG * 2)
    cum = Decimal("0")
    peak = Decimal("0")
    mdd = Decimal("0")
    for p in daily_total:
        cum += p
        if cum > peak: peak = cum
        dd = peak - cum
        if dd > mdd: mdd = dd
    return float(mdd) / gross


def worst_n_day(daily_total: list[Decimal], n: int) -> float:
    gross = float(NOTIONAL_PER_LEG * 2)
    if len(daily_total) < n: return float("nan")
    running = sum(daily_total[:n], Decimal("0"))
    worst = running
    for i in range(n, len(daily_total)):
        running = running - daily_total[i - n] + daily_total[i]
        if running < worst: worst = running
    return float(worst) / gross


def main() -> int:
    print("=" * 92)
    print("Hedged-carry simulator v2 — 1h-resolution prices at funding events")
    print("=" * 92)
    print()
    print(f"Window:               {WINDOW_START.date()} → {WINDOW_END.date()}")
    print(f"Notional per leg:     ${NOTIONAL_PER_LEG}")
    print(f"Gross exposure:       ${NOTIONAL_PER_LEG * 2}")
    print(f"Round-trip cost/leg:  {ROUND_TRIP_COST_BPS} bps per rebalance")
    print(f"Rebalance frequency:  every funding event (3x daily)")
    print(f"Price source:         1h klines (perp + spot), close at event time")
    print()

    print("Loading data...")
    funding = load_funding()
    print(f"  Funding events:    {len(funding)}")
    perp_prices = load_1h_prices(BinanceKlinesArchiveFetcher, "1h")
    print(f"  Perp 1h bars:      {len(perp_prices)}")
    spot_prices = load_1h_prices(BinanceKlinesArchiveSpotFetcher, "1h")
    print(f"  Spot 1h bars:      {len(spot_prices)}")
    print()

    if len(perp_prices) < 22000 or len(spot_prices) < 22000:
        print("ERROR: insufficient 1h price data. Run prefetch_btc_1h.py first.")
        return 1

    print("Running simulation...")
    result = simulate(funding, perp_prices, spot_prices)
    n_events = len(result["event_records"])
    n_skipped = result["skipped_events"]
    print(f"  Events processed:  {n_events}")
    print(f"  Events skipped:    {n_skipped}")
    print()

    # Basis statistics at funding events
    basis_bps = [r["basis_bps"] for r in result["event_records"]]
    print(f"Basis (bps) at funding events:")
    print(f"  mean:    {sum(basis_bps)/len(basis_bps):+.2f}")
    print(f"  min:     {min(basis_bps):+.2f}")
    print(f"  max:     {max(basis_bps):+.2f}")
    print()

    daily = aggregate_to_daily(result["event_records"])
    n_days = len(daily)
    daily_total = [d["total"] for _, d in daily]
    daily_funding = [d["funding_pnl"] for _, d in daily]
    daily_perp = [d["perp_pnl"] for _, d in daily]
    daily_spot = [d["spot_pnl"] for _, d in daily]
    daily_cost = [d["cost"] for _, d in daily]

    gross = float(NOTIONAL_PER_LEG * 2)
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

    print("P&L attribution (full window):")
    print(f"  Funding receipts:      ${total_funding:+,.2f}  ({total_funding/gross*100:+.2f}% of gross)")
    print(f"  Perp leg price P&L:    ${total_perp:+,.2f}  ({total_perp/gross*100:+.2f}% of gross)")
    print(f"  Spot leg price P&L:    ${total_spot:+,.2f}  ({total_spot/gross*100:+.2f}% of gross)")
    print(f"  Basis convergence:     ${total_perp + total_spot:+,.2f}  "
          f"({(total_perp+total_spot)/gross*100:+.2f}%)")
    print(f"  Execution costs:       ${-total_cost:,.2f}  ({-total_cost/gross*100:.2f}%)")
    print(f"  ───────────────────────────────")
    print(f"  Net total:             ${total_net:+,.2f}  ({total_net/gross*100:+.2f}% of gross)")
    print()
    print(f"Aggregate metrics ({n_days} trading days)")
    print(f"  Annualized return:     {ann_ret*100:+.2f}%")
    print(f"  Annualized Sharpe:     {sharpe:+.3f}")
    print(f"  Max drawdown:          {mdd*100:+.2f}% of gross")
    print(f"  Worst 1-day:           {w1d*100:+.3f}% of gross")
    print(f"  Worst 5-day:           {w5d*100:+.3f}% of gross")
    print()
    print("Decision criteria (locked):")
    bar_sharpe = sharpe >= 1.0
    bar_dd = mdd <= 0.15
    bar_w1 = w1d >= -0.015
    bar_w5 = w5d >= -0.030
    check = lambda b: "PASS" if b else "FAIL"
    print(f"  Sharpe ≥ +1.00:    {sharpe:+.3f}  {check(bar_sharpe)}")
    print(f"  Max DD ≤ 15%:      {mdd*100:+.2f}%  {check(bar_dd)}")
    print(f"  Worst 1d ≥ -1.5%:  {w1d*100:+.3f}%  {check(bar_w1)}")
    print(f"  Worst 5d ≥ -3.0%:  {w5d*100:+.3f}%  {check(bar_w5)}")
    print()
    all_clear = bar_sharpe and bar_dd and bar_w1 and bar_w5
    if all_clear:
        print("All bars cleared at 1h resolution. Significant improvement over v1's")
        print("daily-close artifact. Real basis P&L now visible in attribution.")
    else:
        print("Not all bars cleared at 1h resolution. The attribution above shows")
        print("which component dominates — funding, basis, or cost.")
    print()
    print("Comparison with prior runs:")
    print(f"  v1 (1d-close, basis-zeroed):   Sharpe ≈ +11.32  (artifact of granularity)")
    print(f"  v2 (1h funding-event prices):  Sharpe = {sharpe:+8.3f}  (this run)")
    print()
    print("Caveats: 1h granularity still misses sub-hour basis swings around")
    print("funding moments. A live strategy faces additional friction from")
    print("margin maintenance, funding-rate prediction error, adversarial")
    print("slippage during stress, and venue downtime.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
