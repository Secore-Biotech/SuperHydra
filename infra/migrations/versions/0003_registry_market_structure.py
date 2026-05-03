"""registry_market_structure

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-03

Creates effective-dated and structural metadata tables:
- vendors: data sources (Tardis, Glassnode, etc.); separate from venues
- symbol_translations: vendor_symbol -> canonical instrument_id mapping
- instrument_specs_history: effective-dated tick_size, lot_size, etc.
- fee_schedules: effective-dated maker/taker fees
- asset_clusters: cluster definitions (DeFi, L1, etc.)
- asset_cluster_memberships: asset-level cluster membership
- venue_capabilities: per-venue feature support, effective-dated

Uses btree_gist exclusion constraints to prevent overlapping effective ranges.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Required for time-range exclusion constraints
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist;")

    # ===== registry.vendors =====
    # Moved from 0004 into 0003 because symbol_translations depends on it.
    # Vendors are data sources; venues are trading venues. Some entities exist
    # in both registries (Binance is both vendor and venue).
    op.execute("""
        CREATE TABLE registry.vendors (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            data_types TEXT[] NOT NULL,
            tier TEXT,
            monthly_cost_usd NUMERIC(10,2) NOT NULL DEFAULT 0,
            status TEXT NOT NULL CHECK (status IN ('active', 'pending', 'paused', 'sunset')),
            verified_status TEXT NOT NULL CHECK (verified_status IN ('VERIFIED', 'UNVERIFIED')),
            last_verified_at TIMESTAMPTZ,
            verification_due_by DATE,
            phase_one_use BOOLEAN NOT NULL DEFAULT FALSE,
            credential_secret_name TEXT,
            endpoint_config JSONB NOT NULL DEFAULT '{}'::jsonb,
            config JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    op.execute("""
        CREATE INDEX idx_vendors_status ON registry.vendors(status) WHERE status = 'active';
        CREATE INDEX idx_vendors_verified ON registry.vendors(verified_status);
        CREATE INDEX idx_vendors_phase_one ON registry.vendors(phase_one_use) WHERE phase_one_use = TRUE;
    """)

    op.execute("""
        CREATE TRIGGER vendors_updated_at
            BEFORE UPDATE ON registry.vendors
            FOR EACH ROW EXECUTE FUNCTION registry.set_updated_at();
    """)

    op.execute("""
        COMMENT ON TABLE registry.vendors IS
            'Data vendors (Tardis, Glassnode, CCXT, etc.). Separate from venues, though Binance is both vendor and venue. Endpoint config in endpoint_config; credentials in secrets manager via credential_secret_name.';
    """)

    # ===== registry.symbol_translations =====
    # vendor_id references registry.vendors (NOT venues, per reviewer 2026-05-03)
    op.execute("""
        CREATE TABLE registry.symbol_translations (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            vendor_id BIGINT NOT NULL REFERENCES registry.vendors(id),
            vendor_symbol TEXT NOT NULL,
            canonical_instrument_id BIGINT NOT NULL REFERENCES registry.instruments(id),
            effective_from TIMESTAMPTZ NOT NULL,
            effective_to TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (effective_to IS NULL OR effective_to > effective_from)
        );
    """)

    # Exclusion constraint: same vendor_id + vendor_symbol cannot have overlapping ranges
    op.execute("""
        ALTER TABLE registry.symbol_translations
        ADD CONSTRAINT no_overlapping_symbol_translations
        EXCLUDE USING gist (
            vendor_id WITH =,
            vendor_symbol WITH =,
            tstzrange(effective_from, COALESCE(effective_to, 'infinity'::timestamptz), '[)') WITH &&
        );
    """)

    op.execute("""
        CREATE INDEX idx_symbol_translations_lookup
            ON registry.symbol_translations(vendor_id, vendor_symbol, effective_from DESC);
        CREATE INDEX idx_symbol_translations_instrument
            ON registry.symbol_translations(canonical_instrument_id);
    """)

    op.execute("""
        COMMENT ON TABLE registry.symbol_translations IS
            'Per-vendor symbol to canonical instrument mapping. vendor_id references registry.vendors. Effective ranges cannot overlap (enforced by exclusion constraint).';
    """)

    # ===== registry.instrument_specs_history =====
    op.execute("""
        CREATE TABLE registry.instrument_specs_history (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            instrument_id BIGINT NOT NULL REFERENCES registry.instruments(id),
            tick_size NUMERIC(38,18),
            lot_size NUMERIC(38,18),
            min_notional NUMERIC(38,18),
            contract_size NUMERIC(38,18),
            price_precision INTEGER,
            quantity_precision INTEGER,
            margin_mode TEXT CHECK (margin_mode IN ('none', 'spot', 'isolated', 'cross', 'portfolio')),
            effective_from TIMESTAMPTZ NOT NULL,
            effective_to TIMESTAMPTZ,
            source TEXT NOT NULL,
            source_record_hash TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (effective_to IS NULL OR effective_to > effective_from),
            CHECK (price_precision IS NULL OR price_precision BETWEEN 0 AND 30),
            CHECK (quantity_precision IS NULL OR quantity_precision BETWEEN 0 AND 30),
            CHECK (tick_size IS NULL OR tick_size > 0),
            CHECK (lot_size IS NULL OR lot_size > 0),
            CHECK (min_notional IS NULL OR min_notional >= 0),
            CHECK (contract_size IS NULL OR contract_size > 0)
        );
    """)

    op.execute("""
        ALTER TABLE registry.instrument_specs_history
        ADD CONSTRAINT no_overlapping_instrument_specs
        EXCLUDE USING gist (
            instrument_id WITH =,
            tstzrange(effective_from, COALESCE(effective_to, 'infinity'::timestamptz), '[)') WITH &&
        );
    """)

    op.execute("""
        CREATE INDEX idx_instrument_specs_lookup
            ON registry.instrument_specs_history(instrument_id, effective_from DESC);
    """)

    op.execute("""
        COMMENT ON TABLE registry.instrument_specs_history IS
            'Effective-dated instrument specifications. Cost model and validation queries use effective_from <= T < effective_to to get spec at historical timestamp T. Overlapping ranges prevented by exclusion constraint.';
    """)

    # ===== registry.fee_schedules =====
    # Includes instrument_id (nullable) for symbol-specific fees per reviewer
    # Maker fee can be negative (rebates exist); range check -1000 to 1000 bps
    op.execute("""
        CREATE TABLE registry.fee_schedules (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            venue_id BIGINT NOT NULL REFERENCES registry.venues(id),
            account_id BIGINT REFERENCES registry.accounts(id),
            instrument_id BIGINT REFERENCES registry.instruments(id),
            instrument_type TEXT,
            maker_fee_bps NUMERIC(20,12),
            taker_fee_bps NUMERIC(20,12),
            effective_from TIMESTAMPTZ NOT NULL,
            effective_to TIMESTAMPTZ,
            source TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (effective_to IS NULL OR effective_to > effective_from),
            CHECK (instrument_type IS NULL OR instrument_type IN (
                'spot', 'perp', 'future', 'option', 'vault_share',
                'lending_position', 'cash', 'synthetic'
            )),
            CHECK (maker_fee_bps IS NULL OR maker_fee_bps BETWEEN -1000 AND 1000),
            CHECK (taker_fee_bps IS NULL OR taker_fee_bps BETWEEN -1000 AND 1000)
        );
    """)

    # Exclusion constraint per (venue, account, instrument, instrument_type) tuple
    # Use COALESCE to treat NULLs as a sentinel value so exclusion can match them
    op.execute("""
        ALTER TABLE registry.fee_schedules
        ADD CONSTRAINT no_overlapping_fee_schedules
        EXCLUDE USING gist (
            venue_id WITH =,
            COALESCE(account_id, -1) WITH =,
            COALESCE(instrument_id, -1) WITH =,
            COALESCE(instrument_type, '__none__') WITH =,
            tstzrange(effective_from, COALESCE(effective_to, 'infinity'::timestamptz), '[)') WITH &&
        );
    """)

    op.execute("""
        CREATE INDEX idx_fee_schedules_lookup
            ON registry.fee_schedules(venue_id, COALESCE(account_id, 0), COALESCE(instrument_id, 0), effective_from DESC);
        CREATE INDEX idx_fee_schedules_active
            ON registry.fee_schedules(venue_id, effective_from DESC) WHERE effective_to IS NULL;
    """)

    op.execute("""
        COMMENT ON TABLE registry.fee_schedules IS
            'Effective-dated fee rates with 5-level precedence (account+instrument > account+instrument_type > venue+instrument > venue+instrument_type > venue default). Maker fee can be negative (rebates).';
    """)

    # ===== registry.asset_clusters =====
    op.execute("""
        CREATE TABLE registry.asset_clusters (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            cluster_code TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            description TEXT,
            risk_weight NUMERIC(10,6) NOT NULL DEFAULT 1.0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (risk_weight >= 0)
        );
    """)

    op.execute("""
        CREATE INDEX idx_asset_clusters_code ON registry.asset_clusters(cluster_code);
    """)

    op.execute("""
        COMMENT ON TABLE registry.asset_clusters IS
            'Cluster definitions: layer_1, defi, gaming, ai, memecoins, etc. Per risk_policy v1.1 cluster exposure limits.';
    """)

    op.execute("""
        CREATE TRIGGER asset_clusters_updated_at
            BEFORE UPDATE ON registry.asset_clusters
            FOR EACH ROW EXECUTE FUNCTION registry.set_updated_at();
    """)

    # ===== registry.asset_cluster_memberships =====
    # Asset-level (not instrument-level) per reviewer 2026-05-03
    # BTC spot, BTC perp, BTC future all inherit cluster from BTC asset
    op.execute("""
        CREATE TABLE registry.asset_cluster_memberships (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            asset_id BIGINT NOT NULL REFERENCES registry.assets(id),
            cluster_id BIGINT NOT NULL REFERENCES registry.asset_clusters(id),
            effective_from TIMESTAMPTZ NOT NULL,
            effective_to TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (effective_to IS NULL OR effective_to > effective_from)
        );
    """)

    # Exclusion constraint: each asset has at most one membership per time range
    op.execute("""
        ALTER TABLE registry.asset_cluster_memberships
        ADD CONSTRAINT no_overlapping_cluster_memberships
        EXCLUDE USING gist (
            asset_id WITH =,
            tstzrange(effective_from, COALESCE(effective_to, 'infinity'::timestamptz), '[)') WITH &&
        );
    """)

    op.execute("""
        CREATE INDEX idx_cluster_membership_lookup
            ON registry.asset_cluster_memberships(asset_id, effective_from DESC);
        CREATE INDEX idx_cluster_membership_cluster
            ON registry.asset_cluster_memberships(cluster_id) WHERE effective_to IS NULL;
    """)

    op.execute("""
        COMMENT ON TABLE registry.asset_cluster_memberships IS
            'Asset-to-cluster membership. Each asset has at most one active membership; instruments inherit cluster from base_asset_id. Cluster exposure queries: SUM positions WHERE base_asset.cluster_id = X.';
    """)

    # ===== registry.venue_capabilities =====
    # Effective-dated per reviewer (capabilities change over time)
    op.execute("""
        CREATE TABLE registry.venue_capabilities (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            venue_id BIGINT NOT NULL REFERENCES registry.venues(id),
            max_client_order_id_len INTEGER NOT NULL,
            supports_post_only BOOLEAN NOT NULL DEFAULT FALSE,
            supports_reduce_only BOOLEAN NOT NULL DEFAULT FALSE,
            supports_gtc BOOLEAN NOT NULL DEFAULT TRUE,
            supports_ioc BOOLEAN NOT NULL DEFAULT TRUE,
            supports_fok BOOLEAN NOT NULL DEFAULT FALSE,
            supports_gtd BOOLEAN NOT NULL DEFAULT FALSE,
            supports_batch_orders BOOLEAN NOT NULL DEFAULT FALSE,
            supports_order_amend BOOLEAN NOT NULL DEFAULT FALSE,
            supports_client_order_id_lookup BOOLEAN NOT NULL DEFAULT TRUE,
            min_notional_usd NUMERIC(38,12),
            max_orders_per_second INTEGER,
            self_trade_prevention TEXT CHECK (self_trade_prevention IN (
                'none', 'cancel_taker', 'cancel_maker', 'cancel_both', 'reduce_quantity'
            )),
            config JSONB NOT NULL DEFAULT '{}'::jsonb,
            effective_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            effective_to TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (max_client_order_id_len > 0 AND max_client_order_id_len <= 128),
            CHECK (min_notional_usd IS NULL OR min_notional_usd >= 0),
            CHECK (max_orders_per_second IS NULL OR max_orders_per_second > 0),
            CHECK (effective_to IS NULL OR effective_to > effective_from)
        );
    """)

    op.execute("""
        ALTER TABLE registry.venue_capabilities
        ADD CONSTRAINT no_overlapping_venue_capabilities
        EXCLUDE USING gist (
            venue_id WITH =,
            tstzrange(effective_from, COALESCE(effective_to, 'infinity'::timestamptz), '[)') WITH &&
        );
    """)

    op.execute("""
        CREATE TRIGGER venue_capabilities_updated_at
            BEFORE UPDATE ON registry.venue_capabilities
            FOR EACH ROW EXECUTE FUNCTION registry.set_updated_at();
    """)

    op.execute("""
        COMMENT ON TABLE registry.venue_capabilities IS
            'Effective-dated venue feature support. OMS pre-submit checks query the active row for the venue at decision time. History preserves capability changes (post_only added, GTD support upgraded, etc.).';
    """)

    # ===== Verification block =====
    op.execute("""
        DO $$
        DECLARE
            expected_tables TEXT[] := ARRAY[
                'vendors', 'symbol_translations', 'instrument_specs_history', 'fee_schedules',
                'asset_clusters', 'asset_cluster_memberships', 'venue_capabilities'
            ];
            actual_count INT;
            t TEXT;
        BEGIN
            FOREACH t IN ARRAY expected_tables LOOP
                SELECT COUNT(*) INTO actual_count
                FROM information_schema.tables
                WHERE table_schema = 'registry' AND table_name = t;

                IF actual_count != 1 THEN
                    RAISE EXCEPTION 'registry.% not created', t;
                END IF;
            END LOOP;

            RAISE NOTICE 'All 7 registry market structure tables verified';
        END;
        $$;
    """)


def downgrade() -> None:
    # Drop in reverse dependency order, no CASCADE (per reviewer 2026-05-03)
    # If a later migration has dependencies, the drop will fail loudly rather than silently cascade
    op.execute("DROP TABLE IF EXISTS registry.venue_capabilities;")
    op.execute("DROP TABLE IF EXISTS registry.asset_cluster_memberships;")
    op.execute("DROP TABLE IF EXISTS registry.asset_clusters;")
    op.execute("DROP TABLE IF EXISTS registry.fee_schedules;")
    op.execute("DROP TABLE IF EXISTS registry.instrument_specs_history;")
    op.execute("DROP TABLE IF EXISTS registry.symbol_translations;")
    op.execute("DROP TABLE IF EXISTS registry.vendors;")
