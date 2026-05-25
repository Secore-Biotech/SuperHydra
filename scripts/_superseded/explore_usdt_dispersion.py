"""USDT/USD dispersion characterization on Coinbase.

Bounded measurement. Four questions:
  1. How often does USDT deviate > 5, 10, 25, 50 bps from $1.00?
  2. How long do deviations persist (contiguous run lengths)?
  3. Are there identifiable clustering periods?
  4. What is the empirical distribution shape?

Pre-locked decision rule (LOCKED before data is loaded):
  Meaningful threshold = ±25 bps (above typical Coinbase USDT-USD spread).
  Looser thresholds (±5, ±10) reported descriptively but not used for verdict.

  Total ±25 bps events across the OOS window:
    < 50         → phenomenon too sparse to support follow-up
    50 - 200     → ambiguous; do not proceed to follow-up without re-scoping
    >= 200       → dispersion is meaningful; follow-up scoping justified

  Meta-rule from prior session: if the result is syntactically met but the
  threshold turns out to measure the wrong thing, the rule can be
  overridden in writing, not silently.

NOT a strategy. NOT a stress framework. Pure descriptive measurement.
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

from data.ingestion.vendors.coinbase.usdt_usd_fetcher import CoinbaseUsdtUsdFetcher


WINDOW_START = datetime(2023, 4, 15, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 4, 15, tzinfo=timezone.utc)

THRESHOLDS_BPS = [5.0, 10.0, 25.0, 50.0]
DECISION_THRESHOLD_BPS = 25.0
DECISION_LOW_COUNT = 50
DECISION_HIGH_COUNT = 200


@dataclass
class DispersionEvent:
    start: datetime
    end: datetime
    duration_hours: int
    peak_bps: float
    peak_at: datetime
    sign: int  # +1 if USDT > $1, -1 if < $1


def deviation_bps(price: Decimal) -> float:
    """Deviation from par in bps. Positive = above $1, negative = below."""
    return float((price - Decimal("1")) / Decimal("1") * Decimal("10000"))


def find_events(
    series: list[tuple[datetime, float]],
    threshold_bps: float,
) -> list[DispersionEvent]:
    """Find contiguous runs where |deviation| > threshold."""
    events = []
    run_start_idx = None
    for i, (_, b) in enumerate(series):
        is_event = abs(b) > threshold_bps
        if is_event and run_start_idx is None:
            run_start_idx = i
        elif not is_event and run_start_idx is not None:
            run = series[run_start_idx:i]
            events.append(_run_to_event(run))
            run_start_idx = None
    if run_start_idx is not None:
        run = series[run_start_idx:]
        events.append(_run_to_event(run))
    return events


def _run_to_event(run: list[tuple[datetime, float]]) -> DispersionEvent:
    peak_idx = max(range(len(run)), key=lambda i: abs(run[i][1]))
    peak_t, peak_b = run[peak_idx]
    return DispersionEvent(
        start=run[0][0],
        end=run[-1][0],
        duration_hours=len(run),
        peak_bps=abs(peak_b),
        peak_at=peak_t,
        sign=1 if peak_b > 0 else -1,
    )


def percentile(sorted_values: list[float], pct: float) -> float:
    """Simple percentile from a sorted list. 0 <= pct <= 100."""
    if not sorted_values:
        return 0.0
    if pct <= 0:
        return sorted_values[0]
    if pct >= 100:
        return sorted_values[-1]
    idx = (pct / 100) * (len(sorted_values) - 1)
    lo = int(idx)
    frac = idx - lo
    if lo + 1 >= len(sorted_values):
        return sorted_values[lo]
    return sorted_values[lo] * (1 - frac) + sorted_values[lo + 1] * frac


def main() -> int:
    print()
    print("=" * 96)
    print("USDT/USD dispersion measurement (Coinbase, 1h, 3-year OOS)")
    print("=" * 96)
    print(f"Window: {WINDOW_START.date()} → {WINDOW_END.date()}")
    print()
    print("Pre-locked decision rule on TOTAL ±25 bps event count:")
    print(f"  < {DECISION_LOW_COUNT}    → sparse, deprioritize")
    print(f"  {DECISION_LOW_COUNT}-{DECISION_HIGH_COUNT}   → ambiguous")
    print(f"  >= {DECISION_HIGH_COUNT}  → meaningful, follow-up justified")
    print()

    print("Loading data from cache...")
    fetcher = CoinbaseUsdtUsdFetcher(throttle_seconds=0.40)
    klines = fetcher.fetch_window(WINDOW_START, WINDOW_END)
    print(f"  {len(klines)} hourly klines loaded.")
    print()

    if not klines:
        print("ERROR: no data.")
        return 1

    # ── Build deviation series ──────────────────────────────────────────
    series: list[tuple[datetime, float]] = [
        (k.open_time, deviation_bps(k.close)) for k in klines
    ]
    deviations = [b for _, b in series]
    abs_deviations = [abs(b) for b in deviations]
    n_hours = len(series)

    # ── Q4: distribution shape ──────────────────────────────────────────
    print("Q4: Empirical distribution shape (deviation_bps from par)")
    sorted_dev = sorted(deviations)
    print(f"  count:        {n_hours}")
    print(f"  mean:         {statistics.fmean(deviations):+.3f} bps")
    print(f"  median:       {statistics.median(deviations):+.3f} bps")
    print(f"  stdev:        {statistics.stdev(deviations):.3f} bps")
    print(f"  min:          {min(deviations):+.3f} bps")
    print(f"  max:          {max(deviations):+.3f} bps")
    print()
    print("  Percentiles of abs(deviation):")
    sorted_abs = sorted(abs_deviations)
    for p in [50, 75, 90, 95, 99, 99.5, 99.9]:
        print(f"    p{p:<5}     {percentile(sorted_abs, p):>8.2f} bps")
    print()

    # ── Q1 + Q2: frequency and persistence at each threshold ────────────
    print("Q1 + Q2: Event frequency and persistence")
    print(f"  {'threshold':<12}  {'events':>8}  {'event-hrs':>10}  "
          f"{'time-frac':>10}  {'med-dur':>8}  {'max-dur':>8}")
    print("  " + "-" * 78)

    events_by_threshold: dict[float, list[DispersionEvent]] = {}
    for thr in THRESHOLDS_BPS:
        events = find_events(series, thr)
        events_by_threshold[thr] = events
        n_events = len(events)
        event_hours = sum(e.duration_hours for e in events)
        time_frac = event_hours / n_hours
        if events:
            durations = [e.duration_hours for e in events]
            med_dur = statistics.median(durations)
            max_dur = max(durations)
        else:
            med_dur = 0
            max_dur = 0
        print(f"  ±{thr:>4.0f} bps   "
              f"{n_events:>8}  "
              f"{event_hours:>10}  "
              f"{time_frac:>9.2%}   "
              f"{med_dur:>6.1f}h  "
              f"{max_dur:>6}h")
    print()

    # ── Q3: clustering — events per calendar month ──────────────────────
    print("Q3: Temporal clustering (events at ±25 bps per calendar month, top 10)")
    events_25 = events_by_threshold[25.0]
    month_counter: Counter[str] = Counter()
    for e in events_25:
        month_key = f"{e.start.year}-{e.start.month:02d}"
        month_counter[month_key] += 1

    if month_counter:
        # Print top 10 months by event count
        top_months = month_counter.most_common(10)
        print(f"  {'month':<10}  {'events':>7}")
        for month, count in top_months:
            print(f"  {month:<10}  {count:>7}")
        print()
        # Total months covered vs months with events
        all_months = set()
        for k in klines:
            all_months.add(f"{k.open_time.year}-{k.open_time.month:02d}")
        active_months = len(month_counter)
        total_months = len(all_months)
        print(f"  Months with at least one ±25 bps event: "
              f"{active_months}/{total_months} ({active_months/total_months:.0%})")
    else:
        print("  No ±25 bps events in window — no clustering analysis possible.")
    print()

    # ── Top 20 largest events at ±25 bps ────────────────────────────────
    print("Top 20 ±25 bps events by peak deviation:")
    if events_25:
        top = sorted(events_25, key=lambda e: e.peak_bps, reverse=True)[:20]
        print(f"  {'#':<3}  {'start':<25}  {'dur':>5}  {'peak':>10}  {'sign':>5}")
        for i, e in enumerate(top, 1):
            sign_str = "+" if e.sign > 0 else "-"
            print(f"  {i:<3}  {e.start!s:<25}  {e.duration_hours:>4}h  "
                  f"{e.peak_bps:>9.2f}b  {sign_str:>5}")
    else:
        print("  (none)")
    print()

    # ── Verdict ─────────────────────────────────────────────────────────
    print("=" * 96)
    n_25 = len(events_25)
    print(f"Pre-locked decision rule: TOTAL ±25 bps event count = {n_25}")
    if n_25 < DECISION_LOW_COUNT:
        verdict = "SPARSE"
        explanation = (f"Below {DECISION_LOW_COUNT} events at the meaningful threshold "
                       f"(±25 bps) over 3 years. USDT-USD dispersion does not "
                       f"appear to support follow-up scoping based on this data.")
    elif n_25 >= DECISION_HIGH_COUNT:
        verdict = "MEANINGFUL"
        explanation = (f"At least {DECISION_HIGH_COUNT} events at ±25 bps. "
                       f"The phenomenon is frequent enough to characterize further. "
                       f"This does NOT validate any strategy — it validates that "
                       f"the phenomenon is real enough to deserve next-session "
                       f"thought about what to ask of it.")
    else:
        verdict = "AMBIGUOUS"
        explanation = (f"Between {DECISION_LOW_COUNT}-{DECISION_HIGH_COUNT} events. "
                       f"Substrate is borderline. Do NOT escalate without explicit "
                       f"re-scoping. The right move is to step back and reconsider, "
                       f"not to chase the result with another script.")
    print(f"Verdict: {verdict}")
    print()
    import textwrap
    for line in textwrap.wrap(explanation, width=92):
        print(f"  {line}")
    print()
    print("=" * 96)
    print("Reminder: descriptive measurement only. No strategy claim.")
    print("If the verdict triggers questions about WHY (regulatory, liquidity,")
    print("issuer events), those questions are NEXT-SESSION scope.")
    print("=" * 96)
    return 0


if __name__ == "__main__":
    sys.exit(main())
