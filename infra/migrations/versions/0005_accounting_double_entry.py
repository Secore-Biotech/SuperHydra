"""accounting_double_entry

Revision ID: 0005
Revises: 0004b
Create Date: 2026-05-03

Creates accounting double-entry primitives (v7).

Foundational principle:
  A posted journal is immutable, balanced, and dimensionally coherent.
  A void is only a posted reversal linked to the original; both remain
  in posted-ledger queries.

v7 design: a single combined trigger on ledger_entries acquires all
required locks in deterministic order:
  1. Journal rows, ascending id (FOR UPDATE)
  2. Ledger account rows, ascending id (FOR UPDATE)
After locks are held, the trigger checks journal posted-status and entry
dimension consistency. This eliminates the cross-trigger deadlock that
would arise from separate immutability and dimension triggers.

Approved by external reviewer on 2026-05-03 (round 7).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ===== accounting.ledger_accounts =====
    op.execute("""
        CREATE TABLE accounting.ledger_accounts (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            account_code TEXT NOT NULL UNIQUE,
            account_name TEXT NOT NULL,
            account_type TEXT NOT NULL CHECK (account_type IN (
                'asset', 'liability', 'equity', 'income', 'expense'
            )),
            account_subtype TEXT NOT NULL,
            portfolio_id BIGINT REFERENCES registry.portfolios(id),
            strategy_id BIGINT REFERENCES registry.strategies(id),
            registry_account_id BIGINT REFERENCES registry.accounts(id),
            asset_id BIGINT REFERENCES registry.assets(id),
            instrument_id BIGINT REFERENCES registry.instruments(id),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (LENGTH(TRIM(account_code)) > 0),
            CHECK (LENGTH(TRIM(account_name)) > 0),
            CHECK (
                (account_type = 'asset' AND account_subtype IN (
                    'cash', 'position', 'receivable', 'margin_collateral', 'vault_share'
                ))
                OR (account_type = 'liability' AND account_subtype IN (
                    'payable', 'debt'
                ))
                OR (account_type = 'equity' AND account_subtype IN (
                    'capital_contributed', 'capital_distributed',
                    'realized_pnl', 'unrealized_pnl', 'fx_pnl'
                ))
                OR (account_type = 'income' AND account_subtype IN (
                    'funding_income', 'rebate_income', 'interest_income', 'other_income'
                ))
                OR (account_type = 'expense' AND account_subtype IN (
                    'fee_expense', 'funding_expense', 'borrow_expense',
                    'interest_expense', 'gas_expense', 'other_expense',
                    'management_fee', 'performance_fee', 'adjustment'
                ))
            )
        );
    """)

    op.execute("""
        CREATE INDEX idx_ledger_accounts_portfolio
            ON accounting.ledger_accounts(portfolio_id) WHERE portfolio_id IS NOT NULL;
        CREATE INDEX idx_ledger_accounts_strategy
            ON accounting.ledger_accounts(strategy_id) WHERE strategy_id IS NOT NULL;
        CREATE INDEX idx_ledger_accounts_registry_account
            ON accounting.ledger_accounts(registry_account_id) WHERE registry_account_id IS NOT NULL;
        CREATE INDEX idx_ledger_accounts_asset
            ON accounting.ledger_accounts(asset_id) WHERE asset_id IS NOT NULL;
        CREATE INDEX idx_ledger_accounts_instrument
            ON accounting.ledger_accounts(instrument_id) WHERE instrument_id IS NOT NULL;
        CREATE INDEX idx_ledger_accounts_active
            ON accounting.ledger_accounts(is_active) WHERE is_active = TRUE;
    """)

    op.execute("""
        CREATE TRIGGER ledger_accounts_updated_at
            BEFORE UPDATE ON accounting.ledger_accounts
            FOR EACH ROW EXECUTE FUNCTION registry.set_updated_at();
    """)

    # ===== accounting.journals =====
    op.execute("""
        CREATE TABLE accounting.journals (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            journal_uuid UUID NOT NULL DEFAULT gen_uuidv7() UNIQUE,
            journal_type TEXT NOT NULL CHECK (journal_type IN (
                'trade', 'fee', 'funding', 'cashflow', 'transfer',
                'mtm', 'adjustment', 'reversal'
            )),
            status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'posted')),
            portfolio_id BIGINT NOT NULL REFERENCES registry.portfolios(id),
            strategy_id BIGINT REFERENCES registry.strategies(id),
            journal_at TIMESTAMPTZ NOT NULL,
            source_type TEXT NOT NULL CHECK (source_type IN (
                'fill', 'cashflow', 'fee_event', 'funding_event', 'borrow_event',
                'rebate_event', 'mark_event', 'transfer_event',
                'manual_adjustment', 'reversal', 'system',
                'vault_event', 'defi_event', 'settlement_event'
            )),
            source_namespace TEXT NOT NULL DEFAULT 'global',
            source_id TEXT,
            source_hash TEXT,
            description TEXT,
            created_by TEXT NOT NULL,
            posted_by TEXT,
            voided_by TEXT,
            voids_journal_id BIGINT REFERENCES accounting.journals(id),
            voided_by_journal_id BIGINT REFERENCES accounting.journals(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            posted_at TIMESTAMPTZ,
            voided_at TIMESTAMPTZ,
            CHECK (
                (status = 'draft' AND posted_at IS NULL AND posted_by IS NULL)
                OR (status = 'posted' AND posted_at IS NOT NULL AND posted_by IS NOT NULL)
            ),
            CHECK (
                (voided_at IS NULL AND voided_by IS NULL AND voided_by_journal_id IS NULL)
                OR
                (voided_at IS NOT NULL AND voided_by IS NOT NULL AND voided_by_journal_id IS NOT NULL)
            ),
            CHECK (voided_at IS NULL OR status = 'posted'),
            CHECK (
                (journal_type = 'reversal' AND voids_journal_id IS NOT NULL)
                OR (journal_type != 'reversal' AND voids_journal_id IS NULL)
            ),
            CHECK (voids_journal_id IS NULL OR voids_journal_id <> id),
            CHECK (voided_by_journal_id IS NULL OR voided_by_journal_id <> id),
            CHECK (source_id IS NOT NULL OR source_type = 'system'),
            CHECK (LENGTH(TRIM(source_namespace)) > 0),
            CHECK (source_id IS NULL OR LENGTH(TRIM(source_id)) > 0),
            CHECK (LENGTH(TRIM(created_by)) > 0),
            CHECK (posted_by IS NULL OR LENGTH(TRIM(posted_by)) > 0),
            CHECK (voided_by IS NULL OR LENGTH(TRIM(voided_by)) > 0)
        );
    """)

    op.execute("""
        CREATE UNIQUE INDEX uniq_journal_source
            ON accounting.journals(source_type, source_namespace, source_id, journal_type)
            WHERE source_id IS NOT NULL;
        CREATE INDEX idx_journals_portfolio_journal_at
            ON accounting.journals(portfolio_id, journal_at DESC);
        CREATE INDEX idx_journals_strategy_journal_at
            ON accounting.journals(strategy_id, journal_at DESC) WHERE strategy_id IS NOT NULL;
        CREATE INDEX idx_journals_status_posted
            ON accounting.journals(status, journal_at DESC) WHERE status = 'posted';
        CREATE INDEX idx_journals_voided
            ON accounting.journals(voided_at DESC) WHERE voided_at IS NOT NULL;
        CREATE INDEX idx_journals_voids
            ON accounting.journals(voids_journal_id) WHERE voids_journal_id IS NOT NULL;
        CREATE INDEX idx_journals_voided_by
            ON accounting.journals(voided_by_journal_id) WHERE voided_by_journal_id IS NOT NULL;
    """)

    # ===== accounting.ledger_entries =====
    op.execute("""
        CREATE TABLE accounting.ledger_entries (
            id UUID NOT NULL DEFAULT gen_uuidv7() PRIMARY KEY,
            journal_id BIGINT NOT NULL REFERENCES accounting.journals(id),
            ledger_account_id BIGINT NOT NULL REFERENCES accounting.ledger_accounts(id),
            debit_credit TEXT NOT NULL CHECK (debit_credit IN ('debit', 'credit')),
            asset_id BIGINT NOT NULL REFERENCES registry.assets(id),
            instrument_id BIGINT REFERENCES registry.instruments(id),
            quantity NUMERIC(38,18),
            amount_usd NUMERIC(38,12) NOT NULL,
            memo TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (amount_usd > 0),
            CHECK (quantity IS NULL OR quantity > 0)
        );
    """)

    op.execute("""
        CREATE INDEX idx_ledger_entries_journal
            ON accounting.ledger_entries(journal_id);
        CREATE INDEX idx_ledger_entries_ledger_account
            ON accounting.ledger_entries(ledger_account_id, created_at DESC);
        CREATE INDEX idx_ledger_entries_asset
            ON accounting.ledger_entries(asset_id);
        CREATE INDEX idx_ledger_entries_instrument
            ON accounting.ledger_entries(instrument_id) WHERE instrument_id IS NOT NULL;
    """)

    # ===== Journal status-transition trigger =====
    op.execute("""
        CREATE OR REPLACE FUNCTION accounting.enforce_journal_status_transitions()
        RETURNS TRIGGER AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.status != 'draft' THEN
                    RAISE EXCEPTION
                        'Journals must be inserted as draft; use accounting.post_journal() to post';
                END IF;
                IF NEW.journal_type = 'reversal'
                   AND current_setting('superhydra.allow_journal_void', true) IS DISTINCT FROM 'on'
                THEN
                    RAISE EXCEPTION
                        'Direct reversal journal creation is forbidden; use accounting.void_journal()';
                END IF;
                RETURN NEW;
            END IF;

            IF OLD.status = 'draft' AND NEW.status = 'draft' THEN
                IF OLD.journal_type != 'reversal'
                   AND NEW.journal_type = 'reversal'
                   AND current_setting('superhydra.allow_journal_void', true) IS DISTINCT FROM 'on'
                THEN
                    RAISE EXCEPTION
                        'Direct conversion to reversal journal is forbidden; use accounting.void_journal()';
                END IF;
                RETURN NEW;
            END IF;

            IF OLD.status = 'draft' AND NEW.status = 'posted' THEN
                IF current_setting('superhydra.allow_journal_post', true) IS DISTINCT FROM 'on' THEN
                    RAISE EXCEPTION
                        'Direct status transition to posted is forbidden; use accounting.post_journal()';
                END IF;
                RETURN NEW;
            END IF;

            IF OLD.status = 'posted' AND NEW.status = 'posted' THEN
                RETURN NEW;
            END IF;

            RAISE EXCEPTION 'Invalid journal status transition: % -> %', OLD.status, NEW.status;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER journals_status_transitions_insert
            BEFORE INSERT ON accounting.journals
            FOR EACH ROW EXECUTE FUNCTION accounting.enforce_journal_status_transitions();
        CREATE TRIGGER journals_status_transitions_update
            BEFORE UPDATE ON accounting.journals
            FOR EACH ROW EXECUTE FUNCTION accounting.enforce_journal_status_transitions();
    """)

    # ===== Posted-journal core immutability =====
    op.execute("""
        CREATE OR REPLACE FUNCTION accounting.enforce_posted_journal_core_immutability()
        RETURNS TRIGGER AS $$
        DECLARE
            v_void_metadata_changed BOOLEAN;
            v_void_flag TEXT;
            v_reversal_valid BOOLEAN;
        BEGIN
            IF OLD.status != 'posted' THEN
                RETURN NEW;
            END IF;

            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.journal_uuid IS DISTINCT FROM OLD.journal_uuid
               OR NEW.journal_type IS DISTINCT FROM OLD.journal_type
               OR NEW.portfolio_id IS DISTINCT FROM OLD.portfolio_id
               OR NEW.strategy_id IS DISTINCT FROM OLD.strategy_id
               OR NEW.journal_at IS DISTINCT FROM OLD.journal_at
               OR NEW.source_type IS DISTINCT FROM OLD.source_type
               OR NEW.source_namespace IS DISTINCT FROM OLD.source_namespace
               OR NEW.source_id IS DISTINCT FROM OLD.source_id
               OR NEW.source_hash IS DISTINCT FROM OLD.source_hash
               OR NEW.description IS DISTINCT FROM OLD.description
               OR NEW.created_by IS DISTINCT FROM OLD.created_by
               OR NEW.posted_by IS DISTINCT FROM OLD.posted_by
               OR NEW.posted_at IS DISTINCT FROM OLD.posted_at
               OR NEW.voids_journal_id IS DISTINCT FROM OLD.voids_journal_id
               OR NEW.created_at IS DISTINCT FROM OLD.created_at
            THEN
                RAISE EXCEPTION 'Posted journal % core fields are immutable', OLD.id;
            END IF;

            v_void_metadata_changed := (
                NEW.voided_at IS DISTINCT FROM OLD.voided_at
                OR NEW.voided_by IS DISTINCT FROM OLD.voided_by
                OR NEW.voided_by_journal_id IS DISTINCT FROM OLD.voided_by_journal_id
            );

            IF v_void_metadata_changed THEN
                v_void_flag := current_setting('superhydra.allow_journal_void', true);
                IF v_void_flag IS DISTINCT FROM 'on' THEN
                    RAISE EXCEPTION
                        'Direct modification of void metadata on journal % is forbidden; use accounting.void_journal()',
                        OLD.id;
                END IF;
                IF OLD.voided_at IS NOT NULL THEN
                    RAISE EXCEPTION
                        'Journal % is already voided; void metadata is immutable', OLD.id;
                END IF;
                IF NEW.voided_by_journal_id IS NOT NULL THEN
                    SELECT EXISTS (
                        SELECT 1 FROM accounting.journals r
                        WHERE r.id = NEW.voided_by_journal_id
                          AND r.status = 'posted'
                          AND r.journal_type = 'reversal'
                          AND r.voids_journal_id = OLD.id
                    ) INTO v_reversal_valid;
                    IF NOT v_reversal_valid THEN
                        RAISE EXCEPTION
                            'voided_by_journal_id % must reference a posted reversal journal whose voids_journal_id = %',
                            NEW.voided_by_journal_id, OLD.id;
                    END IF;
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER journals_core_immutability
            BEFORE UPDATE ON accounting.journals
            FOR EACH ROW EXECUTE FUNCTION accounting.enforce_posted_journal_core_immutability();
    """)

    # ===== Combined ledger-entry integrity trigger (v7) =====
    op.execute("""
        CREATE OR REPLACE FUNCTION accounting.enforce_ledger_entry_integrity()
        RETURNS TRIGGER AS $$
        DECLARE
            v_jrn_lower BIGINT;
            v_jrn_upper BIGINT;
            v_acct_lower BIGINT;
            v_acct_upper BIGINT;
            v_old_journal_status TEXT;
            v_new_journal_status TEXT;
            v_journal_portfolio_id BIGINT;
            v_journal_strategy_id BIGINT;
            v_account_portfolio_id BIGINT;
            v_account_strategy_id BIGINT;
            v_account_asset_id BIGINT;
            v_account_instrument_id BIGINT;
        BEGIN
            -- Phase 1: Lock journal rows in ascending id order
            IF TG_OP = 'INSERT' THEN
                SELECT status INTO v_new_journal_status
                FROM accounting.journals WHERE id = NEW.journal_id FOR UPDATE;
            ELSIF TG_OP = 'DELETE' THEN
                SELECT status INTO v_old_journal_status
                FROM accounting.journals WHERE id = OLD.journal_id FOR UPDATE;
            ELSE
                IF OLD.journal_id = NEW.journal_id THEN
                    SELECT status INTO v_old_journal_status
                    FROM accounting.journals WHERE id = OLD.journal_id FOR UPDATE;
                    v_new_journal_status := v_old_journal_status;
                ELSE
                    IF OLD.journal_id < NEW.journal_id THEN
                        v_jrn_lower := OLD.journal_id;
                        v_jrn_upper := NEW.journal_id;
                    ELSE
                        v_jrn_lower := NEW.journal_id;
                        v_jrn_upper := OLD.journal_id;
                    END IF;
                    PERFORM 1 FROM accounting.journals WHERE id = v_jrn_lower FOR UPDATE;
                    PERFORM 1 FROM accounting.journals WHERE id = v_jrn_upper FOR UPDATE;
                    SELECT status INTO v_old_journal_status
                    FROM accounting.journals WHERE id = OLD.journal_id;
                    SELECT status INTO v_new_journal_status
                    FROM accounting.journals WHERE id = NEW.journal_id;
                END IF;
            END IF;

            -- Phase 2: Reject if any involved journal is posted
            IF TG_OP = 'INSERT' THEN
                IF v_new_journal_status = 'posted' THEN
                    RAISE EXCEPTION
                        'INSERT on ledger_entries blocked: journal % is posted', NEW.journal_id;
                END IF;
            ELSIF TG_OP = 'DELETE' THEN
                IF v_old_journal_status = 'posted' THEN
                    RAISE EXCEPTION
                        'DELETE on ledger_entries blocked: journal % is posted', OLD.journal_id;
                END IF;
                RETURN OLD;
            ELSE
                IF v_old_journal_status = 'posted' THEN
                    RAISE EXCEPTION
                        'UPDATE on ledger_entries blocked: original journal % is posted', OLD.journal_id;
                END IF;
                IF OLD.journal_id IS DISTINCT FROM NEW.journal_id
                   AND v_new_journal_status = 'posted'
                THEN
                    RAISE EXCEPTION
                        'UPDATE on ledger_entries blocked: target journal % is posted', NEW.journal_id;
                END IF;
            END IF;

            -- Phase 3: Lock ledger account rows in ascending id order
            IF TG_OP = 'INSERT' THEN
                SELECT portfolio_id, strategy_id, asset_id, instrument_id
                INTO v_account_portfolio_id, v_account_strategy_id,
                     v_account_asset_id, v_account_instrument_id
                FROM accounting.ledger_accounts
                WHERE id = NEW.ledger_account_id FOR UPDATE;
            ELSIF TG_OP = 'UPDATE' THEN
                IF OLD.ledger_account_id = NEW.ledger_account_id THEN
                    SELECT portfolio_id, strategy_id, asset_id, instrument_id
                    INTO v_account_portfolio_id, v_account_strategy_id,
                         v_account_asset_id, v_account_instrument_id
                    FROM accounting.ledger_accounts
                    WHERE id = NEW.ledger_account_id FOR UPDATE;
                ELSE
                    IF OLD.ledger_account_id < NEW.ledger_account_id THEN
                        v_acct_lower := OLD.ledger_account_id;
                        v_acct_upper := NEW.ledger_account_id;
                    ELSE
                        v_acct_lower := NEW.ledger_account_id;
                        v_acct_upper := OLD.ledger_account_id;
                    END IF;
                    PERFORM 1 FROM accounting.ledger_accounts WHERE id = v_acct_lower FOR UPDATE;
                    PERFORM 1 FROM accounting.ledger_accounts WHERE id = v_acct_upper FOR UPDATE;
                    SELECT portfolio_id, strategy_id, asset_id, instrument_id
                    INTO v_account_portfolio_id, v_account_strategy_id,
                         v_account_asset_id, v_account_instrument_id
                    FROM accounting.ledger_accounts WHERE id = NEW.ledger_account_id;
                END IF;
            END IF;

            -- Phase 4: Validate dimensions (INSERT/UPDATE only)
            IF TG_OP IN ('INSERT', 'UPDATE') THEN
                SELECT portfolio_id, strategy_id
                INTO v_journal_portfolio_id, v_journal_strategy_id
                FROM accounting.journals WHERE id = NEW.journal_id;

                IF v_account_portfolio_id IS NOT NULL
                   AND v_account_portfolio_id IS DISTINCT FROM v_journal_portfolio_id
                THEN
                    RAISE EXCEPTION
                        'Ledger entry portfolio mismatch: account portfolio %, journal portfolio %',
                        v_account_portfolio_id, v_journal_portfolio_id;
                END IF;
                IF v_account_strategy_id IS NOT NULL
                   AND v_account_strategy_id IS DISTINCT FROM v_journal_strategy_id
                THEN
                    RAISE EXCEPTION
                        'Ledger entry strategy mismatch: account strategy %, journal strategy %',
                        v_account_strategy_id, v_journal_strategy_id;
                END IF;
                IF v_account_asset_id IS NOT NULL
                   AND v_account_asset_id IS DISTINCT FROM NEW.asset_id
                THEN
                    RAISE EXCEPTION
                        'Ledger entry asset mismatch: account asset %, entry asset %',
                        v_account_asset_id, NEW.asset_id;
                END IF;
                IF v_account_instrument_id IS NOT NULL
                   AND v_account_instrument_id IS DISTINCT FROM NEW.instrument_id
                THEN
                    RAISE EXCEPTION
                        'Ledger entry instrument mismatch: account instrument %, entry instrument %',
                        v_account_instrument_id, NEW.instrument_id;
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        COMMENT ON FUNCTION accounting.enforce_ledger_entry_integrity() IS
            'Combined integrity trigger for ledger_entries. Acquires journal row locks (ascending id) then ledger account row locks (ascending id), then enforces posted-journal immutability AND dimension consistency. Single-trigger design eliminates cross-trigger lock-order deadlocks.';
    """)

    op.execute("""
        CREATE TRIGGER ledger_entries_integrity_insert
            BEFORE INSERT ON accounting.ledger_entries
            FOR EACH ROW EXECUTE FUNCTION accounting.enforce_ledger_entry_integrity();
        CREATE TRIGGER ledger_entries_integrity_update
            BEFORE UPDATE ON accounting.ledger_entries
            FOR EACH ROW EXECUTE FUNCTION accounting.enforce_ledger_entry_integrity();
        CREATE TRIGGER ledger_entries_integrity_delete
            BEFORE DELETE ON accounting.ledger_entries
            FOR EACH ROW EXECUTE FUNCTION accounting.enforce_ledger_entry_integrity();
    """)

    # ===== Post-time dimension validator =====
    op.execute("""
        CREATE OR REPLACE FUNCTION accounting.validate_journal_entry_dimensions(
            p_journal_id BIGINT
        ) RETURNS VOID AS $$
        DECLARE
            v_bad_count INT;
            v_first_bad_entry_id UUID;
            v_first_bad_reason TEXT;
        BEGIN
            SELECT COUNT(*) INTO v_bad_count
            FROM accounting.ledger_entries e
            JOIN accounting.journals j ON j.id = e.journal_id
            JOIN accounting.ledger_accounts a ON a.id = e.ledger_account_id
            WHERE e.journal_id = p_journal_id
              AND (
                  (a.portfolio_id IS NOT NULL AND a.portfolio_id IS DISTINCT FROM j.portfolio_id)
                  OR (a.strategy_id IS NOT NULL AND a.strategy_id IS DISTINCT FROM j.strategy_id)
                  OR (a.asset_id IS NOT NULL AND a.asset_id IS DISTINCT FROM e.asset_id)
                  OR (a.instrument_id IS NOT NULL AND a.instrument_id IS DISTINCT FROM e.instrument_id)
              );

            IF v_bad_count > 0 THEN
                SELECT e.id,
                    CASE
                        WHEN a.portfolio_id IS NOT NULL AND a.portfolio_id IS DISTINCT FROM j.portfolio_id THEN
                            'portfolio mismatch (account ' || a.portfolio_id || ', journal ' || j.portfolio_id || ')'
                        WHEN a.strategy_id IS NOT NULL AND a.strategy_id IS DISTINCT FROM j.strategy_id THEN
                            'strategy mismatch (account ' || COALESCE(a.strategy_id::TEXT, 'NULL')
                            || ', journal ' || COALESCE(j.strategy_id::TEXT, 'NULL') || ')'
                        WHEN a.asset_id IS NOT NULL AND a.asset_id IS DISTINCT FROM e.asset_id THEN
                            'asset mismatch (account ' || a.asset_id || ', entry ' || e.asset_id || ')'
                        WHEN a.instrument_id IS NOT NULL AND a.instrument_id IS DISTINCT FROM e.instrument_id THEN
                            'instrument mismatch (account ' || a.instrument_id
                            || ', entry ' || COALESCE(e.instrument_id::TEXT, 'NULL') || ')'
                    END
                INTO v_first_bad_entry_id, v_first_bad_reason
                FROM accounting.ledger_entries e
                JOIN accounting.journals j ON j.id = e.journal_id
                JOIN accounting.ledger_accounts a ON a.id = e.ledger_account_id
                WHERE e.journal_id = p_journal_id
                  AND (
                      (a.portfolio_id IS NOT NULL AND a.portfolio_id IS DISTINCT FROM j.portfolio_id)
                      OR (a.strategy_id IS NOT NULL AND a.strategy_id IS DISTINCT FROM j.strategy_id)
                      OR (a.asset_id IS NOT NULL AND a.asset_id IS DISTINCT FROM e.asset_id)
                      OR (a.instrument_id IS NOT NULL AND a.instrument_id IS DISTINCT FROM e.instrument_id)
                  )
                LIMIT 1;

                RAISE EXCEPTION
                    'Journal % has % dimensionally inconsistent ledger entries (first: entry %, %)',
                    p_journal_id, v_bad_count, v_first_bad_entry_id, v_first_bad_reason;
            END IF;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # ===== Ledger account identity immutability =====
    op.execute("""
        CREATE OR REPLACE FUNCTION accounting.enforce_ledger_account_identity_immutability()
        RETURNS TRIGGER AS $$
        DECLARE
            v_used_in_any_entry BOOLEAN;
        BEGIN
            IF NEW.account_code IS NOT DISTINCT FROM OLD.account_code
               AND NEW.account_type IS NOT DISTINCT FROM OLD.account_type
               AND NEW.account_subtype IS NOT DISTINCT FROM OLD.account_subtype
               AND NEW.portfolio_id IS NOT DISTINCT FROM OLD.portfolio_id
               AND NEW.strategy_id IS NOT DISTINCT FROM OLD.strategy_id
               AND NEW.registry_account_id IS NOT DISTINCT FROM OLD.registry_account_id
               AND NEW.asset_id IS NOT DISTINCT FROM OLD.asset_id
               AND NEW.instrument_id IS NOT DISTINCT FROM OLD.instrument_id
            THEN
                RETURN NEW;
            END IF;

            SELECT EXISTS (
                SELECT 1 FROM accounting.ledger_entries WHERE ledger_account_id = OLD.id
            ) INTO v_used_in_any_entry;

            IF v_used_in_any_entry THEN
                RAISE EXCEPTION
                    'Ledger account % identity fields cannot change after use in any ledger entry',
                    OLD.id;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER ledger_accounts_identity_immutability
            BEFORE UPDATE ON accounting.ledger_accounts
            FOR EACH ROW EXECUTE FUNCTION accounting.enforce_ledger_account_identity_immutability();
    """)

    # ===== accounting.post_journal() =====
    op.execute("""
        CREATE OR REPLACE FUNCTION accounting.post_journal(
            p_journal_id BIGINT,
            p_posted_by TEXT
        ) RETURNS VOID AS $$
        DECLARE
            v_status TEXT;
            v_entry_count INT;
            v_debit_total NUMERIC(38,12);
            v_credit_total NUMERIC(38,12);
            v_imbalance NUMERIC(38,12);
        BEGIN
            SELECT status INTO v_status
            FROM accounting.journals WHERE id = p_journal_id FOR UPDATE;

            IF v_status IS NULL THEN
                RAISE EXCEPTION 'Journal % does not exist', p_journal_id;
            END IF;
            IF v_status != 'draft' THEN
                RAISE EXCEPTION 'Journal % is not in draft state (current: %)', p_journal_id, v_status;
            END IF;

            SELECT COUNT(*) INTO v_entry_count
            FROM accounting.ledger_entries WHERE journal_id = p_journal_id;

            IF v_entry_count < 2 THEN
                RAISE EXCEPTION 'Journal % has fewer than 2 entries (count: %)',
                    p_journal_id, v_entry_count;
            END IF;

            PERFORM accounting.validate_journal_entry_dimensions(p_journal_id);

            SELECT
                COALESCE(SUM(amount_usd) FILTER (WHERE debit_credit = 'debit'), 0),
                COALESCE(SUM(amount_usd) FILTER (WHERE debit_credit = 'credit'), 0)
            INTO v_debit_total, v_credit_total
            FROM accounting.ledger_entries WHERE journal_id = p_journal_id;

            v_imbalance := ABS(v_debit_total - v_credit_total);

            IF v_imbalance > 0 THEN
                RAISE EXCEPTION
                    'Journal % unbalanced: debits=%, credits=%, imbalance=%',
                    p_journal_id, v_debit_total, v_credit_total, v_imbalance;
            END IF;

            PERFORM set_config('superhydra.allow_journal_post', 'on', true);

            BEGIN
                UPDATE accounting.journals
                SET status = 'posted', posted_at = NOW(), posted_by = p_posted_by
                WHERE id = p_journal_id;
            EXCEPTION WHEN OTHERS THEN
                PERFORM set_config('superhydra.allow_journal_post', 'off', true);
                RAISE;
            END;

            PERFORM set_config('superhydra.allow_journal_post', 'off', true);
        END;
        $$ LANGUAGE plpgsql;
    """)

    # ===== accounting.void_journal() (v7: ORDER BY ledger_account_id, id added) =====
    op.execute("""
        CREATE OR REPLACE FUNCTION accounting.void_journal(
            p_original_journal_id BIGINT,
            p_voided_by TEXT,
            p_reason TEXT DEFAULT NULL
        ) RETURNS BIGINT AS $$
        DECLARE
            v_original_status TEXT;
            v_original_journal_type TEXT;
            v_already_voided_by BIGINT;
            v_original_portfolio_id BIGINT;
            v_original_strategy_id BIGINT;
            v_original_journal_at TIMESTAMPTZ;
            v_original_source_namespace TEXT;
            v_reversal_journal_id BIGINT;
            v_reversal_status TEXT;
            v_reversal_voids_id BIGINT;
            v_entry RECORD;
        BEGIN
            SELECT status, journal_type, voided_by_journal_id, portfolio_id, strategy_id,
                   journal_at, source_namespace
            INTO v_original_status, v_original_journal_type, v_already_voided_by,
                 v_original_portfolio_id, v_original_strategy_id, v_original_journal_at,
                 v_original_source_namespace
            FROM accounting.journals WHERE id = p_original_journal_id FOR UPDATE;

            IF v_original_status IS NULL THEN
                RAISE EXCEPTION 'Journal % does not exist', p_original_journal_id;
            END IF;
            IF v_original_status != 'posted' THEN
                RAISE EXCEPTION
                    'Cannot void journal % (status: %); only posted journals can be voided',
                    p_original_journal_id, v_original_status;
            END IF;
            IF v_already_voided_by IS NOT NULL THEN
                RAISE EXCEPTION
                    'Journal % is already voided by journal %',
                    p_original_journal_id, v_already_voided_by;
            END IF;
            IF v_original_journal_type = 'reversal' THEN
                RAISE EXCEPTION
                    'Cannot void a reversal journal in Phase 1 (journal %)', p_original_journal_id;
            END IF;

            PERFORM set_config('superhydra.allow_journal_void', 'on', true);

            BEGIN
                INSERT INTO accounting.journals (
                    journal_type, status, portfolio_id, strategy_id, journal_at,
                    source_type, source_namespace, source_id, description,
                    created_by, voids_journal_id
                ) VALUES (
                    'reversal', 'draft', v_original_portfolio_id, v_original_strategy_id,
                    v_original_journal_at,
                    'reversal', v_original_source_namespace, p_original_journal_id::TEXT,
                    COALESCE(p_reason, 'Reversal of journal ' || p_original_journal_id),
                    p_voided_by, p_original_journal_id
                ) RETURNING id INTO v_reversal_journal_id;

                -- v7: ORDER BY ledger_account_id, id for deterministic lock acquisition
                FOR v_entry IN
                    SELECT ledger_account_id, debit_credit, asset_id, instrument_id,
                           quantity, amount_usd, memo
                    FROM accounting.ledger_entries
                    WHERE journal_id = p_original_journal_id
                    ORDER BY ledger_account_id, id
                LOOP
                    INSERT INTO accounting.ledger_entries (
                        journal_id, ledger_account_id, debit_credit,
                        asset_id, instrument_id, quantity, amount_usd, memo
                    ) VALUES (
                        v_reversal_journal_id, v_entry.ledger_account_id,
                        CASE v_entry.debit_credit WHEN 'debit' THEN 'credit' ELSE 'debit' END,
                        v_entry.asset_id, v_entry.instrument_id,
                        v_entry.quantity, v_entry.amount_usd,
                        'Reversal of: ' || COALESCE(v_entry.memo, '')
                    );
                END LOOP;

                PERFORM accounting.post_journal(v_reversal_journal_id, p_voided_by);

                SELECT status, voids_journal_id
                INTO v_reversal_status, v_reversal_voids_id
                FROM accounting.journals WHERE id = v_reversal_journal_id;

                IF v_reversal_status != 'posted' THEN
                    RAISE EXCEPTION 'Reversal journal % did not reach posted status', v_reversal_journal_id;
                END IF;
                IF v_reversal_voids_id IS DISTINCT FROM p_original_journal_id THEN
                    RAISE EXCEPTION
                        'Reversal journal % voids_journal_id (% ) does not match original journal id (%)',
                        v_reversal_journal_id, v_reversal_voids_id, p_original_journal_id;
                END IF;

                UPDATE accounting.journals
                SET voided_at = NOW(), voided_by = p_voided_by,
                    voided_by_journal_id = v_reversal_journal_id
                WHERE id = p_original_journal_id;
            EXCEPTION WHEN OTHERS THEN
                PERFORM set_config('superhydra.allow_journal_void', 'off', true);
                RAISE;
            END;

            PERFORM set_config('superhydra.allow_journal_void', 'off', true);

            RETURN v_reversal_journal_id;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # ===== Verification (7 functions) =====
    op.execute("""
        DO $$
        DECLARE
            expected_tables TEXT[] := ARRAY['ledger_accounts', 'journals', 'ledger_entries'];
            expected_functions TEXT[] := ARRAY[
                'post_journal', 'void_journal',
                'validate_journal_entry_dimensions',
                'enforce_journal_status_transitions',
                'enforce_posted_journal_core_immutability',
                'enforce_ledger_account_identity_immutability',
                'enforce_ledger_entry_integrity'
            ];
            t TEXT;
            f TEXT;
            actual_count INT;
        BEGIN
            FOREACH t IN ARRAY expected_tables LOOP
                SELECT COUNT(*) INTO actual_count
                FROM information_schema.tables
                WHERE table_schema = 'accounting' AND table_name = t;
                IF actual_count != 1 THEN
                    RAISE EXCEPTION 'accounting.% not created', t;
                END IF;
            END LOOP;
            FOREACH f IN ARRAY expected_functions LOOP
                SELECT COUNT(*) INTO actual_count
                FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'accounting' AND p.proname = f;
                IF actual_count < 1 THEN
                    RAISE EXCEPTION 'accounting.%() not created', f;
                END IF;
            END LOOP;
            RAISE NOTICE 'accounting double-entry primitives verified (v7)';
        END;
        $$;
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS ledger_entries_integrity_delete ON accounting.ledger_entries;")
    op.execute("DROP TRIGGER IF EXISTS ledger_entries_integrity_update ON accounting.ledger_entries;")
    op.execute("DROP TRIGGER IF EXISTS ledger_entries_integrity_insert ON accounting.ledger_entries;")
    op.execute("DROP FUNCTION IF EXISTS accounting.enforce_ledger_entry_integrity();")
    op.execute("DROP FUNCTION IF EXISTS accounting.validate_journal_entry_dimensions(BIGINT);")
    op.execute("DROP TRIGGER IF EXISTS ledger_accounts_identity_immutability ON accounting.ledger_accounts;")
    op.execute("DROP FUNCTION IF EXISTS accounting.enforce_ledger_account_identity_immutability();")
    op.execute("DROP TRIGGER IF EXISTS journals_core_immutability ON accounting.journals;")
    op.execute("DROP TRIGGER IF EXISTS journals_status_transitions_update ON accounting.journals;")
    op.execute("DROP TRIGGER IF EXISTS journals_status_transitions_insert ON accounting.journals;")
    op.execute("DROP FUNCTION IF EXISTS accounting.enforce_posted_journal_core_immutability();")
    op.execute("DROP FUNCTION IF EXISTS accounting.enforce_journal_status_transitions();")
    op.execute("DROP FUNCTION IF EXISTS accounting.void_journal(BIGINT, TEXT, TEXT);")
    op.execute("DROP FUNCTION IF EXISTS accounting.post_journal(BIGINT, TEXT);")
    op.execute("DROP TRIGGER IF EXISTS ledger_accounts_updated_at ON accounting.ledger_accounts;")
    op.execute("DROP TABLE IF EXISTS accounting.ledger_entries;")
    op.execute("DROP TABLE IF EXISTS accounting.journals;")
    op.execute("DROP TABLE IF EXISTS accounting.ledger_accounts;")
