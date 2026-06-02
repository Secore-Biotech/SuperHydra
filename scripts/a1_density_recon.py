"""A1 funding-rate density reconnaissance.

Two modes, sharing the same parsing and 80/20 split logic.

MODE 1 — train-only density table (default).

Pure descriptive measurement to inform θ selection for the A1 probe.
Reports per-symbol density across a fixed grid of candidate θ values
on the *train* window only. OOS data is NOT used for θ selection —
same discipline as Section A's percentile-event detector.

Outputs per symbol:
  threshold (%/8h)  | train_events | event_density | mean_above | median_above

MODE 2 — single-threshold OOS sample-sufficiency check (--threshold).

After θ has been locked in the spec, this mode runs the OOS-window
sample-sufficiency check required by spec §9 step 2. Reports train and
OOS event counts and OOS span at the locked θ, per symbol and combined,
against the §5.3 floors (train >= 100 pooled, OOS >= 30 pooled, OOS
span >= 182 days).

Density counts here are an UPPER BOUND on what the probe will see
post-data-hygiene (entry/exit bar presence, funding-window completeness
gap check). The probe's real event count will be <= the density count.
If the density is borderline, the real probe is at meaningful risk of
landing in DATA_LIMITED on hygiene attrition. The script prints this
caveat alongside the numbers.

Usage:
    # Mode 1: density table for θ selection
    python3 scripts/a1_density_recon.py --fixture fixtures/<fixture>.json

    # Mode 2: OOS check at locked θ (raw funding_rate, e.g. 0.0002 for 0.0200%/8h)
    python3 scripts/a1_density_recon.py --fixture <fixture> --threshold 0.0002
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


def _check_oos_sufficiency(funding_records: list[dict], theta_dec: Decimal) -> dict:
    """OOS sample-sufficiency check at a single locked θ.

    Counts funding observations f >= θ in the OOS window (last 20% calendar
    split). Returns counts and the OOS calendar span. Density only — does
    not check entry/exit bar presence or funding-window completeness; those
    require the actual probe pipeline.
    """
    if not funding_records:
        return {"error": "no funding records"}

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

    train = [(t, f) for t, f in parsed if t <= train_end]
    oos = [(t, f) for t, f in parsed if t > train_end]

    train_above = sum(1 for _, f in train if f >= theta_dec)
    oos_above = sum(1 for _, f in oos if f >= theta_dec)

    if oos:
        oos_first = oos[0][0]
        oos_last = oos[-1][0]
        oos_span_days = (oos_last - oos_first).total_seconds() / 86400.0
    else:
        oos_first = oos_last = None
        oos_span_days = 0.0

    return {
        "train_total_obs": len(train),
        "oos_total_obs": len(oos),
        "train_events_above": train_above,
        "oos_events_above": oos_above,
        "oos_first": oos_first.isoformat() if oos_first else None,
        "oos_last": oos_last.isoformat() if oos_last else None,
        "oos_span_days": oos_span_days,
        "train_end_split": train_end.isoformat(),
    }


# Spec §5.3 floors — pooled BTC+ETH.
_GATE_TRAIN_MIN = 100
_GATE_OOS_MIN = 30
_GATE_OOS_SPAN_DAYS = 182


def _print_oos_check(by_symbol_results: dict, theta_dec: Decimal) -> None:
    theta_pct = theta_dec * Decimal("100")
    print(f"\n=== A1 OOS sample-sufficiency check ===")
    print(f"  threshold θ = {theta_pct:.4f}% per 8h  (raw {theta_dec})")
    print(f"  spec §5.3 floors (pooled BTC+ETH): "
          f"train >= {_GATE_TRAIN_MIN}, OOS >= {_GATE_OOS_MIN}, "
          f"OOS span >= {_GATE_OOS_SPAN_DAYS}d")
    print()

    # Per-symbol
    print(f"  {'symbol':>10}  {'train_obs':>10}  {'train_evts':>11}  "
          f"{'oos_obs':>8}  {'oos_evts':>9}  {'oos_span_d':>11}")
    print(f"  {'-'*10}  {'-'*10}  {'-'*11}  {'-'*8}  {'-'*9}  {'-'*11}")

    pooled_train = 0
    pooled_oos = 0
    span_days_values = []
    train_end_values = set()
    for sym in sorted(by_symbol_results):
        r = by_symbol_results[sym]
        if "error" in r:
            print(f"  {sym:>10}  ERROR: {r['error']}")
            continue
        print(f"  {sym:>10}  {r['train_total_obs']:>10}  "
              f"{r['train_events_above']:>11}  {r['oos_total_obs']:>8}  "
              f"{r['oos_events_above']:>9}  {r['oos_span_days']:>11.1f}")
        pooled_train += r["train_events_above"]
        pooled_oos += r["oos_events_above"]
        span_days_values.append(r["oos_span_days"])
        train_end_values.add(r["train_end_split"])

    # Pooled
    print(f"  {'-'*10}  {'-'*10}  {'-'*11}  {'-'*8}  {'-'*9}  {'-'*11}")
    pooled_span = max(span_days_values) if span_days_values else 0.0
    print(f"  {'POOLED':>10}  {'':>10}  {pooled_train:>11}  "
          f"{'':>8}  {pooled_oos:>9}  {pooled_span:>11.1f}")
    print()

    # Train-end calendar split (same across symbols if funding spans match;
    # we surface it to make the 80/20 boundary explicit).
    if len(train_end_values) == 1:
        print(f"  train/OOS split (calendar): "
              f"{next(iter(train_end_values))}")
    else:
        print(f"  WARNING: train-end split differs across symbols: "
              f"{sorted(train_end_values)}")
        print(f"  This indicates differing funding spans per symbol — "
              f"investigate before trusting pooled counts.")

    # Verdict against §5.3
    print()
    print(f"  verdict against §5.3:")
    train_ok = pooled_train >= _GATE_TRAIN_MIN
    oos_ok = pooled_oos >= _GATE_OOS_MIN
    span_ok = pooled_span >= _GATE_OOS_SPAN_DAYS
    print(f"    pooled train events >= {_GATE_TRAIN_MIN}: "
          f"{pooled_train} -> {'PASS' if train_ok else 'FAIL'}")
    print(f"    pooled OOS events   >= {_GATE_OOS_MIN}:  "
          f"{pooled_oos} -> {'PASS' if oos_ok else 'FAIL'}")
    print(f"    OOS span (days)     >= {_GATE_OOS_SPAN_DAYS}: "
          f"{pooled_span:.1f} -> {'PASS' if span_ok else 'FAIL'}")
    print()
    if train_ok and oos_ok and span_ok:
        print(f"  >>> §5.3 floors cleared (pre-hygiene). Probe build can proceed.")
    else:
        print(f"  >>> §5.3 floors NOT all cleared at θ = {theta_pct:.4f}%.")
        print(f"      Per spec §8, θ is immutable in v1; per §7.4 the affected")
        print(f"      horizons would return DATA_LIMITED on actual run.")
        print(f"      An alternate θ requires a new v2 spec.")
    print()

    # Mandatory caveat: density is upper bound on real events.
    print(f"  CAVEAT: counts above are an UPPER BOUND on probe event counts.")
    print(f"  The real probe applies entry/exit bar presence checks and the")
    print(f"  funding-window completeness gap check, both of which can reduce")
    print(f"  event counts further. Margins above the floors should be treated")
    print(f"  as room for hygiene attrition, not as comfort.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--fixture", required=True, type=Path)
    ap.add_argument(
        "--threshold",
        type=Decimal,
        default=None,
        help="If supplied, run mode 2 (OOS sample-sufficiency check at this "
             "raw funding_rate threshold). Otherwise mode 1 (train density table).",
    )
    args = ap.parse_args()

    with args.fixture.open() as f:
        fixture = json.load(f)

    by_symbol: dict[str, list[dict]] = {}
    for rec in fixture.get("funding", []):
        sym = rec["instrument"]
        by_symbol.setdefault(sym, []).append(rec)

    if not by_symbol:
        print("ERROR: no funding records in fixture.")
        return

    if args.threshold is not None:
        # Mode 2: OOS check
        results = {sym: _check_oos_sufficiency(by_symbol[sym], args.threshold)
                   for sym in sorted(by_symbol)}
        _print_oos_check(results, args.threshold)
        return

    # Mode 1: density table (original behavior)
    for sym in sorted(by_symbol):
        result = _measure_one_symbol(by_symbol[sym])
        _print_table(sym, result)

    print()
    print("Note: this is descriptive reconnaissance only. No PnL is computed,")
    print("no strategy logic is applied. θ-selection happens against this table")
    print("and is then validated against the (yet-to-be-drafted) A1 gates.")


if __name__ == "__main__":
    main()
