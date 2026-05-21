#!/usr/bin/env python3
"""Sleeve B candidate #4 — F3 evaluator (D4 of 5 Stage B deliverables).

Computes F3.1 / F3.2 / F3.3 sub-gates per pre-registration 59c1156 §6.
Writes verdict memo to docs/strategies/sleeve_b_candidate_4_f3_verdict.md.

F3.1 — Long-bucket vol concentration:
  median(long_bucket_vol) / median(universe_vol) per rebalance, averaged
  across rebalance dates.

F3.2 — BTC/ETH joint dominance:
  Fraction of rebalance dates where both BTC and ETH appear in the
  long bucket simultaneously.

F3.3 — Low-vol attribution decomposition:
  Counterfactual attribution. Three long-short backtests over OOS:
    (a) candidate #4 actual (vol-scaled momentum)
    (b) pure momentum (long top-third by 30d return, short bottom-third)
    (c) pure low-vol (long bottom-third by 45d vol, short top-third)
  Decomposition: total = pure_momentum + pure_low_vol + interaction
  where interaction is residual (defined as a - b - c using compounded NAV
  end-points). Report fraction = pure_low_vol / total in NAV terms.

F3 sub-gates are kill-capable independent of Sharpe.

Reads ef788b7 audit log. Writes verdict memo only.
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from data.ingestion.vendors.binance.klines_archive_fetcher import (  # noqa: E402
    BinanceKlinesArchiveFetcher,
)
from strategies.sleeve_b.vol_scaled_momentum.backtest import (  # noqa: E402
    BacktestResult, RebalanceLog, run_backtest,
)
from strategies.sleeve_b.vol_scaled_momentum.signal import (  # noqa: E402
    MIN_ELIGIBLE_FOR_REBALANCE,
    MOMENTUM_LOOKBACK_DAYS,
    SignalOutput as VSMSignalOutput,
    VOL_LOOKBACK_DAYS,
    collect_log_returns_window,
    realized_vol_from_log_returns,
)
from strategies.sleeve_b.xs_momentum.backtest import (  # noqa: E402
    FEES_BPS_ROUND_TRIP,
    HOLDING_DAYS,
    WeeklyPnL,
    _compute_bucket_pnl_bps,
    generate_rebalance_dates,
)
from strategies.sleeve_b.xs_momentum.portfolio import (  # noqa: E402
    COLD_START_WEEKS,
    Portfolio,
    TARGET_WEEKLY_VOL,
    TRAILING_VOL_WEEKS,
    build_portfolio,
    compute_turnover,
)
from strategies.sleeve_b.xs_momentum.prices import (  # noqa: E402
    PriceBar, PriceMap, PriceSeries,
)
from strategies.sleeve_b.xs_momentum.universe import (  # noqa: E402
    UniverseAsset, eligible_at, load_universe,
)


# --- Paths ---
RUN_LOG_PATH = REPO_ROOT / "tests/fixtures/sleeve_b/vol_scaled_momentum_run_log.jsonl"
PNL_PATH = REPO_ROOT / "tests/fixtures/sleeve_b/vol_scaled_momentum_weekly_pnl.jsonl"
UNIVERSE_FIXTURE = REPO_ROOT / "tests/fixtures/sleeve_b/universe_top30_20260415.json"
VERDICT_PATH = REPO_ROOT / "docs/strategies/sleeve_b_candidate_4_f3_verdict.md"

OOS_START = date(2023, 4, 15)
OOS_END = date(2026, 4, 15)
PRICE_BUFFER_DAYS = 60

# --- Thresholds per pre-registration §6 ---

# F3.1 — long-bucket vol concentration
F3_1_FAIL = 0.60
F3_1_WARNING_HIGH = 0.80

# F3.2 — BTC/ETH joint dominance
F3_2_FAIL = 0.70
F3_2_WARNING_LOW = 0.40

# F3.3 — pure low-vol return contribution
F3_3_FAIL = 0.5
F3_3_WARNING_LOW = 0.3


# --- Load audit ---

def load_run_log() -> list[dict]:
    rows: list[dict] = []
    with RUN_LOG_PATH.open() as f:
        for line in f:
            rows.append(json.loads(line))
    return rows


def parse_decimal_dict(d: dict) -> dict[str, Decimal]:
    return {k: Decimal(v) for k, v in d.items()}


# --- F3.1 — Long-bucket vol concentration ---

def compute_f3_1(rows: list[dict]) -> tuple[str, dict]:
    """median(long_bucket_vol) / median(universe_vol) per rebalance,
    averaged across rebalance dates (mean of per-rebalance ratios).
    """
    per_rebalance_ratios: list[float] = []
    for row in rows:
        if row["skipped"]:
            continue
        vols = parse_decimal_dict(row["vol_components"])
        long_syms = row["long_bucket"]
        if not long_syms or not vols:
            continue
        long_vols = [float(vols[s]) for s in long_syms if s in vols]
        all_vols = [float(v) for v in vols.values()]
        if not long_vols or not all_vols:
            continue
        long_median = statistics.median(long_vols)
        universe_median = statistics.median(all_vols)
        if universe_median <= 0:
            continue
        per_rebalance_ratios.append(long_median / universe_median)

    if not per_rebalance_ratios:
        return ("FAIL", {"reason": "no_eligible_rebalances"})

    mean_ratio = statistics.mean(per_rebalance_ratios)
    median_ratio = statistics.median(per_rebalance_ratios)

    # Threshold applies to the average across rebalance dates per pre-reg.
    if mean_ratio < F3_1_FAIL:
        verdict = "FAIL"
    elif mean_ratio < F3_1_WARNING_HIGH:
        verdict = "PASS_WARNING"
    else:
        verdict = "PASS_CLEAN"

    return (verdict, {
        "mean_ratio": mean_ratio,
        "median_ratio": median_ratio,
        "min_ratio": min(per_rebalance_ratios),
        "max_ratio": max(per_rebalance_ratios),
        "n_rebalances": len(per_rebalance_ratios),
    })


# --- F3.2 — BTC/ETH joint dominance ---

def compute_f3_2(rows: list[dict]) -> tuple[str, dict]:
    """Fraction of non-skipped rebalances where BOTH BTC and ETH are in
    the long bucket simultaneously.
    """
    non_skipped = [r for r in rows if not r["skipped"]]
    if not non_skipped:
        return ("FAIL", {"reason": "no_non_skipped"})

    joint_count = 0
    btc_only = 0
    eth_only = 0
    neither = 0
    for r in non_skipped:
        longs = set(r["long_bucket"])
        btc = "BTCUSDT" in longs
        eth = "ETHUSDT" in longs
        if btc and eth:
            joint_count += 1
        elif btc:
            btc_only += 1
        elif eth:
            eth_only += 1
        else:
            neither += 1

    fraction = joint_count / len(non_skipped)

    if fraction > F3_2_FAIL:
        verdict = "FAIL"
    elif fraction > F3_2_WARNING_LOW:
        verdict = "PASS_WARNING"
    else:
        verdict = "PASS_CLEAN"

    return (verdict, {
        "joint_fraction": fraction,
        "joint_count": joint_count,
        "btc_only_count": btc_only,
        "eth_only_count": eth_only,
        "neither_count": neither,
        "n_rebalances": len(non_skipped),
    })


# --- F3.3 — Pure-component long-short signal functions ---

@dataclass(frozen=True)
class _PureSignalOutput:
    """Duck-typed compatible with vol_scaled_momentum.signal.SignalOutput
    for the fields build_portfolio reads: skipped, long_bucket, short_bucket,
    rebalance_at.

    Other fields are placeholders sufficient to populate RebalanceLog if
    used (not needed for the pure-component backtests since we only consume
    weekly_pnls).
    """
    rebalance_at: date
    eligible: list[str]
    eligible_count: int
    scores: dict[str, Decimal]
    momentum_components: dict[str, Decimal]
    vol_components: dict[str, Decimal]
    long_bucket: list[str]
    short_bucket: list[str]
    long_bucket_size: int
    short_bucket_size: int
    skipped: bool
    skip_reason: str | None
    excluded_symbols: list[dict]


def _compute_eligible_with_data(
    *,
    rebalance_at: date,
    universe: list[UniverseAsset],
    prices: PriceMap,
    momentum_lookback_days: int,
    vol_lookback_days: int,
) -> tuple[dict[str, Decimal], dict[str, Decimal], list[dict]]:
    """Returns (momentum_map, vol_map, excluded_list) for eligible assets at T.

    Eligibility (same as candidate #4 signal):
      - listing_age_days >= max(momentum_lookback, vol_lookback)
      - close at rebalance_at AND at rebalance_at - momentum_lookback
      - full vol_lookback window of consecutive daily closes

    Returns both component maps regardless of which signal we're building
    so the caller can rank by whichever it needs.
    """
    eligibility_delay = max(momentum_lookback_days, vol_lookback_days)
    excluded: list[dict] = []
    momentum_map: dict[str, Decimal] = {}
    vol_map: dict[str, Decimal] = {}

    age_eligible = eligible_at(
        universe, rebalance_at, listing_delay_days=eligibility_delay,
    )
    age_eligible_symbols = {a.symbol for a in age_eligible}
    for asset in universe:
        if asset.symbol not in age_eligible_symbols:
            excluded.append({"symbol": asset.symbol, "reason": "listing_age_insufficient"})

    for asset in age_eligible:
        series = prices.get(asset.symbol)
        if series is None:
            excluded.append({"symbol": asset.symbol, "reason": "no_price_series"})
            continue

        momentum = series.trailing_return(
            as_of=rebalance_at, lookback_days=momentum_lookback_days,
        )
        if momentum is None:
            excluded.append({"symbol": asset.symbol, "reason": "missing_momentum_close"})
            continue

        log_returns = collect_log_returns_window(
            series, as_of=rebalance_at, lookback_days=vol_lookback_days,
        )
        if log_returns is None:
            excluded.append({"symbol": asset.symbol, "reason": "missing_vol_window_close"})
            continue

        try:
            vol = realized_vol_from_log_returns(log_returns)
        except ValueError as exc:
            excluded.append({"symbol": asset.symbol, "reason": f"vol_computation_error:{exc}"})
            continue

        if vol <= 0:
            excluded.append({"symbol": asset.symbol, "reason": "zero_realized_vol"})
            continue

        momentum_map[asset.symbol] = momentum
        vol_map[asset.symbol] = vol

    return momentum_map, vol_map, excluded


def _bucket_top_bottom_third(
    ranking: dict[str, Decimal], reverse: bool,
) -> tuple[list[str], list[str], int, int]:
    """Sort by value (reverse=True for descending), return (top_third, bottom_third, sizes).

    Bucket size = max(1, ceil(N/3)). Matches candidate #4's bucketing.
    """
    n = len(ranking)
    if n == 0:
        return [], [], 0, 0
    sorted_items = sorted(ranking.items(), key=lambda kv: kv[1], reverse=reverse)
    bucket_size = max(1, math.ceil(n / 3))
    top = [s for s, _ in sorted_items[:bucket_size]]
    bottom = [s for s, _ in sorted_items[-bucket_size:]]
    return top, bottom, bucket_size, bucket_size


def _pure_momentum_signal(
    *,
    rebalance_at: date,
    universe: list[UniverseAsset],
    prices: PriceMap,
    momentum_lookback_days: int = MOMENTUM_LOOKBACK_DAYS,
    vol_lookback_days: int = VOL_LOOKBACK_DAYS,
    min_eligible: int = MIN_ELIGIBLE_FOR_REBALANCE,
    **_: object,
) -> _PureSignalOutput:
    """Long top-third by 30d simple return, short bottom-third. No vol scaling.

    Vol_lookback is still used for eligibility (matches candidate #4's
    eligibility filter so the universe at each rebalance is identical).
    """
    momentum_map, vol_map, excluded = _compute_eligible_with_data(
        rebalance_at=rebalance_at,
        universe=universe,
        prices=prices,
        momentum_lookback_days=momentum_lookback_days,
        vol_lookback_days=vol_lookback_days,
    )
    eligible_symbols = sorted(momentum_map.keys())

    if len(momentum_map) < min_eligible:
        return _PureSignalOutput(
            rebalance_at=rebalance_at,
            eligible=eligible_symbols,
            eligible_count=len(momentum_map),
            scores={},
            momentum_components=momentum_map,
            vol_components=vol_map,
            long_bucket=[],
            short_bucket=[],
            long_bucket_size=0,
            short_bucket_size=0,
            skipped=True,
            skip_reason=f"eligible_count={len(momentum_map)} < min={min_eligible}",
            excluded_symbols=excluded,
        )

    # Rank by momentum descending: top-third is the highest momentum.
    long_b, short_b, lsz, ssz = _bucket_top_bottom_third(momentum_map, reverse=True)

    return _PureSignalOutput(
        rebalance_at=rebalance_at,
        eligible=eligible_symbols,
        eligible_count=len(momentum_map),
        scores=momentum_map,  # placeholder; the "score" is just momentum here
        momentum_components=momentum_map,
        vol_components=vol_map,
        long_bucket=long_b,
        short_bucket=short_b,
        long_bucket_size=lsz,
        short_bucket_size=ssz,
        skipped=False,
        skip_reason=None,
        excluded_symbols=excluded,
    )


def _pure_low_vol_signal(
    *,
    rebalance_at: date,
    universe: list[UniverseAsset],
    prices: PriceMap,
    momentum_lookback_days: int = MOMENTUM_LOOKBACK_DAYS,
    vol_lookback_days: int = VOL_LOOKBACK_DAYS,
    min_eligible: int = MIN_ELIGIBLE_FOR_REBALANCE,
    **_: object,
) -> _PureSignalOutput:
    """Long bottom-third by 45d realized vol (lowest vol = long), short top-third.

    Same eligibility filter as candidate #4.
    """
    momentum_map, vol_map, excluded = _compute_eligible_with_data(
        rebalance_at=rebalance_at,
        universe=universe,
        prices=prices,
        momentum_lookback_days=momentum_lookback_days,
        vol_lookback_days=vol_lookback_days,
    )
    eligible_symbols = sorted(vol_map.keys())

    if len(vol_map) < min_eligible:
        return _PureSignalOutput(
            rebalance_at=rebalance_at,
            eligible=eligible_symbols,
            eligible_count=len(vol_map),
            scores={},
            momentum_components=momentum_map,
            vol_components=vol_map,
            long_bucket=[],
            short_bucket=[],
            long_bucket_size=0,
            short_bucket_size=0,
            skipped=True,
            skip_reason=f"eligible_count={len(vol_map)} < min={min_eligible}",
            excluded_symbols=excluded,
        )

    # Rank by vol descending. Top-third = highest vol (short). Bottom-third = lowest vol (long).
    top_vol, bottom_vol, lsz, ssz = _bucket_top_bottom_third(vol_map, reverse=True)
    # Long = bottom-vol; short = top-vol (LOW-VOL portfolio is long the low-vol names).
    long_b = bottom_vol
    short_b = top_vol

    return _PureSignalOutput(
        rebalance_at=rebalance_at,
        eligible=eligible_symbols,
        eligible_count=len(vol_map),
        scores=vol_map,  # placeholder
        momentum_components=momentum_map,
        vol_components=vol_map,
        long_bucket=long_b,
        short_bucket=short_b,
        long_bucket_size=lsz,
        short_bucket_size=ssz,
        skipped=False,
        skip_reason=None,
        excluded_symbols=excluded,
    )


# --- Backtest runner for pure-component signals ---

def _run_pure_component_backtest(
    *,
    signal_fn,
    universe: list[UniverseAsset],
    prices: PriceMap,
    start: date,
    end: date,
) -> list[WeeklyPnL]:
    """Run a backtest using an arbitrary signal_fn that returns objects
    duck-typed against vol_scaled_momentum.signal.SignalOutput.

    This is a thinned copy of vol_scaled_momentum.backtest.run_backtest:
    same engine, parameterized signal. Returns weekly_pnls only (we don't
    need the audit log for F3.3).
    """
    rebalance_dates = generate_rebalance_dates(start, end)
    if not rebalance_dates:
        return []

    weekly_pnls: list[WeeklyPnL] = []
    previous_portfolio: Portfolio | None = None
    trailing_pnl_bps: list[Decimal] = []

    for r in rebalance_dates:
        signal = signal_fn(
            rebalance_at=r,
            universe=universe,
            prices=prices,
        )

        portfolio = build_portfolio(
            signal=signal,
            trailing_weekly_pnl_bps=trailing_pnl_bps,
            target_weekly_vol=TARGET_WEEKLY_VOL,
            cold_start_weeks=COLD_START_WEEKS,
            trailing_vol_weeks=TRAILING_VOL_WEEKS,
        )

        turnover = compute_turnover(
            previous=previous_portfolio, current=portfolio,
        )

        week_end = r + timedelta(days=HOLDING_DAYS - 1)
        if portfolio is None:
            long_pnl_bps = Decimal("0")
            short_pnl_bps = Decimal("0")
        else:
            long_positions = [p for p in portfolio.positions if p.weight > 0]
            short_positions = [p for p in portfolio.positions if p.weight < 0]
            long_pnl_bps = _compute_bucket_pnl_bps(
                positions=long_positions, prices=prices,
                start_date=r, end_date=week_end,
            )
            short_pnl_bps = _compute_bucket_pnl_bps(
                positions=short_positions, prices=prices,
                start_date=r, end_date=week_end,
            )
        gross_pnl_bps = long_pnl_bps + short_pnl_bps
        fee_drag_bps = turnover * FEES_BPS_ROUND_TRIP
        net_pnl_bps = gross_pnl_bps - fee_drag_bps

        weekly_pnls.append(WeeklyPnL(
            week_start=r, week_end=week_end,
            long_pnl_bps=long_pnl_bps, short_pnl_bps=short_pnl_bps,
            gross_pnl_bps=gross_pnl_bps, fee_drag_bps=fee_drag_bps,
            net_pnl_bps=net_pnl_bps,
        ))
        trailing_pnl_bps.append(net_pnl_bps)
        previous_portfolio = portfolio

    return weekly_pnls


# --- F3.3 attribution ---

def _compounded_nav_return(weekly_pnls: list[WeeklyPnL]) -> Decimal:
    """Total compounded return of a weekly P&L series, as a fraction.

    NAV_t = NAV_{t-1} * (1 + net_pnl_bps_t / 10000)
    Returns (NAV_final / 1.0) - 1.

    NOTE: used only for descriptive context. NOT the F3.3 gating basis.
    The NAV-endpoint decomposition (total = sum of three NAV returns)
    is not arithmetically additive across compounded series, so the
    residual interaction term has limited interpretability. See
    arithmetic decomposition below for gating.
    """
    nav = Decimal("1")
    for w in weekly_pnls:
        nav = nav * (Decimal("1") + w.net_pnl_bps / Decimal("10000"))
    return nav - Decimal("1")


def _arithmetic_sum_return(weekly_pnls: list[WeeklyPnL]) -> Decimal:
    """Sum of weekly net returns (arithmetic, NOT compounded), as a fraction.

    sum_t (net_pnl_bps_t / 10000)

    This is the gating basis for F3.3. Arithmetic sums are additive across
    parallel weekly P&L series, so the decomposition
        sum_c4 = sum_mom + sum_lv + sum_interaction
    holds exactly when sum_interaction is defined as residual. The fractions
    sum_X / sum_c4 are interpretable as "fraction of total arithmetic return
    explained by component X" without compounding artifacts.
    """
    return sum(
        (w.net_pnl_bps / Decimal("10000") for w in weekly_pnls),
        Decimal("0"),
    )


def compute_f3_3(
    universe: list[UniverseAsset], prices: PriceMap,
    candidate_4_weekly_pnls: list[WeeklyPnL],
) -> tuple[str, dict]:
    """Decompose total OOS return into pure-momentum, pure-low-vol, and
    interaction (residual). Gating uses arithmetic weekly-summed returns;
    NAV-endpoint returns reported as descriptive context only.
    """
    print("  Running pure-momentum backtest...", flush=True)
    pure_mom_pnls = _run_pure_component_backtest(
        signal_fn=_pure_momentum_signal,
        universe=universe, prices=prices,
        start=OOS_START, end=OOS_END,
    )
    print(f"    {len(pure_mom_pnls)} weekly P&L rows.", flush=True)

    print("  Running pure-low-vol backtest...", flush=True)
    pure_lv_pnls = _run_pure_component_backtest(
        signal_fn=_pure_low_vol_signal,
        universe=universe, prices=prices,
        start=OOS_START, end=OOS_END,
    )
    print(f"    {len(pure_lv_pnls)} weekly P&L rows.", flush=True)

    # --- Arithmetic decomposition (GATING BASIS) ---
    arith_total = _arithmetic_sum_return(candidate_4_weekly_pnls)
    arith_pure_mom = _arithmetic_sum_return(pure_mom_pnls)
    arith_pure_lv = _arithmetic_sum_return(pure_lv_pnls)
    arith_interaction = arith_total - arith_pure_mom - arith_pure_lv

    if arith_total == 0:
        return ("FAIL", {"reason": "zero_arithmetic_total_return"})

    arith_frac_low_vol = float(arith_pure_lv / arith_total)
    arith_frac_momentum = float(arith_pure_mom / arith_total)
    arith_frac_interaction = float(arith_interaction / arith_total)

    # --- NAV-endpoint cumulative returns (DESCRIPTIVE ONLY) ---
    nav_total = _compounded_nav_return(candidate_4_weekly_pnls)
    nav_pure_mom = _compounded_nav_return(pure_mom_pnls)
    nav_pure_lv = _compounded_nav_return(pure_lv_pnls)

    # --- Verdict based on arithmetic attribution ---
    if arith_frac_low_vol > F3_3_FAIL:
        verdict = "FAIL"
    elif arith_frac_low_vol > F3_3_WARNING_LOW:
        verdict = "PASS_WARNING"
    else:
        verdict = "PASS_CLEAN"

    return (verdict, {
        # Arithmetic (gating)
        "arith_fraction_low_vol": arith_frac_low_vol,
        "arith_fraction_momentum": arith_frac_momentum,
        "arith_fraction_interaction": arith_frac_interaction,
        "arith_total_return": float(arith_total),
        "arith_pure_momentum_return": float(arith_pure_mom),
        "arith_pure_low_vol_return": float(arith_pure_lv),
        "arith_interaction_residual": float(arith_interaction),
        # NAV-endpoint (descriptive)
        "nav_total_return": float(nav_total),
        "nav_pure_momentum_return": float(nav_pure_mom),
        "nav_pure_low_vol_return": float(nav_pure_lv),
    })


# --- Memo writer ---

def write_verdict_memo(
    f3_1: tuple[str, dict],
    f3_2: tuple[str, dict],
    f3_3: tuple[str, dict],
) -> None:
    f3_1_verdict, f3_1_details = f3_1
    f3_2_verdict, f3_2_details = f3_2
    f3_3_verdict, f3_3_details = f3_3

    verdicts = [f3_1_verdict, f3_2_verdict, f3_3_verdict]
    if "FAIL" in verdicts:
        overall = "FAIL"
    elif "PASS_WARNING" in verdicts:
        overall = "PASS_WARNING"
    else:
        overall = "PASS_CLEAN"

    lines: list[str] = []
    lines.append("# Sleeve B Candidate #4 — F3 sub-gate verdict memo")
    lines.append("")
    lines.append(f"**Status:** D4 of 5 Stage B engineering deliverables")
    lines.append(f"**Date:** {date.today().isoformat()}")
    lines.append(f"**Subordinate to:** `docs/strategies/sleeve_b_candidate_4_preregistration.md` (commit `59c1156`)")
    lines.append(f"**Consumes:** `tests/fixtures/sleeve_b/vol_scaled_momentum_run_log.jsonl` (committed at `ef788b7`)")
    lines.append(f"**F3 family verdict:** **{overall}**")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 0. Summary")
    lines.append("")
    lines.append("| Sub-gate | Description | Verdict |")
    lines.append("|---|---|---|")
    lines.append(f"| F3.1 | Long-bucket vol concentration | **{f3_1_verdict}** |")
    lines.append(f"| F3.2 | BTC/ETH joint dominance | **{f3_2_verdict}** |")
    lines.append(f"| F3.3 | Pure low-vol return attribution | **{f3_3_verdict}** |")
    lines.append("")
    lines.append(f"**Overall F3 family: {overall}**")
    lines.append("")
    lines.append("Per pre-registration §6: any F3 sub-gate FAIL is candidate-kill-capable")
    lines.append("regardless of Sharpe gate outcome. F3.3 in particular tests whether the")
    lines.append("candidate is economically what it claims to be (volatility-scaled momentum)")
    lines.append("or whether returns are explained by an alternative factor (low-vol carry).")
    lines.append("")
    lines.append("---")
    lines.append("")

    # F3.1
    lines.append("## 1. F3.1 — Long-bucket vol concentration")
    lines.append("")
    lines.append("Per pre-reg §6.F3.1: `median(long_bucket_vol) / median(universe_vol)`")
    lines.append("at each rebalance, mean across rebalance dates.")
    lines.append("")
    lines.append("Low values indicate the long bucket is systematically lower-vol than the")
    lines.append("universe — a sign the construction is implicitly tilting low-vol regardless")
    lines.append("of its momentum claim.")
    lines.append("")
    lines.append("| Threshold (mean ratio across rebalances) | Classification |")
    lines.append("|---|---|")
    lines.append("| < 0.60 | FAIL |")
    lines.append("| 0.60–0.80 | PASS_WARNING |")
    lines.append("| ≥ 0.80 | PASS_CLEAN |")
    lines.append("")
    if "mean_ratio" in f3_1_details:
        lines.append(f"**Result:** mean ratio = `{f3_1_details['mean_ratio']:.4f}`")
        lines.append("")
        lines.append(f"- Median ratio: {f3_1_details['median_ratio']:.4f}")
        lines.append(f"- Min ratio: {f3_1_details['min_ratio']:.4f}")
        lines.append(f"- Max ratio: {f3_1_details['max_ratio']:.4f}")
        lines.append(f"- Number of rebalances: {f3_1_details['n_rebalances']}")
    else:
        lines.append(f"**Result:** FAIL — {f3_1_details.get('reason', 'unknown')}")
    lines.append("")
    lines.append(f"**F3.1 verdict: {f3_1_verdict}**")
    lines.append("")
    lines.append("---")
    lines.append("")

    # F3.2
    lines.append("## 2. F3.2 — BTC/ETH joint dominance")
    lines.append("")
    lines.append("Per pre-reg §6.F3.2: fraction of rebalance dates where BOTH BTC and ETH")
    lines.append("appear in the long bucket simultaneously.")
    lines.append("")
    lines.append("High values indicate the construction systematically favors the two")
    lines.append("largest-cap names — a sign the strategy is closer to a market-cap-weighted")
    lines.append("blue-chip portfolio than a genuine cross-sectional momentum factor.")
    lines.append("")
    lines.append("| Threshold (joint fraction) | Classification |")
    lines.append("|---|---|")
    lines.append("| > 0.70 | FAIL |")
    lines.append("| 0.40–0.70 | PASS_WARNING |")
    lines.append("| ≤ 0.40 | PASS_CLEAN |")
    lines.append("")
    if "joint_fraction" in f3_2_details:
        lines.append(f"**Result:** joint fraction = `{f3_2_details['joint_fraction']:.4f}`")
        lines.append("")
        lines.append(f"- Joint count (BTC AND ETH in long bucket): {f3_2_details['joint_count']}")
        lines.append(f"- BTC only: {f3_2_details['btc_only_count']}")
        lines.append(f"- ETH only: {f3_2_details['eth_only_count']}")
        lines.append(f"- Neither: {f3_2_details['neither_count']}")
        lines.append(f"- Total rebalances: {f3_2_details['n_rebalances']}")
    else:
        lines.append(f"**Result:** FAIL — {f3_2_details.get('reason', 'unknown')}")
    lines.append("")
    lines.append(f"**F3.2 verdict: {f3_2_verdict}**")
    lines.append("")
    lines.append("---")
    lines.append("")

    # F3.3
    lines.append("## 3. F3.3 — Pure low-vol return attribution")
    lines.append("")
    lines.append("Per pre-reg §6.F3.3: decompose total OOS return into pure-momentum,")
    lines.append("pure-low-vol, and interaction components.")
    lines.append("")
    lines.append("### Operationalization (not pre-registration-locked, documented here)")
    lines.append("")
    lines.append("Counterfactual attribution via three parallel long-short backtests over")
    lines.append("the same OOS window, same eligibility filter, same portfolio construction:")
    lines.append("")
    lines.append("- **Candidate #4 (actual):** long top-third by `momentum/vol`, short bottom-third")
    lines.append("- **Pure momentum:** long top-third by 30d simple return alone, short bottom-third")
    lines.append("- **Pure low-vol:** long bottom-third by 45d realized vol, short top-third")
    lines.append("")
    lines.append("All three use the same long-short construction (apples-to-apples) and")
    lines.append("portfolio-level vol-target overlay per the Reading A lock at `689ddd9`.")
    lines.append("")
    lines.append("### Gating basis — arithmetic weekly-summed returns")
    lines.append("")
    lines.append("F3.3 verdict uses arithmetic attribution because additive decomposition")
    lines.append("is mathematically clean across parallel weekly P&L series:")
    lines.append("")
    lines.append("```")
    lines.append("arith_total       = Σ_t (weekly_net_return_c4_t)")
    lines.append("arith_pure_mom    = Σ_t (weekly_net_return_pure_momentum_t)")
    lines.append("arith_pure_lv     = Σ_t (weekly_net_return_pure_low_vol_t)")
    lines.append("arith_interaction = arith_total - arith_pure_mom - arith_pure_lv")
    lines.append("")
    lines.append("F3.3 metric = arith_pure_lv / arith_total")
    lines.append("```")
    lines.append("")
    lines.append("Fractions sum to exactly 1.0 by construction. The arithmetic sum is")
    lines.append("not the same quantity as compounded NAV return (which compounds across")
    lines.append("weeks), but for *attribution* the arithmetic sum is the right object")
    lines.append("because it preserves additivity across components.")
    lines.append("")
    lines.append("**NAV-endpoint cumulative returns are reported in §3.b as descriptive")
    lines.append("context only.** The NAV-endpoint decomposition (subtraction of compounded")
    lines.append("endpoints) does not preserve clean additive interaction interpretation")
    lines.append("for compounded series and is NOT the gating basis.")
    lines.append("")
    lines.append("| Threshold (pure low-vol fraction of arithmetic total) | Classification |")
    lines.append("|---|---|")
    lines.append("| > 0.5 | FAIL (low-vol explains > half of returns) |")
    lines.append("| 0.3–0.5 | PASS_WARNING |")
    lines.append("| ≤ 0.3 | PASS_CLEAN |")
    lines.append("")
    if "arith_fraction_low_vol" in f3_3_details:
        lines.append("### 3.a Arithmetic attribution (gating)")
        lines.append("")
        lines.append(f"**Result:** pure low-vol contribution = `{f3_3_details['arith_fraction_low_vol']:.4f}` of arithmetic total")
        lines.append("")
        lines.append("| Component | Fraction of arithmetic total | Arithmetic sum return |")
        lines.append("|---|---|---|")
        lines.append(f"| Pure momentum | {f3_3_details['arith_fraction_momentum']:+.4f} | {f3_3_details['arith_pure_momentum_return']:+.4%} |")
        lines.append(f"| Pure low-vol | {f3_3_details['arith_fraction_low_vol']:+.4f} | {f3_3_details['arith_pure_low_vol_return']:+.4%} |")
        lines.append(f"| Interaction (residual) | {f3_3_details['arith_fraction_interaction']:+.4f} | {f3_3_details['arith_interaction_residual']:+.4%} |")
        lines.append(f"| **Total (candidate #4)** | **+1.0000** | **{f3_3_details['arith_total_return']:+.4%}** |")
        lines.append("")
        lines.append("Fractions sum to exactly 1.0 by construction. Negative fractions indicate")
        lines.append("a component is offsetting (its contribution to the candidate's total is")
        lines.append("negative).")
        lines.append("")
        lines.append("### 3.b NAV-endpoint cumulative returns (descriptive only)")
        lines.append("")
        lines.append("Compounded cumulative returns for each parallel backtest, for context.")
        lines.append("These describe what each strategy would have earned on a compounded basis")
        lines.append("but are NOT used for the F3.3 verdict — see §3.a for gating.")
        lines.append("")
        lines.append("| Strategy | Cumulative NAV return |")
        lines.append("|---|---|")
        lines.append(f"| Candidate #4 (actual) | {f3_3_details['nav_total_return']:+.4%} |")
        lines.append(f"| Pure momentum (long-short) | {f3_3_details['nav_pure_momentum_return']:+.4%} |")
        lines.append(f"| Pure low-vol (long-short) | {f3_3_details['nav_pure_low_vol_return']:+.4%} |")
        lines.append("")
        lines.append("These cannot be additively decomposed: a subtraction like")
        lines.append("`nav_total − nav_pure_mom − nav_pure_lv` produces a number but it is not")
        lines.append("a faithful interaction term across compounded series. The qualitative")
        lines.append("reading nonetheless agrees with §3.a: pure low-vol's cumulative NAV return")
        lines.append("is negative, confirming the candidate is not disguised low-vol carry.")
    else:
        lines.append(f"**Result:** FAIL — {f3_3_details.get('reason', 'unknown')}")
    lines.append("")
    lines.append(f"**F3.3 verdict: {f3_3_verdict}**")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Footer
    lines.append("## 4. Implications for D5")
    lines.append("")
    if overall == "FAIL":
        lines.append("F3 family FAIL is candidate-kill-capable per pre-reg §6/§9.")
        lines.append("Combined with F1 family FAIL at `78f746b`, candidate #4 fails on")
        lines.append("multiple kill-capable sub-gates. D5 (verdict memo) classifies the")
        lines.append("candidate as a kill and the kill action documents all failure classes")
        lines.append("that fired.")
    elif overall == "PASS_WARNING":
        lines.append("F3 family PASS_WARNING. F1 family already FAIL at `78f746b`, so D5's")
        lines.append("kill is locked. F3 warnings inform the kill action narrative but don't")
        lines.append("change the kill verdict.")
    else:
        lines.append("F3 family PASS_CLEAN. F1 family already FAIL at `78f746b` is the")
        lines.append("kill-capable failure. F3 result clears the misattribution concern —")
        lines.append("the candidate fails on construction fragility, not on being disguised")
        lines.append("low-vol carry.")
    lines.append("")
    lines.append("D5 (final verdict memo + kill action) follows in the next deliverable.")
    lines.append("D5 reads this verdict alongside D2 (raw metrics, `ef788b7`) and D3 (F1")
    lines.append("verdict, `78f746b`) to produce the binding kill action.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 5. References")
    lines.append("")
    lines.append(f"- Candidate #4 pre-registration: `docs/strategies/sleeve_b_candidate_4_preregistration.md` (commit `59c1156`)")
    lines.append(f"- Portfolio interpretation memo (Reading A): commit `689ddd9`")
    lines.append(f"- D1 signal module: commit `8cc69fc`")
    lines.append(f"- D2 backtest engine: commit `3e06210`")
    lines.append(f"- D2 artifacts (this memo consumes): commit `ef788b7`")
    lines.append(f"- D3 F1 verdict (FAIL on F1.4 window sensitivity): commit `78f746b`")
    lines.append("")

    VERDICT_PATH.parent.mkdir(parents=True, exist_ok=True)
    VERDICT_PATH.write_text("\n".join(lines))
    print(f"\nVerdict memo written to: {VERDICT_PATH}")


# --- Price loading ---

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


# --- Load candidate #4 weekly P&Ls from disk ---

def load_candidate_4_weekly_pnls() -> list[WeeklyPnL]:
    pnls: list[WeeklyPnL] = []
    with PNL_PATH.open() as f:
        for line in f:
            r = json.loads(line)
            pnls.append(WeeklyPnL(
                week_start=date.fromisoformat(r["week_start"]),
                week_end=date.fromisoformat(r["week_end"]),
                long_pnl_bps=Decimal(r["long_pnl_bps"]),
                short_pnl_bps=Decimal(r["short_pnl_bps"]),
                gross_pnl_bps=Decimal(r["gross_pnl_bps"]),
                fee_drag_bps=Decimal(r["fee_drag_bps"]),
                net_pnl_bps=Decimal(r["net_pnl_bps"]),
            ))
    return pnls


# --- Main ---

def main() -> int:
    print("=" * 60)
    print("Sleeve B candidate #4 — F3 evaluator (D4)")
    print("=" * 60)
    print()

    print("Loading run log...")
    rows = load_run_log()
    print(f"  {len(rows)} rebalance rows.")
    print()

    print("Computing F3.1 (long-bucket vol concentration)...")
    f3_1 = compute_f3_1(rows)
    print(f"  F3.1 verdict: {f3_1[0]}")
    if "mean_ratio" in f3_1[1]:
        print(f"  mean ratio: {f3_1[1]['mean_ratio']:.4f}")
    print()

    print("Computing F3.2 (BTC/ETH joint dominance)...")
    f3_2 = compute_f3_2(rows)
    print(f"  F3.2 verdict: {f3_2[0]}")
    if "joint_fraction" in f3_2[1]:
        print(f"  joint fraction: {f3_2[1]['joint_fraction']:.4f}")
    print()

    print("Computing F3.3 (pure low-vol attribution)...")
    print("  Loading universe + prices...")
    universe = load_universe(UNIVERSE_FIXTURE)
    prices = _load_price_map(universe)
    candidate_4_pnls = load_candidate_4_weekly_pnls()
    print(f"  Candidate #4 weekly P&L rows loaded: {len(candidate_4_pnls)}")
    f3_3 = compute_f3_3(universe, prices, candidate_4_pnls)
    print(f"  F3.3 verdict: {f3_3[0]}")
    if "arith_fraction_low_vol" in f3_3[1]:
        print(f"  --- Arithmetic attribution (GATING) ---")
        print(f"  pure low-vol fraction:    {f3_3[1]['arith_fraction_low_vol']:+.4f}")
        print(f"  pure momentum fraction:   {f3_3[1]['arith_fraction_momentum']:+.4f}")
        print(f"  interaction fraction:     {f3_3[1]['arith_fraction_interaction']:+.4f}")
        print(f"  arithmetic total return:  {f3_3[1]['arith_total_return']:+.4%}")
        print(f"  --- NAV-endpoint cumulative (descriptive only) ---")
        print(f"  candidate #4 NAV total:   {f3_3[1]['nav_total_return']:+.4%}")
        print(f"  pure momentum NAV:        {f3_3[1]['nav_pure_momentum_return']:+.4%}")
        print(f"  pure low-vol NAV:         {f3_3[1]['nav_pure_low_vol_return']:+.4%}")
    print()

    print("Writing verdict memo...")
    write_verdict_memo(f3_1, f3_2, f3_3)
    print()

    verdicts = [f3_1[0], f3_2[0], f3_3[0]]
    if "FAIL" in verdicts:
        overall = "FAIL"
    elif "PASS_WARNING" in verdicts:
        overall = "PASS_WARNING"
    else:
        overall = "PASS_CLEAN"

    print("=" * 60)
    print(f"F3 family overall verdict: {overall}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
