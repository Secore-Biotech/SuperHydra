#!/usr/bin/env python3
"""
A1 Phase-1 funding-regime-history recon  (levels only — NO economics)

Gating artifact for any future A1 v2 discussion. Answers ONLY:

  Q1  latest-OOS-only collapse?
  Q2  secular decline?
  Q3  episodic leverage-cycle behaviour?

Explicitly NOT answered here (belong to a future A1 v2 pre-build gate):
  Q4 gross carry economics   Q5 basis-drift survivability   Q6 executable funding capture

Method: for each symbol, compute the fraction of funding observations whose
absolute funding rate is >= each of three thresholds (0.0125%, 0.0150%,
0.0200% per 8h), grouped by calendar month and by calendar quarter.

Interpretation (decided BEFORE running, per the locked discriminator):
  all three thresholds collapse together in recent windows -> distribution-wide compression (leans secular)
  0.0200% collapses but 0.0125%/0.0150% survive            -> right-tail thinning
  all three remain present but come and go                 -> leverage-cycle / episodic (regime-contingent)

No spec opens until this reports. This script writes nothing; it prints.

Usage:
  python scripts/a1_phase1_funding_regime_recon.py fixtures/real_vol_event_fixture_v3.json
  python scripts/a1_phase1_funding_regime_recon.py fixtures/real_vol_event_fixture_v3.json --inspect
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone

# Thresholds in PERCENT per 8h (Binance funding-rate convention).
# 0.0100% is the default-rate mass; we sit above it, at the three discriminator levels.
THRESHOLDS_PCT = [0.0125, 0.0150, 0.0200]

# A1 v1 train/OOS split landed here (calendar-time 80/20). Used only to label
# whether a window is TRAIN or OOS in the printout — NOT to recompute anything.
SPLIT_TS = datetime(2025, 10, 9, 22, 24, tzinfo=timezone.utc)


def _parse_ts(raw):
    """Accept epoch ms, epoch s, or ISO-8601 (with or without sub-second jitter)."""
    if isinstance(raw, (int, float)):
        # Binance funding_time is epoch ms; fall back to s if it looks like seconds.
        val = float(raw)
        if val > 1e12:  # ms
            return datetime.fromtimestamp(val / 1000.0, tz=timezone.utc)
        return datetime.fromtimestamp(val, tz=timezone.utc)
    s = str(raw).strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_rate_to_pct(raw):
    """
    Return funding rate as PERCENT per 8h.
    Binance funding_rate in raw form is a fraction (e.g. 0.0001 == 0.0100%).
    If the fixture already stores percent or bps, --inspect will reveal it and
    this assumption must be revisited BEFORE trusting output.
    """
    return float(raw) * 100.0


def inspect(fixture: dict) -> None:
    """Fail-loud shape check. Run this first on any unfamiliar fixture."""
    print("=== FIXTURE INSPECTION (verify before trusting recon output) ===")
    print(f"top-level keys: {list(fixture.keys())}")
    recs = _extract_funding(fixture)
    print(f"\nfunding records (flat list): {len(recs)}")
    sample = recs[0]
    print(f"  sample record keys: {list(sample.keys())}")
    print(f"  sample record: {json.dumps(sample, default=str)[:300]}")
    sym_key, ft_key, fr_key = _funding_keys(sample)
    ts = _parse_ts(sample[ft_key])
    rate = _parse_rate_to_pct(sample[fr_key])
    print(f"  symbol field -> {sym_key!r}  (value {sample[sym_key]!r})")
    print(f"  parsed first ts -> {ts.isoformat()}")
    print(f"  parsed first rate -> {rate:.6f}% per 8h  (raw={sample[fr_key]!r})")
    syms = sorted({str(r[sym_key]) for r in recs})
    print(f"  instruments present: {syms}")
    for s in syms:
        print(f"    {s}: {sum(1 for r in recs if str(r[sym_key]) == s)} records")
    print("\nUnit check: a typical record should parse to ~0.0100% (the default-rate mass).")
    print("If rate magnitudes look ~100x off, fix _parse_rate_to_pct before running the recon.")


def _group_by_symbol(fixture: dict):
    """Yield (symbol, [records]) from a flat funding list keyed by an internal symbol field."""
    recs = _extract_funding(fixture)
    sym_key, _, _ = _funding_keys(recs[0])
    grouped = defaultdict(list)
    for r in recs:
        grouped[str(r[sym_key])].append(r)
    for sym in sorted(grouped):
        yield sym, grouped[sym]


def _extract_funding(fixture: dict) -> list:
    f = fixture.get("funding")
    if isinstance(f, list) and f:
        return f
    raise SystemExit("Expected a non-empty flat 'funding' list at top level. Run --inspect.")


def _funding_keys(record: dict):
    sym = next((k for k in ("instrument", "symbol", "pair") if k in record), None)
    ft = next((k for k in ("funding_time", "fundingTime", "time", "timestamp") if k in record), None)
    fr = next((k for k in ("funding_rate", "fundingRate", "rate") if k in record), None)
    if sym is None or ft is None or fr is None:
        raise SystemExit(f"Unrecognised funding record keys: {list(record.keys())}. Run --inspect.")
    return sym, ft, fr


def recon(fixture: dict) -> None:
    for sym, recs in _group_by_symbol(fixture):
        _, ft_key, fr_key = _funding_keys(recs[0])

        # group -> {period_key: [counts_per_threshold, total]}
        by_month = defaultdict(lambda: [0] * len(THRESHOLDS_PCT) + [0])
        by_quarter = defaultdict(lambda: [0] * len(THRESHOLDS_PCT) + [0])
        oos_total = 0
        oos_hits = [0] * len(THRESHOLDS_PCT)

        for r in recs:
            ts = _parse_ts(r[ft_key])
            rate = abs(_parse_rate_to_pct(r[fr_key]))
            mk = f"{ts.year}-{ts.month:02d}"
            qk = f"{ts.year}-Q{(ts.month - 1)//3 + 1}"
            for i, thr in enumerate(THRESHOLDS_PCT):
                hit = 1 if rate >= thr else 0
                by_month[mk][i] += hit
                by_quarter[qk][i] += hit
                if ts >= SPLIT_TS:
                    oos_hits[i] += hit
            by_month[mk][-1] += 1
            by_quarter[qk][-1] += 1
            if ts >= SPLIT_TS:
                oos_total += 1

        print(f"\n================ {sym} ================")
        print(f"total funding observations: {len(recs)}")
        _print_table("QUARTERLY", by_quarter)
        _print_table("MONTHLY", by_month)
        print(f"\n  OOS window (>= {SPLIT_TS.date()}): {oos_total} obs")
        for i, thr in enumerate(THRESHOLDS_PCT):
            frac = (oos_hits[i] / oos_total * 100) if oos_total else 0.0
            print(f"    >= {thr:.4f}% : {oos_hits[i]:>4} obs  ({frac:5.2f}% of OOS)")


def _print_table(label: str, grouped: dict) -> None:
    print(f"\n  --- {label} fraction (%) at/above threshold ---")
    hdr = "  period      " + "".join(f"{t:>10.4f}%" for t in THRESHOLDS_PCT) + "   n    seg"
    print(hdr)
    for key in sorted(grouped):
        counts = grouped[key]
        n = counts[-1]
        # crude TRAIN/OOS tag for readability (quarter/month vs split)
        seg = ""
        cells = ""
        for i in range(len(THRESHOLDS_PCT)):
            frac = (counts[i] / n * 100) if n else 0.0
            cells += f"{frac:>10.2f} "
        print(f"  {key:<10} {cells}  {n:>4}  {seg}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fixture", help="path to funding fixture JSON (e.g. fixtures/real_vol_event_fixture_v3.json)")
    ap.add_argument("--inspect", action="store_true", help="print fixture shape and exit (run this first)")
    args = ap.parse_args()

    with open(args.fixture) as f:
        fixture = json.load(f)

    if args.inspect:
        inspect(fixture)
        return

    print("A1 Phase-1 funding-regime-history recon — LEVELS ONLY, no economics.")
    print(f"thresholds (% per 8h): {THRESHOLDS_PCT}")
    print(f"A1 v1 train/OOS split label: {SPLIT_TS.isoformat()}\n")
    recon(fixture)
    print("\nInterpretation:")
    print("  all three collapse together in recent windows -> distribution-wide compression (secular)")
    print("  0.0200% collapses, 0.0125/0.0150 survive       -> right-tail thinning")
    print("  all three present but come and go              -> leverage-cycle / episodic (regime-contingent)")
    print("\nThis recon answers Q1-Q3 only. Q4-Q6 (carry/basis/execution) are a future A1 v2 pre-build gate.")


if __name__ == "__main__":
    main()
