"""paper.positions helpers for A2.

Day 28a deliverable. Three functions plus one dataclass:

  - PaperPosition: result type for get_open_position
  - get_open_position: read; returns None if no open position
  - open_position: write; INSERTs a new row; raises on UNIQUE violation
  - paper_position_count: count; for test assertions

Source of truth is paper.fills (entry rows). paper.positions is a cache that
materializes the open-position state. The runner writes positions inline with
fills under hard-block semantics.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class PaperPosition:
    """Open paper-research position. Read-side projection of paper.positions."""
    id: int
    paper_position_uuid: str
    strategy_id: int
    instrument_id: int
    quantity: Decimal
    avg_entry_price: Decimal
    opened_at: datetime
    metadata: dict


def get_open_position(
    conn,
    *,
    strategy_id: int,
    instrument_id: int,
) -> Optional[PaperPosition]:
    """Return the open position for (strategy, instrument), or None.

    Because paper.positions has UNIQUE (strategy_id, instrument_id), at most
    one row matches.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, paper_position_uuid, strategy_id, instrument_id,
                   quantity, avg_entry_price, opened_at, metadata
            FROM paper.positions
            WHERE strategy_id = %s AND instrument_id = %s
            LIMIT 1;
            """,
            (strategy_id, instrument_id),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return PaperPosition(
            id=row[0],
            paper_position_uuid=str(row[1]),
            strategy_id=row[2],
            instrument_id=row[3],
            quantity=row[4],
            avg_entry_price=row[5],
            opened_at=row[6],
            metadata=row[7] if isinstance(row[7], dict) else json.loads(row[7]),
        )


def open_position(
    conn,
    *,
    strategy_id: int,
    portfolio_id: int,
    account_id: int,
    instrument_id: int,
    quantity: Decimal,
    avg_entry_price: Decimal,
    opened_at: datetime,
    metadata: dict,
    source_mode: str = "PAPER_RESEARCH",
) -> str:
    """INSERT a new row into paper.positions, or silent no-op on re-run.

    Idempotency contract: paper.positions is materialized state derived from
    paper.fills. If a position already exists for (strategy_id, instrument_id)
    with the same entry_paper_fill_uuid in metadata, the second call is a
    silent no-op (matches the paper.fills writer's hash-mismatch behavior).
    Different entry_paper_fill_uuid means a real conflict and raises.

    Returns the paper_position_uuid of the inserted (or existing) row.

    Raises:
        ValueError: if quantity == 0.
        psycopg.errors.UniqueViolation: if (strategy_id, instrument_id) already
            has a position with a DIFFERENT entry_paper_fill_uuid (real conflict).
        psycopg.errors.CheckViolation: if source_mode is wrong.
    """
    if quantity == 0:
        raise ValueError("open_position requires non-zero quantity")

    # Idempotency check: if a position already exists for (strategy, instrument)
    # and its metadata's entry_paper_fill_uuid matches ours, return existing.
    incoming_efui = metadata.get("entry_paper_fill_uuid")
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT paper_position_uuid, metadata
            FROM paper.positions
            WHERE strategy_id = %s AND instrument_id = %s
            LIMIT 1;
            """,
            (strategy_id, instrument_id),
        )
        existing = cur.fetchone()
        if existing is not None:
            existing_meta = (
                existing[1] if isinstance(existing[1], dict)
                else json.loads(existing[1])
            )
            existing_efui = existing_meta.get("entry_paper_fill_uuid")
            if (incoming_efui is not None
                    and existing_efui == incoming_efui):
                # Idempotent re-run: silent no-op
                return str(existing[0])
            # Real conflict: let the UNIQUE constraint surface it on INSERT
            # below for clarity in the error message.

        cur.execute(
            """
            INSERT INTO paper.positions (
                source_mode, strategy_id, portfolio_id, account_id,
                instrument_id, quantity, avg_entry_price, opened_at,
                metadata
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s::jsonb
            )
            RETURNING paper_position_uuid;
            """,
            (
                source_mode, strategy_id, portfolio_id, account_id,
                instrument_id, quantity, avg_entry_price, opened_at,
                json.dumps(metadata),
            ),
        )
        return str(cur.fetchone()[0])


def paper_position_count(
    conn,
    *,
    strategy_id: Optional[int] = None,
) -> int:
    """Count rows in paper.positions, optionally filtered by strategy_id."""
    with conn.cursor() as cur:
        if strategy_id is None:
            cur.execute("SELECT COUNT(*) FROM paper.positions;")
        else:
            cur.execute(
                "SELECT COUNT(*) FROM paper.positions WHERE strategy_id = %s;",
                (strategy_id,),
            )
        return cur.fetchone()[0]
