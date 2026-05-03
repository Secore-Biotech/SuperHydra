"""Migration test harness.

Tests that migrations apply cleanly from zero database state, verify expected
state after each migration, and roll back cleanly where applicable.

Run with: pytest tests/integration/test_migrations.py -v

Requires Docker Compose Postgres running on localhost:5432.
"""
import os
import subprocess
from pathlib import Path

import psycopg
import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://superhydra:superhydra_dev_only@localhost:5432/superhydra",
)


def _alembic(*args: str) -> subprocess.CompletedProcess:
    """Run alembic command with the migration directory."""
    cmd = ["alembic", "-c", str(REPO_ROOT / "infra" / "migrations" / "alembic.ini")] + list(args)
    return subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _connect():
    """Connect to the dev database."""
    return psycopg.connect(DATABASE_URL)


@pytest.fixture(scope="function")
def fresh_db():
    """Drop all schemas and reset to migration zero. Yields connection."""
    # Reset to base (zero migrations)
    result = _alembic("downgrade", "base")
    if result.returncode != 0:
        # If alembic table doesn't exist or initial state, manually drop schemas
        with _connect() as conn:
            with conn.cursor() as cur:
                schemas = [
                    "validation", "feature_store", "market_data", "data_ingestion",
                    "audit", "risk", "positions", "trading", "accounting", "registry",
                ]
                for schema in schemas:
                    cur.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
                cur.execute("DROP TABLE IF EXISTS alembic_version")
                cur.execute("DROP FUNCTION IF EXISTS gen_uuidv7()")
            conn.commit()

    yield

    # Cleanup after test
    _alembic("downgrade", "base")


def test_0001_creates_all_schemas(fresh_db):
    """Migration 0001 must create exactly 10 schemas."""
    result = _alembic("upgrade", "0001")
    assert result.returncode == 0, f"Migration failed: {result.stderr}"

    expected_schemas = {
        "registry", "accounting", "trading", "positions", "risk",
        "audit", "data_ingestion", "market_data", "feature_store", "validation",
    }

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT schema_name FROM information_schema.schemata
                WHERE schema_name = ANY(%s)
            """, (list(expected_schemas),))
            found = {row[0] for row in cur.fetchall()}

    assert found == expected_schemas, f"Missing schemas: {expected_schemas - found}"


def test_0001_gen_uuidv7_format(fresh_db):
    """gen_uuidv7() must produce 36-char UUIDs with version 7 and valid variant."""
    _alembic("upgrade", "0001")

    with _connect() as conn:
        with conn.cursor() as cur:
            for _ in range(20):
                cur.execute("SELECT gen_uuidv7()::TEXT")
                uuid_text = cur.fetchone()[0]

                assert len(uuid_text) == 36, f"Wrong length: {uuid_text}"
                assert uuid_text[14] == "7", f"Wrong version: {uuid_text}"
                assert uuid_text[19] in "89ab", f"Wrong variant: {uuid_text}"


def test_0001_gen_uuidv7_uniqueness(fresh_db):
    """100k generated UUIDs must be unique."""
    _alembic("upgrade", "0001")

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT array_agg(gen_uuidv7()) FROM generate_series(1, 100000)")
            uuids = cur.fetchone()[0]

    assert len(set(uuids)) == 100000, f"Duplicates in 100k UUIDs: {100000 - len(set(uuids))} dups"


def test_0001_gen_uuidv7_time_ordering(fresh_db):
    """UUIDs generated across milliseconds must sort in generation order."""
    _alembic("upgrade", "0001")

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                DO $$
                DECLARE
                    uuid_1 UUID;
                    uuid_2 UUID;
                    uuid_3 UUID;
                BEGIN
                    uuid_1 := gen_uuidv7();
                    PERFORM pg_sleep(0.005);
                    uuid_2 := gen_uuidv7();
                    PERFORM pg_sleep(0.005);
                    uuid_3 := gen_uuidv7();

                    IF NOT (uuid_1 < uuid_2 AND uuid_2 < uuid_3) THEN
                        RAISE EXCEPTION 'time-ordering failed: %, %, %',
                            uuid_1, uuid_2, uuid_3;
                    END IF;
                END;
                $$;
            """)


def test_0001_extensions_installed(fresh_db):
    """Required extensions must be installed."""
    _alembic("upgrade", "0001")

    expected_extensions = {"timescaledb", "pgcrypto", "plpgsql"}

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT extname FROM pg_extension")
            installed = {row[0] for row in cur.fetchall()}

    missing = expected_extensions - installed
    assert not missing, f"Missing extensions: {missing}"


def test_0001_database_timezone_utc(fresh_db):
    """Database default timezone must be UTC."""
    _alembic("upgrade", "0001")

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SHOW TIMEZONE")
            tz = cur.fetchone()[0]

    assert tz == "UTC", f"Wrong timezone: {tz}"


def test_0001_downgrade_clean(fresh_db):
    """Downgrade from 0001 to base must drop all schemas and the function."""
    _alembic("upgrade", "0001")
    result = _alembic("downgrade", "base")
    assert result.returncode == 0, f"Downgrade failed: {result.stderr}"

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT schema_name FROM information_schema.schemata
                WHERE schema_name IN (
                    'registry', 'accounting', 'trading', 'positions', 'risk',
                    'audit', 'data_ingestion', 'market_data', 'feature_store', 'validation'
                )
            """)
            remaining = cur.fetchall()

    assert not remaining, f"Schemas not dropped: {remaining}"

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT proname FROM pg_proc WHERE proname = 'gen_uuidv7'
            """)
            functions = cur.fetchall()

    assert not functions, "gen_uuidv7() not dropped on downgrade"


# ============================================================
# Migration 0002 tests: registry_core
# ============================================================


def test_0002_creates_all_registry_tables(fresh_db):
    """Migration 0002 must create 6 registry tables."""
    result = _alembic("upgrade", "0002")
    assert result.returncode == 0, f"Migration failed: {result.stderr}"

    expected_tables = {
        "venues", "assets", "instruments", "accounts", "portfolios", "strategies"
    }

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'registry' AND table_name = ANY(%s)
            """, (list(expected_tables),))
            found = {row[0] for row in cur.fetchall()}

    assert found == expected_tables, f"Missing tables: {expected_tables - found}"


def test_0002_venue_constraints(fresh_db):
    """venue_type CHECK constraint rejects invalid types."""
    _alembic("upgrade", "0002")

    with _connect() as conn:
        with conn.cursor() as cur:
            # Valid insert succeeds
            cur.execute("""
                INSERT INTO registry.venues (venue_code, display_name, venue_type, status)
                VALUES ('test_venue', 'Test Venue', 'cex_futures', 'active')
                RETURNING id
            """)
            assert cur.fetchone()[0] is not None
            conn.commit()

            # Invalid venue_type rejected
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("""
                    INSERT INTO registry.venues (venue_code, display_name, venue_type, status)
                    VALUES ('bad_venue', 'Bad', 'invalid_type', 'active')
                """)
            conn.rollback()

            # Invalid status rejected
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("""
                    INSERT INTO registry.venues (venue_code, display_name, venue_type, status)
                    VALUES ('bad_venue2', 'Bad', 'cex_futures', 'invalid_status')
                """)
            conn.rollback()


def test_0002_venue_code_unique(fresh_db):
    """venue_code UNIQUE constraint rejects duplicates."""
    _alembic("upgrade", "0002")

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO registry.venues (venue_code, display_name, venue_type, status)
                VALUES ('binance_futures', 'Binance Futures', 'cex_futures', 'active')
            """)
            conn.commit()

            with pytest.raises(psycopg.errors.UniqueViolation):
                cur.execute("""
                    INSERT INTO registry.venues (venue_code, display_name, venue_type, status)
                    VALUES ('binance_futures', 'Duplicate', 'cex_futures', 'active')
                """)
            conn.rollback()


def test_0002_asset_unique_nulls_not_distinct(fresh_db):
    """assets uses UNIQUE NULLS NOT DISTINCT — same symbol with NULL chain is unique."""
    _alembic("upgrade", "0002")

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO registry.assets (symbol, display_name, asset_type, decimals, status)
                VALUES ('BTC', 'Bitcoin', 'crypto', 8, 'active')
            """)
            conn.commit()

            # Same symbol with NULL chain should fail
            with pytest.raises(psycopg.errors.UniqueViolation):
                cur.execute("""
                    INSERT INTO registry.assets (symbol, display_name, asset_type, decimals, status)
                    VALUES ('BTC', 'Bitcoin Duplicate', 'crypto', 8, 'active')
                """)
            conn.rollback()

            # Same symbol with different chain should succeed
            cur.execute("""
                INSERT INTO registry.assets (symbol, display_name, asset_type, decimals, chain, status)
                VALUES ('BTC', 'Wrapped Bitcoin Polygon', 'crypto', 8, 'polygon', 'active')
                RETURNING id
            """)
            assert cur.fetchone()[0] is not None
            conn.commit()


def test_0002_instrument_option_constraint(fresh_db):
    """Options must have expiry, strike, and option_type."""
    _alembic("upgrade", "0002")

    with _connect() as conn:
        with conn.cursor() as cur:
            # Set up a venue first
            cur.execute("""
                INSERT INTO registry.venues (venue_code, display_name, venue_type, status)
                VALUES ('deribit', 'Deribit', 'cex_options', 'active')
                RETURNING id
            """)
            venue_id = cur.fetchone()[0]
            conn.commit()

            # Option without expiry rejected
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("""
                    INSERT INTO registry.instruments
                        (instrument_code, display_name, venue_id, instrument_type, status)
                    VALUES ('BTC-OPT-BAD', 'Bad Option', %s, 'option', 'active')
                """, (venue_id,))
            conn.rollback()

            # Option with all required fields succeeds
            cur.execute("""
                INSERT INTO registry.instruments
                    (instrument_code, display_name, venue_id, instrument_type, status,
                     expiry, strike, option_type)
                VALUES ('BTC-50000-CALL-2026-12-26', 'BTC Call', %s, 'option', 'active',
                        '2026-12-26 08:00:00+00', 50000, 'call')
                RETURNING id
            """, (venue_id,))
            assert cur.fetchone()[0] is not None
            conn.commit()


def test_0002_account_self_reference(fresh_db):
    """Accounts can reference parent accounts via parent_account_id."""
    _alembic("upgrade", "0002")

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO registry.venues (venue_code, display_name, venue_type, status)
                VALUES ('binance_futures', 'Binance Futures', 'cex_futures', 'active')
                RETURNING id
            """)
            venue_id = cur.fetchone()[0]
            conn.commit()

            # Master account
            cur.execute("""
                INSERT INTO registry.accounts (venue_id, account_code, display_name, account_type, status)
                VALUES (%s, 'binance_master', 'Master', 'trading', 'active')
                RETURNING id
            """, (venue_id,))
            master_id = cur.fetchone()[0]
            conn.commit()

            # Subaccount references master
            cur.execute("""
                INSERT INTO registry.accounts
                    (venue_id, account_code, display_name, account_type, parent_account_id, status)
                VALUES (%s, 'binance_subacct_mn', 'MN Subacct', 'subaccount', %s, 'active')
                RETURNING id, parent_account_id
            """, (venue_id, master_id))
            sub_id, parent = cur.fetchone()
            assert parent == master_id
            conn.commit()


def test_0002_updated_at_trigger(fresh_db):
    """updated_at must auto-update on row update."""
    _alembic("upgrade", "0002")

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO registry.venues (venue_code, display_name, venue_type, status)
                VALUES ('test_trigger', 'Test', 'cex_futures', 'active')
                RETURNING id, created_at, updated_at
            """)
            venue_id, created_at, initial_updated = cur.fetchone()
            conn.commit()

            # Sleep briefly then update
            import time
            time.sleep(0.01)

            cur.execute("""
                UPDATE registry.venues SET display_name = 'Test Updated'
                WHERE id = %s
                RETURNING updated_at
            """, (venue_id,))
            new_updated = cur.fetchone()[0]
            conn.commit()

            assert new_updated > initial_updated, \
                f"updated_at not advanced: {initial_updated} -> {new_updated}"


def test_0002_strategy_phase_constraint(fresh_db):
    """current_phase CHECK constraint enforces valid values."""
    _alembic("upgrade", "0002")

    with _connect() as conn:
        with conn.cursor() as cur:
            # Valid phase succeeds
            cur.execute("""
                INSERT INTO registry.strategies
                    (name, display_name, current_phase, phase_entered_at, hypothesis_doc_path)
                VALUES ('mn_ls_test', 'MN L/S Test', 'research', NOW(), 'docs/hypotheses/mn_ls.md')
                RETURNING id
            """)
            assert cur.fetchone()[0] is not None
            conn.commit()

            # Invalid phase rejected
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("""
                    INSERT INTO registry.strategies
                        (name, display_name, current_phase, phase_entered_at, hypothesis_doc_path)
                    VALUES ('mn_ls_bad', 'Bad', 'invalid_phase', NOW(), 'docs/h.md')
                """)
            conn.rollback()


def test_0002_downgrade_clean(fresh_db):
    """Downgrade to 0001 must drop all 6 registry tables."""
    _alembic("upgrade", "0002")
    result = _alembic("downgrade", "0001")
    assert result.returncode == 0, f"Downgrade failed: {result.stderr}"

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'registry'
            """)
            remaining = cur.fetchall()

    assert not remaining, f"Tables not dropped: {remaining}"
