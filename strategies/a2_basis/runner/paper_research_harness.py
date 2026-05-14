"""A2 PAPER_RESEARCH operator CLI harness.

Day 25 deliverable. Single-file harness that:
  1. Bootstraps A2 registry entries (idempotent get-or-create)
  2. Loads a basis fixture
  3. Runs A2PaperResearchRunner
  4. Computes per-leg slippage stats via the Day 20.2 aggregator
  5. Emits a JSON-serializable summary to stdout

CLI usage:
  python -m strategies.a2_basis.runner.paper_research_harness \
      --fixture tests/fixtures/a2_basis/SOLUSDT_BASIS_60obs_one_spike.json \
      --symbol SOLUSDT \
      --quantity 10.0 \
      --pretty

Per Day 25 reviewer-locked decisions:
  - 25.1: _bootstrap_a2_registry lives here; tests import from this module
  - 25.2: single basis fixture (the Day 24 format)
  - 25.3: nested per-leg blocks (perp, spot) + flat top-level summary
  - 25.4: two separate compute_slippage_calibration calls (one per leg)
  - 25.5: same quantity for both legs; documented limitation

Limitation per 25.5: quantity_per_intent is the same unit count for
both perp and spot legs. At A2's firing threshold the basis is at
most ~1% so the notional mismatch between perp and spot legs is
bounded, but this is a known approximation. Notional-matched sizing
is deferred to Day 26+ when real data ingestion lands.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg

from analytics.slippage_calibration import compute_slippage_calibration
from strategies.a2_basis.config.profile_selector import (
    select_research_profile_for_a2,
)
from strategies.a2_basis.signal.cost_threshold import (
    compute_a2_round_trip_threshold_bps,
)
from strategies.a2_basis.runner.paper_research_runner import (
    A2PaperResearchRunner,
    _slippage_tier_names_for,
    load_basis_fixture,
)


# Default uncertainty margin per Day 22 reviewer lock.
DEFAULT_UNCERTAINTY_MARGIN_FRACTION: Decimal = Decimal("0.2")


# ─── DB connection helper ───────────────────────────────────────────────


def _dsn() -> str:
    """Return the DSN to connect to. Uses DATABASE_URL env if set."""
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://superhydra:superhydra_dev_only@localhost:5432/superhydra",
    )


def _connect():
    return psycopg.connect(_dsn())


# ─── NoopFetcher for synthetic-fixture runs (no network) ────────────────


class NoopFetcher:
    """Returns empty trade list for any window.

    A2 harness fixtures are synthetic (perp + spot prices come from the
    fixture, not from the venue). Replay observation always sees an
    empty window → observed_slippage_bps is NULL on every paper.fills
    row. Day 26+ wires real trade fetchers.
    """

    def fetch_window(self, symbol, start, end):
        return []


# ─── Registry bootstrap (refactored from test file per 25.1) ────────────


def _get_or_create_venue(
    cur,
    venue_code: str,
    display_name: str,
    venue_type: str,
) -> int:
    cur.execute(
        "SELECT id FROM registry.venues WHERE venue_code = %s;",
        (venue_code,),
    )
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        """INSERT INTO registry.venues
           (venue_code, display_name, venue_type, status)
           VALUES (%s, %s, %s, 'active')
           RETURNING id;""",
        (venue_code, display_name, venue_type),
    )
    return cur.fetchone()[0]


def _get_or_create_asset(
    cur,
    symbol: str,
    display_name: str,
    asset_type: str,
    decimals: int,
) -> int:
    # Match the canonical asset (NULL chain, NULL contract_address); avoids
    # picking up a chain-specific record like ('SOL', 'solana', '...')
    cur.execute(
        """SELECT id FROM registry.assets
           WHERE symbol = %s AND chain IS NULL AND contract_address IS NULL;""",
        (symbol,),
    )
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        """INSERT INTO registry.assets
           (symbol, display_name, asset_type, decimals, status)
           VALUES (%s, %s, %s, %s, 'active')
           RETURNING id;""",
        (symbol, display_name, asset_type, decimals),
    )
    return cur.fetchone()[0]


def _get_or_create_strategy(
    cur,
    name: str,
    display_name: str,
    hypothesis_doc_path: str,
) -> int:
    cur.execute(
        "SELECT id FROM registry.strategies WHERE name = %s;",
        (name,),
    )
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        """INSERT INTO registry.strategies
           (name, display_name, current_phase, phase_entered_at,
            hypothesis_doc_path, config)
           VALUES (%s, %s, 'research', NOW(), %s, '{}'::jsonb)
           RETURNING id;""",
        (name, display_name, hypothesis_doc_path),
    )
    return cur.fetchone()[0]


def _get_or_create_portfolio(
    cur,
    portfolio_code: str,
    display_name: str,
) -> int:
    cur.execute(
        "SELECT id FROM registry.portfolios WHERE portfolio_code = %s;",
        (portfolio_code,),
    )
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        """INSERT INTO registry.portfolios
           (portfolio_code, display_name, product_type, status)
           VALUES (%s, %s, 'paper', 'research')
           RETURNING id;""",
        (portfolio_code, display_name),
    )
    return cur.fetchone()[0]


def _get_or_create_account(
    cur,
    venue_id: int,
    account_code: str,
    display_name: str,
) -> int:
    cur.execute(
        """SELECT id FROM registry.accounts
           WHERE venue_id = %s AND account_code = %s;""",
        (venue_id, account_code),
    )
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        """INSERT INTO registry.accounts
           (venue_id, account_code, display_name, account_type, status)
           VALUES (%s, %s, %s, 'trading', 'active')
           RETURNING id;""",
        (venue_id, account_code, display_name),
    )
    return cur.fetchone()[0]


def _get_or_create_instrument(
    cur,
    instrument_code: str,
    display_name: str,
    venue_id: int,
    base_asset_id: int,
    quote_asset_id: int,
    instrument_type: str,
) -> int:
    cur.execute(
        "SELECT id FROM registry.instruments WHERE instrument_code = %s;",
        (instrument_code,),
    )
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        """INSERT INTO registry.instruments
           (instrument_code, display_name, venue_id, base_asset_id,
            quote_asset_id, instrument_type, status)
           VALUES (%s, %s, %s, %s, %s, %s, 'active')
           RETURNING id;""",
        (instrument_code, display_name, venue_id,
         base_asset_id, quote_asset_id, instrument_type),
    )
    return cur.fetchone()[0]


def _bootstrap_a2_registry(
    conn,
    *,
    suffix: str = "",
    hypothesis_doc_path: str = "docs/strategies/a2_basis_design_brief.md",
) -> dict:
    """Get-or-create all A2-required registry entries.

    Suffix optional:
      - "" (default): stable codes (idempotent across CLI invocations)
      - non-empty: codes have "_{suffix}" appended (tests use this for
        isolation; the codes are then unique per test)
    """
    suf = f"_{suffix}" if suffix else ""

    with conn.cursor() as cur:
        venue_id = _get_or_create_venue(
            cur, "binance", "Binance", "cex_futures",
        )
        sol_asset_id = _get_or_create_asset(
            cur, "SOL", "Solana", "crypto", 9,
        )
        usdt_asset_id = _get_or_create_asset(
            cur, "USDT", "Tether USD", "stablecoin", 6,
        )
        strategy_id = _get_or_create_strategy(
            cur, f"a2_basis_research{suf}",
            "A2 Basis Research",
            hypothesis_doc_path,
        )
        portfolio_id = _get_or_create_portfolio(
            cur, f"a2_basis_portfolio{suf}", "A2 Basis Portfolio",
        )
        account_id = _get_or_create_account(
            cur, venue_id, f"a2_basis_account{suf}", "A2 Basis Account",
        )
        perp_instrument_id = _get_or_create_instrument(
            cur, f"SOLUSDT_a2_research{suf}",
            "SOLUSDT Perp (A2)",
            venue_id, sol_asset_id, usdt_asset_id, "perp",
        )
        spot_instrument_id = _get_or_create_instrument(
            cur, f"SOLUSDT_SPOT_a2_research{suf}",
            "SOLUSDT Spot (A2)",
            venue_id, sol_asset_id, usdt_asset_id, "spot",
        )

    return {
        "venue_id": venue_id,
        "sol_asset_id": sol_asset_id,
        "usdt_asset_id": usdt_asset_id,
        "strategy_id": strategy_id,
        "portfolio_id": portfolio_id,
        "account_id": account_id,
        "perp_instrument_id": perp_instrument_id,
        "spot_instrument_id": spot_instrument_id,
    }


# ─── HarnessConfig ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class HarnessConfig:
    """Configuration for one harness invocation.

    fixture_path: path to JSON basis fixture (Day 24 format)
    symbol: base symbol (e.g. SOLUSDT)
    venue: venue identifier (currently only 'binance' supported)
    quantity_per_intent: same unit count applied to both legs (25.5 limitation)
    suffix: optional registry-code suffix for test isolation
    """

    fixture_path: Path
    symbol: str = "SOLUSDT"
    venue: str = "binance"
    quantity_per_intent: Decimal = Decimal("10.0")
    suffix: str = ""


# ─── Per-leg block builder ──────────────────────────────────────────────


def _bps_or_none(v: Decimal | None) -> str | None:
    return str(v) if v is not None else None


def _build_leg_block(
    *,
    profile_name: str,
    slippage_tier_name: str,
    modeled_slippage_bps: Decimal,
    slippage_stats,
) -> dict[str, Any]:
    """Construct one of the per-leg JSON blocks (perp or spot)."""
    return {
        "cost_profile_name": profile_name,
        "slippage_tier_name": slippage_tier_name,
        "modeled_slippage_bps": str(modeled_slippage_bps),
        "median_observed_slippage_bps": _bps_or_none(
            getattr(slippage_stats, "median_bps", None),
        ),
        "p90_observed_slippage_bps": _bps_or_none(
            getattr(slippage_stats, "p90_bps", None),
        ),
        "observed_slippage_non_null": (
            getattr(slippage_stats, "n_non_null", None)
            if hasattr(slippage_stats, "n_non_null")
            else getattr(slippage_stats, "n_observations", 0)
        ),
        "observed_slippage_null": getattr(
            slippage_stats, "n_excluded_null", 0,
        ),
    }


# ─── Main harness function ──────────────────────────────────────────────


def run_harness(config: HarnessConfig) -> dict[str, Any]:
    """Execute one harness invocation and return the summary dict.

    Caller flow:
      1. Bootstrap registry (idempotent)
      2. Load fixture into list[BasisObservation]
      3. Run A2PaperResearchRunner
      4. Compute per-leg slippage stats (two aggregator calls per 25.4)
      5. Build nested JSON structure per 25.3
      6. Return dict (caller serializes via json.dumps)
    """
    if not config.fixture_path.exists():
        raise FileNotFoundError(
            f"Fixture not found: {config.fixture_path}"
        )
    if config.quantity_per_intent <= 0:
        raise ValueError(
            f"quantity_per_intent must be positive, "
            f"got {config.quantity_per_intent}"
        )

    observations = load_basis_fixture(config.fixture_path)

    # Pre-compute round-trip decomposition (same throughout run, useful
    # for output regardless of whether the run fires)
    bundle = select_research_profile_for_a2(config.symbol, config.venue)
    perp_tier_name, spot_tier_name = _slippage_tier_names_for(config.symbol)
    round_trip = compute_a2_round_trip_threshold_bps(
        bundle,
        perp_slippage_tier_name=perp_tier_name,
        spot_slippage_tier_name=spot_tier_name,
        uncertainty_margin_fraction=DEFAULT_UNCERTAINTY_MARGIN_FRACTION,
    )

    perp_tier = next(
        t for t in bundle.perp_profile.slippage_tiers
        if t.tier_name == perp_tier_name
    )
    spot_tier = next(
        t for t in bundle.spot_profile.slippage_tiers
        if t.tier_name == spot_tier_name
    )

    with _connect() as conn:
        ids = _bootstrap_a2_registry(conn, suffix=config.suffix)
        conn.commit()

        # Capture before-state
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM paper.fills;")
            paper_fills_before = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM trading.fills;")
            trading_fills_before = cur.fetchone()[0]

        runner = A2PaperResearchRunner(
            basis_source=observations,
            trade_fetcher=NoopFetcher(),
            fetch_source="archive",
            strategy_id=ids["strategy_id"],
            portfolio_id=ids["portfolio_id"],
            account_id=ids["account_id"],
            perp_instrument_id=ids["perp_instrument_id"],
            spot_instrument_id=ids["spot_instrument_id"],
            venue=config.venue,
            base_symbol=config.symbol,
            quantity_per_intent=config.quantity_per_intent,
            cost_bundle=bundle,
            uncertainty_margin_fraction=DEFAULT_UNCERTAINTY_MARGIN_FRACTION,
        )
        summary = runner.run(conn)
        conn.commit()

        # Capture after-state
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM paper.fills;")
            paper_fills_after = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM trading.fills;")
            trading_fills_after = cur.fetchone()[0]

        # Per-leg slippage stats (25.4: two separate aggregator calls).
        # Window: min/max observation time +/- 1s (matches A1's pattern).
        window_start = observations[0].sampled_at - timedelta(seconds=1)
        window_end = observations[-1].sampled_at + timedelta(seconds=1)

        perp_slippage = compute_slippage_calibration(
            conn,
            cost_profile_name=bundle.perp_profile.profile_name,
            instrument_id=ids["perp_instrument_id"],
            window_start=window_start,
            window_end=window_end,
        )
        spot_slippage = compute_slippage_calibration(
            conn,
            cost_profile_name=bundle.spot_profile.profile_name,
            instrument_id=ids["spot_instrument_id"],
            window_start=window_start,
            window_end=window_end,
        )

    return {
        "fixture": str(config.fixture_path),
        "symbol": config.symbol,
        "venue": config.venue,
        "source_mode": "PAPER_RESEARCH",
        "quantity_per_intent": str(config.quantity_per_intent),
        "evaluations_total": summary.evaluations_total,
        "evaluations_skipped_insufficient_lookback": (
            summary.evaluations_skipped_insufficient_lookback
        ),
        "evaluations_skipped_stale_window": (
            summary.evaluations_skipped_stale_window
        ),
        "evaluations_skipped_zero_or_near_zero_stdev": (
            summary.evaluations_skipped_zero_or_near_zero_stdev
        ),
        "evaluations_skipped_z_below_threshold": (
            summary.evaluations_skipped_z_below_threshold
        ),
        "evaluations_skipped_cost_not_cleared": (
            summary.evaluations_skipped_cost_not_cleared
        ),
        "evaluations_skipped_already_positioned": (
            summary.evaluations_skipped_already_positioned
        ),
        # Day 28b.2 exit-side counters
        "exit_evaluations_total": summary.exit_evaluations_total,
        "exit_evaluations_hold_insufficient_lookback": (
            summary.exit_evaluations_hold_insufficient_lookback
        ),
        "exit_evaluations_hold_stale_window": (
            summary.exit_evaluations_hold_stale_window
        ),
        "exit_evaluations_hold_zero_or_near_zero_stdev": (
            summary.exit_evaluations_hold_zero_or_near_zero_stdev
        ),
        "exit_evaluations_hold_still_dislocated": (
            summary.exit_evaluations_hold_still_dislocated
        ),
        "a2_exits_fired_basis_converged": (
            summary.a2_exits_fired_basis_converged
        ),
        "a2_exits_fired_time_forced": (
            summary.a2_exits_fired_time_forced
        ),
        "positions_open_at_end_of_run": (
            summary.positions_open_at_end_of_run
        ),
        "a2_intents_fired": summary.a2_intents_fired,
        "paper_fills_before": paper_fills_before,
        "paper_fills_after": paper_fills_after,
        "trading_fills_before": trading_fills_before,
        "trading_fills_after": trading_fills_after,
        "perp": _build_leg_block(
            profile_name=bundle.perp_profile.profile_name,
            slippage_tier_name=perp_tier_name,
            modeled_slippage_bps=perp_tier.slippage_bps,
            slippage_stats=perp_slippage,
        ),
        "spot": _build_leg_block(
            profile_name=bundle.spot_profile.profile_name,
            slippage_tier_name=spot_tier_name,
            modeled_slippage_bps=spot_tier.slippage_bps,
            slippage_stats=spot_slippage,
        ),
        "round_trip": {
            "perp_entry_bps": str(round_trip.perp_entry_bps),
            "perp_exit_bps": str(round_trip.perp_exit_bps),
            "spot_entry_bps": str(round_trip.spot_entry_bps),
            "spot_exit_bps": str(round_trip.spot_exit_bps),
            "subtotal_bps": str(round_trip.subtotal_bps),
            "uncertainty_margin_bps": str(round_trip.uncertainty_margin_bps),
            "total_threshold_bps": str(round_trip.total_threshold_bps),
        },
    }


# ─── CLI entry point ────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="A2 PAPER_RESEARCH harness. "
                    "Runs the A2 runner against a synthetic basis "
                    "fixture and emits a JSON summary."
    )
    parser.add_argument(
        "--fixture", required=True, type=Path,
        help="Path to JSON basis fixture.",
    )
    parser.add_argument(
        "--symbol", default="SOLUSDT",
        help="Base symbol (default: SOLUSDT). "
             "Currently supported: SOLUSDT, BTCUSDT, ETHUSDT.",
    )
    parser.add_argument(
        "--venue", default="binance",
        help="Venue (default: binance). Multi-venue not yet supported.",
    )
    parser.add_argument(
        "--quantity", default="10.0", type=Decimal,
        help="Quantity per intent (default: 10.0). "
             "Per 25.5 reviewer lock: same unit count applied to "
             "both perp and spot legs. Notional-matched sizing is "
             "deferred to Day 26+.",
    )
    parser.add_argument(
        "--suffix", default="",
        help="Optional registry-code suffix for test isolation. "
             "Leave empty for production CLI use.",
    )
    parser.add_argument(
        "--pretty", action="store_true",
        help="Pretty-print JSON output (indent=2).",
    )
    args = parser.parse_args()

    config = HarnessConfig(
        fixture_path=args.fixture,
        symbol=args.symbol,
        venue=args.venue,
        quantity_per_intent=args.quantity,
        suffix=args.suffix,
    )

    try:
        summary = run_harness(config)
    except Exception as e:
        err = {"error": type(e).__name__, "message": str(e)}
        print(json.dumps(err))
        sys.exit(1)

    indent = 2 if args.pretty else None
    print(json.dumps(summary, indent=indent))


if __name__ == "__main__":
    main()
