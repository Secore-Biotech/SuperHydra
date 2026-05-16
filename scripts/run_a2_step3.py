#!/usr/bin/env python3
"""Step 3: A2 basis strategy normal-regime validation test.

Per docs/strategies/a2_step3_preregistration.md (committed before this run).

Hard constraints:
  - Real Binance trade fetcher REQUIRED (A2DualFetcher wrapping perp +
    spot archive fetchers).
  - --allow-noop-fetcher is INVALID. No such flag exists on this script.
  - Window: 2023-10-01T00:00:00Z → 2023-10-15T00:00:00Z. Hardcoded.
  - Cost assumption: Binance perp taker 4.5 bps + spot taker 10.0 bps =
    14.5 bps round-trip fees, applied independently of observed slippage.
  - Per-trade P&L: gross - 14.5 - observed_slippage. The runner's
    embedded research_pnl_bps (which uses the 33.84 bps threshold
    including 20% safety margin) is explicitly NOT used.
  - If 0 entries fire, write kill memo and exit successfully.
  - If entries fire but all observed_slippage_bps are NULL, refuse
    headline net P&L; mark memo non-decision-grade.

Reproducibility: fixed RUN_ID ("step3_sol_2023_10_01_15_v1") so re-running
produces identical UUIDs and the script's paper.fills writes are
silently idempotent (hash-match no-op on second run).

Usage:
  python3 scripts/run_a2_step3.py
"""
from __future__ import annotations

import os
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import psycopg

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from strategies.a2_basis.runner.paper_research_runner import (  # noqa: E402
    A2PaperResearchRunner,
    load_basis_fixture,
)
from strategies.a2_basis.data.dual_fetcher import A2DualFetcher  # noqa: E402
from data.ingestion.vendors.binance.archive_trade_fetcher import (  # noqa: E402
    BinanceArchiveTradeFetcher,
)
from data.ingestion.vendors.binance.spot_archive_trade_fetcher import (  # noqa: E402
    BinanceSpotArchiveTradeFetcher,
)

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://superhydra:superhydra_dev_only@localhost:5432/superhydra",
)

FIXTURE_PATH = (
    REPO_ROOT
    / "tests/fixtures/a2_basis/SOLUSDT_basis_14d_20231001T000000_20231015T000000.json"
)
MEMO_PATH = REPO_ROOT / "docs/strategies/a2_step3_result.md"
PREREG_PATH = REPO_ROOT / "docs/strategies/a2_step3_preregistration.md"

# Pre-registered constants
WINDOW_START = "2023-10-01T00:00:00Z"
WINDOW_END = "2023-10-15T00:00:00Z"
FEES_BPS = Decimal("14.5")  # 4.5 perp + 10.0 spot taker, round-trip
RUN_ID = "step3_sol_2023_10_01_15_v1"

# Sep 2021 stress window (per pre-registration cross-reference requirement)
SEP_2021_STRESS_START = datetime(2021, 9, 1, 0, 0, tzinfo=timezone.utc)
SEP_2021_STRESS_END = datetime(2021, 9, 15, 0, 0, tzinfo=timezone.utc)

# Stable bootstrap identifiers (distinct from empirical_a2_complete_trade_results)
VENUE_CODE = "binance"
STRATEGY_NAME = "a2_basis_step3"
PORTFOLIO_CODE = "a2_step3"
ACCOUNT_CODE = "a2_step3_acct"
PERP_INSTRUMENT_CODE = "SOLUSDT_PERP_step3"
SPOT_INSTRUMENT_CODE = "SOLUSDT_SPOT_step3"


def _connect():
    return psycopg.connect(DATABASE_URL)


def _alembic_upgrade_head() -> None:
    r = subprocess.run(
        [
            "alembic", "-c", "infra/migrations/alembic.ini",
            "upgrade", "head",
        ],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    if r.returncode != 0:
        print("ERROR: alembic upgrade head failed:")
        print(r.stdout); print(r.stderr)
        sys.exit(r.returncode)


def _get_or_create_venue(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM registry.venues WHERE venue_code = %s;",
            (VENUE_CODE,),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute(
            """
            INSERT INTO registry.venues
                (venue_code, display_name, venue_type, status)
            VALUES (%s, 'Binance', 'cex_futures', 'active')
            RETURNING id;
            """,
            (VENUE_CODE,),
        )
        return cur.fetchone()[0]


def _get_or_create_asset(conn, symbol, asset_type, decimals, display_name):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM registry.assets WHERE symbol = %s "
            "AND chain IS NULL AND contract_address IS NULL;",
            (symbol,),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute(
            """
            INSERT INTO registry.assets
                (symbol, display_name, asset_type, decimals, status)
            VALUES (%s, %s, %s, %s, 'active')
            RETURNING id;
            """,
            (symbol, display_name, asset_type, decimals),
        )
        return cur.fetchone()[0]


def _get_or_create_strategy(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM registry.strategies WHERE name = %s;",
            (STRATEGY_NAME,),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute(
            """
            INSERT INTO registry.strategies
                (name, display_name, current_phase, phase_entered_at,
                 hypothesis_doc_path, config)
            VALUES (%s, 'A2 Basis Step 3', 'research', NOW(),
                    'docs/strategies/a2_basis_design_brief.md', '{}'::jsonb)
            RETURNING id;
            """,
            (STRATEGY_NAME,),
        )
        return cur.fetchone()[0]


def _get_or_create_portfolio(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM registry.portfolios WHERE portfolio_code = %s;",
            (PORTFOLIO_CODE,),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute(
            """
            INSERT INTO registry.portfolios
                (portfolio_code, display_name, product_type, status)
            VALUES (%s, 'A2 Step 3', 'paper', 'research')
            RETURNING id;
            """,
            (PORTFOLIO_CODE,),
        )
        return cur.fetchone()[0]


def _get_or_create_account(conn, venue_id) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM registry.accounts WHERE venue_id = %s "
            "AND account_code = %s;",
            (venue_id, ACCOUNT_CODE),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute(
            """
            INSERT INTO registry.accounts
                (venue_id, account_code, display_name, account_type, status)
            VALUES (%s, %s, 'A2 Step 3 Acct', 'trading', 'active')
            RETURNING id;
            """,
            (venue_id, ACCOUNT_CODE),
        )
        return cur.fetchone()[0]


def _get_or_create_instrument(conn, *, code, display_name, venue_id,
                              base_asset_id, quote_asset_id,
                              instrument_type) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM registry.instruments WHERE instrument_code = %s;",
            (code,),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute(
            """
            INSERT INTO registry.instruments
                (instrument_code, display_name, venue_id, base_asset_id,
                 quote_asset_id, instrument_type, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'active')
            RETURNING id;
            """,
            (code, display_name, venue_id, base_asset_id,
             quote_asset_id, instrument_type),
        )
        return cur.fetchone()[0]


def _bootstrap_registry(conn) -> dict:
    venue_id = _get_or_create_venue(conn)
    sol_id = _get_or_create_asset(conn, "SOL", "crypto", 9, "Solana")
    usdt_id = _get_or_create_asset(conn, "USDT", "stablecoin", 6, "Tether USD")
    strategy_id = _get_or_create_strategy(conn)
    portfolio_id = _get_or_create_portfolio(conn)
    account_id = _get_or_create_account(conn, venue_id)
    perp_id = _get_or_create_instrument(
        conn, code=PERP_INSTRUMENT_CODE,
        display_name="SOLUSDT Perp (Step 3)",
        venue_id=venue_id, base_asset_id=sol_id,
        quote_asset_id=usdt_id, instrument_type="perp",
    )
    spot_id = _get_or_create_instrument(
        conn, code=SPOT_INSTRUMENT_CODE,
        display_name="SOLUSDT Spot (Step 3)",
        venue_id=venue_id, base_asset_id=sol_id,
        quote_asset_id=usdt_id, instrument_type="spot",
    )
    return {
        "venue_id": venue_id, "strategy_id": strategy_id,
        "portfolio_id": portfolio_id, "account_id": account_id,
        "perp_id": perp_id, "spot_id": spot_id,
    }


def _wipe_paper(conn, strategy_id) -> None:
    """Wipe paper.fills + paper.positions for this strategy."""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM paper.fills WHERE strategy_id = %s;",
            (strategy_id,),
        )
        cur.execute(
            "DELETE FROM paper.positions WHERE strategy_id = %s;",
            (strategy_id,),
        )


def _build_real_fetcher():
    """Build the REAL Binance trade fetcher per Step 3 hard constraint.

    No NoopFetcher. No CLI flag to override. The fetcher class is
    constructed inline so it cannot be swapped at runtime without
    editing source code.
    """
    perp = BinanceArchiveTradeFetcher()
    spot = BinanceSpotArchiveTradeFetcher()
    return A2DualFetcher(
        perp_fetcher=perp,
        spot_fetcher=spot,
        perp_symbol="SOLUSDT_PERP",
        spot_symbol="SOLUSDT_SPOT",
        base_symbol="SOLUSDT",
    )


def _run_a2(conn, ids, fetcher):
    observations = load_basis_fixture(FIXTURE_PATH)
    runner = A2PaperResearchRunner(
        basis_source=observations,
        trade_fetcher=fetcher,
        fetch_source="archive",
        strategy_id=ids["strategy_id"],
        portfolio_id=ids["portfolio_id"],
        account_id=ids["account_id"],
        perp_instrument_id=ids["perp_id"],
        spot_instrument_id=ids["spot_id"],
        venue="binance",
        base_symbol="SOLUSDT",
        quantity_per_intent=Decimal("10.0"),
        run_id=RUN_ID,
    )
    summary = runner.run(conn)
    conn.commit()
    return summary


def _query_trades(conn, strategy_id):
    """Query paper.fills and group into complete trades by a2_intent_uuid.

    Returns list of trade dicts; each trade has 4 fills (entry perp,
    entry spot, exit perp, exit spot). Incomplete trades (entry only,
    no exit) are excluded from the trade list but counted separately.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                metadata->>'a2_intent_uuid' AS intent_uuid,
                metadata->>'a2_phase' AS phase,
                metadata->>'a2_leg' AS leg,
                price,
                observed_slippage_bps,
                filled_at,
                metadata
            FROM paper.fills
            WHERE strategy_id = %s
              AND metadata->>'empirical_run_id' = %s
            ORDER BY filled_at, metadata->>'a2_intent_uuid';
            """,
            (strategy_id, RUN_ID),
        )
        rows = cur.fetchall()

    trades_by_uuid = {}
    for intent_uuid, phase, leg, price, slip, filled_at, meta in rows:
        if intent_uuid not in trades_by_uuid:
            trades_by_uuid[intent_uuid] = {"intent_uuid": intent_uuid}
        key = f"{phase}_{leg}"
        trades_by_uuid[intent_uuid][key] = {
            "price": price,
            "slippage_bps": slip,
            "filled_at": filled_at,
            "metadata": meta,
        }

    required_keys = {"entry_perp", "entry_spot", "exit_perp", "exit_spot"}
    complete = [
        t for t in trades_by_uuid.values()
        if required_keys.issubset(set(t.keys()))
    ]
    incomplete_count = len(trades_by_uuid) - len(complete)
    return complete, len(rows), incomplete_count


def _compute_trade_pnl(trade):
    """Recompute P&L from scratch per Step 3 pre-registered formula.

    gross_pnl_bps  = profit-positive sum across legs (from runner-computed
                     research_perp_pnl_bps + research_spot_pnl_bps)
    fees_bps       = 14.5 (constant, pre-registered)
    slippage_bps   = sum of observed_slippage_bps across all 4 fills
    net_pnl_bps    = gross - fees - slippage

    If ANY of the 4 fills has slippage_bps NULL, net is None and the
    trade is non-decision-grade for this run.

    Returns dict with all components plus a slippage_complete flag.
    """
    exit_perp_meta = trade["exit_perp"]["metadata"]
    perp_pnl = Decimal(exit_perp_meta["research_perp_pnl_bps"])
    spot_pnl = Decimal(exit_perp_meta["research_spot_pnl_bps"])
    gross_pnl_bps = Decimal(exit_perp_meta["research_gross_pnl_bps"])

    slippages = []
    for key in ("entry_perp", "entry_spot", "exit_perp", "exit_spot"):
        slip = trade[key]["slippage_bps"]
        slippages.append(slip)

    slippage_complete = all(s is not None for s in slippages)
    if slippage_complete:
        total_slippage = sum(slippages)
        net_pnl_bps = gross_pnl_bps - FEES_BPS - total_slippage
    else:
        total_slippage = None
        net_pnl_bps = None

    return {
        "perp_pnl_bps": perp_pnl,
        "spot_pnl_bps": spot_pnl,
        "gross_pnl_bps": gross_pnl_bps,
        "fees_bps": FEES_BPS,
        "slippage_bps_total": total_slippage,
        "slippage_complete": slippage_complete,
        "net_pnl_bps": net_pnl_bps,
        "holding_duration_seconds": int(exit_perp_meta["a2_holding_duration_seconds"]),
        "exit_reason": exit_perp_meta["a2_exit_reason"],
        "entry_filled_at": trade["entry_perp"]["filled_at"],
        "exit_filled_at": trade["exit_perp"]["filled_at"],
        "entry_perp_price": trade["entry_perp"]["price"],
        "entry_spot_price": trade["entry_spot"]["price"],
        "exit_perp_price": trade["exit_perp"]["price"],
        "exit_spot_price": trade["exit_spot"]["price"],
        "entry_perp_slip": trade["entry_perp"]["slippage_bps"],
        "entry_spot_slip": trade["entry_spot"]["slippage_bps"],
        "exit_perp_slip": trade["exit_perp"]["slippage_bps"],
        "exit_spot_slip": trade["exit_spot"]["slippage_bps"],
    }


def _check_sep_2021_overlap(complete_trades):
    """Pre-registration requires confirming no fill in Sep 2021 stress window."""
    overlapping = []
    for trade in complete_trades:
        for key in ("entry_perp", "entry_spot", "exit_perp", "exit_spot"):
            filled_at = trade[key]["filled_at"]
            if (SEP_2021_STRESS_START <= filled_at < SEP_2021_STRESS_END):
                overlapping.append(filled_at)
    return overlapping


def _apply_kill_criterion(n_entries, computable_trades):
    """Map (n_entries, mean_net) to the pre-registered decision table.

    Returns (criterion_label, decision_text).
    """
    if n_entries == 0:
        return (
            "0 entries fired",
            "Strategy is purely a stress-event harvester. Recommend "
            "pivot to a different signal family or shelve A2.",
        )
    if not computable_trades:
        # Entries fired but no trades have computable net P&L
        return (
            f"{n_entries} entries fired but slippage unavailable for all trades",
            "NON-DECISION-GRADE. Per pre-registration extra requirement: "
            "refuse to produce headline net P&L. Investigate fetcher/"
            "replay path before any decision.",
        )

    nets = [t["net_pnl_bps"] for t in computable_trades]
    mean_net = sum(nets) / Decimal(len(nets))
    n_computable = len(computable_trades)

    if 1 <= n_computable <= 3:
        if mean_net <= 0:
            return (
                f"{n_computable} entries with mean net P&L "
                f"{float(mean_net):.2f} bps (≤ 0)",
                "No normal-regime edge demonstrated. Recommend pivot "
                "or shelving.",
            )
        else:
            return (
                f"{n_computable} entries with mean net P&L "
                f"{float(mean_net):.2f} bps (> 0)",
                "Insufficient sample. Do not promote. Justify expanded "
                "multi-window test (≥20 windows).",
            )
    # n >= 4
    if 0 <= mean_net <= 5:
        return (
            f"{n_computable} entries with mean net P&L "
            f"{float(mean_net):.2f} bps (0–5)",
            "Marginal. Discuss with reviewer before allocating more "
            "research time.",
        )
    if mean_net > 5:
        return (
            f"{n_computable} entries with mean net P&L "
            f"{float(mean_net):.2f} bps (> 5)",
            "Promising. Justify expanded multi-window test with "
            "in-sample/out-of-sample split.",
        )
    # mean_net < 0 with n >= 4
    return (
        f"{n_computable} entries with mean net P&L "
        f"{float(mean_net):.2f} bps (< 0)",
        "No normal-regime edge demonstrated. Recommend pivot or "
        "shelving.",
    )


def _write_memo(*, summary, complete_trades, total_fills, incomplete_count,
                fetcher_classname, sep_overlap):
    lines = []
    lines.append("# A2 Step 3 — Normal-Regime Test Result")
    lines.append("")
    lines.append("Generated by `scripts/run_a2_step3.py`  ")
    lines.append(
        f"Generated at: {datetime.now(tz=timezone.utc).isoformat()}  "
    )
    lines.append(f"Run ID: `{RUN_ID}`  ")
    lines.append(f"Fetcher: `{fetcher_classname}`  ")
    lines.append(
        f"  wrapping: `BinanceArchiveTradeFetcher` (perp) + "
        f"`BinanceSpotArchiveTradeFetcher` (spot)  "
    )
    lines.append(f"Window: {WINDOW_START} → {WINDOW_END}  ")
    lines.append(f"Fixture: `{FIXTURE_PATH.relative_to(REPO_ROOT)}`  ")
    lines.append(
        f"Pre-registration: `{PREREG_PATH.relative_to(REPO_ROOT)}` "
        f"(committed before this run)"
    )
    lines.append("")

    # Run summary
    lines.append("## Run summary")
    lines.append("")
    lines.append(f"- Entries fired: {summary.a2_intents_fired}")
    lines.append(
        f"- Exits (basis_converged): "
        f"{summary.a2_exits_fired_basis_converged}"
    )
    lines.append(
        f"- Exits (time_forced): {summary.a2_exits_fired_time_forced}"
    )
    lines.append(
        f"- Positions open at end: {summary.positions_open_at_end_of_run}"
    )
    lines.append(f"- Total paper.fills rows: {total_fills}")
    lines.append(f"- Complete trades: {len(complete_trades)}")
    if incomplete_count > 0:
        lines.append(f"- Incomplete trades (entry only, no exit): {incomplete_count}")
    lines.append(f"- Cost assumption: {FEES_BPS} bps round-trip fees")
    lines.append("  (Binance perp taker 4.5 + spot taker 10.0)")
    lines.append("")

    # Per-trade detail
    if complete_trades:
        trade_pnls = [_compute_trade_pnl(t) for t in complete_trades]
        computable_trades = [
            p for p in trade_pnls if p["slippage_complete"]
        ]

        lines.append("## Per-trade detail")
        lines.append("")
        lines.append(
            "All values in bps. P&L is profit-positive (positive = "
            "trade made money). Net = gross − fees − slippage."
        )
        lines.append("")
        lines.append(
            "| # | Entry → Exit | Hold (s) | Reason | Perp P&L | "
            "Spot P&L | Gross | Slip total | Net |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for i, p in enumerate(trade_pnls, 1):
            entry_t = p["entry_filled_at"].strftime("%Y-%m-%d %H:%M")
            exit_t = p["exit_filled_at"].strftime("%H:%M")
            slip_display = (
                f"{float(p['slippage_bps_total']):.2f}"
                if p["slippage_complete"] else "NULL"
            )
            net_display = (
                f"{float(p['net_pnl_bps']):.2f}"
                if p["slippage_complete"] else "—"
            )
            lines.append(
                f"| {i} | {entry_t} → {exit_t} | "
                f"{p['holding_duration_seconds']} | "
                f"{p['exit_reason']} | "
                f"{float(p['perp_pnl_bps']):.2f} | "
                f"{float(p['spot_pnl_bps']):.2f} | "
                f"{float(p['gross_pnl_bps']):.2f} | "
                f"{slip_display} | {net_display} |"
            )
        lines.append("")

        # Slippage availability
        n_complete = len(computable_trades)
        n_total = len(complete_trades)
        lines.append("### Slippage availability")
        lines.append("")
        if n_complete == n_total:
            lines.append(
                f"All {n_total} trades have non-NULL observed slippage "
                "on all 4 fills. Net P&L is decision-grade."
            )
        elif n_complete == 0:
            lines.append(
                f"**Non-decision-grade**: 0 of {n_total} trades have "
                "non-NULL slippage on all 4 fills. Per pre-registration "
                "Section C: refuse headline net P&L."
            )
        else:
            lines.append(
                f"Partial: {n_complete} of {n_total} trades have "
                "non-NULL slippage on all 4 fills. Aggregate stats "
                "computed only over the complete subset."
            )
        lines.append("")

        # Distribution
        if computable_trades:
            nets = [float(p["net_pnl_bps"]) for p in computable_trades]
            grosses = [float(p["gross_pnl_bps"]) for p in computable_trades]
            slips = [
                float(p["slippage_bps_total"])
                for p in computable_trades
            ]
            holdings = [
                p["holding_duration_seconds"]
                for p in computable_trades
            ]
            lines.append("### Distribution (decision-grade trades only)")
            lines.append("")
            lines.append("| Metric | Net P&L (bps) | Gross (bps) | Slip total (bps) | Hold (s) |")
            lines.append("|---|---|---|---|---|")
            for stat_name in ["mean", "median", "stdev", "min", "max"]:
                row = f"| {stat_name.title()} |"
                for series in (nets, grosses, slips, holdings):
                    if len(series) < 2 and stat_name == "stdev":
                        row += " — |"
                        continue
                    if stat_name == "mean":
                        v = statistics.mean(series)
                    elif stat_name == "median":
                        v = statistics.median(series)
                    elif stat_name == "stdev":
                        v = statistics.stdev(series)
                    elif stat_name == "min":
                        v = min(series)
                    else:
                        v = max(series)
                    row += f" {v:.2f} |"
                lines.append(row)
            lines.append("")
    else:
        lines.append("## Per-trade detail")
        lines.append("")
        lines.append("No complete trades.")
        lines.append("")

    # Sep 2021 cross-reference (always)
    lines.append("## Sep 2021 stress-window cross-reference")
    lines.append("")
    if not complete_trades:
        lines.append(
            "No fills generated, so the Sep 2021 cross-reference is not "
            "applicable. The Step 3 window (2023-10-01 → 2023-10-15) "
            "is entirely post-Sep-2021 in any case; no overlap possible "
            "by window construction."
        )
    elif sep_overlap:
        lines.append(
            f"**WARNING**: {len(sep_overlap)} fills overlap the Sep 2021 "
            f"stress window. This violates the test's regime-isolation "
            f"intent; investigate."
        )
        for ts in sep_overlap:
            lines.append(f"- `{ts.isoformat()}`")
    else:
        lines.append(
            "Confirmed: no fills overlap the Sep 2021 stress window. "
            "The Step 3 window (2023-10-01 → 2023-10-15) is entirely "
            "post-Sep-2021, so non-overlap was structurally guaranteed."
        )
    lines.append("")

    # Kill criterion evaluation
    lines.append("## Kill criterion evaluation")
    lines.append("")
    computable_trades_pnl = []
    if complete_trades:
        trade_pnls = [_compute_trade_pnl(t) for t in complete_trades]
        computable_trades_pnl = [
            p for p in trade_pnls if p["slippage_complete"]
        ]
    criterion_label, decision_text = _apply_kill_criterion(
        summary.a2_intents_fired, computable_trades_pnl,
    )
    lines.append(f"**Outcome**: {criterion_label}")
    lines.append("")
    lines.append(f"**Decision**: {decision_text}")
    lines.append("")

    # Special-case messaging
    if summary.a2_intents_fired == 0:
        lines.append(
            "No fills were generated, so slippage availability is not "
            "applicable. Kill criterion triggered by zero entries."
        )
        lines.append("")
        lines.append(
            "Per the pre-registration anti-cherry-pick rule, no further "
            "fixture hunting under this specification is permitted. "
            "A2 basis as currently specified should be shelved or "
            "pivoted to a different signal family. Any alternate window "
            "test must be its own pre-registered Step with its own "
            "kill criteria; Step 3's result is preserved regardless."
        )
        lines.append("")

    # Closing
    lines.append("---")
    lines.append("")
    lines.append(
        "*This memo records the outcome of one pre-registered test on "
        "one window. The pre-registration's anti-cherry-pick rule "
        "binds: this result is final.*"
    )

    MEMO_PATH.write_text("\n".join(lines))


def main() -> None:
    print("Step 3: A2 Normal-Regime Validation Test")
    print("=" * 60)
    print(f"Window: {WINDOW_START} → {WINDOW_END}")
    print(f"Fixture: {FIXTURE_PATH.name}")
    print(f"Run ID: {RUN_ID}")
    print()

    if not FIXTURE_PATH.exists():
        sys.exit(f"ERROR: fixture missing: {FIXTURE_PATH}")

    print("Upgrading DB to migration head...")
    _alembic_upgrade_head()
    print("Done.")
    print()

    print("Building REAL fetcher (no NoopFetcher)...")
    fetcher = _build_real_fetcher()
    fetcher_classname = type(fetcher).__name__
    print(f"  fetcher: {fetcher_classname}")
    print()

    with _connect() as conn:
        print("Bootstrapping registry (idempotent)...")
        ids = _bootstrap_registry(conn)
        conn.commit()
        print(
            f"  strategy_id={ids['strategy_id']}, "
            f"perp_id={ids['perp_id']}, spot_id={ids['spot_id']}"
        )
        print()

        print("Wiping paper.fills + paper.positions for this strategy...")
        _wipe_paper(conn, ids["strategy_id"])
        conn.commit()
        print("Done.")
        print()

        print("Running A2 runner against SOL 2023-10-01..15 fixture...")
        print("(may take 1-10 minutes if Binance archive cache misses)")
        summary = _run_a2(conn, ids, fetcher)
        print(f"  Entries: {summary.a2_intents_fired}")
        print(
            f"  Exits: "
            f"{summary.a2_exits_fired_basis_converged} converged + "
            f"{summary.a2_exits_fired_time_forced} time-forced"
        )
        print(
            f"  Open at end: {summary.positions_open_at_end_of_run}"
        )
        print()

        print("Querying paper.fills for per-trade detail...")
        complete_trades, total_fills, incomplete_count = _query_trades(
            conn, ids["strategy_id"],
        )
        print(
            f"  Complete trades: {len(complete_trades)}, "
            f"total fills: {total_fills}"
        )
        if incomplete_count > 0:
            print(f"  Incomplete trades: {incomplete_count}")
        print()

        sep_overlap = _check_sep_2021_overlap(complete_trades)
        if sep_overlap:
            print(
                f"  WARNING: {len(sep_overlap)} fills overlap "
                "Sep 2021 stress window"
            )
        print()

    print(f"Writing result memo to {MEMO_PATH.relative_to(REPO_ROOT)}...")
    _write_memo(
        summary=summary,
        complete_trades=complete_trades,
        total_fills=total_fills,
        incomplete_count=incomplete_count,
        fetcher_classname=fetcher_classname,
        sep_overlap=sep_overlap,
    )
    size = MEMO_PATH.stat().st_size
    print(f"Memo written: {size:,} bytes")
    print()

    # Final summary line
    if summary.a2_intents_fired == 0:
        print("KILL CRITERION TRIGGERED: zero entries fired.")
        print("See memo for full pre-registered response.")
    elif complete_trades:
        print(f"Result: {len(complete_trades)} complete trades.")
        print("See memo for kill-criterion evaluation.")
    else:
        print(
            f"Result: {summary.a2_intents_fired} entries, "
            f"no complete trades."
        )


if __name__ == "__main__":
    main()
