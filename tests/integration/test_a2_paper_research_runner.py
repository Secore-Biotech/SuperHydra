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


# ─── Registry bootstrap for A2 tests (refactored to harness module) ────
# Per Day 25.1: bootstrap helper lives in the harness module; this test
# wrapper preserves the positional call convention of the existing
# Day 24 test call sites.


def _bootstrap_a2_registry(conn, suffix: str) -> dict:
    """Thin wrapper around the harness module's _bootstrap_a2_registry,
    preserving the positional suffix convention used by Day 24's tests."""
    from strategies.a2_basis.runner.paper_research_harness import (
        _bootstrap_a2_registry as _harness_bootstrap,
    )
    return _harness_bootstrap(conn, suffix=suffix)


# ═══════════════════════════════════════════════════════════════════════
# Constant fixture: zero fires
# ═══════════════════════════════════════════════════════════════════════


def test_constant_fixture_produces_zero_fires(fresh_db):
    """60 obs at constant basis = 10 bps. Expected: zero_or_near_zero_stdev
    on every evaluation past min_lookback. No paper.fills rows."""
    _alembic("upgrade", "0011")

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
    _alembic("upgrade", "0011")

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
    _alembic("upgrade", "0011")
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
    _alembic("upgrade", "0011")
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



# ═══════════════════════════════════════════════════════════════════════
# Day 28a: anti-reentry integration tests
# ═══════════════════════════════════════════════════════════════════════


from strategies.a2_basis.data.positions import (  # noqa: E402
    paper_position_count,
    get_open_position,
)


FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "a2_basis"


class TestAntiReentry:
    """Day 28a hard-block: once positioned, subsequent fires are skipped."""

    def test_three_spike_fixture_fires_only_once(self, fresh_db):
        _alembic("upgrade", "0011")
        suffix = uuid.uuid4().hex[:8]

        with _connect() as conn:
            ids = _bootstrap_a2_registry(conn, suffix)
            conn.commit()

            observations = load_basis_fixture(
                FIXTURE_DIR / "SOLUSDT_BASIS_60obs_three_spikes.json"
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

        # Day 28b.2 update: with exit logic, each spike now produces
        # a complete trade (entry → converge → exit). All three spikes
        # fire as separate trades because the basis converges between
        # them. The Day 28a hard-block-within-same-position invariant
        # still holds — anti-reentry only blocks while positioned, and
        # the position closes between spikes via basis_converged exit.
        assert summary.a2_intents_fired == 3
        assert summary.a2_exits_fired_basis_converged == 3
        assert summary.positions_open_at_end_of_run == 0

        # paper.positions is empty (all 3 trades closed).
        with _connect() as conn:
            assert paper_position_count(conn, strategy_id=ids["strategy_id"]) == 0

    def test_position_metadata_links_to_entry_fill(self, fresh_db):
        """paper.positions metadata carries a2_intent_uuid + a2_leg +
        entry_paper_fill_uuid so Day 28b's exit logic can find the entry."""
        _alembic("upgrade", "0011")
        suffix = uuid.uuid4().hex[:8]

        with _connect() as conn:
            ids = _bootstrap_a2_registry(conn, suffix)
            conn.commit()

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
            runner.run(conn)
            conn.commit()

            perp_pos = get_open_position(
                conn,
                strategy_id=ids["strategy_id"],
                instrument_id=ids["perp_instrument_id"],
            )
            spot_pos = get_open_position(
                conn,
                strategy_id=ids["strategy_id"],
                instrument_id=ids["spot_instrument_id"],
            )

        assert perp_pos is not None
        assert spot_pos is not None
        # Same a2_intent_uuid on both legs
        assert (
            perp_pos.metadata["a2_intent_uuid"]
            == spot_pos.metadata["a2_intent_uuid"]
        )
        # Distinct legs
        assert perp_pos.metadata["a2_leg"] == "perp"
        assert spot_pos.metadata["a2_leg"] == "spot"
        # entry_paper_fill_uuid present
        assert "entry_paper_fill_uuid" in perp_pos.metadata
        assert "entry_paper_fill_uuid" in spot_pos.metadata

    def test_constant_fixture_writes_no_positions(self, fresh_db):
        """Regression: zero fires → zero positions, zero skip increments."""
        _alembic("upgrade", "0011")
        suffix = uuid.uuid4().hex[:8]

        with _connect() as conn:
            ids = _bootstrap_a2_registry(conn, suffix)
            conn.commit()

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

        assert summary.a2_intents_fired == 0
        assert summary.evaluations_skipped_already_positioned == 0
        with _connect() as conn:
            assert paper_position_count(conn, strategy_id=ids["strategy_id"]) == 0

    def test_entry_fill_metadata_carries_a2_phase(self, fresh_db):
        """Per Day 28a reviewer convention: entry fills include a2_phase='entry'."""
        _alembic("upgrade", "0011")
        suffix = uuid.uuid4().hex[:8]

        with _connect() as conn:
            ids = _bootstrap_a2_registry(conn, suffix)
            conn.commit()

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
            runner.run(conn)
            conn.commit()

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT metadata FROM paper.fills "
                    "WHERE strategy_id = %s ORDER BY id;",
                    (ids["strategy_id"],),
                )
                rows = cur.fetchall()

        # Two entry fills, both with a2_phase=entry
        assert len(rows) == 2
        for (meta,) in rows:
            assert meta["a2_phase"] == "entry"



# ═══════════════════════════════════════════════════════════════════════
# Day 28b.2: exit logic integration tests
# ═══════════════════════════════════════════════════════════════════════


from strategies.a2_basis.signal.evaluate_exit import (  # noqa: E402
    A2ExitConfig,
)


class TestExitLogic:
    """Reviewer-locked checks 1-8 for Day 28b.2."""

    def test_complete_trade_writes_4_paper_fills(self, fresh_db):
        """Check 2: complete-trade fixture writes 2 entry + 2 exit fills."""
        _alembic("upgrade", "0011")
        suffix = uuid.uuid4().hex[:8]

        with _connect() as conn:
            ids = _bootstrap_a2_registry(conn, suffix)
            conn.commit()

            observations = load_basis_fixture(
                FIXTURE_DIR / "SOLUSDT_BASIS_60obs_complete_trade.json"
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

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM paper.fills WHERE strategy_id = %s;",
                    (ids["strategy_id"],),
                )
                fill_count = cur.fetchone()[0]

        assert summary.a2_intents_fired == 1
        # Check 2: 2 entry + 2 exit = 4 paper.fills rows
        assert fill_count == 4
        # Exit fired with basis_converged (price collapsed back to flat)
        assert summary.a2_exits_fired_basis_converged == 1
        assert summary.a2_exits_fired_time_forced == 0

    def test_complete_trade_leaves_paper_positions_empty(self, fresh_db):
        """Check 3: paper.positions empty after a completed trade."""
        _alembic("upgrade", "0011")
        suffix = uuid.uuid4().hex[:8]

        with _connect() as conn:
            ids = _bootstrap_a2_registry(conn, suffix)
            conn.commit()

            observations = load_basis_fixture(
                FIXTURE_DIR / "SOLUSDT_BASIS_60obs_complete_trade.json"
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

            assert paper_position_count(conn, strategy_id=ids["strategy_id"]) == 0
        assert summary.positions_open_at_end_of_run == 0

    def test_sustained_spike_leaves_paper_positions_populated(self, fresh_db):
        """Check 4: paper.positions remains populated if fixture ends before exit."""
        _alembic("upgrade", "0011")
        suffix = uuid.uuid4().hex[:8]

        with _connect() as conn:
            ids = _bootstrap_a2_registry(conn, suffix)
            conn.commit()

            observations = load_basis_fixture(
                FIXTURE_DIR / "SOLUSDT_BASIS_60obs_sustained_spike.json"
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

            assert paper_position_count(conn, strategy_id=ids["strategy_id"]) == 2
        assert summary.positions_open_at_end_of_run == 1
        assert summary.a2_intents_fired == 1
        # Position still open: no exit fired
        assert summary.a2_exits_fired_basis_converged == 0
        assert summary.a2_exits_fired_time_forced == 0

    def test_research_pnl_is_profit_positive(self, fresh_db):
        """Check 5: research_pnl_bps is profit-positive."""
        _alembic("upgrade", "0011")
        suffix = uuid.uuid4().hex[:8]

        with _connect() as conn:
            ids = _bootstrap_a2_registry(conn, suffix)
            conn.commit()

            observations = load_basis_fixture(
                FIXTURE_DIR / "SOLUSDT_BASIS_60obs_complete_trade.json"
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
            runner.run(conn)
            conn.commit()

            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT metadata FROM paper.fills
                    WHERE strategy_id = %s
                      AND metadata->>'a2_phase' = 'exit'
                    ORDER BY id;
                    """,
                    (ids["strategy_id"],),
                )
                rows = cur.fetchall()

        # 2 exit rows expected
        assert len(rows) == 2
        for (meta,) in rows:
            # Check 6: all P&L fields present
            assert "research_pnl_bps" in meta
            assert "research_gross_pnl_bps" in meta
            assert "research_round_trip_cost_bps" in meta
            assert "research_perp_pnl_bps" in meta
            assert "research_spot_pnl_bps" in meta
        # Both rows carry the SAME aggregate P&L (each leg's exit fill
        # records the entire trade's P&L for audit symmetry).
        gross_pnl = Decimal(rows[0][0]["research_gross_pnl_bps"])
        net_pnl = Decimal(rows[0][0]["research_pnl_bps"])
        cost = Decimal(rows[0][0]["research_round_trip_cost_bps"])
        # Check 5: research_pnl_bps profit-positive for this fixture
        # (perp went 100.85 → 100.00 = 84.28 bps profit on SHORT;
        #  spot flat; gross ≈ 84.28; cost 33.84; net ≈ 50.44 profit)
        assert gross_pnl > 0
        assert net_pnl > 0
        # Sanity: net = gross - cost
        assert net_pnl == gross_pnl - cost

    def test_re_entry_within_same_run_writes_8_fills(self, fresh_db):
        """Re-entry: two complete trades within one fixture, 4 fills each."""
        _alembic("upgrade", "0011")
        suffix = uuid.uuid4().hex[:8]

        with _connect() as conn:
            ids = _bootstrap_a2_registry(conn, suffix)
            conn.commit()

            observations = load_basis_fixture(
                FIXTURE_DIR / "SOLUSDT_BASIS_60obs_re_entry.json"
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

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM paper.fills WHERE strategy_id = %s;",
                    (ids["strategy_id"],),
                )
                fill_count = cur.fetchone()[0]

        # 2 entries, 2 exits, 2 legs each = 8 paper.fills rows
        assert summary.a2_intents_fired == 2
        assert summary.a2_exits_fired_basis_converged == 2
        assert fill_count == 8
        # No open positions at end (both trades closed)
        assert summary.positions_open_at_end_of_run == 0

    def test_trading_fills_unchanged_after_complete_trade(self, fresh_db):
        """Check 8: trading.fills is untouched by paper-research workflow."""
        _alembic("upgrade", "0011")
        suffix = uuid.uuid4().hex[:8]

        with _connect() as conn:
            ids = _bootstrap_a2_registry(conn, suffix)
            conn.commit()

            observations = load_basis_fixture(
                FIXTURE_DIR / "SOLUSDT_BASIS_60obs_complete_trade.json"
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
            runner.run(conn)
            conn.commit()

            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM trading.fills;")
                trading_count = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM paper.fills;")
                paper_count = cur.fetchone()[0]

        # Check 8: trading.fills untouched (firewall holds)
        assert trading_count == 0
        # paper.fills has the 4 expected rows
        assert paper_count == 4

    def test_exit_fill_shares_entry_a2_intent_uuid(self, fresh_db):
        """Q4 lock: exit fills share entry's a2_intent_uuid (a2_phase
        discriminates within a single trade lifecycle)."""
        _alembic("upgrade", "0011")
        suffix = uuid.uuid4().hex[:8]

        with _connect() as conn:
            ids = _bootstrap_a2_registry(conn, suffix)
            conn.commit()

            observations = load_basis_fixture(
                FIXTURE_DIR / "SOLUSDT_BASIS_60obs_complete_trade.json"
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
            runner.run(conn)
            conn.commit()

            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT metadata->>'a2_phase', metadata->>'a2_intent_uuid'
                    FROM paper.fills
                    WHERE strategy_id = %s
                    ORDER BY id;
                    """,
                    (ids["strategy_id"],),
                )
                rows = cur.fetchall()

        # 4 rows: 2 entry + 2 exit, all with same a2_intent_uuid
        assert len(rows) == 4
        phases = [r[0] for r in rows]
        uuids = [r[1] for r in rows]
        assert phases.count("entry") == 2
        assert phases.count("exit") == 2
        assert len(set(uuids)) == 1  # single shared a2_intent_uuid

    def test_constant_fixture_no_changes(self, fresh_db):
        """Check 1: entry-only-zero fixtures (no entries → no exits)
        behave correctly. Constant fixture still produces 0 entries,
        0 exits, 0 open positions."""
        _alembic("upgrade", "0011")
        suffix = uuid.uuid4().hex[:8]

        with _connect() as conn:
            ids = _bootstrap_a2_registry(conn, suffix)
            conn.commit()

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

        assert summary.a2_intents_fired == 0
        assert summary.exit_evaluations_total == 0
        assert summary.a2_exits_fired_basis_converged == 0
        assert summary.a2_exits_fired_time_forced == 0
        assert summary.positions_open_at_end_of_run == 0
