"""Operator harness for A1 PAPER_RESEARCH runner.

Day 20.5 deliverable: makes A1PaperResearchRunner operator-callable
from the CLI so fixture sweeps don't require writing more integration
tests for each hypothesis.

Usage:
  python -m strategies.a1_funding.runner.paper_research_harness \
      --fixture path/to/funding_fixture.json \
      --symbol SOLUSDT \
      --quantity 10.0

Output (JSON to stdout):
  {
    "events_loaded": ...,
    "events_skipped_below_lookback": ...,
    "events_skipped_below_threshold": ...,
    "events_skipped_zero_funding": ...,
    "events_skipped_no_reference_price": ...,
    "intents_fired": ...,
    "paper_fills_before": ...,
    "paper_fills_after": ...,
    "observed_slippage_non_null": ...,
    "observed_slippage_null": ...,
    "median_observed_slippage_bps": "...",
    "p90_observed_slippage_bps": "...",
    "trading_fills_before": ...,
    "trading_fills_after": ...
  }

Use --pretty for indented output. JSON-by-default makes fixture sweeps
scriptable: pipe to jq, accumulate over multiple --fixture runs, etc.

Idempotent registry bootstrap: subsequent runs with the same
--strategy-code etc. find existing registry rows rather than creating
duplicates. This is the key difference from _setup_basic_0009, which is
test-scoped and uses random UUIDs.

Hard constraints (reviewer-locked):
  - No network calls
  - No archive fetcher (uses NoopFetcher; only mark_price referenced)
  - No accounting writes
  - No trading.fills writes (verified by row-count delta)
  - Uses existing A1PaperResearchRunner (composition, no new logic)
  - Writes only paper.fills via Day 20.1 writer
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg

from analytics.slippage_calibration import compute_slippage_calibration
from data.ingestion.vendors.binance.funding_rate import FundingRate
from strategies.a1_funding.runner.paper_research_runner import (
    A1PaperResearchRunner,
)


DEFAULT_DATABASE_URL = (
    "postgresql://superhydra:superhydra_dev_only@localhost:5432/superhydra"
)


# ─── Fetcher used by harness (mark_price only, no network) ───────────────


class NoopFetcher:
    """Fetcher that returns no trades.

    The harness deliberately does NOT do tape fetching: it relies on
    FundingRate.mark_price for the decision reference, and skips events
    with mark_price absent (skipped_no_reference_price). Replay
    observations will therefore have empty trade windows -> NULL
    observed_slippage_bps, which is the correct semantic for a
    no-network harness.

    Day 20.5 scope is the operator loop. Real tape replay belongs to
    Day 20.5C (network/archive integration), explicitly NOT this commit.
    """

    def fetch_window(self, symbol, start, end):
        return []


# ─── Fixture loading ─────────────────────────────────────────────────────


def load_funding_fixture(path: Path) -> list[FundingRate]:
    """Load a Binance-shaped funding-rate JSON fixture.

    Returns FundingRate records in the order they appear in the file.
    Caller is responsible for ordering validation (runner enforces
    strict ascending at __init__).
    """
    with path.open() as f:
        payload = json.load(f)
    events: list[FundingRate] = []
    for r in payload["records"]:
        events.append(FundingRate(
            venue=r["venue"],
            instrument=r["instrument"],
            funding_time=datetime.fromisoformat(r["funding_time"]),
            funding_rate=Decimal(r["funding_rate"]),
            mark_price=Decimal(r["mark_price"]) if r.get("mark_price") else None,
        ))
    return events


# ─── Idempotent registry bootstrap ───────────────────────────────────────


@dataclass
class _RegistryIds:
    venue_id: int
    base_asset_id: int
    quote_asset_id: int
    instrument_id: int
    portfolio_id: int
    account_id: int
    strategy_id: int


def _get_or_create_venue(cur, venue_code: str) -> int:
    cur.execute(
        "SELECT id FROM registry.venues WHERE venue_code = %s;",
        (venue_code,),
    )
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        "INSERT INTO registry.venues "
        "(venue_code, display_name, venue_type, status) "
        "VALUES (%s, %s, 'cex_futures', 'active') RETURNING id;",
        (venue_code, f"Venue ({venue_code})"),
    )
    return cur.fetchone()[0]


def _get_or_create_asset(cur, symbol: str, asset_type: str) -> int:
    cur.execute(
        "SELECT id FROM registry.assets WHERE symbol = %s;",
        (symbol,),
    )
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        "INSERT INTO registry.assets "
        "(symbol, display_name, asset_type, decimals, status) "
        "VALUES (%s, %s, %s, 8, 'active') RETURNING id;",
        (symbol, f"{symbol} ({asset_type})", asset_type),
    )
    return cur.fetchone()[0]


def _get_or_create_instrument(
    cur, instrument_code: str, venue_id: int,
    base_asset_id: int, quote_asset_id: int,
) -> int:
    cur.execute(
        "SELECT id FROM registry.instruments WHERE instrument_code = %s;",
        (instrument_code,),
    )
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        "INSERT INTO registry.instruments "
        "(instrument_code, display_name, venue_id, "
        " base_asset_id, quote_asset_id, instrument_type, status) "
        "VALUES (%s, %s, %s, %s, %s, 'perp', 'active') RETURNING id;",
        (instrument_code, f"{instrument_code} (paper research)",
         venue_id, base_asset_id, quote_asset_id),
    )
    return cur.fetchone()[0]


def _get_or_create_portfolio(cur, portfolio_code: str) -> int:
    cur.execute(
        "SELECT id FROM registry.portfolios WHERE portfolio_code = %s;",
        (portfolio_code,),
    )
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        "INSERT INTO registry.portfolios "
        "(portfolio_code, display_name, product_type, status) "
        "VALUES (%s, %s, 'internal', 'live') RETURNING id;",
        (portfolio_code, f"Portfolio ({portfolio_code})"),
    )
    return cur.fetchone()[0]


def _get_or_create_account(cur, account_code: str, venue_id: int) -> int:
    cur.execute(
        "SELECT id FROM registry.accounts "
        "WHERE account_code = %s AND venue_id = %s;",
        (account_code, venue_id),
    )
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        "INSERT INTO registry.accounts "
        "(venue_id, account_code, display_name, account_type, status) "
        "VALUES (%s, %s, %s, 'trading', 'active') RETURNING id;",
        (venue_id, account_code, f"Account ({account_code})"),
    )
    return cur.fetchone()[0]


def _get_or_create_strategy(cur, name: str) -> int:
    cur.execute(
        "SELECT id FROM registry.strategies WHERE name = %s;",
        (name,),
    )
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        "INSERT INTO registry.strategies "
        "(name, display_name, current_phase, phase_entered_at, "
        " hypothesis_doc_path) "
        "VALUES (%s, %s, 'research', NOW(), %s) RETURNING id;",
        (name, f"Strategy ({name})", f"docs/strategies/{name}.md"),
    )
    return cur.fetchone()[0]


def _parse_symbol_assets(symbol: str) -> tuple[str, str]:
    """Parse e.g. 'SOLUSDT' -> ('SOL', 'USDT').

    Hardcoded for USDT-quoted Binance perps; expand as new symbol classes
    are added. Raises if the suffix isn't recognized.
    """
    if symbol.endswith("USDT"):
        return symbol[:-4], "USDT"
    if symbol.endswith("USDC"):
        return symbol[:-4], "USDC"
    raise ValueError(
        f"Cannot parse base/quote from symbol {symbol!r}; "
        f"only USDT/USDC suffixes are currently supported."
    )


def ensure_registry_rows(
    conn,
    *,
    symbol: str,
    venue_code: str,
    instrument_code: str,
    portfolio_code: str,
    account_code: str,
    strategy_name: str,
) -> _RegistryIds:
    """Idempotent bootstrap of registry rows for the harness.

    Caller owns transaction.
    """
    base_symbol, quote_symbol = _parse_symbol_assets(symbol)
    with conn.cursor() as cur:
        venue_id = _get_or_create_venue(cur, venue_code)
        base_id = _get_or_create_asset(cur, base_symbol, "crypto")
        quote_id = _get_or_create_asset(cur, quote_symbol, "stablecoin")
        instrument_id = _get_or_create_instrument(
            cur, instrument_code, venue_id, base_id, quote_id,
        )
        portfolio_id = _get_or_create_portfolio(cur, portfolio_code)
        account_id = _get_or_create_account(cur, account_code, venue_id)
        strategy_id = _get_or_create_strategy(cur, strategy_name)

    return _RegistryIds(
        venue_id=venue_id,
        base_asset_id=base_id,
        quote_asset_id=quote_id,
        instrument_id=instrument_id,
        portfolio_id=portfolio_id,
        account_id=account_id,
        strategy_id=strategy_id,
    )


# ─── Row-count helpers ───────────────────────────────────────────────────


def _count(cur, table: str, where: str = "", params: tuple = ()) -> int:
    sql = f"SELECT COUNT(*) FROM {table}"
    if where:
        sql += f" WHERE {where}"
    cur.execute(sql + ";", params)
    return cur.fetchone()[0]


# ─── Per-run slippage stats via Day 20.2 aggregator ──────────────────────


def _per_run_slippage_stats(
    conn, *, instrument_id: int, window_start, window_end,
) -> dict:
    """Compute median/p90 over paper.fills rows in this run's window.

    Uses Day 20.2 aggregator for canonical semantics. Window is widened
    by 1 second on each side to avoid boundary-exclusive edge cases.
    """
    from datetime import timedelta
    calib = compute_slippage_calibration(
        conn,
        instrument_id=instrument_id,
        window_start=window_start - timedelta(seconds=1),
        window_end=window_end + timedelta(seconds=1),
    )
    return {
        "observed_slippage_non_null": calib.n,
        "observed_slippage_null": calib.n_excluded_null,
        "median_observed_slippage_bps": (
            str(calib.median_bps) if calib.median_bps is not None else None
        ),
        "p90_observed_slippage_bps": (
            str(calib.p90_bps) if calib.p90_bps is not None else None
        ),
    }


# ─── Main harness function ───────────────────────────────────────────────


@dataclass
class HarnessConfig:
    fixture_path: Path
    symbol: str
    quantity_per_intent: Decimal
    venue_code: str = "binance"
    instrument_code: str | None = None  # default: f"{symbol}_paper_research"
    portfolio_code: str = "paper_research_portfolio"
    account_code: str = "paper_research_account"
    strategy_name: str = "a1_paper_research"
    database_url: str = DEFAULT_DATABASE_URL

    def resolved_instrument_code(self) -> str:
        return (
            self.instrument_code
            if self.instrument_code is not None
            else f"{self.symbol}_paper_research"
        )


def run_harness(config: HarnessConfig) -> dict[str, Any]:
    """Run the harness end-to-end and return a result dict.

    Result dict keys match the reviewer-locked output schema; all
    Decimal values are stringified for JSON-safety.

    Validation order is intentional: argument-shape errors (invalid
    quantity, missing fixture, etc.) are surfaced BEFORE any DB
    connection is opened. This is important for CLI ergonomics: an
    operator running with `--quantity 0` should see "ValueError:
    quantity_per_intent must be positive" rather than a confusing
    "UndefinedTable" error from psycopg if the DB schema is not yet
    bootstrapped on the operator\'s machine. The
    A1PaperResearchRunner ALSO validates internally; this pre-check
    is a clearer-error wrapper, not a replacement.
    """
    # Pre-DB argument validation: surface shape errors before any
    # network/connection work.
    if config.quantity_per_intent <= 0:
        raise ValueError(
            f"quantity_per_intent must be positive, "
            f"got {config.quantity_per_intent}"
        )

    events = load_funding_fixture(config.fixture_path)
    events_loaded = len(events)

    with psycopg.connect(config.database_url) as conn:
        ids = ensure_registry_rows(
            conn,
            symbol=config.symbol,
            venue_code=config.venue_code,
            instrument_code=config.resolved_instrument_code(),
            portfolio_code=config.portfolio_code,
            account_code=config.account_code,
            strategy_name=config.strategy_name,
        )

        with conn.cursor() as cur:
            paper_fills_before = _count(cur, "paper.fills")
            trading_fills_before = _count(cur, "trading.fills")

        runner = A1PaperResearchRunner(
            funding_source=events,
            trade_fetcher=NoopFetcher(),
            fetch_source="archive",  # cosmetic; no network calls made
            strategy_id=ids.strategy_id,
            portfolio_id=ids.portfolio_id,
            account_id=ids.account_id,
            instrument_id=ids.instrument_id,
            symbol=config.symbol,
            quantity_per_intent=config.quantity_per_intent,
        )
        summary = runner.run(conn)
        conn.commit()

        with conn.cursor() as cur:
            paper_fills_after = _count(cur, "paper.fills")
            trading_fills_after = _count(cur, "trading.fills")

        # Compute per-run slippage stats using Day 20.2 aggregator,
        # scoped to this run's intent-time window. Use first/last
        # funding_time as the window bounds.
        if events:
            window_start = events[0].funding_time
            window_end = events[-1].funding_time
            stats = _per_run_slippage_stats(
                conn,
                instrument_id=ids.instrument_id,
                window_start=window_start,
                window_end=window_end,
            )
        else:
            stats = {
                "observed_slippage_non_null": 0,
                "observed_slippage_null": 0,
                "median_observed_slippage_bps": None,
                "p90_observed_slippage_bps": None,
            }

    return {
        "fixture": str(config.fixture_path),
        "symbol": config.symbol,
        "quantity_per_intent": str(config.quantity_per_intent),
        "cost_profile_name": "binance_vip5_alt_research_v1",
        "source_mode": "PAPER_RESEARCH",
        "events_loaded": events_loaded,
        "events_skipped_below_lookback": summary.skipped_below_lookback,
        "events_skipped_below_threshold": summary.skipped_no_edge,
        "events_skipped_zero_funding": summary.skipped_zero_funding,
        "events_skipped_no_reference_price": summary.skipped_no_reference,
        "intents_fired": summary.intents_fired,
        "paper_fills_before": paper_fills_before,
        "paper_fills_after": paper_fills_after,
        "trading_fills_before": trading_fills_before,
        "trading_fills_after": trading_fills_after,
        **stats,
    }


# ─── CLI ────────────────────────────────────────────────────────────────


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="paper_research_harness",
        description=(
            "Operator harness for A1 PAPER_RESEARCH runner. "
            "Runs A1PaperResearchRunner against a funding fixture and "
            "outputs JSON stats. No network, no trading.fills writes."
        ),
    )
    p.add_argument("--fixture", required=True, type=Path,
                   help="Path to a Binance-shaped funding-rate JSON fixture.")
    p.add_argument("--symbol", required=True,
                   help="Venue-native instrument symbol, e.g. SOLUSDT.")
    p.add_argument("--quantity", required=True, type=Decimal,
                   help="Quantity per intent (positive Decimal).")
    p.add_argument("--venue-code", default="binance")
    p.add_argument("--instrument-code", default=None,
                   help="Default: <symbol>_paper_research.")
    p.add_argument("--portfolio-code", default="paper_research_portfolio")
    p.add_argument("--account-code", default="paper_research_account")
    p.add_argument("--strategy-name", default="a1_paper_research")
    p.add_argument("--database-url",
                   default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    p.add_argument("--pretty", action="store_true",
                   help="Pretty-print JSON output (indented).")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if not args.fixture.exists():
        print(f"ERROR: fixture not found: {args.fixture}", file=sys.stderr)
        return 2

    config = HarnessConfig(
        fixture_path=args.fixture,
        symbol=args.symbol,
        quantity_per_intent=args.quantity,
        venue_code=args.venue_code,
        instrument_code=args.instrument_code,
        portfolio_code=args.portfolio_code,
        account_code=args.account_code,
        strategy_name=args.strategy_name,
        database_url=args.database_url,
    )

    try:
        result = run_harness(config)
    except Exception as e:
        print(
            json.dumps({"error": type(e).__name__, "message": str(e)}),
            file=sys.stderr,
        )
        return 1

    if args.pretty:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
