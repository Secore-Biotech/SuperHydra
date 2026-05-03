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


# ============================================================
# Migration 0003 tests: registry_market_structure
# ============================================================

from decimal import Decimal


def _setup_basic_registry(cur):
    """Helper: insert a venue + asset + instrument + account for tests."""
    cur.execute("""
        INSERT INTO registry.venues (venue_code, display_name, venue_type, status)
        VALUES ('binance_futures', 'Binance Futures', 'cex_futures', 'active')
        RETURNING id
    """)
    venue_id = cur.fetchone()[0]

    cur.execute("""
        INSERT INTO registry.assets (symbol, display_name, asset_type, decimals, status)
        VALUES ('BTC', 'Bitcoin', 'crypto', 8, 'active')
        RETURNING id
    """)
    btc_id = cur.fetchone()[0]

    cur.execute("""
        INSERT INTO registry.assets (symbol, display_name, asset_type, decimals, status)
        VALUES ('USDT', 'Tether', 'stablecoin', 6, 'active')
        RETURNING id
    """)
    usdt_id = cur.fetchone()[0]

    cur.execute("""
        INSERT INTO registry.instruments
            (instrument_code, display_name, venue_id, base_asset_id, quote_asset_id, instrument_type, status)
        VALUES ('BTCUSDT-PERP-BINANCE', 'BTC USDT Perp', %s, %s, %s, 'perp', 'active')
        RETURNING id
    """, (venue_id, btc_id, usdt_id))
    instrument_id = cur.fetchone()[0]

    cur.execute("""
        INSERT INTO registry.accounts (venue_id, account_code, display_name, account_type, status)
        VALUES (%s, 'binance_master', 'Master', 'trading', 'active')
        RETURNING id
    """, (venue_id,))
    account_id = cur.fetchone()[0]

    return venue_id, btc_id, usdt_id, instrument_id, account_id


def _setup_vendor(cur, name='binance_api'):
    """Helper: insert a vendor row."""
    cur.execute("""
        INSERT INTO registry.vendors (name, data_types, status, verified_status)
        VALUES (%s, ARRAY['ohlcv', 'trades', 'funding_rate'], 'active', 'VERIFIED')
        RETURNING id
    """, (name,))
    return cur.fetchone()[0]


def test_0003_creates_all_tables(fresh_db):
    """Migration 0003 must create 7 tables."""
    result = _alembic("upgrade", "0003")
    assert result.returncode == 0, f"Migration failed: {result.stderr}"

    expected_tables = {
        "vendors", "symbol_translations", "instrument_specs_history", "fee_schedules",
        "asset_clusters", "asset_cluster_memberships", "venue_capabilities",
    }

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'registry' AND table_name = ANY(%s)
            """, (list(expected_tables),))
            found = {row[0] for row in cur.fetchall()}

    assert found == expected_tables, f"Missing tables: {expected_tables - found}"


def test_0003_btree_gist_extension(fresh_db):
    """btree_gist extension must be installed."""
    _alembic("upgrade", "0003")

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT extname FROM pg_extension WHERE extname = 'btree_gist'")
            assert cur.fetchone() is not None, "btree_gist not installed"


def test_0003_vendor_separate_from_venue(fresh_db):
    """vendors and venues are independently registered; symbol_translations references vendors."""
    _alembic("upgrade", "0003")

    with _connect() as conn:
        with conn.cursor() as cur:
            _setup_basic_registry(cur)
            conn.commit()

            # Tardis is a vendor only, not a venue
            cur.execute("""
                INSERT INTO registry.vendors (name, data_types, status, verified_status)
                VALUES ('tardis', ARRAY['l2_orderbook', 'trades'], 'pending', 'UNVERIFIED')
                RETURNING id
            """)
            tardis_id = cur.fetchone()[0]
            conn.commit()

            # Tardis is NOT in venues
            cur.execute("SELECT id FROM registry.venues WHERE venue_code = 'tardis'")
            assert cur.fetchone() is None

            # symbol_translations references vendors
            cur.execute("""
                SELECT confrelid::regclass::text
                FROM pg_constraint
                WHERE conname LIKE '%symbol_translations%'
                  AND confrelid IS NOT NULL
                  AND contype = 'f'
            """)
            referenced = {row[0] for row in cur.fetchall()}
            assert 'registry.vendors' in referenced, \
                f"symbol_translations should reference registry.vendors, found: {referenced}"


def test_0003_overlapping_specs_rejected(fresh_db):
    """Exclusion constraint prevents overlapping instrument_specs_history ranges."""
    _alembic("upgrade", "0003")

    with _connect() as conn:
        with conn.cursor() as cur:
            _, _, _, instrument_id, _ = _setup_basic_registry(cur)
            conn.commit()

            cur.execute("""
                INSERT INTO registry.instrument_specs_history
                    (instrument_id, tick_size, effective_from, effective_to, source)
                VALUES (%s, 0.10, '2024-01-01 00:00:00+00', '2025-06-15 00:00:00+00', 'binance_api')
            """, (instrument_id,))
            conn.commit()

            # Overlapping range rejected
            with pytest.raises(psycopg.errors.ExclusionViolation):
                cur.execute("""
                    INSERT INTO registry.instrument_specs_history
                        (instrument_id, tick_size, effective_from, effective_to, source)
                    VALUES (%s, 0.05, '2025-01-01 00:00:00+00', '2026-01-01 00:00:00+00', 'binance_api')
                """, (instrument_id,))
            conn.rollback()

            # Non-overlapping range (after first ends) accepted
            cur.execute("""
                INSERT INTO registry.instrument_specs_history
                    (instrument_id, tick_size, effective_from, source)
                VALUES (%s, 0.01, '2025-06-15 00:00:00+00', 'binance_api')
                RETURNING id
            """, (instrument_id,))
            assert cur.fetchone()[0] is not None
            conn.commit()


def test_0003_historical_lookup_with_effective_to(fresh_db):
    """Historical lookup uses both effective_from and effective_to. Returns Decimal."""
    _alembic("upgrade", "0003")

    with _connect() as conn:
        with conn.cursor() as cur:
            _, _, _, instrument_id, _ = _setup_basic_registry(cur)
            conn.commit()

            # Spec 1: 2024-01-01 to 2025-06-15 (closed range), tick = 0.10
            cur.execute("""
                INSERT INTO registry.instrument_specs_history
                    (instrument_id, tick_size, effective_from, effective_to, source)
                VALUES (%s, 0.10, '2024-01-01 00:00:00+00', '2025-06-15 00:00:00+00', 'binance_api')
            """, (instrument_id,))

            # Spec 2: 2025-06-15 to NULL (active), tick = 0.01
            cur.execute("""
                INSERT INTO registry.instrument_specs_history
                    (instrument_id, tick_size, effective_from, effective_to, source)
                VALUES (%s, 0.01, '2025-06-15 00:00:00+00', NULL, 'binance_api')
            """, (instrument_id,))
            conn.commit()

            # Lookup at 2025-01-01 should return tick=0.10 (during spec 1's range)
            cur.execute("""
                SELECT tick_size FROM registry.instrument_specs_history
                WHERE instrument_id = %s
                  AND effective_from <= '2025-01-01 00:00:00+00'
                  AND (effective_to IS NULL OR effective_to > '2025-01-01 00:00:00+00')
            """, (instrument_id,))
            tick = cur.fetchone()[0]
            assert tick == Decimal("0.10"), f"Expected Decimal('0.10') at 2025-01-01, got {tick} (type {type(tick)})"

            # Lookup at 2026-01-01 should return tick=0.01 (during spec 2's range)
            cur.execute("""
                SELECT tick_size FROM registry.instrument_specs_history
                WHERE instrument_id = %s
                  AND effective_from <= '2026-01-01 00:00:00+00'
                  AND (effective_to IS NULL OR effective_to > '2026-01-01 00:00:00+00')
            """, (instrument_id,))
            tick = cur.fetchone()[0]
            assert tick == Decimal("0.01"), f"Expected Decimal('0.01') at 2026-01-01, got {tick}"


def test_0003_positive_value_constraints(fresh_db):
    """tick_size, lot_size, contract_size must be > 0; min_notional must be >= 0."""
    _alembic("upgrade", "0003")

    with _connect() as conn:
        with conn.cursor() as cur:
            _, _, _, instrument_id, _ = _setup_basic_registry(cur)
            conn.commit()

            # Negative tick_size rejected
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("""
                    INSERT INTO registry.instrument_specs_history
                        (instrument_id, tick_size, effective_from, source)
                    VALUES (%s, -0.01, '2024-01-01 00:00:00+00', 'test')
                """, (instrument_id,))
            conn.rollback()

            # Zero tick_size rejected
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("""
                    INSERT INTO registry.instrument_specs_history
                        (instrument_id, tick_size, effective_from, source)
                    VALUES (%s, 0, '2024-01-01 00:00:00+00', 'test')
                """, (instrument_id,))
            conn.rollback()

            # Zero min_notional accepted (>= 0 is allowed)
            cur.execute("""
                INSERT INTO registry.instrument_specs_history
                    (instrument_id, tick_size, min_notional, effective_from, source)
                VALUES (%s, 0.01, 0, '2024-01-01 00:00:00+00', 'test')
                RETURNING id
            """, (instrument_id,))
            assert cur.fetchone()[0] is not None
            conn.commit()


def test_0003_negative_maker_fee_allowed(fresh_db):
    """Maker fee can be negative (rebate). Taker fee can also be negative in extreme cases."""
    _alembic("upgrade", "0003")

    with _connect() as conn:
        with conn.cursor() as cur:
            venue_id, _, _, _, _ = _setup_basic_registry(cur)
            conn.commit()

            # Negative maker fee (rebate) accepted
            cur.execute("""
                INSERT INTO registry.fee_schedules
                    (venue_id, instrument_type, maker_fee_bps, taker_fee_bps, effective_from, source)
                VALUES (%s, 'perp', -1.0, 4.0, '2024-01-01 00:00:00+00', 'binance_vip')
                RETURNING id
            """, (venue_id,))
            assert cur.fetchone()[0] is not None
            conn.commit()

            # Out of range rejected
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("""
                    INSERT INTO registry.fee_schedules
                        (venue_id, instrument_type, maker_fee_bps, taker_fee_bps, effective_from, source)
                    VALUES (%s, 'perp', -2000.0, 4.0, '2024-02-01 00:00:00+00', 'bad_data')
                """, (venue_id,))
            conn.rollback()


def test_0003_fee_schedule_instrument_specific(fresh_db):
    """fee_schedules can have instrument-specific entries via instrument_id."""
    _alembic("upgrade", "0003")

    with _connect() as conn:
        with conn.cursor() as cur:
            venue_id, _, _, instrument_id, _ = _setup_basic_registry(cur)
            conn.commit()

            # Instrument-specific fee
            cur.execute("""
                INSERT INTO registry.fee_schedules
                    (venue_id, instrument_id, maker_fee_bps, taker_fee_bps, effective_from, source)
                VALUES (%s, %s, 0.5, 3.0, '2024-01-01 00:00:00+00', 'binance_btc_promotion')
                RETURNING id
            """, (venue_id, instrument_id))
            assert cur.fetchone()[0] is not None
            conn.commit()


def test_0003_asset_cluster_membership_unique_active(fresh_db):
    """Each asset has at most one active cluster membership; exclusion constraint prevents overlap."""
    _alembic("upgrade", "0003")

    with _connect() as conn:
        with conn.cursor() as cur:
            _, btc_id, _, _, _ = _setup_basic_registry(cur)

            cur.execute("""
                INSERT INTO registry.asset_clusters (cluster_code, display_name)
                VALUES ('layer_1', 'Layer 1'), ('defi', 'DeFi')
            """)
            cur.execute("SELECT id FROM registry.asset_clusters WHERE cluster_code = 'layer_1'")
            cluster_l1 = cur.fetchone()[0]
            cur.execute("SELECT id FROM registry.asset_clusters WHERE cluster_code = 'defi'")
            cluster_defi = cur.fetchone()[0]
            conn.commit()

            # First active membership succeeds
            cur.execute("""
                INSERT INTO registry.asset_cluster_memberships
                    (asset_id, cluster_id, effective_from)
                VALUES (%s, %s, '2024-01-01 00:00:00+00')
            """, (btc_id, cluster_l1))
            conn.commit()

            # Overlapping membership rejected
            with pytest.raises(psycopg.errors.ExclusionViolation):
                cur.execute("""
                    INSERT INTO registry.asset_cluster_memberships
                        (asset_id, cluster_id, effective_from)
                    VALUES (%s, %s, '2024-06-01 00:00:00+00')
                """, (btc_id, cluster_defi))
            conn.rollback()

            # Closing the first and adding a new one succeeds
            cur.execute("""
                UPDATE registry.asset_cluster_memberships
                SET effective_to = '2024-06-01 00:00:00+00'
                WHERE asset_id = %s
            """, (btc_id,))
            cur.execute("""
                INSERT INTO registry.asset_cluster_memberships
                    (asset_id, cluster_id, effective_from)
                VALUES (%s, %s, '2024-06-01 00:00:00+00')
                RETURNING id
            """, (btc_id, cluster_defi))
            assert cur.fetchone()[0] is not None
            conn.commit()


def test_0003_venue_capabilities_effective_dated(fresh_db):
    """venue_capabilities effective-dated; overlap rejected; non-overlapping accepted."""
    _alembic("upgrade", "0003")

    with _connect() as conn:
        with conn.cursor() as cur:
            venue_id, _, _, _, _ = _setup_basic_registry(cur)
            conn.commit()

            cur.execute("""
                INSERT INTO registry.venue_capabilities
                    (venue_id, max_client_order_id_len, supports_post_only, effective_from, effective_to)
                VALUES (%s, 32, FALSE, '2024-01-01 00:00:00+00', '2024-12-01 00:00:00+00')
                RETURNING id
            """, (venue_id,))
            assert cur.fetchone()[0] is not None
            conn.commit()

            # Overlapping rejected
            with pytest.raises(psycopg.errors.ExclusionViolation):
                cur.execute("""
                    INSERT INTO registry.venue_capabilities
                        (venue_id, max_client_order_id_len, effective_from)
                    VALUES (%s, 36, '2024-06-01 00:00:00+00')
                """, (venue_id,))
            conn.rollback()

            # Non-overlapping (after first ends) accepted
            cur.execute("""
                INSERT INTO registry.venue_capabilities
                    (venue_id, max_client_order_id_len, supports_post_only, effective_from)
                VALUES (%s, 36, TRUE, '2024-12-01 00:00:00+00')
                RETURNING id
            """, (venue_id,))
            assert cur.fetchone()[0] is not None
            conn.commit()


def test_0003_margin_mode_includes_none(fresh_db):
    """margin_mode accepts 'none' for spot/cash instruments."""
    _alembic("upgrade", "0003")

    with _connect() as conn:
        with conn.cursor() as cur:
            _, _, _, instrument_id, _ = _setup_basic_registry(cur)
            conn.commit()

            cur.execute("""
                INSERT INTO registry.instrument_specs_history
                    (instrument_id, tick_size, margin_mode, effective_from, source)
                VALUES (%s, 0.01, 'none', '2024-01-01 00:00:00+00', 'test')
                RETURNING id
            """, (instrument_id,))
            assert cur.fetchone()[0] is not None
            conn.commit()


def test_0003_downgrade_clean(fresh_db):
    """Downgrade from 0003 to 0002 must drop all 7 tables; core registry preserved."""
    _alembic("upgrade", "0003")
    result = _alembic("downgrade", "0002")
    assert result.returncode == 0, f"Downgrade failed: {result.stderr}"

    market_structure_tables = {
        "vendors", "symbol_translations", "instrument_specs_history", "fee_schedules",
        "asset_clusters", "asset_cluster_memberships", "venue_capabilities",
    }
    core_tables = {
        "venues", "assets", "instruments", "accounts", "portfolios", "strategies"
    }

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'registry'
            """)
            remaining = {row[0] for row in cur.fetchall()}

    leaked = remaining & market_structure_tables
    assert not leaked, f"Market structure tables not dropped: {leaked}"

    missing_core = core_tables - remaining
    assert not missing_core, f"Core tables wrongly dropped: {missing_core}"


# ============================================================
# Migration 0004 tests: registry_strategy_model
# ============================================================


def _setup_strategy_for_promotion(cur):
    """Helper: insert a strategy."""
    cur.execute("""
        INSERT INTO registry.strategies
            (name, display_name, current_phase, phase_entered_at, hypothesis_doc_path)
        VALUES ('mn_ls_test', 'MN L/S Test', 'research', NOW(), 'docs/hypotheses/mn_ls.md')
        RETURNING id
    """)
    return cur.fetchone()[0]


def test_0004_creates_all_tables(fresh_db):
    """Migration 0004 must create 11 tables."""
    result = _alembic("upgrade", "0004")
    assert result.returncode == 0, f"Migration failed: {result.stderr}"

    expected_tables = {
        "promotions", "features", "models", "model_deployments",
        "signal_batches", "allocator_runs", "allocator_run_signal_batches",
        "target_weights", "portfolio_strategies", "model_features",
        "strategy_feature_dependencies",
    }

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'registry' AND table_name = ANY(%s)
            """, (list(expected_tables),))
            found = {row[0] for row in cur.fetchall()}

    assert found == expected_tables, f"Missing tables: {expected_tables - found}"


def test_0004_promotion_yubikey_required_for_canary(fresh_db):
    """Promotion to canary/scale requires yubikey signature method."""
    _alembic("upgrade", "0004")

    with _connect() as conn:
        with conn.cursor() as cur:
            strategy_id = _setup_strategy_for_promotion(cur)
            conn.commit()

            # GPG for shadow: accepted
            cur.execute("""
                INSERT INTO registry.promotions
                    (strategy_id, from_phase, to_phase, operator_id, operator_signature,
                     signature_method, gate_evidence_doc_path)
                VALUES (%s, 'research', 'shadow', 'wasseem', 'gpg-sig',
                        'gpg', 'docs/reports/mn_ls_shadow.md')
                RETURNING id
            """, (strategy_id,))
            assert cur.fetchone()[0] is not None
            conn.commit()

            # GPG for canary: rejected
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("""
                    INSERT INTO registry.promotions
                        (strategy_id, from_phase, to_phase, operator_id, operator_signature,
                         signature_method, gate_evidence_doc_path)
                    VALUES (%s, 'shadow', 'canary', 'wasseem', 'gpg-sig',
                            'gpg', 'docs/reports/mn_ls_canary.md')
                """, (strategy_id,))
            conn.rollback()


def test_0004_active_promotion_uniqueness(fresh_db):
    """Each strategy has at most one active (un-revoked) promotion."""
    _alembic("upgrade", "0004")

    with _connect() as conn:
        with conn.cursor() as cur:
            strategy_id = _setup_strategy_for_promotion(cur)
            conn.commit()

            # First active promotion
            cur.execute("""
                INSERT INTO registry.promotions
                    (strategy_id, from_phase, to_phase, operator_id, operator_signature,
                     signature_method, gate_evidence_doc_path)
                VALUES (%s, 'research', 'shadow', 'wasseem', 'sig1',
                        'gpg', 'docs/p1.md')
                RETURNING id
            """, (strategy_id,))
            first_id = cur.fetchone()[0]
            conn.commit()

            # Second active promotion: rejected by partial unique index
            with pytest.raises(psycopg.errors.UniqueViolation):
                cur.execute("""
                    INSERT INTO registry.promotions
                        (strategy_id, from_phase, to_phase, operator_id, operator_signature,
                         signature_method, gate_evidence_doc_path)
                    VALUES (%s, 'shadow', 'canary', 'wasseem', 'sig2',
                            'yubikey', 'docs/p2.md')
                """, (strategy_id,))
            conn.rollback()

            # Revoke first with full audit fields
            cur.execute("""
                UPDATE registry.promotions
                SET revoked_at = NOW(), revoked_by = 'wasseem',
                    revocation_signature = 'rev-sig', revocation_signature_method = 'gpg',
                    revocation_reason = 'Superseded by canary promotion'
                WHERE id = %s
            """, (first_id,))
            conn.commit()

            # New active promotion now accepted
            cur.execute("""
                INSERT INTO registry.promotions
                    (strategy_id, from_phase, to_phase, operator_id, operator_signature,
                     signature_method, gate_evidence_doc_path)
                VALUES (%s, 'shadow', 'canary', 'wasseem', 'sig2',
                        'yubikey', 'docs/p2.md')
                RETURNING id
            """, (strategy_id,))
            assert cur.fetchone()[0] is not None
            conn.commit()


def test_0004_revocation_audit_completeness(fresh_db):
    """Revocation requires all 4 audit fields together; partial revocation rejected."""
    _alembic("upgrade", "0004")

    with _connect() as conn:
        with conn.cursor() as cur:
            strategy_id = _setup_strategy_for_promotion(cur)
            cur.execute("""
                INSERT INTO registry.promotions
                    (strategy_id, from_phase, to_phase, operator_id, operator_signature,
                     signature_method, gate_evidence_doc_path)
                VALUES (%s, 'research', 'shadow', 'wasseem', 'sig', 'gpg', 'docs/p.md')
                RETURNING id
            """, (strategy_id,))
            promo_id = cur.fetchone()[0]
            conn.commit()

            # Setting only revoked_at without revoked_by: rejected
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("""
                    UPDATE registry.promotions
                    SET revoked_at = NOW()
                    WHERE id = %s
                """, (promo_id,))
            conn.rollback()


def test_0004_feature_data_sources_must_be_array(fresh_db):
    """data_sources JSONB must be an array, not object or scalar."""
    _alembic("upgrade", "0004")

    with _connect() as conn:
        with conn.cursor() as cur:
            # Object rejected
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("""
                    INSERT INTO registry.features
                        (feature_name, version, definition, computation_script_path,
                         data_sources, refresh_cadence)
                    VALUES ('bad', 1, 'def', 'p.py', '{}'::jsonb, '1h')
                """)
            conn.rollback()

            # Array accepted
            cur.execute("""
                INSERT INTO registry.features
                    (feature_name, version, definition, computation_script_path,
                     data_sources, refresh_cadence)
                VALUES ('good', 1, 'def', 'p.py',
                        '[{"vendor_id": 1, "data_type": "ohlcv"}]'::jsonb, '1h')
                RETURNING id
            """)
            assert cur.fetchone()[0] is not None
            conn.commit()


def test_0004_model_deployment_strategy_role(fresh_db):
    """Two primary deployments for same strategy/environment overlapping rejected; different roles allowed."""
    _alembic("upgrade", "0004")

    with _connect() as conn:
        with conn.cursor() as cur:
            strategy_id = _setup_strategy_for_promotion(cur)

            # Create two models for the strategy
            cur.execute("""
                INSERT INTO registry.models
                    (strategy_id, version_id, model_class, training_data_hash,
                     feature_set_hash, hyperparam_hash, artifact_path, artifact_hash, trained_at)
                VALUES
                    (%s, 'model_a', 'lightgbm', 'data_v1', 'feat_v1', 'h1', 's3://m_a', 'sha:a', NOW()),
                    (%s, 'model_b', 'lightgbm', 'data_v1', 'feat_v1', 'h2', 's3://m_b', 'sha:b', NOW())
                RETURNING id
            """, (strategy_id, strategy_id))
            ids = [row[0] for row in cur.fetchall()]
            model_a, model_b = ids[0], ids[1]
            conn.commit()

            # First primary deployment for strategy in shadow
            cur.execute("""
                INSERT INTO registry.model_deployments
                    (model_id, strategy_id, environment, deployment_role,
                     deployed_at, retired_at, deployed_by)
                VALUES (%s, %s, 'shadow', 'primary',
                        '2024-01-01 00:00:00+00', '2024-12-01 00:00:00+00', 'wasseem')
            """, (model_a, strategy_id))
            conn.commit()

            # Second primary deployment for SAME strategy/environment overlapping: rejected
            with pytest.raises(psycopg.errors.ExclusionViolation):
                cur.execute("""
                    INSERT INTO registry.model_deployments
                        (model_id, strategy_id, environment, deployment_role,
                         deployed_at, deployed_by)
                    VALUES (%s, %s, 'shadow', 'primary',
                            '2024-06-01 00:00:00+00', 'wasseem')
                """, (model_b, strategy_id))
            conn.rollback()

            # Challenger role overlapping with primary: accepted (different role)
            cur.execute("""
                INSERT INTO registry.model_deployments
                    (model_id, strategy_id, environment, deployment_role,
                     deployed_at, deployed_by)
                VALUES (%s, %s, 'shadow', 'challenger',
                        '2024-06-01 00:00:00+00', 'wasseem')
                RETURNING id
            """, (model_b, strategy_id))
            assert cur.fetchone()[0] is not None
            conn.commit()


def test_0004_signal_batch_uses_uuidv7(fresh_db):
    """signal_batches PK is UUIDv7."""
    _alembic("upgrade", "0004")

    with _connect() as conn:
        with conn.cursor() as cur:
            strategy_id = _setup_strategy_for_promotion(cur)
            conn.commit()

            cur.execute("""
                INSERT INTO registry.signal_batches
                    (strategy_id, feature_version, data_snapshot_id, batch_size, generated_at)
                VALUES (%s, 'features_v1', 'snap_001', 50, NOW())
                RETURNING id
            """, (strategy_id,))
            from uuid import UUID
            uuid_obj = UUID(str(cur.fetchone()[0]))
            assert (uuid_obj.int >> 76) & 0xF == 7


def test_0004_allocator_run_jsonb_array_check(fresh_db):
    """input_signal_batch_ids must be JSONB array."""
    _alembic("upgrade", "0004")

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO registry.portfolios (portfolio_code, display_name, product_type, status)
                VALUES ('p1', 'P1', 'market_neutral_fund', 'research')
                RETURNING id
            """)
            portfolio_id = cur.fetchone()[0]
            conn.commit()

            # Object rejected
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("""
                    INSERT INTO registry.allocator_runs
                        (portfolio_id, input_signal_batch_ids, objective_version,
                         constraints_version, solve_status, generated_at)
                    VALUES (%s, '{}'::jsonb, 'obj_v1', 'cons_v1', 'optimal', NOW())
                """, (portfolio_id,))
            conn.rollback()

            # Empty array accepted
            cur.execute("""
                INSERT INTO registry.allocator_runs
                    (portfolio_id, input_signal_batch_ids, objective_version,
                     constraints_version, solve_status, generated_at)
                VALUES (%s, '[]'::jsonb, 'obj_v1', 'cons_v1', 'optimal', NOW())
                RETURNING id
            """, (portfolio_id,))
            assert cur.fetchone()[0] is not None
            conn.commit()


def test_0004_allocator_signal_bridge(fresh_db):
    """allocator_run_signal_batches enforces FK and queryable lineage."""
    _alembic("upgrade", "0004")

    with _connect() as conn:
        with conn.cursor() as cur:
            strategy_id = _setup_strategy_for_promotion(cur)
            cur.execute("""
                INSERT INTO registry.portfolios (portfolio_code, display_name, product_type, status)
                VALUES ('p1', 'P1', 'market_neutral_fund', 'research')
                RETURNING id
            """)
            portfolio_id = cur.fetchone()[0]
            conn.commit()

            # Create signal batch
            cur.execute("""
                INSERT INTO registry.signal_batches
                    (strategy_id, feature_version, data_snapshot_id, batch_size, generated_at)
                VALUES (%s, 'fv1', 'snap_001', 50, NOW())
                RETURNING id
            """, (strategy_id,))
            batch_id = cur.fetchone()[0]

            # Create allocator run
            cur.execute("""
                INSERT INTO registry.allocator_runs
                    (portfolio_id, input_signal_batch_ids, objective_version,
                     constraints_version, solve_status, generated_at)
                VALUES (%s, '[]'::jsonb, 'obj_v1', 'cons_v1', 'optimal', NOW())
                RETURNING id
            """, (portfolio_id,))
            run_id = cur.fetchone()[0]
            conn.commit()

            # Bridge accepts valid signal_batch_id
            cur.execute("""
                INSERT INTO registry.allocator_run_signal_batches
                    (allocator_run_id, signal_batch_id)
                VALUES (%s, %s)
            """, (run_id, batch_id))
            conn.commit()

            # Bridge rejects nonexistent signal_batch_id
            from uuid import uuid4
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                cur.execute("""
                    INSERT INTO registry.allocator_run_signal_batches
                        (allocator_run_id, signal_batch_id)
                    VALUES (%s, %s)
                """, (run_id, uuid4()))
            conn.rollback()

            # Queryable lineage: signal batches consumed by run
            cur.execute("""
                SELECT signal_batch_id FROM registry.allocator_run_signal_batches
                WHERE allocator_run_id = %s
            """, (run_id,))
            consumed = [row[0] for row in cur.fetchall()]
            assert len(consumed) == 1


def test_0004_target_weights_signed(fresh_db):
    """target_weight allows positive (long) and negative (short) values."""
    _alembic("upgrade", "0004")

    with _connect() as conn:
        with conn.cursor() as cur:
            venue_id, _, _, instrument_id, _ = _setup_basic_registry(cur)
            cur.execute("""
                INSERT INTO registry.portfolios (portfolio_code, display_name, product_type, status)
                VALUES ('p1', 'P1', 'market_neutral_fund', 'research')
                RETURNING id
            """)
            portfolio_id = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO registry.allocator_runs
                    (portfolio_id, input_signal_batch_ids, objective_version,
                     constraints_version, solve_status, generated_at)
                VALUES (%s, '[]'::jsonb, 'obj_v1', 'cons_v1', 'optimal', NOW())
                RETURNING id
            """, (portfolio_id,))
            run_id = cur.fetchone()[0]
            conn.commit()

            # Negative weight (short) accepted
            cur.execute("""
                INSERT INTO registry.target_weights
                    (allocator_run_id, instrument_id, target_weight)
                VALUES (%s, %s, -0.05)
                RETURNING id
            """, (run_id, instrument_id))
            assert cur.fetchone()[0] is not None
            conn.commit()


def test_0004_portfolio_strategy_active_risk_nonneg(fresh_db):
    """active_risk_weight must be nonnegative."""
    _alembic("upgrade", "0004")

    with _connect() as conn:
        with conn.cursor() as cur:
            strategy_id = _setup_strategy_for_promotion(cur)
            cur.execute("""
                INSERT INTO registry.portfolios (portfolio_code, display_name, product_type, status)
                VALUES ('p1', 'P1', 'market_neutral_fund', 'research')
                RETURNING id
            """)
            portfolio_id = cur.fetchone()[0]
            conn.commit()

            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("""
                    INSERT INTO registry.portfolio_strategies
                        (portfolio_id, strategy_id, active_risk_weight, starts_at)
                    VALUES (%s, %s, -0.5, NOW())
                """, (portfolio_id, strategy_id))
            conn.rollback()


def test_0004_model_features_simple_bridge(fresh_db):
    """model_features bridge with simplified (model_id, feature_id) PK."""
    _alembic("upgrade", "0004")

    with _connect() as conn:
        with conn.cursor() as cur:
            strategy_id = _setup_strategy_for_promotion(cur)
            cur.execute("""
                INSERT INTO registry.models
                    (strategy_id, version_id, model_class, training_data_hash,
                     feature_set_hash, hyperparam_hash, artifact_path, artifact_hash, trained_at)
                VALUES (%s, 'm1', 'lightgbm', 'data_v1', 'feat_v1', 'h1', 's3://m', 'sha:1', NOW())
                RETURNING id
            """, (strategy_id,))
            model_id = cur.fetchone()[0]

            cur.execute("""
                INSERT INTO registry.features
                    (feature_name, version, definition, computation_script_path,
                     data_sources, refresh_cadence)
                VALUES ('funding_zscore', 1, 'fz', 'fz.py', '[]'::jsonb, '1h')
                RETURNING id
            """)
            feature_id = cur.fetchone()[0]
            conn.commit()

            cur.execute("""
                INSERT INTO registry.model_features (model_id, feature_id)
                VALUES (%s, %s)
            """, (model_id, feature_id))
            conn.commit()

            # Duplicate (model, feature) rejected
            with pytest.raises(psycopg.errors.UniqueViolation):
                cur.execute("""
                    INSERT INTO registry.model_features (model_id, feature_id)
                    VALUES (%s, %s)
                """, (model_id, feature_id))
            conn.rollback()


def test_0004_strategy_feature_dependencies_for_oms(fresh_db):
    """strategy_feature_dependencies enables OMS require_data_fresh check."""
    _alembic("upgrade", "0004")

    with _connect() as conn:
        with conn.cursor() as cur:
            strategy_id = _setup_strategy_for_promotion(cur)
            cur.execute("""
                INSERT INTO registry.features
                    (feature_name, version, definition, computation_script_path,
                     data_sources, refresh_cadence)
                VALUES ('fz', 1, 'fz', 'fz.py', '[]'::jsonb, '1h')
                RETURNING id
            """)
            feature_id = cur.fetchone()[0]
            conn.commit()

            cur.execute("""
                INSERT INTO registry.strategy_feature_dependencies
                    (strategy_id, feature_id, required)
                VALUES (%s, %s, TRUE)
            """, (strategy_id, feature_id))
            conn.commit()

            cur.execute("""
                SELECT feature_id, required
                FROM registry.strategy_feature_dependencies
                WHERE strategy_id = %s AND required = TRUE
            """, (strategy_id,))
            deps = cur.fetchall()
            assert len(deps) == 1
            assert deps[0] == (feature_id, True)


def test_0004_downgrade_clean(fresh_db):
    """Downgrade to 0003 drops all 11 tables; earlier registry preserved."""
    _alembic("upgrade", "0004")
    result = _alembic("downgrade", "0003")
    assert result.returncode == 0, f"Downgrade failed: {result.stderr}"

    strategy_model_tables = {
        "promotions", "features", "models", "model_deployments",
        "signal_batches", "allocator_runs", "allocator_run_signal_batches",
        "target_weights", "portfolio_strategies", "model_features",
        "strategy_feature_dependencies",
    }
    earlier_tables = {
        "venues", "assets", "instruments", "accounts", "portfolios", "strategies",
        "vendors", "symbol_translations", "instrument_specs_history", "fee_schedules",
        "asset_clusters", "asset_cluster_memberships", "venue_capabilities",
    }

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name FROM information_schema.tables WHERE table_schema = 'registry'
            """)
            remaining = {row[0] for row in cur.fetchall()}

    leaked = remaining & strategy_model_tables
    assert not leaked, f"Strategy/model tables not dropped: {leaked}"
    missing_earlier = earlier_tables - remaining
    assert not missing_earlier, f"Earlier tables wrongly dropped: {missing_earlier}"


# ============================================================
# Migration 0004b tests: registry_guardrails
# ============================================================


def test_0004b_models_strategy_consistency_fk(fresh_db):
    """Composite FK prevents model_deployments.strategy_id from differing from model.strategy_id."""
    _alembic("upgrade", "0004b")

    with _connect() as conn:
        with conn.cursor() as cur:
            # Two strategies
            cur.execute("""
                INSERT INTO registry.strategies
                    (name, display_name, current_phase, phase_entered_at, hypothesis_doc_path)
                VALUES
                    ('strat_a', 'Strat A', 'research', NOW(), 'docs/a.md'),
                    ('strat_b', 'Strat B', 'research', NOW(), 'docs/b.md')
                RETURNING id
            """)
            ids = [row[0] for row in cur.fetchall()]
            strat_a, strat_b = ids[0], ids[1]

            # Model belongs to strat_a
            cur.execute("""
                INSERT INTO registry.models
                    (strategy_id, version_id, model_class, training_data_hash,
                     feature_set_hash, hyperparam_hash, artifact_path, artifact_hash, trained_at)
                VALUES (%s, 'm_a', 'lightgbm', 'd1', 'f1', 'h1', 's3://m', 'sha:1', NOW())
                RETURNING id
            """, (strat_a,))
            model_id = cur.fetchone()[0]
            conn.commit()

            # Deployment claiming model belongs to strat_b: rejected by composite FK
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                cur.execute("""
                    INSERT INTO registry.model_deployments
                        (model_id, strategy_id, environment, deployment_role,
                         deployed_at, deployed_by)
                    VALUES (%s, %s, 'shadow', 'primary', NOW(), 'wasseem')
                """, (model_id, strat_b))
            conn.rollback()

            # Deployment with correct strategy: accepted
            cur.execute("""
                INSERT INTO registry.model_deployments
                    (model_id, strategy_id, environment, deployment_role,
                     deployed_at, deployed_by)
                VALUES (%s, %s, 'shadow', 'primary', NOW(), 'wasseem')
                RETURNING id
            """, (model_id, strat_a))
            assert cur.fetchone()[0] is not None
            conn.commit()


def test_0004b_deployment_slot_for_ensemble(fresh_db):
    """Multiple ensemble_member deployments allowed if deployment_slot differs."""
    _alembic("upgrade", "0004b")

    with _connect() as conn:
        with conn.cursor() as cur:
            strategy_id = _setup_strategy_for_promotion(cur)

            # Three models for the strategy
            cur.execute("""
                INSERT INTO registry.models
                    (strategy_id, version_id, model_class, training_data_hash,
                     feature_set_hash, hyperparam_hash, artifact_path, artifact_hash, trained_at)
                VALUES
                    (%s, 'm1', 'lightgbm', 'd1', 'f1', 'h1', 's3://m1', 'sha:1', NOW()),
                    (%s, 'm2', 'lightgbm', 'd1', 'f1', 'h2', 's3://m2', 'sha:2', NOW()),
                    (%s, 'm3', 'lightgbm', 'd1', 'f1', 'h3', 's3://m3', 'sha:3', NOW())
                RETURNING id
            """, (strategy_id, strategy_id, strategy_id))
            ids = [row[0] for row in cur.fetchall()]
            m1, m2, m3 = ids[0], ids[1], ids[2]
            conn.commit()

            # Three ensemble_members with different slots: all accepted
            cur.execute("""
                INSERT INTO registry.model_deployments
                    (model_id, strategy_id, environment, deployment_role, deployment_slot,
                     deployed_at, deployed_by)
                VALUES
                    (%s, %s, 'shadow', 'ensemble_member', 'slot_01', NOW(), 'wasseem'),
                    (%s, %s, 'shadow', 'ensemble_member', 'slot_02', NOW(), 'wasseem'),
                    (%s, %s, 'shadow', 'ensemble_member', 'slot_03', NOW(), 'wasseem')
            """, (m1, strategy_id, m2, strategy_id, m3, strategy_id))
            conn.commit()

            # Two ensemble_members with same slot overlapping: rejected
            with pytest.raises(psycopg.errors.ExclusionViolation):
                cur.execute("""
                    INSERT INTO registry.model_deployments
                        (model_id, strategy_id, environment, deployment_role, deployment_slot,
                         deployed_at, deployed_by)
                    VALUES (%s, %s, 'shadow', 'ensemble_member', 'slot_01', NOW(), 'wasseem')
                """, (m1, strategy_id))
            conn.rollback()


def test_0004b_allocator_runs_no_jsonb_field(fresh_db):
    """allocator_runs no longer has input_signal_batch_ids column."""
    _alembic("upgrade", "0004b")

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'registry'
                  AND table_name = 'allocator_runs'
                  AND column_name = 'input_signal_batch_ids'
            """)
            assert cur.fetchone() is None, "input_signal_batch_ids should be removed"


def test_0004b_strategy_phase_synced_from_promotion(fresh_db):
    """Inserting active promotion auto-updates strategies.current_phase."""
    _alembic("upgrade", "0004b")

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO registry.strategies
                    (name, display_name, current_phase, phase_entered_at, hypothesis_doc_path)
                VALUES ('sync_test', 'Sync Test', 'research', NOW(), 'docs/s.md')
                RETURNING id
            """)
            strategy_id = cur.fetchone()[0]
            conn.commit()

            # Initial phase: research
            cur.execute("SELECT current_phase FROM registry.strategies WHERE id = %s", (strategy_id,))
            assert cur.fetchone()[0] == 'research'

            # Promote to shadow
            cur.execute("""
                INSERT INTO registry.promotions
                    (strategy_id, from_phase, to_phase, operator_id, operator_signature,
                     signature_method, gate_evidence_doc_path)
                VALUES (%s, 'research', 'shadow', 'wasseem', 'sig', 'gpg', 'docs/p.md')
            """, (strategy_id,))
            conn.commit()

            # Strategy phase auto-synced
            cur.execute("SELECT current_phase FROM registry.strategies WHERE id = %s", (strategy_id,))
            assert cur.fetchone()[0] == 'shadow', "Strategy phase should auto-sync from active promotion"


def test_0004b_model_immutability(fresh_db):
    """models columns marked immutable cannot be updated."""
    _alembic("upgrade", "0004b")

    with _connect() as conn:
        with conn.cursor() as cur:
            strategy_id = _setup_strategy_for_promotion(cur)

            cur.execute("""
                INSERT INTO registry.models
                    (strategy_id, version_id, model_class, training_data_hash,
                     feature_set_hash, hyperparam_hash, artifact_path, artifact_hash, trained_at)
                VALUES (%s, 'imm_test', 'lightgbm', 'd1', 'f1', 'h1', 's3://m', 'sha:1', NOW())
                RETURNING id
            """, (strategy_id,))
            model_id = cur.fetchone()[0]
            conn.commit()

            # artifact_hash change rejected
            with pytest.raises(psycopg.errors.RaiseException):
                cur.execute("""
                    UPDATE registry.models SET artifact_hash = 'sha:tampered' WHERE id = %s
                """, (model_id,))
            conn.rollback()

            # retired_at change accepted
            cur.execute("""
                UPDATE registry.models
                SET retired_at = NOW(), retirement_reason = 'replaced by v2'
                WHERE id = %s
                RETURNING retired_at
            """, (model_id,))
            assert cur.fetchone()[0] is not None
            conn.commit()


def test_0004b_feature_immutability(fresh_db):
    """features columns marked immutable cannot be updated."""
    _alembic("upgrade", "0004b")

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO registry.features
                    (feature_name, version, definition, computation_script_path,
                     data_sources, refresh_cadence)
                VALUES ('imm_feat', 1, 'def_v1', 'fz.py', '[]'::jsonb, '1h')
                RETURNING id
            """)
            feature_id = cur.fetchone()[0]
            conn.commit()

            # definition change rejected
            with pytest.raises(psycopg.errors.RaiseException):
                cur.execute("""
                    UPDATE registry.features SET definition = 'tampered' WHERE id = %s
                """, (feature_id,))
            conn.rollback()

            # parity_test_passing change accepted
            cur.execute("""
                UPDATE registry.features
                SET parity_test_passing = TRUE, parity_last_tested_at = NOW()
                WHERE id = %s
                RETURNING parity_test_passing
            """, (feature_id,))
            assert cur.fetchone()[0] is True
            conn.commit()


def test_0004b_view_active_promotions(fresh_db):
    """active_promotions view returns only un-revoked promotions."""
    _alembic("upgrade", "0004b")

    with _connect() as conn:
        with conn.cursor() as cur:
            strategy_id = _setup_strategy_for_promotion(cur)

            cur.execute("""
                INSERT INTO registry.promotions
                    (strategy_id, from_phase, to_phase, operator_id, operator_signature,
                     signature_method, gate_evidence_doc_path)
                VALUES (%s, 'research', 'shadow', 'wasseem', 'sig', 'gpg', 'docs/p.md')
                RETURNING id
            """, (strategy_id,))
            promo_id = cur.fetchone()[0]
            conn.commit()

            cur.execute("""
                SELECT strategy_id, to_phase FROM registry.active_promotions
                WHERE strategy_id = %s
            """, (strategy_id,))
            row = cur.fetchone()
            assert row == (strategy_id, 'shadow')

            # Revoke and verify view excludes
            cur.execute("""
                UPDATE registry.promotions
                SET revoked_at = NOW(), revoked_by = 'wasseem',
                    revocation_signature = 'rev', revocation_signature_method = 'gpg',
                    revocation_reason = 'test'
                WHERE id = %s
            """, (promo_id,))
            conn.commit()

            cur.execute("""
                SELECT * FROM registry.active_promotions WHERE strategy_id = %s
            """, (strategy_id,))
            assert cur.fetchone() is None


def test_0004b_view_current_instrument_specs(fresh_db):
    """current_instrument_specs returns active spec only (effective_from <= NOW < effective_to)."""
    _alembic("upgrade", "0004b")

    with _connect() as conn:
        with conn.cursor() as cur:
            _, _, _, instrument_id, _ = _setup_basic_registry(cur)
            conn.commit()

            # Active spec: ends tomorrow
            cur.execute("""
                INSERT INTO registry.instrument_specs_history
                    (instrument_id, tick_size, effective_from, effective_to, source)
                VALUES (%s, 0.01, '2024-01-01 00:00:00+00', NOW() + INTERVAL '1 day', 'binance')
            """, (instrument_id,))
            conn.commit()

            # Future spec (effective_from > NOW): should NOT appear in view
            cur.execute("""
                INSERT INTO registry.instrument_specs_history
                    (instrument_id, tick_size, effective_from, source)
                VALUES (%s, 0.001, NOW() + INTERVAL '1 day', 'binance')
            """, (instrument_id,))
            conn.commit()

            cur.execute("""
                SELECT tick_size FROM registry.current_instrument_specs
                WHERE instrument_id = %s
            """, (instrument_id,))
            tick = cur.fetchone()[0]
            from decimal import Decimal
            assert tick == Decimal("0.01"), f"Expected current spec 0.01, got {tick}"


def test_0004b_view_current_fee_schedules_precedence(fresh_db):
    """current_fee_schedules has precedence_rank for cost model lookup."""
    _alembic("upgrade", "0004b")

    with _connect() as conn:
        with conn.cursor() as cur:
            venue_id, _, _, instrument_id, account_id = _setup_basic_registry(cur)
            conn.commit()

            # Venue default (rank 5)
            cur.execute("""
                INSERT INTO registry.fee_schedules
                    (venue_id, maker_fee_bps, taker_fee_bps, effective_from, source)
                VALUES (%s, 2.0, 5.0, '2024-01-01 00:00:00+00', 'venue_default')
            """, (venue_id,))

            # Venue + instrument (rank 3)
            cur.execute("""
                INSERT INTO registry.fee_schedules
                    (venue_id, instrument_id, maker_fee_bps, taker_fee_bps,
                     effective_from, source)
                VALUES (%s, %s, 1.5, 4.0, '2024-01-01 00:00:00+00', 'venue_btc')
            """, (venue_id, instrument_id))

            # Account + instrument (rank 1, highest specificity)
            cur.execute("""
                INSERT INTO registry.fee_schedules
                    (venue_id, account_id, instrument_id, maker_fee_bps, taker_fee_bps,
                     effective_from, source)
                VALUES (%s, %s, %s, 0.5, 3.0, '2024-01-01 00:00:00+00', 'vip_btc')
            """, (venue_id, account_id, instrument_id))
            conn.commit()

            cur.execute("""
                SELECT maker_fee_bps, precedence_rank
                FROM registry.current_fee_schedules
                WHERE venue_id = %s
                ORDER BY precedence_rank ASC
            """, (venue_id,))
            rows = cur.fetchall()
            from decimal import Decimal
            # First row should be highest specificity (account+instrument, rank 1)
            assert rows[0] == (Decimal("0.5"), 1)
            # Last row should be venue default (rank 5)
            assert rows[-1] == (Decimal("2.0"), 5)


def test_0004b_full_registry_lineage_integration(fresh_db):
    """Full registry chain: every entity from venue to target_weight is queryable."""
    _alembic("upgrade", "0004b")

    with _connect() as conn:
        with conn.cursor() as cur:
            # Build full lineage
            venue_id, btc_id, usdt_id, instrument_id, account_id = _setup_basic_registry(cur)

            # Vendor
            cur.execute("""
                INSERT INTO registry.vendors (name, data_types, status, verified_status)
                VALUES ('binance_api', ARRAY['ohlcv'], 'active', 'VERIFIED')
                RETURNING id
            """)
            vendor_id = cur.fetchone()[0]

            # Cluster + membership
            cur.execute("""
                INSERT INTO registry.asset_clusters (cluster_code, display_name)
                VALUES ('layer_1', 'Layer 1')
                RETURNING id
            """)
            cluster_id = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO registry.asset_cluster_memberships
                    (asset_id, cluster_id, effective_from)
                VALUES (%s, %s, '2024-01-01 00:00:00+00')
            """, (btc_id, cluster_id))

            # Strategy + promotion
            strategy_id = _setup_strategy_for_promotion(cur)
            cur.execute("""
                INSERT INTO registry.promotions
                    (strategy_id, from_phase, to_phase, operator_id, operator_signature,
                     signature_method, gate_evidence_doc_path)
                VALUES (%s, 'research', 'shadow', 'wasseem', 'sig', 'gpg', 'docs/p.md')
            """, (strategy_id,))

            # Feature + model + dependency
            cur.execute("""
                INSERT INTO registry.features
                    (feature_name, version, definition, computation_script_path,
                     data_sources, refresh_cadence)
                VALUES ('fz', 1, 'fz', 'fz.py', '[]'::jsonb, '1h')
                RETURNING id
            """)
            feature_id = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO registry.models
                    (strategy_id, version_id, model_class, training_data_hash,
                     feature_set_hash, hyperparam_hash, artifact_path, artifact_hash, trained_at)
                VALUES (%s, 'm1', 'lightgbm', 'd1', 'f1', 'h1', 's3://m', 'sha:1', NOW())
                RETURNING id
            """, (strategy_id,))
            model_id = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO registry.model_features (model_id, feature_id) VALUES (%s, %s)
            """, (model_id, feature_id))
            cur.execute("""
                INSERT INTO registry.strategy_feature_dependencies
                    (strategy_id, feature_id, required) VALUES (%s, %s, TRUE)
            """, (strategy_id, feature_id))

            # Deployment
            cur.execute("""
                INSERT INTO registry.model_deployments
                    (model_id, strategy_id, environment, deployment_role,
                     deployed_at, deployed_by)
                VALUES (%s, %s, 'shadow', 'primary', NOW(), 'wasseem')
            """, (model_id, strategy_id))

            # Portfolio + portfolio_strategy
            cur.execute("""
                INSERT INTO registry.portfolios (portfolio_code, display_name, product_type, status)
                VALUES ('mn_ls_p1', 'MN L/S P1', 'market_neutral_fund', 'shadow')
                RETURNING id
            """)
            portfolio_id = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO registry.portfolio_strategies
                    (portfolio_id, strategy_id, capital_allocation_pct, starts_at)
                VALUES (%s, %s, 1.0, NOW())
            """, (portfolio_id, strategy_id))

            # Signal batch
            cur.execute("""
                INSERT INTO registry.signal_batches
                    (strategy_id, model_id, feature_version, data_snapshot_id,
                     batch_size, generated_at)
                VALUES (%s, %s, 'fv1', 'snap_001', 50, NOW())
                RETURNING id
            """, (strategy_id, model_id))
            batch_id = cur.fetchone()[0]

            # Allocator run + bridge + target weight
            cur.execute("""
                INSERT INTO registry.allocator_runs
                    (portfolio_id, objective_version, constraints_version,
                     solve_status, generated_at)
                VALUES (%s, 'obj_v1', 'cons_v1', 'optimal', NOW())
                RETURNING id
            """, (portfolio_id,))
            run_id = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO registry.allocator_run_signal_batches
                    (allocator_run_id, signal_batch_id) VALUES (%s, %s)
            """, (run_id, batch_id))
            cur.execute("""
                INSERT INTO registry.target_weights
                    (allocator_run_id, instrument_id, target_weight)
                VALUES (%s, %s, 0.05)
            """, (run_id, instrument_id))
            conn.commit()

            # Now query the full lineage in one statement
            cur.execute("""
                SELECT
                    s.name AS strategy,
                    p.to_phase AS active_phase,
                    m.version_id AS model,
                    md.environment AS deployment_env,
                    f.feature_name,
                    sb.id AS signal_batch_id,
                    ar.id AS allocator_run_id,
                    arsb.signal_batch_id AS bridge_batch_id,
                    tw.target_weight,
                    i.instrument_code,
                    ac.cluster_code
                FROM registry.target_weights tw
                JOIN registry.allocator_runs ar ON ar.id = tw.allocator_run_id
                JOIN registry.allocator_run_signal_batches arsb ON arsb.allocator_run_id = ar.id
                JOIN registry.signal_batches sb ON sb.id = arsb.signal_batch_id
                JOIN registry.strategies s ON s.id = sb.strategy_id
                JOIN registry.active_promotions p ON p.strategy_id = s.id
                JOIN registry.models m ON m.id = sb.model_id
                JOIN registry.active_model_deployments md ON md.model_id = m.id
                JOIN registry.model_features mf ON mf.model_id = m.id
                JOIN registry.features f ON f.id = mf.feature_id
                JOIN registry.instruments i ON i.id = tw.instrument_id
                JOIN registry.asset_cluster_memberships acm
                    ON acm.asset_id = i.base_asset_id AND acm.effective_to IS NULL
                JOIN registry.asset_clusters ac ON ac.id = acm.cluster_id
                LIMIT 1
            """)
            row = cur.fetchone()
            assert row is not None, "Full lineage query returned no rows"
            assert row[1] == 'shadow', "Strategy phase should be 'shadow' from active promotion"
            assert row[7] == row[5], "Bridge batch_id should match signal_batch_id"
            from decimal import Decimal
            assert row[8] == Decimal("0.05")
            assert row[9] == 'BTCUSDT-PERP-BINANCE'
            assert row[10] == 'layer_1'


def test_0004b_downgrade_clean(fresh_db):
    """Downgrade from 0004b to 0004 is clean."""
    _alembic("upgrade", "0004b")
    result = _alembic("downgrade", "0004")
    assert result.returncode == 0, f"Downgrade failed: {result.stderr}"

    with _connect() as conn:
        with conn.cursor() as cur:
            # Views should be gone
            cur.execute("""
                SELECT viewname FROM pg_views
                WHERE schemaname = 'registry'
                  AND viewname IN ('active_promotions', 'active_model_deployments',
                                   'current_instrument_specs', 'current_fee_schedules',
                                   'active_venue_capabilities')
            """)
            assert cur.fetchall() == []

            # Triggers should be gone
            cur.execute("""
                SELECT tgname FROM pg_trigger
                WHERE tgname IN ('models_immutability', 'features_immutability',
                                 'promotions_sync_strategy_phase')
            """)
            assert cur.fetchall() == []

            # input_signal_batch_ids should be restored
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'registry' AND table_name = 'allocator_runs'
                  AND column_name = 'input_signal_batch_ids'
            """)
            assert cur.fetchone() is not None


# ============================================================
# Migration 0005 tests: accounting_double_entry (v7)
# ============================================================

from datetime import datetime, timezone
from decimal import Decimal


def _setup_basic_accounting(cur):
    """Helper: registry data + ledger accounts. Returns dict of IDs."""
    cur.execute("""
        INSERT INTO registry.venues (venue_code, display_name, venue_type, status)
        VALUES ('binance_futures', 'Binance Futures', 'cex_futures', 'active')
        RETURNING id
    """)
    venue_id = cur.fetchone()[0]

    cur.execute("""
        INSERT INTO registry.assets (symbol, display_name, asset_type, decimals, status)
        VALUES ('BTC', 'Bitcoin', 'crypto', 8, 'active'),
               ('USDT', 'Tether', 'stablecoin', 6, 'active')
        RETURNING id
    """)
    ids = [row[0] for row in cur.fetchall()]
    btc_id, usdt_id = ids[0], ids[1]

    cur.execute("""
        INSERT INTO registry.accounts (venue_id, account_code, display_name, account_type, status)
        VALUES (%s, 'binance_master', 'Master', 'trading', 'active')
        RETURNING id
    """, (venue_id,))
    registry_account_id = cur.fetchone()[0]

    cur.execute("""
        INSERT INTO registry.portfolios (portfolio_code, display_name, product_type, status)
        VALUES ('mn_ls_p1', 'MN L/S P1', 'market_neutral_fund', 'research')
        RETURNING id
    """)
    portfolio_id = cur.fetchone()[0]

    cur.execute("""
        INSERT INTO registry.strategies
            (name, display_name, current_phase, phase_entered_at, hypothesis_doc_path)
        VALUES ('mn_ls_test', 'MN L/S Test', 'research', NOW(), 'docs/h.md')
        RETURNING id
    """)
    strategy_id = cur.fetchone()[0]

    cur.execute("""
        INSERT INTO accounting.ledger_accounts
            (account_code, account_name, account_type, account_subtype,
             portfolio_id, strategy_id, registry_account_id, asset_id)
        VALUES
            ('USDT_CASH', 'USDT Cash', 'asset', 'cash',
             %s, %s, %s, %s),
            ('BTC_POSITION', 'BTC Position', 'asset', 'position',
             %s, %s, %s, %s),
            ('FEE_EXPENSE', 'Fee Expense', 'expense', 'fee_expense',
             %s, %s, %s, %s)
        RETURNING id
    """, (portfolio_id, strategy_id, registry_account_id, usdt_id,
          portfolio_id, strategy_id, registry_account_id, btc_id,
          portfolio_id, strategy_id, registry_account_id, usdt_id))
    ledger_ids = [row[0] for row in cur.fetchall()]

    return {
        'portfolio_id': portfolio_id, 'strategy_id': strategy_id,
        'registry_account_id': registry_account_id, 'venue_id': venue_id,
        'btc_id': btc_id, 'usdt_id': usdt_id,
        'cash_acct': ledger_ids[0], 'pos_acct': ledger_ids[1], 'fee_acct': ledger_ids[2],
    }


def _create_draft_journal(cur, ctx, source_id='fill_001', journal_at=None,
                           source_namespace='binance_futures'):
    """Helper: create a draft trade journal."""
    if journal_at is None:
        journal_at = datetime.now(timezone.utc)
    cur.execute("""
        INSERT INTO accounting.journals
            (journal_type, portfolio_id, strategy_id, journal_at,
             source_type, source_namespace, source_id, created_by)
        VALUES ('trade', %s, %s, %s, 'fill', %s, %s, 'wasseem')
        RETURNING id
    """, (ctx['portfolio_id'], ctx['strategy_id'], journal_at, source_namespace, source_id))
    return cur.fetchone()[0]


def test_0005_creates_all_tables(fresh_db):
    """Migration 0005 creates 3 accounting tables."""
    result = _alembic("upgrade", "0005")
    assert result.returncode == 0, f"Migration failed: {result.stderr}"

    expected = {"ledger_accounts", "journals", "ledger_entries"}
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'accounting' AND table_name = ANY(%s)
            """, (list(expected),))
            assert {row[0] for row in cur.fetchall()} == expected


def test_0005_journal_at_required(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            conn.commit()
            with pytest.raises(psycopg.errors.NotNullViolation):
                cur.execute("""
                    INSERT INTO accounting.journals
                        (journal_type, portfolio_id, strategy_id,
                         source_type, source_namespace, source_id, created_by)
                    VALUES ('trade', %s, %s, 'fill', 'global', 'f1', 'wasseem')
                """, (ctx['portfolio_id'], ctx['strategy_id']))
            conn.rollback()


def test_0005_balanced_journal_posts(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            j_id = _create_draft_journal(cur, ctx)
            cur.execute("""
                INSERT INTO accounting.ledger_entries
                    (journal_id, ledger_account_id, debit_credit, asset_id, quantity, amount_usd)
                VALUES (%s, %s, 'debit', %s, 0.01, 1000),
                       (%s, %s, 'credit', %s, 1000, 1000)
            """, (j_id, ctx['pos_acct'], ctx['btc_id'],
                  j_id, ctx['cash_acct'], ctx['usdt_id']))
            conn.commit()
            cur.execute("SELECT accounting.post_journal(%s, 'wasseem')", (j_id,))
            conn.commit()
            cur.execute("SELECT status, posted_at, posted_by FROM accounting.journals WHERE id = %s", (j_id,))
            status, posted_at, posted_by = cur.fetchone()
            assert status == 'posted'
            assert posted_at is not None
            assert posted_by == 'wasseem'


def test_0005_unbalanced_journal_rejected(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            j_id = _create_draft_journal(cur, ctx, source_id='unbal_1')
            cur.execute("""
                INSERT INTO accounting.ledger_entries
                    (journal_id, ledger_account_id, debit_credit, asset_id, amount_usd)
                VALUES (%s, %s, 'debit', %s, 1000), (%s, %s, 'credit', %s, 999)
            """, (j_id, ctx['pos_acct'], ctx['btc_id'],
                  j_id, ctx['cash_acct'], ctx['usdt_id']))
            conn.commit()
            with pytest.raises(psycopg.errors.RaiseException) as exc:
                cur.execute("SELECT accounting.post_journal(%s, 'wasseem')", (j_id,))
            assert 'unbalanced' in str(exc.value).lower()
            conn.rollback()


def test_0005_one_sided_journal_rejected(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            j_id = _create_draft_journal(cur, ctx, source_id='one_sided')
            cur.execute("""
                INSERT INTO accounting.ledger_entries
                    (journal_id, ledger_account_id, debit_credit, asset_id, amount_usd)
                VALUES (%s, %s, 'debit', %s, 1000)
            """, (j_id, ctx['pos_acct'], ctx['btc_id']))
            conn.commit()
            with pytest.raises(psycopg.errors.RaiseException):
                cur.execute("SELECT accounting.post_journal(%s, 'wasseem')", (j_id,))
            conn.rollback()


def test_0005_zero_amount_rejected(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            j_id = _create_draft_journal(cur, ctx, source_id='zero_amt')
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("""
                    INSERT INTO accounting.ledger_entries
                        (journal_id, ledger_account_id, debit_credit, asset_id, amount_usd)
                    VALUES (%s, %s, 'debit', %s, 0)
                """, (j_id, ctx['pos_acct'], ctx['btc_id']))
            conn.rollback()


def test_0005_direct_status_update_blocked(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            j_id = _create_draft_journal(cur, ctx, source_id='direct_post_attack')
            cur.execute("""
                INSERT INTO accounting.ledger_entries
                    (journal_id, ledger_account_id, debit_credit, asset_id, amount_usd)
                VALUES (%s, %s, 'debit', %s, 1000)
            """, (j_id, ctx['pos_acct'], ctx['btc_id']))
            conn.commit()
            with pytest.raises(psycopg.errors.RaiseException) as exc:
                cur.execute("""
                    UPDATE accounting.journals
                    SET status = 'posted', posted_at = NOW(), posted_by = 'attacker'
                    WHERE id = %s
                """, (j_id,))
            assert 'forbidden' in str(exc.value).lower() or 'use accounting.post_journal' in str(exc.value).lower()
            conn.rollback()


def test_0005_direct_posted_insert_blocked(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            conn.commit()
            with pytest.raises(psycopg.errors.RaiseException) as exc:
                cur.execute("""
                    INSERT INTO accounting.journals
                        (journal_type, status, portfolio_id, strategy_id, journal_at,
                         source_type, source_namespace, source_id, created_by, posted_by, posted_at)
                    VALUES ('trade', 'posted', %s, %s, NOW(),
                            'fill', 'binance_futures', 'sneak_1', 'attacker', 'attacker', NOW())
                """, (ctx['portfolio_id'], ctx['strategy_id']))
            assert 'must be inserted as draft' in str(exc.value).lower()
            conn.rollback()


def test_0005_posted_journal_no_new_entries(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            j_id = _create_draft_journal(cur, ctx, source_id='no_new_entries')
            cur.execute("""
                INSERT INTO accounting.ledger_entries
                    (journal_id, ledger_account_id, debit_credit, asset_id, amount_usd)
                VALUES (%s, %s, 'debit', %s, 1000), (%s, %s, 'credit', %s, 1000)
            """, (j_id, ctx['pos_acct'], ctx['btc_id'],
                  j_id, ctx['cash_acct'], ctx['usdt_id']))
            cur.execute("SELECT accounting.post_journal(%s, 'wasseem')", (j_id,))
            conn.commit()
            with pytest.raises(psycopg.errors.RaiseException):
                cur.execute("""
                    INSERT INTO accounting.ledger_entries
                        (journal_id, ledger_account_id, debit_credit, asset_id, amount_usd)
                    VALUES (%s, %s, 'debit', %s, 100)
                """, (j_id, ctx['fee_acct'], ctx['usdt_id']))
            conn.rollback()


def test_0005_entry_move_to_posted_blocked(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            j_a = _create_draft_journal(cur, ctx, source_id='post_a')
            cur.execute("""
                INSERT INTO accounting.ledger_entries
                    (journal_id, ledger_account_id, debit_credit, asset_id, amount_usd)
                VALUES (%s, %s, 'debit', %s, 1000), (%s, %s, 'credit', %s, 1000)
                RETURNING id
            """, (j_a, ctx['pos_acct'], ctx['btc_id'],
                  j_a, ctx['cash_acct'], ctx['usdt_id']))
            entry_ids = [row[0] for row in cur.fetchall()]
            cur.execute("SELECT accounting.post_journal(%s, 'wasseem')", (j_a,))
            j_b = _create_draft_journal(cur, ctx, source_id='draft_b')
            conn.commit()
            with pytest.raises(psycopg.errors.RaiseException):
                cur.execute("""
                    UPDATE accounting.ledger_entries SET journal_id = %s WHERE id = %s
                """, (j_b, entry_ids[0]))
            conn.rollback()


def test_0005_posted_entries_immutable(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            j_id = _create_draft_journal(cur, ctx, source_id='imm_1')
            cur.execute("""
                INSERT INTO accounting.ledger_entries
                    (journal_id, ledger_account_id, debit_credit, asset_id, amount_usd)
                VALUES (%s, %s, 'debit', %s, 1000), (%s, %s, 'credit', %s, 1000)
                RETURNING id
            """, (j_id, ctx['pos_acct'], ctx['btc_id'],
                  j_id, ctx['cash_acct'], ctx['usdt_id']))
            entry_ids = [row[0] for row in cur.fetchall()]
            cur.execute("SELECT accounting.post_journal(%s, 'wasseem')", (j_id,))
            conn.commit()
            with pytest.raises(psycopg.errors.RaiseException):
                cur.execute("UPDATE accounting.ledger_entries SET amount_usd = 999 WHERE id = %s", (entry_ids[0],))
            conn.rollback()
            with pytest.raises(psycopg.errors.RaiseException):
                cur.execute("DELETE FROM accounting.ledger_entries WHERE id = %s", (entry_ids[0],))
            conn.rollback()


def test_0005_draft_journal_editable(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            j_id = _create_draft_journal(cur, ctx, source_id='draft_edit')
            cur.execute("""
                INSERT INTO accounting.ledger_entries
                    (journal_id, ledger_account_id, debit_credit, asset_id, amount_usd)
                VALUES (%s, %s, 'debit', %s, 500)
                RETURNING id
            """, (j_id, ctx['pos_acct'], ctx['btc_id']))
            e_id = cur.fetchone()[0]
            cur.execute("UPDATE accounting.ledger_entries SET amount_usd = 1000 WHERE id = %s", (e_id,))
            cur.execute("DELETE FROM accounting.ledger_entries WHERE id = %s", (e_id,))
            conn.commit()


def test_0005_draft_journal_metadata_editable(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            j_id = _create_draft_journal(cur, ctx, source_id='metadata_edit')
            conn.commit()
            cur.execute("""
                UPDATE accounting.journals
                SET description = 'edited draft', source_hash = 'sha:abc123'
                WHERE id = %s
                RETURNING description, source_hash
            """, (j_id,))
            desc, hsh = cur.fetchone()
            assert desc == 'edited draft'
            assert hsh == 'sha:abc123'
            conn.commit()


def test_0005_draft_to_reversal_update_blocked(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            j_victim = _create_draft_journal(cur, ctx, source_id='victim_for_fake_reversal')
            cur.execute("""
                INSERT INTO accounting.ledger_entries
                    (journal_id, ledger_account_id, debit_credit, asset_id, amount_usd)
                VALUES (%s, %s, 'debit', %s, 1000), (%s, %s, 'credit', %s, 1000)
            """, (j_victim, ctx['pos_acct'], ctx['btc_id'],
                  j_victim, ctx['cash_acct'], ctx['usdt_id']))
            cur.execute("SELECT accounting.post_journal(%s, 'wasseem')", (j_victim,))
            j_normal = _create_draft_journal(cur, ctx, source_id='normal_draft_to_reversal')
            conn.commit()
            with pytest.raises(psycopg.errors.RaiseException) as exc:
                cur.execute("""
                    UPDATE accounting.journals
                    SET journal_type = 'reversal', voids_journal_id = %s
                    WHERE id = %s
                """, (j_victim, j_normal))
            assert 'reversal' in str(exc.value).lower()
            conn.rollback()


def test_0005_idempotent_source_event(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            _create_draft_journal(cur, ctx, source_id='idem_1', source_namespace='binance_futures')
            conn.commit()
            with pytest.raises(psycopg.errors.UniqueViolation):
                _create_draft_journal(cur, ctx, source_id='idem_1', source_namespace='binance_futures')
            conn.rollback()


def test_0005_source_namespace_isolation(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            j1 = _create_draft_journal(cur, ctx, source_id='same_id_12345', source_namespace='binance_futures')
            conn.commit()
            j2 = _create_draft_journal(cur, ctx, source_id='same_id_12345', source_namespace='okx')
            conn.commit()
            assert j1 != j2


def test_0005_void_journal_creates_reversal_original_stays_posted(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            j_id = _create_draft_journal(cur, ctx, source_id='void_test')
            cur.execute("""
                INSERT INTO accounting.ledger_entries
                    (journal_id, ledger_account_id, debit_credit, asset_id, quantity, amount_usd)
                VALUES (%s, %s, 'debit', %s, 0.01, 1000),
                       (%s, %s, 'credit', %s, 1000, 1000)
            """, (j_id, ctx['pos_acct'], ctx['btc_id'],
                  j_id, ctx['cash_acct'], ctx['usdt_id']))
            cur.execute("SELECT accounting.post_journal(%s, 'wasseem')", (j_id,))
            conn.commit()
            cur.execute("SELECT accounting.void_journal(%s, 'wasseem', 'Test')", (j_id,))
            reversal_id = cur.fetchone()[0]
            conn.commit()
            cur.execute("""
                SELECT status, voided_at, voided_by, voided_by_journal_id
                FROM accounting.journals WHERE id = %s
            """, (j_id,))
            status, voided_at, voided_by, voided_by_jid = cur.fetchone()
            assert status == 'posted'
            assert voided_at is not None
            assert voided_by == 'wasseem'
            assert voided_by_jid == reversal_id


def test_0005_void_net_zero_per_ledger_account(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            j_id = _create_draft_journal(cur, ctx, source_id='per_account_net_zero')
            cur.execute("""
                INSERT INTO accounting.ledger_entries
                    (journal_id, ledger_account_id, debit_credit, asset_id, quantity, amount_usd)
                VALUES (%s, %s, 'debit', %s, 0.01, 1000),
                       (%s, %s, 'credit', %s, 1000, 1000)
            """, (j_id, ctx['pos_acct'], ctx['btc_id'],
                  j_id, ctx['cash_acct'], ctx['usdt_id']))
            cur.execute("SELECT accounting.post_journal(%s, 'wasseem')", (j_id,))
            cur.execute("SELECT accounting.void_journal(%s, 'wasseem')", (j_id,))
            reversal_id = cur.fetchone()[0]
            conn.commit()
            cur.execute("""
                SELECT e.ledger_account_id,
                    SUM(CASE e.debit_credit WHEN 'debit' THEN e.amount_usd ELSE -e.amount_usd END)
                FROM accounting.ledger_entries e
                JOIN accounting.journals j ON j.id = e.journal_id
                WHERE j.status = 'posted' AND j.id IN (%s, %s)
                GROUP BY e.ledger_account_id
            """, (j_id, reversal_id))
            for ledger_account_id, account_net in cur.fetchall():
                assert account_net == Decimal("0"), \
                    f"Account {ledger_account_id} net is {account_net}, expected 0"


def test_0005_double_void_rejected(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            j_id = _create_draft_journal(cur, ctx, source_id='double_void')
            cur.execute("""
                INSERT INTO accounting.ledger_entries
                    (journal_id, ledger_account_id, debit_credit, asset_id, amount_usd)
                VALUES (%s, %s, 'debit', %s, 1000), (%s, %s, 'credit', %s, 1000)
            """, (j_id, ctx['pos_acct'], ctx['btc_id'],
                  j_id, ctx['cash_acct'], ctx['usdt_id']))
            cur.execute("SELECT accounting.post_journal(%s, 'wasseem')", (j_id,))
            cur.execute("SELECT accounting.void_journal(%s, 'wasseem')", (j_id,))
            conn.commit()
            with pytest.raises(psycopg.errors.RaiseException) as exc:
                cur.execute("SELECT accounting.void_journal(%s, 'wasseem')", (j_id,))
            assert 'already voided' in str(exc.value).lower()
            conn.rollback()


def test_0005_reversal_of_reversal_rejected(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            j_id = _create_draft_journal(cur, ctx, source_id='reversal_of_reversal')
            cur.execute("""
                INSERT INTO accounting.ledger_entries
                    (journal_id, ledger_account_id, debit_credit, asset_id, amount_usd)
                VALUES (%s, %s, 'debit', %s, 1000), (%s, %s, 'credit', %s, 1000)
            """, (j_id, ctx['pos_acct'], ctx['btc_id'],
                  j_id, ctx['cash_acct'], ctx['usdt_id']))
            cur.execute("SELECT accounting.post_journal(%s, 'wasseem')", (j_id,))
            cur.execute("SELECT accounting.void_journal(%s, 'wasseem')", (j_id,))
            reversal_id = cur.fetchone()[0]
            conn.commit()
            with pytest.raises(psycopg.errors.RaiseException) as exc:
                cur.execute("SELECT accounting.void_journal(%s, 'wasseem')", (reversal_id,))
            assert 'reversal' in str(exc.value).lower()
            conn.rollback()


def test_0005_cross_asset_trade_balances_in_usd(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            j_id = _create_draft_journal(cur, ctx, source_id='cross_asset_1')
            cur.execute("""
                INSERT INTO accounting.ledger_entries
                    (journal_id, ledger_account_id, debit_credit, asset_id, quantity, amount_usd)
                VALUES (%s, %s, 'debit', %s, 0.02, 1000),
                       (%s, %s, 'credit', %s, 1000, 1000)
            """, (j_id, ctx['pos_acct'], ctx['btc_id'],
                  j_id, ctx['cash_acct'], ctx['usdt_id']))
            conn.commit()
            cur.execute("SELECT accounting.post_journal(%s, 'wasseem')", (j_id,))
            conn.commit()
            cur.execute("SELECT status FROM accounting.journals WHERE id = %s", (j_id,))
            assert cur.fetchone()[0] == 'posted'


def test_0005_reversal_entries_by_account(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            j_id = _create_draft_journal(cur, ctx, source_id='reversal_by_account')
            cur.execute("""
                INSERT INTO accounting.ledger_entries
                    (journal_id, ledger_account_id, debit_credit, asset_id, quantity, amount_usd)
                VALUES (%s, %s, 'debit', %s, 0.01, 1000),
                       (%s, %s, 'credit', %s, 1000, 1000)
            """, (j_id, ctx['pos_acct'], ctx['btc_id'],
                  j_id, ctx['cash_acct'], ctx['usdt_id']))
            cur.execute("SELECT accounting.post_journal(%s, 'wasseem')", (j_id,))
            cur.execute("SELECT accounting.void_journal(%s, 'wasseem')", (j_id,))
            reversal_id = cur.fetchone()[0]
            conn.commit()
            cur.execute("""
                SELECT debit_credit FROM accounting.ledger_entries
                WHERE journal_id = %s AND ledger_account_id = %s
            """, (reversal_id, ctx['pos_acct']))
            assert cur.fetchone()[0] == 'credit'
            cur.execute("""
                SELECT debit_credit FROM accounting.ledger_entries
                WHERE journal_id = %s AND ledger_account_id = %s
            """, (reversal_id, ctx['cash_acct']))
            assert cur.fetchone()[0] == 'debit'


def test_0005_posted_journal_core_immutable(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            j_id = _create_draft_journal(cur, ctx, source_id='core_imm_1')
            cur.execute("""
                INSERT INTO accounting.ledger_entries
                    (journal_id, ledger_account_id, debit_credit, asset_id, amount_usd)
                VALUES (%s, %s, 'debit', %s, 1000), (%s, %s, 'credit', %s, 1000)
            """, (j_id, ctx['pos_acct'], ctx['btc_id'],
                  j_id, ctx['cash_acct'], ctx['usdt_id']))
            cur.execute("SELECT accounting.post_journal(%s, 'wasseem')", (j_id,))
            conn.commit()
            with pytest.raises(psycopg.errors.RaiseException):
                cur.execute("UPDATE accounting.journals SET description = 'modified' WHERE id = %s", (j_id,))
            conn.rollback()


def test_0005_source_id_required_except_system(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            conn.commit()
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("""
                    INSERT INTO accounting.journals
                        (journal_type, portfolio_id, strategy_id, journal_at,
                         source_type, source_namespace, created_by)
                    VALUES ('trade', %s, %s, NOW(), 'fill', 'binance_futures', 'wasseem')
                """, (ctx['portfolio_id'], ctx['strategy_id']))
            conn.rollback()
            cur.execute("""
                INSERT INTO accounting.journals
                    (journal_type, portfolio_id, strategy_id, journal_at,
                     source_type, source_namespace, created_by, description)
                VALUES ('adjustment', %s, %s, NOW(), 'system', 'global', 'wasseem', 'period close')
                RETURNING id
            """, (ctx['portfolio_id'], ctx['strategy_id']))
            assert cur.fetchone()[0] is not None
            conn.commit()


def test_0005_direct_void_metadata_update_blocked(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            j1 = _create_draft_journal(cur, ctx, source_id='void_direct_1')
            cur.execute("""
                INSERT INTO accounting.ledger_entries
                    (journal_id, ledger_account_id, debit_credit, asset_id, amount_usd)
                VALUES (%s, %s, 'debit', %s, 1000), (%s, %s, 'credit', %s, 1000)
            """, (j1, ctx['pos_acct'], ctx['btc_id'],
                  j1, ctx['cash_acct'], ctx['usdt_id']))
            cur.execute("SELECT accounting.post_journal(%s, 'wasseem')", (j1,))
            j2 = _create_draft_journal(cur, ctx, source_id='void_direct_2')
            cur.execute("""
                INSERT INTO accounting.ledger_entries
                    (journal_id, ledger_account_id, debit_credit, asset_id, amount_usd)
                VALUES (%s, %s, 'debit', %s, 500), (%s, %s, 'credit', %s, 500)
            """, (j2, ctx['pos_acct'], ctx['btc_id'],
                  j2, ctx['cash_acct'], ctx['usdt_id']))
            cur.execute("SELECT accounting.post_journal(%s, 'wasseem')", (j2,))
            conn.commit()
            with pytest.raises(psycopg.errors.RaiseException) as exc:
                cur.execute("""
                    UPDATE accounting.journals
                    SET voided_at = NOW(), voided_by = 'attacker', voided_by_journal_id = %s
                    WHERE id = %s
                """, (j2, j1))
            assert 'use accounting.void_journal' in str(exc.value).lower() or \
                   'forbidden' in str(exc.value).lower()
            conn.rollback()


def test_0005_direct_reversal_journal_creation_blocked(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            j_victim = _create_draft_journal(cur, ctx, source_id='victim_for_direct_reversal')
            cur.execute("""
                INSERT INTO accounting.ledger_entries
                    (journal_id, ledger_account_id, debit_credit, asset_id, amount_usd)
                VALUES (%s, %s, 'debit', %s, 1000), (%s, %s, 'credit', %s, 1000)
            """, (j_victim, ctx['pos_acct'], ctx['btc_id'],
                  j_victim, ctx['cash_acct'], ctx['usdt_id']))
            cur.execute("SELECT accounting.post_journal(%s, 'wasseem')", (j_victim,))
            conn.commit()
            with pytest.raises(psycopg.errors.RaiseException) as exc:
                cur.execute("""
                    INSERT INTO accounting.journals
                        (journal_type, portfolio_id, strategy_id, journal_at,
                         source_type, source_namespace, source_id, created_by, voids_journal_id)
                    VALUES ('reversal', %s, %s, NOW(),
                            'reversal', 'binance_futures', %s, 'attacker', %s)
                """, (ctx['portfolio_id'], ctx['strategy_id'], str(j_victim), j_victim))
            assert 'reversal' in str(exc.value).lower()
            conn.rollback()


def test_0005_ledger_account_identity_immutable_after_posted_use(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            cur.execute("""
                UPDATE accounting.ledger_accounts
                SET asset_id = %s
                WHERE id = %s
                RETURNING asset_id
            """, (ctx['usdt_id'], ctx['pos_acct']))
            assert cur.fetchone()[0] == ctx['usdt_id']
            cur.execute("""
                UPDATE accounting.ledger_accounts SET asset_id = %s WHERE id = %s
            """, (ctx['btc_id'], ctx['pos_acct']))
            conn.commit()
            j_id = _create_draft_journal(cur, ctx, source_id='identity_imm')
            cur.execute("""
                INSERT INTO accounting.ledger_entries
                    (journal_id, ledger_account_id, debit_credit, asset_id, amount_usd)
                VALUES (%s, %s, 'debit', %s, 1000), (%s, %s, 'credit', %s, 1000)
            """, (j_id, ctx['pos_acct'], ctx['btc_id'],
                  j_id, ctx['cash_acct'], ctx['usdt_id']))
            cur.execute("SELECT accounting.post_journal(%s, 'wasseem')", (j_id,))
            conn.commit()
            with pytest.raises(psycopg.errors.RaiseException) as exc:
                cur.execute("""
                    UPDATE accounting.ledger_accounts SET asset_id = %s WHERE id = %s
                """, (ctx['usdt_id'], ctx['pos_acct']))
            assert 'identity fields cannot change' in str(exc.value).lower()
            conn.rollback()
            cur.execute("""
                UPDATE accounting.ledger_accounts
                SET account_name = 'BTC Position (Renamed)', is_active = FALSE
                WHERE id = %s
                RETURNING account_name, is_active
            """, (ctx['pos_acct'],))
            name, active = cur.fetchone()
            assert name == 'BTC Position (Renamed)'
            assert active is False
            conn.commit()


def test_0005_account_type_subtype_alignment(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            conn.commit()
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("""
                    INSERT INTO accounting.ledger_accounts
                        (account_code, account_name, account_type, account_subtype,
                         portfolio_id, asset_id)
                    VALUES ('BAD_1', 'Bad', 'asset', 'fee_expense', %s, %s)
                """, (ctx['portfolio_id'], ctx['btc_id']))
            conn.rollback()
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("""
                    INSERT INTO accounting.ledger_accounts
                        (account_code, account_name, account_type, account_subtype,
                         portfolio_id, asset_id)
                    VALUES ('BAD_2', 'Bad', 'liability', 'cash', %s, %s)
                """, (ctx['portfolio_id'], ctx['btc_id']))
            conn.rollback()
            cur.execute("""
                INSERT INTO accounting.ledger_accounts
                    (account_code, account_name, account_type, account_subtype,
                     portfolio_id, asset_id)
                VALUES ('DEBT_1', 'Borrow Debt', 'liability', 'debt', %s, %s)
                RETURNING id
            """, (ctx['portfolio_id'], ctx['usdt_id']))
            assert cur.fetchone()[0] is not None
            conn.commit()


def test_0005_empty_text_fields_rejected(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            conn.commit()
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("""
                    INSERT INTO accounting.journals
                        (journal_type, portfolio_id, strategy_id, journal_at,
                         source_type, source_namespace, source_id, created_by)
                    VALUES ('trade', %s, %s, NOW(), 'fill', '', 'fill_x', 'wasseem')
                """, (ctx['portfolio_id'], ctx['strategy_id']))
            conn.rollback()
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("""
                    INSERT INTO accounting.journals
                        (journal_type, portfolio_id, strategy_id, journal_at,
                         source_type, source_namespace, source_id, created_by)
                    VALUES ('trade', %s, %s, NOW(), 'fill', 'binance', '   ', 'wasseem')
                """, (ctx['portfolio_id'], ctx['strategy_id']))
            conn.rollback()
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("""
                    INSERT INTO accounting.journals
                        (journal_type, portfolio_id, strategy_id, journal_at,
                         source_type, source_namespace, source_id, created_by)
                    VALUES ('trade', %s, %s, NOW(), 'fill', 'binance', 'fill_y', '')
                """, (ctx['portfolio_id'], ctx['strategy_id']))
            conn.rollback()


def test_0005_entry_asset_must_match_ledger_account_asset(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            j_id = _create_draft_journal(cur, ctx, source_id='asset_mismatch')
            with pytest.raises(psycopg.errors.RaiseException) as exc:
                cur.execute("""
                    INSERT INTO accounting.ledger_entries
                        (journal_id, ledger_account_id, debit_credit, asset_id, amount_usd)
                    VALUES (%s, %s, 'credit', %s, 1000)
                """, (j_id, ctx['cash_acct'], ctx['btc_id']))
            assert 'asset mismatch' in str(exc.value).lower()
            conn.rollback()


def test_0005_entry_portfolio_must_match_journal_portfolio(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            cur.execute("""
                INSERT INTO registry.portfolios (portfolio_code, display_name, product_type, status)
                VALUES ('other_portfolio', 'Other Portfolio', 'paper', 'research')
                RETURNING id
            """)
            other_portfolio_id = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO accounting.ledger_accounts
                    (account_code, account_name, account_type, account_subtype,
                     portfolio_id, asset_id)
                VALUES ('OTHER_CASH', 'Other Cash', 'asset', 'cash', %s, %s)
                RETURNING id
            """, (other_portfolio_id, ctx['usdt_id']))
            other_cash_acct = cur.fetchone()[0]
            j_id = _create_draft_journal(cur, ctx, source_id='portfolio_mismatch')
            conn.commit()
            with pytest.raises(psycopg.errors.RaiseException) as exc:
                cur.execute("""
                    INSERT INTO accounting.ledger_entries
                        (journal_id, ledger_account_id, debit_credit, asset_id, amount_usd)
                    VALUES (%s, %s, 'debit', %s, 1000)
                """, (j_id, other_cash_acct, ctx['usdt_id']))
            assert 'portfolio mismatch' in str(exc.value).lower()
            conn.rollback()


def test_0005_entry_strategy_must_match_journal_strategy(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            cur.execute("""
                INSERT INTO registry.strategies
                    (name, display_name, current_phase, phase_entered_at, hypothesis_doc_path)
                VALUES ('other_strategy', 'Other', 'research', NOW(), 'docs/o.md')
                RETURNING id
            """)
            other_strategy_id = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO accounting.ledger_accounts
                    (account_code, account_name, account_type, account_subtype,
                     portfolio_id, strategy_id, asset_id)
                VALUES ('OTHER_STRAT_CASH', 'Other Strat Cash', 'asset', 'cash',
                        %s, %s, %s)
                RETURNING id
            """, (ctx['portfolio_id'], other_strategy_id, ctx['usdt_id']))
            other_strat_acct = cur.fetchone()[0]
            j_id = _create_draft_journal(cur, ctx, source_id='strategy_mismatch')
            conn.commit()
            with pytest.raises(psycopg.errors.RaiseException) as exc:
                cur.execute("""
                    INSERT INTO accounting.ledger_entries
                        (journal_id, ledger_account_id, debit_credit, asset_id, amount_usd)
                    VALUES (%s, %s, 'debit', %s, 1000)
                """, (j_id, other_strat_acct, ctx['usdt_id']))
            assert 'strategy mismatch' in str(exc.value).lower()
            conn.rollback()


def test_0005_v5_post_journal_revalidates_after_journal_portfolio_mutation(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            cur.execute("""
                INSERT INTO registry.portfolios (portfolio_code, display_name, product_type, status)
                VALUES ('other_portfolio', 'Other Portfolio', 'paper', 'research')
                RETURNING id
            """)
            other_portfolio_id = cur.fetchone()[0]
            j_id = _create_draft_journal(cur, ctx, source_id='post_time_portfolio_mut')
            cur.execute("""
                INSERT INTO accounting.ledger_entries
                    (journal_id, ledger_account_id, debit_credit, asset_id, amount_usd)
                VALUES (%s, %s, 'debit', %s, 1000), (%s, %s, 'credit', %s, 1000)
            """, (j_id, ctx['pos_acct'], ctx['btc_id'],
                  j_id, ctx['cash_acct'], ctx['usdt_id']))
            conn.commit()
            cur.execute("""
                UPDATE accounting.journals SET portfolio_id = %s WHERE id = %s
            """, (other_portfolio_id, j_id))
            conn.commit()
            with pytest.raises(psycopg.errors.RaiseException) as exc:
                cur.execute("SELECT accounting.post_journal(%s, 'wasseem')", (j_id,))
            err = str(exc.value).lower()
            assert 'dimensionally inconsistent' in err or 'portfolio mismatch' in err
            conn.rollback()


def test_0005_v5_post_journal_revalidates_after_journal_strategy_mutation(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            cur.execute("""
                INSERT INTO registry.strategies
                    (name, display_name, current_phase, phase_entered_at, hypothesis_doc_path)
                VALUES ('other_strat', 'Other', 'research', NOW(), 'docs/o.md')
                RETURNING id
            """)
            other_strategy_id = cur.fetchone()[0]
            j_id = _create_draft_journal(cur, ctx, source_id='post_time_strategy_mut')
            cur.execute("""
                INSERT INTO accounting.ledger_entries
                    (journal_id, ledger_account_id, debit_credit, asset_id, amount_usd)
                VALUES (%s, %s, 'debit', %s, 1000), (%s, %s, 'credit', %s, 1000)
            """, (j_id, ctx['pos_acct'], ctx['btc_id'],
                  j_id, ctx['cash_acct'], ctx['usdt_id']))
            conn.commit()
            cur.execute("""
                UPDATE accounting.journals SET strategy_id = %s WHERE id = %s
            """, (other_strategy_id, j_id))
            conn.commit()
            with pytest.raises(psycopg.errors.RaiseException) as exc:
                cur.execute("SELECT accounting.post_journal(%s, 'wasseem')", (j_id,))
            err = str(exc.value).lower()
            assert 'dimensionally inconsistent' in err or 'strategy mismatch' in err
            conn.rollback()


def test_0005_v5_ledger_account_identity_immutable_after_draft_entry(fresh_db):
    _alembic("upgrade", "0005")
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _setup_basic_accounting(cur)
            j_id = _create_draft_journal(cur, ctx, source_id='draft_use_identity')
            cur.execute("""
                INSERT INTO accounting.ledger_entries
                    (journal_id, ledger_account_id, debit_credit, asset_id, amount_usd)
                VALUES (%s, %s, 'debit', %s, 1000)
            """, (j_id, ctx['pos_acct'], ctx['btc_id']))
            conn.commit()
            with pytest.raises(psycopg.errors.RaiseException) as exc:
                cur.execute("""
                    UPDATE accounting.ledger_accounts SET asset_id = %s WHERE id = %s
                """, (ctx['usdt_id'], ctx['pos_acct']))
            assert 'identity fields cannot change' in str(exc.value).lower()
            conn.rollback()
            cur.execute("""
                UPDATE accounting.ledger_accounts
                SET account_name = 'Renamed', is_active = FALSE
                WHERE id = %s
                RETURNING account_name
            """, (ctx['pos_acct'],))
            assert cur.fetchone()[0] == 'Renamed'
            conn.commit()


def test_0005_downgrade_clean(fresh_db):
    _alembic("upgrade", "0005")
    result = _alembic("downgrade", "0004b")
    assert result.returncode == 0, f"Downgrade failed: {result.stderr}"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'accounting' AND table_type = 'BASE TABLE'
            """)
            assert cur.fetchall() == []
            cur.execute("""
                SELECT proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'accounting'
            """)
            assert cur.fetchall() == []
            cur.execute("""
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema = 'registry' AND table_type = 'BASE TABLE'
            """)
            assert cur.fetchone()[0] == 24


# ============================================================
# Migration 0004c tests: registry_guardrails_followup (v3)
# ============================================================


def _setup_strategy_for_0004c(cur, name='mn_ls_test'):
    cur.execute("""
        INSERT INTO registry.strategies
            (name, display_name, current_phase, phase_entered_at, hypothesis_doc_path)
        VALUES (%s, 'Test', 'research', NOW(), 'docs/h.md')
        RETURNING id
    """, (name,))
    return cur.fetchone()[0]


def _setup_model_for_0004c(cur, strategy_id, version_id='m1'):
    cur.execute("""
        INSERT INTO registry.models
            (strategy_id, version_id, model_class, training_data_hash,
             feature_set_hash, hyperparam_hash, artifact_path, artifact_hash, trained_at)
        VALUES (%s, %s, 'lightgbm', 'd1', 'f1', 'h1', 's3://m', 'sha:1', NOW())
        RETURNING id
    """, (strategy_id, version_id))
    return cur.fetchone()[0]


def _setup_active_deployment(cur, strategy_id, model_id, slot='default'):
    cur.execute("""
        INSERT INTO registry.model_deployments
            (model_id, strategy_id, environment, deployment_role, deployment_slot,
             deployed_at, deployed_by)
        VALUES (%s, %s, 'shadow', 'primary', %s, NOW(), 'wasseem')
        RETURNING id
    """, (model_id, strategy_id, slot))
    return cur.fetchone()[0]


def test_0004c_direct_strategy_phase_update_blocked(fresh_db):
    _alembic("upgrade", "0004c")
    with _connect() as conn:
        with conn.cursor() as cur:
            strategy_id = _setup_strategy_for_0004c(cur)
            conn.commit()
            with pytest.raises(psycopg.errors.RaiseException):
                cur.execute("UPDATE registry.strategies SET current_phase = 'canary' WHERE id = %s", (strategy_id,))
            conn.rollback()
            cur.execute("UPDATE registry.strategies SET description = 'updated' WHERE id = %s RETURNING description", (strategy_id,))
            assert cur.fetchone()[0] == 'updated'
            conn.commit()


def test_0004c_promotion_syncs_strategy_phase(fresh_db):
    _alembic("upgrade", "0004c")
    with _connect() as conn:
        with conn.cursor() as cur:
            strategy_id = _setup_strategy_for_0004c(cur)
            conn.commit()
            cur.execute("""
                INSERT INTO registry.promotions
                    (strategy_id, from_phase, to_phase, operator_id, operator_signature,
                     signature_method, gate_evidence_doc_path)
                VALUES (%s, 'research', 'shadow', 'wasseem', 'sig', 'gpg', 'docs/p.md')
            """, (strategy_id,))
            conn.commit()
            cur.execute("SELECT current_phase FROM registry.strategies WHERE id = %s", (strategy_id,))
            assert cur.fetchone()[0] == 'shadow'


def test_0004c_revocation_with_no_active_promotion_sets_paused(fresh_db):
    _alembic("upgrade", "0004c")
    with _connect() as conn:
        with conn.cursor() as cur:
            strategy_id = _setup_strategy_for_0004c(cur)
            cur.execute("""
                INSERT INTO registry.promotions
                    (strategy_id, from_phase, to_phase, operator_id, operator_signature,
                     signature_method, gate_evidence_doc_path)
                VALUES (%s, 'research', 'shadow', 'wasseem', 'sig', 'gpg', 'docs/p.md')
                RETURNING id
            """, (strategy_id,))
            promo_id = cur.fetchone()[0]
            conn.commit()
            cur.execute("""
                UPDATE registry.promotions
                SET revoked_at = NOW(), revoked_by = 'wasseem',
                    revocation_signature = 'rev-sig', revocation_signature_method = 'gpg',
                    revocation_reason = 'test'
                WHERE id = %s
            """, (promo_id,))
            conn.commit()
            cur.execute("SELECT current_phase FROM registry.strategies WHERE id = %s", (strategy_id,))
            assert cur.fetchone()[0] == 'paused'


def test_0004c_promotion_must_be_inserted_active(fresh_db):
    _alembic("upgrade", "0004c")
    with _connect() as conn:
        with conn.cursor() as cur:
            strategy_id = _setup_strategy_for_0004c(cur)
            conn.commit()
            with pytest.raises(psycopg.errors.RaiseException) as exc:
                cur.execute("""
                    INSERT INTO registry.promotions
                        (strategy_id, from_phase, to_phase, operator_id, operator_signature,
                         signature_method, gate_evidence_doc_path,
                         revoked_at, revoked_by, revocation_signature,
                         revocation_signature_method, revocation_reason)
                    VALUES (%s, 'research', 'shadow', 'wasseem', 'sig', 'gpg', 'docs/p.md',
                            NOW(), 'wasseem', 'rev', 'gpg', 'pre-revoked')
                """, (strategy_id,))
            assert 'inserted active' in str(exc.value).lower()
            conn.rollback()


def test_0004c_promotion_event_immutability(fresh_db):
    _alembic("upgrade", "0004c")
    with _connect() as conn:
        with conn.cursor() as cur:
            strategy_id = _setup_strategy_for_0004c(cur)
            cur.execute("""
                INSERT INTO registry.promotions
                    (strategy_id, from_phase, to_phase, operator_id, operator_signature,
                     signature_method, gate_evidence_doc_path)
                VALUES (%s, 'research', 'shadow', 'wasseem', 'sig', 'gpg', 'docs/p.md')
                RETURNING id
            """, (strategy_id,))
            promo_id = cur.fetchone()[0]
            conn.commit()
            with pytest.raises(psycopg.errors.RaiseException):
                cur.execute("UPDATE registry.promotions SET to_phase = 'canary' WHERE id = %s", (promo_id,))
            conn.rollback()
            with pytest.raises(psycopg.errors.RaiseException):
                cur.execute("UPDATE registry.promotions SET gate_evidence_doc_path = 'fake.md' WHERE id = %s", (promo_id,))
            conn.rollback()
            cur.execute("""
                UPDATE registry.promotions
                SET revoked_at = NOW(), revoked_by = 'wasseem',
                    revocation_signature = 'rev', revocation_signature_method = 'gpg',
                    revocation_reason = 'test'
                WHERE id = %s
                RETURNING revoked_at
            """, (promo_id,))
            assert cur.fetchone()[0] is not None
            conn.commit()
            with pytest.raises(psycopg.errors.RaiseException):
                cur.execute("UPDATE registry.promotions SET revocation_reason = 'changed' WHERE id = %s", (promo_id,))
            conn.rollback()


def test_0004c_model_must_be_inserted_active(fresh_db):
    _alembic("upgrade", "0004c")
    with _connect() as conn:
        with conn.cursor() as cur:
            strategy_id = _setup_strategy_for_0004c(cur)
            conn.commit()
            with pytest.raises(psycopg.errors.RaiseException) as exc:
                cur.execute("""
                    INSERT INTO registry.models
                        (strategy_id, version_id, model_class, training_data_hash,
                         feature_set_hash, hyperparam_hash, artifact_path, artifact_hash, trained_at,
                         retired_at, retired_by, retirement_reason)
                    VALUES (%s, 'm_pre_retired', 'lightgbm', 'd1', 'f1', 'h1', 's3://m', 'sha:1', NOW(),
                            NOW(), 'wasseem', 'pre-retired')
                """, (strategy_id,))
            assert 'inserted active' in str(exc.value).lower()
            conn.rollback()


def test_0004c_deployment_must_be_inserted_active(fresh_db):
    _alembic("upgrade", "0004c")
    with _connect() as conn:
        with conn.cursor() as cur:
            strategy_id = _setup_strategy_for_0004c(cur)
            model_id = _setup_model_for_0004c(cur, strategy_id)
            conn.commit()
            with pytest.raises(psycopg.errors.RaiseException) as exc:
                cur.execute("""
                    INSERT INTO registry.model_deployments
                        (model_id, strategy_id, environment, deployment_role, deployment_slot,
                         deployed_at, deployed_by, retired_at, retired_by, retirement_reason)
                    VALUES (%s, %s, 'shadow', 'primary', 'default', NOW(), 'wasseem',
                            NOW(), 'wasseem', 'pre-retired')
                """, (model_id, strategy_id))
            assert 'inserted active' in str(exc.value).lower()
            conn.rollback()


def test_0004c_model_retirement_requires_full_metadata(fresh_db):
    _alembic("upgrade", "0004c")
    with _connect() as conn:
        with conn.cursor() as cur:
            strategy_id = _setup_strategy_for_0004c(cur)
            model_id = _setup_model_for_0004c(cur, strategy_id)
            conn.commit()
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("UPDATE registry.models SET retired_at = NOW() WHERE id = %s", (model_id,))
            conn.rollback()
            cur.execute("""
                UPDATE registry.models
                SET retired_at = NOW(), retired_by = 'wasseem', retirement_reason = 'replaced'
                WHERE id = %s
                RETURNING retired_at, retired_by, retirement_reason
            """, (model_id,))
            row = cur.fetchone()
            assert row[0] is not None
            assert row[1] == 'wasseem'
            assert row[2] == 'replaced'
            conn.commit()


def test_0004c_model_retirement_irreversible(fresh_db):
    _alembic("upgrade", "0004c")
    with _connect() as conn:
        with conn.cursor() as cur:
            strategy_id = _setup_strategy_for_0004c(cur)
            model_id = _setup_model_for_0004c(cur, strategy_id)
            cur.execute("""
                UPDATE registry.models
                SET retired_at = NOW(), retired_by = 'wasseem', retirement_reason = 'replaced'
                WHERE id = %s
            """, (model_id,))
            conn.commit()
            with pytest.raises(psycopg.errors.RaiseException):
                cur.execute("""
                    UPDATE registry.models
                    SET retired_at = NULL, retired_by = NULL, retirement_reason = NULL
                    WHERE id = %s
                """, (model_id,))
            conn.rollback()
            with pytest.raises(psycopg.errors.RaiseException):
                cur.execute("UPDATE registry.models SET retirement_reason = 'different' WHERE id = %s", (model_id,))
            conn.rollback()


def test_0004c_deployment_identity_immutability(fresh_db):
    _alembic("upgrade", "0004c")
    with _connect() as conn:
        with conn.cursor() as cur:
            strategy_id = _setup_strategy_for_0004c(cur)
            model_a = _setup_model_for_0004c(cur, strategy_id, 'm_a')
            model_b = _setup_model_for_0004c(cur, strategy_id, 'm_b')
            deployment_id = _setup_active_deployment(cur, strategy_id, model_a)
            conn.commit()
            with pytest.raises(psycopg.errors.RaiseException):
                cur.execute("UPDATE registry.model_deployments SET model_id = %s WHERE id = %s",
                           (model_b, deployment_id))
            conn.rollback()
            with pytest.raises(psycopg.errors.RaiseException):
                cur.execute("UPDATE registry.model_deployments SET environment = 'canary' WHERE id = %s",
                           (deployment_id,))
            conn.rollback()


def test_0004c_deployment_retirement_irreversible(fresh_db):
    _alembic("upgrade", "0004c")
    with _connect() as conn:
        with conn.cursor() as cur:
            strategy_id = _setup_strategy_for_0004c(cur)
            model_id = _setup_model_for_0004c(cur, strategy_id)
            deployment_id = _setup_active_deployment(cur, strategy_id, model_id)
            conn.commit()
            import time; time.sleep(0.01)
            cur.execute("""
                UPDATE registry.model_deployments
                SET retired_at = NOW(), retired_by = 'wasseem', retirement_reason = 'paused'
                WHERE id = %s
            """, (deployment_id,))
            conn.commit()
            with pytest.raises(psycopg.errors.RaiseException):
                cur.execute("""
                    UPDATE registry.model_deployments
                    SET retired_at = NULL, retired_by = NULL, retirement_reason = NULL
                    WHERE id = %s
                """, (deployment_id,))
            conn.rollback()


def test_0004c_cannot_deploy_retired_model(fresh_db):
    _alembic("upgrade", "0004c")
    with _connect() as conn:
        with conn.cursor() as cur:
            strategy_id = _setup_strategy_for_0004c(cur)
            model_id = _setup_model_for_0004c(cur, strategy_id)
            cur.execute("""
                UPDATE registry.models
                SET retired_at = NOW(), retired_by = 'wasseem', retirement_reason = 'experimental'
                WHERE id = %s
            """, (model_id,))
            conn.commit()
            with pytest.raises(psycopg.errors.RaiseException) as exc:
                cur.execute("""
                    INSERT INTO registry.model_deployments
                        (model_id, strategy_id, environment, deployment_role, deployment_slot,
                         deployed_at, deployed_by)
                    VALUES (%s, %s, 'shadow', 'primary', 'default', NOW(), 'wasseem')
                """, (model_id, strategy_id))
            assert 'retired' in str(exc.value).lower()
            conn.rollback()


def test_0004c_cannot_retire_model_with_active_deployment(fresh_db):
    _alembic("upgrade", "0004c")
    with _connect() as conn:
        with conn.cursor() as cur:
            strategy_id = _setup_strategy_for_0004c(cur)
            model_id = _setup_model_for_0004c(cur, strategy_id)
            _setup_active_deployment(cur, strategy_id, model_id)
            conn.commit()
            with pytest.raises(psycopg.errors.RaiseException) as exc:
                cur.execute("""
                    UPDATE registry.models
                    SET retired_at = NOW(), retired_by = 'wasseem', retirement_reason = 'replaced'
                    WHERE id = %s
                """, (model_id,))
            assert 'active deployment' in str(exc.value).lower()
            conn.rollback()


def test_0004c_can_retire_deployment_then_model(fresh_db):
    _alembic("upgrade", "0004c")
    with _connect() as conn:
        with conn.cursor() as cur:
            strategy_id = _setup_strategy_for_0004c(cur)
            model_id = _setup_model_for_0004c(cur, strategy_id)
            deployment_id = _setup_active_deployment(cur, strategy_id, model_id)
            conn.commit()
            cur.execute("""
                UPDATE registry.model_deployments
                SET retired_at = NOW(), retired_by = 'wasseem', retirement_reason = 'switching'
                WHERE id = %s
            """, (deployment_id,))
            cur.execute("""
                UPDATE registry.models
                SET retired_at = NOW(), retired_by = 'wasseem', retirement_reason = 'replaced'
                WHERE id = %s
                RETURNING retired_at
            """, (model_id,))
            assert cur.fetchone()[0] is not None
            conn.commit()


def test_0004c_audit_records_cannot_be_deleted(fresh_db):
    _alembic("upgrade", "0004c")
    with _connect() as conn:
        with conn.cursor() as cur:
            strategy_id = _setup_strategy_for_0004c(cur)
            model_id = _setup_model_for_0004c(cur, strategy_id)
            deployment_id = _setup_active_deployment(cur, strategy_id, model_id)
            cur.execute("""
                INSERT INTO registry.promotions
                    (strategy_id, from_phase, to_phase, operator_id, operator_signature,
                     signature_method, gate_evidence_doc_path)
                VALUES (%s, 'research', 'shadow', 'wasseem', 'sig', 'gpg', 'docs/p.md')
                RETURNING id
            """, (strategy_id,))
            promo_id = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO registry.features
                    (feature_name, version, definition, computation_script_path,
                     data_sources, refresh_cadence)
                VALUES ('feat_test', 1, 'def', 'fz.py', '[]'::jsonb, '1h')
                RETURNING id
            """)
            feature_id = cur.fetchone()[0]
            conn.commit()

            for table, row_id in [
                ('promotions', promo_id),
                ('model_deployments', deployment_id),
                ('models', model_id),
                ('features', feature_id),
            ]:
                with pytest.raises(psycopg.errors.RaiseException) as exc:
                    cur.execute(f"DELETE FROM registry.{table} WHERE id = %s", (row_id,))
                assert 'append-only' in str(exc.value).lower() or 'forbidden' in str(exc.value).lower()
                conn.rollback()


def test_0004c_downgrade_clean(fresh_db):
    _alembic("upgrade", "0004c")
    result = _alembic("downgrade", "0005")
    assert result.returncode == 0, f"Downgrade failed: {result.stderr}"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'registry'
                  AND proname IN ('enforce_strategy_phase_cache_update',
                                  'enforce_no_deploy_retired_model',
                                  'enforce_no_retire_with_active_deployments',
                                  'enforce_model_retirement_irreversibility',
                                  'enforce_deployment_retirement_irreversibility',
                                  'enforce_promotion_event_immutability',
                                  'enforce_deployment_identity_immutability',
                                  'enforce_model_insert_active',
                                  'enforce_deployment_insert_active',
                                  'prevent_registry_audit_delete')
            """)
            assert cur.fetchall() == []
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'registry'
                  AND ((table_name = 'models' AND column_name = 'retired_by')
                       OR (table_name = 'model_deployments' AND column_name IN ('retired_by', 'retirement_reason')))
            """)
            assert cur.fetchall() == []
