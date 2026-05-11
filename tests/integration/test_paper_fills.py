"""Integration tests for paper.fills writer.

Day 20.1: writer behavior + DB-level constraints verified end-to-end
via real Postgres connection through the existing fresh_db / _connect /
_setup_basic_0009 pattern from tests/integration/test_migrations.py.

Reviewer-locked scope:
  - Happy path: write, read back
  - Idempotency: same UUID + same content is no-op
  - Hash conflict: same UUID + different content raises
  - Append-only: UPDATE and DELETE both raise via DB triggers
  - DB CHECK firewall: source_mode allowlist, promotion_eligible forbidden
    for PAPER_RESEARCH, quantity > 0, price > 0
  - PaperFillCandidate validation errors at __post_init__
  - Content hash determinism + sensitivity
  - Isolation: writing paper.fills never touches trading.fills
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from psycopg.errors import (
    CheckViolation,
    RestrictViolation,
)

from tests.integration.test_migrations import (  # noqa: F401
    _alembic,
    _connect,
    _setup_basic_0009,
    fresh_db,
)
from execution.paper.fill_writer import (
    FillIntegrityError,
    PaperFillCandidate,
    PaperFillValidationError,
    write_paper_fill,
)


def _bootstrap(cur):
    """Apply migrations to 0010 then bootstrap registry rows.

    Order matters: alembic upgrade 0010 must run BEFORE _setup_basic_0009
    inserts any registry rows. The reason is FK lock acquisition:
    migration 0010 ALTERs paper.fills to add FOREIGN KEY REFERENCES
    registry.strategies(id), which requires a SHARE lock on
    registry.strategies. If the outer transaction has already INSERTed
    into that table, it holds a ROW EXCLUSIVE lock which conflicts with
    SHARE. Result: alembic subprocess blocks forever waiting for the
    outer transaction to release locks the outer test code can't
    release until the subprocess returns. Classic synchronous deadlock.

    Running 0010 first means no locks are held when DDL runs.
    _setup_basic_0009's internal _alembic('upgrade', '0009') is a no-op
    since we're already at 0010.
    """
    _alembic("upgrade", "0010")
    ctx = _setup_basic_0009(cur)
    return ctx


def _make_candidate(refs, **overrides) -> PaperFillCandidate:
    defaults = dict(
        paper_fill_uuid=uuid.uuid4(),
        source_mode="PAPER_RESEARCH",
        strategy_id=refs["strategy_id"],
        portfolio_id=refs["portfolio_id"],
        account_id=refs["account_id"],
        instrument_id=refs["instrument_id"],
        side="buy",
        quantity=Decimal("1.5"),
        price=Decimal("150.00"),
        modeled_slippage_bps=Decimal("0.5"),
        cost_profile_name="binance_vip5_alt_research_v1",
        cost_profile_hash="a" * 64,
        filled_at=datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return PaperFillCandidate(**defaults)


# ─── Happy path ──────────────────────────────────────────────────────────


def test_write_returns_id_and_new_flag(fresh_db):
    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)
        conn.commit()

        candidate = _make_candidate(refs)
        row_id, content_hash, was_new = write_paper_fill(conn, candidate)
        conn.commit()

        assert row_id > 0
        assert len(content_hash) == 64
        assert was_new is True


def test_row_readable_after_write(fresh_db):
    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)
        conn.commit()

        candidate = _make_candidate(refs, quantity=Decimal("2.5"))
        row_id, _, _ = write_paper_fill(conn, candidate)
        conn.commit()

        with conn.cursor() as cur:
            cur.execute(
                "SELECT source_mode, side, quantity, price, "
                "promotion_eligible, content_hash "
                "FROM paper.fills WHERE id=%s;",
                (row_id,),
            )
            row = cur.fetchone()
        assert row[0] == "PAPER_RESEARCH"
        assert row[1] == "buy"
        assert row[2] == Decimal("2.500000000000000000")
        assert row[3] == Decimal("150.000000000000000000")
        assert row[4] is False
        assert len(row[5]) == 64


# ─── Idempotency + hash conflict ─────────────────────────────────────────


def test_reinsert_same_content_is_no_op(fresh_db):
    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)
        conn.commit()

        candidate = _make_candidate(refs)
        id1, hash1, new1 = write_paper_fill(conn, candidate)
        conn.commit()
        id2, hash2, new2 = write_paper_fill(conn, candidate)
        conn.commit()

        assert id1 == id2
        assert hash1 == hash2
        assert new1 is True
        assert new2 is False


def test_reinsert_different_content_raises(fresh_db):
    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)
        conn.commit()

        uid = uuid.uuid4()
        c1 = _make_candidate(refs, paper_fill_uuid=uid,
                             quantity=Decimal("1.5"))
        c2 = _make_candidate(refs, paper_fill_uuid=uid,
                             quantity=Decimal("9.9"))

        write_paper_fill(conn, c1)
        conn.commit()
        with pytest.raises(FillIntegrityError, match="content_hash mismatch"):
            write_paper_fill(conn, c2)


# ─── Append-only enforcement ─────────────────────────────────────────────


def test_update_raises(fresh_db):
    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)
        conn.commit()

        candidate = _make_candidate(refs)
        row_id, _, _ = write_paper_fill(conn, candidate)
        conn.commit()

        with pytest.raises(RestrictViolation, match="append-only"):
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE paper.fills SET quantity = 99 WHERE id = %s;",
                    (row_id,),
                )


def test_delete_raises(fresh_db):
    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)
        conn.commit()

        candidate = _make_candidate(refs)
        row_id, _, _ = write_paper_fill(conn, candidate)
        conn.commit()

        with pytest.raises(RestrictViolation, match="append-only"):
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM paper.fills WHERE id = %s;",
                    (row_id,),
                )


# ─── DB-level CHECK constraints (firewall enforcement at SQL level) ─────


def test_promotion_eligible_true_raises_check(fresh_db):
    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)
        conn.commit()

        with pytest.raises(CheckViolation):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO paper.fills (
                        paper_fill_uuid, source_mode,
                        strategy_id, portfolio_id, account_id, instrument_id,
                        side, quantity, price,
                        modeled_slippage_bps,
                        cost_profile_name, cost_profile_hash,
                        promotion_eligible,
                        content_hash, filled_at
                    ) VALUES (
                        gen_uuidv7(), 'PAPER_RESEARCH',
                        %s, %s, %s, %s,
                        'buy', 1, 100,
                        0.5,
                        'test_profile', 'a',
                        TRUE,
                        repeat('0', 64), NOW()
                    );
                    """,
                    (refs["strategy_id"], refs["portfolio_id"],
                     refs["account_id"], refs["instrument_id"]),
                )


def test_unknown_source_mode_raises_check(fresh_db):
    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)
        conn.commit()

        with pytest.raises(CheckViolation):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO paper.fills (
                        paper_fill_uuid, source_mode,
                        strategy_id, portfolio_id, account_id, instrument_id,
                        side, quantity, price,
                        modeled_slippage_bps,
                        cost_profile_name, cost_profile_hash,
                        promotion_eligible,
                        content_hash, filled_at
                    ) VALUES (
                        gen_uuidv7(), 'PAPER_EMPIRICAL',
                        %s, %s, %s, %s,
                        'buy', 1, 100,
                        0.5,
                        'test_profile', 'a',
                        FALSE,
                        repeat('0', 64), NOW()
                    );
                    """,
                    (refs["strategy_id"], refs["portfolio_id"],
                     refs["account_id"], refs["instrument_id"]),
                )


def test_zero_quantity_raises_check(fresh_db):
    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)
        conn.commit()

        with pytest.raises(CheckViolation):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO paper.fills (
                        paper_fill_uuid, source_mode,
                        strategy_id, portfolio_id, account_id, instrument_id,
                        side, quantity, price,
                        modeled_slippage_bps,
                        cost_profile_name, cost_profile_hash,
                        promotion_eligible,
                        content_hash, filled_at
                    ) VALUES (
                        gen_uuidv7(), 'PAPER_RESEARCH',
                        %s, %s, %s, %s,
                        'buy', 0, 100,
                        0.5,
                        'test_profile', 'a',
                        FALSE,
                        repeat('0', 64), NOW()
                    );
                    """,
                    (refs["strategy_id"], refs["portfolio_id"],
                     refs["account_id"], refs["instrument_id"]),
                )


# ─── Writer-level validation (caught at __post_init__ before any SQL) ───


def test_candidate_wrong_source_mode_raises():
    with pytest.raises(PaperFillValidationError, match="source_mode"):
        PaperFillCandidate(
            paper_fill_uuid=uuid.uuid4(),
            source_mode="LIVE",
            strategy_id=1, portfolio_id=1, account_id=1, instrument_id=1,
            side="buy",
            quantity=Decimal("1"), price=Decimal("100"),
            modeled_slippage_bps=Decimal("0.5"),
            cost_profile_name="p", cost_profile_hash="h",
            filled_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
        )


def test_candidate_zero_quantity_raises():
    with pytest.raises(PaperFillValidationError, match="quantity"):
        PaperFillCandidate(
            paper_fill_uuid=uuid.uuid4(),
            source_mode="PAPER_RESEARCH",
            strategy_id=1, portfolio_id=1, account_id=1, instrument_id=1,
            side="buy",
            quantity=Decimal("0"), price=Decimal("100"),
            modeled_slippage_bps=Decimal("0.5"),
            cost_profile_name="p", cost_profile_hash="h",
            filled_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
        )


def test_candidate_negative_price_raises():
    with pytest.raises(PaperFillValidationError, match="price"):
        PaperFillCandidate(
            paper_fill_uuid=uuid.uuid4(),
            source_mode="PAPER_RESEARCH",
            strategy_id=1, portfolio_id=1, account_id=1, instrument_id=1,
            side="buy",
            quantity=Decimal("1"), price=Decimal("-1"),
            modeled_slippage_bps=Decimal("0.5"),
            cost_profile_name="p", cost_profile_hash="h",
            filled_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
        )


def test_candidate_naive_filled_at_raises():
    with pytest.raises(PaperFillValidationError, match="timezone-aware"):
        PaperFillCandidate(
            paper_fill_uuid=uuid.uuid4(),
            source_mode="PAPER_RESEARCH",
            strategy_id=1, portfolio_id=1, account_id=1, instrument_id=1,
            side="buy",
            quantity=Decimal("1"), price=Decimal("100"),
            modeled_slippage_bps=Decimal("0.5"),
            cost_profile_name="p", cost_profile_hash="h",
            filled_at=datetime(2026, 5, 11),
        )


def test_candidate_invalid_side_raises():
    with pytest.raises(PaperFillValidationError, match="side"):
        PaperFillCandidate(
            paper_fill_uuid=uuid.uuid4(),
            source_mode="PAPER_RESEARCH",
            strategy_id=1, portfolio_id=1, account_id=1, instrument_id=1,
            side="long",
            quantity=Decimal("1"), price=Decimal("100"),
            modeled_slippage_bps=Decimal("0.5"),
            cost_profile_name="p", cost_profile_hash="h",
            filled_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
        )


# ─── Content hash semantics (pure Python; no DB) ────────────────────────


def test_hash_is_deterministic():
    refs = {"strategy_id": 1, "portfolio_id": 1,
            "account_id": 1, "instrument_id": 1}
    c1 = _make_candidate(refs)
    c2 = _make_candidate(refs, paper_fill_uuid=c1.paper_fill_uuid)
    assert c1.content_hash == c2.content_hash


def test_hash_excludes_metadata():
    refs = {"strategy_id": 1, "portfolio_id": 1,
            "account_id": 1, "instrument_id": 1}
    c1 = _make_candidate(refs, metadata={})
    c2 = _make_candidate(refs, paper_fill_uuid=c1.paper_fill_uuid,
                         metadata={"trace_id": "abc"})
    assert c1.content_hash == c2.content_hash


def test_hash_changes_with_quantity():
    refs = {"strategy_id": 1, "portfolio_id": 1,
            "account_id": 1, "instrument_id": 1}
    c1 = _make_candidate(refs, quantity=Decimal("1"))
    c2 = _make_candidate(refs, paper_fill_uuid=c1.paper_fill_uuid,
                         quantity=Decimal("2"))
    assert c1.content_hash != c2.content_hash


def test_hash_changes_with_observed_slippage_null_vs_value():
    refs = {"strategy_id": 1, "portfolio_id": 1,
            "account_id": 1, "instrument_id": 1}
    c1 = _make_candidate(refs, observed_slippage_bps=None)
    c2 = _make_candidate(refs, paper_fill_uuid=c1.paper_fill_uuid,
                         observed_slippage_bps=Decimal("0"))
    assert c1.content_hash != c2.content_hash


# ─── Isolation from trading.fills ────────────────────────────────────────


def test_write_to_paper_does_not_touch_trading(fresh_db):
    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM trading.fills;")
            trading_count_before = cur.fetchone()[0]

        candidate = _make_candidate(refs)
        write_paper_fill(conn, candidate)
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM trading.fills;")
            trading_count_after = cur.fetchone()[0]

        assert trading_count_after == trading_count_before
