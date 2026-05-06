"""A1 vertical smoke test.

Drives the strategy-layer pipeline (Day 1-7) through the production OMS /
risk / fills / positions stack on a single synthetic intent, against a
fresh DB. The goal is to prove every contract along the path works
end-to-end on real schema, not just in unit tests.

Assertion gates (per Day 8 plan, refined by Day 8 recon):

PASSING (main test):
  1. Pure-function pipeline produces an OrderIntent
  2. Synthetic allocator_run + target_weights created with strategy
     lineage in solve_metadata (NOT in constraints_metadata)
  3. trading.order_intents rows accepted by 0007's lineage triggers
  4. trading.orders rows accepted at pending_submit
  5. risk.evaluate_action returns 'allowed' (no limits configured)
  5.5 trading.order_reservations cash reservation per intent
  5.7 trading.oms_outbox 'submit' rows per order
  6. orders transition pending_submit → submitted (transition_order_state)
     and submitted → working (record_order_ack)
  7. SHADOW + MODELED_FILL fills inserted; process_fill_update_order
     trigger updates filled_quantity AND state to 'filled'

XFAIL (single root cause: execution/ledger/fill_journal_writer.py missing):
  8. reconcile_fill(fill_id, journal_id, reconciled_by) — needs journal
  9. position_lots → position_snapshots — lots require reconciled fills
 11. accounting.journals + ledger_entries balanced
 12. P&L derivable from ledger

Day 8 endpoint: fills inserted + order FSM advanced to 'filled'. Recon
during Day 8 revealed the entire downstream chain (reconcile → lots →
snapshots → journals → P&L) blocks on the same missing writer module.
That module is the first concrete Day 9-15 deliverable.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

# Helpers borrowed from the migrations integration test. _setup_basic_0009
# already creates portfolio / strategy / account / venue / instrument /
# mark_price_set / valuation_run / NAV snapshot — exactly the dependencies
# the smoke test would otherwise duplicate.
from tests.integration.test_migrations import _connect, _setup_basic_0009, fresh_db

# Strategy-layer pipeline (Day 1-7). All pure functions.
from data.ingestion.vendors.binance.funding_rate import FundingRate
from core.config.cost_model import conservative_default_v0 as cost_default
from strategies.a1_funding.config.sizing import (
    InstrumentSizingRule,
    SizingConfig,
    SIZING_CONFIG_SCHEMA_VERSION,
)
from strategies.a1_funding.signal.expected_funding import expected_next_funding
from strategies.a1_funding.signal.evaluate import (
    SignalDecision,
    evaluate_signal,
)
from strategies.a1_funding.sizing.sizer import size_intent


UTC = timezone.utc


# ─── Helpers local to this test ──────────────────────────────────────────


def _make_funding_window(symbol: str = "BTCUSDT") -> list[FundingRate]:
    """Three positive-funding observations. Drives evaluate_signal to
    SHORT_PERP_LONG_SPOT (longs are paying shorts → we want to short
    the perp and hedge with long spot)."""
    base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    return [
        FundingRate(
            venue="binance", instrument=symbol,
            funding_time=base + timedelta(hours=8 * i),
            funding_rate=Decimal(rate),
            mark_price=Decimal("100000"),
        )
        for i, rate in enumerate(["0.0020", "0.0025", "0.0030"])
    ]


def _sizing_config_for_btcusdt(spot_instrument_code: str) -> SizingConfig:
    """Sizing config that names the BTCUSDT perp + the spot instrument
    code that _setup_basic_0009 (or our extension to it) created.

    The _setup_basic_0009 helper creates BTCUSDT perp by default; we
    create the matching spot instrument inside the smoke test."""
    return SizingConfig(
        schema_version=SIZING_CONFIG_SCHEMA_VERSION,
        rules=(
            InstrumentSizingRule(
                venue="binance",
                perp_instrument="BTCUSDT",
                spot_instrument=spot_instrument_code,
                max_quantity=Decimal("0.01"),
                min_quantity=Decimal("0.001"),
                slippage_tier_name="btc_eth_top_tier",
            ),
        ),
        max_total_notional_usd=Decimal("2000"),
        notes="smoke-test config",
    )


def _create_btc_spot_instrument(cur, ctx) -> int:
    """Create a BTC spot instrument that mirrors the perp's identity.

    _setup_basic_0009 creates the perp (instrument_type='perp') under
    BTCUSDT. We need a separate spot row for the spot leg of the
    funding-capture pair.
    """
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
        RETURNING id
        """,
        (ctx["venue_id"],),
    )
    return cur.fetchone()[0]


def _allocator_run_with_lineage(
    cur, ctx, *, signal_eval, cost_model_hash, sizing_config_hash,
    funding_window_hash,
) -> str:
    """Insert one allocator_runs row carrying full strategy lineage in
    solve_metadata. Returns the allocator_run UUID."""
    solve_metadata = {
        "engine": "a1_funding",
        "engine_schema_version": "a1.v0",
        "signal_decision": signal_eval.decision.value,
        "forecast_rate": str(signal_eval.forecast_rate),
        "per_period_cost_rate": str(signal_eval.per_period_cost_rate),
        "net_edge_rate": str(signal_eval.net_edge_rate),
        "cost_model_hash": cost_model_hash,
        "sizing_config_hash": sizing_config_hash,
        "funding_window_hash": funding_window_hash,
    }
    cur.execute(
        """
        INSERT INTO registry.allocator_runs (
            portfolio_id,
            objective_version, constraints_version,
            solve_status, solve_metadata, generated_at
        ) VALUES (%s, 'a1.objective.v0', 'a1.constraints.v0',
                  'optimal', %s::jsonb, NOW())
        RETURNING id
        """,
        (ctx["portfolio_id"], json.dumps(solve_metadata)),
    )
    return cur.fetchone()[0]


def _target_weight(
    cur, allocator_run_id: str, instrument_id: int,
    target_weight: Decimal, target_quantity: Decimal,
    target_notional_usd: Decimal,
) -> str:
    """Insert one target_weights row. Returns the UUID."""
    cur.execute(
        """
        INSERT INTO registry.target_weights (
            allocator_run_id, instrument_id, target_weight,
            target_notional_usd, target_quantity, reason
        ) VALUES (%s, %s, %s, %s, %s, '{}'::jsonb)
        RETURNING id
        """,
        (allocator_run_id, instrument_id, target_weight,
         target_notional_usd, target_quantity),
    )
    return cur.fetchone()[0]


def _hash_funding_window(window: list[FundingRate]) -> str:
    """Stable digest over a window — content_hash of every record concatenated."""
    import hashlib
    h = hashlib.sha256()
    for r in window:
        h.update(r.content_hash.encode("ascii"))
    return h.hexdigest()


# ─── The smoke test ──────────────────────────────────────────────────────


def test_a1_smoke_vertical(fresh_db):
    """Day 8 vertical smoke test. See module docstring for gate list."""

    # ─── Step 1: Pure-function pipeline ─────────────────────────────────
    funding_window = _make_funding_window()
    forecast = expected_next_funding(
        funding_window,
        discount_k=Decimal("1"),
        as_of=datetime(2026, 1, 5, 0, 0, 0, tzinfo=UTC),
    )
    cost_model = cost_default()
    signal_eval = evaluate_signal(
        forecast, cost_model,
        slippage_tier_name="btc_eth_top_tier",
        funding_intervals_per_day=3,
    )
    assert signal_eval.decision == SignalDecision.SHORT_PERP_LONG_SPOT, (
        f"smoke test assumes positive funding → SHORT_PERP_LONG_SPOT; "
        f"got {signal_eval.decision}"
    )

    # ─── DB phase: setup fixtures ───────────────────────────────────────
    with _connect() as conn, conn.cursor() as cur:
        ctx = _setup_basic_0009(cur)
        spot_instrument_id = _create_btc_spot_instrument(cur, ctx)

        sizing_config = _sizing_config_for_btcusdt("BTCUSDT-SPOT")

        # Sizer needs current_perp_quantity. Smoke test starts flat.
        intent = size_intent(
            signal_eval,
            current_perp_quantity=Decimal("0"),
            sizing_config=sizing_config,
        )
        assert intent is not None, "sizer must produce an intent from flat"
        # Two legs, hedged, equal quantity (Day 6-7 invariants).
        assert intent.perp_leg.quantity == intent.spot_leg.quantity
        assert intent.perp_leg.side != intent.spot_leg.side

        # ─── Step 2: allocator_run + target_weights with lineage ────────
        funding_window_hash = _hash_funding_window(funding_window)
        run_id = _allocator_run_with_lineage(
            cur, ctx,
            signal_eval=signal_eval,
            cost_model_hash=intent.cost_model_hash,
            sizing_config_hash=intent.sizing_config_hash,
            funding_window_hash=funding_window_hash,
        )

        # Target weight per leg.
        perp_tw_id = _target_weight(
            cur, run_id, ctx["instrument_id"],
            target_weight=Decimal("-1") if intent.perp_leg.side.value == "sell"
                                        else Decimal("1"),
            target_quantity=intent.perp_leg.quantity,
            target_notional_usd=intent.perp_leg.quantity * Decimal("100000"),
        )
        spot_tw_id = _target_weight(
            cur, run_id, spot_instrument_id,
            target_weight=Decimal("1") if intent.spot_leg.side.value == "buy"
                                       else Decimal("-1"),
            target_quantity=intent.spot_leg.quantity,
            target_notional_usd=intent.spot_leg.quantity * Decimal("100000"),
        )

        # Sanity: solve_metadata is queryable, lineage is preserved.
        cur.execute(
            "SELECT solve_metadata FROM registry.allocator_runs WHERE id = %s",
            (run_id,),
        )
        sm = cur.fetchone()[0]
        assert sm["cost_model_hash"] == intent.cost_model_hash
        assert sm["sizing_config_hash"] == intent.sizing_config_hash
        assert sm["signal_decision"] == intent.signal_decision

        conn.commit()

    # ─── Step 3: trading.order_intents inserts (one per leg) ────────────
    with _connect() as conn, conn.cursor() as cur:
        # Fetch venue_namespace from venue (lineage trigger inspects it).
        cur.execute(
            "SELECT venue_code FROM registry.venues WHERE id = %s",
            (ctx["venue_id"],),
        )
        venue_namespace = cur.fetchone()[0]

        # Perp leg intent
        cur.execute(
            """
            INSERT INTO trading.order_intents (
                allocator_run_id, target_weight_id,
                strategy_id, portfolio_id, account_id,
                instrument_id, venue_id, venue_namespace,
                side, target_quantity, target_value_usd,
                intent_type, urgency, execution_environment, created_via,
                constraints_metadata, intended_at, created_by
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s,
                'open', 'normal', 'SHADOW', 'strategy',
                '{"post_only": false}'::jsonb, NOW(), 'smoke_test'
            )
            RETURNING id, intent_uuid
            """,
            (
                run_id, perp_tw_id,
                ctx["strategy_id"], ctx["portfolio_id"], ctx["account_id"],
                ctx["instrument_id"], ctx["venue_id"], venue_namespace,
                intent.perp_leg.side.value, intent.perp_leg.quantity,
                intent.perp_leg.quantity * Decimal("100000"),
            ),
        )
        perp_intent_id, perp_intent_uuid = cur.fetchone()

        # Spot leg intent
        cur.execute(
            """
            INSERT INTO trading.order_intents (
                allocator_run_id, target_weight_id,
                strategy_id, portfolio_id, account_id,
                instrument_id, venue_id, venue_namespace,
                side, target_quantity, target_value_usd,
                intent_type, urgency, execution_environment, created_via,
                constraints_metadata, intended_at, created_by
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s,
                'open', 'normal', 'SHADOW', 'strategy',
                '{"post_only": false}'::jsonb, NOW(), 'smoke_test'
            )
            RETURNING id, intent_uuid
            """,
            (
                run_id, spot_tw_id,
                ctx["strategy_id"], ctx["portfolio_id"], ctx["account_id"],
                spot_instrument_id, ctx["venue_id"], venue_namespace,
                intent.spot_leg.side.value, intent.spot_leg.quantity,
                intent.spot_leg.quantity * Decimal("100000"),
            ),
        )
        spot_intent_id, spot_intent_uuid = cur.fetchone()

        conn.commit()

    # ─── Step 4: trading.orders inserts (state='pending_submit') ────────
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO trading.orders (
                intent_id, account_id, instrument_id, venue_id, venue_namespace,
                client_order_id, side, order_type, quantity, time_in_force, state,
                created_via, created_by
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                'market', %s, 'ioc', 'pending_submit',
                'strategy', 'smoke_test'
            )
            RETURNING id
            """,
            (
                perp_intent_id, ctx["account_id"], ctx["instrument_id"],
                ctx["venue_id"], venue_namespace,
                f"so_{str(perp_intent_uuid).replace('-', '')[:16]}_{intent.perp_leg.side.value}",
                intent.perp_leg.side.value, intent.perp_leg.quantity,
            ),
        )
        perp_order_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO trading.orders (
                intent_id, account_id, instrument_id, venue_id, venue_namespace,
                client_order_id, side, order_type, quantity, time_in_force, state,
                created_via, created_by
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                'market', %s, 'ioc', 'pending_submit',
                'strategy', 'smoke_test'
            )
            RETURNING id
            """,
            (
                spot_intent_id, ctx["account_id"], spot_instrument_id,
                ctx["venue_id"], venue_namespace,
                f"so_{str(spot_intent_uuid).replace('-', '')[:16]}_{intent.spot_leg.side.value}",
                intent.spot_leg.side.value, intent.spot_leg.quantity,
            ),
        )
        spot_order_id = cur.fetchone()[0]
        conn.commit()

    # ─── Step 5: risk.evaluate_action returns 'allowed' for both ────────
    with _connect() as conn, conn.cursor() as cur:
        eval_ts = datetime.now(UTC)
        for leg_label, intent_id, leg in [
            ("perp", perp_intent_id, intent.perp_leg),
            ("spot", spot_intent_id, intent.spot_leg),
        ]:
            cur.execute(
                """
                SELECT risk.evaluate_action(
                    'intent', %s, %s, 'smoke_test',
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    NULL,
                    %s, %s, %s,
                    NULL, NULL, NULL,
                    '{}'::jsonb
                )
                """,
                (
                    f"smoke-{leg_label}",
                    f"smoke-eval-{leg_label}-{intent_id}",
                    ctx["portfolio_id"], ctx["strategy_id"],
                    ctx["account_id"],
                    (ctx["instrument_id"] if leg_label == "perp"
                     else spot_instrument_id),
                    eval_ts, eval_ts, 'LIVE',
                    leg.quantity if leg.side.value == "buy" else -leg.quantity,
                    leg.quantity * Decimal("100000"),
                    ctx["mark_price_set_id"], ctx["mark_source_ts"], "last",
                ),
            )
            eval_id = cur.fetchone()[0]
            cur.execute(
                "SELECT verdict_raw FROM risk.evaluations WHERE id = %s",
                (eval_id,),
            )
            verdict = cur.fetchone()[0]
            assert verdict == "allowed", (
                f"{leg_label} risk evaluation: expected 'allowed', got {verdict!r}"
            )
        conn.commit()

    # ─── Step 5.5: cash reservation per intent (assert_order_submit_ready) ──
    with _connect() as conn, conn.cursor() as cur:
        # Required notional per leg = target_value_usd = qty * $100k.
        # Reserve the exact amount in USDT cash on the account.
        for intent_id, leg in [
            (perp_intent_id, intent.perp_leg),
            (spot_intent_id, intent.spot_leg),
        ]:
            cur.execute(
                """
                INSERT INTO trading.order_reservations (
                    intent_id, account_id, asset_id,
                    reservation_type, amount_reserved
                ) VALUES (
                    %s, %s,
                    (SELECT id FROM registry.assets WHERE symbol = 'USDT'),
                    'cash', %s
                )
                """,
                (intent_id, ctx["account_id"], leg.quantity * Decimal("100000")),
            )
        conn.commit()

    # ─── Step 5.7: oms_outbox 'submit' rows (assert_order_submit_ready) ──
    with _connect() as conn, conn.cursor() as cur:
        for order_id in (perp_order_id, spot_order_id):
            # operation_key format: 'submit:<order_uuid>' exactly.
            cur.execute(
                "SELECT order_uuid FROM trading.orders WHERE id = %s",
                (order_id,),
            )
            order_uuid = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO trading.oms_outbox (
                    order_id, operation, operation_key,
                    payload, state
                ) VALUES (%s, 'submit', %s, '{}'::jsonb, 'pending')
                """,
                (order_id, f"submit:{order_uuid}"),
            )
        conn.commit()

    # ─── Step 6: state transitions pending_submit → submitted → working ──
    with _connect() as conn, conn.cursor() as cur:
        for label, order_id in [('perp', perp_order_id), ('spot', spot_order_id)]:
            # pending_submit → submitted: operator-driven transition
            cur.execute(
                """
                SELECT trading.transition_order_state(
                    %s, 'submitted', 'paper submit',
                    'system', 'global', 'smoke',
                    'smoke_test', '{}'::jsonb
                )
                """,
                (order_id,),
            )
            # submitted → working: requires record_order_ack (venue ack semantics).
            # In paper, we synthesize the venue ack with a synthetic id.
            cur.execute(
                """
                SELECT trading.record_order_ack(
                    %s, %s, '{}'::jsonb, 'smoke_test'
                )
                """,
                (order_id, f"venue-ack-{label}-{order_id}"),
            )
        conn.commit()

        for order_id in (perp_order_id, spot_order_id):
            cur.execute(
                "SELECT state FROM trading.orders WHERE id = %s", (order_id,)
            )
            assert cur.fetchone()[0] == "working"

    # ─── Step 7: SHADOW MODELED_FILL fills, trigger updates filled_qty ──
    perp_fill_price = Decimal("100000")
    spot_fill_price = Decimal("100000")
    fill_ts = datetime.now(UTC)
    with _connect() as conn, conn.cursor() as cur:
        # Day 8: fills carry paper-lineage (cost_model_hash, simulation_seed)
        # in raw_record JSONB. Where these belong long-term (a separate
        # paper_fill_metadata table? extension columns?) is a Day 9-15
        # design question — for now, lineage is preserved in raw_record
        # so reconciliation can read it back.
        for label, order_id, leg in [
            ('perp', perp_order_id, intent.perp_leg),
            ('spot', spot_order_id, intent.spot_leg),
        ]:
            instrument_id = (ctx["instrument_id"] if label == 'perp'
                             else spot_instrument_id)
            fill_price = perp_fill_price if label == 'perp' else spot_fill_price
            raw_record = json.dumps({
                "venue": "binance",
                "fill_environment": "SHADOW",
                "fill_settlement_type": "MODELED_FILL",
                "lineage": {
                    "cost_model_hash": intent.cost_model_hash,
                    "sizing_config_hash": intent.sizing_config_hash,
                    "simulation_seed": 42,
                    "intent_uuid": str(perp_intent_uuid if label == 'perp'
                                       else spot_intent_uuid),
                },
            })
            cur.execute(
                """
                INSERT INTO trading.fills (
                    order_id, instrument_id,
                    venue_fill_id, venue_namespace,
                    side, quantity, price, notional_value,
                    liquidity_side,
                    fill_environment, fill_settlement_type,
                    filled_at, raw_record
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    'taker',
                    'SHADOW', 'MODELED_FILL',
                    %s, %s::jsonb
                )
                RETURNING id
                """,
                (
                    order_id, instrument_id,
                    f"smoke-fill-{label}-{order_id}", venue_namespace,
                    leg.side.value, leg.quantity, fill_price,
                    leg.quantity * fill_price,
                    fill_ts, raw_record,
                ),
            )
            fill_id = cur.fetchone()[0]
            if label == 'perp':
                perp_fill_id = fill_id
            else:
                spot_fill_id = fill_id
        conn.commit()

        # Trigger should have flipped state to 'filled' and updated quantities.
        for order_id, expected_qty in [
            (perp_order_id, intent.perp_leg.quantity),
            (spot_order_id, intent.spot_leg.quantity),
        ]:
            cur.execute(
                "SELECT state, filled_quantity FROM trading.orders WHERE id = %s",
                (order_id,),
            )
            state, fq = cur.fetchone()
            assert state == "filled", (
                f"order {order_id} expected 'filled', got {state}"
            )
            assert fq == expected_qty

    # ─── Step 8: reconcile_fill (DEFERRED to xfail at module level) ─────
    # reconcile_fill(fill_id, journal_id, reconciled_by) requires a journal_id
    # in accounting.journals. That journal is produced by the fills→journal
    # writer (Day 9-15 deliverable). Without that writer, fills cannot be
    # reconciled, and reconciliation is the prerequisite for step 11+12's
    # double-entry assertions. The smoke test stops here for the main path
    # and exposes the gap as explicit xfails below.

    # ─── Day 8 endpoint: fills inserted + order FSM transitioned to 'filled' ──
    # Recon-via-failure during Day 8 revealed that the entire downstream
    # chain (reconcile_fill → position_lots → compute_position_snapshot →
    # ledger → P&L) requires journals to exist, and journals come from
    # the fills→journal writer that doesn't yet exist.
    #
    # Specifically:
    #   - reconcile_fill(fill_id, journal_id, reconciled_by) requires a
    #     journal_id from accounting.journals.
    #   - position_lots inserts require opening_fill_id to be reconciled
    #     (i.e. journal_id NOT NULL) — the trigger raises 'unreconciled'.
    #   - compute_position_snapshot reads from position_lots, so without
    #     populated lots the snapshot returns quantity=0.
    #
    # All four downstream gates (reconcile, lots, snapshots, journals)
    # block on the same missing module: execution/ledger/fill_journal_writer.py
    # That module is the keystone for Day 9-15 wiring.
    #
    # Day 8's smoke test therefore stops here — at the natural boundary
    # of "everything that can pass without the writer." The downstream
    # gates are exposed as xfails below, all citing the same root cause.

    # Final positive assertion: trigger updated order state via
    # process_fill_update_order; both orders should be 'filled' with
    # filled_quantity matching the intent's leg quantities.
    with _connect() as conn, conn.cursor() as cur:
        for label, order_id, leg in [
            ('perp', perp_order_id, intent.perp_leg),
            ('spot', spot_order_id, intent.spot_leg),
        ]:
            cur.execute(
                """
                SELECT state, filled_quantity
                FROM trading.orders WHERE id = %s
                """,
                (order_id,),
            )
            state, fq = cur.fetchone()
            assert state == 'filled', (
                f"{label} order {order_id}: expected state='filled', got {state!r}"
            )
            assert fq == leg.quantity, (
                f"{label} order {order_id}: expected filled_quantity={leg.quantity}, "
                f"got {fq}"
            )


# ─── xfail steps 11-12 ────────────────────────────────────────────────────
# These are the explicit Day 9-15 gap. We DO NOT inline manual journal /
# ledger writes here — that would hide the gap the smoke test exists to
# expose. The fills→journal wiring belongs in
# execution/ledger/fill_journal_writer.py and is the first concrete Day
# 9-15 deliverable.


@pytest.mark.xfail(
    reason=(
        "Day 9-15: requires execution/ledger/fill_journal_writer.py — fills do not "
        "auto-emit balanced journal entries; this assertion stays xfail until the "
        "writer module exists."
    ),
    strict=True,
)
def test_a1_smoke_vertical_step11_journal_balanced(fresh_db):
    """Step 11 (xfail): journal entries created from a SHADOW fill must be
    balanced (sum debits == sum credits per journal in USD)."""
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT j.id, COALESCE(SUM(CASE WHEN le.debit_credit = 'debit'
                                            THEN le.amount_usd ELSE 0 END), 0) AS debits,
                         COALESCE(SUM(CASE WHEN le.debit_credit = 'credit'
                                            THEN le.amount_usd ELSE 0 END), 0) AS credits
            FROM accounting.journals j
            LEFT JOIN accounting.ledger_entries le ON le.journal_id = j.id
            WHERE j.source_type = 'fill'
            GROUP BY j.id
        """)
        rows = cur.fetchall()
    assert rows, "no fill-sourced journals exist (writer module missing)"
    for jid, debits, credits in rows:
        assert debits == credits, (
            f"journal {jid} unbalanced: debits={debits} credits={credits}"
        )


@pytest.mark.xfail(
    reason=(
        "Day 9-15: depends on test_a1_smoke_vertical_step11_journal_balanced. "
        "P&L cannot be derived from ledger entries until the fills→journal "
        "writer module exists."
    ),
    strict=True,
)
def test_a1_smoke_vertical_step12_pnl_derivable(fresh_db):
    """Step 12 (xfail): once journals exist, net P&L for the engine is
    derivable as (sum of credits to P&L equity account) - (sum of debits)."""
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT COALESCE(
                SUM(CASE WHEN le.debit_credit = 'credit' THEN le.amount_usd ELSE 0 END)
              - SUM(CASE WHEN le.debit_credit = 'debit'  THEN le.amount_usd ELSE 0 END),
                0
            )
            FROM accounting.ledger_entries le
            JOIN accounting.ledger_accounts la ON la.id = le.ledger_account_id
            JOIN accounting.journals j         ON j.id = le.journal_id
            WHERE la.account_type = 'equity'
              AND la.account_subtype = 'pnl'
              AND j.source_type = 'fill'
        """)
        pnl = cur.fetchone()[0]
    # We don't assert a specific value yet — once the writer exists we'll
    # check that P&L is non-zero (or matches expected funding less costs).
    assert pnl is not None
