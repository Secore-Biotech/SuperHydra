"""Cross-venue basis probe.

Measures Binance vs OKX basis at 1h cadence over the OOS window.

Three time series:
  - Binance BTCUSDT perp 1h   (USDT-margined)
  - Binance BTCUSDT spot 1h
  - OKX BTC-USDT-SWAP 1h     (USDT-margined perp)

Two pair comparisons:
  - Binance perp vs OKX perp  (cleanest test — both USDT perps)
  - Binance spot vs OKX perp  (the typical hedged-carry shape)

Output: distribution stats (mean / median / stdev / min / max / abs-mean)
plus top 10 widest events with timestamps.

Decision criterion (LOCKED, stated before running):
  - stdev > 10 bps OR abs-mean > 5 bps    → cross-venue basis IS materially wider
                                            than same-venue (~±2 bps); justifies simulator work
  - stdev < 5 bps AND abs-mean < 3 bps    → cross-venue basis on USDT-quoted majors
                                            is also tight; thesis weakens
  - in between                            → ambiguous, needs more thought

NOT a strategy. NOT pre-registered. NOT a candidate. Pure measurement.
"""
from __future__ import annotations

import statistics
import sys
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


def load_binance_perp_1h() -> dict[datetime, Decimal]:
    fetcher = BinanceKlinesArchiveFetcher(interval="1h")
    klines = fetcher.fetch_window("BTCUSDT", WINDOW_START, WINDOW_END)
    return {k.open_time: k.close for k in klines}


def load_binance_spot_1h() -> dict[datetime, Decimal]:
    fetcher = BinanceKlinesArchiveSpotFetcher(interval="1h")
    klines = fetcher.fetch_window("BTCUSDT", WINDOW_START, WINDOW_END)
    return {k.open_time: k.close for k in klines}


def load_okx_perp_1h() -> dict[datetime, Decimal]:
    fetcher = OkxKlinesFetcher(inst_id="BTC-USDT-SWAP", interval="1H")
    klines = fetcher.fetch_window(WINDOW_START, WINDOW_END)
    return {k.open_time: k.close for k in klines}


def compute_basis_bps(numerator_price: Decimal, denominator_price: Decimal) -> float:
    """Basis in bps: (num - denom) / denom * 10000. Sign convention:
    positive means numerator price is higher than denominator."""
    return float((numerator_price - denominator_price) / denominator_price * Decimal("10000"))


def report_pair(
    name: str,
    series_a: dict[datetime, Decimal],
    series_b: dict[datetime, Decimal],
    a_label: str,
    b_label: str,
) -> dict:
    """Compute basis stats between two aligned price series.

    Returns dict with stats, prints a formatted report.
    """
    print("=" * 92)
    print(f"PAIR: {name}")
    print(f"  Numerator:    {a_label}")
    print(f"  Denominator:  {b_label}")
    print(f"  Basis_bps = ({a_label} - {b_label}) / {b_label} * 10000")
    print("=" * 92)

    # Find overlap
    common_times = set(series_a.keys()) & set(series_b.keys())
    common_sorted = sorted(common_times)
    if not common_sorted:
        print("NO OVERLAP between the two series. Skipping.")
        return {}

    print(f"  Hourly observations:    {len(common_sorted)}")
    print(f"  Window covered:         {common_sorted[0]} → {common_sorted[-1]}")
    print()

    basis_bps_series: list[tuple[datetime, float]] = []
    for t in common_sorted:
        b = compute_basis_bps(series_a[t], series_b[t])
        basis_bps_series.append((t, b))

    bps_values = [b for _, b in basis_bps_series]
    abs_bps = [abs(b) for b in bps_values]

    stats = {
        "count": len(bps_values),
        "mean": statistics.mean(bps_values),
        "median": statistics.median(bps_values),
        "stdev": statistics.stdev(bps_values) if len(bps_values) > 1 else 0.0,
        "min": min(bps_values),
        "max": max(bps_values),
        "abs_mean": statistics.mean(abs_bps),
        "abs_median": statistics.median(abs_bps),
    }

    print(f"Distribution (basis_bps):")
    print(f"  mean:        {stats['mean']:+.3f} bps")
    print(f"  median:      {stats['median']:+.3f} bps")
    print(f"  stdev:       {stats['stdev']:.3f} bps")
    print(f"  min:         {stats['min']:+.3f} bps")
    print(f"  max:         {stats['max']:+.3f} bps")
    print(f"  abs-mean:    {stats['abs_mean']:.3f} bps   (size of typical divergence)")
    print(f"  abs-median:  {stats['abs_median']:.3f} bps")
    print()

    # Top 10 widest
    by_abs_desc = sorted(basis_bps_series, key=lambda x: abs(x[1]), reverse=True)
    print(f"Top 10 widest basis events (signed):")
    for t, b in by_abs_desc[:10]:
        direction = f"{a_label} > {b_label}" if b > 0 else f"{a_label} < {b_label}"
        print(f"  {t}   basis={b:+8.3f} bps   ({direction})")
    print()

    # Decision criterion check (use stdev + abs_mean)
    DECISION_WIDE_STDEV = 10.0
    DECISION_WIDE_ABS_MEAN = 5.0
    DECISION_TIGHT_STDEV = 5.0
    DECISION_TIGHT_ABS_MEAN = 3.0

    is_wide = stats["stdev"] > DECISION_WIDE_STDEV or stats["abs_mean"] > DECISION_WIDE_ABS_MEAN
    is_tight = stats["stdev"] < DECISION_TIGHT_STDEV and stats["abs_mean"] < DECISION_TIGHT_ABS_MEAN

    if is_wide:
        verdict = "WIDE — cross-venue basis is materially larger than same-venue (~±2 bps)"
    elif is_tight:
        verdict = "TIGHT — cross-venue basis is also small; thesis weakens"
    else:
        verdict = "AMBIGUOUS — between the wide and tight thresholds"

    print(f"Verdict for this pair: {verdict}")
    print()
    return stats


def main() -> int:
    print()
    print("=" * 92)
    print("Cross-venue basis probe")
    print("=" * 92)
    print(f"Window:  {WINDOW_START.date()} → {WINDOW_END.date()}")
    print()
    print("Decision criterion (locked before running):")
    print("  stdev > 10 bps OR abs-mean > 5 bps  → WIDE (cross-venue is meaningful)")
    print("  stdev < 5 bps AND abs-mean < 3 bps  → TIGHT (cross-venue thesis weakens)")
    print("  else                                → AMBIGUOUS")
    print()

    print("Loading data...")
    binance_perp = load_binance_perp_1h()
    print(f"  Binance perp 1h:   {len(binance_perp)} bars")
    binance_spot = load_binance_spot_1h()
    print(f"  Binance spot 1h:   {len(binance_spot)} bars")
    okx_perp = load_okx_perp_1h()
    print(f"  OKX perp 1h:       {len(okx_perp)} bars")
    print()

    if not (binance_perp and binance_spot and okx_perp):
        print("ERROR: at least one data source is empty.")
        return 1

    # Pair 1: Binance perp vs OKX perp (cleanest cross-venue test)
    pair1 = report_pair(
        name="Binance perp vs OKX perp",
        series_a=binance_perp,
        series_b=okx_perp,
        a_label="binance_perp",
        b_label="okx_perp",
    )

    # Pair 2: Binance spot vs OKX perp (typical hedged-carry shape, cross-venue)
    pair2 = report_pair(
        name="Binance spot vs OKX perp",
        series_a=binance_spot,
        series_b=okx_perp,
        a_label="binance_spot",
        b_label="okx_perp",
    )

    # Pair 3 (bonus check): Binance perp vs Binance spot — same-venue reference
    # so we can directly compare cross-venue magnitudes against same-venue
    pair3 = report_pair(
        name="(reference) Binance perp vs Binance spot",
        series_a=binance_perp,
        series_b=binance_spot,
        a_label="binance_perp",
        b_label="binance_spot",
    )

    print("=" * 92)
    print("Summary")
    print("=" * 92)
    print(f"{'Pair':<40}  {'stdev':>10}  {'abs-mean':>10}  {'abs-median':>10}")
    print("-" * 92)
    for label, s in [
        ("Binance perp vs OKX perp",  pair1),
        ("Binance spot vs OKX perp",  pair2),
        ("(ref) Binance perp vs spot", pair3),
    ]:
        if s:
            print(f"{label:<40}  {s['stdev']:>9.2f}b  {s['abs_mean']:>9.2f}b  {s['abs_median']:>9.2f}b")
    print()
    print("Note: 'b' = bps.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
