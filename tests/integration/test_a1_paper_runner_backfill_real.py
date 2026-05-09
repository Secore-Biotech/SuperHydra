"""Day 16b: real-data no-trade regime test.

Loads a real 14-day BTCUSDT funding-rate fixture and runs the runner
across 30 backfill intervals (after a 12-rate prior history). The
specific historical window in this fixture has mean funding rate close
to zero with a slight negative bias — well below the cost model's
~0.0012 per-interval cost threshold. The correct A1 behavior in such
a regime is to stay flat: no trades, no fills, no journals, no
funding payments.

This test celebrates and requires that correct behavior. It is the
primary evidence that the engine refuses to trade when no edge
exists. A separate Day 16b.2 test (with a different fixture chosen
for strong positive funding) exercises the yes-trade case.

Refresh the fixture via:
  python3 scripts/refresh_binance_funding_fixture.py

Acceptance:
  - 30 ticks, all produce no_intent_reason='signal_flat'
  - No exceptions during the backfill
  - 0 order_intents, 0 orders, 0 fills, 0 trade journals
  - 0 funding_payments, 0 funding journals
  - 0 position snapshots created by the runner
  - Fixture stats documented in the test docstring for auditability
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from core.config.cost_model import conservative_default_v0 as cost_default
from data.ingestion.vendors.binance.funding_rate import FundingRate
from strategies.a1_funding.runner.paper_runner import (
    A1PaperRunner,
    FundingDueEvent,
)
from tests.integration.test_a1_paper_runner import (
    _make_current_position_source,
    _sizing_for_btcusdt,
)
from tests.integration.test_a1_smoke_vertical import (
    _connect,
    _create_btc_spot_instrument,
    fresh_db,  # noqa: F401
)
from tests.integration.test_migrations import _setup_basic_0009


UTC = timezone.utc

FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent
    / "fixtures" / "binance_funding"
    / 'BTCUSDT_14d_20260424T000000_20260508T000000.json'
)


def _load_fixture() -> tuple[list[FundingRate], dict]:
    """Load the Binance fixture. Returns (rates, manifest_metadata)."""
    if not FIXTURE_PATH.exists():
        pytest.skip(
            f"Fixture not present at {FIXTURE_PATH}; "
            f"run scripts/refresh_binance_funding_fixture.py to generate."
        )
    with FIXTURE_PATH.open() as f:
        payload = json.load(f)

    records = []
    for r in payload["records"]:
        records.append(FundingRate(
            venue=r["venue"],
            instrument=r["instrument"],
            funding_time=datetime.fromisoformat(r["funding_time"]),
            funding_rate=Decimal(r["funding_rate"]),
            mark_price=Decimal(r["mark_price"]) if r["mark_price"] else None,
            next_funding_time=(
                datetime.fromisoformat(r["next_funding_time"])
                if r["next_funding_time"] else None
            ),
            ingested_at=(
                datetime.fromisoformat(r["ingested_at"])
                if r["ingested_at"] else None
            ),
            schema_version=r["schema_version"],
        ))
    return records, payload


def test_a1_paper_runner_real_binance_no_edge_stays_flat(fresh_db):
    """Real-data no-trade regime test.

    Fixture stats (computed at fixture-generation time, see manifest):
      symbol: BTCUSDT
      window: 14 days, 42 records (3/day Binance funding cadence)
      mean rate: ~-0.000026 per interval (negative bias)
      negative intervals: 32 of 42
      positive intervals: 10 of 42
      max rate: ~0.00005
      min rate: ~-0.00009

    The cost model's per-interval cost is ~0.0012. Even the most
    favorable real rates in this window are 20x below cost. The signal
    correctly returns flat on every tick.
    """
    fixture_rates, manifest = _load_fixture()
    assert len(fixture_rates) == 42, (
        f"fixture is supposed to have 42 records (3/day x 14d); "
        f"got {len(fixture_rates)}"
    )

    PRIOR = fixture_rates[:12]
    BACKFILL = fixture_rates[12:]
    assert len(BACKFILL) == 30

    INTERVAL = timedelta(hours=8)
    BACKFILL_START = BACKFILL[0].funding_time

    # ─── Sanity: confirm the fixture is in the no-edge regime. ─────────
    # Mean rate over the full 42 intervals should be well below the cost
    # model's per-interval cost (~0.0012). If the fixture is regenerated
    # for a strong-funding window in the future, this test should be
    # updated or split into a separate yes-trade test.
    mean_rate = sum(r.funding_rate for r in fixture_rates) / Decimal(len(fixture_rates))
    assert abs(mean_rate) < Decimal("0.0005"), (
        f"Fixture mean rate {mean_rate} is too strong for the no-edge "
        f"test; this fixture should be tested by the yes-trade variant "
        f"in Day 16b.2."
    )

    # ─── DB fixtures ────────────────────────────────────────────────────
    with _connect() as conn, conn.cursor() as cur:
        ctx = _setup_basic_0009(cur)
        spot_instrument_id = _create_btc_spot_instrument(cur, ctx)
        cur.execute(
            "SELECT instrument_code FROM registry.instruments WHERE id = %s",
            (ctx["instrument_id"],),
        )
        perp_instrument_code = cur.fetchone()[0]
        conn.commit()

    sizing_config = _sizing_for_btcusdt(perp_instrument_code, "BTCUSDT-SPOT")
    cost_model = cost_default()

    instrument_id_by_code = {
        perp_instrument_code: ctx["instrument_id"],
        "BTCUSDT-SPOT": spot_instrument_id,
    }

    current_idx = [0]

    def clock_for_tick():
        return BACKFILL_START + INTERVAL * current_idx[0]

    def funding_rate_source_for_tick(code, as_of):
        # Trailing 12 of [PRIOR + BACKFILL[:idx]], rekeyed to runner's
        # instrument_code.
        full = PRIOR + BACKFILL[:current_idx[0]]
        window = full[-12:] if len(full) >= 12 else full
        return [
            FundingRate(
                venue=r.venue,
                instrument=code,
                funding_time=r.funding_time,
                funding_rate=r.funding_rate,
                mark_price=r.mark_price,
                next_funding_time=r.next_funding_time,
                ingested_at=r.ingested_at,
                schema_version=r.schema_version,
            )
            for r in window
        ]

    # The submit and funding callbacks should never be invoked. We wire
    # tripwires that fail the test if they ever fire.
    submit_fired: list = []
    fund_fired: list = []

    def tripwire_submit(intent):
        submit_fired.append(intent)
        raise AssertionError(
            "submit_callback fired in a no-edge regime — "
            "the engine should have produced signal_flat instead"
        )

    def tripwire_fund(event):
        fund_fired.append(event)
        raise AssertionError(
            "funding_event_callback fired in a no-edge regime — "
            "no position should exist to accrue funding on"
        )

    with _connect() as conn:
        current_position_source = _make_current_position_source(
            conn, ctx, instrument_id_by_code,
        )

        runner = A1PaperRunner(
            clock=clock_for_tick,
            funding_rate_source=funding_rate_source_for_tick,
            submit_callback=tripwire_submit,
            current_position_source=current_position_source,
            due_events_source=lambda as_of: [],  # never any due events
            funding_event_callback=tripwire_fund,
            instruments=[perp_instrument_code],
            sizing_config=sizing_config,
            cost_model=cost_model,
            slippage_tier_name="btc_eth_top_tier",
        )

        outcomes_per_tick: list[tuple[int, str]] = []
        for idx in range(30):
            current_idx[0] = idx

            tick_result = runner.tick()
            outcome = tick_result.outcomes[0]

            assert outcome.error is None, (
                f"interval {idx}: unexpected error {outcome.error}"
            )
            assert outcome.intent is None, (
                f"interval {idx}: unexpected intent in no-edge regime: "
                f"{outcome.intent}"
            )
            outcomes_per_tick.append((idx, outcome.no_intent_reason))

    # ─── Per-tick outcomes ──────────────────────────────────────────────
    assert len(outcomes_per_tick) == 30
    # All outcomes should be 'signal_flat' (rates below cost threshold).
    flat_count = sum(1 for _, r in outcomes_per_tick if r == "signal_flat")
    assert flat_count == 30, (
        f"expected all 30 ticks to be signal_flat; got {flat_count}. "
        f"Distribution: {set(r for _, r in outcomes_per_tick)}"
    )

    # Tripwires never fired.
    assert submit_fired == []
    assert fund_fired == []

    # ─── DB state: nothing the runner created should exist ──────────────
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM trading.order_intents "
            "WHERE created_by = 'paper_runner'"
        )
        assert cur.fetchone()[0] == 0, "no order_intents should exist"

        cur.execute(
            "SELECT COUNT(*) FROM trading.orders WHERE created_by = 'paper_runner'"
        )
        assert cur.fetchone()[0] == 0, "no orders should exist"

        cur.execute(
            "SELECT COUNT(*) FROM trading.fills "
            "WHERE order_id IN (SELECT id FROM trading.orders "
            "                   WHERE created_by = 'paper_runner')"
        )
        assert cur.fetchone()[0] == 0, "no fills should exist"

        cur.execute(
            "SELECT COUNT(*) FROM accounting.journals "
            "WHERE created_by = 'paper_runner'"
        )
        assert cur.fetchone()[0] == 0, "no journals should exist"

        cur.execute(
            "SELECT COUNT(*) FROM accounting.funding_payments"
        )
        assert cur.fetchone()[0] == 0, "no funding_payments should exist"

        cur.execute(
            "SELECT COUNT(*) FROM positions.position_snapshots "
            "WHERE created_by = 'paper_runner'"
        )
        assert cur.fetchone()[0] == 0, "no position_snapshots should exist"
