"""Paper-fill writer.

Day 20.1 deliverable: pure persistence function for paper.fills.

Writer responsibilities (reviewer-locked):
  - Append-only: only INSERTs, never UPDATE/DELETE (DB triggers enforce this
    too, but writer-level discipline catches mistakes at higher level).
  - Idempotent by (paper_fill_uuid, content_hash): re-insert with same UUID
    and content is a silent no-op returning the existing id.
  - Hash-mismatch raises: re-insert with same UUID but different content
    raises FillIntegrityError; never silently overwrites.
  - source_mode='PAPER_RESEARCH' enforced at the writer level too (DB
    CHECK is the backstop; writer is the friendly error).
  - Never writes trading.fills. This module imports nothing from the
    trading.fills writer path.

The writer is called by the A1 PAPER_RESEARCH runner (Day 20.3) but Day
20.1 ships only the writer + its tests. No runner wiring in this commit.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Final
from uuid import UUID


VALID_SOURCE_MODES: Final[frozenset[str]] = frozenset({"PAPER_RESEARCH"})
VALID_SIDES: Final[frozenset[str]] = frozenset({"buy", "sell"})


class FillIntegrityError(Exception):
    """Raised when a re-insert with the same paper_fill_uuid has a different
    content_hash than the existing row. Indicates either a writer bug
    (caller mutating fields between attempts) or a serious data
    integrity issue."""


class PaperFillValidationError(Exception):
    """Raised when a PaperFillCandidate has invalid fields the DB CHECK
    constraints would also reject, surfaced earlier for a friendlier
    error path."""


@dataclass(frozen=True)
class PaperFillCandidate:
    """A candidate paper.fills row, ready to write.

    All fields except metadata participate in content_hash. Content hash
    is computed lazily via the .content_hash property. Two candidates
    with the same paper_fill_uuid but different content_hash represent
    a conflict; the writer raises on detection.

    metadata is excluded from the content hash because it's free-form
    instrumentation; including it would make hash mismatches noisy when
    only logging metadata changes between runs.

    Required tz-aware filled_at (UTC).
    """

    paper_fill_uuid: UUID
    source_mode: str
    strategy_id: int
    portfolio_id: int
    account_id: int
    instrument_id: int
    side: str
    quantity: Decimal
    price: Decimal
    modeled_slippage_bps: Decimal
    cost_profile_name: str
    cost_profile_hash: str
    filled_at: datetime
    observed_slippage_bps: Decimal | None = None
    order_intent_id: int | None = None
    order_id: int | None = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source_mode not in VALID_SOURCE_MODES:
            raise PaperFillValidationError(
                f"source_mode must be one of {sorted(VALID_SOURCE_MODES)}, "
                f"got {self.source_mode!r}"
            )
        if self.side not in VALID_SIDES:
            raise PaperFillValidationError(
                f"side must be 'buy' or 'sell', got {self.side!r}"
            )
        if self.quantity <= 0:
            raise PaperFillValidationError(
                f"quantity must be positive, got {self.quantity}"
            )
        if self.price <= 0:
            raise PaperFillValidationError(
                f"price must be positive, got {self.price}"
            )
        if self.filled_at.tzinfo is None:
            raise PaperFillValidationError(
                "filled_at must be timezone-aware (UTC recommended)"
            )
        if not isinstance(self.metadata, dict):
            raise PaperFillValidationError(
                f"metadata must be a dict, got {type(self.metadata).__name__}"
            )
        for name in ("cost_profile_name", "cost_profile_hash"):
            v = getattr(self, name)
            if not isinstance(v, str) or not v.strip():
                raise PaperFillValidationError(
                    f"{name} must be a non-empty string"
                )

    @property
    def content_hash(self) -> str:
        """SHA-256 hex of canonical content. Excludes id, paper_fill_uuid,
        created_at (DB-assigned), and metadata (free-form)."""
        canonical_parts = [
            self.source_mode,
            str(self.strategy_id),
            str(self.portfolio_id),
            str(self.account_id),
            str(self.instrument_id),
            str(self.order_intent_id) if self.order_intent_id is not None else "null",
            str(self.order_id) if self.order_id is not None else "null",
            self.side,
            str(self.quantity),
            str(self.price),
            str(self.modeled_slippage_bps),
            str(self.observed_slippage_bps) if self.observed_slippage_bps is not None else "null",
            self.cost_profile_name,
            self.cost_profile_hash,
            self.filled_at.astimezone(timezone.utc).isoformat(),
        ]
        canonical = "\n".join(canonical_parts)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def write_paper_fill(
    conn,
    candidate: PaperFillCandidate,
) -> tuple[int, str, bool]:
    """Write a paper fill, idempotent by paper_fill_uuid + content_hash.

    Args:
        conn: psycopg connection. The caller owns the transaction;
            this function does not commit.
        candidate: PaperFillCandidate to persist.

    Returns:
        Tuple of (paper.fills.id, content_hash, was_new):
            id: the row id (existing or newly inserted)
            content_hash: SHA-256 hex of canonical content
            was_new: True if INSERT occurred; False if existing row
                with matching content was found

    Raises:
        FillIntegrityError: if a row with the same paper_fill_uuid
            exists but with a different content_hash.
        PaperFillValidationError: if the candidate is invalid (also
            raised at __post_init__ time, but the writer adds a check
            in case the dataclass was constructed via a path that
            skipped __post_init__).
    """
    if candidate.source_mode != "PAPER_RESEARCH":
        # Belt-and-suspenders; __post_init__ should have rejected this.
        raise PaperFillValidationError(
            f"writer only accepts source_mode='PAPER_RESEARCH'; "
            f"got {candidate.source_mode!r}"
        )

    content_hash = candidate.content_hash
    metadata_json = _json_encode(candidate.metadata)

    sql = """
        INSERT INTO paper.fills (
            paper_fill_uuid, source_mode,
            strategy_id, portfolio_id, account_id, instrument_id,
            order_intent_id, order_id,
            side, quantity, price,
            modeled_slippage_bps, observed_slippage_bps,
            cost_profile_name, cost_profile_hash,
            promotion_eligible,
            content_hash,
            filled_at,
            metadata
        )
        VALUES (
            %s, %s,
            %s, %s, %s, %s,
            %s, %s,
            %s, %s, %s,
            %s, %s,
            %s, %s,
            %s,
            %s,
            %s,
            %s::jsonb
        )
        ON CONFLICT (paper_fill_uuid) DO NOTHING
        RETURNING id;
    """

    params = (
        str(candidate.paper_fill_uuid), candidate.source_mode,
        candidate.strategy_id, candidate.portfolio_id,
        candidate.account_id, candidate.instrument_id,
        candidate.order_intent_id, candidate.order_id,
        candidate.side, candidate.quantity, candidate.price,
        candidate.modeled_slippage_bps, candidate.observed_slippage_bps,
        candidate.cost_profile_name, candidate.cost_profile_hash,
        False,  # promotion_eligible: PAPER_RESEARCH must be false
        content_hash,
        candidate.filled_at.astimezone(timezone.utc),
        metadata_json,
    )

    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()

        if row is not None:
            # INSERT succeeded.
            return (row[0], content_hash, True)

        # ON CONFLICT DO NOTHING: row already exists. Verify hash matches.
        cur.execute(
            "SELECT id, content_hash FROM paper.fills "
            "WHERE paper_fill_uuid = %s;",
            (str(candidate.paper_fill_uuid),),
        )
        existing = cur.fetchone()
        if existing is None:
            # Shouldn't happen: conflict reported but row not found.
            raise FillIntegrityError(
                f"paper_fill_uuid={candidate.paper_fill_uuid} conflicted "
                f"on INSERT but is not visible in SELECT"
            )
        existing_id, existing_hash = existing
        if existing_hash != content_hash:
            raise FillIntegrityError(
                f"paper_fill_uuid={candidate.paper_fill_uuid}: "
                f"content_hash mismatch "
                f"(existing={existing_hash}, new={content_hash})"
            )
        return (existing_id, content_hash, False)


def _json_encode(d: dict) -> str:
    """Stable JSON encoding for the metadata column."""
    import json
    return json.dumps(d, sort_keys=True, separators=(",", ":"), default=str)
