"""Sleeve B candidate #4 — Stage A evaluation.

Computes Stage A sub-gate verdicts per the pre-registration at commit 59c1156:

  A1 — Static coverage: min C(T) across rebalance dates
       Threshold: <15 FAIL / 15-17 PASS_WARNING / >=18 PASS_CLEAN

  A2 — Temporal stability (corrected, per 39970f1 §2.2):
       D(T) = deterministic expansion (fixture-only, listing-age rule)
       C(T) = actual eligibility (OHLCV-verified at T and T-45d)
       E(T) = C(T) - D(T)
       Threshold: spread of E >6 FAIL / <=6 PASS

  A3 — Source agreement: NOT_APPLICABLE (single-venue Binance)
  A4 — PIT discipline: PASS_CLEAN (Binance kline immutable historical)
  A5 — Taxonomy sensitivity: PASS (no alternatives)

Outputs:
  - docs/strategies/sleeve_b_candidate_4_stage_a_verdict.md
  - prints summary to stdout

No backtest, no signal computation. Pure data availability accounting.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Make the repo root importable when invoked from anywhere.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from data.ingestion.vendors.binance.klines_archive_fetcher import (
    BinanceKlinesArchiveFetcher,
)
from strategies.sleeve_b.xs_momentum.backtest import generate_rebalance_dates
from strategies.sleeve_b.xs_momentum.universe import (
    UniverseAsset,
    eligible_at,
    load_universe,
)


# ----- Constants locked by the candidate #4 pre-registration (59c1156) -----

FIXTURE_PATH = _REPO_ROOT / "tests" / "fixtures" / "sleeve_b" / "universe_top30_20260415.json"
VERDICT_OUTPUT_PATH = _REPO_ROOT / "docs" / "strategies" / "sleeve_b_candidate_4_stage_a_verdict.md"

OOS_START = date(2023, 4, 15)
OOS_END = date(2026, 4, 15)

# Per §2.6 of the pre-registration.
MOMENTUM_LOOKBACK_DAYS = 30
VOL_LOOKBACK_DAYS = 45
ELIGIBILITY_DELAY_DAYS = max(MOMENTUM_LOOKBACK_DAYS, VOL_LOOKBACK_DAYS)  # 45

# A1 thresholds (inherited from candidate #2, PASS_DIRECT per §2.5).
A1_FAIL_THRESHOLD = 15  # < this  → FAIL
A1_WARNING_FLOOR = 15   # in [15, 17]  → PASS_WARNING
A1_CLEAN_FLOOR = 18     # >= this  → PASS_CLEAN

# A2 threshold (corrected per 39970f1, applied to spread of E).
A2_FAIL_THRESHOLD = 6  # > this  → FAIL


# ----- D(T) -----

def compute_deterministic_expansion(
    universe: list[UniverseAsset],
    rebalance_dates: list[date],
    delay_days: int,
) -> dict[date, int]:
    """D(T) for each rebalance date.

    Pure function of the frozen fixture's onboard_date field. No OHLCV.
    """
    return {
        t: len(eligible_at(universe, t, listing_delay_days=delay_days))
        for t in rebalance_dates
    }


# ----- C(T) — OHLCV-verified eligibility -----

def fetch_close_dates(
    fetcher: BinanceKlinesArchiveFetcher,
    symbol: str,
    start: date,
    end: date,
) -> set[date]:
    """Return the set of UTC dates for which Binance has a daily close.

    Slightly buffers the start to ensure the (T - 45d) anchor is covered
    for the earliest rebalance date.
    """
    buffered_start = start - timedelta(days=ELIGIBILITY_DELAY_DAYS + 5)
    start_dt = datetime.combine(buffered_start, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_dt = datetime.combine(end + timedelta(days=1), datetime.min.time()).replace(tzinfo=timezone.utc)
    bars = fetcher.fetch_window(symbol, start_dt, end_dt)
    return {b.open_time.date() for b in bars}


def build_ohlcv_availability(
    universe: list[UniverseAsset],
    start: date,
    end: date,
) -> dict[str, set[date]]:
    """For each symbol, the set of dates on which a daily kline exists.

    Uses BinanceKlinesArchiveFetcher with default cache. Cache-served when
    available, network-fetched otherwise. Multi-month windows handled by
    the fetcher.
    """
    fetcher = BinanceKlinesArchiveFetcher(interval="1d")
    availability: dict[str, set[date]] = {}
    for asset in universe:
        # An asset cannot have OHLCV before its onboard date.
        symbol_start = max(start - timedelta(days=ELIGIBILITY_DELAY_DAYS + 5), asset.onboard_date)
        if symbol_start > end:
            availability[asset.symbol] = set()
            continue
        print(f"  fetching {asset.symbol} from {symbol_start} to {end}...", flush=True)
        try:
            availability[asset.symbol] = fetch_close_dates(fetcher, asset.symbol, symbol_start, end)
        except Exception as exc:  # noqa: BLE001
            print(f"    ERROR for {asset.symbol}: {type(exc).__name__}: {exc}", flush=True)
            availability[asset.symbol] = set()
    return availability


def compute_actual_eligibility(
    universe: list[UniverseAsset],
    rebalance_dates: list[date],
    delay_days: int,
    availability: dict[str, set[date]],
) -> dict[date, int]:
    """C(T): assets eligible at T iff:
        - listing age >= delay_days
        - OHLCV exists at T
        - OHLCV exists at T - delay_days
    """
    result: dict[date, int] = {}
    for t in rebalance_dates:
        anchor = t - timedelta(days=delay_days)
        count = 0
        for asset in universe:
            if (t - asset.onboard_date).days < delay_days:
                continue
            asset_dates = availability.get(asset.symbol, set())
            if t in asset_dates and anchor in asset_dates:
                count += 1
        result[t] = count
    return result


# ----- Verdict classification -----

def classify_a1(min_c: int) -> str:
    if min_c < A1_FAIL_THRESHOLD:
        return "FAIL"
    if min_c < A1_CLEAN_FLOOR:  # 15 or 16 or 17
        return "PASS_WARNING"
    return "PASS_CLEAN"


def classify_a2(e_spread: int) -> str:
    if e_spread > A2_FAIL_THRESHOLD:
        return "FAIL"
    return "PASS_CLEAN"


# ----- Verdict memo writer -----

def write_verdict_memo(
    rebalance_dates: list[date],
    d_traj: dict[date, int],
    c_traj: dict[date, int],
    e_traj: dict[date, int],
    a1_verdict: str,
    a2_verdict: str,
    excluded_names: list[tuple[str, date, str]],
    stage_b_authorization: str,
) -> None:
    """Write the Stage A verdict memo."""

    e_values = list(e_traj.values())
    e_min, e_max = min(e_values), max(e_values)
    c_values = list(c_traj.values())
    c_min, c_max = min(c_values), max(c_values)
    d_values = list(d_traj.values())
    d_min, d_max = min(d_values), max(d_values)

    # Identify the rebalance dates where C and D first reach key values.
    first_c_at_min = next(t for t in rebalance_dates if c_traj[t] == c_min)
    first_c_at_max = next(t for t in rebalance_dates if c_traj[t] == c_max)
    nonzero_e_dates = [t for t in rebalance_dates if e_traj[t] != 0]

    lines: list[str] = []
    lines.append("# Sleeve B Candidate #4 — Stage A verdict memo")
    lines.append("")
    lines.append(f"**Status:** Stage A complete")
    lines.append(f"**Date:** {date.today().isoformat()}")
    lines.append(f"**Subordinate to:** `docs/strategies/sleeve_b_candidate_4_preregistration.md` (commit `59c1156`)")
    lines.append(f"**OOS window:** {OOS_START.isoformat()} → {OOS_END.isoformat()}")
    lines.append(f"**Rebalance dates evaluated:** {len(rebalance_dates)} (weekly Mondays)")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 0. Summary")
    lines.append("")
    lines.append("| Sub-gate | Status (per §2.5 of pre-reg) | Verdict |")
    lines.append("|---|---|---|")
    lines.append(f"| A1 — Static coverage | PASS_DIRECT | **{a1_verdict}** |")
    lines.append(f"| A2 — Temporal stability | PASS_ADAPTED | **{a2_verdict}** |")
    lines.append(f"| A3 — Source agreement | NOT_APPLICABLE | N/A |")
    lines.append(f"| A4 — PIT discipline | PASS_DIRECT | **PASS_CLEAN** |")
    lines.append(f"| A5 — Taxonomy sensitivity | PASS_DIRECT | **PASS** |")
    lines.append("")
    lines.append(f"**Stage B authorization: {stage_b_authorization}**")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 1. A1 — Static coverage")
    lines.append("")
    lines.append(f"- C(T) range: [{c_min}, {c_max}]")
    lines.append(f"- min C(T) = {c_min} (first observed at {first_c_at_min.isoformat()})")
    lines.append(f"- max C(T) = {c_max} (first observed at {first_c_at_max.isoformat()})")
    lines.append("")
    lines.append("**Classification rule:**")
    lines.append("")
    lines.append("| min C(T) | Classification |")
    lines.append("|---|---|")
    lines.append("| < 15 | FAIL |")
    lines.append("| 15–17 | PASS_WARNING |")
    lines.append("| ≥ 18 | PASS_CLEAN |")
    lines.append("")
    lines.append(f"**A1 verdict: {a1_verdict}**")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 2. A2 — Temporal stability (corrected per 39970f1 §2.2)")
    lines.append("")
    lines.append("Four-step evaluation:")
    lines.append("")
    lines.append(f"- D(T) range: [{d_min}, {d_max}] — deterministic expansion from fixture")
    lines.append(f"- C(T) range: [{c_min}, {c_max}] — actual OHLCV-verified eligibility")
    lines.append(f"- E(T) = C(T) − D(T) range: [{e_min}, {e_max}]")
    lines.append(f"- Spread of E (max − min) = {e_max - e_min}")
    lines.append("")
    lines.append("**Classification rule:**")
    lines.append("")
    lines.append("| Spread of E | Classification |")
    lines.append("|---|---|")
    lines.append("| > 6 | FAIL |")
    lines.append("| ≤ 6 | PASS_CLEAN |")
    lines.append("")
    lines.append(f"**A2 verdict: {a2_verdict}**")
    lines.append("")
    if nonzero_e_dates:
        lines.append(f"**Non-zero E(T) events:** {len(nonzero_e_dates)} rebalance dates with E ≠ 0.")
        lines.append("")
        lines.append("These represent endogenous instability (assets past the 45-day listing-age delay")
        lines.append("but missing OHLCV at T or T − 45d). Audit list:")
        lines.append("")
        lines.append("| Rebalance date | D(T) | C(T) | E(T) |")
        lines.append("|---|---|---|---|")
        for t in nonzero_e_dates[:30]:  # cap display
            lines.append(f"| {t.isoformat()} | {d_traj[t]} | {c_traj[t]} | {e_traj[t]} |")
        if len(nonzero_e_dates) > 30:
            lines.append(f"| ... | ... | ... | ... ({len(nonzero_e_dates) - 30} more) |")
        lines.append("")
    else:
        lines.append("**Non-zero E(T) events:** 0. E(T) ≡ 0 across all rebalance dates.")
        lines.append("")
        lines.append("OHLCV availability matches listing-age eligibility exactly. No delistings,")
        lines.append("suspensions, or extended OHLCV gaps observed in the universe across OOS.")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 3. A3 — Source agreement")
    lines.append("")
    lines.append("**NOT_APPLICABLE.** Single-venue construction (Binance USDT-M perps). No")
    lines.append("cross-source comparison is required or meaningful for this candidate.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 4. A4 — PIT discipline")
    lines.append("")
    lines.append("**PASS_CLEAN.** Binance daily kline endpoint is venue-native immutable historical")
    lines.append("with no documented backfill mechanism. Klines fetched at any future date for")
    lines.append("a given historical interval return identical values to klines fetched at that")
    lines.append("interval's close. The cache at `~/.cache/hydra-next/binance_klines_1d/` serves")
    lines.append("from immutable monthly archives.")
    lines.append("")
    lines.append("No evidence of Binance kline revision was surfaced during Stage A execution.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 5. A5 — Taxonomy sensitivity")
    lines.append("")
    lines.append("**PASS.** The metric `momentum / realized_vol` has no reasonable taxonomy")
    lines.append("alternatives. Window-length choices (30-day momentum, 45-day vol) are parameters")
    lines.append("locked at §2.6 of the pre-registration, not taxonomy decisions. No sensitivity")
    lines.append("test is required or meaningful.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 6. D(T) trajectory")
    lines.append("")
    lines.append("Computed from the frozen fixture by applying the 45-day listing-age rule to each")
    lines.append("asset's onboard_date. Monotone non-decreasing across OOS by construction.")
    lines.append("")
    lines.append("Key transition dates:")
    lines.append("")
    seen_d = -1
    transition_lines = []
    for t in rebalance_dates:
        if d_traj[t] != seen_d:
            transition_lines.append(f"| {t.isoformat()} | {d_traj[t]} |")
            seen_d = d_traj[t]
    lines.append("| Rebalance date | D(T) |")
    lines.append("|---|---|")
    for tl in transition_lines:
        lines.append(tl)
    lines.append("")
    lines.append(f"Total deterministic expansion across OOS: {d_max - d_min} names "
                 f"({d_min} → {d_max}).")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 7. Excluded names")
    lines.append("")
    if excluded_names:
        lines.append("Names that were not eligible at every rebalance date, with first-eligible date:")
        lines.append("")
        lines.append("| Symbol | Onboard date | First-eligible date |")
        lines.append("|---|---|---|")
        for sym, onboard, first_elig in excluded_names:
            lines.append(f"| {sym} | {onboard.isoformat()} | {first_elig} |")
        lines.append("")
    else:
        lines.append("All universe names were eligible at all rebalance dates.")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 8. Stage B authorization")
    lines.append("")
    lines.append(f"**{stage_b_authorization}**")
    lines.append("")
    if stage_b_authorization.startswith("CONSTRAINED"):
        lines.append("Stage B operates under the warning-tightened threshold structure of §4.B3:")
        lines.append("Sharpe ≥ 1.75 AND drawdown ≤ 20% required for promotion eligibility.")
    elif stage_b_authorization.startswith("UNCONSTRAINED"):
        lines.append("Stage B operates under the clean threshold structure of §4.B3:")
        lines.append("Sharpe ≥ 1.5 AND drawdown ≤ 25% required for promotion eligibility.")
    else:
        lines.append("Stage A failed; Stage B does not begin. Draft kill action per §9 of the pre-reg.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 9. Audit data")
    lines.append("")
    lines.append("Full rebalance-date series for D(T), C(T), E(T):")
    lines.append("")
    lines.append("| Rebalance date | D(T) | C(T) | E(T) |")
    lines.append("|---|---|---|---|")
    for t in rebalance_dates:
        lines.append(f"| {t.isoformat()} | {d_traj[t]} | {c_traj[t]} | {e_traj[t]} |")
    lines.append("")

    VERDICT_OUTPUT_PATH.write_text("\n".join(lines))
    print(f"\nVerdict memo written to: {VERDICT_OUTPUT_PATH}")


# ----- Main -----

def main() -> int:
    print(f"Loading universe from {FIXTURE_PATH}")
    universe = load_universe(FIXTURE_PATH)
    print(f"  Loaded {len(universe)} assets")

    print(f"\nGenerating rebalance dates {OOS_START} -> {OOS_END}")
    rebalance_dates = generate_rebalance_dates(OOS_START, OOS_END)
    print(f"  {len(rebalance_dates)} weekly Monday rebalance dates")

    print(f"\nComputing D(T) trajectory (deterministic expansion, eligibility delay {ELIGIBILITY_DELAY_DAYS}d)")
    d_traj = compute_deterministic_expansion(universe, rebalance_dates, ELIGIBILITY_DELAY_DAYS)
    d_min, d_max = min(d_traj.values()), max(d_traj.values())
    print(f"  D(T) range: [{d_min}, {d_max}]")

    print(f"\nBuilding OHLCV availability from cache/archive (this may take a while if cache is cold)")
    availability = build_ohlcv_availability(universe, OOS_START, OOS_END)

    print(f"\nComputing C(T) trajectory (OHLCV-verified eligibility)")
    c_traj = compute_actual_eligibility(universe, rebalance_dates, ELIGIBILITY_DELAY_DAYS, availability)
    c_min, c_max = min(c_traj.values()), max(c_traj.values())
    print(f"  C(T) range: [{c_min}, {c_max}]")

    e_traj = {t: c_traj[t] - d_traj[t] for t in rebalance_dates}
    e_min, e_max = min(e_traj.values()), max(e_traj.values())
    e_spread = e_max - e_min
    print(f"  E(T) range: [{e_min}, {e_max}], spread = {e_spread}")

    # Excluded names: anyone not eligible at every rebalance date.
    excluded: list[tuple[str, date, str]] = []
    for asset in universe:
        first_eligible_date = asset.onboard_date + timedelta(days=ELIGIBILITY_DELAY_DAYS)
        if first_eligible_date > rebalance_dates[0]:
            excluded.append((asset.symbol, asset.onboard_date, first_eligible_date.isoformat()))

    # Classify.
    a1_verdict = classify_a1(c_min)
    a2_verdict = classify_a2(e_spread)

    print(f"\nA1 verdict: {a1_verdict} (min C = {c_min})")
    print(f"A2 verdict: {a2_verdict} (spread of E = {e_spread})")

    # Stage B authorization.
    if a1_verdict == "FAIL" or a2_verdict == "FAIL":
        stage_b_auth = "SHELVE — draft kill action per §9 of pre-reg"
    elif a1_verdict == "PASS_WARNING":
        stage_b_auth = "CONSTRAINED (per §4.B3: A1 PASS_WARNING tightens Stage B thresholds)"
    else:
        stage_b_auth = "UNCONSTRAINED"

    print(f"Stage B authorization: {stage_b_auth}")

    # Write the memo.
    write_verdict_memo(
        rebalance_dates,
        d_traj,
        c_traj,
        e_traj,
        a1_verdict,
        a2_verdict,
        excluded,
        stage_b_auth,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
