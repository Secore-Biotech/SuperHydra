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
