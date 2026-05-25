"""Pre-fetch BTCUSDT spot 1d klines into local cache.

One-shot data-prep script. Run before the hedged-carry simulator session
so that simulator iterations don't pay HTTP latency each time.

Covers the OOS window with margin: 2023-04-01 → 2026-04-30.

NOT a test, NOT committed, NOT exploratory — just data prep.

Throttle: 0.5s between requests (per fetcher default).
Expected runtime: ~18s wall time on first run (35-37 archives), instant on rerun.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data.ingestion.vendors.binance.klines_archive_spot_fetcher import (
    BinanceKlinesArchiveSpotFetcher,
    _default_cache_dir_for,
)


def main() -> int:
    fetcher = BinanceKlinesArchiveSpotFetcher(interval="1d")
    cache_dir = _default_cache_dir_for("1d")
    print(f"Cache directory: {cache_dir}")
    print(f"Cache contents before fetch: {len(list(cache_dir.glob('*.zip')))} zips")
    print()

    start = datetime(2023, 4, 1, tzinfo=timezone.utc)
    end = datetime(2026, 5, 1, tzinfo=timezone.utc)  # exclusive
    print(f"Fetching BTCUSDT spot 1d: {start.date()} → {end.date()} (exclusive)")
    print("This populates the cache for the hedged-carry simulator.")
    print()

    t0 = time.monotonic()
    klines = fetcher.fetch_window("BTCUSDT", start, end)
    t_elapsed = time.monotonic() - t0
    print(f"Returned {len(klines)} klines in {t_elapsed:.1f}s")
    print()

    cached = sorted(cache_dir.glob("*.zip"))
    print(f"Cache contents after fetch: {len(cached)} zips")
    if cached:
        first_size = cached[0].stat().st_size / 1024
        last_size = cached[-1].stat().st_size / 1024
        print(f"  First: {cached[0].name}  ({first_size:.1f} KB)")
        print(f"  Last:  {cached[-1].name}  ({last_size:.1f} KB)")
    print()

    # Sanity checks
    issues = []
    expected_klines_min = 1050  # ~3 years * 365 ≈ 1095 days, allow some missing
    expected_klines_max = 1130
    if not (expected_klines_min <= len(klines) <= expected_klines_max):
        issues.append(
            f"unexpected count: {len(klines)} "
            f"(expected {expected_klines_min}-{expected_klines_max} for ~3 years daily)"
        )

    expected_zips_min = 35
    expected_zips_max = 38
    if not (expected_zips_min <= len(cached) <= expected_zips_max):
        issues.append(
            f"unexpected zip count: {len(cached)} "
            f"(expected ~{expected_zips_min}-{expected_zips_max} months)"
        )

    if klines:
        first_kline = klines[0]
        last_kline = klines[-1]
        print(f"First kline: {first_kline.open_time}  close={first_kline.close}")
        print(f"Last kline:  {last_kline.open_time}  close={last_kline.close}")

        # BTC range sanity: $15k–$110k covers the whole 2023-2026 range
        for k in (first_kline, last_kline):
            if not (15000 < float(k.close) < 110000):
                issues.append(
                    f"price out of expected BTC range $15k-$110k: "
                    f"{k.open_time} close={k.close}"
                )

    print()
    if issues:
        print(f"WARNING ({len(issues)} issue{'s' if len(issues) != 1 else ''}):")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")
        return 1
    print("Cache ready for hedged-carry simulator session.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
