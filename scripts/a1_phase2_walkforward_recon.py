#!/usr/bin/env python3
"""
A1 Phase-2 walk-forward fold-count recon  (split-placement test — NO economics)

Question this gates:
  Was A1 v1 DATA_LIMITED because theta was wrong, or because the single
  80/20 calendar split landed OOS in a low-burst regime?

It keeps A1 v1's EXACT event definition and changes ONLY the split:
  - theta = 0.0200% per 8h   (FIXED — this recon must NOT be used to change theta)
  - BTCUSDT + ETHUSDT
  - positive funding only (funding_rate > 0), magnitude >= theta
  - no spot data, no holding-window capture, no basis, no economics

Single 80/20 split  ->  rolling walk-forward folds:
  train window = 12 months   (intentionally short — see below)
  OOS   window = 6 months
  step         = 3 months

THIS IS NOT AN A1 v1 GATE RERUN. It is a SPLIT-PLACEMENT DIAGNOSTIC.
The 12m train window is deliberately shorter than v1's implied train depth so that
the rolling OOS window lands ON the burst regimes in early folds and on the dead
zone in late folds. A 24m train cannot do this on ~38 months of data (it forces
every burst into train), so it is mechanically valid but diagnostically weak and
was rejected as a fold design. Train-floor failures in quiet folds are expected
under a 12m train and are part of the signal, not a defect.

Per-fold sample-sufficiency uses A1 v1's §5 floors VERBATIM, all three required:
  train events >= 100   AND   OOS events >= 30   AND   OOS span >= 182 days
(NB: a 6-month OOS is ~183 days, sitting right on the span floor by design, so
folds pass/fail primarily on the OOS event COUNT — which is the quantity under test.)

Decision interpretation (locked before running):
  early folds pass, late folds fail   -> episodic / regime-cyclical; v1 split landed in a dead zone
  most folds pass                      -> v1 failure mostly a split-placement artifact (next: walk-forward spec)
  all / nearly all folds fail          -> fixed-theta likely structurally sparse; skip A1 v2 unless new premise
  train fails but OOS passes in burst windows -> usable event bursts exist, but 12m train-depth calibration is unstable

Guard: this recon tests SPLIT PLACEMENT ONLY. theta is fixed at 0.0200%.

Usage:
  python scripts/a1_phase2_walkforward_recon.py fixtures/real_vol_event_fixture_v3.json
  python scripts/a1_phase2_walkforward_recon.py fixtures/real_vol_event_fixture_v3.json --csv folds.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta, timezone

# --- LOCKED A1 v1 parameters (do not edit to chase a result) ---
THETA_PCT = 0.0200            # % per 8h, absolute, FIXED
SYMBOLS = ("BTCUSDT", "ETHUSDT")
POSITIVE_FUNDING_ONLY = True  # v1: positive-funding capture

# §5 floors, verbatim from A1 v1 spec / Section A verdict table
FLOOR_TRAIN_EVENTS = 100
FLOOR_OOS_EVENTS = 30
FLOOR_OOS_SPAN_DAYS = 182

# --- Fold design (split-placement diagnostic — NOT a v1 gate rerun) ---
# 12m train is intentionally SHORTER than v1's implied train depth: the purpose
# is to roll the OOS window ACROSS the burst regimes, which a 24m train cannot do
# on this data span. Train-floor failures in quiet folds are therefore expected
# and informative, not a defect — see interpretation note on train-depth.
TRAIN_MONTHS = 12
OOS_MONTHS = 6
STEP_MONTHS = 3

# Approximate month as 30.4375 days for window arithmetic; fold boundaries are
# then snapped to actual data, so this only sets nominal window widths.
DAYS_PER_MONTH = 30.4375


def _parse_ts(raw):
    s = str(raw).strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _rate_pct(raw):
    """Funding rate as PERCENT per 8h. Raw is a fraction string (0.0001 == 0.0100%)."""
    return float(raw) * 100.0


def load_funding(path):
    with open(path) as f:
        fixture = json.load(f)
    recs = fixture.get("funding")
    if not isinstance(recs, list) or not recs:
        raise SystemExit("Expected non-empty top-level 'funding' list. Check fixture shape.")
    # normalize: {symbol: [(ts, signed_rate_pct), ...]} sorted by ts
    out = {s: [] for s in SYMBOLS}
    for r in recs:
        sym = r.get("instrument") or r.get("symbol")
        if sym not in out:
            continue
        ts = _parse_ts(r["funding_time"])
        rate = _rate_pct(r["funding_rate"])
        out[sym].append((ts, rate))
    for s in out:
        out[s].sort(key=lambda x: x[0])
    return out


def is_event(signed_rate_pct):
    """v1 event: positive funding whose magnitude clears theta."""
    if POSITIVE_FUNDING_ONLY and signed_rate_pct <= 0:
        return False
    return abs(signed_rate_pct) >= THETA_PCT


def count_events(series, lo, hi):
    """Count events with lo <= ts < hi. series is sorted list of (ts, rate)."""
    return sum(1 for ts, rate in series if lo <= ts < hi and is_event(rate))


def build_folds(global_start, global_end):
    """Rolling walk-forward folds: 24m train, 6m OOS, 3m step."""
    folds = []
    train_w = timedelta(days=TRAIN_MONTHS * DAYS_PER_MONTH)
    oos_w = timedelta(days=OOS_MONTHS * DAYS_PER_MONTH)
    step = timedelta(days=STEP_MONTHS * DAYS_PER_MONTH)

    train_start = global_start
    while True:
        train_end = train_start + train_w
        oos_start = train_end
        oos_end = oos_start + oos_w
        if oos_end > global_end + timedelta(days=1):
            break
        folds.append((train_start, train_end, oos_start, oos_end))
        train_start = train_start + step
    return folds


def run(path, csv_path=None):
    funding = load_funding(path)

    all_ts = [ts for s in SYMBOLS for ts, _ in funding[s]]
    if not all_ts:
        raise SystemExit("No funding observations for the target symbols.")
    global_start, global_end = min(all_ts), max(all_ts)

    print("A1 Phase-2 walk-forward fold-count recon — SPLIT-PLACEMENT DIAGNOSTIC, NO economics.")
    print("(not an A1 v1 gate rerun; 12m train is intentionally short to roll OOS across bursts)")
    print(f"theta = {THETA_PCT:.4f}% per 8h (FIXED)  |  positive-funding-only = {POSITIVE_FUNDING_ONLY}")
    print(f"folds: train {TRAIN_MONTHS}m / OOS {OOS_MONTHS}m / step {STEP_MONTHS}m")
    print(f"floors: train >= {FLOOR_TRAIN_EVENTS}, OOS >= {FLOOR_OOS_EVENTS}, OOS span >= {FLOOR_OOS_SPAN_DAYS}d (all required)")
    print(f"data span: {global_start.date()} -> {global_end.date()}")
    print(f"per symbol: BTCUSDT {len(funding['BTCUSDT'])} obs, ETHUSDT {len(funding['ETHUSDT'])} obs\n")

    folds = build_folds(global_start, global_end)
    if not folds:
        raise SystemExit("No complete folds fit in the data span. Check window sizes vs data length.")

    rows = []
    hdr = (f"{'#':>2}  {'train_start':<11}{'train_end':<11}{'oos_start':<11}{'oos_end':<11}"
           f"{'trN':>5}{'oosN':>6}{'trBTC':>7}{'trETH':>7}{'oBTC':>6}{'oETH':>6}{'span':>6}  suff")
    print(hdr)
    print("-" * len(hdr))

    n_pass = 0
    for i, (ts0, ts1, ts2, ts3) in enumerate(folds, 1):
        tr_btc = count_events(funding["BTCUSDT"], ts0, ts1)
        tr_eth = count_events(funding["ETHUSDT"], ts0, ts1)
        oo_btc = count_events(funding["BTCUSDT"], ts2, ts3)
        oo_eth = count_events(funding["ETHUSDT"], ts2, ts3)
        tr_comb = tr_btc + tr_eth
        oo_comb = oo_btc + oo_eth
        span_days = (ts3 - ts2).days

        suff = (tr_comb >= FLOOR_TRAIN_EVENTS
                and oo_comb >= FLOOR_OOS_EVENTS
                and span_days >= FLOOR_OOS_SPAN_DAYS)
        if suff:
            n_pass += 1

        print(f"{i:>2}  {ts0.date()!s:<11}{ts1.date()!s:<11}{ts2.date()!s:<11}{ts3.date()!s:<11}"
              f"{tr_comb:>5}{oo_comb:>6}{tr_btc:>7}{tr_eth:>7}{oo_btc:>6}{oo_eth:>6}{span_days:>6}"
              f"  {'PASS' if suff else 'fail'}")

        rows.append(dict(
            fold=i,
            fold_train_start=ts0.date().isoformat(),
            fold_train_end=ts1.date().isoformat(),
            fold_oos_start=ts2.date().isoformat(),
            fold_oos_end=ts3.date().isoformat(),
            train_events_combined=tr_comb,
            oos_events_combined=oo_comb,
            train_events_BTC=tr_btc,
            train_events_ETH=tr_eth,
            oos_events_BTC=oo_btc,
            oos_events_ETH=oo_eth,
            oos_span_days=span_days,
            sample_sufficient=suff,
        ))

    n = len(folds)
    print(f"\nfolds: {n}  |  sample-sufficient: {n_pass}  |  starved: {n - n_pass}")

    # Locate where v1's single split (~2025-10-09) falls among OOS windows, for context.
    v1_split = datetime(2025, 10, 9, 22, 24, tzinfo=timezone.utc)
    covering = [r for r in rows
                if r["fold_oos_start"] <= v1_split.date().isoformat() <= r["fold_oos_end"]]
    if covering:
        ids = ", ".join(str(r["fold"]) for r in covering)
        print(f"v1's single-split OOS start (~{v1_split.date()}) falls in fold(s): {ids}")

    print("\nInterpretation (locked):")
    print("  early folds pass, late folds fail            -> episodic / regime-cyclical; v1 split landed in a dead zone")
    print("  most folds pass                              -> v1 failure mostly split-placement artifact (next: walk-forward spec)")
    print("  all / nearly all folds fail                  -> fixed-theta likely structurally sparse; skip v2 unless new premise")
    print("  train fails but OOS passes in burst windows  -> usable bursts exist, 12m train-depth calibration unstable")
    print("\nGuard: theta is fixed at 0.0200%. This recon tests SPLIT PLACEMENT ONLY.")
    print("It says nothing about carry/basis/execution (Q4-Q6) — those remain a future v2 pre-build gate.")

    if csv_path:
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"\nwrote {len(rows)} fold rows -> {csv_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fixture")
    ap.add_argument("--csv", default=None, help="optional path to write per-fold rows as CSV")
    args = ap.parse_args()
    run(args.fixture, args.csv)


if __name__ == "__main__":
    main()
