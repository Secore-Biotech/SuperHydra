"""A1 OMS submit helper.

Extracts the end-to-end OMS path that an A1 intent flows through:
  allocator_run + target_weights  (lineage)
  order_intents                   (one per leg)
  orders                          (pending_submit)
  risk.evaluate_action            (per leg)
  order_reservations              (cash reservation)
  oms_outbox                      (submit operation)
  state transitions               (pending_submit → submitted → working)
  fills                           (SHADOW + MODELED_FILL)

This was previously inlined in the vertical smoke test. The runner
needs the same path, so it lives here. A2/A3 may eventually reuse
parts of this; once that pressure is real, the generic parts (intents,
orders, risk eval, reservations, outbox, FSM transitions) lift into
execution/oms/. For now it stays A1-specific because the lineage
scaffolding (allocator_run with funding-window hash, sizing_config
hash, etc.) is A1-specific.

Caller owns the transaction. The helper opens NO connections of its own;
it expects an open psycopg connection and a single cursor it can drive.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from strategies.a1_funding.sizing.order_intent import OrderIntent


@dataclass(frozen=True)
class SubmissionResult:
    """The handles the caller needs to continue the post-submit pipeline
    (journal posting, reconciliation, snapshot computation, etc.)."""
    allocator_run_id: int
    perp_intent_id: int
    spot_intent_id: int
    perp_intent_uuid: str
    spot_intent_uuid: str
    perp_order_id: int
    spot_order_id: int
    perp_fill_id: int
    spot_fill_id: int
    perp_venue_namespace: str
    spot_venue_namespace: str
    perp_venue_fill_id: str
    spot_venue_fill_id: str


def _allocator_run_with_lineage(
    cur, ctx: dict, *,
    signal_eval, cost_model_hash: str, sizing_config_hash: str,
    funding_window_hash: str,
) -> int:
    """Insert an allocator_run carrying full A1 lineage in solve_metadata."""
    solve_metadata = json.dumps({
        "cost_model_hash": cost_model_hash,
        "sizing_config_hash": sizing_config_hash,
        "funding_window_hash": funding_window_hash,
        "signal_decision": signal_eval.decision.value
            if hasattr(signal_eval.decision, "value") else str(signal_eval.decision),
        "expected_funding_schema_version": signal_eval.expected_funding_schema_version,
        "signal_evaluation_schema_version": signal_eval.schema_version,
    })
    cur.execute(
        """
        INSERT INTO registry.allocator_runs (
            portfolio_id, objective_version, constraints_version,
            solve_status, generated_at, solve_metadata
        )
        VALUES (%s, 'a1.smoke.v0', 'a1.smoke.v0', 'optimal', NOW(), %s::jsonb)
        RETURNING id
        """,
        (ctx["portfolio_id"], solve_metadata),
    )
    return cur.fetchone()[0]


def _target_weight(
    cur, allocator_run_id: int, instrument_id: int, *,
    target_weight: Decimal, target_quantity: Decimal,
    target_notional_usd: Decimal,
) -> int:
    cur.execute(
        """
        INSERT INTO registry.target_weights
            (allocator_run_id, instrument_id, target_weight, reason)
        VALUES (%s, %s, %s, '{}'::jsonb)
        RETURNING id
        """,
        (allocator_run_id, instrument_id, target_weight),
    )
    return cur.fetchone()[0]


def submit_intent_through_oms(
    conn,
    intent: OrderIntent,
    *,
    ctx: dict,
    spot_instrument_id: int,
    venue_namespace: str,
    funding_window_hash: str,
    signal_eval,
    fill_price_perp: Decimal,
    fill_price_spot: Decimal,
    fill_ts: datetime,
    created_by: str = "a1_runner",
) -> SubmissionResult:
    """Drive an A1 OrderIntent end-to-end through the OMS path.

    Sequences: allocator_run + target_weights → order_intents → orders →
    risk.evaluate_action → order_reservations → oms_outbox → state
    transitions → fills.

    Caller owns the transaction. This function does NOT commit; it
    pumps statements through the supplied connection. The caller decides
    when to commit (typically: per phase, or once at the end).

    For paper runs, fills are SHADOW + MODELED_FILL with the supplied
    fill prices and timestamp. The caller controls those — this helper
    does not invent them.

    Returns SubmissionResult containing every id the caller needs to
    drive the post-submit pipeline (journal posting, reconciliation).
    """

    # ─── Step 2: allocator_run + target_weights ─────────────────────────
    with conn.cursor() as cur:
        run_id = _allocator_run_with_lineage(
            cur, ctx,
            signal_eval=signal_eval,
            cost_model_hash=intent.cost_model_hash,
            sizing_config_hash=intent.sizing_config_hash,
            funding_window_hash=funding_window_hash,
        )
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

    # ─── Step 3: order_intents (one per leg) ────────────────────────────
    with conn.cursor() as cur:
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
                '{"post_only": false}'::jsonb, NOW(), %s
            )
            RETURNING id, intent_uuid
            """,
            (
                run_id, perp_tw_id,
                ctx["strategy_id"], ctx["portfolio_id"], ctx["account_id"],
                ctx["instrument_id"], ctx["venue_id"], venue_namespace,
                intent.perp_leg.side.value, intent.perp_leg.quantity,
                intent.perp_leg.quantity * Decimal("100000"),
                created_by,
            ),
        )
        perp_intent_id, perp_intent_uuid = cur.fetchone()

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
                '{"post_only": false}'::jsonb, NOW(), %s
            )
            RETURNING id, intent_uuid
            """,
            (
                run_id, spot_tw_id,
                ctx["strategy_id"], ctx["portfolio_id"], ctx["account_id"],
                spot_instrument_id, ctx["venue_id"], venue_namespace,
                intent.spot_leg.side.value, intent.spot_leg.quantity,
                intent.spot_leg.quantity * Decimal("100000"),
                created_by,
            ),
        )
        spot_intent_id, spot_intent_uuid = cur.fetchone()

    # ─── Step 4: orders at pending_submit ───────────────────────────────
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO trading.orders (
                intent_id, account_id, instrument_id, venue_id, venue_namespace,
                client_order_id, side, order_type, quantity, time_in_force, state,
                created_via, created_by
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                'market', %s, 'ioc', 'pending_submit',
                'strategy', %s
            )
            RETURNING id
            """,
            (
                perp_intent_id, ctx["account_id"], ctx["instrument_id"],
                ctx["venue_id"], venue_namespace,
                f"so_{str(perp_intent_uuid).replace('-', '')[:16]}_{intent.perp_leg.side.value}",
                intent.perp_leg.side.value, intent.perp_leg.quantity,
                created_by,
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
                'strategy', %s
            )
            RETURNING id
            """,
            (
                spot_intent_id, ctx["account_id"], spot_instrument_id,
                ctx["venue_id"], venue_namespace,
                f"so_{str(spot_intent_uuid).replace('-', '')[:16]}_{intent.spot_leg.side.value}",
                intent.spot_leg.side.value, intent.spot_leg.quantity,
                created_by,
            ),
        )
        spot_order_id = cur.fetchone()[0]

    # ─── Step 5: risk.evaluate_action ───────────────────────────────────
    with conn.cursor() as cur:
        eval_ts = datetime.now(timezone.utc)
        for leg_label, intent_id, leg in [
            ("perp", perp_intent_id, intent.perp_leg),
            ("spot", spot_intent_id, intent.spot_leg),
        ]:
            cur.execute(
                """
                SELECT risk.evaluate_action(
                    'intent', %s, %s, %s,
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
                    f"{created_by}-{leg_label}",
                    f"{created_by}-eval-{leg_label}-{intent_id}",
                    created_by,
                    ctx["portfolio_id"], ctx["strategy_id"],
                    ctx["account_id"],
                    (ctx["instrument_id"] if leg_label == "perp"
                     else spot_instrument_id),
                    eval_ts, eval_ts, "LIVE",
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
            if verdict != "allowed":
                raise RuntimeError(
                    f"{leg_label} risk evaluation: expected 'allowed', got {verdict!r}"
                )

    # ─── Step 5.5: cash reservation per intent ──────────────────────────
    with conn.cursor() as cur:
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

    # ─── Step 5.7: oms_outbox 'submit' rows ─────────────────────────────
    with conn.cursor() as cur:
        for order_id in (perp_order_id, spot_order_id):
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

    # ─── Step 6: state transitions ──────────────────────────────────────
    with conn.cursor() as cur:
        for label, order_id in [("perp", perp_order_id), ("spot", spot_order_id)]:
            cur.execute(
                """
                SELECT trading.transition_order_state(
                    %s, 'submitted', 'paper submit',
                    'system', 'global', %s,
                    %s, '{}'::jsonb
                )
                """,
                (order_id, created_by, created_by),
            )
            cur.execute(
                """
                SELECT trading.record_order_ack(
                    %s, %s, '{}'::jsonb, %s
                )
                """,
                (order_id, f"venue-ack-{label}-{order_id}", created_by),
            )

    # ─── Step 7: fills (SHADOW + MODELED_FILL) ──────────────────────────
    with conn.cursor() as cur:
        for label, order_id, leg in [
            ("perp", perp_order_id, intent.perp_leg),
            ("spot", spot_order_id, intent.spot_leg),
        ]:
            instrument_id = (ctx["instrument_id"] if label == "perp"
                             else spot_instrument_id)
            fill_price = fill_price_perp if label == "perp" else fill_price_spot
            raw_record = json.dumps({
                "venue": "binance",
                "fill_environment": "SHADOW",
                "fill_settlement_type": "MODELED_FILL",
                "lineage": {
                    "cost_model_hash": intent.cost_model_hash,
                    "sizing_config_hash": intent.sizing_config_hash,
                    "simulation_seed": 42,
                    "intent_uuid": str(perp_intent_uuid if label == "perp"
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
                RETURNING id, venue_namespace, venue_fill_id
                """,
                (
                    order_id, instrument_id,
                    f"{created_by}-fill-{label}-{order_id}", venue_namespace,
                    leg.side.value, leg.quantity, fill_price,
                    leg.quantity * fill_price,
                    fill_ts, raw_record,
                ),
            )
            fill_id, fvns, fvfid = cur.fetchone()
            if label == "perp":
                perp_fill_id = fill_id
                perp_venue_namespace_out = fvns
                perp_venue_fill_id_out = fvfid
            else:
                spot_fill_id = fill_id
                spot_venue_namespace_out = fvns
                spot_venue_fill_id_out = fvfid

    return SubmissionResult(
        allocator_run_id=run_id,
        perp_intent_id=perp_intent_id,
        spot_intent_id=spot_intent_id,
        perp_intent_uuid=str(perp_intent_uuid),
        spot_intent_uuid=str(spot_intent_uuid),
        perp_order_id=perp_order_id,
        spot_order_id=spot_order_id,
        perp_fill_id=perp_fill_id,
        spot_fill_id=spot_fill_id,
        perp_venue_namespace=perp_venue_namespace_out,
        spot_venue_namespace=spot_venue_namespace_out,
        perp_venue_fill_id=perp_venue_fill_id_out,
        spot_venue_fill_id=spot_venue_fill_id_out,
    )
