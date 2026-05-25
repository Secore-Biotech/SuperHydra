"""Pre-fetch Coinbase USDT-USD 1h candles over the OOS window.

Populates: artifacts/cache/coinbase_klines_USDT-USD_1h/

Needed for scripts/explore_usdt_dispersion.py.

Pagination math:
  300 records per call × ~88 calls = 26,400 hours = 3 years
  At 0.4s throttle: ~35-40 seconds wall time

NOT a strategy. One-shot data prep.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data.ingestion.vendors.coinbase.usdt_usd_fetcher import (
    CoinbaseUsdtUsdFetcher,
    _default_cache_dir_for,
)


def main() -> int:
    product_id = "USDT-USD"
    interval = "1h"
    cache_dir = _default_cache_dir_for(product_id, interval)

    print(f"Pre-fetching Coinbase {product_id} {interval} candles")
    print(f"  Cache: {cache_dir}")
    print()

    pre_pages = len(list(cache_dir.glob("*.json"))) if cache_dir.exists() else 0
    print(f"Cached pages before: {pre_pages}")
    print()

    fetcher = CoinbaseUsdtUsdFetcher(
        product_id=product_id,
        throttle_seconds=0.40,
    )

    # OOS window
    start = datetime(2023, 4, 1, tzinfo=timezone.utc)
    end = datetime(2026, 5, 1, tzinfo=timezone.utc)
    print(f"Window: {start.date()} → {end.date()}")
    print()

    t0 = time.monotonic()
    klines = fetcher.fetch_window(start, end)
    elapsed = time.monotonic() - t0

    post_pages = len(list(cache_dir.glob("*.json")))
    print(f"Returned {len(klines)} klines in {elapsed:.1f}s")
    print(f"Cached pages after: {post_pages} (+{post_pages - pre_pages} new)")
    print()
    if klines:
        print(f"First: {klines[0].open_time}  close={klines[0].close}  vol={klines[0].volume}")
        print(f"Last:  {klines[-1].open_time}  close={klines[-1].close}  vol={klines[-1].volume}")
    print()

    # Sanity checks
    issues = []
    expected_min = 22000  # allow ~15% gaps
    expected_max = 27500
    if not (expected_min <= len(klines) <= expected_max):
        issues.append(
            f"unexpected kline count: {len(klines)} "
            f"(expected {expected_min}-{expected_max})"
        )

    if klines:
        for k in (klines[0], klines[-1]):
            if not (0.90 < float(k.close) < 1.10):
                issues.append(
                    f"price out of expected USDT range: "
                    f"{k.open_time} close={k.close}"
                )
        # Volume sanity: most hours should have nonzero volume on a liquid market
        zero_vol_count = sum(1 for k in klines if float(k.volume) == 0)
        if zero_vol_count > len(klines) * 0.05:  # more than 5% zero-volume
            issues.append(
                f"high zero-volume rate: {zero_vol_count}/{len(klines)} "
                f"({100*zero_vol_count/len(klines):.1f}%)"
            )

    if issues:
        print(f"WARNINGS ({len(issues)}):")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")
        return 1

    print("Coinbase USDT-USD cache ready for dispersion probe.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
