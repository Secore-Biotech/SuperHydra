"""Pre-fetch OKX BTC-USDT-SWAP 1h klines over the OOS window.

Populates: artifacts/cache/okx_klines_BTC-USDT-SWAP_1H/

Needed for scripts/probe_cross_venue_basis.py which measures whether
cross-venue (Binance vs OKX) basis is meaningfully wider than
same-venue basis (~±2 bps).

Pagination math:
  300 records per call × ~88 calls = 26,400 hours = 3 years
  At 0.3s throttle: ~26 seconds wall time

NOT a strategy. NOT committed. One-shot data prep.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data.ingestion.vendors.okx.okx_klines_fetcher import (
    OkxKlinesFetcher,
    _default_cache_dir_for,
)


def main() -> int:
    inst_id = "BTC-USDT-SWAP"
    interval = "1H"
    cache_dir = _default_cache_dir_for(inst_id, interval)

    print(f"Pre-fetching OKX 1h klines")
    print(f"  Instrument:   {inst_id}")
    print(f"  Interval:     {interval}")
    print(f"  Cache:        {cache_dir}")
    print()

    pre_zips = len(list(cache_dir.glob("*.json"))) if cache_dir.exists() else 0
    print(f"Cached pages before: {pre_zips}")
    print()

    fetcher = OkxKlinesFetcher(
        inst_id=inst_id,
        interval=interval,
        throttle_seconds=0.30,
    )

    # OOS window — same as Binance 1h prefetch
    start = datetime(2023, 4, 1, tzinfo=timezone.utc)
    end = datetime(2026, 5, 1, tzinfo=timezone.utc)
    print(f"Window: {start.date()} → {end.date()}")
    print()

    t0 = time.monotonic()
    klines = fetcher.fetch_window(start, end)
    elapsed = time.monotonic() - t0

    post_zips = len(list(cache_dir.glob("*.json")))
    print(f"Returned {len(klines)} klines in {elapsed:.1f}s")
    print(f"Cached pages after: {post_zips} (+{post_zips - pre_zips} new)")
    print()
    if klines:
        print(f"First: {klines[0].open_time}  close={klines[0].close}")
        print(f"Last:  {klines[-1].open_time}  close={klines[-1].close}")
    print()

    # Sanity checks
    issues = []
    expected_min = 22000  # 3 years × 8760 hours = 26,280; allow 15% missing
    expected_max = 27000  # but not absurdly more
    if not (expected_min <= len(klines) <= expected_max):
        issues.append(
            f"unexpected kline count: {len(klines)} "
            f"(expected {expected_min}-{expected_max})"
        )

    if klines:
        for k in (klines[0], klines[-1]):
            if not (15000 < float(k.close) < 150000):
                issues.append(
                    f"price out of expected BTC range: "
                    f"{k.open_time} close={k.close}"
                )

    if issues:
        print(f"WARNING ({len(issues)} issue{'s' if len(issues) != 1 else ''}):")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")
        return 1

    print("OKX cache ready for cross-venue basis probe.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
