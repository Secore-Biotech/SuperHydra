"""Smoke test: BinanceKlinesArchiveSpotFetcher.

Fetches BTCUSDT spot 1d klines for two test months. Verifies:
  - URL pattern works (spot archive returns 200 not 404)
  - Parser produces valid BinanceKline records
  - Cache directory created at expected path
  - Cached file persists for second-pass instant-load
  - Sort+dedupe produces expected count

NOT a unit test. NOT a regression test. One-shot exploratory verification
before relying on the fetcher for the hedged-carry simulator.

Usage:
    python scripts/smoke_test_spot_fetcher.py
"""
from __future__ import annotations

import sys
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
    print("=" * 70)
    print("Smoke test: BinanceKlinesArchiveSpotFetcher")
    print("=" * 70)
    print()

    fetcher = BinanceKlinesArchiveSpotFetcher(interval="1d")
    cache_dir = _default_cache_dir_for("1d")
    print(f"Cache directory: {cache_dir}")
    print(f"Cache dir exists pre-fetch: {cache_dir.exists()}")
    print()

    # Fetch BTCUSDT spot for two months: 2024-01 and 2024-02
    # Small window, well within Binance's archive range, well-known
    # high-volume instrument so the archives must exist.
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2024, 3, 1, tzinfo=timezone.utc)
    print(f"Fetching BTCUSDT spot 1d klines: {start.date()} to {end.date()}")
    print(f"Expected count: ~60 daily bars")
    print()

    klines = fetcher.fetch_window("BTCUSDT", start, end)
    print(f"Returned: {len(klines)} klines")

    if not klines:
        print("FAIL: no klines returned. Possible causes:")
        print(f"  - URL pattern wrong (404 → cached as .notfound)")
        print(f"  - {cache_dir} contains .notfound markers")
        print(f"  - Binance returned empty archive")
        return 1

    first = klines[0]
    last = klines[-1]
    print()
    print("First record:")
    print(f"  open_time:   {first.open_time}")
    print(f"  instrument:  {first.instrument}")
    print(f"  interval:    {first.interval}")
    print(f"  venue:       {first.venue}")
    print(f"  open/close:  {first.open} → {first.close}")
    print(f"  volume:      {first.volume}")
    print(f"  trade_count: {first.trade_count}")
    print()
    print("Last record:")
    print(f"  open_time:   {last.open_time}")
    print(f"  open/close:  {last.open} → {last.close}")
    print(f"  volume:      {last.volume}")
    print()

    # Sanity checks
    issues = []
    if len(klines) < 50 or len(klines) > 70:
        issues.append(
            f"unexpected count: {len(klines)} (expected ~60 for 2 months daily)"
        )
    if first.venue != "binance":
        issues.append(f"first.venue = {first.venue!r}, expected 'binance'")
    if first.instrument != "BTCUSDT":
        issues.append(f"first.instrument = {first.instrument!r}, expected 'BTCUSDT'")
    if first.interval != "1d":
        issues.append(f"first.interval = {first.interval!r}, expected '1d'")

    # Sanity-check the prices: BTC spot in Jan/Feb 2024 was ~$40K-$60K
    if not (20000 < float(first.close) < 100000):
        issues.append(
            f"first.close = {first.close}, out of expected BTC range $20k-$100k"
        )

    # Verify sort
    prev = klines[0].open_time
    for k in klines[1:]:
        if k.open_time <= prev:
            issues.append(f"unsorted: {prev} not before {k.open_time}")
            break
        prev = k.open_time

    # Verify cache populated
    print("Cache directory contents after fetch:")
    cached = sorted(cache_dir.glob("*.zip"))
    for c in cached:
        size_kb = c.stat().st_size / 1024
        print(f"  {c.name}  ({size_kb:.1f} KB)")
    print()

    if not cached:
        issues.append("no zip files in cache after fetch")

    # Second-pass: refetch the same window, should be instant from cache
    print("Second pass (should be instant — cache hit)...")
    t_start = __import__("time").monotonic()
    klines2 = fetcher.fetch_window("BTCUSDT", start, end)
    t_elapsed = __import__("time").monotonic() - t_start
    print(f"  Returned {len(klines2)} klines in {t_elapsed:.3f}s")

    if len(klines2) != len(klines):
        issues.append(
            f"second pass returned {len(klines2)}, first pass returned {len(klines)}"
        )
    if t_elapsed > 1.0:
        issues.append(
            f"second pass took {t_elapsed:.2f}s, expected <1s (cache hit)"
        )

    print()
    print("=" * 70)
    if issues:
        print(f"FAIL ({len(issues)} issue{'s' if len(issues) != 1 else ''}):")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")
        return 1
    else:
        print("PASS — spot fetcher works end-to-end")
        print()
        print("Spot fetcher is ready for the hedged-carry simulator next session.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
