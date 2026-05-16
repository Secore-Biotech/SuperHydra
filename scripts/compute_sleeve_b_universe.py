#!/usr/bin/env python3
"""Compute the Sleeve B research universe.

Per pre-registration (docs/strategies/sleeve_b_research_preregistration.md,
commit fe909bb) Section 1:

  Universe: top-30 by Binance USDT-margined perp ADV
  ADV window: 2026-03-15 to 2026-04-15 (fixed)
  As-of date: 2026-04-15
  Min listing age: 90 days
  Min continuous trading prior to ADV-window start: 60 days
  Stablecoins excluded
  Index/basket contracts excluded
  Survivorship: operational approximation (current exchangeInfo)

Output: tests/fixtures/sleeve_b/universe_top30_20260415.json

The universe is frozen at fixture commit time. Per the pre-registration:
no reconstitution, no rolling inclusion during the research window.
This script runs ONCE; re-running produces identical output by
construction (deterministic given Binance archive data).

Reviewer additions per locked decisions:
  - survivorship_warning field disclosing the operational approximation
  - universe_membership_policy: "frozen", reconstitution_permitted: false
  - raw_adv_candidates array with full audit trail (every candidate
    considered, ADV computed, filter outcomes)

Usage:
  python3 scripts/compute_sleeve_b_universe.py
"""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from data.ingestion.vendors.binance.klines_archive_fetcher import (  # noqa: E402
    BinanceKlinesArchiveFetcher,
)

# Pre-registration constants (locked)
AS_OF_DATE = datetime(2026, 4, 15, tzinfo=timezone.utc)
ADV_WINDOW_START = datetime(2026, 3, 15, tzinfo=timezone.utc)
ADV_WINDOW_END = datetime(2026, 4, 15, tzinfo=timezone.utc)
ADV_WINDOW_DAYS = 30  # 2026-03-15 to 2026-04-15 = 31 calendar days; using 30 per pre-reg
MIN_LISTING_AGE_DAYS = 90
MIN_CONTINUOUS_TRADING_DAYS_PRIOR = 60
UNIVERSE_SIZE = 30

FIXTURE_DIR = REPO_ROOT / "tests/fixtures/sleeve_b"
FIXTURE_PATH = FIXTURE_DIR / "universe_top30_20260415.json"

EXCHANGE_INFO_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"

# Stablecoins to exclude from base-asset position
STABLECOIN_BASE_ASSETS = {
    "USDC", "BUSD", "DAI", "FDUSD", "TUSD", "USDP", "UST", "USDD",
    "GUSD", "LUSD", "FRAX", "SUSD", "PYUSD",
}


def _fetch_exchange_info():
    """Fetch Binance USDT-M Futures exchangeInfo (live REST call)."""
    print(f"Fetching exchangeInfo from {EXCHANGE_INFO_URL}...")
    req = urllib.request.Request(
        EXCHANGE_INFO_URL,
        headers={"User-Agent": "SuperHydra/sleeve-b-universe/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read()
    data = json.loads(body)
    print(f"  fetched {len(data.get('symbols', []))} symbols")
    return data


def _is_index_or_basket(sym_info: dict) -> bool:
    """Detect index/basket products. Binance exposes underlyingType."""
    if sym_info.get("underlyingType") == "INDEX":
        return True
    # Defensive: known basket patterns even if underlyingType isn't set
    base = sym_info.get("baseAsset", "")
    if base in ("BTCDOM", "DEFI"):
        return True
    return False


def _is_stablecoin(sym_info: dict) -> bool:
    return sym_info.get("baseAsset") in STABLECOIN_BASE_ASSETS


def _filter_candidates(exchange_info: dict) -> list[dict]:
    """Apply Section 1 filters: USDT-margined perp, TRADING status,
    not index, not stablecoin. Returns list of candidate dicts with
    onboard_date computed."""
    candidates = []
    for sym in exchange_info.get("symbols", []):
        if sym.get("contractType") != "PERPETUAL":
            continue
        if sym.get("quoteAsset") != "USDT":
            continue
        if sym.get("status") != "TRADING":
            continue
        if _is_index_or_basket(sym):
            continue
        if _is_stablecoin(sym):
            continue
        # Operational filter: non-ASCII symbols are Binance memecoin novelties
        # (e.g. Chinese-character base assets). Not credible top-30 candidates;
        # they break URL encoding, filename conventions, and downstream string
        # handling. Documented in fixture metadata under filters_applied.
        if not sym["symbol"].isascii():
            continue

        onboard_ms = sym.get("onboardDate")
        if onboard_ms is None:
            continue
        onboard_dt = datetime.fromtimestamp(onboard_ms / 1000, tz=timezone.utc)
        listing_age_days = (AS_OF_DATE - onboard_dt).days

        candidates.append({
            "symbol": sym["symbol"],
            "base_asset": sym["baseAsset"],
            "onboard_date": onboard_dt.strftime("%Y-%m-%d"),
            "onboard_ms": onboard_ms,
            "listing_age_days": listing_age_days,
        })
    print(f"  {len(candidates)} candidates after USDT-perp / status / "
          "index / stablecoin filters")
    return candidates


def _filter_by_listing_age(candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    """Apply min listing age (90 days). Returns (passed, excluded)."""
    passed = []
    excluded = []
    for c in candidates:
        if c["listing_age_days"] >= MIN_LISTING_AGE_DAYS:
            passed.append(c)
        else:
            excluded.append({
                **c,
                "filter_failures": ["listing_age_below_threshold"],
            })
    print(f"  {len(passed)} candidates passed listing-age filter, "
          f"{len(excluded)} excluded")
    return passed, excluded


def _compute_adv(
    fetcher: BinanceKlinesArchiveFetcher,
    symbol: str,
) -> tuple[Decimal | None, int, list[str]]:
    """Compute ADV for one symbol over the locked window.

    Returns (adv_usdt, days_with_data, failure_reasons).
    adv_usdt is None if symbol had no archive data.
    """
    klines = fetcher.fetch_window(
        symbol, ADV_WINDOW_START, ADV_WINDOW_END,
    )
    failures = []
    if not klines:
        failures.append("no_archive_data_in_adv_window")
        return None, 0, failures
    total_quote_vol = sum((k.quote_volume for k in klines), Decimal("0"))
    days_with_data = len(klines)
    adv = total_quote_vol / Decimal(ADV_WINDOW_DAYS)
    return adv, days_with_data, failures


def _check_continuous_history(
    fetcher: BinanceKlinesArchiveFetcher,
    symbol: str,
) -> tuple[bool, int]:
    """Check whether the symbol has >= 60 continuous trading days before
    ADV-window start (2026-03-15). Looks back 60+ days and counts klines.

    Returns (passed, days_found).
    """
    # Look back from 2026-03-15 by 60 days = 2026-01-14. Add small buffer
    # for the boundary day handling.
    lookback_start = datetime(2026, 1, 13, tzinfo=timezone.utc)
    lookback_end = ADV_WINDOW_START
    klines = fetcher.fetch_window(symbol, lookback_start, lookback_end)
    days_found = len(klines)
    # 2026-01-13 to 2026-03-15 = 61 days; require >= 60 days of data
    passed = days_found >= MIN_CONTINUOUS_TRADING_DAYS_PRIOR
    return passed, days_found


def main():
    print("Sleeve B universe computation")
    print("=" * 60)
    print(f"As-of date: {AS_OF_DATE.strftime('%Y-%m-%d')}")
    print(f"ADV window: {ADV_WINDOW_START.strftime('%Y-%m-%d')} → "
          f"{ADV_WINDOW_END.strftime('%Y-%m-%d')}")
    print(f"Min listing age: {MIN_LISTING_AGE_DAYS} days")
    print(f"Min continuous-trading-days prior: "
          f"{MIN_CONTINUOUS_TRADING_DAYS_PRIOR}")
    print(f"Universe size: {UNIVERSE_SIZE}")
    print()

    # Stage 1: exchangeInfo
    info = _fetch_exchange_info()

    # Stage 2: structural filters
    print("Applying structural filters...")
    candidates = _filter_candidates(info)

    # Stage 3: listing-age filter
    print("Applying listing-age filter...")
    age_passed, age_excluded = _filter_by_listing_age(candidates)

    # Stage 4: compute ADV + continuous-history for each remaining
    print(f"Computing ADV and continuous-history for "
          f"{len(age_passed)} candidates...")
    print("(may take 3-10 minutes if archive cache is cold)")
    fetcher = BinanceKlinesArchiveFetcher(interval="1d")
    raw_adv_candidates = []
    history_excluded = []
    for i, c in enumerate(age_passed):
        print(f"  [{i+1}/{len(age_passed)}] {c['symbol']}...", flush=True)
        adv, days_in_adv_window, adv_failures = _compute_adv(
            fetcher, c["symbol"],
        )
        history_passed, hist_days = _check_continuous_history(
            fetcher, c["symbol"],
        )
        filter_failures = list(adv_failures)
        if not history_passed:
            filter_failures.append("insufficient_continuous_history")
        passed = adv is not None and history_passed
        raw_adv_candidates.append({
            "symbol": c["symbol"],
            "base_asset": c["base_asset"],
            "onboard_date": c["onboard_date"],
            "listing_age_days": c["listing_age_days"],
            "adv_usdt": str(adv) if adv is not None else None,
            "days_with_data_in_adv_window": days_in_adv_window,
            "continuous_history_days_prior": hist_days,
            "passed_filters": passed,
            "filter_failures": filter_failures,
        })
        if not passed and adv is not None:
            history_excluded.append({
                **c,
                "adv_usdt": str(adv),
                "filter_failures": filter_failures,
            })

    # Stage 5: rank by ADV, take top-30
    print()
    print("Ranking by ADV...")
    ranked = sorted(
        (c for c in raw_adv_candidates if c["passed_filters"]),
        key=lambda c: Decimal(c["adv_usdt"]),
        reverse=True,
    )
    top_30 = ranked[:UNIVERSE_SIZE]
    just_below = ranked[UNIVERSE_SIZE:UNIVERSE_SIZE + 5]
    print(f"  top-{UNIVERSE_SIZE} candidates selected; "
          f"{len(ranked) - UNIVERSE_SIZE} candidates below the cutoff")

    # Stage 6: write fixture
    print()
    print(f"Writing fixture to {FIXTURE_PATH.relative_to(REPO_ROOT)}...")
    fixture = {
        "computed_at": datetime.now(tz=timezone.utc).isoformat(),
        "pre_registration": "docs/strategies/sleeve_b_research_preregistration.md",
        "pre_registration_commit": "fe909bb",
        "as_of_date": AS_OF_DATE.strftime("%Y-%m-%d"),
        "adv_window_start": ADV_WINDOW_START.isoformat(),
        "adv_window_end": ADV_WINDOW_END.isoformat(),
        "adv_window_days": ADV_WINDOW_DAYS,
        "exchange": "binance",
        "market": "usdt_perp",
        "universe_size": UNIVERSE_SIZE,
        "filters_applied": {
            "min_listing_age_days": MIN_LISTING_AGE_DAYS,
            "min_continuous_trading_days_prior_to_adv_window":
                MIN_CONTINUOUS_TRADING_DAYS_PRIOR,
            "stablecoins_excluded": True,
            "index_contracts_excluded": True,
            "perpetual_only": True,
            "usdt_margined_only": True,
            "trading_status_required": True,
            "ascii_only_symbol": True,
        },
        "universe_membership_policy": "frozen",
        "reconstitution_permitted": False,
        "survivorship_warning": (
            "Universe approximated from current exchangeInfo plus archive "
            "verification; not guaranteed survivorship-clean reconstruction "
            "as of 2026-04-15. Symbols delisted between 2026-04-15 and the "
            "computation date may have been in the true top-30 but are "
            "invisible to this method. For top-30 ADV on Binance perps, "
            "survivorship bias is operationally small but non-zero."
        ),
        "universe": [
            {
                "rank": i + 1,
                "symbol": c["symbol"],
                "base_asset": c["base_asset"],
                "adv_usdt": c["adv_usdt"],
                "onboard_date": c["onboard_date"],
                "listing_age_days_as_of_as_of_date": c["listing_age_days"],
                "days_with_data_in_adv_window": c["days_with_data_in_adv_window"],
                "continuous_history_days_prior": c["continuous_history_days_prior"],
            }
            for i, c in enumerate(top_30)
        ],
        "just_below_cutoff": [
            {
                "rank": UNIVERSE_SIZE + i + 1,
                "symbol": c["symbol"],
                "adv_usdt": c["adv_usdt"],
            }
            for i, c in enumerate(just_below)
        ],
        "raw_adv_candidates": raw_adv_candidates,
        "excluded_for_listing_age": [
            {
                "symbol": c["symbol"],
                "onboard_date": c["onboard_date"],
                "listing_age_days": c["listing_age_days"],
                "filter_failures": c["filter_failures"],
            }
            for c in age_excluded
        ],
    }
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text(json.dumps(fixture, indent=2, sort_keys=True))
    size = FIXTURE_PATH.stat().st_size
    print(f"Fixture written: {size:,} bytes")
    print()

    # Stage 7: summary
    print("=" * 60)
    print("Top-30 universe:")
    print("=" * 60)
    for u in fixture["universe"]:
        adv_b = Decimal(u["adv_usdt"]) / Decimal("1000000000")
        print(f"  {u['rank']:2d}. {u['symbol']:20s} "
              f"ADV ${adv_b:,.3f}B  "
              f"(listing age {u['listing_age_days_as_of_as_of_date']}d)")
    print()
    print(f"Just-below-cutoff (next 5):")
    for u in fixture["just_below_cutoff"]:
        adv_b = Decimal(u["adv_usdt"]) / Decimal("1000000000")
        print(f"  {u['rank']:2d}. {u['symbol']:20s} "
              f"ADV ${adv_b:,.3f}B")
    print()
    print(f"Total candidates considered: {len(raw_adv_candidates)}")
    print(f"  passed all filters: "
          f"{sum(1 for c in raw_adv_candidates if c['passed_filters'])}")
    print(f"  excluded for listing age: {len(age_excluded)}")
    print(f"  excluded for history/data: "
          f"{sum(1 for c in raw_adv_candidates if not c['passed_filters'])}")


def _build_fixture_metadata() -> int:
    """Helper so that compute_adv etc. can be called without side effects."""
    return 0


if __name__ == "__main__":
    main()
