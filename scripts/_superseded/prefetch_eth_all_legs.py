"""Pre-fetch ETH 1h klines across three legs for event-count expansion.

Populates:
  artifacts/cache/binance_klines_1h/        (Binance ETHUSDT perp 1h)
  artifacts/cache/binance_klines_spot_1h/   (Binance ETHUSDT spot 1h)
  artifacts/cache/okx_klines_ETH-USDT-SWAP_1H/  (OKX ETH-USDT-SWAP perp 1h)

Note: Binance perp/spot caches are SHARED across symbols (BTC and ETH
both live in the same directory, distinguished by filename like
ETHUSDT-1h-YYYY-MM.zip vs BTCUSDT-1h-YYYY-MM.zip). OKX cache is
already per-instrument.

Estimated runtime:
  Binance perp ETH:    ~37 archive fetches × 0.5s = ~18s
  Binance spot ETH:    ~37 archive fetches × 0.5s = ~18s
  OKX perp ETH:        ~88 REST calls × 0.3s = ~26s
  Total:               ~60-90s wall time

NOT a strategy. One-shot data prep for probe_event_count_expansion.py.
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
)
from data.ingestion.vendors.binance.klines_archive_spot_fetcher import (
    BinanceKlinesArchiveSpotFetcher,
)
from data.ingestion.vendors.okx.okx_klines_fetcher import (
    OkxKlinesFetcher,
    _default_cache_dir_for as okx_cache_dir,
)


WINDOW_START = datetime(2023, 4, 1, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 5, 1, tzinfo=timezone.utc)


def fetch_leg(name: str, fetch_callable, expected_min: int = 22000) -> int:
    print(f"--- {name} ---")
    t0 = time.monotonic()
    klines = fetch_callable()
    elapsed = time.monotonic() - t0
    print(f"  Returned {len(klines)} klines in {elapsed:.1f}s")
    if klines:
        print(f"  First: {klines[0].open_time}  close={klines[0].close}")
        print(f"  Last:  {klines[-1].open_time}  close={klines[-1].close}")
    if len(klines) < expected_min:
        print(f"  WARNING: count {len(klines)} below expected min {expected_min}")
    print()
    return len(klines)


def main() -> int:
    print(f"Window: {WINDOW_START.date()} → {WINDOW_END.date()}")
    print()

    # Binance ETH perp
    perp_fetcher = BinanceKlinesArchiveFetcher(interval="1h")
    n_perp = fetch_leg(
        "Binance ETHUSDT perp 1h",
        lambda: perp_fetcher.fetch_window("ETHUSDT", WINDOW_START, WINDOW_END),
    )

    # Binance ETH spot
    spot_fetcher = BinanceKlinesArchiveSpotFetcher(interval="1h")
    n_spot = fetch_leg(
        "Binance ETHUSDT spot 1h",
        lambda: spot_fetcher.fetch_window("ETHUSDT", WINDOW_START, WINDOW_END),
    )

    # OKX ETH perp
    okx_fetcher = OkxKlinesFetcher(inst_id="ETH-USDT-SWAP", interval="1H")
    n_okx = fetch_leg(
        "OKX ETH-USDT-SWAP 1h",
        lambda: okx_fetcher.fetch_window(WINDOW_START, WINDOW_END),
    )

    # Final sanity
    issues = []
    expected_min = 22000
    for name, n in [("Binance perp", n_perp), ("Binance spot", n_spot), ("OKX perp", n_okx)]:
        if n < expected_min:
            issues.append(f"{name} count {n} below expected min {expected_min}")

    if issues:
        print(f"WARNING: {len(issues)} issue(s):")
        for i in issues:
            print(f"  - {i}")
        return 1

    print("All three ETH legs cached. Ready for event-count expansion probe.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
