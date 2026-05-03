-- SuperHydra Phase 1 Postgres extensions and initial setup
-- Runs once on first container start

-- TimescaleDB: time-series hypertables for OHLCV, funding rates, ledger entries
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- pgcrypto: gen_random_bytes() for UUIDv7 generation
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Partition lifecycle is managed by application code, not pg_partman.
-- Native Postgres PARTITION BY RANGE handles the partitioned tables.
-- TimescaleDB hypertables handle time-series via create_hypertable().

-- UUIDv7 generation per RFC 9562
-- Layout (128 bits total):
--   48 bits: unix_ts_ms (milliseconds since epoch)
--    4 bits: version (must be 0111 = 7)
--   12 bits: random
--    2 bits: variant (must be 10)
--   62 bits: random
CREATE OR REPLACE FUNCTION gen_uuidv7() RETURNS UUID AS $$
DECLARE
    unix_ts_ms_bytes BYTEA;
    rand_bytes BYTEA;
    uuid_bytes BYTEA;
BEGIN
    -- Get 48-bit timestamp: take last 6 bytes of the 8-byte BIGINT
    -- (unix_ts_ms in milliseconds fits in 48 bits until year ~10895)
    unix_ts_ms_bytes := substring(int8send((EXTRACT(EPOCH FROM clock_timestamp()) * 1000)::BIGINT) FROM 3 FOR 6);

    -- Get 10 random bytes for the rest
    rand_bytes := gen_random_bytes(10);

    -- Concatenate: 6 bytes timestamp + 10 bytes random = 16 bytes
    uuid_bytes := unix_ts_ms_bytes || rand_bytes;

    -- Set version to 7: byte 6 (0-indexed), top 4 bits = 0111
    -- Clear top 4 bits of byte 6, then OR with 0x70
    uuid_bytes := set_byte(uuid_bytes, 6, (get_byte(uuid_bytes, 6) & 15) | 112);

    -- Set variant to RFC 4122: byte 8 (0-indexed), top 2 bits = 10
    -- Clear top 2 bits of byte 8, then OR with 0x80
    uuid_bytes := set_byte(uuid_bytes, 8, (get_byte(uuid_bytes, 8) & 63) | 128);

    -- Convert to UUID via hex encoding
    RETURN encode(uuid_bytes, 'hex')::UUID;
END;
$$ LANGUAGE plpgsql VOLATILE;

-- Sanity test the function before granting (will raise if broken)
DO $$
DECLARE
    test_uuid UUID;
    test_uuid_text TEXT;
BEGIN
    test_uuid := gen_uuidv7();
    test_uuid_text := test_uuid::TEXT;

    -- Verify it parses as a UUID
    IF length(test_uuid_text) != 36 THEN
        RAISE EXCEPTION 'gen_uuidv7() produced wrong length: %', test_uuid_text;
    END IF;

    -- Verify version nibble is 7 (character 14 of the UUID string,
    -- which is position 14 in 'xxxxxxxx-xxxx-Mxxx-Nxxx-xxxxxxxxxxxx')
    IF substring(test_uuid_text, 15, 1) != '7' THEN
        RAISE EXCEPTION 'gen_uuidv7() produced wrong version nibble: %', test_uuid_text;
    END IF;

    RAISE NOTICE 'gen_uuidv7() sanity test passed: %', test_uuid_text;
END;
$$;

-- Grant superhydra user permissions and set timezone
GRANT ALL ON DATABASE superhydra TO superhydra;
ALTER DATABASE superhydra SET timezone TO 'UTC';

-- Confirm extensions installed
SELECT extname, extversion FROM pg_extension ORDER BY extname;
