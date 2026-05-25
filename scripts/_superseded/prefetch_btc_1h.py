"""Pre-fetch BTCUSDT perp 1h and spot 1h klines over the OOS window.

Two-leg pre-fetch:
  - PERP: artifacts/cache/binance_klines_1h/
  - SPOT: artifacts/cache/binance_klines_spot_1h/

Needed for sim_hedged_carry_v2 which aligns funding events to nearest
prior 1h bar instead of using daily closes.

Both fetchers already handle the ms→μs spot timestamp transition correctly
(verified by daily prefetch + smoke tests). 1h archives use the same
schema as 1d archives, just at higher cadence.

Expected runtime: ~37s wall on first run (74 archives, 0.5s throttle).
Instant on rerun.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data.ingestion.vendors.binance.klines_archive_fetcher import (
    BinanceKlinesArchiveFetcher,
    _default_cache_dir_for as _perp_cache_dir,
)
from data.ingestion.vendors.binance.klines_archive_spot_fetcher import (
    BinanceKlinesArchiveSpotFetcher,
    _default_cache_dir_for as _spot_cache_dir,
)


def fetch_leg(name: str, fetcher, cache_dir, start: datetime, end: datetime) -> int:
    print(f"--- {name} ---")
    print(f"Cache directory: {cache_dir}")
    pre = len(list(cache_dir.glob('*.zip'))) if cache_dir.exists() else 0
    print(f"Cached zips before: {pre}")

    t0 = time.monotonic()
    klines = fetcher.fetch_window("BTCUSDT", start, end)
    elapsed = time.monotonic() - t0

    post = len(list(cache_dir.glob('*.zip')))
    print(f"Returned {len(klines)} klines in {elapsed:.1f}s")
    print(f"Cached zips after: {post} (+{post - pre} new)")
    print(f"First: {klines[0].open_time}  close={klines[0].close}")
    print(f"Last:  {klines[-1].open_time}  close={klines[-1].close}")
    print()
    return len(klines)


def main() -> int:
    start = datetime(2023, 4, 1, tzinfo=timezone.utc)
    end = datetime(2026, 5, 1, tzinfo=timezone.utc)
    print(f"Window: {start.date()} → {end.date()} (exclusive)")
    print()

    perp_fetcher = BinanceKlinesArchiveFetcher(interval="1h")
    spot_fetcher = BinanceKlinesArchiveSpotFetcher(interval="1h")

    perp_n = fetch_leg(
        "PERP 1h", perp_fetcher, _perp_cache_dir("1h"), start, end,
    )
    spot_n = fetch_leg(
        "SPOT 1h", spot_fetcher, _spot_cache_dir("1h"), start, end,
    )

    expected_min = 22000  # ~3 years × 365 × 24 ≈ 26280 hours; allow 15% missing
    if perp_n < expected_min or spot_n < expected_min:
        print(f"WARNING: kline counts low. perp={perp_n}, spot={spot_n}, expected ≥{expected_min}")
        return 1

    print("Both legs cached. Ready for sim_hedged_carry_v2.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
