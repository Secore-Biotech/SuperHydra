"""Day 14b integration tests for write_and_post_funding_journal.

Runs against real Postgres via the fresh_db fixture. Covers all four
state-machine branches plus the two integrity-error paths.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import psycopg
import pytest

from execution.ledger.fill_journal_writer import (
    FundingEventRecord,
    FundingPaymentMismatchError,
    JournalSourceHashMismatchError,
    build_funding_journal,
    write_and_post_funding_journal,
    write_and_post_journal,
)
from tests.integration.test_migrations import (
    _connect, _setup_basic_0009, fresh_db,  # noqa: F401
)

UTC = timezone.utc


def _instrument_code_from_ctx(cur, ctx) -> str:
    """Look up the actual instrument_code for the perp instrument
    that _setup_basic_0009 created (it includes a uuid suffix)."""
    cur.execute(
        "SELECT instrument_code FROM registry.instruments WHERE id = %s",
        (ctx['instrument_id'],),
    )
    return cur.fetchone()[0]


def _make_resolvers(cur):
    def asset_id(symbol: str) -> int:
        cur.execute(
            "SELECT id FROM registry.assets WHERE symbol = %s", (symbol,),
        )
        row = cur.fetchone()
        if row is None:
            raise KeyError(f"unknown asset symbol {symbol!r}")
        return row[0]

    def instrument_id(code: str):
        cur.execute(
            "SELECT id FROM registry.instruments WHERE instrument_code = %s",
            (code,),
        )
        row = cur.fetchone()
        return row[0] if row else None

    return asset_id, instrument_id


def _make_funding_event(ctx, instrument_code: str, **overrides) -> FundingEventRecord:
    base = dict(
        venue_namespace="venue_test",
        venue_funding_id="BTCUSDT-2026-01-08T08-00",
        portfolio_id=ctx["portfolio_id"],
        strategy_id=ctx["strategy_id"],
        account_id=ctx["account_id"],
        instrument_id=ctx["instrument_id"],
        instrument_code=instrument_code,
        quote_asset_symbol="USDT",
        funding_rate=Decimal("0.0001"),
        position_size=Decimal("-0.01"),
        amount_usd=Decimal("0.95"),
        direction="received",
        funded_at=datetime(2026, 1, 8, 8, 0, 0, tzinfo=UTC),
        funding_environment="SHADOW",
    )
    base.update(overrides)
    return FundingEventRecord(**base)


def test_write_and_post_funding_journal_received_fresh(fresh_db):
    """Fresh write of a 'received' funding event: journal + payment created."""
    with _connect() as conn, conn.cursor() as cur:
        ctx = _setup_basic_0009(cur)
        instrument_code = _instrument_code_from_ctx(cur, ctx)
        conn.commit()

        event = _make_funding_event(ctx, instrument_code)
        draft = build_funding_journal(event, created_by="t14b")
        ar, ir = _make_resolvers(cur)

        journal_id, payment_id, was_new = write_and_post_funding_journal(
            conn, draft, event,
            posted_by="t14b",
            asset_id_resolver=ar,
            instrument_id_resolver=ir,
        )
        assert was_new is True
        assert journal_id > 0
        assert payment_id > 0

        cur.execute(
            "SELECT direction, amount_usd, journal_id, source_type, "
            "       source_namespace, source_id "
            "FROM accounting.funding_payments WHERE id = %s",
            (payment_id,),
        )
        direction, amount_usd, jrn, st, sns, sid = cur.fetchone()
        assert direction == "received"
        assert amount_usd == Decimal("0.95")
        assert jrn == journal_id
        assert st == "funding_event"
        assert sns == "venue_test"
        assert sid == "BTCUSDT-2026-01-08T08-00"

        cur.execute(
            "SELECT COUNT(*) FROM accounting.ledger_entries WHERE journal_id = %s",
            (journal_id,),
        )
        assert cur.fetchone()[0] == 2

        conn.commit()


def test_write_and_post_funding_journal_paid_fresh(fresh_db):
    """Fresh write of a 'paid' funding event: DR funding_expense / CR cash."""
    with _connect() as conn, conn.cursor() as cur:
        ctx = _setup_basic_0009(cur)
        instrument_code = _instrument_code_from_ctx(cur, ctx)
        conn.commit()

        event = _make_funding_event(
            ctx, instrument_code,
            direction="paid",
            position_size=Decimal("0.01"),
            amount_usd=Decimal("0.85"),
        )
        draft = build_funding_journal(event, created_by="t14b")
        ar, ir = _make_resolvers(cur)

        journal_id, payment_id, was_new = write_and_post_funding_journal(
            conn, draft, event,
            posted_by="t14b",
            asset_id_resolver=ar,
            instrument_id_resolver=ir,
        )
        assert was_new is True
        cur.execute(
            "SELECT direction, amount_usd FROM accounting.funding_payments "
            "WHERE id = %s",
            (payment_id,),
        )
        direction, amount_usd = cur.fetchone()
        assert direction == "paid"
        assert amount_usd == Decimal("0.85")

        cur.execute(
            """
            SELECT la.account_code, le.debit_credit, le.amount_usd
            FROM accounting.ledger_entries le
            JOIN accounting.ledger_accounts la ON la.id = le.ledger_account_id
            WHERE le.journal_id = %s
            ORDER BY le.id
            """,
            (journal_id,),
        )
        rows = cur.fetchall()
        assert rows[0][1] == "debit"
        assert rows[0][0].startswith("v1:funding_expense:")
        assert rows[1][1] == "credit"
        assert rows[1][0].startswith("v1:cash:")
        assert rows[1][0].endswith(":USDT")

        conn.commit()


def test_write_and_post_funding_journal_idempotent_replay(fresh_db):
    """Identical second call returns the same ids and was_newly_created=False."""
    with _connect() as conn, conn.cursor() as cur:
        ctx = _setup_basic_0009(cur)
        instrument_code = _instrument_code_from_ctx(cur, ctx)
        conn.commit()

        event = _make_funding_event(ctx, instrument_code)
        draft = build_funding_journal(event, created_by="t14b")
        ar, ir = _make_resolvers(cur)

        j1, p1, new1 = write_and_post_funding_journal(
            conn, draft, event,
            posted_by="t14b",
            asset_id_resolver=ar,
            instrument_id_resolver=ir,
        )
        conn.commit()
        assert new1 is True

        j2, p2, new2 = write_and_post_funding_journal(
            conn, draft, event,
            posted_by="t14b",
            asset_id_resolver=ar,
            instrument_id_resolver=ir,
        )
        assert (j1, p1) == (j2, p2)
        assert new2 is False

        cur.execute(
            "SELECT COUNT(*) FROM accounting.funding_payments "
            "WHERE source_namespace = %s AND source_id = %s",
            ("venue_test", "BTCUSDT-2026-01-08T08-00"),
        )
        assert cur.fetchone()[0] == 1
        conn.commit()


def test_write_and_post_funding_journal_distinct_events(fresh_db):
    """Two events with different venue_funding_id produce distinct rows."""
    with _connect() as conn, conn.cursor() as cur:
        ctx = _setup_basic_0009(cur)
        instrument_code = _instrument_code_from_ctx(cur, ctx)
        conn.commit()

        e1 = _make_funding_event(ctx, instrument_code,
                                 venue_funding_id="BTCUSDT-2026-01-08T08-00")
        e2 = _make_funding_event(ctx, instrument_code,
                                 venue_funding_id="BTCUSDT-2026-01-08T16-00")
        d1 = build_funding_journal(e1, created_by="t14b")
        d2 = build_funding_journal(e2, created_by="t14b")
        ar, ir = _make_resolvers(cur)

        j1, p1, _ = write_and_post_funding_journal(
            conn, d1, e1,
            posted_by="t14b",
            asset_id_resolver=ar,
            instrument_id_resolver=ir,
        )
        j2, p2, _ = write_and_post_funding_journal(
            conn, d2, e2,
            posted_by="t14b",
            asset_id_resolver=ar,
            instrument_id_resolver=ir,
        )
        assert j1 != j2
        assert p1 != p2
        conn.commit()


def test_write_and_post_funding_journal_amount_mismatch_raises(fresh_db):
    """Replay with the same venue id but a different amount raises
    JournalSourceHashMismatchError at the journal layer (because
    amount_usd contributes to the source_hash)."""
    with _connect() as conn, conn.cursor() as cur:
        ctx = _setup_basic_0009(cur)
        instrument_code = _instrument_code_from_ctx(cur, ctx)
        conn.commit()

        e1 = _make_funding_event(ctx, instrument_code,
                                 amount_usd=Decimal("0.95"))
        d1 = build_funding_journal(e1, created_by="t14b")
        ar, ir = _make_resolvers(cur)

        write_and_post_funding_journal(
            conn, d1, e1,
            posted_by="t14b",
            asset_id_resolver=ar,
            instrument_id_resolver=ir,
        )
        conn.commit()

        e2 = _make_funding_event(ctx, instrument_code,
                                 amount_usd=Decimal("1.05"))
        d2 = build_funding_journal(e2, created_by="t14b")
        with pytest.raises(JournalSourceHashMismatchError):
            write_and_post_funding_journal(
                conn, d2, e2,
                posted_by="t14b",
                asset_id_resolver=ar,
                instrument_id_resolver=ir,
            )
        conn.rollback()


def test_write_and_post_funding_journal_recovery_path(fresh_db):
    """Journal exists in posted state, but funding_payment INSERT was never
    completed (simulated partial-failure recovery). The next call should
    insert the payment and report was_newly_created=False."""
    with _connect() as conn, conn.cursor() as cur:
        ctx = _setup_basic_0009(cur)
        instrument_code = _instrument_code_from_ctx(cur, ctx)
        conn.commit()

        event = _make_funding_event(ctx, instrument_code)
        draft = build_funding_journal(event, created_by="t14b")
        ar, ir = _make_resolvers(cur)

        # Manually post the journal alone, skipping the payment INSERT.
        journal_id, _ = write_and_post_journal(
            conn, draft,
            posted_by="t14b",
            asset_id_resolver=ar,
            instrument_id_resolver=ir,
        )
        conn.commit()

        # Now run the full writer. Journal exists, payment doesn't.
        j2, payment_id, was_new = write_and_post_funding_journal(
            conn, draft, event,
            posted_by="t14b",
            asset_id_resolver=ar,
            instrument_id_resolver=ir,
        )
        assert j2 == journal_id
        assert payment_id > 0
        assert was_new is False
        conn.commit()


def test_write_and_post_funding_journal_strategy_id_propagates(fresh_db):
    """funding_payment.strategy_id matches event.strategy_id."""
    with _connect() as conn, conn.cursor() as cur:
        ctx = _setup_basic_0009(cur)
        instrument_code = _instrument_code_from_ctx(cur, ctx)
        conn.commit()

        event = _make_funding_event(ctx, instrument_code)
        draft = build_funding_journal(event, created_by="t14b")
        ar, ir = _make_resolvers(cur)

        _, payment_id, _ = write_and_post_funding_journal(
            conn, draft, event,
            posted_by="t14b",
            asset_id_resolver=ar,
            instrument_id_resolver=ir,
        )
        cur.execute(
            "SELECT strategy_id FROM accounting.funding_payments WHERE id = %s",
            (payment_id,),
        )
        assert cur.fetchone()[0] == ctx["strategy_id"]
        conn.commit()


def test_write_and_post_funding_journal_empty_posted_by_rejected(fresh_db):
    """Empty posted_by rejected before any DB activity."""
    with _connect() as conn, conn.cursor() as cur:
        ctx = _setup_basic_0009(cur)
        instrument_code = _instrument_code_from_ctx(cur, ctx)
        conn.commit()

        event = _make_funding_event(ctx, instrument_code)
        draft = build_funding_journal(event, created_by="t14b")
        ar, ir = _make_resolvers(cur)
        with pytest.raises(ValueError, match="posted_by must be non-empty"):
            write_and_post_funding_journal(
                conn, draft, event,
                posted_by="   ",
                asset_id_resolver=ar,
                instrument_id_resolver=ir,
            )


def test_write_and_post_funding_journal_unknown_instrument_rejected(fresh_db):
    """Unresolvable instrument_code raises before INSERT attempt."""
    with _connect() as conn, conn.cursor() as cur:
        ctx = _setup_basic_0009(cur)
        # Unused: we deliberately use a bogus code instead.
        _ = _instrument_code_from_ctx(cur, ctx)
        conn.commit()

        event = _make_funding_event(ctx, "UNKNOWN-COIN")
        draft = build_funding_journal(event, created_by="t14b")
        ar, ir = _make_resolvers(cur)
        with pytest.raises(ValueError, match="instrument"):
            write_and_post_funding_journal(
                conn, draft, event,
                posted_by="t14b",
                asset_id_resolver=ar,
                instrument_id_resolver=ir,
            )
        conn.rollback()
