#!/usr/bin/env python3
"""Day 28b.3: Empirical close-out for A2 complete trade results.

Runs the A2 paper-research runner against two real-data fixtures
(Mar 2024 SOL regression check, Sep 2021 SOL headline) and produces
the comparative memo at docs/strategies/a2_complete_trade_results.md.

Each run is tagged with a unique run_id (UUIDv4) stored in fill metadata
(metadata->>'empirical_run_id'). All downstream queries filter by run_id
so multiple runs coexist in the same DB without interference. Previous
fills are never deleted (append-only guard on paper.fills).

# TODO(Option A): proper long-term design is run-id partitioning at the
# schema level — a top-level `empirical_runs` table with run_id PK, and
# paper.fills.empirical_run_id as a nullable FK column (NULL = live fill).
# This eliminates the metadata-JSON query pattern and enables efficient
# per-run cleanup, archival, and comparison queries.

Usage:
  python3 scripts/empirical_a2_complete_trade_results.py
  python3 scripts/empirical_a2_complete_trade_results.py --allow-noop-fetcher

Outputs:
  docs/strategies/a2_complete_trade_results.md
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import uuid
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

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://superhydra:superhydra_dev_only@localhost:5432/superhydra",
)

MAR_2024_FIXTURE = (
    REPO_ROOT
    / "tests/fixtures/a2_basis/SOLUSDT_basis_14d_20240316T000000_20240330T000000.json"
)
SEP_2021_FIXTURE = (
    REPO_ROOT
    / "tests/fixtures/a2_basis/SOLUSDT_basis_14d_20210901T000000_20210915T000000.json"
)
MEMO_PATH = REPO_ROOT / "docs/strategies/a2_complete_trade_results.md"

# Stable identifiers for the script's registry rows. Distinct from any
# test_*-suffixed rows so test fresh_db cycles do not interfere with the
# script's state.
VENUE_CODE = "binance"
STRATEGY_NAME = "a2_basis_complete_trade_results"
PORTFOLIO_CODE = "a2_complete_trade_results"
ACCOUNT_CODE = "a2_complete_trade_acct"
PERP_INSTRUMENT_CODE = "SOLUSDT_PERP_a2_results"
SPOT_INSTRUMENT_CODE = "SOLUSDT_SPOT_a2_results"


MODELED_ONLY_PREFIX = "[MODELED-ONLY / NON-DECISION-GRADE]"


def _build_fetcher(allow_noop: bool):
    """Return the trade fetcher to use for this run.

    If --allow-noop-fetcher was passed, import the test-only _NoopFetcher.
    Otherwise, use the real Binance trade fetcher.
    """
    if allow_noop:
        from tests.fixtures._noop_fetcher import _NoopFetcher
        return _NoopFetcher()
    # Real fetcher — import from the venue adapter
    from venues.binance.trade_fetcher import BinanceTradeFetcher
    return BinanceTradeFetcher()


def _connect():
    return psycopg.connect(DATABASE_URL)


def _alembic_upgrade_head() -> None:
    """Ensure DB is at migration head before bootstrapping."""
    r = subprocess.run(
        [
            "alembic", "-c", "infra/migrations/alembic.ini",
            "upgrade", "head",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        print("ERROR: alembic upgrade head failed:")
        print(r.stdout)
        print(r.stderr)
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


def _get_or_create_asset(conn, symbol: str, asset_type: str, decimals: int,
                         display_name: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM registry.assets
            WHERE symbol = %s AND chain IS NULL AND contract_address IS NULL;
            """,
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
            VALUES (%s, 'A2 Complete Trade Results', 'research', NOW(),
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
            VALUES (%s, 'A2 Complete Trade Results', 'paper', 'research')
            RETURNING id;
            """,
            (PORTFOLIO_CODE,),
        )
        return cur.fetchone()[0]


def _get_or_create_account(conn, venue_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM registry.accounts
            WHERE venue_id = %s AND account_code = %s;
            """,
            (venue_id, ACCOUNT_CODE),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute(
            """
            INSERT INTO registry.accounts
                (venue_id, account_code, display_name, account_type, status)
            VALUES (%s, %s, 'A2 Results Acct', 'trading', 'active')
            RETURNING id;
            """,
            (venue_id, ACCOUNT_CODE),
        )
        return cur.fetchone()[0]


def _get_or_create_instrument(conn, *, code: str, display_name: str,
                              venue_id: int, base_asset_id: int,
                              quote_asset_id: int,
                              instrument_type: str) -> int:
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
            (code, display_name, venue_id, base_asset_id, quote_asset_id,
             instrument_type),
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
        conn,
        code=PERP_INSTRUMENT_CODE,
        display_name="SOLUSDT Perp (A2 Results)",
        venue_id=venue_id,
        base_asset_id=sol_id,
        quote_asset_id=usdt_id,
        instrument_type="perp",
    )
    spot_id = _get_or_create_instrument(
        conn,
        code=SPOT_INSTRUMENT_CODE,
        display_name="SOLUSDT Spot (A2 Results)",
        venue_id=venue_id,
        base_asset_id=sol_id,
        quote_asset_id=usdt_id,
        instrument_type="spot",
    )
    return {
        "venue_id": venue_id,
        "strategy_id": strategy_id,
        "portfolio_id": portfolio_id,
        "account_id": account_id,
        "perp_id": perp_id,
        "spot_id": spot_id,
    }


def _count_fills_for_run(conn, strategy_id: int, run_id: str) -> int:
    """Count paper.fills rows tagged with this run_id."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*) FROM paper.fills
               WHERE strategy_id = %s
                 AND metadata->>'empirical_run_id' = %s;""",
            (strategy_id, run_id),
        )
        return cur.fetchone()[0]


def _run_window(conn, ids: dict, fixture_path: Path, fetcher, run_id: str):
    """Run the runner against one fixture; return (summary, exit_rows).

    run_id is passed to the runner, which:
      (a) mixes it into paper_fill_uuid hashes (unique UUIDs per run), and
      (b) injects {"empirical_run_id": run_id} into every fill's metadata
          at intent-construction time — NOT via post-hoc UPDATE, because
          paper.fills is append-only (trigger forbids UPDATE/DELETE).
    """
    # TODO(Option A): promote empirical_run_id to a first-class FK column
    # on paper.fills (nullable, NULL = live fill) with an empirical_runs
    # parent table. This eliminates the metadata-JSON query pattern and
    # enables efficient per-run cleanup, archival, and comparison queries.
    observations = load_basis_fixture(fixture_path)
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
        run_id=run_id,
    )
    summary = runner.run(conn)
    conn.commit()

    # ── Fill-count verification ──────────────────────────────────────
    # Each entry fires 2 legs; each exit fires 2 legs.
    n_entries = summary.a2_intents_fired
    n_exits = (summary.a2_exits_fired_basis_converged
               + summary.a2_exits_fired_time_forced)
    expected_fills = (n_entries * 2) + (n_exits * 2)
    n_inserted = _count_fills_for_run(conn, ids["strategy_id"], run_id)
    print(f"  Inserted {n_inserted} fills tagged with run_id={run_id[:8]}...")

    if n_inserted != expected_fills:
        raise RuntimeError(
            f"Fill count mismatch: expected {expected_fills} fills "
            f"({n_entries} entries * 2 legs + {n_exits} exits * 2 legs) "
            f"but found {n_inserted} with run_id={run_id}. Possible "
            f"causes: ON CONFLICT swallowed inserts (run_id not mixed "
            f"into paper_fill_uuid), or the runner produced unexpected fills."
        )

    # Query exit rows for THIS run only.
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT metadata, filled_at
            FROM paper.fills
            WHERE strategy_id = %s
              AND metadata->>'empirical_run_id' = %s
              AND metadata->>'a2_phase' = 'exit'
              AND metadata->>'a2_leg' = 'perp'
            ORDER BY id;
            """,
            (ids["strategy_id"], run_id),
        )
        exit_rows = [
            {"metadata": meta, "filled_at": filled_at}
            for meta, filled_at in cur.fetchall()
        ]

    return summary, exit_rows


def _stats(values):
    """Compute mean/median/min/max/sum for a list of Decimal values."""
    if not values:
        return None
    n = len(values)
    sorted_v = sorted(values)
    mean = sum(values) / Decimal(n)
    if n % 2 == 1:
        median = sorted_v[n // 2]
    else:
        median = (sorted_v[n // 2 - 1] + sorted_v[n // 2]) / Decimal(2)
    return {
        "mean": float(mean),
        "median": float(median),
        "min": float(min(values)),
        "max": float(max(values)),
        "sum": float(sum(values)),
        "n": n,
    }


def _aggregate(exit_rows):
    """Compute per-trade aggregate stats from exit metadata."""
    if not exit_rows:
        return {"n_trades": 0}
    metas = [r["metadata"] for r in exit_rows]
    gross = [Decimal(m["research_gross_pnl_bps"]) for m in metas]
    net_conservative = [Decimal(m["research_pnl_bps"]) for m in metas]
    perp_pnl = [Decimal(m["research_perp_pnl_bps"]) for m in metas]
    spot_pnl = [Decimal(m["research_spot_pnl_bps"]) for m in metas]
    holding = [Decimal(int(m["a2_holding_duration_seconds"])) for m in metas]
    reasons = [m["a2_exit_reason"] for m in metas]
    threshold_cost = Decimal(metas[0]["research_round_trip_cost_bps"])
    # Estimated true cost: remove 20% safety margin
    estimated_true_cost = threshold_cost / Decimal("1.2")
    net_estimated = [g - estimated_true_cost for g in gross]
    return {
        "n_trades": len(metas),
        "gross_bps": _stats(gross),
        "net_conservative_bps": _stats(net_conservative),
        "net_estimated_bps": _stats(net_estimated),
        "perp_pnl_bps": _stats(perp_pnl),
        "spot_pnl_bps": _stats(spot_pnl),
        "holding_seconds": _stats(holding),
        "reasons": {
            "basis_converged": reasons.count("basis_converged"),
            "time_forced": reasons.count("time_forced"),
        },
        "threshold_cost_bps": float(threshold_cost),
        "estimated_true_cost_bps": float(estimated_true_cost),
    }


def _fmt(v):
    return f"{v:.2f}" if isinstance(v, (int, float)) else "—"


def _write_memo(mar_summary, mar_aggregate,
                sep_summary, sep_aggregate, sep_exit_rows,
                *, memo_path=None, title_prefix="", run_id=""):
    """Generate the markdown memo and write to disk."""
    if memo_path is None:
        memo_path = MEMO_PATH
    lines = []

    # Generated-header (reviewer requirement)
    lines.append(f"# {title_prefix}A2 Complete Trade Results — Mar 2024 vs Sep 2021")
    lines.append("")
    lines.append("Generated by `scripts/empirical_a2_complete_trade_results.py`  ")
    lines.append(
        f"Generated at: {datetime.now(tz=timezone.utc).isoformat()}  "
    )
    lines.append(f"run_id: `{run_id}`  ")
    lines.append("Inputs:")
    lines.append(f"- Mar 2024 fixture: `{MAR_2024_FIXTURE.relative_to(REPO_ROOT)}`")
    lines.append(f"- Sep 2021 fixture: `{SEP_2021_FIXTURE.relative_to(REPO_ROOT)}`")
    lines.append("")

    # Headline summary table
    lines.append("## Headline")
    lines.append("")
    lines.append(
        "| Window | Entries | Exits (converged) | Exits (time-forced) | "
        "Open at end | Mean net (cons.) | Mean net (est. true) |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    for label, summary, agg in [
        ("Mar 2024", mar_summary, mar_aggregate),
        ("Sep 2021", sep_summary, sep_aggregate),
    ]:
        if agg.get("n_trades", 0) > 0:
            mc = f"{agg['net_conservative_bps']['mean']:.2f}"
            me = f"{agg['net_estimated_bps']['mean']:.2f}"
        else:
            mc = "—"
            me = "—"
        lines.append(
            f"| {label} | {summary.a2_intents_fired} | "
            f"{summary.a2_exits_fired_basis_converged} | "
            f"{summary.a2_exits_fired_time_forced} | "
            f"{summary.positions_open_at_end_of_run} | {mc} | {me} |"
        )
    lines.append("")

    # Mar 2024 regression section
    lines.append("## Mar 2024 — regression check")
    lines.append("")
    lines.append(
        "Expected: zero entries. The Day 27(A) memo "
        "(`a2_first_real_data_run.md`) established that the March 2024 SOL "
        "window had no basis dislocations exceeding the entry threshold. "
        "The Day 28b.2 changes (exit logic, P&L attribution) should leave "
        "this regression unchanged."
    )
    lines.append("")
    lines.append(f"- Entries: {mar_summary.a2_intents_fired}")
    lines.append(
        f"- Exits (basis_converged): {mar_summary.a2_exits_fired_basis_converged}"
    )
    lines.append(
        f"- Exits (time_forced): {mar_summary.a2_exits_fired_time_forced}"
    )
    lines.append(
        f"- Positions open at end of run: "
        f"{mar_summary.positions_open_at_end_of_run}"
    )
    lines.append("")
    if mar_summary.a2_intents_fired == 0:
        lines.append(
            "**Regression holds:** zero entries → zero exits → zero closed "
            "trades. Day 28b.2's machinery is correctly a no-op on data "
            "without trade signals."
        )
    else:
        lines.append(
            "**REGRESSION FAILED:** entries fired against Mar 2024 data when "
            "none were expected. Investigate before promoting the Sep 2021 "
            "results."
        )
    lines.append("")

    # Sep 2021 headline section
    lines.append("## Sep 2021 — headline")
    lines.append("")
    lines.append(
        "Sep 1-15 2021 SOLUSDT covers the Sep 7 2021 crypto crash "
        "(SOL $175 → $135 during the El Salvador BTC adoption news cycle). "
        "Day 27(B) found 12 entries pre-hard-block within a 56-minute "
        "window on Sep 7. With Day 28a's hard-block and Day 28b.2's exit "
        "logic engaged, the substrate now produces closed trades with "
        "realized P&L."
    )
    lines.append("")
    lines.append("### Run summary")
    lines.append("")
    lines.append(f"- Entries: {sep_summary.a2_intents_fired}")
    lines.append(
        f"- Exits (basis_converged): "
        f"{sep_summary.a2_exits_fired_basis_converged}"
    )
    lines.append(
        f"- Exits (time_forced): {sep_summary.a2_exits_fired_time_forced}"
    )
    lines.append(
        f"- Positions open at end of run: "
        f"{sep_summary.positions_open_at_end_of_run}"
    )
    n_closed = (sep_summary.a2_exits_fired_basis_converged
                + sep_summary.a2_exits_fired_time_forced)
    lines.append(f"- Closed trades: {n_closed}")
    lines.append(
        f"- Total paper.fills: "
        f"{2 * sep_summary.a2_intents_fired + 2 * n_closed}"
    )
    lines.append("")

    if sep_aggregate.get("n_trades", 0) > 0:
        agg = sep_aggregate
        # P&L distribution
        lines.append(f"### P&L distribution ({agg['n_trades']} closed trades)")
        lines.append("")
        lines.append(
            "All values in basis points (bps). 1 bp = 0.01% of capital "
            "deployed at entry. P&L is profit-positive per Day 28b.2 lock: "
            "positive values mean the trade made money."
        )
        lines.append("")
        lines.append(
            "| Metric | Gross | Net (conservative) | Net (est. true cost) |"
        )
        lines.append("|---|---|---|---|")
        for stat in ["mean", "median", "min", "max", "sum"]:
            row = f"| {stat.title()} |"
            for key in ["gross_bps", "net_conservative_bps",
                        "net_estimated_bps"]:
                v = agg[key].get(stat)
                row += f" {v:.2f} |" if v is not None else " — |"
            lines.append(row)
        lines.append("")
        lines.append("**Cost basis disclosure:**")
        lines.append(
            f"- Conservative threshold cost: **"
            f"{agg['threshold_cost_bps']:.2f} bps** (round-trip cost + "
            "20% safety margin per Day 22 cost model)"
        )
        lines.append(
            f"- Estimated true cost: **"
            f"{agg['estimated_true_cost_bps']:.2f} bps** (threshold / 1.2, "
            "removing the safety margin)"
        )
        lines.append(
            "- Real-world net P&L falls between the conservative and "
            "estimated-true-cost columns; the actual value depends on "
            "live fee schedules and realized slippage. Day 29+ cost-model "
            "refinement narrows this band."
        )
        lines.append("")

        # Holding time
        lines.append("### Holding time")
        lines.append("")
        lines.append("| Stat | Seconds | Minutes |")
        lines.append("|---|---|---|")
        for stat in ["mean", "median", "min", "max"]:
            v = agg["holding_seconds"][stat]
            lines.append(f"| {stat.title()} | {v:.0f} | {v/60:.1f} |")
        lines.append("")

        # Exit reasons
        lines.append("### Exit reasons")
        lines.append("")
        lines.append(
            f"- basis_converged: {agg['reasons']['basis_converged']}"
        )
        lines.append(
            f"- time_forced: {agg['reasons']['time_forced']}"
        )
        lines.append("")

        # Per-leg breakdown
        lines.append("### Per-leg P&L breakdown (gross, bps)")
        lines.append("")
        lines.append(
            "Per-leg P&L answers: did the edge come from the perp leg "
            "converging, the spot leg moving, or both?"
        )
        lines.append("")
        lines.append("| Leg | Mean | Median | Min | Max | Sum |")
        lines.append("|---|---|---|---|---|---|")
        for leg_label, leg_key in [
            ("Perp", "perp_pnl_bps"),
            ("Spot", "spot_pnl_bps"),
        ]:
            row = f"| {leg_label} |"
            for stat in ["mean", "median", "min", "max", "sum"]:
                v = agg[leg_key].get(stat)
                row += f" {v:.2f} |" if v is not None else " — |"
            lines.append(row)
        lines.append("")

        # Per-trade detail
        lines.append("### Per-trade detail")
        lines.append("")
        lines.append(
            "| # | Exit reason | Holding (s) | Gross | Perp | Spot | "
            "Net (cons.) | Net (est.) |"
        )
        lines.append("|---|---|---|---|---|---|---|---|")
        for i, row in enumerate(sep_exit_rows, 1):
            m = row["metadata"]
            gross = Decimal(m["research_gross_pnl_bps"])
            perp = Decimal(m["research_perp_pnl_bps"])
            spot = Decimal(m["research_spot_pnl_bps"])
            net_cons = Decimal(m["research_pnl_bps"])
            net_est = gross - Decimal(str(agg["estimated_true_cost_bps"]))
            lines.append(
                f"| {i} | {m['a2_exit_reason']} | "
                f"{m['a2_holding_duration_seconds']} | "
                f"{float(gross):.2f} | {float(perp):.2f} | "
                f"{float(spot):.2f} | "
                f"{float(net_cons):.2f} | {float(net_est):.2f} |"
            )
        lines.append("")
    else:
        lines.append(
            "**No closed trades.** Position(s) opened but did not close "
            "before fixture end. Mean P&L not computable."
        )
        lines.append("")

    # Interpretation
    lines.append("## Interpretation")
    lines.append("")
    if sep_aggregate.get("n_trades", 0) > 0:
        agg = sep_aggregate
        mean_cons = agg["net_conservative_bps"]["mean"]
        mean_est = agg["net_estimated_bps"]["mean"]
        if mean_cons > 5:
            verdict = "profitable"
        elif mean_cons > -5:
            verdict = "approximately break-even"
        else:
            verdict = "unprofitable"
        lines.append(
            f"On the Sep 2021 SOL dislocation episode, A2's complete-trade "
            f"loop produced an average net P&L of **{mean_cons:.2f} bps** per "
            f"trade under the conservative cost basis. By the profit-positive "
            f"convention locked in Day 28b.2 (`_compute_leg_pnl_bps`), this "
            f"means the strategy was **{verdict}** on this specific episode "
            f"at the cost model used."
        )
        lines.append("")
        lines.append(
            f"Cost-margin sensitivity: at the estimated true cost (removing "
            f"the 20% safety margin), mean net P&L would be "
            f"**{mean_est:.2f} bps** per trade."
        )
        lines.append("")
        n_converged = agg["reasons"]["basis_converged"]
        n_forced = agg["reasons"]["time_forced"]
        if n_converged > n_forced:
            lines.append(
                f"Most exits ({n_converged}/{agg['n_trades']}) fired via "
                "basis_converged — the dislocations did revert within the "
                "4h time window. This validates the half-threshold "
                "convergence trigger from Day 28b.2."
            )
        elif n_forced > n_converged:
            lines.append(
                f"Most exits ({n_forced}/{agg['n_trades']}) fired via "
                "time_forced — the dislocations did NOT revert within 4h. "
                "This suggests the Sep 2021 regime had persistent basis "
                "dislocations; the 4h time cap was the binding constraint. "
                "P&L for time-forced exits is realized at whatever basis "
                "happened to exist at the 4h boundary, which may be "
                "favorable, unfavorable, or roughly neutral."
            )
        else:
            lines.append(
                f"Exits split between basis_converged ({n_converged}) and "
                f"time_forced ({n_forced})."
            )
        lines.append("")
    else:
        lines.append(
            "No closed trades; interpretation not applicable."
        )
        lines.append("")

    # Comparative framing
    lines.append("## Comparative framing — substrate to deployable")
    lines.append("")
    lines.append("This memo closes the A2 design loop:")
    lines.append("")
    lines.append(
        "- **Day 27(B)** (substrate-only): \"12 entries on Sep 7 2021 "
        "crash, signal-positive, execution-incomplete.\""
    )
    lines.append(
        "- **Day 28a**: position state + hard-block anti-reentry "
        "(12 entries → 1 logical position within a single open trade)."
    )
    lines.append(
        "- **Day 28b.1**: pure exit signal evaluator with structured "
        "result (HOLD/CLOSE with six reasons)."
    )
    lines.append(
        "- **Day 28b.2**: interleaved entry/exit loop + paired exit "
        "fills + profit-positive P&L attribution."
    )
    lines.append(
        f"- **Day 28b.3** (this memo): empirical close-out. "
        f"{sep_aggregate.get('n_trades', 0)} complete trades on Sep 2021, "
        "mean net P&L documented above."
    )
    lines.append("")
    lines.append(
        "The strategy now has a complete trade lifecycle in code. "
        "`paper.fills` carries the full audit (entry + exit rows, shared "
        "`a2_intent_uuid`). `paper.positions` reflects only currently-open "
        "positions. Re-entry within a single run is allowed. Position-"
        "carryover across runs remains out of scope (future Day 29+ work)."
    )
    lines.append("")

    # What this does NOT establish
    lines.append("## What this does NOT establish")
    lines.append("")
    lines.append(
        "- **Generalization beyond Sep 7 2021.** One episode is not a "
        "strategy proof. Sample size = 1 market regime."
    )
    lines.append(
        "- **Real-fee accuracy.** The cost model is conservative. Live "
        "fees, real slippage, and venue-specific economics may diverge "
        "in either direction."
    )
    lines.append(
        "- **Live execution viability.** PAPER_RESEARCH mode uses "
        "synthetic fills with `_NoopFetcher`. Real-venue tests come "
        "later in the canary phase."
    )
    lines.append(
        "- **Capacity.** P&L is computed per `quantity_per_intent = "
        "10.0` SOL notional. Scaling considerations (market impact, "
        "borrow availability, funding-rate dependencies) are separate "
        "questions."
    )
    lines.append("")
    lines.append(
        "Day 29+ work addresses these gaps en route to canary readiness."
    )
    lines.append("")

    memo_path.write_text("\n".join(lines))


def _check_slippage_guard(
    conn, strategy_id: int, run_id: str,
) -> tuple[bool, int, int]:
    """Check what fraction of this run's fills lack observed slippage.

    Returns (modeled_only, total_fills, null_count).
    Raises RuntimeError if total_fills == 0 — that means the runner
    produced no fills at all (likely ON CONFLICT swallowed everything).

    Queries the real observed_slippage_bps COLUMN on paper.fills,
    NOT the metadata JSONB.
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*) FROM paper.fills
               WHERE strategy_id = %s
                 AND metadata->>'empirical_run_id' = %s;""",
            (strategy_id, run_id),
        )
        total = cur.fetchone()[0]
        if total == 0:
            raise RuntimeError(
                f"Zero fills found for run_id={run_id}. "
                "The runner may have silently swallowed all inserts via "
                "ON CONFLICT (paper_fill_uuid) DO NOTHING. Check whether "
                "run_id is being mixed into paper_fill_uuid hashes."
            )
        cur.execute(
            """SELECT COUNT(*) FROM paper.fills
               WHERE strategy_id = %s
                 AND metadata->>'empirical_run_id' = %s
                 AND observed_slippage_bps IS NULL;""",
            (strategy_id, run_id),
        )
        null_count = cur.fetchone()[0]
    modeled_only = (null_count / total) >= 0.90
    return modeled_only, total, null_count


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Day 28b.3: Empirical A2 Complete Trade Results",
    )
    parser.add_argument(
        "--allow-noop-fetcher",
        action="store_true",
        default=False,
        help="Use test-only _NoopFetcher instead of real Binance trade fetcher",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    run_id = str(uuid.uuid4())

    print("Day 28b.3: Empirical A2 Complete Trade Results")
    print("=" * 60)
    print(f"run_id: {run_id}")

    fetcher = _build_fetcher(args.allow_noop_fetcher)
    fetcher_label = type(fetcher).__name__
    print(f"Trade fetcher: {fetcher_label}")

    for fix in [MAR_2024_FIXTURE, SEP_2021_FIXTURE]:
        if not fix.exists():
            sys.exit(f"ERROR: fixture missing: {fix}")
        print(f"Found {fix.name} ({fix.stat().st_size:,} bytes)")
    print()

    print("Upgrading DB to migration head...")
    _alembic_upgrade_head()
    print("Done.")
    print()

    with _connect() as conn:
        print("Bootstrapping registry (idempotent)...")
        ids = _bootstrap_registry(conn)
        conn.commit()
        print(f"  strategy_id={ids['strategy_id']}, "
              f"perp_id={ids['perp_id']}, spot_id={ids['spot_id']}")
        print()

        # Mar 2024 run (append-only — no wipe, fills tagged by run_id)
        print(f"Running Mar 2024 SOL...")
        mar_summary, mar_exit_rows = _run_window(
            conn, ids, MAR_2024_FIXTURE, fetcher, run_id,
        )
        mar_aggregate = _aggregate(mar_exit_rows)
        print(f"  Entries: {mar_summary.a2_intents_fired}, "
              f"Exits: {mar_summary.a2_exits_fired_basis_converged + mar_summary.a2_exits_fired_time_forced}, "
              f"Open at end: {mar_summary.positions_open_at_end_of_run}")
        print()

        # Sep 2021 run (append-only — no wipe, fills tagged by run_id)
        print(f"Running Sep 2021 SOL...")
        sep_summary, sep_exit_rows = _run_window(
            conn, ids, SEP_2021_FIXTURE, fetcher, run_id,
        )
        sep_aggregate = _aggregate(sep_exit_rows)
        n_closed = (
            sep_summary.a2_exits_fired_basis_converged
            + sep_summary.a2_exits_fired_time_forced
        )
        print(f"  Entries: {sep_summary.a2_intents_fired}, "
              f"Exits: {n_closed}, "
              f"Open at end: {sep_summary.positions_open_at_end_of_run}")
        if sep_aggregate.get("n_trades", 0) > 0:
            print(f"  Mean net P&L (conservative): "
                  f"{sep_aggregate['net_conservative_bps']['mean']:.2f} bps")
            print(f"  Mean net P&L (est. true): "
                  f"{sep_aggregate['net_estimated_bps']['mean']:.2f} bps")
        print()

        # ── Slippage guard: label as MODELED-ONLY if >=90% NULL ──
        modeled_only, total_fills, null_fills = _check_slippage_guard(
            conn, ids["strategy_id"], run_id,
        )
        pct = (null_fills / total_fills * 100) if total_fills else 0
        print(f"Slippage guard: examined {total_fills} fills, "
              f"{null_fills} had NULL observed_slippage_bps "
              f"({pct:.1f}%).")

    memo_title_prefix = f"{MODELED_ONLY_PREFIX} " if modeled_only else ""
    memo_filename = MEMO_PATH
    if modeled_only:
        memo_filename = MEMO_PATH.with_name(
            MODELED_ONLY_PREFIX.replace(" ", "_").replace("/", "-")
            + "_" + MEMO_PATH.name
        )

    if modeled_only:
        print(f"WARNING: >=90% threshold hit — memo labelled: {MODELED_ONLY_PREFIX}")
        print()

    # Prepend label to P&L summary lines if modeled-only
    pnl_prefix = f"{MODELED_ONLY_PREFIX} " if modeled_only else ""

    if sep_aggregate.get("n_trades", 0) > 0 and modeled_only:
        print(f"  {pnl_prefix}Mean net P&L (conservative): "
              f"{sep_aggregate['net_conservative_bps']['mean']:.2f} bps")
        print(f"  {pnl_prefix}Mean net P&L (est. true): "
              f"{sep_aggregate['net_estimated_bps']['mean']:.2f} bps")
        print()

    print(f"Writing memo to {memo_filename.relative_to(REPO_ROOT)}...")
    _write_memo(
        mar_summary, mar_aggregate,
        sep_summary, sep_aggregate, sep_exit_rows,
        memo_path=memo_filename,
        title_prefix=memo_title_prefix,
        run_id=run_id,
    )
    size = memo_filename.stat().st_size
    print(f"Memo written: {size:,} bytes")


if __name__ == "__main__":
    main()
