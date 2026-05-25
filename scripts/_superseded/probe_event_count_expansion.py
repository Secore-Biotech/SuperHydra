"""Event-count expansion probe.

Counts cross-venue basis events across:
  - 2 assets:        BTC, ETH
  - 3 pair types:    Binance perp vs OKX perp
                     Binance spot vs OKX perp
                     Binance perp vs Binance spot (same-venue reference)
  - 4 thresholds:    ±5, ±10, ±15, ±25 bps
  - 3-year window:   2023-04-15 → 2026-04-15

Event definition (LOCKED): a contiguous run of hours where |basis| > threshold.

Decision rule (LOCKED, before any data is loaded):
  Total ±5 bps events across all 6 pairs (2 assets × 3 pair types) over 3 years:
    < 500       → basis-stress direction deprioritized
    500-2000    → ambiguous, more thinking needed (NOT another script)
    > 2000      → substrate exists, characterization layer justified next session

The decision rule is on ±5 bps because that's the most lenient threshold —
if even the loosest definition doesn't produce substrate, tighter thresholds
won't either.

NOT a strategy. NOT a characterization. NOT pre-registration. One measurement
question: is there enough event substrate to study at all?
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal
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
)


WINDOW_START = datetime(2023, 4, 15, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 4, 15, tzinfo=timezone.utc)

THRESHOLDS_BPS = [5.0, 10.0, 15.0, 25.0]

DECISION_THRESHOLD_BPS = 5.0
DECISION_LOW_COUNT = 500   # below this → deprioritize
DECISION_HIGH_COUNT = 2000 # above this → substrate exists


def load_series(
    asset: str,
) -> tuple[dict[datetime, Decimal], dict[datetime, Decimal], dict[datetime, Decimal]]:
    """Load 1h close-price series for one asset across three legs."""
    bp_fetcher = BinanceKlinesArchiveFetcher(interval="1h")
    bs_fetcher = BinanceKlinesArchiveSpotFetcher(interval="1h")

    okx_inst = f"{asset[:3]}-USDT-SWAP"  # "BTC-USDT-SWAP" or "ETH-USDT-SWAP"
    op_fetcher = OkxKlinesFetcher(inst_id=okx_inst, interval="1H")

    bp_klines = bp_fetcher.fetch_window(asset, WINDOW_START, WINDOW_END)
    bs_klines = bs_fetcher.fetch_window(asset, WINDOW_START, WINDOW_END)
    op_klines = op_fetcher.fetch_window(WINDOW_START, WINDOW_END)

    bp = {k.open_time: k.close for k in bp_klines}
    bs = {k.open_time: k.close for k in bs_klines}
    op = {k.open_time: k.close for k in op_klines}
    return bp, bs, op


def basis_bps(num: Decimal, denom: Decimal) -> float:
    return float((num - denom) / denom * Decimal("10000"))


def build_basis(
    series_a: dict[datetime, Decimal],
    series_b: dict[datetime, Decimal],
) -> list[tuple[datetime, float]]:
    common = sorted(set(series_a.keys()) & set(series_b.keys()))
    return [(t, basis_bps(series_a[t], series_b[t])) for t in common]


def count_events(basis_series: list[tuple[datetime, float]], threshold: float) -> tuple[int, int]:
    """Return (event_count, event_hour_count) for contiguous runs where |basis| > threshold."""
    event_count = 0
    event_hour_count = 0
    in_event = False
    for _, b in basis_series:
        if abs(b) > threshold:
            event_hour_count += 1
            if not in_event:
                event_count += 1
                in_event = True
        else:
            in_event = False
    return event_count, event_hour_count


def main() -> int:
    print()
    print("=" * 96)
    print("Event-count expansion probe — basis dislocation frequency")
    print("=" * 96)
    print(f"Window:  {WINDOW_START.date()} → {WINDOW_END.date()}")
    print(f"Assets:  BTC, ETH")
    print(f"Pairs:   Binance perp vs OKX perp,")
    print(f"         Binance spot vs OKX perp,")
    print(f"         Binance perp vs Binance spot (same-venue ref)")
    print(f"Thresholds: ±5, ±10, ±15, ±25 bps")
    print()
    print(f"Pre-locked decision rule on TOTAL ±{DECISION_THRESHOLD_BPS} bps events"
          f" across all 6 pairs:")
    print(f"  < {DECISION_LOW_COUNT}   → basis-stress direction deprioritized")
    print(f"  {DECISION_LOW_COUNT}-{DECISION_HIGH_COUNT}   → ambiguous, more thinking needed")
    print(f"  > {DECISION_HIGH_COUNT}  → substrate exists, characterization layer justified")
    print()

    print("Loading data...")
    btc_bp, btc_bs, btc_op = load_series("BTCUSDT")
    print(f"  BTC: perp={len(btc_bp)}, spot={len(btc_bs)}, okx-perp={len(btc_op)}")
    eth_bp, eth_bs, eth_op = load_series("ETHUSDT")
    print(f"  ETH: perp={len(eth_bp)}, spot={len(eth_bs)}, okx-perp={len(eth_op)}")
    print()

    # Build all 6 pair basis series
    pairs = {
        ("BTC", "binance_perp vs okx_perp"):   build_basis(btc_bp, btc_op),
        ("BTC", "binance_spot vs okx_perp"):   build_basis(btc_bs, btc_op),
        ("BTC", "binance_perp vs binance_spot (ref)"): build_basis(btc_bp, btc_bs),
        ("ETH", "binance_perp vs okx_perp"):   build_basis(eth_bp, eth_op),
        ("ETH", "binance_spot vs okx_perp"):   build_basis(eth_bs, eth_op),
        ("ETH", "binance_perp vs binance_spot (ref)"): build_basis(eth_bp, eth_bs),
    }

    # Print per-pair, per-threshold table
    print("Event counts by pair and threshold:")
    print()
    header = (f"{'asset':<5}  {'pair':<42}  "
              f"{'hours':>6}  "
              + "  ".join(f"{'±'+str(int(t))+'b':>12}" for t in THRESHOLDS_BPS))
    print(header)
    print("-" * 96)

    totals_by_threshold: dict[float, int] = {t: 0 for t in THRESHOLDS_BPS}
    same_venue_totals: dict[float, int] = {t: 0 for t in THRESHOLDS_BPS}
    cross_venue_totals: dict[float, int] = {t: 0 for t in THRESHOLDS_BPS}

    for (asset, pair_label), bseries in pairs.items():
        n_hours = len(bseries)
        cells = []
        for thr in THRESHOLDS_BPS:
            event_count, _ = count_events(bseries, thr)
            cells.append(f"{event_count:>12}")
            totals_by_threshold[thr] += event_count
            if "(ref)" in pair_label:
                same_venue_totals[thr] += event_count
            else:
                cross_venue_totals[thr] += event_count
        cells_str = "  ".join(cells)
        print(f"{asset:<5}  {pair_label:<42}  {n_hours:>6}  {cells_str}")
    print()

    # Subtotal rows
    print("Subtotals:")
    print(f"  {'cross-venue (BTC+ETH × perp/spot vs OKX)':<48}  "
          + "  ".join(f"{cross_venue_totals[t]:>12}" for t in THRESHOLDS_BPS))
    print(f"  {'same-venue (BTC+ETH binance perp vs spot)':<48}  "
          + "  ".join(f"{same_venue_totals[t]:>12}" for t in THRESHOLDS_BPS))
    print(f"  {'TOTAL':<48}  "
          + "  ".join(f"{totals_by_threshold[t]:>12}" for t in THRESHOLDS_BPS))
    print()

    # Decision verdict
    print("=" * 96)
    decision_count = totals_by_threshold[DECISION_THRESHOLD_BPS]
    print(f"Decision rule applied to TOTAL ±{DECISION_THRESHOLD_BPS} bps events: {decision_count}")
    if decision_count < DECISION_LOW_COUNT:
        verdict = "DEPRIORITIZE"
        explanation = (f"Below {DECISION_LOW_COUNT} events across the entire expanded "
                       f"universe (BTC+ETH × cross+same-venue) over 3 years. "
                       f"Basis-stress direction does not have enough event substrate "
                       f"to study at 1h resolution.")
    elif decision_count > DECISION_HIGH_COUNT:
        verdict = "JUSTIFIED"
        explanation = (f"Above {DECISION_HIGH_COUNT} events. Substrate exists for "
                       f"characterization layer next session. Note: this does NOT yet "
                       f"validate any strategy — it validates that the phenomenon is "
                       f"frequent enough to be studied.")
    else:
        verdict = "AMBIGUOUS"
        explanation = (f"Between {DECISION_LOW_COUNT}-{DECISION_HIGH_COUNT} events. "
                       f"Substrate is borderline. More thinking required before "
                       f"committing to characterization layer. Do NOT write another "
                       f"script chasing this; the right move is to step back and "
                       f"reconsider the research direction.")
    print(f"Verdict: {verdict}")
    print()
    # Wrap the explanation at ~80 chars
    import textwrap
    for line in textwrap.wrap(explanation, width=88):
        print(f"  {line}")
    print()
    print("=" * 96)
    print("Reminder: this is descriptive measurement only.")
    print("No strategy claim. No promotion. No selection memo.")
    print("=" * 96)
    return 0


if __name__ == "__main__":
    sys.exit(main())
