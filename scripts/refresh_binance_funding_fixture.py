#!/usr/bin/env python3
"""Refresh the BTCUSDT 14-day funding-rate fixture.

Hits the real Binance USDM-Futures fundingRate endpoint via the
existing FundingRateFetcher. Writes a deterministic JSON file that
the integration test consumes.

Usage:
  python3 scripts/refresh_binance_funding_fixture.py [--symbol BTCUSDT]
                                                     [--days 14]
                                                     [--end-utc YYYY-MM-DDTHH:MM:SSZ]

Default end is "yesterday at 00:00 UTC" so the fixture covers a
complete prior period and won't drift if rerun within the same day.
The committed fixture should be regenerated only when the harness
needs to test against newer data; otherwise it stays stable for
byte-stable test runs.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

# Make the project root importable when run as a script.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from data.ingestion.vendors.binance.funding_fetcher import FundingRateFetcher
from data.ingestion.vendors.binance.funding_rate import FundingRate


FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "binance_funding"


def _serialize(rate: FundingRate) -> dict:
    return {
        "venue": rate.venue,
        "instrument": rate.instrument,
        "funding_time": rate.funding_time.isoformat(),
        "funding_rate": str(rate.funding_rate),
        "mark_price": str(rate.mark_price) if rate.mark_price is not None else None,
        "next_funding_time": (
            rate.next_funding_time.isoformat()
            if rate.next_funding_time is not None else None
        ),
        "ingested_at": (
            rate.ingested_at.isoformat()
            if rate.ingested_at is not None else None
        ),
        "schema_version": rate.schema_version,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument(
        "--end-utc",
        default=None,
        help="End boundary in ISO 8601 (UTC). Default: yesterday 00:00 UTC.",
    )
    args = parser.parse_args()

    if args.end_utc:
        end = datetime.fromisoformat(args.end_utc.replace("Z", "+00:00"))
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
    else:
        # Yesterday 00:00 UTC — stable across reruns within the same day.
        today = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end = today - timedelta(days=1)

    start = end - timedelta(days=args.days)

    fetcher = FundingRateFetcher()
    print(
        f"Fetching {args.symbol} funding rates "
        f"from {start.isoformat()} to {end.isoformat()}...",
        file=sys.stderr,
    )
    rates = fetcher.fetch_window(args.symbol, start=start, end=end)
    print(f"Got {len(rates)} records.", file=sys.stderr)

    if not rates:
        print(
            "ERROR: fetcher returned 0 records — check symbol/window.",
            file=sys.stderr,
        )
        return 2

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    fname = (
        f"{args.symbol}_{args.days}d_"
        f"{start.strftime('%Y%m%dT%H%M%S')}_"
        f"{end.strftime('%Y%m%dT%H%M%S')}.json"
    )
    out = FIXTURE_DIR / fname
    payload = {
        "symbol": args.symbol,
        "start_utc": start.isoformat(),
        "end_utc": end.isoformat(),
        "n_records": len(rates),
        "records": [_serialize(r) for r in rates],
    }
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
