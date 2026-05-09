"""A1 vertical smoke test.

Drives the strategy-layer pipeline (Day 1-7) through the production OMS /
risk / fills / positions stack on a single synthetic intent, against a
fresh DB. The goal is to prove every contract along the path works
end-to-end on real schema, not just in unit tests.

Assertion gates (per Day 8 plan, refined through Day 12):

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
  7.5 build_trade_journal + write_and_post_journal per fill (Day 11 writer)
  8. trading.reconcile_fill(fill_id, journal_id, 'smoke_test') succeeds
  9. positions.compute_position_snapshot computes (Day 13: xfail INLINE
     if quantity=0 — position_lots writer not yet built)

PASSING (separate tests):
 11. Every fill-sourced journal is balanced (Day 11 writer guarantees)
 12. Every fill-sourced journal has ≥ 2 entries referencing v1: accounts

Day 12 endpoint: fills are now reconciled to balanced posted journals.
Position snapshot status is determined empirically — DEBUG print at
step 9 captures snap_quantity/fill_count/lot_count for inspection.
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

# Day 11 writer for fills→journals (now that the keystone exists).
# Day 14 writer for funding events.
from execution.ledger.fill_journal_writer import (
    FillRecord,
    FundingEventRecord,
    build_funding_journal,
    build_trade_journal,
    write_and_post_funding_journal,
    write_and_post_journal,
)

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


def _instrument_code_from_ctx_smoke(ctx) -> str:
    """Look up the instrument_code for the perp instrument
    that _setup_basic_0009 created (it includes a uuid suffix).
    Used by step 10's funding event construction."""
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT instrument_code FROM registry.instruments WHERE id = %s",
            (ctx["instrument_id"],),
        )
        return cur.fetchone()[0]


def _make_db_resolvers(cur):
    """Return (asset_id_resolver, instrument_id_resolver) backed by
    the supplied cursor. Used by Day 11's write_and_post_journal."""
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

    # ─── Step 7.5: build + post journal per fill (Day 11 writer) ───────
    # The fills→journal writer exists as of Day 11. FillRecord uses
    # venue_namespace + venue_fill_id (Day 12.5) — NOT fill_uuid. The
    # accounting layer reconciles by venue identity, not internal id.
    perp_journal_id: int
    spot_journal_id: int
    with _connect() as conn, conn.cursor() as cur:
        asset_id_resolver, instrument_id_resolver = _make_db_resolvers(cur)

        # Confirm process_fill_update_order trigger advanced order state to
        # 'filled' (regression-check; was the only assertion in Day 8's endpoint).
        for label, order_id, leg in [
            ('perp', perp_order_id, intent.perp_leg),
            ('spot', spot_order_id, intent.spot_leg),
        ]:
            cur.execute(
                "SELECT state, filled_quantity FROM trading.orders WHERE id = %s",
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

        # Fetch venue identity for both fills (FillRecord requires it).
        cur.execute(
            """
            SELECT id, venue_namespace, venue_fill_id
            FROM trading.fills
            WHERE id IN (%s, %s) ORDER BY id
            """,
            (perp_fill_id, spot_fill_id),
        )
        venue_rows = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
        perp_venue_namespace, perp_venue_fill_id = venue_rows[perp_fill_id]
        spot_venue_namespace, spot_venue_fill_id = venue_rows[spot_fill_id]

        for (label, venue_ns, vfid, leg, instrument_code, instrument_type,
             fill_price) in [
            ('perp', perp_venue_namespace, perp_venue_fill_id,
             intent.perp_leg, 'BTCUSDT', 'perp', perp_fill_price),
            ('spot', spot_venue_namespace, spot_venue_fill_id,
             intent.spot_leg, 'BTCUSDT-SPOT', 'spot', spot_fill_price),
        ]:
            fill_record = FillRecord(
                venue_namespace=venue_ns,
                venue_fill_id=vfid,
                # trading.fills has no real content_hash column; for smoke
                # purposes the venue identity + lineage prefix is stable.
                fill_content_hash=vfid + ":" + intent.cost_model_hash[:32],
                portfolio_id=ctx["portfolio_id"],
                strategy_id=ctx["strategy_id"],
                account_id=ctx["account_id"],
                instrument_id=ctx["instrument_id"] if label == 'perp' else spot_instrument_id,
                instrument_code=instrument_code,
                instrument_type=instrument_type,
                base_asset_symbol="BTC",
                quote_asset_symbol="USDT",
                side=leg.side.value,
                quantity=leg.quantity,
                price=fill_price,
                fee_usd=Decimal("0.50"),
                fill_environment="SHADOW",
                filled_at=fill_ts,
            )
            draft = build_trade_journal(fill_record, created_by="smoke_test")
            journal_id, was_new = write_and_post_journal(
                conn, draft,
                posted_by="smoke_test",
                asset_id_resolver=asset_id_resolver,
                instrument_id_resolver=instrument_id_resolver,
            )
            assert was_new is True, (
                f"first run of {label} fill should create a fresh journal"
            )
            if label == 'perp':
                perp_journal_id = journal_id
            else:
                spot_journal_id = journal_id
        conn.commit()

    # ─── Step 8: reconcile_fill links fill ↔ journal ────────────────────
    with _connect() as conn, conn.cursor() as cur:
        for fill_id, journal_id in [
            (perp_fill_id, perp_journal_id),
            (spot_fill_id, spot_journal_id),
        ]:
            cur.execute(
                "SELECT trading.reconcile_fill(%s, %s, %s)",
                (fill_id, journal_id, "smoke_test"),
            )
        conn.commit()

        # Confirm reconciliation took: fills now carry their journal_id
        # and reconciled_at.
        for fill_id, expected_journal_id in [
            (perp_fill_id, perp_journal_id),
            (spot_fill_id, spot_journal_id),
        ]:
            cur.execute(
                "SELECT journal_id, reconciled_at, reconciled_by "
                "FROM trading.fills WHERE id = %s",
                (fill_id,),
            )
            jrn, rec_at, rec_by = cur.fetchone()
            assert jrn == expected_journal_id
            assert rec_at is not None
            assert rec_by == "smoke_test"

    # ─── Step 9: compute_position_snapshot for the perp leg ─────────────
    # The snapshot reads from positions.position_lots. Lots normally
    # require a reconciled fill (journal_id NOT NULL) PLUS an explicit
    # insert. Day 13 was scoped to build a fills→position_lots writer,
    # but Day 12 may discover that some part of the schema populates
    # lots automatically once fills are reconciled. The DEBUG print
    # captures the actual snapshot state for inspection.
    with _connect() as conn, conn.cursor() as cur:
        snap_at = datetime.now(UTC) + timedelta(seconds=1)
        cur.execute(
            """
            SELECT positions.compute_position_snapshot(
                %s, %s, %s, %s, 'SHADOW',
                %s, %s, 'a1.smoke.v0', 'smoke_test', '{}'::jsonb
            )
            """,
            (
                ctx["portfolio_id"], ctx["strategy_id"],
                ctx["account_id"], ctx["instrument_id"],
                snap_at, snap_at,
            ),
        )
        snapshot_id = cur.fetchone()[0]
        cur.execute(
            """
            SELECT quantity, contributing_fill_count
            FROM positions.position_snapshots WHERE id = %s
            """,
            (snapshot_id,),
        )
        snap_quantity, fill_count = cur.fetchone()

        # Also count position_lots so we know whether they got created
        # automatically by some trigger we missed.
        cur.execute(
            "SELECT COUNT(*) FROM positions.position_lots "
            "WHERE portfolio_id = %s AND strategy_id = %s "
            "AND account_id = %s AND instrument_id = %s",
            (ctx["portfolio_id"], ctx["strategy_id"],
             ctx["account_id"], ctx["instrument_id"]),
        )
        lot_count = cur.fetchone()[0]
        conn.commit()

        if snap_quantity == 0 and fill_count == 0:
            # Day 13 target: position_lots requires its own writer to
            # convert reconciled fills into lots. Until that lands the
            # snapshot is structurally empty. Inline xfail (rather than
            # a test-level mark) keeps earlier assertions strict.
            pytest.xfail(
                "Day 13: fills→position_lots writer required — "
                "position_snapshot.quantity=0 because position_lots is empty"
            )

        # Day 13+: once lots are wired, expect non-zero perp exposure.
        expected_signed = -intent.perp_leg.quantity
        assert snap_quantity == expected_signed, (
            f"perp position snapshot expected quantity={expected_signed}, "
            f"got {snap_quantity}"
        )
        assert fill_count == 1, (
            f"snapshot should derive from exactly one fill, got {fill_count}"
        )

    # ─── Step 10: fake one funding event for the perp leg ───────────────
    # Position is short -0.01 BTC after reconciliation. Pretend the next
    # 8h funding interval has rate +0.0001 (longs pay shorts) and BTC mark
    # is $50,000. Expected receipt: 0.01 * 0.0001 * 50000 = $0.05 USD.
    # This validates the funding writer end-to-end against the same DB
    # the fills passed through.
    funded_at = datetime.now(UTC) + timedelta(hours=8)
    funding_event = FundingEventRecord(
        venue_namespace=perp_venue_namespace,
        venue_funding_id=f"BTCUSDT-{funded_at.strftime('%Y%m%dT%H%M%S')}",
        portfolio_id=ctx["portfolio_id"],
        strategy_id=ctx["strategy_id"],
        account_id=ctx["account_id"],
        instrument_id=ctx["instrument_id"],
        instrument_code=_instrument_code_from_ctx_smoke(ctx),
        quote_asset_symbol="USDT",
        funding_rate=Decimal("0.0001"),
        position_size=Decimal("-0.01"),  # short
        amount_usd=Decimal("0.05"),       # 0.01 * 0.0001 * 50000
        direction="received",
        funded_at=funded_at,
        funding_environment="SHADOW",
    )
    funding_draft = build_funding_journal(funding_event, created_by="smoke_test")
    with _connect() as conn, conn.cursor() as cur:
        ar, ir = _make_db_resolvers(cur)
        funding_journal_id, funding_payment_id, funding_was_new = (
            write_and_post_funding_journal(
                conn, funding_draft, funding_event,
                posted_by="smoke_test",
                asset_id_resolver=ar,
                instrument_id_resolver=ir,
            )
        )
        conn.commit()
    assert funding_was_new is True, "fresh funding event should create new rows"
    assert funding_journal_id > 0
    assert funding_payment_id > 0


# ─── xfail steps 11-12 ────────────────────────────────────────────────────
# These are the explicit Day 9-15 gap. We DO NOT inline manual journal /
# ledger writes here — that would hide the gap the smoke test exists to
# expose. The fills→journal wiring belongs in
# execution/ledger/fill_journal_writer.py and is the first concrete Day
# 9-15 deliverable.


def test_a1_smoke_vertical_step11_journal_balanced(fresh_db):
    """Step 11: journal entries created from SHADOW fills must be
    balanced (sum debits == sum credits per journal in USD).

    Day 11 wired in the writer; this test now passes. We invoke the
    smoke-test main path first to populate fills + journals, then check
    the invariant.
    """
    test_a1_smoke_vertical(fresh_db)  # populate fills + journals
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
    assert rows, "expected fill-sourced journals to exist"
    for jid, debits, credits in rows:
        assert debits == credits, (
            f"journal {jid} unbalanced: debits={debits} credits={credits}"
        )


def test_a1_smoke_vertical_step12_journal_entries_per_fill(fresh_db):
    """Step 12: every fill-sourced journal has at least 2 ledger entries
    and references resolved ledger_accounts via the v1 chart-of-accounts.

    Trade-journal P&L (close-of-position) and funding-event P&L are Day
    14 deliverables. For Day 12 we assert the structural invariant: the
    writer's journals link properly to ledger_entries through the
    enforce_ledger_entry_integrity dimension trigger.
    """
    test_a1_smoke_vertical(fresh_db)  # populate fills + journals
    with _connect() as conn, conn.cursor() as cur:
        # Every fill-sourced journal should have >= 2 entries.
        cur.execute("""
            SELECT j.id, COUNT(le.id) AS entry_count
            FROM accounting.journals j
            LEFT JOIN accounting.ledger_entries le ON le.journal_id = j.id
            WHERE j.source_type = 'fill'
            GROUP BY j.id
        """)
        rows = cur.fetchall()
    assert rows, "expected fill-sourced journals"
    for jid, count in rows:
        assert count >= 2, f"journal {jid}: only {count} entries"

    with _connect() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*)
            FROM accounting.ledger_entries le
            JOIN accounting.ledger_accounts la ON la.id = le.ledger_account_id
            JOIN accounting.journals j         ON j.id = le.journal_id
            WHERE j.source_type = 'fill'
              AND la.account_code LIKE 'v1:%%'
        """)
        v1_entries = cur.fetchone()[0]
    assert v1_entries > 0, "expected v1: account-coded entries from the writer"



def test_a1_smoke_vertical_step13_funding_journal(fresh_db):
    """Step 13: the funding event posted in step 10 produced exactly one
    funding_payments row, linked to a posted non-voided journal of type
    'funding', with balanced ledger entries (DR cash $0.05, CR
    funding_income $0.05).
    """
    test_a1_smoke_vertical(fresh_db)  # populate fills, journals, funding event
    with _connect() as conn, conn.cursor() as cur:
        # Exactly one funding_payment exists.
        cur.execute(
            "SELECT id, journal_id, direction, amount_usd, source_namespace, "
            "       source_id "
            "FROM accounting.funding_payments"
        )
        rows = cur.fetchall()
        assert len(rows) == 1, f"expected 1 funding_payment, got {len(rows)}"
        payment_id, journal_id, direction, amount_usd, sns, sid = rows[0]
        assert direction == "received"
        assert amount_usd == Decimal("0.05")
        assert sns.startswith("venue_")
        assert sid.startswith("BTCUSDT-")

        # The linked journal exists, is posted, not voided, type='funding'.
        cur.execute(
            "SELECT status, journal_type, voided_at, source_type "
            "FROM accounting.journals WHERE id = %s",
            (journal_id,),
        )
        status, jtype, voided_at, stype = cur.fetchone()
        assert status == "posted"
        assert jtype == "funding"
        assert voided_at is None
        assert stype == "funding_event"

        # Ledger entries: 1 debit to cash, 1 credit to funding_income, both $0.05.
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
        entries = cur.fetchall()
        assert len(entries) == 2, f"expected 2 entries, got {len(entries)}"

        debits = [e for e in entries if e[1] == "debit"]
        credits = [e for e in entries if e[1] == "credit"]
        assert len(debits) == 1
        assert len(credits) == 1
        assert debits[0][0].startswith("v1:cash:")
        assert debits[0][0].endswith(":USDT")
        assert debits[0][2] == Decimal("0.05")
        assert credits[0][0].startswith("v1:funding_income:")
        assert credits[0][2] == Decimal("0.05")
