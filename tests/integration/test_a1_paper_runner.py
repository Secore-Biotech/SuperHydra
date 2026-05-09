"""Day 15b.2: A1PaperRunner integration test.

Drives one logical tick through the full OMS submit + accounting path
against real Postgres. The runner's submit_callback is a closure that
composes:

  submit_intent_through_oms(conn, intent, ...)         # allocator → fills
  build_trade_journal + write_and_post_journal         # per fill
  trading.reconcile_fill                               # per fill (links journal)
  positions.compute_position_snapshot                  # per leg's instrument

This is the production-shaped runner: tick() returns when one intent
has been submitted and fully accounted for.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable

import pytest

from core.config.cost_model import conservative_default_v0 as cost_default
from data.ingestion.vendors.binance.funding_rate import FundingRate
from execution.ledger.fill_journal_writer import (
    FillRecord,
    build_trade_journal,
    write_and_post_journal,
)
from strategies.a1_funding.config.sizing import (
    InstrumentSizingRule,
    SizingConfig,
    SIZING_CONFIG_SCHEMA_VERSION,
)
from strategies.a1_funding.sizing.order_intent import OrderIntent
from strategies.a1_funding.runner.oms_submit import (
    SubmissionResult,
    submit_intent_through_oms,
)
from strategies.a1_funding.runner.paper_runner import (
    A1PaperRunner,
    FundingDueEvent,
)

# Reuse the smoke test's DB fixtures and helpers.
from tests.integration.test_a1_smoke_vertical import (
    _connect,
    _create_btc_spot_instrument,
    _hash_funding_window,
    _make_db_resolvers,
    fresh_db,  # noqa: F401
)
from tests.integration.test_migrations import _setup_basic_0009


UTC = timezone.utc


def _make_funding_window(*, instrument_code: str, n: int = 12) -> list[FundingRate]:
    """Synthetic positive-funding window: receives by being short."""
    base_time = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    return [
        FundingRate(
            venue="binance",
            instrument=instrument_code,
            funding_time=base_time + timedelta(hours=8 * i),
            funding_rate=Decimal("0.005"),  # well above cost ~0.0012/period
            mark_price=Decimal("100000"),
            ingested_at=base_time + timedelta(hours=8 * i, minutes=1),
        )
        for i in range(n)
    ]


def _sizing_for_btcusdt(perp_code: str, spot_code: str) -> SizingConfig:
    return SizingConfig(
        schema_version=SIZING_CONFIG_SCHEMA_VERSION,
        rules=(
            InstrumentSizingRule(
                venue="binance",
                perp_instrument=perp_code,
                spot_instrument=spot_code,
                max_quantity=Decimal("0.01"),
                slippage_tier_name="btc_eth_top_tier",
                min_quantity=Decimal("0.001"),
            ),
        ),
        max_total_notional_usd=Decimal("10000"),
    )


def _make_current_position_source(conn, ctx, instrument_id_by_code) -> Callable:
    """Return a callable that reads signed quantity from
    positions.position_snapshots (latest by snapshot_at) for the given
    instrument code, or Decimal("0") if no snapshot exists yet.

    First-tick semantics: no snapshot exists → flat → returns 0.
    """
    def _read_qty(instrument_code: str) -> Decimal:
        instrument_id = instrument_id_by_code.get(instrument_code)
        if instrument_id is None:
            return Decimal("0")
        with conn.cursor() as cur:
            # Filter by created_by='paper_runner' to ignore the bootstrap
            # NAV snapshot that _setup_basic_0009 creates at wall-clock time.
            # Without this filter, mixing a synthetic-time runner with a
            # wall-clock-time bootstrap would cause the runner to read the
            # bootstrap snapshot (which is timestamped "now" and thus newer
            # than synthetic snapshots) and conclude the position is flat
            # when it isn't.
            cur.execute(
                """
                SELECT quantity
                FROM positions.position_snapshots
                WHERE portfolio_id = %s
                  AND strategy_id = %s
                  AND account_id = %s
                  AND instrument_id = %s
                  AND created_by = 'paper_runner'
                  AND computation_version = 'a1.runner.v0'
                ORDER BY snapshot_at DESC
                LIMIT 1
                """,
                (
                    ctx["portfolio_id"], ctx["strategy_id"],
                    ctx["account_id"], instrument_id,
                ),
            )
            row = cur.fetchone()
            return row[0] if row is not None else Decimal("0")
    return _read_qty


def _make_submit_callback(
    conn, ctx, *,
    spot_instrument_id: int,
    venue_namespace: str,
    funding_window_hash: str,
    signal_eval,
    asset_id_resolver,
    instrument_id_resolver,
    perp_fill_price: Decimal,
    spot_fill_price: Decimal,
    fill_ts_source: Callable[[], "datetime"] | None = None,
) -> Callable[[OrderIntent], None]:
    """Build a submit_callback closure that drives the full accounted path:
    submit_intent_through_oms → journals per fill → reconcile_fill →
    compute_position_snapshot per leg.

    Production shape: the runner submits an intent and the system reaches
    a fully-accounted state.
    """
    def _submit(intent: OrderIntent) -> None:
        # If a fill_ts_source is injected (e.g. by a backfill harness using
        # a logical clock), use it; otherwise use wall-clock time.
        fill_ts = fill_ts_source() if fill_ts_source is not None else datetime.now(UTC)

        # ─── Steps 2-7 via helper ──────────────────────────────────────
        sub: SubmissionResult = submit_intent_through_oms(
            conn,
            intent,
            ctx=ctx,
            spot_instrument_id=spot_instrument_id,
            venue_namespace=venue_namespace,
            funding_window_hash=funding_window_hash,
            signal_eval=signal_eval,
            fill_price_perp=perp_fill_price,
            fill_price_spot=spot_fill_price,
            fill_ts=fill_ts,
            created_by="paper_runner",
        )
        conn.commit()

        # ─── Steps 7.5-8: journal + reconcile per fill ─────────────────
        journal_ids: dict[str, int] = {}
        for label, fill_id, vns, vfid, leg, instrument_code, itype, fp in [
            ("perp", sub.perp_fill_id, sub.perp_venue_namespace,
             sub.perp_venue_fill_id, intent.perp_leg, "BTCUSDT", "perp", perp_fill_price),
            ("spot", sub.spot_fill_id, sub.spot_venue_namespace,
             sub.spot_venue_fill_id, intent.spot_leg, "BTCUSDT-SPOT", "spot", spot_fill_price),
        ]:
            fill_record = FillRecord(
                venue_namespace=vns,
                venue_fill_id=vfid,
                fill_content_hash=vfid + ":" + intent.cost_model_hash[:32],
                portfolio_id=ctx["portfolio_id"],
                strategy_id=ctx["strategy_id"],
                account_id=ctx["account_id"],
                instrument_id=ctx["instrument_id"] if label == "perp" else spot_instrument_id,
                instrument_code=instrument_code,
                instrument_type=itype,
                base_asset_symbol="BTC",
                quote_asset_symbol="USDT",
                side=leg.side.value,
                quantity=leg.quantity,
                price=fp,
                fee_usd=Decimal("0.50"),
                fill_environment="SHADOW",
                filled_at=fill_ts,
            )
            draft = build_trade_journal(fill_record, created_by="paper_runner")
            with conn.cursor() as cur:
                journal_id, was_new = write_and_post_journal(
                    conn, draft,
                    posted_by="paper_runner",
                    asset_id_resolver=asset_id_resolver,
                    instrument_id_resolver=instrument_id_resolver,
                )
                journal_ids[label] = journal_id

                # Reconcile: links fill ↔ journal; trigger fills_reconciled_derive_positions
                # auto-populates position_lots.
                cur.execute(
                    "SELECT trading.reconcile_fill(%s, %s, %s)",
                    (fill_id, journal_id, "paper_runner"),
                )
        conn.commit()

        # ─── Step 9: compute_position_snapshot per leg ─────────────────
        snap_at = fill_ts + timedelta(seconds=1)
        for label, instrument_id in [
            ("perp", ctx["instrument_id"]),
            ("spot", spot_instrument_id),
        ]:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT positions.compute_position_snapshot(
                        %s, %s, %s, %s, 'SHADOW',
                        %s, %s, 'a1.runner.v0', 'paper_runner', '{}'::jsonb
                    )
                    """,
                    (
                        ctx["portfolio_id"], ctx["strategy_id"],
                        ctx["account_id"], instrument_id,
                        snap_at, snap_at,
                    ),
                )
        conn.commit()

    return _submit


def test_a1_paper_runner_one_tick_drives_full_accounted_path(fresh_db):
    """One logical tick through the runner produces a fully accounted
    state in the DB: allocator_run + intents + orders + fills + journals
    + reconciliations + position snapshots.
    """
    # ─── DB setup ───────────────────────────────────────────────────────
    with _connect() as conn, conn.cursor() as cur:
        ctx = _setup_basic_0009(cur)
        spot_instrument_id = _create_btc_spot_instrument(cur, ctx)
        cur.execute(
            "SELECT venue_code FROM registry.venues WHERE id = %s",
            (ctx["venue_id"],),
        )
        venue_namespace = cur.fetchone()[0]
        cur.execute(
            "SELECT instrument_code FROM registry.instruments WHERE id = %s",
            (ctx["instrument_id"],),
        )
        perp_instrument_code = cur.fetchone()[0]
        conn.commit()


    # ─── Configure runner ───────────────────────────────────────────────
    funding_window = _make_funding_window(instrument_code=perp_instrument_code)
    funding_window_hash = _hash_funding_window(funding_window)
    sizing_config = _sizing_for_btcusdt(perp_instrument_code, "BTCUSDT-SPOT")
    cost_model = cost_default()

    # Need a signal_eval reference for the helper's solve_metadata.
    # The runner internally evaluates the same signal; we replicate it
    # here to pass into the closure (the closure could fish it out of
    # the runner via a shared state, but explicit is simpler).
    from strategies.a1_funding.signal.expected_funding import expected_next_funding
    from strategies.a1_funding.signal.evaluate import evaluate_signal
    forecast = expected_next_funding(
        funding_window,
        discount_k=Decimal("1"),
        as_of=datetime(2026, 1, 5, 0, 0, 0, tzinfo=UTC),
    )
    signal_eval = evaluate_signal(
        forecast, cost_model,
        slippage_tier_name="btc_eth_top_tier",
        funding_intervals_per_day=3,
    )

    instrument_id_by_code = {
        perp_instrument_code: ctx["instrument_id"],
        "BTCUSDT-SPOT": spot_instrument_id,
    }

    # Open one connection that the closure will reuse for the duration.
    with _connect() as conn, conn.cursor() as resolver_cur:
        asset_id_resolver, instrument_id_resolver = _make_db_resolvers(resolver_cur)
        submit_callback = _make_submit_callback(
            conn, ctx,
            spot_instrument_id=spot_instrument_id,
            venue_namespace=venue_namespace,
            funding_window_hash=funding_window_hash,
            signal_eval=signal_eval,
            asset_id_resolver=asset_id_resolver,
            instrument_id_resolver=instrument_id_resolver,
            perp_fill_price=Decimal("100000"),
            spot_fill_price=Decimal("100000"),
        )
        current_position_source = _make_current_position_source(
            conn, ctx, instrument_id_by_code,
        )

        runner = A1PaperRunner(
            clock=lambda: datetime(2026, 1, 5, 0, 0, 0, tzinfo=UTC),
            funding_rate_source=lambda code, as_of: _make_funding_window(
                instrument_code=code,
            ),
            submit_callback=submit_callback,
            current_position_source=current_position_source,
            due_events_source=lambda as_of: [],
            funding_event_callback=lambda e: None,
            instruments=[perp_instrument_code],
            sizing_config=sizing_config,
            cost_model=cost_model,
            slippage_tier_name="btc_eth_top_tier",
        )

        # ─── Tick ───────────────────────────────────────────────────────
        result = runner.tick()

    # ─── Assertions on TickResult ───────────────────────────────────────
    assert len(result.outcomes) == 1
    outcome = result.outcomes[0]
    assert outcome.error is None, f"unexpected error: {outcome.error}"
    assert outcome.intent is not None, (
        f"expected intent; got no_intent_reason={outcome.no_intent_reason}"
    )
    assert result.submitted_count == 1

    # ─── Assertions on DB state ─────────────────────────────────────────
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM registry.allocator_runs")
        # _setup_basic_0009 inserts one; runner adds one more.
        assert cur.fetchone()[0] >= 2

        cur.execute("SELECT COUNT(*) FROM registry.target_weights")
        # Setup inserts 1; runner inserts 2 (perp + spot).
        assert cur.fetchone()[0] >= 3

        cur.execute(
            "SELECT COUNT(*) FROM trading.order_intents "
            "WHERE created_by = 'paper_runner'"
        )
        assert cur.fetchone()[0] == 2

        cur.execute(
            "SELECT COUNT(*) FROM trading.orders WHERE created_by = 'paper_runner'"
        )
        assert cur.fetchone()[0] == 2

        cur.execute(
            "SELECT state FROM trading.orders WHERE created_by = 'paper_runner'"
        )
        states = [r[0] for r in cur.fetchall()]
        assert all(s == "filled" for s in states), f"not all filled: {states}"

        cur.execute(
            "SELECT COUNT(*) FROM trading.fills "
            "WHERE order_id IN (SELECT id FROM trading.orders WHERE created_by = 'paper_runner')"
        )
        assert cur.fetchone()[0] == 2

        cur.execute(
            "SELECT COUNT(*) FROM accounting.journals "
            "WHERE journal_type = 'trade' AND status = 'posted' "
            "AND created_by = 'paper_runner'"
        )
        assert cur.fetchone()[0] == 2

        cur.execute(
            "SELECT COUNT(*) FROM trading.fills "
            "WHERE journal_id IS NOT NULL AND reconciled_by = 'paper_runner'"
        )
        assert cur.fetchone()[0] == 2

        cur.execute(
            "SELECT COUNT(*) FROM positions.position_snapshots "
            "WHERE created_by = 'paper_runner'"
        )
        snap_count = cur.fetchone()[0]
        assert snap_count >= 1, (
            f"expected at least one position_snapshot from runner; got {snap_count}"
        )



# ─── Day 15c: multi-tick + funding dispatch idempotency ──────────────────


def test_a1_paper_runner_two_ticks_no_double_exposure(fresh_db):
    """Day 15c Test A: tick 1 establishes position; tick 2 sees position
    via current_position_source and produces no new intent (or a no-op
    sized intent). Total OMS rows do not double after tick 2.
    """
    with _connect() as conn, conn.cursor() as cur:
        ctx = _setup_basic_0009(cur)
        spot_instrument_id = _create_btc_spot_instrument(cur, ctx)
        cur.execute(
            "SELECT venue_code FROM registry.venues WHERE id = %s",
            (ctx["venue_id"],),
        )
        venue_namespace = cur.fetchone()[0]
        cur.execute(
            "SELECT instrument_code FROM registry.instruments WHERE id = %s",
            (ctx["instrument_id"],),
        )
        perp_instrument_code = cur.fetchone()[0]
        conn.commit()

    funding_window = _make_funding_window(instrument_code=perp_instrument_code)
    funding_window_hash = _hash_funding_window(funding_window)
    sizing_config = _sizing_for_btcusdt(perp_instrument_code, "BTCUSDT-SPOT")
    cost_model = cost_default()

    from strategies.a1_funding.signal.expected_funding import expected_next_funding
    from strategies.a1_funding.signal.evaluate import evaluate_signal
    forecast = expected_next_funding(
        funding_window, discount_k=Decimal("1"),
        as_of=datetime(2026, 1, 5, 0, 0, 0, tzinfo=UTC),
    )
    signal_eval = evaluate_signal(
        forecast, cost_model,
        slippage_tier_name="btc_eth_top_tier",
        funding_intervals_per_day=3,
    )

    instrument_id_by_code = {
        perp_instrument_code: ctx["instrument_id"],
        "BTCUSDT-SPOT": spot_instrument_id,
    }

    with _connect() as conn, conn.cursor() as resolver_cur:
        asset_id_resolver, instrument_id_resolver = _make_db_resolvers(resolver_cur)
        submit_callback = _make_submit_callback(
            conn, ctx,
            spot_instrument_id=spot_instrument_id,
            venue_namespace=venue_namespace,
            funding_window_hash=funding_window_hash,
            signal_eval=signal_eval,
            asset_id_resolver=asset_id_resolver,
            instrument_id_resolver=instrument_id_resolver,
            perp_fill_price=Decimal("100000"),
            spot_fill_price=Decimal("100000"),
        )
        current_position_source = _make_current_position_source(
            conn, ctx, instrument_id_by_code,
        )

        # Two distinct clock values so any internal timestamp ordering
        # works (some triggers compare against snapshot_at).
        clocks = iter([
            datetime(2026, 1, 5, 0, 0, 0, tzinfo=UTC),
            datetime(2026, 1, 5, 0, 5, 0, tzinfo=UTC),
        ])

        runner = A1PaperRunner(
            clock=lambda: next(clocks),
            funding_rate_source=lambda code, as_of: _make_funding_window(
                instrument_code=code,
            ),
            submit_callback=submit_callback,
            current_position_source=current_position_source,
            due_events_source=lambda as_of: [],
            funding_event_callback=lambda e: None,
            instruments=[perp_instrument_code],
            sizing_config=sizing_config,
            cost_model=cost_model,
            slippage_tier_name="btc_eth_top_tier",
        )

        result1 = runner.tick()
        assert result1.outcomes[0].error is None
        assert result1.outcomes[0].intent is not None, "tick 1 should establish"
        assert result1.submitted_count == 1

        # ─── After tick 1 ──────────────────────────────────────────────
        with _connect() as audit_conn, audit_conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM trading.fills "
                "WHERE order_id IN (SELECT id FROM trading.orders "
                "                   WHERE created_by = 'paper_runner')"
            )
            fills_after_t1 = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM positions.position_snapshots "
                "WHERE created_by = 'paper_runner'"
            )
            snaps_after_t1 = cur.fetchone()[0]
        assert fills_after_t1 == 2
        assert snaps_after_t1 >= 1

        result2 = runner.tick()
        outcome2 = result2.outcomes[0]
        # tick 2: position now exists. Acceptable outcomes:
        #   - no_intent_reason="signal_flat" (signal flipped flat — won't happen)
        #   - no_intent_reason="current_position_matches_target"
        #   - no_intent_reason="sizer_no_op"
        #   - intent is None for any of the above
        assert outcome2.error is None, f"tick 2 error: {outcome2.error}"
        assert outcome2.intent is None, (
            f"tick 2 expected no intent (already in position); "
            f"got intent={outcome2.intent}, no_intent_reason={outcome2.no_intent_reason}"
        )
        assert result2.submitted_count == 0

        # ─── After tick 2: no new fills, no new snapshots ──────────────
        with _connect() as audit_conn, audit_conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM trading.fills "
                "WHERE order_id IN (SELECT id FROM trading.orders "
                "                   WHERE created_by = 'paper_runner')"
            )
            fills_after_t2 = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM positions.position_snapshots "
                "WHERE created_by = 'paper_runner'"
            )
            snaps_after_t2 = cur.fetchone()[0]
        assert fills_after_t2 == 2, (
            f"tick 2 must not produce new fills; "
            f"after t1={fills_after_t1}, after t2={fills_after_t2}"
        )
        assert snaps_after_t2 == snaps_after_t1, (
            f"tick 2 must not produce new snapshots; "
            f"after t1={snaps_after_t1}, after t2={snaps_after_t2}"
        )


def test_a1_paper_runner_funding_dispatch_three_intervals_then_replay(fresh_db):
    """Day 15c Test B: dispatch 3 due funding events; each posts one
    journal + one funding_payment. Replay returns 0 new events; counts
    remain 3 / 3 (Day 14b's writer idempotency).
    """
    from execution.ledger.fill_journal_writer import (
        FundingEventRecord,
        build_funding_journal,
        write_and_post_funding_journal,
    )

    with _connect() as conn, conn.cursor() as cur:
        ctx = _setup_basic_0009(cur)
        cur.execute(
            "SELECT instrument_code FROM registry.instruments WHERE id = %s",
            (ctx["instrument_id"],),
        )
        perp_instrument_code = cur.fetchone()[0]
        conn.commit()

    base_ts = datetime(2026, 1, 5, 0, 0, 0, tzinfo=UTC)
    intervals = [base_ts + timedelta(hours=8 * i) for i in range(3)]

    # Track which intervals still need posting. After dispatch, this
    # becomes empty so replay returns no events.
    pending_intervals: list[datetime] = list(intervals)

    with _connect() as conn, conn.cursor() as resolver_cur:
        asset_id_resolver, instrument_id_resolver = _make_db_resolvers(resolver_cur)

        def due_source(as_of):
            return [
                FundingDueEvent(
                    instrument_code=perp_instrument_code,
                    funded_at=t,
                    venue_namespace="venue_test",
                    venue_funding_id=f"BTCUSDT-{t.strftime('%Y%m%dT%H%M%S')}",
                )
                for t in pending_intervals
            ]

        def fund_callback(event):
            record = FundingEventRecord(
                venue_namespace=event.venue_namespace,
                venue_funding_id=event.venue_funding_id,
                portfolio_id=ctx["portfolio_id"],
                strategy_id=ctx["strategy_id"],
                account_id=ctx["account_id"],
                instrument_id=ctx["instrument_id"],
                instrument_code=perp_instrument_code,
                quote_asset_symbol="USDT",
                funding_rate=Decimal("0.0001"),
                position_size=Decimal("-0.01"),
                amount_usd=Decimal("0.05"),
                direction="received",
                funded_at=event.funded_at,
                funding_environment="SHADOW",
            )
            draft = build_funding_journal(record, created_by="paper_runner")
            write_and_post_funding_journal(
                conn, draft, record,
                posted_by="paper_runner",
                asset_id_resolver=asset_id_resolver,
                instrument_id_resolver=instrument_id_resolver,
            )
            conn.commit()
            # Mark this interval as processed so replay returns no events.
            pending_intervals.remove(event.funded_at)

        runner = A1PaperRunner(
            clock=lambda: base_ts + timedelta(hours=24),
            funding_rate_source=lambda c, t: [],
            submit_callback=lambda i: None,
            current_position_source=lambda c: Decimal("0"),
            due_events_source=due_source,
            funding_event_callback=fund_callback,
            instruments=[perp_instrument_code],
            sizing_config=_sizing_for_btcusdt(perp_instrument_code, "BTCUSDT-SPOT"),
            cost_model=cost_default(),
            slippage_tier_name="btc_eth_top_tier",
        )

        # ─── First dispatch ────────────────────────────────────────────
        result1 = runner.dispatch_due_funding_events()
        assert result1.events_dispatched == 3
        assert result1.error_count == 0

        with _connect() as audit_conn, audit_conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM accounting.funding_payments "
                "WHERE source_type = 'funding_event'"
            )
            payments_after_first = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM accounting.journals "
                "WHERE journal_type = 'funding' AND status = 'posted'"
            )
            journals_after_first = cur.fetchone()[0]
        assert payments_after_first == 3
        assert journals_after_first == 3

        # ─── Replay ────────────────────────────────────────────────────
        # All intervals were popped from pending_intervals during dispatch,
        # so due_source now returns []. This simulates the production
        # path where the DB query for "intervals lacking a payment" returns
        # nothing once everything is posted.
        result2 = runner.dispatch_due_funding_events()
        assert result2.events == ()
        assert result2.events_dispatched == 0

        with _connect() as audit_conn, audit_conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM accounting.funding_payments "
                "WHERE source_type = 'funding_event'"
            )
            payments_after_replay = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM accounting.journals "
                "WHERE journal_type = 'funding' AND status = 'posted'"
            )
            journals_after_replay = cur.fetchone()[0]
        assert payments_after_replay == 3
        assert journals_after_replay == 3
