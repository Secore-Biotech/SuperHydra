"""paper_fills

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-11

Day 20.1: paper schema + paper.fills table.

Crosses the boundary from research-only spread estimates (Day 19a
research profile, Day 19c.3 tape evidence) into empirical paper
execution evidence. The first commit in this transition creates only
the safe evidence container; A1 runner wiring is Day 20.3.

Schema-level isolation (reviewer-locked):
  - paper schema is a hard namespace boundary
  - paper.fills is NOT trading.fills (which remains venue-confirmed only)
  - No is_paper flag on trading.fills; the two paths never share storage
  - source_mode initially restricted to 'PAPER_RESEARCH' via CHECK; future
    modes (PAPER_EMPIRICAL, etc.) require a follow-up migration that
    explicitly relaxes the CHECK

Promotion firewall (reviewer-locked):
  - PAPER_RESEARCH source_mode forbidden from promotion_eligible=true
    via CHECK constraint; enforced at DB level, not just writer level
  - When future modes are added (e.g. PAPER_EMPIRICAL backed by live
    paper fills), a follow-up migration relaxes the CHECK to permit
    promotion_eligible=true for those modes only

Append-only (reviewer-locked):
  - BEFORE-UPDATE trigger raises on any UPDATE attempt
  - BEFORE-DELETE trigger raises on any DELETE attempt
  - INSERT is the only permitted operation
  - Writer-level idempotency via (paper_fill_uuid, content_hash) is
    enforced by application code, not DB constraints (the DB sees only
    UNIQUE paper_fill_uuid)
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0010"
down_revision: Union[str, Sequence[str], None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Schema.
    op.execute("CREATE SCHEMA paper;")

    # Table.
    op.execute("""
        CREATE TABLE paper.fills (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            paper_fill_uuid UUID NOT NULL DEFAULT gen_uuidv7() UNIQUE,

            -- Source classification.
            -- PAPER_RESEARCH is the only mode at Day 20.1; future modes
            -- require a follow-up migration relaxing this CHECK.
            source_mode TEXT NOT NULL CHECK (source_mode IN ('PAPER_RESEARCH')),

            -- Entity references.
            strategy_id BIGINT NOT NULL REFERENCES registry.strategies(id),
            portfolio_id BIGINT NOT NULL REFERENCES registry.portfolios(id),
            account_id BIGINT NOT NULL REFERENCES registry.accounts(id),
            instrument_id BIGINT NOT NULL REFERENCES registry.instruments(id),

            -- Optional order context (caller-supplied).
            order_intent_id BIGINT REFERENCES trading.order_intents(id),
            -- order_id: no FK yet; Day 20.3 may wire to trading.orders or
            -- similar when the runner integration lands.
            order_id BIGINT,

            -- Economics.
            side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
            quantity NUMERIC(38,18) NOT NULL CHECK (quantity > 0),
            price NUMERIC(38,18) NOT NULL CHECK (price > 0),

            -- Slippage in basis points. Allowed to be negative for price
            -- improvement; no sign CHECK.
            modeled_slippage_bps NUMERIC(20,10) NOT NULL,
            observed_slippage_bps NUMERIC(20,10),

            -- Cost-profile lineage (snapshot of which profile generated
            -- this fill).
            cost_profile_name TEXT NOT NULL
                CHECK (LENGTH(TRIM(cost_profile_name)) > 0),
            cost_profile_hash TEXT NOT NULL
                CHECK (LENGTH(TRIM(cost_profile_hash)) > 0),

            -- Promotion control (DB-enforced firewall).
            -- PAPER_RESEARCH source_mode FORBIDDEN from promotion_eligible=true.
            promotion_eligible BOOLEAN NOT NULL DEFAULT false,

            -- Content integrity. SHA-256 hex of canonical content fields,
            -- computed by writer. Used for idempotency conflict detection.
            content_hash TEXT NOT NULL CHECK (LENGTH(content_hash) = 64),

            -- Timestamps.
            filled_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            -- Free-form metadata.
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

            -- Cross-column invariants.
            CONSTRAINT paper_fills_research_no_promotion CHECK (
                source_mode = 'PAPER_RESEARCH'
                AND promotion_eligible = false
            ),

            CONSTRAINT paper_fills_metadata_is_object CHECK (
                jsonb_typeof(metadata) = 'object'
            )
        );
    """)

    # Indexes.
    op.execute("""
        CREATE INDEX idx_paper_fills_strategy_filled_at
            ON paper.fills(strategy_id, filled_at DESC);
        CREATE INDEX idx_paper_fills_instrument_filled_at
            ON paper.fills(instrument_id, filled_at DESC);
        CREATE INDEX idx_paper_fills_cost_profile_filled_at
            ON paper.fills(cost_profile_name, filled_at DESC);
        CREATE INDEX idx_paper_fills_source_mode
            ON paper.fills(source_mode);
    """)

    # Append-only enforcement.
    op.execute("""
        CREATE OR REPLACE FUNCTION paper.fills_append_only_guard()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION
                'paper.fills is append-only; % not permitted', TG_OP
                USING ERRCODE = 'restrict_violation';
        END;
        $$;

        CREATE TRIGGER paper_fills_block_update
            BEFORE UPDATE ON paper.fills
            FOR EACH ROW EXECUTE FUNCTION paper.fills_append_only_guard();

        CREATE TRIGGER paper_fills_block_delete
            BEFORE DELETE ON paper.fills
            FOR EACH ROW EXECUTE FUNCTION paper.fills_append_only_guard();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS paper_fills_block_delete ON paper.fills;")
    op.execute("DROP TRIGGER IF EXISTS paper_fills_block_update ON paper.fills;")
    op.execute("DROP FUNCTION IF EXISTS paper.fills_append_only_guard();")
    op.execute("DROP TABLE IF EXISTS paper.fills;")
    op.execute("DROP SCHEMA IF EXISTS paper;")
