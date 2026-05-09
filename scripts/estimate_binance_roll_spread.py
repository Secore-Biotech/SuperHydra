#!/usr/bin/env python3
"""Day 19b.3 — Roll effective-spread estimation harness for Binance perps.

Pulls aggregate trades for N short windows in a regime, applies Roll's
autocovariance estimator (analytics/effective_spread.py) per window,
and writes a JSON artifact summarizing per-window results plus
aggregate stats. Raw trades are NOT persisted — they are ephemeral
in-memory only.

Output is research-only research support, NOT execution-grade
calibration. No cost profile should be promoted solely from this
script's output. See docs/research/sol_roll_spread_estimation_memo.md
for the full caveat list.

Usage:
  python3 scripts/estimate_binance_roll_spread.py \
      --symbol SOLUSDT --regime quiet --output artifacts/quiet.json

  python3 scripts/estimate_binance_roll_spread.py \
      --symbol SOLUSDT --regime volatile --output artifacts/volatile.json

  # Custom window list:
  python3 scripts/estimate_binance_roll_spread.py \
      --symbol SOLUSDT --regime custom \
      --custom-windows '["2024-03-01T12:00:00Z","2024-03-04T12:00:00Z"]' \
      --output artifacts/custom.json
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

# Allow running from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analytics.effective_spread import estimate_roll, RollEstimate
from data.ingestion.vendors.binance.trade_fetcher import (
    BinanceTradeFetcher,
    PermanentFetcherError,
    TransientFetcherError,
)


# Predefined regime windows: 5 windows of 5 minutes each, distributed
# every 3 days through a 14-day fixture window, at 12:00 UTC.
#
# WARNING (Day 19b finding, 2026-05-09):
#   Binance /fapi/v1/aggTrades REST endpoint serves recent history only.
#   The 'quiet' (Jan 2025) and 'volatile' (Mar 2024) regimes BELOW are
#   operationally inaccessible via this endpoint — both return zero
#   trades. To use these windows, ingest from data.binance.vision
#   monthly archives instead (Day 19c deliverable:
#   data/ingestion/vendors/binance/archive_trade_fetcher.py). The REST
#   fetcher in trade_fetcher.py works correctly for recent windows; it
#   is the venue's data-availability boundary that excludes deep
#   history, not a fetcher bug.
#
#   Until Day 19c lands, --regime quiet and --regime volatile will
#   produce empty artifacts. Use --regime custom with recent
#   timestamps for any meaningful Roll estimation today.
#
PREDEFINED_REGIMES = {
    "quiet": [
        datetime(2025, 1, 1,  12, 0, tzinfo=timezone.utc),
        datetime(2025, 1, 4,  12, 0, tzinfo=timezone.utc),
        datetime(2025, 1, 7,  12, 0, tzinfo=timezone.utc),
        datetime(2025, 1, 10, 12, 0, tzinfo=timezone.utc),
        datetime(2025, 1, 13, 12, 0, tzinfo=timezone.utc),
    ],
    "volatile": [
        datetime(2024, 3, 1,  12, 0, tzinfo=timezone.utc),
        datetime(2024, 3, 4,  12, 0, tzinfo=timezone.utc),
        datetime(2024, 3, 7,  12, 0, tzinfo=timezone.utc),
        datetime(2024, 3, 10, 12, 0, tzinfo=timezone.utc),
        datetime(2024, 3, 13, 12, 0, tzinfo=timezone.utc),
    ],
}


def _decimal_to_str(v):
    """Decimal-aware JSON encoder helper."""
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, datetime):
        return v.isoformat()
    return v


def _serialize_estimate(window_start: datetime, est: RollEstimate, n_trades: int) -> dict:
    return {
        "window_start_utc": window_start.isoformat(),
        "n_trades": n_trades,
        "mean_price": _decimal_to_str(est.mean_price),
        "autocov_1": _decimal_to_str(est.autocov_1),
        "half_spread_price": _decimal_to_str(est.half_spread_price),
        "full_spread_price": _decimal_to_str(est.full_spread_price),
        "half_spread_bps": _decimal_to_str(est.half_spread_bps),
        "full_spread_bps": _decimal_to_str(est.full_spread_bps),
        "estimator_name": est.estimator_name,
        "estimator_version": est.estimator_version,
        "undefined_reason": est.undefined_reason,
    }


def _serialize_skipped(
    window_start: datetime, n_trades: int, reason: str,
) -> dict:
    return {
        "window_start_utc": window_start.isoformat(),
        "n_trades": n_trades,
        "skipped": True,
        "skip_reason": reason,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbol", required=True,
                   help="Binance symbol, e.g. SOLUSDT")
    p.add_argument("--regime", required=True,
                   choices=["quiet", "volatile", "custom"],
                   help="Predefined regime, or 'custom' with --custom-windows")
    p.add_argument("--custom-windows",
                   help="JSON list of ISO-8601 window-start times (UTC). "
                        "Required if --regime=custom.")
    p.add_argument("--window-minutes", type=int, default=5,
                   help="Window length in minutes (default 5)")
    p.add_argument("--output", required=True,
                   help="Output path for JSON artifact")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    if args.regime == "custom":
        if not args.custom_windows:
            print("ERROR: --custom-windows required when regime=custom",
                  file=sys.stderr)
            return 2
        try:
            window_strs = json.loads(args.custom_windows)
        except json.JSONDecodeError as e:
            print(f"ERROR: --custom-windows must be valid JSON: {e}",
                  file=sys.stderr)
            return 2
        windows = [
            datetime.fromisoformat(s.replace("Z", "+00:00"))
            for s in window_strs
        ]
    else:
        windows = PREDEFINED_REGIMES[args.regime]

    print(f"Estimating Roll spread for {args.symbol} in regime '{args.regime}'")
    print(f"Windows: {len(windows)} of {args.window_minutes}min each")

    fetcher = BinanceTradeFetcher()
    window_delta = timedelta(minutes=args.window_minutes)

    per_window: list[dict] = []
    valid_full_bps: list[Decimal] = []
    valid_half_bps: list[Decimal] = []
    undefined_count = 0

    started_at = datetime.now(tz=timezone.utc)

    for i, ws in enumerate(windows):
        we = ws + window_delta
        print(f"\n[{i+1}/{len(windows)}] {ws.isoformat()} → {we.isoformat()}")
        try:
            trades = fetcher.fetch_window(
                args.symbol, ws, we,
                limit=1000, max_pages=200,
            )
        except (TransientFetcherError, PermanentFetcherError) as e:
            print(f"  fetch failed: {e}")
            per_window.append(_serialize_skipped(ws, 0, f"fetch_failed: {e}"))
            continue

        n = len(trades)
        print(f"  fetched {n} trades")

        if n < 3:
            per_window.append(_serialize_skipped(
                ws, n, "too_few_trades_for_estimator",
            ))
            continue

        prices = [t.price for t in trades]
        try:
            est = estimate_roll(prices)
        except (ValueError, TypeError) as e:
            print(f"  estimator failed: {e}")
            per_window.append(_serialize_skipped(
                ws, n, f"estimator_failed: {e}",
            ))
            continue

        per_window.append(_serialize_estimate(ws, est, n))
        if est.undefined_reason is None:
            valid_full_bps.append(est.full_spread_bps)
            valid_half_bps.append(est.half_spread_bps)
            print(
                f"  defined estimate: full {est.full_spread_bps:.4f} bps, "
                f"half {est.half_spread_bps:.4f} bps"
            )
        else:
            undefined_count += 1
            print(f"  undefined: {est.undefined_reason}")

    finished_at = datetime.now(tz=timezone.utc)

    aggregate = {
        "n_windows_total": len(windows),
        "n_windows_valid": len(valid_full_bps),
        "n_windows_undefined": undefined_count,
        "n_windows_skipped": len(windows) - len(valid_full_bps) - undefined_count,
    }

    if valid_full_bps:
        aggregate["full_spread_bps_median"] = str(
            statistics.median(valid_full_bps)
        )
        aggregate["full_spread_bps_mean"] = str(
            sum(valid_full_bps) / Decimal(len(valid_full_bps))
        )
        aggregate["half_spread_bps_median"] = str(
            statistics.median(valid_half_bps)
        )
        aggregate["half_spread_bps_mean"] = str(
            sum(valid_half_bps) / Decimal(len(valid_half_bps))
        )
        aggregate["full_spread_bps_min"] = str(min(valid_full_bps))
        aggregate["full_spread_bps_max"] = str(max(valid_full_bps))

    artifact = {
        "schema_version": "roll_spread_estimation.v1",
        "symbol": args.symbol,
        "regime": args.regime,
        "window_minutes": args.window_minutes,
        "estimator_name": "roll_1984",
        "estimator_version": "v1",
        "started_at_utc": started_at.isoformat(),
        "finished_at_utc": finished_at.isoformat(),
        "elapsed_seconds": (finished_at - started_at).total_seconds(),
        "per_window": per_window,
        "aggregate": aggregate,
        "research_only_caveat": (
            "Output is research support only. Roll's estimator on public "
            "aggTrades is NOT promotion-grade execution calibration. No "
            "cost profile should be promoted solely from this result. See "
            "docs/research/sol_roll_spread_estimation_memo.md."
        ),
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(artifact, indent=2))
    print(f"\nWrote {output_path}")
    print(f"Aggregate: {aggregate}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
