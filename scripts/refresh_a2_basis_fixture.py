#!/usr/bin/env python3
"""Refresh A2 basis fixture from Binance perp + spot archive trades.

Day 26 deliverable. Mirrors scripts/refresh_binance_funding_fixture.py
shape: fetches a window of paired perp + spot trades, pairs them into
BasisObservations via the Day 26 pairing logic, writes a JSON fixture
that the Day 24 A2 runner can consume.

Usage:
  python scripts/refresh_a2_basis_fixture.py \
      --symbol SOLUSDT \
      --days 14 \
      --end-utc 2024-03-30T00:00:00Z \
      [--cadence-seconds 60]

Output:
  tests/fixtures/a2_basis/{symbol}_basis_{days}d_{start}_{end}.json

Notes:
  - Per Day 26.3: UTC-day-range only (--start = end - days, full days).
  - Per Day 26.5: --cadence-seconds is the only optional flag.
  - Both fetchers cache archives to artifacts/cache/binance_archive[_spot]
  - Monthly ZIPs are large (300MB+); first run on a fresh cache will
    download substantial data. Subsequent runs are fast.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

# Ensure repo root is on path when run as script
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from data.ingestion.vendors.binance.archive_trade_fetcher import (
    BinanceArchiveTradeFetcher,
)
from data.ingestion.vendors.binance.spot_archive_trade_fetcher import (
    BinanceSpotArchiveTradeFetcher,
)
from strategies.a2_basis.data.basis_pairing import (
    pair_perp_spot_to_basis,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh A2 basis fixture from Binance perp + spot archives.",
    )
    parser.add_argument("--symbol", required=True,
                        help="Base symbol, e.g. SOLUSDT.")
    parser.add_argument("--days", type=int, required=True,
                        help="Number of UTC days back from --end-utc.")
    parser.add_argument("--end-utc", required=True,
                        help="End timestamp, ISO 8601, e.g. 2024-03-30T00:00:00Z")
    parser.add_argument("--cadence-seconds", type=int, default=60,
                        help="Bucket size for basis snapshots (default: 60).")
    parser.add_argument("--output-dir",
                        default="tests/fixtures/a2_basis",
                        help="Where to write the fixture JSON.")
    args = parser.parse_args()

    end_str = args.end_utc.replace("Z", "+00:00")
    end = datetime.fromisoformat(end_str)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    start = end - timedelta(days=args.days)

    print(f"Symbol: {args.symbol}")
    print(f"Window: {start.isoformat()} to {end.isoformat()}")
    print(f"Cadence: {args.cadence_seconds}s")
    print()

    perp_fetcher = BinanceArchiveTradeFetcher()
    spot_fetcher = BinanceSpotArchiveTradeFetcher()

    print("Fetching perp archive trades...")
    perp_trades = perp_fetcher.fetch_window(args.symbol, start, end)
    print(f"  perp trades: {len(perp_trades):,}")

    print("Fetching spot archive trades...")
    spot_trades = spot_fetcher.fetch_window(args.symbol, start, end)
    print(f"  spot trades: {len(spot_trades):,}")

    print("Pairing...")
    observations, stats = pair_perp_spot_to_basis(
        perp_trades, spot_trades,
        cadence_seconds=args.cadence_seconds,
    )
    print(f"  perp buckets:       {stats.perp_buckets:,}")
    print(f"  spot buckets:       {stats.spot_buckets:,}")
    print(f"  common buckets:     {stats.common_buckets:,}")
    print(f"  perp-only buckets:  {stats.perp_only_buckets:,}")
    print(f"  spot-only buckets:  {stats.spot_only_buckets:,}")
    print(f"  observations:       {len(observations):,}")

    if not observations:
        print("ERROR: zero observations emitted. Cannot write empty fixture.")
        return 1

    fixture = {
        "venue": "binance",
        "symbol": args.symbol,
        "cadence_seconds": args.cadence_seconds,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "pairing_stats": {
            "perp_trades_in": stats.perp_trades_in,
            "spot_trades_in": stats.spot_trades_in,
            "perp_buckets": stats.perp_buckets,
            "spot_buckets": stats.spot_buckets,
            "common_buckets": stats.common_buckets,
            "perp_only_buckets": stats.perp_only_buckets,
            "spot_only_buckets": stats.spot_only_buckets,
            "cadence_seconds": stats.cadence_seconds,
        },
        "observations": [
            {
                "sampled_at": obs.sampled_at.isoformat().replace("+00:00", "Z"),
                "perp_price": str(obs.perp_price),
                "spot_price": str(obs.spot_price),
            }
            for obs in observations
        ],
    }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    start_str = start.strftime("%Y%m%dT%H%M%S")
    end_str = end.strftime("%Y%m%dT%H%M%S")
    filename = f"{args.symbol}_basis_{args.days}d_{start_str}_{end_str}.json"
    out_path = output_dir / filename
    out_path.write_text(json.dumps(fixture, indent=2))
    print()
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
