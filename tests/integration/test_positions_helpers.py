"""Unit tests for paper.positions helpers.

These are integration tests in the sense that they touch the DB, but they
live under strategies/a2_basis/tests/unit/ to keep them close to the module
they test. The full integration suite under tests/integration/ exercises the
runner end-to-end (Day 28a appends to test_a2_paper_research_runner.py).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import psycopg
import pytest

from strategies.a2_basis.data.positions import (
    PaperPosition,
    get_open_position,
    open_position,
    paper_position_count,
)
from tests.integration.test_migrations import (  # noqa: F401
    _alembic,
    _connect,
    fresh_db,
)


def _bootstrap_minimal(conn, suffix: str) -> dict:
    """Minimal registry rows for position tests. Inline get-or-create."""
    suf = f"_{suffix}"
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO registry.venues "
            "(venue_code, display_name, venue_type, status) "
            "VALUES ('binance', 'Binance', 'cex_futures', 'active') "
            "RETURNING id;"
        )
        venue_id = cur.fetchone()[0]

        cur.execute(
            "INSERT INTO registry.assets "
            "(symbol, display_name, asset_type, decimals, status) "
            "VALUES ('SOL', 'Solana', 'crypto', 9, 'active') "
            "RETURNING id;"
        )
        sol_id = cur.fetchone()[0]

        cur.execute(
            "INSERT INTO registry.assets "
            "(symbol, display_name, asset_type, decimals, status) "
            "VALUES ('USDT', 'Tether USD', 'stablecoin', 6, 'active') "
            "RETURNING id;"
        )
        usdt_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO registry.strategies
              (name, display_name, current_phase, phase_entered_at,
               hypothesis_doc_path, config)
            VALUES (%s, 'A2 Basis', 'research', NOW(),
                    'docs/strategies/a2_basis_design_brief.md', '{}'::jsonb)
            RETURNING id;
            """,
            (f"a2_basis_pos_test{suf}",),
        )
        strategy_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO registry.portfolios
              (portfolio_code, display_name, product_type, status)
            VALUES (%s, 'A2 Pos Test', 'paper', 'research')
            RETURNING id;
            """,
            (f"a2_pos_test{suf}",),
        )
        portfolio_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO registry.accounts
              (venue_id, account_code, display_name, account_type, status)
            VALUES (%s, %s, 'A2 Pos Acct', 'trading', 'active')
            RETURNING id;
            """,
            (venue_id, f"a2_pos_acct{suf}"),
        )
        account_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO registry.instruments
              (instrument_code, display_name, venue_id, base_asset_id,
               quote_asset_id, instrument_type, status)
            VALUES (%s, 'SOL Perp', %s, %s, %s, 'perp', 'active')
            RETURNING id;
            """,
            (f"SOLUSDT_postest{suf}", venue_id, sol_id, usdt_id),
        )
        perp_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO registry.instruments
              (instrument_code, display_name, venue_id, base_asset_id,
               quote_asset_id, instrument_type, status)
            VALUES (%s, 'SOL Spot', %s, %s, %s, 'spot', 'active')
            RETURNING id;
            """,
            (f"SOLUSDT_SPOT_postest{suf}", venue_id, sol_id, usdt_id),
        )
        spot_id = cur.fetchone()[0]

    return {
        "venue_id": venue_id,
        "strategy_id": strategy_id,
        "portfolio_id": portfolio_id,
        "account_id": account_id,
        "perp_id": perp_id,
        "spot_id": spot_id,
    }


# ═══════════════════════════════════════════════════════════════════════
# get_open_position
# ═══════════════════════════════════════════════════════════════════════


def test_get_open_position_returns_none_when_no_position(fresh_db):
    _alembic("upgrade", "0011")
    suffix = uuid.uuid4().hex[:8]
    with _connect() as conn:
        ids = _bootstrap_minimal(conn, suffix)
        result = get_open_position(
            conn,
            strategy_id=ids["strategy_id"],
            instrument_id=ids["perp_id"],
        )
        assert result is None


# ═══════════════════════════════════════════════════════════════════════
# open_position
# ═══════════════════════════════════════════════════════════════════════


def test_open_position_inserts_and_returns_uuid(fresh_db):
    _alembic("upgrade", "0011")
    suffix = uuid.uuid4().hex[:8]
    with _connect() as conn:
        ids = _bootstrap_minimal(conn, suffix)
        pos_uuid = open_position(
            conn,
            strategy_id=ids["strategy_id"],
            portfolio_id=ids["portfolio_id"],
            account_id=ids["account_id"],
            instrument_id=ids["perp_id"],
            quantity=Decimal("-10.0"),  # short
            avg_entry_price=Decimal("150.00"),
            opened_at=datetime(2024, 3, 20, 12, 0, 0, tzinfo=timezone.utc),
            metadata={"a2_intent_uuid": "test-uuid", "a2_leg": "perp"},
        )
        conn.commit()
        assert isinstance(pos_uuid, str)
        assert len(pos_uuid) > 10


def test_open_position_then_get_returns_inserted_row(fresh_db):
    _alembic("upgrade", "0011")
    suffix = uuid.uuid4().hex[:8]
    with _connect() as conn:
        ids = _bootstrap_minimal(conn, suffix)
        open_position(
            conn,
            strategy_id=ids["strategy_id"],
            portfolio_id=ids["portfolio_id"],
            account_id=ids["account_id"],
            instrument_id=ids["perp_id"],
            quantity=Decimal("-10.0"),
            avg_entry_price=Decimal("150.00"),
            opened_at=datetime(2024, 3, 20, 12, 0, 0, tzinfo=timezone.utc),
            metadata={"a2_intent_uuid": "test-uuid-1", "a2_leg": "perp"},
        )
        conn.commit()

        pos = get_open_position(
            conn,
            strategy_id=ids["strategy_id"],
            instrument_id=ids["perp_id"],
        )
        assert pos is not None
        assert pos.quantity == Decimal("-10.0")
        assert pos.avg_entry_price == Decimal("150.00")
        assert pos.metadata["a2_intent_uuid"] == "test-uuid-1"
        assert pos.metadata["a2_leg"] == "perp"


def test_open_position_zero_quantity_raises(fresh_db):
    _alembic("upgrade", "0011")
    suffix = uuid.uuid4().hex[:8]
    with _connect() as conn:
        ids = _bootstrap_minimal(conn, suffix)
        with pytest.raises(ValueError, match="non-zero quantity"):
            open_position(
                conn,
                strategy_id=ids["strategy_id"],
                portfolio_id=ids["portfolio_id"],
                account_id=ids["account_id"],
                instrument_id=ids["perp_id"],
                quantity=Decimal("0"),
                avg_entry_price=Decimal("150.00"),
                opened_at=datetime(2024, 3, 20, tzinfo=timezone.utc),
                metadata={},
            )


def test_open_position_duplicate_strategy_instrument_raises(fresh_db):
    """UNIQUE (strategy_id, instrument_id) is the DB-level hard-block backstop."""
    _alembic("upgrade", "0011")
    suffix = uuid.uuid4().hex[:8]
    with _connect() as conn:
        ids = _bootstrap_minimal(conn, suffix)
        open_position(
            conn,
            strategy_id=ids["strategy_id"],
            portfolio_id=ids["portfolio_id"],
            account_id=ids["account_id"],
            instrument_id=ids["perp_id"],
            quantity=Decimal("-10.0"),
            avg_entry_price=Decimal("150.00"),
            opened_at=datetime(2024, 3, 20, tzinfo=timezone.utc),
            metadata={"a2_intent_uuid": "first", "a2_leg": "perp"},
        )
        conn.commit()

        with pytest.raises(psycopg.errors.UniqueViolation):
            open_position(
                conn,
                strategy_id=ids["strategy_id"],
                portfolio_id=ids["portfolio_id"],
                account_id=ids["account_id"],
                instrument_id=ids["perp_id"],
                quantity=Decimal("-5.0"),
                avg_entry_price=Decimal("151.00"),
                opened_at=datetime(2024, 3, 20, 12, 1, tzinfo=timezone.utc),
                metadata={"a2_intent_uuid": "second", "a2_leg": "perp"},
            )


def test_open_position_different_instruments_no_conflict(fresh_db):
    """Same strategy, different instrument: both positions can coexist (perp + spot)."""
    _alembic("upgrade", "0011")
    suffix = uuid.uuid4().hex[:8]
    with _connect() as conn:
        ids = _bootstrap_minimal(conn, suffix)
        # Open perp leg
        open_position(
            conn,
            strategy_id=ids["strategy_id"],
            portfolio_id=ids["portfolio_id"],
            account_id=ids["account_id"],
            instrument_id=ids["perp_id"],
            quantity=Decimal("-10.0"),
            avg_entry_price=Decimal("150.00"),
            opened_at=datetime(2024, 3, 20, tzinfo=timezone.utc),
            metadata={"a2_intent_uuid": "uuid-1", "a2_leg": "perp"},
        )
        # Open spot leg — same intent, different instrument
        open_position(
            conn,
            strategy_id=ids["strategy_id"],
            portfolio_id=ids["portfolio_id"],
            account_id=ids["account_id"],
            instrument_id=ids["spot_id"],
            quantity=Decimal("10.0"),
            avg_entry_price=Decimal("149.50"),
            opened_at=datetime(2024, 3, 20, tzinfo=timezone.utc),
            metadata={"a2_intent_uuid": "uuid-1", "a2_leg": "spot"},
        )
        conn.commit()
        assert paper_position_count(conn) == 2


# ═══════════════════════════════════════════════════════════════════════
# paper_position_count
# ═══════════════════════════════════════════════════════════════════════


def test_paper_position_count_zero_when_empty(fresh_db):
    _alembic("upgrade", "0011")
    with _connect() as conn:
        assert paper_position_count(conn) == 0


def test_paper_position_count_filter_by_strategy(fresh_db):
    _alembic("upgrade", "0011")
    suffix = uuid.uuid4().hex[:8]
    with _connect() as conn:
        ids = _bootstrap_minimal(conn, suffix)
        open_position(
            conn,
            strategy_id=ids["strategy_id"],
            portfolio_id=ids["portfolio_id"],
            account_id=ids["account_id"],
            instrument_id=ids["perp_id"],
            quantity=Decimal("-10.0"),
            avg_entry_price=Decimal("150.00"),
            opened_at=datetime(2024, 3, 20, tzinfo=timezone.utc),
            metadata={},
        )
        conn.commit()
        assert paper_position_count(conn, strategy_id=ids["strategy_id"]) == 1
        # Unrelated strategy id: zero
        assert paper_position_count(conn, strategy_id=999999) == 0
