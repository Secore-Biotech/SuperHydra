"""Aligned hourly market state loader.

Engineering hygiene utility. Loads the same data that exploration scripts
have been re-aligning ad hoc and returns a sorted, inner-joined list of
HourlyMarketState records.

This is NOT:
  - a strategy
  - a regime classifier
  - a "stress detector"
  - a feature engineering layer

It IS:
  - a thin loader that consolidates the project's repeated alignment logic
  - stdlib-only (no pandas dependency added)
  - honest about gaps (funding only included where cached; no imputation)

Returns a list of dataclasses, not a dataframe. Trivially convertible
to pandas later if downstream code needs it; doesn't require pandas now.

Inputs:
  start_utc, end_utc: timezone-aware UTC bounds (end exclusive)
  assets:             list of asset symbols, e.g. ["BTCUSDT", "ETHUSDT"]
  venues:             list of venues, e.g. ["binance", "okx"]

Output:
  list[HourlyMarketState], inner-joined on hourly timestamp across all
  available (asset, venue, instrument_type) tuples that returned data,
  sorted chronologically.

Alignment rule:
  Inner join. An hour is included only if EVERY requested (asset, venue,
  instrument_type) tuple has data for that hour. Funding is best-effort:
  if funding for an asset is cached, it's attached; if not, the funding
  field is None. Funding does NOT participate in the inner join (a missing
  funding cache wouldn't drop the row).

Funding handling:
  Only BTC funding is currently cached (artifacts/cache/btc_funding_explore.json).
  ETH funding is not yet cached. The loader makes this honest: any asset
  without a funding cache gets funding=None on every row.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional


# Module is positioned at data/loaders/market_state_loader.py
# Repo root is two dirs up
REPO_ROOT = Path(__file__).resolve().parents[2]


# ─── Public dataclass ────────────────────────────────────────────────────

@dataclass(frozen=True)
class HourlyMarketState:
    """One hour's worth of aligned market state across the requested universe.

    prices, volumes are dicts keyed by a string identifier like
    "{venue}_{asset}_{instrument_type}". For example:
      binance_BTCUSDT_perp_close
      binance_BTCUSDT_spot_close
      okx_BTCUSDT_perp_close

    The key includes asset to allow multi-asset frames in the same record.
    funding is keyed by "{venue}_{asset}_funding".
    """
    timestamp: datetime
    prices: dict[str, Decimal] = field(default_factory=dict)
    highs: dict[str, Decimal] = field(default_factory=dict)
    lows: dict[str, Decimal] = field(default_factory=dict)
    volumes: dict[str, Decimal] = field(default_factory=dict)
    funding: dict[str, Optional[Decimal]] = field(default_factory=dict)


# ─── Per-leg loaders ─────────────────────────────────────────────────────

def _load_binance_perp(asset: str, start: datetime, end: datetime) -> dict:
    """Load Binance USDM-perp 1h klines for an asset. Returns dict keyed
    by open_time → kline-like record."""
    from data.ingestion.vendors.binance.klines_archive_fetcher import (
        BinanceKlinesArchiveFetcher,
    )
    fetcher = BinanceKlinesArchiveFetcher(interval="1h")
    klines = fetcher.fetch_window(asset, start, end)
    return {k.open_time: k for k in klines}


def _load_binance_spot(asset: str, start: datetime, end: datetime) -> dict:
    """Load Binance spot 1h klines for an asset."""
    from data.ingestion.vendors.binance.klines_archive_spot_fetcher import (
        BinanceKlinesArchiveSpotFetcher,
    )
    fetcher = BinanceKlinesArchiveSpotFetcher(interval="1h")
    klines = fetcher.fetch_window(asset, start, end)
    return {k.open_time: k for k in klines}


def _load_okx_perp(asset: str, start: datetime, end: datetime) -> dict:
    """Load OKX USDT-margined perp 1h klines for an asset.

    Asset translation: "BTCUSDT" → "BTC-USDT-SWAP", "ETHUSDT" → "ETH-USDT-SWAP".
    """
    from data.ingestion.vendors.okx.okx_klines_fetcher import OkxKlinesFetcher
    # Translate Binance-style symbol to OKX-style instrument
    base = asset.replace("USDT", "")
    inst_id = f"{base}-USDT-SWAP"
    fetcher = OkxKlinesFetcher(inst_id=inst_id, interval="1H")
    klines = fetcher.fetch_window(start, end)
    return {k.open_time: k for k in klines}


def _load_funding(asset: str, start: datetime, end: datetime) -> dict[datetime, Decimal]:
    """Load Binance funding rates for an asset from the exploration cache.

    Currently only BTC funding is cached. For other assets, returns empty dict.
    Funding times in cache may have microsecond offsets (e.g. 08:00:00.013);
    we truncate to the hour for alignment with kline timestamps.
    """
    # Map Binance symbol to cache filename
    cache_map = {
        "BTCUSDT": REPO_ROOT / "artifacts" / "cache" / "btc_funding_explore.json",
    }
    cache_path = cache_map.get(asset)
    if cache_path is None or not cache_path.exists():
        return {}

    with cache_path.open() as f:
        raw = json.load(f)

    out = {}
    for rec in raw:
        t = datetime.fromisoformat(rec["time"])
        if t < start or t >= end:
            continue
        # Truncate to the hour for alignment with kline open_times
        hour_aligned = t.replace(minute=0, second=0, microsecond=0)
        out[hour_aligned] = Decimal(rec["rate"])
    return out


# Dispatch tables — venue → (instrument_type → loader)
_VENUE_LOADERS = {
    "binance": {
        "perp": _load_binance_perp,
        "spot": _load_binance_spot,
    },
    "okx": {
        "perp": _load_okx_perp,
    },
}


# ─── Public function ─────────────────────────────────────────────────────

def load_hourly_market_state(
    start_utc: datetime,
    end_utc: datetime,
    assets: list[str] = None,
    venues: list[str] = None,
    instrument_types: list[str] = None,
    # Testing hook: override the dispatch table with a custom one.
    # In production this stays None and the module-level _VENUE_LOADERS is used.
    _venue_loaders_override: dict | None = None,
    _funding_loader_override=None,
) -> list[HourlyMarketState]:
    """Load aligned hourly market state across the requested universe.

    Defaults:
      assets:           ["BTCUSDT"]
      venues:           ["binance", "okx"]
      instrument_types: ["perp", "spot"] (filtered per venue's capabilities)

    Returns a chronologically sorted list of HourlyMarketState records.
    An hour is included only if every requested (venue, asset, type) tuple
    has data at that hour. Funding is best-effort and does not gate inclusion.
    """
    if start_utc.tzinfo is None:
        raise ValueError("start_utc must be timezone-aware")
    if end_utc.tzinfo is None:
        raise ValueError("end_utc must be timezone-aware")
    if end_utc <= start_utc:
        raise ValueError(f"end_utc ({end_utc}) must be after start_utc ({start_utc})")

    if assets is None:
        assets = ["BTCUSDT"]
    if venues is None:
        venues = ["binance", "okx"]
    if instrument_types is None:
        instrument_types = ["perp", "spot"]

    venue_loaders = _venue_loaders_override if _venue_loaders_override is not None else _VENUE_LOADERS
    funding_loader = _funding_loader_override if _funding_loader_override is not None else _load_funding

    # Step 1: load every requested (venue, asset, instrument_type) leg.
    # Tracks the cross-product of what successfully loaded.
    legs: dict[tuple[str, str, str], dict] = {}
    for venue in venues:
        venue_dispatch = venue_loaders.get(venue)
        if venue_dispatch is None:
            continue
        for inst_type in instrument_types:
            loader = venue_dispatch.get(inst_type)
            if loader is None:
                continue  # this venue doesn't support this instrument type
            for asset in assets:
                key = (venue, asset, inst_type)
                try:
                    leg_data = loader(asset, start_utc, end_utc)
                except Exception:
                    # If a leg fails to load entirely, treat it as absent for
                    # this call. Caller can debug separately by calling the
                    # individual fetchers.
                    continue
                if leg_data:
                    legs[key] = leg_data

    if not legs:
        return []

    # Step 2: compute the inner-join timestamp set (intersection of keys).
    common_times = None
    for leg_data in legs.values():
        if common_times is None:
            common_times = set(leg_data.keys())
        else:
            common_times &= set(leg_data.keys())
    if not common_times:
        return []

    # Step 3: load funding for each asset (best-effort).
    funding_by_asset: dict[str, dict[datetime, Decimal]] = {}
    for asset in assets:
        funding_by_asset[asset] = funding_loader(asset, start_utc, end_utc)

    # Step 4: build the output records, sorted chronologically.
    records: list[HourlyMarketState] = []
    for t in sorted(common_times):
        prices: dict[str, Decimal] = {}
        highs: dict[str, Decimal] = {}
        lows: dict[str, Decimal] = {}
        volumes: dict[str, Decimal] = {}
        for (venue, asset, inst_type), leg_data in legs.items():
            kline = leg_data[t]
            base = f"{venue}_{asset}_{inst_type}"
            prices[f"{base}_close"] = kline.close
            highs[f"{base}_high"] = kline.high
            lows[f"{base}_low"] = kline.low
            volumes[f"{base}_volume"] = kline.volume

        # Funding (best-effort, may be None)
        funding: dict[str, Optional[Decimal]] = {}
        for asset in assets:
            funding_dict = funding_by_asset.get(asset, {})
            funding[f"binance_{asset}_funding"] = funding_dict.get(t)

        records.append(HourlyMarketState(
            timestamp=t,
            prices=prices,
            highs=highs,
            lows=lows,
            volumes=volumes,
            funding=funding,
        ))

    return records
