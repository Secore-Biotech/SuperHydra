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
