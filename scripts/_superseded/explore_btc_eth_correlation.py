"""BTC/ETH rolling correlation probe.

Purpose: validate whether market_state_loader actually reduces friction
for multi-asset exploration. NOT a basis script. NOT a strategy script.
NOT a regime classifier. Pure descriptive measurement.

Uses only the loader API. No direct cache touching, no manual alignment.

Single question: how does the rolling correlation between BTC and ETH
1h returns behave across the OOS window? Are there windows of meaningful
decoupling?

Locked scope:
  1. Load Binance perp BTC + ETH hourly via loader
  2. Compute hourly close-to-close returns
  3. Compute 720-hour (30-day) rolling correlation
  4. Print summary stats + top-10 least/most correlated windows

No persistence analysis. No strategy interpretation. Just the rolling
correlation series and the extremes.
"""
from __future__ import annotations

import math
import statistics
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data.loaders.market_state_loader import load_hourly_market_state


WINDOW_START = datetime(2023, 4, 15, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 4, 15, tzinfo=timezone.utc)
ROLLING_WINDOW_HOURS = 720  # 30 days


def pearson_correlation(xs: list[float], ys: list[float]) -> float:
    """Pearson correlation between two equal-length sequences.

    Returns 0.0 when either series has zero variance (degenerate window).
    Uses statistics.fmean for numerical stability over the sum-of-products form.
    """
    n = len(xs)
    if n == 0 or len(ys) != n:
        return 0.0
    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(ys)
    num = 0.0
    sum_sq_x = 0.0
    sum_sq_y = 0.0
    for x, y in zip(xs, ys):
        dx = x - mean_x
        dy = y - mean_y
        num += dx * dy
        sum_sq_x += dx * dx
        sum_sq_y += dy * dy
    denom = math.sqrt(sum_sq_x * sum_sq_y)
    if denom == 0.0:
        return 0.0
    return num / denom


def _pick_distinct(
    sorted_pairs: list[tuple[datetime, float]],
    min_gap_hours: int,
    n: int,
) -> list[tuple[datetime, float]]:
    """Walk a value-sorted list of (timestamp, value) pairs and return up to
    n entries, each at least min_gap_hours from every already-accepted entry.

    The input is expected to be pre-sorted in the desired order (ascending
    for lowest-value extraction, descending for highest). The function
    preserves that order in its output.
    """
    from datetime import timedelta
    accepted: list[tuple[datetime, float]] = []
    gap = timedelta(hours=min_gap_hours)
    for ts, val in sorted_pairs:
        ok = True
        for acc_ts, _ in accepted:
            if abs(ts - acc_ts) < gap:
                ok = False
                break
        if ok:
            accepted.append((ts, val))
            if len(accepted) >= n:
                break
    return accepted


def main() -> int:
    print()
    print("=" * 92)
    print("BTC/ETH rolling correlation probe (loader-validation task)")
    print("=" * 92)
    print(f"Window:           {WINDOW_START.date()} → {WINDOW_END.date()}")
    print(f"Rolling window:   {ROLLING_WINDOW_HOURS} hours ({ROLLING_WINDOW_HOURS // 24} days)")
    print(f"Venue / type:     Binance perp (single venue, two assets)")
    print()

    # ── Step 1: load via the loader (the actual API exercise) ────────────
    print("Loading hourly market state via market_state_loader ...")
    records = load_hourly_market_state(
        start_utc=WINDOW_START,
        end_utc=WINDOW_END,
        assets=["BTCUSDT", "ETHUSDT"],
        venues=["binance"],
        instrument_types=["perp"],
    )
    print(f"  Returned {len(records)} aligned hourly records.")
    print()

    if len(records) < ROLLING_WINDOW_HOURS + 1:
        print(f"ERROR: too few records ({len(records)}) to compute "
              f"{ROLLING_WINDOW_HOURS}-hour rolling correlation.")
        return 1

    # ── Step 2: hourly close-to-close returns ────────────────────────────
    btc_key = "binance_BTCUSDT_perp_close"
    eth_key = "binance_ETHUSDT_perp_close"

    # Verify the loader returned the keys we expect
    if btc_key not in records[0].prices or eth_key not in records[0].prices:
        print(f"ERROR: expected keys not in record. Available: {list(records[0].prices.keys())}")
        return 1

    btc_returns: list[float] = []
    eth_returns: list[float] = []
    return_timestamps: list[datetime] = []
    for i in range(1, len(records)):
        prev_btc = Decimal(records[i - 1].prices[btc_key])
        cur_btc = Decimal(records[i].prices[btc_key])
        prev_eth = Decimal(records[i - 1].prices[eth_key])
        cur_eth = Decimal(records[i].prices[eth_key])
        # Log returns would be more standard, but close-to-close simple
        # returns are equivalent at 1h resolution for correlation purposes.
        btc_ret = float((cur_btc - prev_btc) / prev_btc)
        eth_ret = float((cur_eth - prev_eth) / prev_eth)
        btc_returns.append(btc_ret)
        eth_returns.append(eth_ret)
        return_timestamps.append(records[i].timestamp)

    print(f"Computed {len(btc_returns)} hourly returns per asset.")
    print()

    # ── Step 3: rolling correlation ──────────────────────────────────────
    print(f"Computing {ROLLING_WINDOW_HOURS}-hour rolling correlation ...")
    rolling_corrs: list[tuple[datetime, float]] = []
    n_returns = len(btc_returns)
    for end_idx in range(ROLLING_WINDOW_HOURS, n_returns + 1):
        start_idx = end_idx - ROLLING_WINDOW_HOURS
        window_btc = btc_returns[start_idx:end_idx]
        window_eth = eth_returns[start_idx:end_idx]
        corr = pearson_correlation(window_btc, window_eth)
        # Use the timestamp at the END of the window — when the window closes
        window_end_ts = return_timestamps[end_idx - 1]
        rolling_corrs.append((window_end_ts, corr))

    print(f"  Produced {len(rolling_corrs)} rolling correlation observations.")
    print()

    # ── Step 4: summary stats and ranked windows ─────────────────────────
    corr_values = [c for _, c in rolling_corrs]
    print("Rolling correlation distribution:")
    print(f"  count:    {len(corr_values)}")
    print(f"  mean:     {statistics.fmean(corr_values):+.4f}")
    print(f"  median:   {statistics.median(corr_values):+.4f}")
    print(f"  stdev:    {statistics.stdev(corr_values):.4f}")
    print(f"  min:      {min(corr_values):+.4f}")
    print(f"  max:      {max(corr_values):+.4f}")
    print()

    # Top 10 lowest-correlation windows with min-gap de-duplication.
    # Rolling correlations at adjacent hours describe the same underlying
    # event shifted by 1 hour. Require >= ROLLING_WINDOW_HOURS gap between
    # ranked entries to guarantee non-overlapping windows.
    sorted_asc = sorted(rolling_corrs, key=lambda x: x[1])
    distinct_low = _pick_distinct(sorted_asc, min_gap_hours=ROLLING_WINDOW_HOURS, n=10)
    print(f"Top 10 LEAST-correlated {ROLLING_WINDOW_HOURS}-hour windows "
          f"(non-overlapping, window ENDING at timestamp):")
    print(f"  {'rank':<4}  {'window-end (UTC)':<25}  {'correlation':>12}")
    for i, (ts, c) in enumerate(distinct_low, 1):
        print(f"  {i:<4}  {ts!s:<25}  {c:>+12.4f}")
    print()

    # Top 10 highest-correlation windows with min-gap de-duplication.
    sorted_desc = sorted(rolling_corrs, key=lambda x: x[1], reverse=True)
    distinct_high = _pick_distinct(sorted_desc, min_gap_hours=ROLLING_WINDOW_HOURS, n=10)
    print(f"Top 10 MOST-correlated {ROLLING_WINDOW_HOURS}-hour windows "
          f"(non-overlapping, window ENDING at timestamp):")
    print(f"  {'rank':<4}  {'window-end (UTC)':<25}  {'correlation':>12}")
    for i, (ts, c) in enumerate(distinct_high, 1):
        print(f"  {i:<4}  {ts!s:<25}  {c:>+12.4f}")
    print()

    print("=" * 92)
    print("Reminder: descriptive measurement only.")
    print("No strategy claim, no regime label, no thesis interpretation.")
    print("=" * 92)
    return 0


if __name__ == "__main__":
    sys.exit(main())
