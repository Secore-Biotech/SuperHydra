"""Migration + firewall integration tests for paper.positions.

Day 28a deliverable. Verifies:
  - paper.positions exists after migration 0011
  - All CHECK constraints enforce (source_mode, promotion_eligible, qty != 0)
  - UNIQUE (strategy_id, instrument_id) enforces hard-block at DB level
  - Firewall: paper.positions is separate from trading.positions
"""
from __future__ import annotations

import uuid

import psycopg
import pytest

from tests.integration.test_migrations import (  # noqa: F401
    _alembic,
    _connect,
    fresh_db,
)


def _bootstrap_min(cur, suffix: str):
    """Minimal registry rows for migration tests."""
    suf = f"_{suffix}"
    cur.execute(
        "INSERT INTO registry.venues (venue_code, display_name, venue_type, status) "
        "VALUES (%s, 'Binance', 'cex_futures', 'active') RETURNING id;",
        (f"binance{suf}",),
    )
    venue_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO registry.assets (symbol, display_name, asset_type, decimals, status) "
        "VALUES (%s, 'SOL', 'crypto', 9, 'active') RETURNING id;",
        (f"SOL{suf}",),
    )
    sol_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO registry.assets (symbol, display_name, asset_type, decimals, status) "
        "VALUES (%s, 'USDT', 'stablecoin', 6, 'active') RETURNING id;",
        (f"USDT{suf}",),
    )
    usdt_id = cur.fetchone()[0]
    cur.execute(
        """INSERT INTO registry.strategies
            (name, display_name, current_phase, phase_entered_at,
             hypothesis_doc_path, config)
           VALUES (%s, 'Test', 'research', NOW(),
                   'docs/strategies/a2_basis_design_brief.md', '{}'::jsonb)
           RETURNING id;""",
        (f"test_strat{suf}",),
    )
    strategy_id = cur.fetchone()[0]
    cur.execute(
        """INSERT INTO registry.portfolios
            (portfolio_code, display_name, product_type, status)
           VALUES (%s, 'Test', 'paper', 'research') RETURNING id;""",
        (f"test_port{suf}",),
    )
    portfolio_id = cur.fetchone()[0]
    cur.execute(
        """INSERT INTO registry.accounts
            (venue_id, account_code, display_name, account_type, status)
           VALUES (%s, %s, 'Test', 'trading', 'active') RETURNING id;""",
        (venue_id, f"test_acct{suf}"),
    )
    account_id = cur.fetchone()[0]
    cur.execute(
        """INSERT INTO registry.instruments
            (instrument_code, display_name, venue_id, base_asset_id,
             quote_asset_id, instrument_type, status)
           VALUES (%s, 'SOL Perp', %s, %s, %s, 'perp', 'active')
           RETURNING id;""",
        (f"SOL_PERP{suf}", venue_id, sol_id, usdt_id),
    )
    instrument_id = cur.fetchone()[0]
    return strategy_id, portfolio_id, account_id, instrument_id


class TestMigration0011:
    def test_paper_positions_table_exists(self, fresh_db):
        _alembic("upgrade", "0011")
        with _connect() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'paper' AND table_name = 'positions';
            """)
            assert cur.fetchone() is not None

    def test_required_columns_present(self, fresh_db):
        _alembic("upgrade", "0011")
        with _connect() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'paper' AND table_name = 'positions';
            """)
            cols = {r[0] for r in cur.fetchall()}
        required = {
            "id", "paper_position_uuid", "source_mode",
            "strategy_id", "portfolio_id", "account_id", "instrument_id",
            "quantity", "avg_entry_price", "opened_at", "last_updated_at",
            "promotion_eligible", "metadata", "created_at",
        }
        assert required.issubset(cols)

    def test_source_mode_check_rejects_non_paper_research(self, fresh_db):
        _alembic("upgrade", "0011")
        suffix = uuid.uuid4().hex[:8]
        with _connect() as conn, conn.cursor() as cur:
            sid, pid, aid, iid = _bootstrap_min(cur, suffix)
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute(
                    """INSERT INTO paper.positions
                       (source_mode, strategy_id, portfolio_id, account_id,
                        instrument_id, quantity, avg_entry_price, opened_at)
                       VALUES ('TRADING', %s, %s, %s, %s, 10, 100, NOW());""",
                    (sid, pid, aid, iid),
                )

    def test_promotion_eligible_must_be_false(self, fresh_db):
        _alembic("upgrade", "0011")
        suffix = uuid.uuid4().hex[:8]
        with _connect() as conn, conn.cursor() as cur:
            sid, pid, aid, iid = _bootstrap_min(cur, suffix)
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute(
                    """INSERT INTO paper.positions
                       (source_mode, strategy_id, portfolio_id, account_id,
                        instrument_id, quantity, avg_entry_price, opened_at,
                        promotion_eligible)
                       VALUES ('PAPER_RESEARCH', %s, %s, %s, %s,
                               10, 100, NOW(), true);""",
                    (sid, pid, aid, iid),
                )

    def test_quantity_nonzero_check(self, fresh_db):
        _alembic("upgrade", "0011")
        suffix = uuid.uuid4().hex[:8]
        with _connect() as conn, conn.cursor() as cur:
            sid, pid, aid, iid = _bootstrap_min(cur, suffix)
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute(
                    """INSERT INTO paper.positions
                       (source_mode, strategy_id, portfolio_id, account_id,
                        instrument_id, quantity, avg_entry_price, opened_at)
                       VALUES ('PAPER_RESEARCH', %s, %s, %s, %s,
                               0, 100, NOW());""",
                    (sid, pid, aid, iid),
                )

    def test_unique_strategy_instrument_blocks_second_insert(self, fresh_db):
        _alembic("upgrade", "0011")
        suffix = uuid.uuid4().hex[:8]
        with _connect() as conn:
            with conn.cursor() as cur:
                sid, pid, aid, iid = _bootstrap_min(cur, suffix)
                cur.execute(
                    """INSERT INTO paper.positions
                       (source_mode, strategy_id, portfolio_id, account_id,
                        instrument_id, quantity, avg_entry_price, opened_at)
                       VALUES ('PAPER_RESEARCH', %s, %s, %s, %s,
                               10, 100, NOW());""",
                    (sid, pid, aid, iid),
                )
            conn.commit()
            with conn.cursor() as cur:
                with pytest.raises(psycopg.errors.UniqueViolation):
                    cur.execute(
                        """INSERT INTO paper.positions
                           (source_mode, strategy_id, portfolio_id, account_id,
                            instrument_id, quantity, avg_entry_price, opened_at)
                           VALUES ('PAPER_RESEARCH', %s, %s, %s, %s,
                                   -5, 101, NOW());""",
                        (sid, pid, aid, iid),
                    )


class TestFirewall:
    def test_paper_positions_in_paper_schema(self, fresh_db):
        _alembic("upgrade", "0011")
        with _connect() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT table_schema FROM information_schema.tables
                WHERE table_name = 'positions' AND table_schema = 'paper';
            """)
            assert cur.fetchone() is not None

    def test_positions_schema_still_exists_separately(self, fresh_db):
        """Migration 0008 created the `positions` schema with snapshots/lots/etc.
        That schema is firewalled separately from `paper`; both must coexist."""
        _alembic("upgrade", "0011")
        with _connect() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT schema_name FROM information_schema.schemata
                WHERE schema_name IN ('paper', 'positions');
            """)
            schemas = {r[0] for r in cur.fetchall()}
        assert "paper" in schemas
        assert "positions" in schemas

    def test_paper_positions_distinct_from_positions_schema(self, fresh_db):
        """paper.positions is a NEW table in the `paper` schema; it does not
        collide with any table in the pre-existing `positions` schema."""
        _alembic("upgrade", "0011")
        with _connect() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT table_schema, table_name FROM information_schema.tables
                WHERE table_name = 'positions';
            """)
            rows = cur.fetchall()
        # Exactly one row: paper.positions. The `positions` schema has tables
        # like position_snapshots, position_lots, etc., but no table literally
        # named `positions`.
        assert ("paper", "positions") in rows
        assert ("positions", "positions") not in rows
