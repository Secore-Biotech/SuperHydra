"""Cross-venue basis tail-event characterization.

The body of cross-venue basis distribution at 1h resolution is too efficient
to support continuous carry (stdev ~3 bps). But the tails extend to ±48 bps
and at least one event (2025-10-10 21:00) is a confirmed multi-hour
real-market stress dislocation.

This script measures the existence, frequency, and persistence of those
tail events. NOT strategy. NOT execution. NOT profitability. Just the
empirical shape of the phenomenon.

Five questions:
  1. How often does |basis| > {10, 15, 25, 50} bps?
  2. How long do those events persist (consecutive hours)?
  3. Are events clustered around high-volatility hours?
  4. What fraction of total time is in dislocation?
  5. What is the decay profile after peak?

Event definition (LOCKED):
  An "event" is a contiguous run of hours where |basis| > threshold.
  Crisp, parameter-free given a threshold. Two events separated by even
  one normal hour are counted as separate events.

Decision criterion (LOCKED, stated before running):
  These are descriptive measurements, not pass/fail tests. We do NOT
  pre-commit to "if X events of Y persistence then thesis is valid."
  The script outputs facts; the interpretation comes after.

NOT a strategy. NOT a candidate. NOT pre-registered. Pure measurement.
"""
from __future__ import annotations

import statistics
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
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
from data.ingestion.vendors.okx.okx_klines_fetcher import (
    OkxKlinesFetcher,
)


WINDOW_START = datetime(2023, 4, 15, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 4, 15, tzinfo=timezone.utc)

THRESHOLDS_BPS = [10.0, 15.0, 25.0, 50.0]


@dataclass
class TailEvent:
    """One contiguous run of hours where |basis| > threshold."""
    start: datetime
    end: datetime           # inclusive — last hour where the condition held
    duration_hours: int
    peak_bps: float         # max abs(basis) seen during this event
    peak_at: datetime
    sign: int               # +1 or -1, based on basis at peak


def load_all_series() -> tuple[
    dict[datetime, Decimal],  # binance perp
    dict[datetime, Decimal],  # binance spot
    dict[datetime, Decimal],  # okx perp
    dict[datetime, tuple[Decimal, Decimal]],  # binance perp (high, low) for vol
]:
    """Load all three close-price series plus Binance perp high/low for
    volatility co-occurrence."""
    bp_fetcher = BinanceKlinesArchiveFetcher(interval="1h")
    bs_fetcher = BinanceKlinesArchiveSpotFetcher(interval="1h")
    op_fetcher = OkxKlinesFetcher(inst_id="BTC-USDT-SWAP", interval="1H")

    bp_klines = bp_fetcher.fetch_window("BTCUSDT", WINDOW_START, WINDOW_END)
    bs_klines = bs_fetcher.fetch_window("BTCUSDT", WINDOW_START, WINDOW_END)
    op_klines = op_fetcher.fetch_window(WINDOW_START, WINDOW_END)

    bp = {k.open_time: k.close for k in bp_klines}
    bs = {k.open_time: k.close for k in bs_klines}
    op = {k.open_time: k.close for k in op_klines}
    bp_hl = {k.open_time: (k.high, k.low) for k in bp_klines}

    return bp, bs, op, bp_hl


def basis_bps(num: Decimal, denom: Decimal) -> float:
    return float((num - denom) / denom * Decimal("10000"))


def build_basis_series(
    series_a: dict[datetime, Decimal],
    series_b: dict[datetime, Decimal],
) -> list[tuple[datetime, float]]:
    """Return sorted [(timestamp, basis_bps), ...] for common timestamps."""
    common = sorted(set(series_a.keys()) & set(series_b.keys()))
    return [(t, basis_bps(series_a[t], series_b[t])) for t in common]


def find_events(
    basis_series: list[tuple[datetime, float]],
    threshold_bps: float,
) -> list[TailEvent]:
    """Find contiguous runs where |basis| > threshold."""
    events = []
    run_start_idx = None
    for i, (t, b) in enumerate(basis_series):
        is_event = abs(b) > threshold_bps
        if is_event and run_start_idx is None:
            run_start_idx = i
        elif not is_event and run_start_idx is not None:
            # Close out the run
            run = basis_series[run_start_idx:i]
            events.append(_run_to_event(run))
            run_start_idx = None
    # Close any trailing run
    if run_start_idx is not None:
        run = basis_series[run_start_idx:]
        events.append(_run_to_event(run))
    return events


def _run_to_event(run: list[tuple[datetime, float]]) -> TailEvent:
    peak_idx = max(range(len(run)), key=lambda i: abs(run[i][1]))
    peak_t, peak_b = run[peak_idx]
    return TailEvent(
        start=run[0][0],
        end=run[-1][0],
        duration_hours=len(run),
        peak_bps=abs(peak_b),
        peak_at=peak_t,
        sign=1 if peak_b > 0 else -1,
    )


def realized_vol_bps(high_low: dict[datetime, tuple[Decimal, Decimal]],
                     t: datetime) -> float | None:
    """Realized hourly bar range as bps of low."""
    hl = high_low.get(t)
    if hl is None:
        return None
    high, low = hl
    if low == 0:
        return None
    return float((high - low) / low * Decimal("10000"))


def report_pair(
    pair_name: str,
    a_label: str,
    b_label: str,
    basis_series: list[tuple[datetime, float]],
    bp_high_low: dict[datetime, tuple[Decimal, Decimal]],
) -> None:
    """Run all five questions on one basis series."""
    print("=" * 92)
    print(f"PAIR: {pair_name}    (basis = {a_label} - {b_label})")
    print("=" * 92)

    n_hours = len(basis_series)
    if n_hours == 0:
        print("Empty series, skipping.")
        return
    print(f"  Total hours observed:  {n_hours}")
    print(f"  Window:                {basis_series[0][0]} → {basis_series[-1][0]}")
    print()

    # --- Q1: frequency at each threshold ---
    print(f"Q1: Frequency of |basis| > threshold")
    print(f"{'threshold':<12}  {'events':>8}  {'event-hours':>12}  {'time-frac':>11}")
    print(f"{'-' * 12}  {'-' * 8}  {'-' * 12}  {'-' * 11}")
    events_by_threshold: dict[float, list[TailEvent]] = {}
    for thr in THRESHOLDS_BPS:
        events = find_events(basis_series, thr)
        events_by_threshold[thr] = events
        n_events = len(events)
        event_hours = sum(e.duration_hours for e in events)
        time_frac = event_hours / n_hours
        print(f"  ±{thr:>4.0f} bps   "
              f"{n_events:>8}  "
              f"{event_hours:>12}  "
              f"{time_frac:>10.2%}")
    print()

    # --- Q2: persistence histogram for ±15 bps events ---
    print(f"Q2: Persistence duration histogram (threshold = ±15 bps)")
    events_15 = events_by_threshold.get(15.0, [])
    if events_15:
        durations = [e.duration_hours for e in events_15]
        hist = Counter(durations)
        max_d = max(durations)
        print(f"  {'duration':<10}  {'count':>6}  {'cum-frac':>9}")
        cum = 0
        total = len(events_15)
        for d in sorted(hist.keys()):
            cum += hist[d]
            print(f"  {d:>4}h      {hist[d]:>6}  {cum/total:>9.1%}")
        print(f"  ---")
        print(f"  total events: {len(events_15)}")
        print(f"  median duration: {statistics.median(durations)} h")
        print(f"  mean duration:   {statistics.mean(durations):.1f} h")
        print(f"  max duration:    {max_d} h")
    else:
        print("  No ±15 bps events.")
    print()

    # --- Q3: co-occurrence with high BTC volatility ---
    # Define "high vol" hour as: realized 1h bar range > 100 bps
    # (i.e., >1% high-low intraday move)
    print(f"Q3: Co-occurrence with high BTC volatility (1h bar range > 100 bps)")
    high_vol_hours = set()
    for t, _ in basis_series:
        rv = realized_vol_bps(bp_high_low, t)
        if rv is not None and rv > 100.0:
            high_vol_hours.add(t)

    high_vol_count = len(high_vol_hours)
    if high_vol_count == 0:
        print("  No high-vol hours found, skipping.")
    else:
        print(f"  Total high-vol hours:  {high_vol_count} ({high_vol_count/n_hours:.2%} of all hours)")
        print(f"  {'threshold':<12}  {'event-hrs':>10}  {'overlap-w-highvol':>20}  {'lift':>8}")
        for thr in THRESHOLDS_BPS:
            events = events_by_threshold[thr]
            # Build set of all hours inside any event
            event_hours: set[datetime] = set()
            for e in events:
                # Iterate from start to end inclusive at 1h step
                t = e.start
                while t <= e.end:
                    event_hours.add(t)
                    t = t.replace(hour=(t.hour + 1) % 24) if t.hour < 23 else t  # cheap step
                    # Better: use timedelta
                # Fix: rebuild correctly
            # Redo correctly using timedelta
            from datetime import timedelta
            event_hours = set()
            for e in events:
                t = e.start
                while t <= e.end:
                    event_hours.add(t)
                    t = t + timedelta(hours=1)
            overlap = len(event_hours & high_vol_hours)
            event_hour_count = len(event_hours)
            if event_hour_count == 0:
                print(f"  ±{thr:>4.0f} bps   "
                      f"{event_hour_count:>10}  "
                      f"{'n/a':>20}  "
                      f"{'n/a':>8}")
                continue
            overlap_frac = overlap / event_hour_count
            # Lift: how many times more concentrated than baseline
            baseline = high_vol_count / n_hours
            lift = overlap_frac / baseline if baseline > 0 else float("inf")
            print(f"  ±{thr:>4.0f} bps   "
                  f"{event_hour_count:>10}  "
                  f"{overlap}/{event_hour_count} = {overlap_frac:>5.1%}  "
                  f"{lift:>6.1f}x")
    print()

    # --- Q4: time-fraction (already shown in Q1 but call out explicitly) ---
    print(f"Q4: Fraction of total time in dislocation")
    for thr in THRESHOLDS_BPS:
        events = events_by_threshold[thr]
        event_hours = sum(e.duration_hours for e in events)
        time_frac = event_hours / n_hours
        if time_frac > 0:
            avg_per_year = event_hours / (n_hours / (365 * 24)) if n_hours > 0 else 0
            print(f"  ±{thr:>4.0f} bps:  {time_frac:.3%}   "
                  f"(~{avg_per_year:.0f} hours/year on average)")
        else:
            print(f"  ±{thr:>4.0f} bps:  0.000%   (no events)")
    print()

    # --- Q5: decay profile after peak (for ±15 bps events) ---
    print(f"Q5: Decay profile — for events lasting ≥3h at ±15 bps:")
    events_15_long = [e for e in events_by_threshold[15.0] if e.duration_hours >= 3]
    if not events_15_long:
        print("  No ±15 bps events lasting ≥3 hours.")
    else:
        # For each long event, find the hour the peak was reached,
        # then look at the basis at peak_at, peak_at+1h, peak_at+2h, peak_at+3h
        from datetime import timedelta
        basis_dict = dict(basis_series)
        decay_offsets = [0, 1, 2, 3]
        decay_buckets: dict[int, list[float]] = {i: [] for i in decay_offsets}
        for e in events_15_long:
            for offset in decay_offsets:
                t = e.peak_at + timedelta(hours=offset)
                if t in basis_dict:
                    decay_buckets[offset].append(abs(basis_dict[t]))
        print(f"  Events: {len(events_15_long)}")
        print(f"  {'offset':<10}  {'mean |bps|':>10}  {'median':>10}  {'count':>6}")
        for offset in decay_offsets:
            vals = decay_buckets[offset]
            if vals:
                mean_v = statistics.mean(vals)
                median_v = statistics.median(vals)
                print(f"  peak+{offset}h    {mean_v:>10.2f}  {median_v:>10.2f}  {len(vals):>6}")
            else:
                print(f"  peak+{offset}h    {'n/a':>10}  {'n/a':>10}  {0:>6}")
    print()

    # --- Top 20 events by peak magnitude ---
    print(f"Top 20 events by peak |basis| (any threshold met):")
    # Use ±10 events as the universe; sort by peak
    events_10 = events_by_threshold[10.0]
    top = sorted(events_10, key=lambda e: e.peak_bps, reverse=True)[:20]
    print(f"  {'#':<3}  {'start':<25}  {'end':<25}  {'dur':>5}  {'peak':>10}  {'sign':>5}")
    for i, e in enumerate(top, 1):
        sign_str = "+" if e.sign > 0 else "-"
        print(f"  {i:<3}  {e.start!s:<25}  {e.end!s:<25}  {e.duration_hours:>4}h  "
              f"{e.peak_bps:>9.2f}b  {sign_str:>5}")
    print()


def main() -> int:
    print()
    print("=" * 92)
    print("Cross-venue basis tail-event characterization")
    print("=" * 92)
    print(f"Window: {WINDOW_START.date()} → {WINDOW_END.date()}")
    print()

    print("Loading data...")
    bp, bs, op, bp_hl = load_all_series()
    print(f"  Binance perp 1h:   {len(bp)} bars")
    print(f"  Binance spot 1h:   {len(bs)} bars")
    print(f"  OKX perp 1h:       {len(op)} bars")
    print()

    # Pair 1: Binance perp vs OKX perp
    series1 = build_basis_series(bp, op)
    report_pair(
        "Binance perp vs OKX perp",
        "binance_perp", "okx_perp",
        series1, bp_hl,
    )

    # Pair 2: Binance spot vs OKX perp
    series2 = build_basis_series(bs, op)
    report_pair(
        "Binance spot vs OKX perp",
        "binance_spot", "okx_perp",
        series2, bp_hl,
    )

    # Pair 3: Binance perp vs Binance spot (same-venue reference)
    series3 = build_basis_series(bp, bs)
    report_pair(
        "(reference) Binance perp vs Binance spot",
        "binance_perp", "binance_spot",
        series3, bp_hl,
    )

    print("=" * 92)
    print("Reminder: these are descriptive measurements only.")
    print("No strategy claim, no profitability estimate, no Sharpe.")
    print("Interpretation of whether tails are tradeable is a separate")
    print("question requiring fresh scoping.")
    print("=" * 92)
    return 0


if __name__ == "__main__":
    sys.exit(main())
