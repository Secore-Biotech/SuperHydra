"""A1 funding-rate density reconnaissance — train-only window.

Pure descriptive measurement to inform θ selection for the A1 probe.
No PnL computation, no strategy logic, no decisions. Just the density
table that lets θ be picked off data rather than intuition.

Outputs per symbol:
  threshold (%/8h)  | train_events | event_density | mean_above | median_above

- train_events: count of funding observations f(T-8h) >= θ in the train window
- event_density: train_events / total_train_funding_observations (fraction)
- mean_above:   mean of f(T-8h) for observations where f >= θ, in %/8h
- median_above: median of f(T-8h) for observations where f >= θ, in %/8h

Train window is the first 80% of the calendar-time span of the fixture,
matching the operator-locked 80/20 split. OOS data is NOT used for θ
selection — same discipline as Section A's percentile-event detector.

Usage:
    python3 scripts/a1_density_recon.py --fixture fixtures/<fixture>.json
"""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime
from decimal import Decimal
from pathlib import Path

# Thresholds in %/8h units. Same scale as Binance fundingRate field
# (fundingRate is a decimal fraction; 0.0001 = 0.01% per funding interval).
# We display in % for human readability; the comparison is on the raw
# decimal funding_rate value.
THRESHOLDS_PCT = [
    Decimal("0.0025"),
    Decimal("0.0050"),
    Decimal("0.0075"),
    Decimal("0.0100"),
    Decimal("0.0125"),
    Decimal("0.0150"),
    Decimal("0.0200"),
    Decimal("0.0250"),
    Decimal("0.0300"),
]

# Convert %/8h to raw decimal funding_rate (Binance's stored format).
# 0.01% = 0.0001 as a decimal.
THRESHOLDS_DEC = [t / Decimal("100") for t in THRESHOLDS_PCT]


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _train_window_end(funding_times: list[datetime]) -> datetime:
    """Train window is first 80% of calendar-time span between first and
    last funding observation, matching A/B probe split convention."""
    if not funding_times:
        raise ValueError("empty funding times")
    start = funding_times[0]
    end = funding_times[-1]
    span = end - start
    train_end = start + (span * 0.8)
    return train_end


def _measure_one_symbol(funding_records: list[dict]) -> dict:
    """Run density measurement on one symbol's funding records.
    funding_records: list of {funding_time: ISO str, funding_rate: str|Decimal}
    """
    if not funding_records:
        return {"error": "no funding records"}

    # Parse and sort
    parsed = sorted(
        [
            (
                _parse_dt(r["funding_time"]),
                Decimal(str(r["funding_rate"])),
            )
            for r in funding_records
        ],
        key=lambda x: x[0],
    )
    times = [t for t, _ in parsed]
    train_end = _train_window_end(times)

    # Filter to train window
    train = [(t, f) for t, f in parsed if t <= train_end]
    train_rates = [f for _, f in train]
    n_train = len(train_rates)

    rows = []
    for theta_pct, theta_dec in zip(THRESHOLDS_PCT, THRESHOLDS_DEC):
        above = [f for f in train_rates if f >= theta_dec]
        n_above = len(above)
        density = (Decimal(n_above) / Decimal(n_train)) if n_train > 0 else Decimal("0")
        if above:
            # Convert decimal rate back to % for display
            above_pct = [float(f) * 100 for f in above]
            mean_above = statistics.mean(above_pct)
            median_above = statistics.median(above_pct)
        else:
            mean_above = None
            median_above = None
        rows.append(
            {
                "threshold_pct": f"{theta_pct}",
                "train_events": n_above,
                "event_density": f"{density:.4f}",
                "mean_above_pct": f"{mean_above:.5f}" if mean_above is not None else "-",
                "median_above_pct": f"{median_above:.5f}" if median_above is not None else "-",
            }
        )

    return {
        "train_first": times[0].isoformat(),
        "train_last_used": train_end.isoformat(),
        "fixture_last": times[-1].isoformat(),
        "train_obs": n_train,
        "total_obs": len(parsed),
        "rows": rows,
    }


def _print_table(symbol: str, result: dict) -> None:
    if "error" in result:
        print(f"[{symbol}] {result['error']}")
        return
    print(f"\n=== {symbol} ===")
    print(
        f"  train window: {result['train_first']}  ->  {result['train_last_used']}"
    )
    print(
        f"  train observations: {result['train_obs']}  "
        f"(of {result['total_obs']} total in fixture; 80/20 calendar split)"
    )
    print()
    # column widths
    print(
        f"  {'threshold (%/8h)':>16}  {'train_events':>12}  "
        f"{'density':>9}  {'mean_above (%)':>16}  {'median_above (%)':>18}"
    )
    print(
        f"  {'-'*16}  {'-'*12}  {'-'*9}  {'-'*16}  {'-'*18}"
    )
    for row in result["rows"]:
        print(
            f"  {row['threshold_pct']:>16}  {row['train_events']:>12}  "
            f"{row['event_density']:>9}  {row['mean_above_pct']:>16}  "
            f"{row['median_above_pct']:>18}"
        )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--fixture", required=True, type=Path)
    args = ap.parse_args()

    with args.fixture.open() as f:
        fixture = json.load(f)

    # Group funding by instrument
    by_symbol: dict[str, list[dict]] = {}
    for rec in fixture.get("funding", []):
        sym = rec["instrument"]
        by_symbol.setdefault(sym, []).append(rec)

    if not by_symbol:
        print("ERROR: no funding records in fixture.")
        return

    for sym in sorted(by_symbol):
        result = _measure_one_symbol(by_symbol[sym])
        _print_table(sym, result)

    print()
    print("Note: this is descriptive reconnaissance only. No PnL is computed,")
    print("no strategy logic is applied. θ-selection happens against this table")
    print("and is then validated against the (yet-to-be-drafted) A1 gates.")


if __name__ == "__main__":
    main()
