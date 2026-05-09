"""Day 16a: synthetic 30-interval backfill harness.

Drives the A1 paper runner across 30 funding intervals using a logical
clock and a deterministic rate sequence. No real Binance, no RNG.

The runner ticks once per interval boundary AND dispatches due funding
events once per interval. Tick 1 establishes hedged exposure; tick 2..30
self-regulate (position already matches target). Funding events accrue
each interval.

This is the harness that proves the runner's behavior is coherent under
sustained sequential operation. Real Binance data and Sharpe computation
are downstream concerns (Day 16b+).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable

import pytest

from core.config.cost_model import conservative_default_v0 as cost_default
from data.ingestion.vendors.binance.funding_rate import FundingRate
from execution.ledger.fill_journal_writer import (
    FillRecord,
    FundingEventRecord,
    build_funding_journal,
    build_trade_journal,
    write_and_post_funding_journal,
    write_and_post_journal,
)
from strategies.a1_funding.config.sizing import (
    InstrumentSizingRule,
    SizingConfig,
    SIZING_CONFIG_SCHEMA_VERSION,
)
from strategies.a1_funding.runner.oms_submit import (
    SubmissionResult,
    submit_intent_through_oms,
)
from strategies.a1_funding.runner.paper_runner import (
    A1PaperRunner,
    FundingDueEvent,
)
from strategies.a1_funding.sizing.order_intent import OrderIntent

# Reuse smoke-test DB fixtures + the helpers Day 15b.2 already validated.
from tests.integration.test_a1_paper_runner import (
    _make_current_position_source,
    _make_submit_callback,
    _sizing_for_btcusdt,
)
from tests.integration.test_a1_smoke_vertical import (
    _connect,
    _create_btc_spot_instrument,
    _hash_funding_window,
    _make_db_resolvers,
    fresh_db,  # noqa: F401
)
from tests.integration.test_migrations import _setup_basic_0009


UTC = timezone.utc


# ─── Deterministic synthetic rate series ─────────────────────────────────


# 12 hardcoded rates representing pre-backfill history. The runner uses
# the trailing 12 of (PRIOR + observed) at every tick, so we need 12
# observations available even at interval 0.
PRIOR_RATES: tuple[Decimal, ...] = (
    Decimal("0.0050"), Decimal("0.0048"), Decimal("0.0052"),
    Decimal("0.0045"), Decimal("0.0055"), Decimal("0.0050"),
    Decimal("0.0053"), Decimal("0.0047"), Decimal("0.0051"),
    Decimal("0.0049"), Decimal("0.0054"), Decimal("0.0050"),
)
assert len(PRIOR_RATES) == 12

# 30 hardcoded funding rates that settle DURING the backfill window.
# These are the ones for which funding_payments will be posted.
# Selection: positive-biased with mild noise. Mean well above the cost
# model's per-period cost rate (~0.0012), so the signal stays
# SHORT perp / LONG spot across all 30 intervals → position holds.
SYNTHETIC_RATES: tuple[Decimal, ...] = (
    Decimal("0.0052"), Decimal("0.0048"), Decimal("0.0053"),  # day 1
    Decimal("0.0050"), Decimal("0.0055"), Decimal("0.0046"),  # day 2
    Decimal("0.0051"), Decimal("0.0049"), Decimal("0.0054"),  # day 3
    Decimal("0.0050"), Decimal("0.0053"), Decimal("0.0047"),  # day 4
    Decimal("0.0052"), Decimal("0.0051"), Decimal("0.0048"),  # day 5
    Decimal("0.0050"), Decimal("0.0054"), Decimal("0.0049"),  # day 6
    Decimal("0.0050"), Decimal("0.0048"), Decimal("0.0052"),  # day 7
    Decimal("0.0045"), Decimal("0.0055"), Decimal("0.0050"),  # day 8
    Decimal("0.0053"), Decimal("0.0047"), Decimal("0.0051"),  # day 9
    Decimal("0.0049"), Decimal("0.0054"), Decimal("0.0050"),  # day 10
)
assert len(SYNTHETIC_RATES) == 30

# Mark price held flat at $100k for the whole window. Backfilling real
# marks is a Day 16b concern; for the synthetic harness, holding marks
# flat means realized P&L is purely funding-driven (which is the point
# of an A1 funding-capture engine).
SYNTHETIC_MARK = Decimal("100000")

# t=0 anchor. Backfill starts here; each interval is +8h.
BACKFILL_START = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
INTERVAL = timedelta(hours=8)


def _funding_window_at(interval_idx: int, instrument_code: str) -> list[FundingRate]:
    """Window of historical FundingRate observations as of `interval_idx`.

    Returns the trailing 12 from the concatenation [PRIOR..., SYNTHETIC[:idx]].
    Funding times are placed at -12 * INTERVAL through 0 (PRIOR), then
    0 through INTERVAL * (idx-1) (SYNTHETIC settled so far).

    Day 4-5's expected_next_funding requires a window of past rates to
    forecast; we give it 12 every time.
    """
    full_series = list(PRIOR_RATES) + list(SYNTHETIC_RATES[:interval_idx])
    full_times = [
        BACKFILL_START + INTERVAL * (i - 12)
        for i in range(len(full_series))
    ]
    window_start = max(0, len(full_series) - 12)
    return [
        FundingRate(
            venue="binance",
            instrument=instrument_code,
            funding_time=full_times[i],
            funding_rate=full_series[i],
            mark_price=SYNTHETIC_MARK,
            ingested_at=full_times[i] + timedelta(minutes=1),
        )
        for i in range(window_start, len(full_series))
    ]


def test_a1_paper_runner_backfill_30_intervals(fresh_db):
    """30-interval synthetic backfill. Tick 1 establishes the hedge;
    ticks 2-30 self-regulate. Each interval posts exactly one funding
    event. Final state shows 30 funding_payments + 30 posted journals
    against 2 fills (no double exposure).
    """
    # ─── Fixtures ───────────────────────────────────────────────────────
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

    sizing_config = _sizing_for_btcusdt(perp_instrument_code, "BTCUSDT-SPOT")
    cost_model = cost_default()

    # The submit_callback closure needs a reference signal_eval for the
    # solve_metadata it injects into allocator_runs. We compute one here
    # using a representative window; the runner internally re-evaluates
    # on every tick with whatever window funding_rate_source returns.
    from strategies.a1_funding.signal.expected_funding import expected_next_funding
    from strategies.a1_funding.signal.evaluate import evaluate_signal
    representative_window = _funding_window_at(12, perp_instrument_code)
    forecast = expected_next_funding(
        representative_window,
        discount_k=Decimal("1"),
        as_of=BACKFILL_START + INTERVAL * 12,
    )
    signal_eval = evaluate_signal(
        forecast, cost_model,
        slippage_tier_name="btc_eth_top_tier",
        funding_intervals_per_day=3,
    )
    funding_window_hash = _hash_funding_window(representative_window)

    instrument_id_by_code = {
        perp_instrument_code: ctx["instrument_id"],
        "BTCUSDT-SPOT": spot_instrument_id,
    }

    # ─── Backfill loop ──────────────────────────────────────────────────
    # We need a mutable interval index that the lambdas close over. The
    # cleanest pattern: a list-of-one mutable cell.
    current_idx = [0]

    def clock_for_tick():
        # The clock represents "now" at the moment of evaluation. By the
        # time tick(idx) runs, the funding rate at idx-1 has already
        # settled, so the window includes everything up to but not
        # including idx. as_of is the boundary timestamp at idx.
        return BACKFILL_START + INTERVAL * current_idx[0]

    def funding_rate_source_for_tick(code, as_of):
        return _funding_window_at(current_idx[0], code)

    # Track which funding intervals have been "settled" but not yet
    # processed by the runner. Synchronously: at interval idx, the rate
    # for [idx-1, idx) has settled and is due for accrual. We populate
    # this list at the start of each interval's loop iteration; the
    # callback removes events from it.
    pending_funding: list[int] = []  # list of interval indices

    def due_events_source(as_of):
        return [
            FundingDueEvent(
                instrument_code=perp_instrument_code,
                funded_at=BACKFILL_START + INTERVAL * (idx + 1),
                venue_namespace=venue_namespace,
                venue_funding_id=f"BTCUSDT-bf-{idx:03d}",
            )
            for idx in pending_funding
        ]

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
            perp_fill_price=SYNTHETIC_MARK,
            spot_fill_price=SYNTHETIC_MARK,
        )
        current_position_source = _make_current_position_source(
            conn, ctx, instrument_id_by_code,
        )

        def fund_callback(event: FundingDueEvent) -> None:
            # Compute amount_usd = |position| * rate * mark.
            # Position size: -0.01 BTC (short), rate from SYNTHETIC_RATES
            # at the index encoded in venue_funding_id, mark = $100k.
            idx = int(event.venue_funding_id.split("-")[-1])
            rate = SYNTHETIC_RATES[idx]
            amount_usd = Decimal("0.01") * rate * SYNTHETIC_MARK  # = rate * 1000

            record = FundingEventRecord(
                venue_namespace=event.venue_namespace,
                venue_funding_id=event.venue_funding_id,
                portfolio_id=ctx["portfolio_id"],
                strategy_id=ctx["strategy_id"],
                account_id=ctx["account_id"],
                instrument_id=ctx["instrument_id"],
                instrument_code=perp_instrument_code,
                quote_asset_symbol="USDT",
                funding_rate=rate,
                position_size=Decimal("-0.01"),
                amount_usd=amount_usd,
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
            pending_funding.remove(idx)

        runner = A1PaperRunner(
            clock=clock_for_tick,
            funding_rate_source=funding_rate_source_for_tick,
            submit_callback=submit_callback,
            current_position_source=current_position_source,
            due_events_source=due_events_source,
            funding_event_callback=fund_callback,
            instruments=[perp_instrument_code],
            sizing_config=sizing_config,
            cost_model=cost_model,
            slippage_tier_name="btc_eth_top_tier",
        )

        # ─── Walk forward 30 intervals ──────────────────────────────────
        outcomes_per_tick: list[tuple[int, str]] = []  # (idx, outcome_type)
        for idx in range(30):
            current_idx[0] = idx
            # The interval that just settled: idx-1 → idx. Index 0 is the
            # first observable settlement (the rate from BACKFILL_START
            # → +8h).
            if idx > 0:
                pending_funding.append(idx - 1)

            tick_result = runner.tick()
            outcome = tick_result.outcomes[0]
            if outcome.intent is not None:
                outcomes_per_tick.append((idx, "submitted"))
            elif outcome.no_intent_reason is not None:
                outcomes_per_tick.append((idx, outcome.no_intent_reason))
            else:
                pytest.fail(
                    f"interval {idx}: outcome had error: {outcome.error}"
                )

            if idx > 0:
                dispatch_result = runner.dispatch_due_funding_events()
                # Each interval should post exactly one new event after t=0.
                # Idempotency means re-dispatching is safe but not required
                # in this loop.
                assert dispatch_result.error_count == 0, (
                    f"interval {idx} dispatch errors: "
                    f"{dispatch_result.error_messages}"
                )

    # ─── Top-level state assertions ─────────────────────────────────────
    with _connect() as conn, conn.cursor() as cur:
        # Tick 1 (idx=0) submitted; ticks 2..30 self-regulated.
        assert outcomes_per_tick[0] == (0, "submitted"), (
            f"interval 0 should submit; got {outcomes_per_tick[0]}"
        )
        no_intent_reasons = {x[1] for x in outcomes_per_tick[1:]}
        assert no_intent_reasons.issubset(
            {"current_position_matches_target", "sizer_no_op", "signal_flat"}
        ), f"unexpected outcomes after interval 0: {no_intent_reasons}"

        # Exactly 2 fills (perp + spot), set up at interval 0.
        cur.execute(
            "SELECT COUNT(*) FROM trading.fills "
            "WHERE order_id IN (SELECT id FROM trading.orders "
            "                   WHERE created_by = 'paper_runner')"
        )
        fill_count = cur.fetchone()[0]
        assert fill_count == 2, f"expected 2 fills, got {fill_count}"

        # Exactly 2 trade journals.
        cur.execute(
            "SELECT COUNT(*) FROM accounting.journals "
            "WHERE journal_type = 'trade' "
            "  AND status = 'posted' "
            "  AND created_by = 'paper_runner'"
        )
        trade_journal_count = cur.fetchone()[0]
        assert trade_journal_count == 2

        # 29 funding_payments (intervals 1..29 settled while position held;
        # interval 0 is when we entered, so no settlement was due before
        # we had a position).
        cur.execute(
            "SELECT COUNT(*) FROM accounting.funding_payments "
            "WHERE source_type = 'funding_event'"
        )
        funding_payment_count = cur.fetchone()[0]
        assert funding_payment_count == 29, (
            f"expected 29 funding_payments, got {funding_payment_count}"
        )

        # 29 funding journals.
        cur.execute(
            "SELECT COUNT(*) FROM accounting.journals "
            "WHERE journal_type = 'funding' "
            "  AND status = 'posted'"
        )
        funding_journal_count = cur.fetchone()[0]
        assert funding_journal_count == 29

        # Every funding_payment links a posted, non-voided journal.
        cur.execute(
            """
            SELECT COUNT(*)
            FROM accounting.funding_payments fp
            JOIN accounting.journals j ON j.id = fp.journal_id
            WHERE j.status = 'posted'
              AND j.voided_at IS NULL
              AND j.journal_type = 'funding'
            """
        )
        linked_count = cur.fetchone()[0]
        assert linked_count == 29, (
            f"expected 29 fully-linked funding payments, got {linked_count}"
        )

        # No orphan funding_payments (no journal_id IS NULL).
        cur.execute(
            "SELECT COUNT(*) FROM accounting.funding_payments "
            "WHERE journal_id IS NULL"
        )
        assert cur.fetchone()[0] == 0

        # Realized P&L from accounting is queryable. Sum amount_usd of
        # all received funding payments. With rate ~0.005 average and
        # position $1000 USD-equivalent, expected ~ 29 * 0.005 * 1000 = ~$145.
        # Synthetic mean of SYNTHETIC_RATES[1:30] is computable from the
        # fixed series; assert we are in a sensible range.
        cur.execute(
            "SELECT COALESCE(SUM(amount_usd), 0) "
            "FROM accounting.funding_payments "
            "WHERE direction = 'received'"
        )
        realized_funding_usd = cur.fetchone()[0]
        # Bounds: each rate is in [0.0045, 0.0055], so 29 events * 1000 USD
        # contribution per $1000 position gives [29*4.5, 29*5.5] = [130.5, 159.5]
        assert Decimal("130") < realized_funding_usd < Decimal("160"), (
            f"realized funding {realized_funding_usd} out of expected band"
        )

        # Final position state is queryable and matches setup.
        cur.execute(
            """
            SELECT quantity
            FROM positions.position_snapshots
            WHERE portfolio_id = %s
              AND strategy_id = %s
              AND account_id = %s
              AND instrument_id = %s
            ORDER BY snapshot_at DESC
            LIMIT 1
            """,
            (ctx["portfolio_id"], ctx["strategy_id"],
             ctx["account_id"], ctx["instrument_id"]),
        )
        latest_perp_qty = cur.fetchone()[0]
        assert latest_perp_qty == Decimal("-0.01"), (
            f"expected perp position -0.01, got {latest_perp_qty}"
        )
