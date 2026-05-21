#!/usr/bin/env python3
"""Sleeve B candidate #4 — F1 evaluator (D3 of 5 Stage B deliverables).

Computes F1.1 / F1.2 / F1.3 / F1.4 sub-gates per pre-registration 59c1156 §5.
Writes verdict memo to docs/strategies/sleeve_b_candidate_4_f1_verdict.md.

F1.1 — Vol estimator stability:
  Per asset, rolling 60d stdev of the 45d realized-vol time series,
  normalized by mean of that series. Cross-sectional median.

F1.2 — Rank churn:
  Fraction of top-third (long bucket) retained week-over-week, averaged
  across all rebalance transitions.

F1.3 — Numerator-vs-denominator variance contribution:
  Counterfactual decomposition. At each rebalance, compute:
    var_score_actual = Var(momentum_i / vol_i across i)
    var_score_if_constant_vol = Var(momentum_i / vol_bar across i)
                                where vol_bar = mean(vol) at this rebalance
  fraction_momentum_explains = var_score_if_constant_vol / var_score_actual
  Take median across rebalance dates.

  This operationalization is documented in the verdict memo because the
  pre-registration did not lock the specific decomposition formula.

F1.4 — Window sensitivity:
  Re-run backtest with 4 pre-registered parameter variants:
    (mom=15d, vol=45d), (mom=45d, vol=45d), (mom=30d, vol=30d), (mom=30d, vol=60d)
  Compute (max - min) / median Sharpe.

Reads ef788b7 audit log. Writes verdict memo only.
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from data.ingestion.vendors.binance.klines_archive_fetcher import (  # noqa: E402
    BinanceKlinesArchiveFetcher,
)
from strategies.sleeve_b.vol_scaled_momentum.backtest import (  # noqa: E402
    run_backtest,
)
from strategies.sleeve_b.xs_momentum.prices import (  # noqa: E402
    PriceBar, PriceSeries,
)
from strategies.sleeve_b.xs_momentum.universe import (  # noqa: E402
    UniverseAsset, load_universe,
)


# --- Paths ---
RUN_LOG_PATH = REPO_ROOT / "tests/fixtures/sleeve_b/vol_scaled_momentum_run_log.jsonl"
PNL_PATH = REPO_ROOT / "tests/fixtures/sleeve_b/vol_scaled_momentum_weekly_pnl.jsonl"
UNIVERSE_FIXTURE = REPO_ROOT / "tests/fixtures/sleeve_b/universe_top30_20260415.json"
VERDICT_PATH = REPO_ROOT / "docs/strategies/sleeve_b_candidate_4_f1_verdict.md"

OOS_START = date(2023, 4, 15)
OOS_END = date(2026, 4, 15)
PRICE_BUFFER_DAYS = 75  # Generous buffer for window-sensitivity variants (max vol=60d).

# --- Thresholds per pre-registration §5 ---

# F1.1 — vol estimator stability (cross-sectional median of vol-of-vol)
F1_1_FAIL = 0.6
F1_1_WARNING_LOW = 0.4

# F1.2 — rank churn (median top-bucket retention)
F1_2_FAIL = 0.40
F1_2_WARNING_HIGH = 0.55

# F1.3 — numerator-vs-denominator variance contribution
F1_3_FAIL = 0.5
F1_3_WARNING_HIGH = 0.65

# F1.4 — window sensitivity (max-min)/median Sharpe
F1_4_FAIL = 0.30
F1_4_WARNING_LOW = 0.15

# F1.4 variants per pre-registration §5
F1_4_VARIANTS = [
    (15, 45),  # (momentum_days, vol_days)
    (45, 45),
    (30, 30),
    (30, 60),
]
F1_4_BASELINE = (30, 45)


# --- Load run log ---

def load_run_log() -> list[dict]:
    rows: list[dict] = []
    with RUN_LOG_PATH.open() as f:
        for line in f:
            rows.append(json.loads(line))
    return rows


def parse_decimal_dict(d: dict) -> dict[str, Decimal]:
    return {k: Decimal(v) for k, v in d.items()}


# --- F1.1 — Vol estimator stability ---

def compute_f1_1(rows: list[dict]) -> tuple[str, dict]:
    """Vol-of-vol per asset, cross-sectional median.

    For each asset, build the time series of its 45d realized vol across
    all rebalance dates where it was eligible. Compute the *rolling 60d
    stdev / mean* of that time series. The pre-reg says "rolling 60d
    realized stdev of the 45d realized-vol time series" — operationalized
    here as: 60-day-rolling stdev (≈ 9 weekly rebalances) divided by
    rolling mean over the same window.

    For each asset, take the median of the rolling vol-of-vol metric
    across the OOS window. Then take the cross-sectional median across
    all assets.
    """
    # Build per-asset vol time series.
    asset_vols: dict[str, list[Decimal]] = {}
    for row in rows:
        if row["skipped"]:
            continue
        vols = parse_decimal_dict(row["vol_components"])
        for sym, v in vols.items():
            asset_vols.setdefault(sym, []).append(v)

    # Rolling window of 9 weekly samples ≈ 60-65 days.
    window_size = 9

    per_asset_vol_of_vol: dict[str, float] = {}
    for sym, series in asset_vols.items():
        if len(series) < window_size:
            continue
        rolling_ratios: list[float] = []
        for i in range(window_size, len(series) + 1):
            window = series[i - window_size:i]
            window_floats = [float(x) for x in window]
            mean_w = statistics.mean(window_floats)
            if mean_w <= 0:
                continue
            stdev_w = statistics.stdev(window_floats)
            rolling_ratios.append(stdev_w / mean_w)
        if rolling_ratios:
            per_asset_vol_of_vol[sym] = statistics.median(rolling_ratios)

    if not per_asset_vol_of_vol:
        return ("FAIL", {"reason": "no_per_asset_data", "values": {}})

    xs_median = statistics.median(per_asset_vol_of_vol.values())

    if xs_median > F1_1_FAIL:
        verdict = "FAIL"
    elif xs_median > F1_1_WARNING_LOW:
        verdict = "PASS_WARNING"
    else:
        verdict = "PASS_CLEAN"

    return (verdict, {
        "xs_median_vol_of_vol": xs_median,
        "per_asset_count": len(per_asset_vol_of_vol),
        "per_asset_min": min(per_asset_vol_of_vol.values()),
        "per_asset_max": max(per_asset_vol_of_vol.values()),
        "per_asset_values": per_asset_vol_of_vol,
    })


# --- F1.2 — Rank churn ---

def compute_f1_2(rows: list[dict]) -> tuple[str, dict]:
    """Fraction of long bucket retained week-over-week.

    For each consecutive pair of non-skipped rebalances, compute:
      |L_curr ∩ L_prev| / |L_curr|
    where L is the long bucket. Take the average across all transitions.
    """
    non_skipped = [r for r in rows if not r["skipped"]]
    if len(non_skipped) < 2:
        return ("FAIL", {"reason": "insufficient_non_skipped", "n": len(non_skipped)})

    retentions: list[float] = []
    for i in range(1, len(non_skipped)):
        prev_long = set(non_skipped[i - 1]["long_bucket"])
        curr_long = set(non_skipped[i]["long_bucket"])
        if not curr_long:
            continue
        retention = len(curr_long & prev_long) / len(curr_long)
        retentions.append(retention)

    if not retentions:
        return ("FAIL", {"reason": "no_transitions", "n_transitions": 0})

    mean_retention = statistics.mean(retentions)
    median_retention = statistics.median(retentions)

    if median_retention < F1_2_FAIL:
        verdict = "FAIL"
    elif median_retention < F1_2_WARNING_HIGH:
        verdict = "PASS_WARNING"
    else:
        verdict = "PASS_CLEAN"

    return (verdict, {
        "median_retention": median_retention,
        "mean_retention": mean_retention,
        "n_transitions": len(retentions),
        "min_retention": min(retentions),
        "max_retention": max(retentions),
    })


# --- F1.3 — Numerator-vs-denominator variance contribution ---

def compute_f1_3(rows: list[dict]) -> tuple[str, dict]:
    """Fraction of cross-sectional score variance attributable to momentum.

    Counterfactual decomposition. At each rebalance:
      var_actual = Var(m_i / v_i) across eligible assets
      var_constant_vol = Var(m_i / v_bar) where v_bar = mean(v) at this rebalance
      fraction_momentum = var_constant_vol / var_actual

    If fraction_momentum is close to 1, varying vol added little — momentum
    drives the ranking. If fraction_momentum is close to 0, varying vol
    drove most of the cross-sectional dispersion of the final score.

    Take median across rebalance dates.

    Operationalization choice (not pre-registration-locked): documented
    in the verdict memo.
    """
    per_rebalance_fractions: list[float] = []
    for row in rows:
        if row["skipped"]:
            continue
        momentum = parse_decimal_dict(row["momentum_components"])
        vols = parse_decimal_dict(row["vol_components"])

        # Compute across common eligible assets.
        common = set(momentum.keys()) & set(vols.keys())
        if len(common) < 2:
            continue

        # Actual scores.
        actual_scores = [float(momentum[s] / vols[s]) for s in common]
        # Counterfactual: replace each vol with cross-sectional mean.
        vol_bar = statistics.mean(float(vols[s]) for s in common)
        if vol_bar <= 0:
            continue
        cf_scores = [float(momentum[s]) / vol_bar for s in common]

        var_actual = statistics.variance(actual_scores)
        var_cf = statistics.variance(cf_scores)
        if var_actual <= 0:
            continue
        fraction = var_cf / var_actual
        per_rebalance_fractions.append(fraction)

    if not per_rebalance_fractions:
        return ("FAIL", {"reason": "no_decomposable_rebalances"})

    median_fraction = statistics.median(per_rebalance_fractions)

    if median_fraction < F1_3_FAIL:
        verdict = "FAIL"
    elif median_fraction < F1_3_WARNING_HIGH:
        verdict = "PASS_WARNING"
    else:
        verdict = "PASS_CLEAN"

    return (verdict, {
        "median_fraction_momentum_explains": median_fraction,
        "mean_fraction": statistics.mean(per_rebalance_fractions),
        "min_fraction": min(per_rebalance_fractions),
        "max_fraction": max(per_rebalance_fractions),
        "n_rebalances": len(per_rebalance_fractions),
    })


# --- F1.4 — Window sensitivity ---

def _fetch_window_for_klines(symbol: str, fetcher: BinanceKlinesArchiveFetcher) -> list:
    start_dt = datetime.combine(
        OOS_START - timedelta(days=PRICE_BUFFER_DAYS), time(0, 0),
        tzinfo=timezone.utc,
    )
    end_dt = datetime.combine(
        OOS_END + timedelta(days=14), time(0, 0), tzinfo=timezone.utc,
    )
    return fetcher.fetch_window(symbol, start_dt, end_dt)


def _build_price_series(symbol: str, klines: list) -> PriceSeries:
    bars = []
    for k in klines:
        bars.append(PriceBar(
            bar_date=k.open_time.date(),
            open_price=k.open,
            close_price=k.close,
        ))
    return PriceSeries(symbol, bars)


def _load_price_map(universe: list[UniverseAsset]) -> dict:
    fetcher = BinanceKlinesArchiveFetcher(interval="1d")
    prices = {}
    for asset in universe:
        klines = _fetch_window_for_klines(asset.symbol, fetcher)
        prices[asset.symbol] = _build_price_series(asset.symbol, klines)
    return prices


def _annualized_sharpe(weekly_pnl_bps: list[Decimal]) -> float | None:
    if len(weekly_pnl_bps) < 2:
        return None
    as_floats = [float(b) / 10000 for b in weekly_pnl_bps]
    mean_w = statistics.mean(as_floats)
    stdev_w = statistics.stdev(as_floats)
    if stdev_w == 0:
        return None
    return (mean_w / stdev_w) * math.sqrt(52)


def compute_f1_4(
    universe: list[UniverseAsset], prices: dict,
) -> tuple[str, dict]:
    """Window sensitivity: re-run backtest with 4 variants + report sensitivity.

    Per pre-registration §5.F1.4. Baseline (30, 45) is candidate #4's
    locked parameters; reported alongside for context but NOT included
    in the (max - min) / median calculation since the metric is across
    variants, not baseline-and-variants.

    Wait — re-reading the pre-reg: "Re-run the backtest with parameter
    variants: ..." and "sensitivity = (max_Sharpe − min_Sharpe) / median_Sharpe"
    — the four variants. The pre-reg implies *all variants*, which would
    naturally include the baseline (30, 45) since one of the four explicit
    variants listed is essentially scanning around it. But (30, 45) is
    NOT in the four-variant list. The pre-reg specified four DIFFERENT
    parameter sets.

    Sensitivity = (max - min) / median across exactly the four variants.
    Baseline is reported separately for reference.
    """
    variant_sharpes: dict[tuple[int, int], float | None] = {}

    for mom_days, vol_days in F1_4_VARIANTS:
        print(f"  Variant (mom={mom_days}d, vol={vol_days}d)...", flush=True)
        result = run_backtest(
            universe=universe,
            prices=prices,
            start=OOS_START,
            end=OOS_END,
            momentum_lookback_days=mom_days,
            vol_lookback_days=vol_days,
        )
        weekly_pnl_bps = [w.net_pnl_bps for w in result.weekly_pnls]
        sharpe = _annualized_sharpe(weekly_pnl_bps)
        variant_sharpes[(mom_days, vol_days)] = sharpe
        sharpe_str = f"{sharpe:.4f}" if sharpe is not None else "undefined"
        print(f"    Sharpe: {sharpe_str}")

    # Baseline reference.
    print(f"  Baseline (mom=30d, vol=45d) — re-running for parity...", flush=True)
    baseline_result = run_backtest(
        universe=universe, prices=prices, start=OOS_START, end=OOS_END,
        momentum_lookback_days=30, vol_lookback_days=45,
    )
    baseline_sharpe = _annualized_sharpe(
        [w.net_pnl_bps for w in baseline_result.weekly_pnls]
    )

    valid_sharpes = [s for s in variant_sharpes.values() if s is not None]
    if len(valid_sharpes) < 2:
        return ("FAIL", {
            "reason": "insufficient_valid_variants",
            "valid_count": len(valid_sharpes),
            "variant_sharpes": {f"{k}": v for k, v in variant_sharpes.items()},
        })

    max_s = max(valid_sharpes)
    min_s = min(valid_sharpes)
    median_s = statistics.median(valid_sharpes)
    if median_s == 0:
        return ("FAIL", {
            "reason": "zero_median_sharpe",
            "variant_sharpes": {f"{k}": v for k, v in variant_sharpes.items()},
        })

    sensitivity = (max_s - min_s) / abs(median_s)

    if sensitivity > F1_4_FAIL:
        verdict = "FAIL"
    elif sensitivity > F1_4_WARNING_LOW:
        verdict = "PASS_WARNING"
    else:
        verdict = "PASS_CLEAN"

    return (verdict, {
        "sensitivity": sensitivity,
        "max_sharpe": max_s,
        "min_sharpe": min_s,
        "median_sharpe": median_s,
        "variant_sharpes": {f"({k[0]}, {k[1]})": v for k, v in variant_sharpes.items()},
        "baseline_sharpe_reference": baseline_sharpe,
    })


# --- Memo writer ---

def write_verdict_memo(
    f1_1: tuple[str, dict],
    f1_2: tuple[str, dict],
    f1_3: tuple[str, dict],
    f1_4: tuple[str, dict],
) -> None:
    f1_1_verdict, f1_1_details = f1_1
    f1_2_verdict, f1_2_details = f1_2
    f1_3_verdict, f1_3_details = f1_3
    f1_4_verdict, f1_4_details = f1_4

    # Overall F1 family verdict: any FAIL = FAIL; any WARNING with no FAIL = WARNING.
    verdicts = [f1_1_verdict, f1_2_verdict, f1_3_verdict, f1_4_verdict]
    if "FAIL" in verdicts:
        overall = "FAIL"
    elif "PASS_WARNING" in verdicts:
        overall = "PASS_WARNING"
    else:
        overall = "PASS_CLEAN"

    lines: list[str] = []
    lines.append("# Sleeve B Candidate #4 — F1 sub-gate verdict memo")
    lines.append("")
    lines.append(f"**Status:** D3 of 5 Stage B engineering deliverables")
    lines.append(f"**Date:** {date.today().isoformat()}")
    lines.append(f"**Subordinate to:** `docs/strategies/sleeve_b_candidate_4_preregistration.md` (commit `59c1156`)")
    lines.append(f"**Consumes:** `tests/fixtures/sleeve_b/vol_scaled_momentum_run_log.jsonl` (committed at `ef788b7`)")
    lines.append(f"**F1 family verdict:** **{overall}**")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 0. Summary")
    lines.append("")
    lines.append("| Sub-gate | Description | Verdict |")
    lines.append("|---|---|---|")
    lines.append(f"| F1.1 | Vol estimator stability (vol-of-vol) | **{f1_1_verdict}** |")
    lines.append(f"| F1.2 | Rank churn (top-bucket retention) | **{f1_2_verdict}** |")
    lines.append(f"| F1.3 | Numerator-vs-denominator variance contribution | **{f1_3_verdict}** |")
    lines.append(f"| F1.4 | Window sensitivity | **{f1_4_verdict}** |")
    lines.append("")
    lines.append(f"**Overall F1 family: {overall}**")
    lines.append("")
    lines.append("Per pre-registration §5: any F1 sub-gate FAIL is candidate-kill-capable regardless of Sharpe gate outcome.")
    lines.append("")
    lines.append("---")
    lines.append("")

    # F1.1
    lines.append("## 1. F1.1 — Vol estimator stability")
    lines.append("")
    lines.append("Per pre-reg §5.F1.1: per-asset rolling 60d stdev of 45d realized-vol")
    lines.append("time series, divided by rolling mean. Cross-sectional median across assets.")
    lines.append("")
    lines.append("Operationalization: 9 weekly samples per rolling window (≈ 63 days),")
    lines.append("stdev/mean per window, median across windows per asset, then median across assets.")
    lines.append("")
    lines.append("| Threshold | Classification |")
    lines.append("|---|---|")
    lines.append("| > 0.6 | FAIL |")
    lines.append("| 0.4–0.6 | PASS_WARNING |")
    lines.append("| ≤ 0.4 | PASS_CLEAN |")
    lines.append("")
    if "xs_median_vol_of_vol" in f1_1_details:
        lines.append(f"**Result:** cross-sectional median vol-of-vol = `{f1_1_details['xs_median_vol_of_vol']:.4f}`")
        lines.append("")
        lines.append(f"- Per-asset count: {f1_1_details['per_asset_count']}")
        lines.append(f"- Per-asset min: {f1_1_details['per_asset_min']:.4f}")
        lines.append(f"- Per-asset max: {f1_1_details['per_asset_max']:.4f}")
        lines.append("")
        lines.append("### Per-asset vol-of-vol (sorted)")
        lines.append("")
        lines.append("| Symbol | vol-of-vol |")
        lines.append("|---|---|")
        sorted_assets = sorted(
            f1_1_details["per_asset_values"].items(),
            key=lambda kv: kv[1],
        )
        for sym, v in sorted_assets:
            lines.append(f"| {sym} | {v:.4f} |")
    else:
        lines.append(f"**Result:** FAIL — {f1_1_details.get('reason', 'unknown')}")
    lines.append("")
    lines.append(f"**F1.1 verdict: {f1_1_verdict}**")
    lines.append("")
    lines.append("---")
    lines.append("")

    # F1.2
    lines.append("## 2. F1.2 — Rank churn")
    lines.append("")
    lines.append("Per pre-reg §5.F1.2: fraction of long bucket retained week-over-week,")
    lines.append("averaged across all rebalance transitions. Uses median for robustness.")
    lines.append("")
    lines.append("| Threshold (median retention) | Classification |")
    lines.append("|---|---|")
    lines.append("| < 0.40 | FAIL |")
    lines.append("| 0.40–0.55 | PASS_WARNING |")
    lines.append("| ≥ 0.55 | PASS_CLEAN |")
    lines.append("")
    if "median_retention" in f1_2_details:
        lines.append(f"**Result:** median retention = `{f1_2_details['median_retention']:.4f}`")
        lines.append("")
        lines.append(f"- Mean retention: {f1_2_details['mean_retention']:.4f}")
        lines.append(f"- Min retention: {f1_2_details['min_retention']:.4f}")
        lines.append(f"- Max retention: {f1_2_details['max_retention']:.4f}")
        lines.append(f"- Number of transitions: {f1_2_details['n_transitions']}")
    else:
        lines.append(f"**Result:** FAIL — {f1_2_details.get('reason', 'unknown')}")
    lines.append("")
    lines.append(f"**F1.2 verdict: {f1_2_verdict}**")
    lines.append("")
    lines.append("---")
    lines.append("")

    # F1.3
    lines.append("## 3. F1.3 — Numerator-vs-denominator variance contribution")
    lines.append("")
    lines.append("Per pre-reg §5.F1.3: 'Decompose the variance of the ranked score across")
    lines.append("the cross-section at each rebalance date into momentum-numerator variance,")
    lines.append("vol-denominator variance, and interaction. Compute the fraction of total")
    lines.append("cross-sectional score variance attributable to the momentum numerator.'")
    lines.append("")
    lines.append("### Operationalization (not pre-registration-locked, documented here)")
    lines.append("")
    lines.append("Counterfactual decomposition. At each rebalance:")
    lines.append("")
    lines.append("```")
    lines.append("var_actual         = Var(momentum_i / vol_i)              cross-sectional")
    lines.append("var_constant_vol   = Var(momentum_i / mean(vol))          replace vols with xs-mean")
    lines.append("fraction_momentum  = var_constant_vol / var_actual")
    lines.append("```")
    lines.append("")
    lines.append("Interpretation: if `fraction_momentum` ≈ 1, varying vol added little")
    lines.append("cross-sectional information — momentum alone explains the score dispersion.")
    lines.append("If `fraction_momentum` ≈ 0, the vol denominator drove the dispersion and")
    lines.append("the construction is not actually momentum.")
    lines.append("")
    lines.append("Median across rebalance dates.")
    lines.append("")
    lines.append("Why this operationalization: the pre-registration framed F1.3 as 'does the")
    lines.append("numerator do meaningful work?' The counterfactual directly answers that")
    lines.append("question without requiring log-linearization assumptions (which fail when")
    lines.append("momentum is negative). Three alternatives considered: log decomposition")
    lines.append("(unworkable for negative momentum), delta-method linearization (needed for")
    lines.append("ratio statistics in classical stats but harder to interpret), counterfactual")
    lines.append("(chosen).")
    lines.append("")
    lines.append("| Threshold (fraction explained by momentum) | Classification |")
    lines.append("|---|---|")
    lines.append("| < 0.5 | FAIL (vol denominator dominates) |")
    lines.append("| 0.5–0.65 | PASS_WARNING |")
    lines.append("| > 0.65 | PASS_CLEAN |")
    lines.append("")
    if "median_fraction_momentum_explains" in f1_3_details:
        lines.append(f"**Result:** median fraction explained by momentum = `{f1_3_details['median_fraction_momentum_explains']:.4f}`")
        lines.append("")
        lines.append(f"- Mean fraction: {f1_3_details['mean_fraction']:.4f}")
        lines.append(f"- Min fraction: {f1_3_details['min_fraction']:.4f}")
        lines.append(f"- Max fraction: {f1_3_details['max_fraction']:.4f}")
        lines.append(f"- Number of rebalances: {f1_3_details['n_rebalances']}")
    else:
        lines.append(f"**Result:** FAIL — {f1_3_details.get('reason', 'unknown')}")
    lines.append("")
    lines.append(f"**F1.3 verdict: {f1_3_verdict}**")
    lines.append("")
    lines.append("---")
    lines.append("")

    # F1.4
    lines.append("## 4. F1.4 — Window sensitivity")
    lines.append("")
    lines.append("Per pre-reg §5.F1.4: re-run backtest with four parameter variants and")
    lines.append("compute `(max - min) / median` Sharpe across the variants.")
    lines.append("")
    lines.append("Variants:")
    lines.append("- (momentum=15d, vol=45d)")
    lines.append("- (momentum=45d, vol=45d)")
    lines.append("- (momentum=30d, vol=30d)")
    lines.append("- (momentum=30d, vol=60d)")
    lines.append("")
    lines.append("Sensitivity computed across the four variants (baseline 30/45 reported separately).")
    lines.append("")
    lines.append("| Threshold | Classification |")
    lines.append("|---|---|")
    lines.append("| > 0.30 | FAIL |")
    lines.append("| 0.15–0.30 | PASS_WARNING |")
    lines.append("| ≤ 0.15 | PASS_CLEAN |")
    lines.append("")
    if "sensitivity" in f1_4_details:
        lines.append(f"**Result:** sensitivity = `{f1_4_details['sensitivity']:.4f}`")
        lines.append("")
        lines.append("### Variant Sharpe table")
        lines.append("")
        lines.append("| (momentum_days, vol_days) | Sharpe |")
        lines.append("|---|---|")
        for variant_key, sh in f1_4_details["variant_sharpes"].items():
            sh_str = f"{sh:.4f}" if sh is not None else "undefined"
            lines.append(f"| {variant_key} | {sh_str} |")
        baseline_sharpe = f1_4_details.get("baseline_sharpe_reference")
        if baseline_sharpe is not None:
            lines.append(f"| (30, 45) — baseline (reference) | {baseline_sharpe:.4f} |")
        lines.append("")
        lines.append(f"- max Sharpe: {f1_4_details['max_sharpe']:.4f}")
        lines.append(f"- min Sharpe: {f1_4_details['min_sharpe']:.4f}")
        lines.append(f"- median Sharpe (across variants): {f1_4_details['median_sharpe']:.4f}")
    else:
        lines.append(f"**Result:** FAIL — {f1_4_details.get('reason', 'unknown')}")
    lines.append("")
    lines.append(f"**F1.4 verdict: {f1_4_verdict}**")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Footer
    lines.append("## 5. Implications for D4 and D5")
    lines.append("")
    if overall == "FAIL":
        lines.append("F1 family FAIL is candidate-kill-capable per pre-reg §5/§9.")
        lines.append("D5 (verdict memo) must classify this candidate as a kill regardless")
        lines.append("of B3 Sharpe gate outcome. D4 (F3 evaluator) still runs to complete")
        lines.append("the evidence record, but D5's classification is constrained by this F1 FAIL.")
    elif overall == "PASS_WARNING":
        lines.append("F1 family PASS_WARNING does not by itself kill the candidate, but")
        lines.append("interacts with the Stage B promotion thresholds in §4.B3. D5 will")
        lines.append("synthesize this against D4 (F3) and the D2 raw Sharpe/drawdown.")
    else:
        lines.append("F1 family PASS_CLEAN. D5 will assess against §4.B3 promotion thresholds")
        lines.append("considering D2 metrics and D4 (F3) evidence.")
    lines.append("")
    lines.append("D5 cannot be drafted until D4 has run. F1 evidence alone is not a verdict.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 6. References")
    lines.append("")
    lines.append(f"- Candidate #4 pre-registration: `docs/strategies/sleeve_b_candidate_4_preregistration.md` (commit `59c1156`)")
    lines.append(f"- D1 signal module: commit `8cc69fc`")
    lines.append(f"- D2 backtest engine: commit `3e06210`")
    lines.append(f"- D2 artifacts (this memo consumes): commit `ef788b7`")
    lines.append(f"- Portfolio interpretation memo: commit `689ddd9`")
    lines.append("")

    VERDICT_PATH.parent.mkdir(parents=True, exist_ok=True)
    VERDICT_PATH.write_text("\n".join(lines))
    print(f"\nVerdict memo written to: {VERDICT_PATH}")


# --- Main ---

def main() -> int:
    print("=" * 60)
    print("Sleeve B candidate #4 — F1 evaluator (D3)")
    print("=" * 60)
    print()

    print("Loading run log...")
    rows = load_run_log()
    print(f"  {len(rows)} rebalance rows loaded.")
    print()

    print("Computing F1.1 (vol estimator stability)...")
    f1_1 = compute_f1_1(rows)
    print(f"  F1.1 verdict: {f1_1[0]}")
    if "xs_median_vol_of_vol" in f1_1[1]:
        print(f"  xs median vol-of-vol: {f1_1[1]['xs_median_vol_of_vol']:.4f}")
    print()

    print("Computing F1.2 (rank churn)...")
    f1_2 = compute_f1_2(rows)
    print(f"  F1.2 verdict: {f1_2[0]}")
    if "median_retention" in f1_2[1]:
        print(f"  median retention: {f1_2[1]['median_retention']:.4f}")
    print()

    print("Computing F1.3 (numerator-vs-denominator variance contribution)...")
    f1_3 = compute_f1_3(rows)
    print(f"  F1.3 verdict: {f1_3[0]}")
    if "median_fraction_momentum_explains" in f1_3[1]:
        print(f"  median fraction explained by momentum: {f1_3[1]['median_fraction_momentum_explains']:.4f}")
    print()

    print("Computing F1.4 (window sensitivity)...")
    print("  Re-running backtest with 4 parameter variants + baseline...")
    universe = load_universe(UNIVERSE_FIXTURE)
    print(f"  Loading prices...")
    prices = _load_price_map(universe)
    f1_4 = compute_f1_4(universe, prices)
    print(f"  F1.4 verdict: {f1_4[0]}")
    if "sensitivity" in f1_4[1]:
        print(f"  sensitivity: {f1_4[1]['sensitivity']:.4f}")
    print()

    print("Writing verdict memo...")
    write_verdict_memo(f1_1, f1_2, f1_3, f1_4)
    print()

    overall_verdicts = [f1_1[0], f1_2[0], f1_3[0], f1_4[0]]
    if "FAIL" in overall_verdicts:
        overall = "FAIL"
    elif "PASS_WARNING" in overall_verdicts:
        overall = "PASS_WARNING"
    else:
        overall = "PASS_CLEAN"

    print("=" * 60)
    print(f"F1 family overall verdict: {overall}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
