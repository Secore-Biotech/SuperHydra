"""Exploratory script: three-rule comparison of BTC funding carry exposure (v2).

CORRECTED FROM PRIOR RUN.

Prior version's bug: position flipped on every 8h funding sign change, charging
a full round-trip cost per flip. This tested "micro-rebalancing against noise,"
not "continuous carry." Sanity check showed gross funding capture of +$2,584
(+25.84% over 3 years) was destroyed by ~460 flip costs.

This version uses 21-event smoothing (≈7 days) for regime detection. Position
is held until the smoothed funding sign changes, not flipped per event.

Decision criteria UNCHANGED. Locked before this rerun and not tuned.

The three rules

  Rule 1 (persistent regime carry):
    direction = -sign(trailing_21_mean_funding)
    magnitude = 1.0 if direction != 0 else 0.0

  Rule 2 (persistence-scaled):
    direction = -sign(trailing_21_mean_funding)
    magnitude = fraction of trailing 21 events with same sign as the smoothed mean
    position = direction * magnitude

  Rule 3 (Rule 2 + vol suppression):
    Start from Rule 2's position.
    Compute trailing 21-event funding stdev.
    If stdev > 0.01% per 8h: suppress to 0.
    Otherwise: keep Rule 2's position.

Cost model

  Round-trip cost: 8 bps (Binance USDM taker 4 bps × 2 sides; spot leg assumed
  similarly costed under the perfect-hedge idealization). Charged proportional
  to position size change.

Decision criteria (locked, identical to prior run)

  Annualized Sharpe         ≥ +1.00
  Max drawdown              ≤ 15% of notional
  Worst single-day return   ≥ -1.5% of notional
  Worst 5-day return        ≥ -3.0% of notional

  Rule clears iff ALL FOUR bars cleared.

Caveats

  - Funding P&L only. Underlying perp price P&L not modeled (assumes perfect
    carry capture via spot hedge). This is an idealized capture model.
  - Single smoothing-window value (21 events). Robustness across windows is
    NOT tested in this run; if any rule clears, robustness is the next test.
  - Cherry-picking guard: thresholds and smoothing window LOCKED before run.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


CACHE_PATH = REPO_ROOT / "artifacts" / "cache" / "btc_funding_explore.json"

NOTIONAL = Decimal("10000")
ROUND_TRIP_COST_BPS = Decimal("8")

SMOOTHING_N = 21
RULE3_VOL_THRESHOLD = Decimal("0.0001")

DAYS_PER_YEAR = 365


def load_funding() -> list[dict]:
    if not CACHE_PATH.exists():
        print(f"ERROR: cache not found at {CACHE_PATH}")
        sys.exit(1)
    with CACHE_PATH.open() as f:
        raw = json.load(f)
    records = [
        {"time": datetime.fromisoformat(r["time"]), "rate": Decimal(r["rate"])}
        for r in raw
    ]
    records.sort(key=lambda r: r["time"])
    return records


def trailing_mean_rate(funding: list[dict], end_idx: int, n: int) -> Decimal:
    start = max(0, end_idx - n + 1)
    window = funding[start:end_idx + 1]
    rates = [r["rate"] for r in window]
    return sum(rates, Decimal("0")) / Decimal(len(rates))


def trailing_same_sign_fraction(
    funding: list[dict], end_idx: int, n: int, reference_sign: int,
) -> Decimal:
    if reference_sign == 0:
        return Decimal("0")
    start = max(0, end_idx - n + 1)
    window = funding[start:end_idx + 1]
    same = sum(
        1 for r in window
        if (r["rate"] > 0 and reference_sign > 0) or
           (r["rate"] < 0 and reference_sign < 0)
    )
    return Decimal(same) / Decimal(len(window))


def trailing_stdev_rate(funding: list[dict], end_idx: int, n: int) -> Decimal:
    start = max(0, end_idx - n + 1)
    window = funding[start:end_idx + 1]
    rates = [r["rate"] for r in window]
    if len(rates) < 2:
        return Decimal("0")
    mean = sum(rates, Decimal("0")) / Decimal(len(rates))
    var = sum((r - mean) ** 2 for r in rates) / Decimal(len(rates) - 1)
    return Decimal(str(math.sqrt(float(var))))


def rule1_persistent(funding: list[dict]) -> list[Decimal]:
    positions = []
    for i in range(len(funding)):
        smoothed = trailing_mean_rate(funding, i, SMOOTHING_N)
        if smoothed > 0:
            positions.append(Decimal("-1"))
        elif smoothed < 0:
            positions.append(Decimal("1"))
        else:
            positions.append(Decimal("0"))
    return positions


def rule2_persistence_scaled(funding: list[dict]) -> list[Decimal]:
    positions = []
    for i in range(len(funding)):
        smoothed = trailing_mean_rate(funding, i, SMOOTHING_N)
        if smoothed > 0:
            ref_sign = 1
            direction = Decimal("-1")
        elif smoothed < 0:
            ref_sign = -1
            direction = Decimal("1")
        else:
            positions.append(Decimal("0"))
            continue
        magnitude = trailing_same_sign_fraction(funding, i, SMOOTHING_N, ref_sign)
        positions.append(direction * magnitude)
    return positions


def rule3_vol_suppressed(funding: list[dict]) -> list[Decimal]:
    rule2_positions = rule2_persistence_scaled(funding)
    positions = []
    for i in range(len(funding)):
        stdev = trailing_stdev_rate(funding, i, SMOOTHING_N)
        if stdev > RULE3_VOL_THRESHOLD:
            positions.append(Decimal("0"))
        else:
            positions.append(rule2_positions[i])
    return positions


def simulate(
    funding: list[dict],
    target_positions: list[Decimal],
) -> tuple[list[Decimal], list[Decimal], int]:
    assert len(funding) == len(target_positions)
    gross_per_event = []
    cost_per_event = []
    held = Decimal("0")
    changes = 0

    for i, rec in enumerate(funding):
        target = target_positions[i]
        if target != held:
            change_size = abs(target - held)
            event_cost = (
                change_size * NOTIONAL * ROUND_TRIP_COST_BPS
                / Decimal("10000") / Decimal("2")
            )
            cost_per_event.append(event_cost)
            changes += 1
            held = target
        else:
            cost_per_event.append(Decimal("0"))

        gross = -held * rec["rate"] * NOTIONAL
        gross_per_event.append(gross)

    return gross_per_event, cost_per_event, changes


def aggregate_to_daily(
    funding: list[dict], per_event_pnl: list[Decimal],
) -> list[Decimal]:
    by_day: dict[datetime, Decimal] = {}
    for rec, pnl in zip(funding, per_event_pnl):
        day = rec["time"].replace(hour=0, minute=0, second=0, microsecond=0)
        by_day[day] = by_day.get(day, Decimal("0")) + pnl
    return [v for _, v in sorted(by_day.items())]


def annualized_sharpe(daily_pnl: list[Decimal]) -> float:
    if len(daily_pnl) < 2:
        return float("nan")
    fracs = [float(p) / float(NOTIONAL) for p in daily_pnl]
    n = len(fracs)
    mean = sum(fracs) / n
    var = sum((x - mean) ** 2 for x in fracs) / (n - 1)
    if var <= 0:
        return float("nan")
    std = math.sqrt(var)
    return (mean / std) * math.sqrt(DAYS_PER_YEAR)


def annualized_return(daily_pnl: list[Decimal]) -> float:
    total = float(sum(daily_pnl, Decimal("0"))) / float(NOTIONAL)
    n_days = len(daily_pnl)
    if n_days == 0:
        return float("nan")
    return total * DAYS_PER_YEAR / n_days


def max_drawdown(daily_pnl: list[Decimal]) -> float:
    cum = Decimal("0")
    peak = Decimal("0")
    max_dd = Decimal("0")
    for p in daily_pnl:
        cum += p
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd
    return float(max_dd) / float(NOTIONAL)


def worst_n_day(daily_pnl: list[Decimal], n: int) -> float:
    if len(daily_pnl) < n:
        return float("nan")
    running = sum(daily_pnl[:n], Decimal("0"))
    worst = running
    for i in range(n, len(daily_pnl)):
        running = running - daily_pnl[i - n] + daily_pnl[i]
        if running < worst:
            worst = running
    return float(worst) / float(NOTIONAL)


def exposure_time(positions: list[Decimal]) -> float:
    if not positions:
        return float("nan")
    nonzero = sum(1 for p in positions if p != 0)
    return nonzero / len(positions)


def main() -> int:
    print("Loading BTC funding from cache...")
    funding = load_funding()
    print(f"  {len(funding)} records  "
          f"{funding[0]['time'].date()} → {funding[-1]['time'].date()}")
    print()
    print("Configuration (LOCKED before run):")
    print(f"  Notional:                 ${NOTIONAL}")
    print(f"  Round-trip cost:          {ROUND_TRIP_COST_BPS} bps")
    print(f"  Smoothing window N:       {SMOOTHING_N} events (~7 days)")
    print(f"  Rule 3 vol threshold:     {RULE3_VOL_THRESHOLD * 100}% per 8h")
    print()
    print("Decision criteria (LOCKED):")
    print(f"  Annualized Sharpe         >= +1.00")
    print(f"  Max drawdown              <= 15% of notional")
    print(f"  Worst single-day return   >= -1.5% of notional")
    print(f"  Worst 5-day return        >= -3.0% of notional")
    print()
    print("=" * 110)

    rules = [
        ("Rule 1 (persistent regime)",  rule1_persistent),
        ("Rule 2 (persistence-scaled)", rule2_persistence_scaled),
        ("Rule 3 (Rule 2 + vol cap)",   rule3_vol_suppressed),
    ]

    results = []
    for name, rule_fn in rules:
        positions = rule_fn(funding)
        gross_pe, cost_pe, n_changes = simulate(funding, positions)
        daily_gross = aggregate_to_daily(funding, gross_pe)
        daily_cost = aggregate_to_daily(funding, cost_pe)
        daily_net = [g - c for g, c in zip(daily_gross, daily_cost)]

        gross_total = float(sum(daily_gross, Decimal("0"))) / float(NOTIONAL)
        cost_total = float(sum(daily_cost, Decimal("0"))) / float(NOTIONAL)
        net_total = float(sum(daily_net, Decimal("0"))) / float(NOTIONAL)

        ann_ret = annualized_return(daily_net)
        ann_sharpe = annualized_sharpe(daily_net)
        mdd = max_drawdown(daily_net)
        worst_1d = worst_n_day(daily_net, 1)
        worst_5d = worst_n_day(daily_net, 5)
        exp_t = exposure_time(positions)

        bar_sharpe = ann_sharpe >= 1.0
        bar_dd = mdd <= 0.15
        bar_w1 = worst_1d >= -0.015
        bar_w5 = worst_5d >= -0.030
        clears = bar_sharpe and bar_dd and bar_w1 and bar_w5

        results.append({
            "name": name, "gross_total": gross_total, "cost_total": cost_total,
            "net_total": net_total, "ann_ret": ann_ret, "sharpe": ann_sharpe,
            "mdd": mdd, "w1d": worst_1d, "w5d": worst_5d, "exp_t": exp_t,
            "changes": n_changes,
            "bar_sharpe": bar_sharpe, "bar_dd": bar_dd,
            "bar_w1": bar_w1, "bar_w5": bar_w5, "clears": clears,
        })

    print()
    print(f"{'Rule':<30}  {'Gross%':>8}  {'Cost%':>7}  {'Net%':>8}  "
          f"{'AnnRet%':>8}  {'Sharpe':>8}  {'MaxDD%':>8}  "
          f"{'W1d%':>8}  {'W5d%':>8}  {'Exp%':>6}  {'Chg':>5}")
    print("-" * 110)
    for r in results:
        print(
            f"{r['name']:<30}  {r['gross_total']*100:>+7.2f}%  "
            f"{r['cost_total']*100:>+6.2f}%  {r['net_total']*100:>+7.2f}%  "
            f"{r['ann_ret']*100:>+7.2f}%  {r['sharpe']:>+8.3f}  "
            f"{r['mdd']*100:>+7.2f}%  {r['w1d']*100:>+7.2f}%  "
            f"{r['w5d']*100:>+7.2f}%  {r['exp_t']*100:>+5.1f}%  "
            f"{r['changes']:>5d}"
        )

    print()
    print("Per-bar verdict:")
    print(f"{'Rule':<30}  {'Sharpe>=1':>10}  {'DD<=15%':>9}  "
          f"{'1d>=-1.5%':>10}  {'5d>=-3.0%':>10}  {'CLEARS':>8}")
    print("-" * 92)
    for r in results:
        check = lambda b: "PASS" if b else "FAIL"
        verdict = "YES" if r["clears"] else "no"
        print(
            f"{r['name']:<30}  {check(r['bar_sharpe']):>10}  "
            f"{check(r['bar_dd']):>9}  {check(r['bar_w1']):>10}  "
            f"{check(r['bar_w5']):>10}  {verdict:>8}"
        )

    print()
    print("Notes on this run:")
    print(f"  - Regime-detected via {SMOOTHING_N}-event smoothing (corrected from per-event)")
    print(f"  - Cost reduced from 12 -> 8 bps (BTC perp realistic floor)")
    print(f"  - Gross/cost/net reported side-by-side")
    print(f"  - Funding P&L only - perp price P&L not modeled")
    print(f"  - Single-window robustness only")
    print(f"  - Decision criteria and smoothing window LOCKED before run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
