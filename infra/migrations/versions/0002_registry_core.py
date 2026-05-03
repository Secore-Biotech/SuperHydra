"""registry_core

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-03

Creates the six core registry tables: venues, accounts, assets, instruments,
portfolios, strategies. These are the foundational entities referenced by
all subsequent migrations.

Per ledger schema v0.3 (with v0.2 review additions and data ingestion v0.2
extensions). Cross-schema FKs are created in 0016_constraints_and_triggers.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ===== registry.venues =====
    # Per data ingestion v0.2: vendor endpoint metadata in registry, credentials in secrets manager
    op.execute("""
        CREATE TABLE registry.venues (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            venue_code TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            venue_type TEXT NOT NULL CHECK (venue_type IN (
                'cex_spot', 'cex_futures', 'cex_options',
                'dex', 'lending_protocol', 'custodian',
                'vault', 'paper', 'bank'
            )),
            status TEXT NOT NULL CHECK (status IN ('active', 'paused', 'sunset')),
            config JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    op.execute("""
        CREATE INDEX idx_venues_status ON registry.venues(status)
            WHERE status = 'active';
    """)

    op.execute("COMMENT ON TABLE registry.venues IS 'Trading venues, custodians, paper venue. Endpoint metadata in config; credentials in secrets manager via credential_secret_name.';")

    # ===== registry.assets =====
    # Created before instruments because instruments reference assets
    op.execute("""
        CREATE TABLE registry.assets (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            symbol TEXT NOT NULL,
            display_name TEXT NOT NULL,
            asset_type TEXT NOT NULL CHECK (asset_type IN (
                'crypto', 'stablecoin', 'fiat', 'vault_share', 'tokenized_tbill', 'lp_token'
            )),
            decimals INTEGER NOT NULL CHECK (decimals BETWEEN 0 AND 30),
            chain TEXT,
            contract_address TEXT,
            status TEXT NOT NULL CHECK (status IN ('active', 'paused', 'delisted')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE NULLS NOT DISTINCT (symbol, chain, contract_address)
        );
    """)

    op.execute("""
        CREATE INDEX idx_assets_symbol ON registry.assets(symbol);
        CREATE INDEX idx_assets_status ON registry.assets(status) WHERE status = 'active';
    """)

    op.execute("COMMENT ON TABLE registry.assets IS 'Canonical asset registry. (symbol, chain, contract_address) uniquely identifies an asset; UNIQUE NULLS NOT DISTINCT means BTC with chain=NULL is unique.';")

    # ===== registry.instruments =====
    # Tradeable instruments. Each instrument lives on one venue and references base/quote assets.
    op.execute("""
        CREATE TABLE registry.instruments (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            instrument_code TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            venue_id BIGINT NOT NULL REFERENCES registry.venues(id),
            base_asset_id BIGINT REFERENCES registry.assets(id),
            quote_asset_id BIGINT REFERENCES registry.assets(id),
            instrument_type TEXT NOT NULL CHECK (instrument_type IN (
                'spot', 'perp', 'future', 'option', 'vault_share',
                'lending_position', 'cash', 'synthetic'
            )),
            expiry TIMESTAMPTZ,
            strike NUMERIC(38,18),
            option_type TEXT CHECK (option_type IN ('call', 'put')),
            contract_size NUMERIC(38,18),
            tick_size NUMERIC(38,18),
            lot_size NUMERIC(38,18),
            status TEXT NOT NULL CHECK (status IN ('active', 'paused', 'expired', 'delisted')),
            config JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (
                (instrument_type = 'option' AND expiry IS NOT NULL AND strike IS NOT NULL AND option_type IS NOT NULL)
                OR (instrument_type IN ('future', 'vault_share') AND expiry IS NOT NULL)
                OR (instrument_type IN ('spot', 'perp', 'lending_position', 'cash', 'synthetic'))
            )
        );
    """)

    op.execute("""
        CREATE INDEX idx_instruments_venue ON registry.instruments(venue_id);
        CREATE INDEX idx_instruments_active ON registry.instruments(status) WHERE status = 'active';
        CREATE INDEX idx_instruments_base_asset ON registry.instruments(base_asset_id) WHERE base_asset_id IS NOT NULL;
    """)

    op.execute("COMMENT ON TABLE registry.instruments IS 'Tradeable instruments. instrument_code is canonical, e.g. BTCUSDT-PERP-BINANCE.';")

    # ===== registry.accounts =====
    # Created after venues. Self-referential FK on parent_account_id.
    op.execute("""
        CREATE TABLE registry.accounts (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            venue_id BIGINT NOT NULL REFERENCES registry.venues(id),
            account_code TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            account_type TEXT NOT NULL CHECK (account_type IN (
                'trading', 'custody', 'margin', 'vault', 'paper', 'bank', 'subaccount'
            )),
            parent_account_id BIGINT REFERENCES registry.accounts(id),
            base_currency TEXT NOT NULL DEFAULT 'USD',
            status TEXT NOT NULL CHECK (status IN ('active', 'paused', 'closed')),
            config JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    op.execute("""
        CREATE INDEX idx_accounts_venue ON registry.accounts(venue_id);
        CREATE INDEX idx_accounts_parent ON registry.accounts(parent_account_id) WHERE parent_account_id IS NOT NULL;
        CREATE INDEX idx_accounts_status ON registry.accounts(status) WHERE status = 'active';
    """)

    op.execute("COMMENT ON TABLE registry.accounts IS 'Per-venue account identity. Subaccounts reference master via parent_account_id.';")

    # ===== registry.portfolios =====
    op.execute("""
        CREATE TABLE registry.portfolios (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            portfolio_code TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            product_type TEXT NOT NULL CHECK (product_type IN (
                'internal', 'market_neutral_fund', 'long_flat_certificate',
                'ebtc_vault', 'paper'
            )),
            base_currency TEXT NOT NULL DEFAULT 'USD',
            status TEXT NOT NULL CHECK (status IN (
                'research', 'shadow', 'canary', 'live', 'paused', 'sunset'
            )),
            config JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    op.execute("""
        CREATE INDEX idx_portfolios_status ON registry.portfolios(status);
        CREATE INDEX idx_portfolios_product_type ON registry.portfolios(product_type);
    """)

    op.execute("COMMENT ON TABLE registry.portfolios IS 'Product-level portfolios: market-neutral fund, long-flat product, EBTC vault, paper. Each has independent NAV.';")

    # ===== registry.strategies =====
    op.execute("""
        CREATE TABLE registry.strategies (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            description TEXT,
            current_phase TEXT NOT NULL CHECK (current_phase IN (
                'research', 'shadow', 'canary', 'scale', 'paused', 'sunset'
            )),
            phase_entered_at TIMESTAMPTZ NOT NULL,
            hypothesis_doc_path TEXT NOT NULL,
            ev_check_passed BOOLEAN NOT NULL DEFAULT FALSE,
            ev_check_value NUMERIC(20,12),
            ev_check_at TIMESTAMPTZ,
            config JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    op.execute("""
        CREATE INDEX idx_strategies_phase ON registry.strategies(current_phase);
        CREATE INDEX idx_strategies_ev_passed ON registry.strategies(ev_check_passed)
            WHERE ev_check_passed = TRUE;
    """)

    op.execute("COMMENT ON TABLE registry.strategies IS 'Strategy registry. ev_check_passed gates research-phase admission per measurement_policy v1.1.';")

    # ===== updated_at trigger function =====
    # Generic trigger to maintain updated_at. Used by all six tables in this migration.
    op.execute("""
        CREATE OR REPLACE FUNCTION registry.set_updated_at() RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Apply trigger to all six tables
    for table in ["venues", "assets", "instruments", "accounts", "portfolios", "strategies"]:
        op.execute(f"""
            CREATE TRIGGER {table}_updated_at
                BEFORE UPDATE ON registry.{table}
                FOR EACH ROW
                EXECUTE FUNCTION registry.set_updated_at();
        """)

    # ===== Verification block =====
    op.execute("""
        DO $$
        DECLARE
            expected_tables TEXT[] := ARRAY['venues', 'assets', 'instruments', 'accounts', 'portfolios', 'strategies'];
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

            RAISE NOTICE 'All 6 registry core tables verified';
        END;
        $$;
    """)


def downgrade() -> None:
    # Drop in reverse dependency order
    op.execute("DROP TABLE IF EXISTS registry.strategies CASCADE;")
    op.execute("DROP TABLE IF EXISTS registry.portfolios CASCADE;")
    op.execute("DROP TABLE IF EXISTS registry.accounts CASCADE;")
    op.execute("DROP TABLE IF EXISTS registry.instruments CASCADE;")
    op.execute("DROP TABLE IF EXISTS registry.assets CASCADE;")
    op.execute("DROP TABLE IF EXISTS registry.venues CASCADE;")
    op.execute("DROP FUNCTION IF EXISTS registry.set_updated_at() CASCADE;")
