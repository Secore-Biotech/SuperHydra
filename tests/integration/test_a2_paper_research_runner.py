"""Integration tests for A2PaperResearchRunner.

Day 24 deliverable. Covers:
  - Constant fixture (no fire): 0 a2_intents_fired, 0 paper.fills rows
  - Spike fixture (one fire): 1 a2_intent_fired, 2 paper.fills rows
  - Firewall properties (PAPER_RESEARCH, promotion_eligible=false,
    trading.fills unchanged)
  - Shared a2_intent_uuid in metadata across legs
  - Deterministic per-leg paper_fill_uuid (re-run produces same UUIDs)
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from strategies.a2_basis.runner.paper_research_runner import (
    A2PaperResearchRunner,
    load_basis_fixture,
)
from tests.integration.test_migrations import (  # noqa: F401
    _alembic,
    _connect,
    fresh_db,
)


FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "a2_basis"


# ─── Inline NoopFetcher (no network for synthetic tests) ────────────────


class _NoopFetcher:
    """Returns empty trade list for any window. Day 24 has no real
    perp/spot tick data; replay observation rows have observed_slippage_bps
    NULL with replay_status='empty_window'."""

    def fetch_window(self, symbol, start, end):
        return []


# ─── Registry bootstrap for A2 tests ────────────────────────────────────


def _bootstrap_a2_registry(conn, suffix: str) -> dict:
    """Create A2-specific registry entries with UUID suffix.

    Returns dict of IDs needed by the A2 runner.
    """
    with conn.cursor() as cur:
        # Venue: binance (idempotent)
        cur.execute("""
            INSERT INTO registry.venues (venue_code, display_name, venue_type, status)
            VALUES ('binance', 'Binance', 'cex_futures', 'active')
            RETURNING id;
        """)
        venue_id = cur.fetchone()[0]

        # Assets: SOL, USDT (idempotent)
        cur.execute("""
            INSERT INTO registry.assets (symbol, display_name, asset_type, decimals, status)
            VALUES ('SOL', 'Solana', 'crypto', 9, 'active')
            RETURNING id;
        """)
        sol_asset_id = cur.fetchone()[0]
        cur.execute("""
            INSERT INTO registry.assets (symbol, display_name, asset_type, decimals, status)
            VALUES ('USDT', 'Tether USD', 'stablecoin', 6, 'active')
            RETURNING id;
        """)
        usdt_asset_id = cur.fetchone()[0]

        # A2 strategy (suffixed to avoid collision)
        strategy_name = f"a2_basis_research_{suffix}"
        cur.execute("""
            INSERT INTO registry.strategies
                (name, display_name, current_phase, phase_entered_at,
                 hypothesis_doc_path, config)
            VALUES (%s, %s, 'research', NOW(),
                    'docs/strategies/a2_basis_design_brief.md', '{}'::jsonb)
            RETURNING id;
        """, (strategy_name, "A2 Basis Research"))
        strategy_id = cur.fetchone()[0]

        # A2 portfolio
        portfolio_code = f"a2_basis_portfolio_{suffix}"
        cur.execute("""
            INSERT INTO registry.portfolios
                (portfolio_code, display_name, product_type, status)
            VALUES (%s, %s, 'paper', 'research')
            RETURNING id;
        """, (portfolio_code, "A2 Basis Portfolio"))
        portfolio_id = cur.fetchone()[0]

        # A2 account
        account_code = f"a2_basis_account_{suffix}"
        cur.execute("""
            INSERT INTO registry.accounts
                (venue_id, account_code, display_name, account_type, status)
            VALUES (%s, %s, %s, 'trading', 'active')
            RETURNING id;
        """, (venue_id, account_code, "A2 Basis Account"))
        account_id = cur.fetchone()[0]

        # Perp instrument: SOLUSDT (suffixed)
        perp_code = f"SOLUSDT_a2_{suffix}"
        cur.execute("""
            INSERT INTO registry.instruments
                (instrument_code, display_name, venue_id, base_asset_id,
                 quote_asset_id, instrument_type, status)
            VALUES (%s, %s, %s, %s, %s, 'perp', 'active')
            RETURNING id;
        """, (perp_code, "SOLUSDT Perp (A2)", venue_id, sol_asset_id, usdt_asset_id))
        perp_instrument_id = cur.fetchone()[0]

        # Spot instrument: SOLUSDT_SPOT (suffixed)
        spot_code = f"SOLUSDT_SPOT_a2_{suffix}"
        cur.execute("""
            INSERT INTO registry.instruments
                (instrument_code, display_name, venue_id, base_asset_id,
                 quote_asset_id, instrument_type, status)
            VALUES (%s, %s, %s, %s, %s, 'spot', 'active')
            RETURNING id;
        """, (spot_code, "SOLUSDT Spot (A2)", venue_id, sol_asset_id, usdt_asset_id))
        spot_instrument_id = cur.fetchone()[0]

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


# ═══════════════════════════════════════════════════════════════════════
# Constant fixture: zero fires
# ═══════════════════════════════════════════════════════════════════════


def test_constant_fixture_produces_zero_fires(fresh_db):
    """60 obs at constant basis = 10 bps. Expected: zero_or_near_zero_stdev
    on every evaluation past min_lookback. No paper.fills rows."""
    _alembic("upgrade", "0010")

    suffix = uuid.uuid4().hex[:8]

    with _connect() as conn:
        ids = _bootstrap_a2_registry(conn, suffix)

        observations = load_basis_fixture(
            FIXTURE_DIR / "SOLUSDT_BASIS_60obs_constant.json"
        )

        runner = A2PaperResearchRunner(
            basis_source=observations,
            trade_fetcher=_NoopFetcher(),
            fetch_source="archive",
            strategy_id=ids["strategy_id"],
            portfolio_id=ids["portfolio_id"],
            account_id=ids["account_id"],
            perp_instrument_id=ids["perp_instrument_id"],
            spot_instrument_id=ids["spot_instrument_id"],
            venue="binance",
            base_symbol="SOLUSDT",
            quantity_per_intent=Decimal("10.0"),
        )
        summary = runner.run(conn)
        conn.commit()

        # No fires
        assert summary.a2_intents_fired == 0
        assert len(summary.replay_results) == 0

        # 60 evaluations: 30 insufficient_lookback (indices 0-29 hit
        # min_lookback=30 default), 30 zero_or_near_zero_stdev (indices
        # 30-59 hit constant stdev).
        # Actually: indices 0-28 have window size 1-29, all below min_lookback.
        # Index 29: window 30 samples, all at basis=10. Stdev=0 → zero_stdev.
        # Indices 0-28 = 29 insufficient; 29-59 = 31 zero_stdev.
        assert summary.evaluations_total == 60
        assert summary.evaluations_skipped_insufficient_lookback == 29
        assert summary.evaluations_skipped_zero_or_near_zero_stdev == 31
        assert summary.evaluations_skipped_z_below_threshold == 0
        assert summary.evaluations_skipped_cost_not_cleared == 0

        # No paper.fills rows written
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM paper.fills;")
            assert cur.fetchone()[0] == 0


# ═══════════════════════════════════════════════════════════════════════
# Spike fixture: exactly one fire, two paper.fills rows
# ═══════════════════════════════════════════════════════════════════════


def test_spike_fixture_produces_one_fire_with_two_legs(fresh_db):
    """59 obs at basis=0, 1 final obs at basis=85. Expected: 1 fire,
    2 paper.fills rows with shared a2_intent_uuid."""
    _alembic("upgrade", "0010")

    suffix = uuid.uuid4().hex[:8]

    with _connect() as conn:
        ids = _bootstrap_a2_registry(conn, suffix)

        observations = load_basis_fixture(
            FIXTURE_DIR / "SOLUSDT_BASIS_60obs_one_spike.json"
        )

        runner = A2PaperResearchRunner(
            basis_source=observations,
            trade_fetcher=_NoopFetcher(),
            fetch_source="archive",
            strategy_id=ids["strategy_id"],
            portfolio_id=ids["portfolio_id"],
            account_id=ids["account_id"],
            perp_instrument_id=ids["perp_instrument_id"],
            spot_instrument_id=ids["spot_instrument_id"],
            venue="binance",
            base_symbol="SOLUSDT",
            quantity_per_intent=Decimal("10.0"),
        )
        summary = runner.run(conn)
        conn.commit()

        # Exactly one fire
        assert summary.a2_intents_fired == 1
        assert len(summary.replay_results) == 2

        # Two paper.fills rows
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM paper.fills;")
            assert cur.fetchone()[0] == 2

            # Both rows share a2_intent_uuid in metadata
            cur.execute("""
                SELECT metadata->>'a2_intent_uuid',
                       metadata->>'a2_leg',
                       instrument_id,
                       side
                FROM paper.fills
                ORDER BY metadata->>'a2_leg';
            """)
            rows = cur.fetchall()
            assert len(rows) == 2

            intent_uuid_perp, leg_perp, inst_perp, side_perp = rows[0]
            intent_uuid_spot, leg_spot, inst_spot, side_spot = rows[1]

            # Shared a2_intent_uuid
            assert intent_uuid_perp == intent_uuid_spot
            assert intent_uuid_perp is not None

            # Distinct legs
            assert leg_perp == "perp"
            assert leg_spot == "spot"

            # Correct instrument routing
            assert inst_perp == ids["perp_instrument_id"]
            assert inst_spot == ids["spot_instrument_id"]

            # SHORT_PERP_LONG_SPOT (positive dislocation):
            #   perp_side='sell', spot_side='buy'
            assert side_perp == "sell"
            assert side_spot == "buy"


# ═══════════════════════════════════════════════════════════════════════
# Firewall properties
# ═══════════════════════════════════════════════════════════════════════


def test_spike_fixture_writes_only_paper_research_with_promotion_false(fresh_db):
    """Every paper.fills row from A2 must have source_mode='PAPER_RESEARCH'
    and promotion_eligible=false. trading.fills must be unchanged."""
    _alembic("upgrade", "0010")
    suffix = uuid.uuid4().hex[:8]

    with _connect() as conn:
        ids = _bootstrap_a2_registry(conn, suffix)
        observations = load_basis_fixture(
            FIXTURE_DIR / "SOLUSDT_BASIS_60obs_one_spike.json"
        )

        # Count trading.fills before
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM trading.fills;")
            trading_before = cur.fetchone()[0]

        runner = A2PaperResearchRunner(
            basis_source=observations,
            trade_fetcher=_NoopFetcher(),
            fetch_source="archive",
            strategy_id=ids["strategy_id"],
            portfolio_id=ids["portfolio_id"],
            account_id=ids["account_id"],
            perp_instrument_id=ids["perp_instrument_id"],
            spot_instrument_id=ids["spot_instrument_id"],
            venue="binance",
            base_symbol="SOLUSDT",
            quantity_per_intent=Decimal("10.0"),
        )
        runner.run(conn)
        conn.commit()

        with conn.cursor() as cur:
            # All paper.fills rows are PAPER_RESEARCH + promotion_eligible=false
            cur.execute("""
                SELECT DISTINCT source_mode, promotion_eligible FROM paper.fills;
            """)
            for source_mode, promotion_eligible in cur.fetchall():
                assert source_mode == "PAPER_RESEARCH"
                assert promotion_eligible is False

            # trading.fills unchanged
            cur.execute("SELECT COUNT(*) FROM trading.fills;")
            trading_after = cur.fetchone()[0]
            assert trading_after == trading_before


# ═══════════════════════════════════════════════════════════════════════
# Deterministic UUIDs (idempotency)
# ═══════════════════════════════════════════════════════════════════════


def test_deterministic_uuids_across_reruns(fresh_db):
    """Re-running the same fixture produces same paper_fill_uuid for
    both legs. The Day 20.1 writer's hash-mismatch check then makes
    the second write a silent no-op."""
    _alembic("upgrade", "0010")
    suffix = uuid.uuid4().hex[:8]

    with _connect() as conn:
        ids = _bootstrap_a2_registry(conn, suffix)
        observations = load_basis_fixture(
            FIXTURE_DIR / "SOLUSDT_BASIS_60obs_one_spike.json"
        )

        # First run
        runner1 = A2PaperResearchRunner(
            basis_source=observations,
            trade_fetcher=_NoopFetcher(),
            fetch_source="archive",
            strategy_id=ids["strategy_id"],
            portfolio_id=ids["portfolio_id"],
            account_id=ids["account_id"],
            perp_instrument_id=ids["perp_instrument_id"],
            spot_instrument_id=ids["spot_instrument_id"],
            venue="binance",
            base_symbol="SOLUSDT",
            quantity_per_intent=Decimal("10.0"),
        )
        summary1 = runner1.run(conn)
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("SELECT paper_fill_uuid FROM paper.fills ORDER BY paper_fill_uuid;")
            uuids_first = [row[0] for row in cur.fetchall()]

        # Second run: identical inputs
        runner2 = A2PaperResearchRunner(
            basis_source=observations,
            trade_fetcher=_NoopFetcher(),
            fetch_source="archive",
            strategy_id=ids["strategy_id"],
            portfolio_id=ids["portfolio_id"],
            account_id=ids["account_id"],
            perp_instrument_id=ids["perp_instrument_id"],
            spot_instrument_id=ids["spot_instrument_id"],
            venue="binance",
            base_symbol="SOLUSDT",
            quantity_per_intent=Decimal("10.0"),
        )
        summary2 = runner2.run(conn)
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("SELECT paper_fill_uuid FROM paper.fills ORDER BY paper_fill_uuid;")
            uuids_second = [row[0] for row in cur.fetchall()]

        # Both runs produced same UUIDs; second run was a no-op
        assert uuids_first == uuids_second
        # Still only 2 rows total (no duplicates)
        assert len(uuids_second) == 2
        # Both summaries reported one fire each
        assert summary1.a2_intents_fired == 1
        assert summary2.a2_intents_fired == 1
