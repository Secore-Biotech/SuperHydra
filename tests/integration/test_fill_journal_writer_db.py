"""Integration tests for execution.ledger.fill_journal_writer DB layer.

Day 11. Pure-function tests live in
strategies/a1_funding/tests/unit/test_fill_journal_writer.py and
test_chart_of_accounts.py. This file tests the DB writer end-to-end
against a fresh Postgres.

Coverage:
  * Single spot fill writes balanced 4-entry journal, posts it
  * Single perp fill writes balanced 4-entry journal, posts it
  * Re-running same fill is idempotent (returns same id)
  * Same source identity with mismatched hash raises
  * Crash recovery: pre-existing draft journal gets resumed to posted
  * resolve_account_id: idempotent, accepts repeated calls
  * resolve_account_id: account-code collision raises
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from decimal import Decimal

import psycopg

from tests.integration.test_migrations import _connect, _setup_basic_0009, fresh_db

from execution.ledger.chart_of_accounts import (
    AccountCodeCollisionError,
    AccountSpec,
    resolve_account_id,
    spec_for_account_code,
)
from execution.ledger.fill_journal_writer import (
    FillRecord,
    JournalSourceHashMismatchError,
    build_trade_journal,
    cash_account_code,
    write_and_post_journal,
)


UTC = timezone.utc


# ─── DB-backed resolvers ──────────────────────────────────────────────────


def _make_resolvers(cur):
    """Return (asset_resolver, instrument_resolver) bound to the cursor."""
    def asset_id(symbol: str) -> int:
        cur.execute(
            "SELECT id FROM registry.assets WHERE symbol = %s",
            (symbol,),
        )
        row = cur.fetchone()
        if row is None:
            raise KeyError(f"unknown asset symbol {symbol!r}")
        return row[0]

    def instrument_id(code: str) -> int | None:
        cur.execute(
            "SELECT id FROM registry.instruments WHERE instrument_code = %s",
            (code,),
        )
        row = cur.fetchone()
        return row[0] if row else None

    return asset_id, instrument_id


def _create_btc_spot_instrument(cur, ctx) -> int:
    """Create a BTC spot instrument alongside the perp from _setup_basic_0009.
    Mirrors what the smoke test does."""
    cur.execute(
        """
        INSERT INTO registry.instruments (
            instrument_code, display_name, venue_id, instrument_type,
            base_asset_id, quote_asset_id, status
        ) VALUES (
            'BTCUSDT-SPOT', 'BTC/USDT spot', %s, 'spot',
            (SELECT id FROM registry.assets WHERE symbol = 'BTC'),
            (SELECT id FROM registry.assets WHERE symbol = 'USDT'),
            'active'
        )
        ON CONFLICT (instrument_code) DO NOTHING
        RETURNING id
        """,
        (ctx["venue_id"],),
    )
    row = cur.fetchone()
    if row:
        return row[0]
    # Already existed — fetch
    cur.execute(
        "SELECT id FROM registry.instruments WHERE instrument_code = 'BTCUSDT-SPOT'"
    )
    return cur.fetchone()[0]


def _make_spot_fill(ctx, *, fill_uuid: str = "01900000-0000-7000-8000-000000000001",
                   content_hash: str = "a" * 64,
                   side: str = "buy") -> FillRecord:
    return FillRecord(
        fill_uuid=fill_uuid,
        fill_content_hash=content_hash,
        portfolio_id=ctx["portfolio_id"],
        strategy_id=ctx["strategy_id"],
        account_id=ctx["account_id"],
        instrument_id=ctx["instrument_id"],  # repurposed; spot id resolved at write time
        instrument_code="BTCUSDT-SPOT",
        instrument_type="spot",
        base_asset_symbol="BTC", quote_asset_symbol="USDT",
        side=side,
        quantity=Decimal("0.01"), price=Decimal("100000"),
        fee_usd=Decimal("0.50"),
        fill_environment="SHADOW",
        filled_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
    )


def _make_perp_fill(ctx, *, fill_uuid: str = "01900000-0000-7000-8000-000000000002",
                   content_hash: str = "b" * 64,
                   side: str = "sell") -> FillRecord:
    return FillRecord(
        fill_uuid=fill_uuid,
        fill_content_hash=content_hash,
        portfolio_id=ctx["portfolio_id"],
        strategy_id=ctx["strategy_id"],
        account_id=ctx["account_id"],
        instrument_id=ctx["instrument_id"],
        instrument_code="BTCUSDT",
        instrument_type="perp",
        base_asset_symbol="BTC", quote_asset_symbol="USDT",
        side=side,
        quantity=Decimal("0.01"), price=Decimal("100000"),
        fee_usd=Decimal("0.50"),
        fill_environment="SHADOW",
        filled_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
    )


# ─── resolve_account_id ───────────────────────────────────────────────────


def test_resolve_account_id_inserts_new(fresh_db):
    """First call creates the row, returns the id."""
    with _connect() as conn, conn.cursor() as cur:
        ctx = _setup_basic_0009(cur)
        conn.commit()

        asset_id, instrument_id = _make_resolvers(cur)
        spec = spec_for_account_code(
            cash_account_code(ctx["portfolio_id"], ctx["strategy_id"],
                              ctx["account_id"], "USDT"),
            asset_id_resolver=asset_id,
            instrument_id_resolver=instrument_id,
        )
        new_id = resolve_account_id(conn, spec)
        assert new_id > 0
        conn.commit()


def test_resolve_account_id_idempotent(fresh_db):
    """Same spec, repeated calls → same id, no second row."""
    with _connect() as conn, conn.cursor() as cur:
        ctx = _setup_basic_0009(cur)
        conn.commit()

        asset_id, instrument_id = _make_resolvers(cur)
        spec = spec_for_account_code(
            cash_account_code(ctx["portfolio_id"], ctx["strategy_id"],
                              ctx["account_id"], "USDT"),
            asset_id_resolver=asset_id,
            instrument_id_resolver=instrument_id,
        )
        id1 = resolve_account_id(conn, spec)
        id2 = resolve_account_id(conn, spec)
        id3 = resolve_account_id(conn, spec)
        conn.commit()

        assert id1 == id2 == id3

        cur.execute(
            "SELECT COUNT(*) FROM accounting.ledger_accounts WHERE account_code = %s",
            (spec.account_code,),
        )
        assert cur.fetchone()[0] == 1


def test_resolve_account_id_distinct_codes_distinct_ids(fresh_db):
    """Different account codes → distinct rows."""
    with _connect() as conn, conn.cursor() as cur:
        ctx = _setup_basic_0009(cur)
        conn.commit()

        asset_id, instrument_id = _make_resolvers(cur)

        cash_spec = spec_for_account_code(
            cash_account_code(ctx["portfolio_id"], ctx["strategy_id"],
                              ctx["account_id"], "USDT"),
            asset_id_resolver=asset_id,
            instrument_id_resolver=instrument_id,
        )
        from execution.ledger.fill_journal_writer import (
            margin_collateral_account_code,
            fee_expense_account_code,
        )
        margin_spec = spec_for_account_code(
            margin_collateral_account_code(ctx["portfolio_id"], ctx["strategy_id"],
                                           ctx["account_id"], "USDT"),
            asset_id_resolver=asset_id,
            instrument_id_resolver=instrument_id,
        )
        fee_spec = spec_for_account_code(
            fee_expense_account_code(ctx["portfolio_id"], ctx["strategy_id"]),
            asset_id_resolver=asset_id,
            instrument_id_resolver=instrument_id,
        )

        cash_id = resolve_account_id(conn, cash_spec)
        margin_id = resolve_account_id(conn, margin_spec)
        fee_id = resolve_account_id(conn, fee_spec)
        conn.commit()

        assert cash_id != margin_id != fee_id
        assert len({cash_id, margin_id, fee_id}) == 3


def test_resolve_account_id_collision_raises(fresh_db):
    """Two specs with same account_code but different dimensions → raises.

    Construct the second spec by going around the parser (manual
    AccountSpec) — this simulates the integrity-failure case where the
    naming convention is broken or someone inserted by hand.
    """
    with _connect() as conn, conn.cursor() as cur:
        ctx = _setup_basic_0009(cur)
        conn.commit()

        asset_id, instrument_id = _make_resolvers(cur)
        usdt_id = asset_id("USDT")

        # Insert original
        original_spec = spec_for_account_code(
            cash_account_code(ctx["portfolio_id"], ctx["strategy_id"],
                              ctx["account_id"], "USDT"),
            asset_id_resolver=asset_id,
            instrument_id_resolver=instrument_id,
        )
        resolve_account_id(conn, original_spec)
        conn.commit()

        # Construct a colliding spec by hand: same account_code, but
        # different asset_id (BTC instead of USDT)
        btc_id = asset_id("BTC")
        bad_spec = AccountSpec(
            account_code=original_spec.account_code,  # same code!
            account_name=original_spec.account_name,
            account_type=original_spec.account_type,
            account_subtype=original_spec.account_subtype,
            portfolio_id=original_spec.portfolio_id,
            strategy_id=original_spec.strategy_id,
            registry_account_id=original_spec.registry_account_id,
            asset_id=btc_id,  # WRONG — original has usdt_id
            instrument_id=original_spec.instrument_id,
        )
        with pytest.raises(AccountCodeCollisionError, match="dimensions differ"):
            resolve_account_id(conn, bad_spec)


# ─── write_and_post_journal: spot ─────────────────────────────────────────


def test_write_and_post_journal_spot_fresh(fresh_db):
    """First write of a spot fill: journal + 4 entries, posted, balanced."""
    with _connect() as conn, conn.cursor() as cur:
        ctx = _setup_basic_0009(cur)
        _create_btc_spot_instrument(cur, ctx)
        conn.commit()

        asset_id, instrument_id = _make_resolvers(cur)

        fill = _make_spot_fill(ctx, side="buy")
        draft = build_trade_journal(fill, created_by="day11_test")
        journal_id, was_new = write_and_post_journal(
            conn, draft,
            posted_by="day11_test",
            asset_id_resolver=asset_id,
            instrument_id_resolver=instrument_id,
        )
        conn.commit()

        assert journal_id > 0
        assert was_new is True

        # Status posted
        cur.execute(
            "SELECT status, posted_by FROM accounting.journals WHERE id = %s",
            (journal_id,),
        )
        status, posted_by = cur.fetchone()
        assert status == "posted"
        assert posted_by == "day11_test"

        # 4 entries, balanced
        cur.execute(
            """
            SELECT debit_credit, amount_usd
            FROM accounting.ledger_entries WHERE journal_id = %s
            ORDER BY created_at, id
            """,
            (journal_id,),
        )
        rows = cur.fetchall()
        assert len(rows) == 4
        debits = sum(r[1] for r in rows if r[0] == "debit")
        credits = sum(r[1] for r in rows if r[0] == "credit")
        assert debits == credits == Decimal("1000.50")


def test_write_and_post_journal_spot_zero_fee(fresh_db):
    """Zero-fee spot fill: 2 entries, still balanced."""
    with _connect() as conn, conn.cursor() as cur:
        ctx = _setup_basic_0009(cur)
        _create_btc_spot_instrument(cur, ctx)
        conn.commit()

        asset_id, instrument_id = _make_resolvers(cur)

        fill = FillRecord(
            fill_uuid="01900000-0000-7000-8000-zerofeebuild",
            fill_content_hash="z" * 64,
            portfolio_id=ctx["portfolio_id"], strategy_id=ctx["strategy_id"],
            account_id=ctx["account_id"], instrument_id=ctx["instrument_id"],
            instrument_code="BTCUSDT-SPOT", instrument_type="spot",
            base_asset_symbol="BTC", quote_asset_symbol="USDT",
            side="buy",
            quantity=Decimal("0.01"), price=Decimal("100000"),
            fee_usd=Decimal("0"),
            fill_environment="SHADOW",
            filled_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        )
        draft = build_trade_journal(fill, created_by="day11_test")
        journal_id, was_new = write_and_post_journal(
            conn, draft,
            posted_by="day11_test",
            asset_id_resolver=asset_id,
            instrument_id_resolver=instrument_id,
        )
        conn.commit()

        cur.execute(
            "SELECT COUNT(*) FROM accounting.ledger_entries WHERE journal_id = %s",
            (journal_id,),
        )
        assert cur.fetchone()[0] == 2


# ─── write_and_post_journal: perp ─────────────────────────────────────────


def test_write_and_post_journal_perp_fresh(fresh_db):
    """First write of a perp fill: journal + 4 entries, posted, balanced."""
    with _connect() as conn, conn.cursor() as cur:
        ctx = _setup_basic_0009(cur)
        conn.commit()

        asset_id, instrument_id = _make_resolvers(cur)

        fill = _make_perp_fill(ctx)
        draft = build_trade_journal(fill, created_by="day11_test")
        journal_id, was_new = write_and_post_journal(
            conn, draft,
            posted_by="day11_test",
            asset_id_resolver=asset_id,
            instrument_id_resolver=instrument_id,
        )
        conn.commit()

        assert was_new is True

        # 4 entries, balanced
        cur.execute(
            """
            SELECT debit_credit, amount_usd
            FROM accounting.ledger_entries WHERE journal_id = %s
            """,
            (journal_id,),
        )
        rows = cur.fetchall()
        assert len(rows) == 4
        debits = sum(r[1] for r in rows if r[0] == "debit")
        credits = sum(r[1] for r in rows if r[0] == "credit")
        assert debits == credits == Decimal("1000.50")

        # Verify NO position ledger entry for perp (per Day 9 design)
        cur.execute(
            """
            SELECT la.account_subtype, la.account_code
            FROM accounting.ledger_entries le
            JOIN accounting.ledger_accounts la ON la.id = le.ledger_account_id
            WHERE le.journal_id = %s
            """,
            (journal_id,),
        )
        subtypes = {r[0] for r in cur.fetchall()}
        assert "position" not in subtypes
        assert "margin_collateral" in subtypes
        assert "cash" in subtypes
        assert "fee_expense" in subtypes


# ─── Idempotency & integrity ──────────────────────────────────────────────


def test_write_and_post_journal_idempotent_replay(fresh_db):
    """Same fill → same journal id on every call. No duplicate entries."""
    with _connect() as conn, conn.cursor() as cur:
        ctx = _setup_basic_0009(cur)
        _create_btc_spot_instrument(cur, ctx)
        conn.commit()

        asset_id, instrument_id = _make_resolvers(cur)

        fill = _make_spot_fill(ctx)
        draft = build_trade_journal(fill, created_by="day11_test")

        id1, was_new1 = write_and_post_journal(
            conn, draft,
            posted_by="day11_test",
            asset_id_resolver=asset_id,
            instrument_id_resolver=instrument_id,
        )
        conn.commit()

        id2, was_new2 = write_and_post_journal(
            conn, draft,
            posted_by="day11_test",
            asset_id_resolver=asset_id,
            instrument_id_resolver=instrument_id,
        )
        conn.commit()

        id3, was_new3 = write_and_post_journal(
            conn, draft,
            posted_by="day11_test",
            asset_id_resolver=asset_id,
            instrument_id_resolver=instrument_id,
        )
        conn.commit()

        assert id1 == id2 == id3
        assert was_new1 is True
        assert was_new2 is False
        assert was_new3 is False

        # Still exactly 4 entries — no duplicates from re-runs
        cur.execute(
            "SELECT COUNT(*) FROM accounting.ledger_entries WHERE journal_id = %s",
            (id1,),
        )
        assert cur.fetchone()[0] == 4


def test_write_and_post_journal_source_hash_mismatch_raises(fresh_db):
    """Same source identity, different hash → raises."""
    with _connect() as conn, conn.cursor() as cur:
        ctx = _setup_basic_0009(cur)
        _create_btc_spot_instrument(cur, ctx)
        conn.commit()

        asset_id, instrument_id = _make_resolvers(cur)

        fill1 = _make_spot_fill(
            ctx, content_hash="aaaa" * 16, fill_uuid="01900000-0000-7000-8000-deadbeefdead"
        )
        draft1 = build_trade_journal(fill1, created_by="day11_test")
        write_and_post_journal(
            conn, draft1,
            posted_by="day11_test",
            asset_id_resolver=asset_id,
            instrument_id_resolver=instrument_id,
        )
        conn.commit()

        # Same fill_uuid, different content_hash → different source_hash
        fill2 = _make_spot_fill(
            ctx, content_hash="bbbb" * 16, fill_uuid="01900000-0000-7000-8000-deadbeefdead"
        )
        draft2 = build_trade_journal(fill2, created_by="day11_test")

        with pytest.raises(JournalSourceHashMismatchError) as exc:
            write_and_post_journal(
                conn, draft2,
                posted_by="day11_test",
                asset_id_resolver=asset_id,
                instrument_id_resolver=instrument_id,
            )
        # Exception message includes both hashes
        msg = str(exc.value)
        assert "existing_source_hash" in msg
        assert "incoming_source_hash" in msg
        assert draft1.source_hash in msg
        assert draft2.source_hash in msg


def test_write_and_post_journal_resumes_unposted_draft(fresh_db):
    """A draft journal left over from a prior crashed run gets posted on
    the next call. No duplicate entries created."""
    with _connect() as conn, conn.cursor() as cur:
        ctx = _setup_basic_0009(cur)
        _create_btc_spot_instrument(cur, ctx)
        conn.commit()

        asset_id, instrument_id = _make_resolvers(cur)

        fill = _make_spot_fill(ctx)
        draft = build_trade_journal(fill, created_by="day11_test")

        # Manually insert journal as draft + entries (simulating a prior
        # run that crashed before post_journal was called).
        from execution.ledger.fill_journal_writer import (
            _insert_journal_or_load_existing,
            _insert_entries,
        )
        new_id, was_new, _status = _insert_journal_or_load_existing(
            conn, draft, posted_by="day11_test"
        )
        _insert_entries(
            conn, new_id, draft,
            asset_id_resolver=asset_id,
            instrument_id_resolver=instrument_id,
        )
        conn.commit()

        # Verify it's draft, not posted
        cur.execute(
            "SELECT status FROM accounting.journals WHERE id = %s", (new_id,)
        )
        assert cur.fetchone()[0] == "draft"

        # Now call write_and_post_journal — should detect existing draft
        # and resume posting it. NOT insert duplicate entries.
        recovered_id, was_new = write_and_post_journal(
            conn, draft,
            posted_by="day11_test",
            asset_id_resolver=asset_id,
            instrument_id_resolver=instrument_id,
        )
        conn.commit()

        assert recovered_id == new_id
        assert was_new is False

        cur.execute(
            "SELECT status FROM accounting.journals WHERE id = %s", (new_id,)
        )
        assert cur.fetchone()[0] == "posted"

        # Still exactly 4 entries — recovery did NOT duplicate
        cur.execute(
            "SELECT COUNT(*) FROM accounting.ledger_entries WHERE journal_id = %s",
            (new_id,),
        )
        assert cur.fetchone()[0] == 4


def test_write_and_post_journal_distinct_fills_distinct_journals(fresh_db):
    """Two different fills produce two journals, both balanced."""
    with _connect() as conn, conn.cursor() as cur:
        ctx = _setup_basic_0009(cur)
        _create_btc_spot_instrument(cur, ctx)
        conn.commit()

        asset_id, instrument_id = _make_resolvers(cur)

        fill_a = _make_spot_fill(
            ctx, fill_uuid="01900000-0000-7000-8000-aaaaaaaaaaaa", content_hash="aaaa" * 16
        )
        fill_b = _make_perp_fill(
            ctx, fill_uuid="01900000-0000-7000-8000-bbbbbbbbbbbb", content_hash="bbbb" * 16
        )

        draft_a = build_trade_journal(fill_a, created_by="t")
        draft_b = build_trade_journal(fill_b, created_by="t")

        id_a, _ = write_and_post_journal(
            conn, draft_a, posted_by="t",
            asset_id_resolver=asset_id, instrument_id_resolver=instrument_id,
        )
        id_b, _ = write_and_post_journal(
            conn, draft_b, posted_by="t",
            asset_id_resolver=asset_id, instrument_id_resolver=instrument_id,
        )
        conn.commit()

        assert id_a != id_b
        cur.execute(
            "SELECT id, status FROM accounting.journals WHERE id IN (%s, %s)",
            (id_a, id_b),
        )
        rows = dict(cur.fetchall())
        assert rows[id_a] == "posted"
        assert rows[id_b] == "posted"


def test_posted_by_propagates_to_journals_table(fresh_db):
    """posted_by argument lands in the journal's posted_by column."""
    with _connect() as conn, conn.cursor() as cur:
        ctx = _setup_basic_0009(cur)
        _create_btc_spot_instrument(cur, ctx)
        conn.commit()

        asset_id, instrument_id = _make_resolvers(cur)
        fill = _make_spot_fill(ctx)
        draft = build_trade_journal(fill, created_by="day11_test")
        journal_id, _ = write_and_post_journal(
            conn, draft,
            posted_by="alice@example",
            asset_id_resolver=asset_id,
            instrument_id_resolver=instrument_id,
        )
        conn.commit()

        cur.execute(
            "SELECT created_by, posted_by FROM accounting.journals WHERE id = %s",
            (journal_id,),
        )
        created_by, posted_by = cur.fetchone()
        assert created_by == "day11_test"
        assert posted_by == "alice@example"


def test_empty_posted_by_rejected(fresh_db):
    """posted_by must be non-empty."""
    with _connect() as conn, conn.cursor() as cur:
        ctx = _setup_basic_0009(cur)
        _create_btc_spot_instrument(cur, ctx)
        conn.commit()

        asset_id, instrument_id = _make_resolvers(cur)
        fill = _make_spot_fill(ctx)
        draft = build_trade_journal(fill, created_by="t")

        with pytest.raises(ValueError, match="posted_by"):
            write_and_post_journal(
                conn, draft,
                posted_by="",
                asset_id_resolver=asset_id,
                instrument_id_resolver=instrument_id,
            )
