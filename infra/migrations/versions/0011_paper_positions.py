"""paper_positions

Day 28a deliverable. Adds paper.positions table — materialized state of open
A2 paper-research positions, derived from paper.fills entry rows.

Source of truth remains paper.fills. paper.positions is a cache: each row is
reconstructable from the corresponding paper.fills entries. Day 29+ may add
an explicit reconciler. For Day 28a, the runner writes positions inline with
fills under hard-block anti-reentry semantics.

Schema:
  - paper_position_uuid: stable identity
  - source_mode: locked to 'PAPER_RESEARCH' (firewall)
  - strategy/portfolio/account/instrument: registry FKs
  - quantity: signed Decimal (positive = long, negative = short)
  - avg_entry_price: entry price for P&L computation later
  - opened_at: when the position was opened
  - last_updated_at: most recent state change
  - promotion_eligible: locked false (firewall)
  - metadata: a2_intent_uuid, a2_leg, entry_paper_fill_uuid

Constraints:
  - source_mode = 'PAPER_RESEARCH' (CHECK)
  - promotion_eligible = false (CHECK)
  - quantity != 0 (CHECK)
  - UNIQUE (strategy_id, instrument_id) — at most one open position
    per (strategy, instrument) pair; hard-block enforced at DB level

Revision ID: 0011
Revises: 0010
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE paper.positions (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            paper_position_uuid UUID NOT NULL DEFAULT gen_uuidv7(),
            source_mode TEXT NOT NULL,
            strategy_id BIGINT NOT NULL REFERENCES registry.strategies(id),
            portfolio_id BIGINT NOT NULL REFERENCES registry.portfolios(id),
            account_id BIGINT NOT NULL REFERENCES registry.accounts(id),
            instrument_id BIGINT NOT NULL REFERENCES registry.instruments(id),
            quantity NUMERIC(38,18) NOT NULL,
            avg_entry_price NUMERIC(38,18) NOT NULL,
            opened_at TIMESTAMPTZ NOT NULL,
            last_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            promotion_eligible BOOLEAN NOT NULL DEFAULT false,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT paper_positions_source_mode_check
                CHECK (source_mode = 'PAPER_RESEARCH'),
            CONSTRAINT paper_positions_promotion_eligible_check
                CHECK (promotion_eligible = false),
            CONSTRAINT paper_positions_quantity_nonzero_check
                CHECK (quantity != 0),
            CONSTRAINT paper_positions_strategy_instrument_unique
                UNIQUE (strategy_id, instrument_id)
        );
    """)

    op.execute("""
        CREATE UNIQUE INDEX idx_paper_positions_uuid
            ON paper.positions(paper_position_uuid);
    """)

    op.execute("""
        CREATE INDEX idx_paper_positions_strategy_opened_at
            ON paper.positions(strategy_id, opened_at DESC);
    """)

    op.execute(
        "COMMENT ON TABLE paper.positions IS "
        "'Materialized state of open A2 paper-research positions. "
        "Source of truth is paper.fills entry rows; positions table is a cache. "
        "Day 28a: hard-block anti-reentry via UNIQUE (strategy_id, instrument_id).';"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS paper.positions;")
