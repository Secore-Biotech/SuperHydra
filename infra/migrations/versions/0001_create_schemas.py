"""create_schemas

Revision ID: 0001
Revises:
Create Date: 2026-05-03

Creates the 10 schemas required for SuperHydra Phase 1, installs required
extensions, and defines the corrected gen_uuidv7() function with init-time
sanity tests.

The original gen_uuidv7() in ledger schema v0.3 produced 18-byte hex output
(invalid UUID). The corrected implementation truncates the BIGINT timestamp
to 6 bytes per RFC 9562 section 5.7.

Per reviewer recommendation (2026-05-03), this migration includes additional
sanity tests beyond the original: variant nibble check, 100k uniqueness test
(deferred to test harness), and time-ordering assertion.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Extensions (idempotent — already installed by docker init script,
    # but we re-declare here so this migration can run against a fresh DB)
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")

    # Force database timezone to UTC (per data_policy v1.1)
    op.execute("SET TIMEZONE TO 'UTC';")

    # Drop any existing function before redefining (safe re-run)
    op.execute("DROP FUNCTION IF EXISTS gen_uuidv7();")

    # gen_uuidv7() — corrected per reviewer feedback 2026-05-03
    # Layout (RFC 9562 section 5.7):
    #   48 bits: unix_ts_ms (milliseconds since epoch)
    #    4 bits: version (must be 0111 = 7)
    #   12 bits: random
    #    2 bits: variant (must be 10)
    #   62 bits: random
    op.execute("""
        CREATE OR REPLACE FUNCTION gen_uuidv7() RETURNS UUID AS $$
        DECLARE
            unix_ts_ms_bytes BYTEA;
            rand_bytes BYTEA;
            uuid_bytes BYTEA;
        BEGIN
            unix_ts_ms_bytes := substring(
                int8send((EXTRACT(EPOCH FROM clock_timestamp()) * 1000)::BIGINT)
                FROM 3 FOR 6
            );
            rand_bytes := gen_random_bytes(10);
            uuid_bytes := unix_ts_ms_bytes || rand_bytes;
            uuid_bytes := set_byte(uuid_bytes, 6, (get_byte(uuid_bytes, 6) & 15) | 112);
            uuid_bytes := set_byte(uuid_bytes, 8, (get_byte(uuid_bytes, 8) & 63) | 128);
            RETURN encode(uuid_bytes, 'hex')::UUID;
        END;
        $$ LANGUAGE plpgsql VOLATILE;
    """)

    # Sanity test: function produces correct format
    op.execute("""
        DO $$
        DECLARE
            test_uuid UUID;
            test_text TEXT;
            variant_char CHAR(1);
        BEGIN
            test_uuid := gen_uuidv7();
            test_text := test_uuid::TEXT;

            IF length(test_text) != 36 THEN
                RAISE EXCEPTION 'gen_uuidv7() wrong length: %', test_text;
            END IF;

            IF substring(test_text, 15, 1) != '7' THEN
                RAISE EXCEPTION 'gen_uuidv7() wrong version nibble: %', test_text;
            END IF;

            -- Variant must be 8, 9, a, or b (per RFC 4122/9562)
            variant_char := substring(test_text, 20, 1);
            IF variant_char NOT IN ('8', '9', 'a', 'b') THEN
                RAISE EXCEPTION 'gen_uuidv7() wrong variant nibble: %', test_text;
            END IF;

            RAISE NOTICE 'gen_uuidv7() sanity test passed: %', test_text;
        END;
        $$;
    """)

    # Time-ordering test: 5 UUIDs generated 1ms apart should sort in generation order
    op.execute("""
        DO $$
        DECLARE
            uuid_1 UUID;
            uuid_2 UUID;
            uuid_3 UUID;
        BEGIN
            uuid_1 := gen_uuidv7();
            PERFORM pg_sleep(0.002);
            uuid_2 := gen_uuidv7();
            PERFORM pg_sleep(0.002);
            uuid_3 := gen_uuidv7();

            IF NOT (uuid_1 < uuid_2 AND uuid_2 < uuid_3) THEN
                RAISE EXCEPTION 'gen_uuidv7() time-ordering failed: %, %, %',
                    uuid_1, uuid_2, uuid_3;
            END IF;

            RAISE NOTICE 'gen_uuidv7() time-ordering test passed';
        END;
        $$;
    """)

    # Create the 10 schemas required for Phase 1
    # Per reviewer recommendation 2026-05-03 (was incorrectly listed as 8)
    schemas = [
        "registry",
        "accounting",
        "trading",
        "positions",
        "risk",
        "audit",
        "data_ingestion",
        "market_data",
        "feature_store",
        "validation",
    ]
    for schema in schemas:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema};")

    # Verify all 10 schemas exist
    op.execute("""
        DO $$
        DECLARE
            expected_count INT := 10;
            actual_count INT;
        BEGIN
            SELECT COUNT(*) INTO actual_count
            FROM information_schema.schemata
            WHERE schema_name IN (
                'registry', 'accounting', 'trading', 'positions', 'risk',
                'audit', 'data_ingestion', 'market_data', 'feature_store', 'validation'
            );

            IF actual_count != expected_count THEN
                RAISE EXCEPTION 'Expected % schemas, found %', expected_count, actual_count;
            END IF;

            RAISE NOTICE 'All 10 schemas created and verified';
        END;
        $$;
    """)


def downgrade() -> None:
    # Drop schemas in reverse order; CASCADE because tables added in later migrations
    schemas = [
        "validation",
        "feature_store",
        "market_data",
        "data_ingestion",
        "audit",
        "risk",
        "positions",
        "trading",
        "accounting",
        "registry",
    ]
    for schema in schemas:
        op.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE;")

    # Drop the function
    op.execute("DROP FUNCTION IF EXISTS gen_uuidv7();")
