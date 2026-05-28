#!/usr/bin/env python3
"""Export a vol_event_fixture.v1 file for the vol_event_persistence probe.

Recomposes three proven patterns already in this repo:
  - BinanceKlinesArchiveFetcher (interval="1h") for perp 1h klines — cache
    served from artifacts/cache/binance_klines_1h/ when months are present
    (offline; no network for cached months).
  - FundingRateFetcher.fetch_window with the 1000-record pagination cursor
    lifted from scripts/_superseded/explore_stress_state_on_candidate_4.py
    (a multi-year funding pull exceeds Binance's 1000-record cap).
  - The deterministic JSON-writer shape from
    scripts/refresh_binance_funding_fixture.py.

Output is the single combined fixture the harness consumes:
    {
      "schema_version": "vol_event_fixture.v1",
      "klines":  [ {... taker_buy_base_volume ...}, ... ],
      "funding": [ {... funding_time, funding_rate, mark_price}, ... ]
    }

NOTE on field naming: the fixture emits "taker_buy_base_volume" (the
harness parser maps it back to BinanceKline.taker_buy_volume). This keeps
the operator-facing fixture legible and matches the harness contract.

NETWORK: klines are cache-served when archived locally (offline). Funding
hits the live Binance USDM fundingRate endpoint, which is geoblocked in
some regions — run on a host with venue access (e.g. via the tunnel) if
funding fetches fail with network errors.

Usage:
  python3 scripts/export_vol_event_fixture.py \
      --symbols BTCUSDT ETHUSDT \
      --start 2023-04-01T00:00:00Z \
      --end   2026-04-01T00:00:00Z \
      --out   fixtures/real_vol_event_fixture.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from data.ingestion.vendors.binance.funding_fetcher import FundingRateFetcher
from data.ingestion.vendors.binance.funding_rate import FundingRate
from data.ingestion.vendors.binance.kline import BinanceKline
from data.ingestion.vendors.binance.klines_archive_fetcher import (
    BinanceKlinesArchiveFetcher,
)

FIXTURE_SCHEMA_VERSION = "vol_event_fixture.v1"
_FUNDING_PAGE_LIMIT = 1000


def _parse_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ─── Klines (cache-served) ───────────────────────────────────────────────────


def fetch_klines(symbol: str, start: datetime, end: datetime) -> list[BinanceKline]:
    fetcher = BinanceKlinesArchiveFetcher(interval="1h")
    print(f"  klines {symbol}: fetch_window {start.date()} -> {end.date()} "
          f"(cache: artifacts/cache/binance_klines_1h/)", file=sys.stderr)
    klines = fetcher.fetch_window(symbol, start, end)
    print(f"  klines {symbol}: {len(klines)} bars", file=sys.stderr)
    return klines


def _serialize_kline(k: BinanceKline) -> dict:
    return {
        "venue": k.venue,
        "instrument": k.instrument,
        "interval": k.interval,
        "open_time": k.open_time.isoformat(),
        "open": str(k.open),
        "high": str(k.high),
        "low": str(k.low),
        "close": str(k.close),
        "volume": str(k.volume),
        "quote_volume": str(k.quote_volume),
        "trade_count": int(k.trade_count),
        # canonical taker_buy_volume -> fixture name taker_buy_base_volume
        "taker_buy_base_volume": str(k.taker_buy_volume),
        "taker_buy_quote_volume": str(k.taker_buy_quote_volume),
    }


# ─── Funding (paginated; lifted from the superseded explore script) ──────────


def fetch_funding(symbol: str, start: datetime, end: datetime) -> list[FundingRate]:
    fetcher = FundingRateFetcher()
    all_records: list[FundingRate] = []
    cursor = start
    batch = 0
    while cursor < end:
        batch += 1
        records = fetcher.fetch_window(symbol, cursor, end, limit=_FUNDING_PAGE_LIMIT)
        if not records:
            break
        print(f"  funding {symbol}: batch {batch} {len(records)} recs "
              f"{records[0].funding_time.date()} -> {records[-1].funding_time.date()}",
              file=sys.stderr)
        all_records.extend(records)
        if len(records) < _FUNDING_PAGE_LIMIT:
            break
        cursor = records[-1].funding_time + timedelta(milliseconds=1)

    # De-dupe by funding_time (pagination edge case), keep ascending order.
    seen: set[datetime] = set()
    deduped: list[FundingRate] = []
    for r in sorted(all_records, key=lambda x: x.funding_time):
        if r.funding_time in seen:
            continue
        seen.add(r.funding_time)
        deduped.append(r)
    print(f"  funding {symbol}: {len(deduped)} records (deduped)", file=sys.stderr)
    return deduped


def _serialize_funding(r: FundingRate) -> dict:
    return {
        "venue": r.venue,
        "instrument": r.instrument,
        "funding_time": r.funding_time.isoformat(),
        "funding_rate": str(r.funding_rate),
        "mark_price": str(r.mark_price) if r.mark_price is not None else None,
    }


# ─── Depth summary (same shape as the pre-run sanity check) ──────────────────


def _print_depth_summary(klines: list[BinanceKline], funding: list[FundingRate],
                         symbols: list[str]) -> None:
    print("=== depth summary ===", file=sys.stderr)
    for sym in symbols:
        kt = sorted(k.open_time for k in klines if k.instrument == sym)
        ft = sorted(f.funding_time for f in funding if f.instrument == sym)
        if kt:
            span_days = (kt[-1] - kt[0]).days
            print(f"  {sym} klines : {kt[0].isoformat()} -> {kt[-1].isoformat()} "
                  f"({len(kt)} bars, ~{span_days}d)", file=sys.stderr)
        else:
            print(f"  {sym} klines : NONE", file=sys.stderr)
        if ft:
            expected = (len(kt) // 24 * 3) if kt else 0  # ~3 funding/day
            print(f"  {sym} funding: {ft[0].isoformat()} -> {ft[-1].isoformat()} "
                  f"({len(ft)} rows; ~{expected} expected for the kline span)",
                  file=sys.stderr)
        else:
            print(f"  {sym} funding: NONE", file=sys.stderr)
    # The probe needs ~2.5+ years for OOS>=6mo under the 80/20 split.
    for sym in symbols:
        kt = sorted(k.open_time for k in klines if k.instrument == sym)
        if kt and (kt[-1] - kt[0]).days < 910:
            print(f"  WARNING {sym}: span < 910d; probe will likely return "
                  f"INSUFFICIENT_SAMPLE (data coverage, not edge).",
                  file=sys.stderr)


# ─── Main ─────────────────────────────────────────────────────────────────────


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    p.add_argument("--start", required=True, help="ISO 8601 UTC, e.g. 2023-04-01T00:00:00Z")
    p.add_argument("--end", required=True, help="ISO 8601 UTC (exclusive)")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--skip-funding", action="store_true",
                   help="klines only (offline); funding array left empty")
    args = p.parse_args(argv)

    start, end = _parse_dt(args.start), _parse_dt(args.end)
    if end <= start:
        print(f"ERROR: end ({end}) must be after start ({start})", file=sys.stderr)
        return 2

    all_klines: list[BinanceKline] = []
    all_funding: list[FundingRate] = []
    for sym in args.symbols:
        print(f"[{sym}]", file=sys.stderr)
        all_klines.extend(fetch_klines(sym, start, end))
        if not args.skip_funding:
            all_funding.extend(fetch_funding(sym, start, end))

    if not all_klines:
        print("ERROR: 0 klines fetched — check symbols/window/cache.", file=sys.stderr)
        return 2

    _print_depth_summary(all_klines, all_funding, args.symbols)

    payload = {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "klines": [_serialize_kline(k) for k in all_klines],
        "funding": [_serialize_funding(r) for r in all_funding],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Wrote {args.out} "
          f"({len(payload['klines'])} klines, {len(payload['funding'])} funding)",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
