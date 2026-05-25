"""Exploratory script: does stress-state conditioning change candidate #4 behavior?

Same logic as v1. Adds:
  - Pagination wrapper around FundingRateFetcher (Binance 1000-record limit)
  - Local JSON cache at artifacts/cache/btc_funding_explore.json so reruns
    are instant after first fetch

NOT a candidate. NOT pre-registered. NOT governance.

Usage:
    python scripts/explore_stress_state_on_candidate_4.py

Output:
    Printed table to stdout.

Dependencies:
    - tests/fixtures/sleeve_b/vol_scaled_momentum_weekly_pnl.jsonl
    - data/ingestion/vendors/binance/funding_fetcher.py (8e60933)
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

from data.ingestion.vendors.binance.funding_fetcher import FundingRateFetcher


# ─── Configuration ────────────────────────────────────────────────────────

WEEKLY_PNL_PATH = (
    REPO_ROOT / "tests" / "fixtures" / "sleeve_b" /
    "vol_scaled_momentum_weekly_pnl.jsonl"
)

CACHE_PATH = REPO_ROOT / "artifacts" / "cache" / "btc_funding_explore.json"

STRESS_ASSET = "BTCUSDT"
PERSISTENCE_WINDOW_DAYS = 7
THRESHOLDS = [Decimal("0.00005"), Decimal("0.00010"), Decimal("0.00020")]
# 0.005%, 0.010%, 0.020% per 8h period

WEEKS_PER_YEAR = 52


# ─── Load weekly P&L ──────────────────────────────────────────────────────

def load_weekly_pnl() -> list[dict]:
    rows = []
    with WEEKLY_PNL_PATH.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            row["week_start_dt"] = datetime.strptime(
                row["week_start"], "%Y-%m-%d"
            ).replace(tzinfo=timezone.utc)
            row["net_pnl_bps_decimal"] = Decimal(row["net_pnl_bps"])
            rows.append(row)
    rows.sort(key=lambda r: r["week_start_dt"])
    return rows


# ─── Paginated funding fetch with local cache ─────────────────────────────

def fetch_btc_funding_paginated(start: datetime, end: datetime) -> list[dict]:
    """Fetch all BTC funding records in [start, end), paginating around
    Binance's 1000-record-per-call limit. Returns sorted list of
    {time: datetime, rate: Decimal}.

    Pagination: each call returns up to 1000 records sorted ascending by
    funding_time. Next call's start = (last_record.funding_time + 1ms).
    Continue until either:
      - a call returns fewer than 1000 records (window exhausted), or
      - the next start would be >= end (window covered).
    """
    fetcher = FundingRateFetcher()
    all_records: list[dict] = []
    cursor = start
    batch_num = 0

    while cursor < end:
        batch_num += 1
        records = fetcher.fetch_window(STRESS_ASSET, cursor, end, limit=1000)
        if not records:
            break

        print(f"    batch {batch_num}: fetched {len(records)} records "
              f"from {records[0].funding_time.date()} to {records[-1].funding_time.date()}")

        for r in records:
            all_records.append({
                "time": r.funding_time,
                "rate": r.funding_rate,
            })

        # If we got fewer than the limit, we've exhausted the window
        if len(records) < 1000:
            break

        # Advance cursor to just after the last record we got
        cursor = records[-1].funding_time + timedelta(milliseconds=1)

    # De-dupe by funding_time (paranoid; pagination edge case)
    seen_times = set()
    deduped = []
    for rec in all_records:
        if rec["time"] in seen_times:
            continue
        seen_times.add(rec["time"])
        deduped.append(rec)

    deduped.sort(key=lambda r: r["time"])
    return deduped


def load_funding_with_cache(start: datetime, end: datetime) -> list[dict]:
    """Load funding records from local cache if present; otherwise fetch
    and cache. Cache is a flat JSON file."""
    if CACHE_PATH.exists():
        print(f"  Loading funding from cache: {CACHE_PATH}")
        with CACHE_PATH.open() as f:
            raw = json.load(f)
        records = [
            {
                "time": datetime.fromisoformat(r["time"]),
                "rate": Decimal(r["rate"]),
            }
            for r in raw
        ]
        print(f"  Loaded {len(records)} cached records")
        # Sanity check: cache must cover the requested window
        if records[0]["time"] > start or records[-1]["time"] < end - timedelta(days=8):
            print(f"  WARNING: cache range {records[0]['time'].date()} → "
                  f"{records[-1]['time'].date()} may not cover requested window "
                  f"{start.date()} → {end.date()}. Delete {CACHE_PATH} and rerun "
                  f"if you need a wider window.")
        return records

    print(f"  No cache found at {CACHE_PATH}. Fetching from Binance "
          f"(throttled — several minutes)...")
    records = fetch_btc_funding_paginated(start, end)

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_PATH.open("w") as f:
        json.dump(
            [{"time": r["time"].isoformat(), "rate": str(r["rate"])} for r in records],
            f,
            indent=2,
        )
    print(f"  Cached {len(records)} records to {CACHE_PATH}")
    return records


# ─── Stress flag computation ──────────────────────────────────────────────

def mean_abs_funding_over_window(
    funding: list[dict],
    window_end: datetime,
    window_days: int,
) -> Decimal | None:
    window_start = window_end - timedelta(days=window_days)
    rates_in_window = [
        r["rate"] for r in funding
        if window_start <= r["time"] < window_end
    ]
    if not rates_in_window:
        return None
    total = sum((abs(r) for r in rates_in_window), Decimal("0"))
    return total / Decimal(len(rates_in_window))


def compute_stress_flags(
    weekly_rows: list[dict],
    funding: list[dict],
    threshold: Decimal,
) -> tuple[list[bool], int]:
    """Returns (flags, weeks_with_no_funding_data)."""
    flags = []
    no_data_weeks = 0
    for row in weekly_rows:
        mean_abs = mean_abs_funding_over_window(
            funding, row["week_start_dt"], PERSISTENCE_WINDOW_DAYS,
        )
        if mean_abs is None:
            no_data_weeks += 1
            flags.append(False)
        else:
            flags.append(mean_abs > threshold)
    return flags, no_data_weeks


# ─── Filter + metrics ─────────────────────────────────────────────────────

def apply_filter(
    weekly_rows: list[dict],
    stress_flags: list[bool],
) -> list[Decimal]:
    out = []
    for row, is_stressed in zip(weekly_rows, stress_flags):
        if is_stressed:
            out.append(Decimal("0"))
        else:
            out.append(row["net_pnl_bps_decimal"])
    return out


def annualized_sharpe(weekly_pnl_bps: list[Decimal]) -> float:
    if len(weekly_pnl_bps) < 2:
        return float("nan")
    floats = [float(p) for p in weekly_pnl_bps]
    n = len(floats)
    mean = sum(floats) / n
    var = sum((x - mean) ** 2 for x in floats) / (n - 1)
    if var <= 0:
        return float("nan")
    std = math.sqrt(var)
    return (mean / std) * math.sqrt(WEEKS_PER_YEAR)


def max_drawdown_bps(weekly_pnl_bps: list[Decimal]) -> float:
    cum = Decimal("0")
    peak = Decimal("0")
    max_dd = Decimal("0")
    for pnl in weekly_pnl_bps:
        cum += pnl
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd
    return float(max_dd)


def total_return_bps(weekly_pnl_bps: list[Decimal]) -> float:
    return float(sum(weekly_pnl_bps, Decimal("0")))


# ─── Main ─────────────────────────────────────────────────────────────────

def main() -> int:
    print("Loading candidate #4 weekly P&L...")
    weekly_rows = load_weekly_pnl()
    print(f"  Loaded {len(weekly_rows)} weekly rows")
    print(f"  Range: {weekly_rows[0]['week_start']} → {weekly_rows[-1]['week_start']}")
    print()

    funding_start = weekly_rows[0]["week_start_dt"] - timedelta(days=14)
    funding_end = weekly_rows[-1]["week_start_dt"] + timedelta(days=7)
    print(f"Loading BTC funding from {funding_start.date()} to {funding_end.date()}...")
    funding = load_funding_with_cache(funding_start, funding_end)
    if funding:
        print(f"  Funding range: {funding[0]['time'].date()} → {funding[-1]['time'].date()}")
        # Quick coverage sanity check
        expected_records = (funding_end - funding_start).days * 3  # 3 per day at 8h
        print(f"  Records: {len(funding)} (expected ~{expected_records} at 8h cadence)")
    print()

    baseline_pnl = [row["net_pnl_bps_decimal"] for row in weekly_rows]
    baseline_sharpe = annualized_sharpe(baseline_pnl)
    baseline_dd = max_drawdown_bps(baseline_pnl)
    baseline_total = total_return_bps(baseline_pnl)

    print("=" * 80)
    print("Baseline (unfiltered candidate #4):")
    print(f"  Annualized Sharpe: {baseline_sharpe:+.3f}")
    print(f"  Max drawdown:      {baseline_dd:,.0f} bps")
    print(f"  Total P&L:         {baseline_total:+,.0f} bps")
    print(f"  Weeks:             {len(baseline_pnl)}")
    print("=" * 80)
    print()

    print("Filtered results (stress = mean |BTC funding| over trailing 7 days > threshold):")
    print()
    header = (
        f"{'threshold':>12}  {'weeks_on':>9}  {'pct_on':>7}  {'no_data':>8}  "
        f"{'sharpe':>8}  {'Δ_sharpe':>9}  {'max_dd':>10}  {'Δ_dd':>10}  {'total':>12}"
    )
    print(header)
    print("-" * len(header))

    for threshold in THRESHOLDS:
        stress_flags, no_data_weeks = compute_stress_flags(
            weekly_rows, funding, threshold,
        )
        filtered_pnl = apply_filter(weekly_rows, stress_flags)

        weeks_on = sum(1 for f in stress_flags if f)
        pct_on = 100.0 * weeks_on / len(stress_flags)
        f_sharpe = annualized_sharpe(filtered_pnl)
        f_dd = max_drawdown_bps(filtered_pnl)
        f_total = total_return_bps(filtered_pnl)

        delta_sharpe = f_sharpe - baseline_sharpe
        delta_dd = f_dd - baseline_dd

        print(
            f"{float(threshold) * 100:>10.4f}%  "
            f"{weeks_on:>9d}  {pct_on:>6.1f}%  {no_data_weeks:>8d}  "
            f"{f_sharpe:>+8.3f}  {delta_sharpe:>+9.3f}  "
            f"{f_dd:>10,.0f}  {delta_dd:>+10,.0f}  "
            f"{f_total:>+12,.0f}"
        )

    print()
    print("Columns:")
    print("  weeks_on   = number of weeks the filter zeroed candidate #4's P&L")
    print("  no_data    = weeks where funding window had no records (forced not-stressed)")
    print("  Δ_sharpe   = filtered_sharpe - baseline_sharpe (positive = good)")
    print("  Δ_dd       = filtered_dd - baseline_dd (negative = good)")
    print()
    print("Decision criterion (informal — exploration, not a gate):")
    print("  - Δ_sharpe ≥ +0.30 AND Δ_dd ≤ −300 bps → intuition warrants a real candidate")
    print("  - otherwise → stress-state conditioning on funding alone is not material")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
