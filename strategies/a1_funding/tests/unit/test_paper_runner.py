"""Day 15a unit tests for A1PaperRunner.

All dependencies injected via fakes — no DB, no real Binance, no clock.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from core.config.cost_model import conservative_default_v0 as cost_default
from data.ingestion.vendors.binance.funding_rate import FundingRate
from strategies.a1_funding.config.sizing import (
    InstrumentSizingRule,
    SizingConfig,
    SIZING_CONFIG_SCHEMA_VERSION,
)
from strategies.a1_funding.sizing.order_intent import OrderIntent
from strategies.a1_funding.runner.paper_runner import (
    A1PaperRunner,
    EvaluationOutcome,
    FundingDueEvent,
    TickResult,
)


UTC = timezone.utc


# ─── Fixture builders ────────────────────────────────────────────────────


def _make_funding_window(
    *, instrument_code: str, n: int = 12,
    base_rate: Decimal = Decimal("0.0001"),
    base_time: datetime = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
) -> list[FundingRate]:
    """Construct a synthetic funding-rate window."""
    return [
        FundingRate(
            venue="binance",
            instrument=instrument_code,
            funding_time=base_time + timedelta(hours=8 * i),
            funding_rate=base_rate,
            mark_price=Decimal("50000"),
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
        max_total_notional_usd=Decimal("1000"),
    )


def _multi_instrument_sizing(instruments: list[str]) -> SizingConfig:
    rules = tuple(
        InstrumentSizingRule(
            venue="binance",
            perp_instrument=code,
            spot_instrument=code.replace("_PERP", "_SPOT"),
            max_quantity=Decimal("0.01"),
            slippage_tier_name="btc_eth_top_tier",
            min_quantity=Decimal("0.001"),
        )
        for code in instruments
    )
    return SizingConfig(
        schema_version=SIZING_CONFIG_SCHEMA_VERSION,
        rules=rules,
        max_total_notional_usd=Decimal("1000"),
    )


def _build_runner(
    *,
    instruments: list[str] = None,
    funding_rate_source=None,
    current_position_source=None,
    due_events_source=None,
    submit_recorder: list = None,
    fund_recorder: list = None,
    clock_value: datetime = datetime(2026, 1, 5, 0, 0, 0, tzinfo=UTC),
):
    """Construct a runner with sensible defaults; tests override what they need."""
    if instruments is None:
        instruments = ["BTCUSDT_PERP"]
    if funding_rate_source is None:
        funding_rate_source = lambda code, as_of: _make_funding_window(
            instrument_code=code,
        )
    if current_position_source is None:
        current_position_source = lambda code: Decimal("0")
    if due_events_source is None:
        due_events_source = lambda as_of: []
    if submit_recorder is None:
        submit_recorder = []
    submit_callback = submit_recorder.append
    if fund_recorder is None:
        fund_recorder = []
    funding_event_callback = fund_recorder.append

    return A1PaperRunner(
        clock=lambda: clock_value,
        funding_rate_source=funding_rate_source,
        submit_callback=submit_callback,
        current_position_source=current_position_source,
        due_events_source=due_events_source,
        funding_event_callback=funding_event_callback,
        instruments=instruments,
        sizing_config=_multi_instrument_sizing(instruments),
        cost_model=cost_default(),
        slippage_tier_name="btc_eth_top_tier",
    )


# ─── Construction validation ─────────────────────────────────────────────


class TestRunnerConstruction:
    def test_minimal_construction(self):
        r = _build_runner()
        assert r.instruments == ("BTCUSDT_PERP",)

    def test_empty_instruments_rejected(self):
        # Use the single-instrument sizing helper (tests the runner check,
        # not SizingConfig validation).
        with pytest.raises(ValueError, match="at least one instrument"):
            A1PaperRunner(
                clock=lambda: datetime.now(UTC),
                funding_rate_source=lambda c, t: [],
                submit_callback=lambda i: None,
                current_position_source=lambda c: Decimal("0"),
                due_events_source=lambda t: [],
                funding_event_callback=lambda e: None,
                instruments=[],
                sizing_config=_sizing_for_btcusdt("BTCUSDT_PERP", "BTCUSDT_SPOT"),
                cost_model=cost_default(),
                slippage_tier_name="btc_eth_top_tier",
            )

    def test_blank_instrument_code_rejected(self):
        with pytest.raises(ValueError, match="non-empty"):
            _build_runner(instruments=["  "])

    def test_negative_discount_k_rejected(self):
        with pytest.raises(ValueError, match="discount_k must be >= 0"):
            A1PaperRunner(
                clock=lambda: datetime.now(UTC),
                funding_rate_source=lambda c, t: [],
                submit_callback=lambda i: None,
                current_position_source=lambda c: Decimal("0"),
                due_events_source=lambda t: [],
                funding_event_callback=lambda e: None,
                instruments=["BTCUSDT_PERP"],
                sizing_config=_sizing_for_btcusdt("BTCUSDT_PERP", "BTCUSDT_SPOT"),
                cost_model=cost_default(),
                slippage_tier_name="btc_eth_top_tier",
                discount_k=Decimal("-0.1"),
            )

    def test_zero_min_lookback_rejected(self):
        with pytest.raises(ValueError, match="min_lookback must be >= 1"):
            A1PaperRunner(
                clock=lambda: datetime.now(UTC),
                funding_rate_source=lambda c, t: [],
                submit_callback=lambda i: None,
                current_position_source=lambda c: Decimal("0"),
                due_events_source=lambda t: [],
                funding_event_callback=lambda e: None,
                instruments=["BTCUSDT_PERP"],
                sizing_config=_sizing_for_btcusdt("BTCUSDT_PERP", "BTCUSDT_SPOT"),
                cost_model=cost_default(),
                slippage_tier_name="btc_eth_top_tier",
                min_lookback=0,
            )

    def test_zero_funding_intervals_per_day_rejected(self):
        with pytest.raises(ValueError, match="funding_intervals_per_day must be >= 1"):
            A1PaperRunner(
                clock=lambda: datetime.now(UTC),
                funding_rate_source=lambda c, t: [],
                submit_callback=lambda i: None,
                current_position_source=lambda c: Decimal("0"),
                due_events_source=lambda t: [],
                funding_event_callback=lambda e: None,
                instruments=["BTCUSDT_PERP"],
                sizing_config=_sizing_for_btcusdt("BTCUSDT_PERP", "BTCUSDT_SPOT"),
                cost_model=cost_default(),
                slippage_tier_name="btc_eth_top_tier",
                funding_intervals_per_day=0,
            )


# ─── tick() coherence ────────────────────────────────────────────────────


class TestTickCoherence:
    def test_clock_called_exactly_once_per_tick(self):
        call_log: list[datetime] = []
        ts = datetime(2026, 1, 5, 0, 0, 0, tzinfo=UTC)

        def clock():
            call_log.append(ts)
            return ts

        runner = A1PaperRunner(
            clock=clock,
            funding_rate_source=lambda c, t: _make_funding_window(instrument_code=c),
            submit_callback=lambda i: None,
            current_position_source=lambda c: Decimal("0"),
            due_events_source=lambda t: [],
            funding_event_callback=lambda e: None,
            instruments=["BTCUSDT_PERP", "ETHUSDT_PERP"],
            sizing_config=_sizing_for_btcusdt("BTCUSDT_PERP", "BTCUSDT_SPOT"),
            cost_model=cost_default(),
            slippage_tier_name="btc_eth_top_tier",
        )
        runner.tick()
        assert len(call_log) == 1, (
            f"clock should be called once per tick, got {len(call_log)}"
        )

    def test_all_outcomes_share_same_as_of(self):
        ts = datetime(2026, 1, 5, 0, 0, 0, tzinfo=UTC)
        runner = _build_runner(
            instruments=["BTCUSDT_PERP", "ETHUSDT_PERP"],
            clock_value=ts,
        )
        result = runner.tick()
        assert result.as_of == ts
        for outcome in result.outcomes:
            assert outcome.as_of == ts

    def test_outcomes_in_instrument_declaration_order(self):
        runner = _build_runner(
            instruments=["A_PERP", "B_PERP", "C_PERP"],
        )
        result = runner.tick()
        codes = [o.instrument_code for o in result.outcomes]
        assert codes == ["A_PERP", "B_PERP", "C_PERP"]


# ─── evaluate_and_size — happy path ──────────────────────────────────────


class TestEvaluateHappyPath:
    def test_signal_flat_no_intent(self):
        # Cost model dominates a tiny rate → flat decision.
        runner = _build_runner(
            funding_rate_source=lambda c, t: _make_funding_window(
                instrument_code=c, base_rate=Decimal("0.00000001"),
            ),
        )
        outcome = runner.evaluate_and_size(
            "BTCUSDT_PERP",
            datetime(2026, 1, 5, 0, 0, 0, tzinfo=UTC),
        )
        assert outcome.intent is None
        assert outcome.no_intent_reason == "signal_flat"
        assert outcome.signal is not None
        assert outcome.signal.decision == "flat"

    def test_signal_short_produces_intent_when_flat(self):
        # Positive funding rate → longs pay shorts → signal=short_perp_long_spot
        # (we receive funding by being short).
        runner = _build_runner(
            funding_rate_source=lambda c, t: _make_funding_window(
                instrument_code=c, base_rate=Decimal("0.005"),
            ),
            current_position_source=lambda c: Decimal("0"),
        )
        outcome = runner.evaluate_and_size(
            "BTCUSDT_PERP",
            datetime(2026, 1, 5, 0, 0, 0, tzinfo=UTC),
        )
        assert outcome.intent is not None
        assert outcome.no_intent_reason is None
        assert outcome.error is None

    def test_evaluation_outcome_invariant(self):
        outcome = EvaluationOutcome(
            instrument_code="X", as_of=datetime.now(UTC),
            forecast=None, signal=None, intent=None,
            no_intent_reason="signal_flat", error=None,
        )
        assert outcome.no_intent_reason == "signal_flat"

    def test_evaluation_outcome_rejects_no_result_at_all(self):
        with pytest.raises(ValueError, match="exactly one"):
            EvaluationOutcome(
                instrument_code="X", as_of=datetime.now(UTC),
                forecast=None, signal=None, intent=None,
                no_intent_reason=None, error=None,
            )


# ─── evaluate_and_size — error/edge paths ────────────────────────────────


class TestEvaluateErrors:
    def test_funding_rate_source_raises_captured(self):
        def bad_source(c, t):
            raise RuntimeError("vendor down")
        runner = _build_runner(funding_rate_source=bad_source)
        outcome = runner.evaluate_and_size(
            "BTCUSDT_PERP",
            datetime(2026, 1, 5, 0, 0, 0, tzinfo=UTC),
        )
        assert outcome.error is not None
        assert "vendor down" in outcome.error
        assert outcome.intent is None
        assert outcome.no_intent_reason is None

    def test_insufficient_window_returns_clean_no_intent(self):
        runner = _build_runner(
            funding_rate_source=lambda c, t: [],  # empty window
        )
        outcome = runner.evaluate_and_size(
            "BTCUSDT_PERP",
            datetime(2026, 1, 5, 0, 0, 0, tzinfo=UTC),
        )
        assert outcome.intent is None
        assert outcome.no_intent_reason == "insufficient_window"
        assert outcome.error is None

    def test_current_position_source_raises_captured(self):
        # Force a non-flat signal so we reach the position-source step.
        def bad_pos(c):
            raise RuntimeError("db unavailable")
        runner = _build_runner(
            funding_rate_source=lambda c, t: _make_funding_window(
                instrument_code=c, base_rate=Decimal("0.005"),
            ),
            current_position_source=bad_pos,
        )
        outcome = runner.evaluate_and_size(
            "BTCUSDT_PERP",
            datetime(2026, 1, 5, 0, 0, 0, tzinfo=UTC),
        )
        assert outcome.error is not None
        assert "db unavailable" in outcome.error
        assert outcome.signal is not None  # got past signal step
        assert outcome.signal.decision != "flat"


# ─── tick() submission behavior ──────────────────────────────────────────


class TestTickSubmission:
    def test_tick_submits_only_non_none_intents(self):
        submitted: list[OrderIntent] = []

        def funding_source(code, as_of):
            # First instrument: strong signal → intent. Second: tiny rate → flat.
            if code == "BTCUSDT_PERP":
                return _make_funding_window(
                    instrument_code=code, base_rate=Decimal("0.005"),
                )
            return _make_funding_window(
                instrument_code=code, base_rate=Decimal("0.00000001"),
            )

        runner = _build_runner(
            instruments=["BTCUSDT_PERP", "ETHUSDT_PERP"],
            funding_rate_source=funding_source,
            submit_recorder=submitted,
        )
        result = runner.tick()
        assert result.submitted_count == 1
        assert len(submitted) == 1

    def test_tick_no_intents_no_submissions(self):
        submitted: list[OrderIntent] = []
        runner = _build_runner(
            funding_rate_source=lambda c, t: _make_funding_window(
                instrument_code=c, base_rate=Decimal("0.00000001"),
            ),
            submit_recorder=submitted,
        )
        result = runner.tick()
        assert result.submitted_count == 0
        assert submitted == []

    def test_tick_multiple_intents_submitted_in_order(self):
        submitted: list[OrderIntent] = []
        runner = _build_runner(
            instruments=["BTCUSDT_PERP", "ETHUSDT_PERP"],
            funding_rate_source=lambda c, t: _make_funding_window(
                instrument_code=c, base_rate=Decimal("0.005"),
            ),
            submit_recorder=submitted,
        )
        result = runner.tick()
        assert result.submitted_count == 2
        assert len(submitted) == 2

    def test_submit_callback_not_called_for_error_outcomes(self):
        submitted: list[OrderIntent] = []
        runner = _build_runner(
            funding_rate_source=lambda c, t: (_ for _ in ()).throw(
                RuntimeError("boom"),
            ),
            submit_recorder=submitted,
        )
        result = runner.tick()
        assert result.outcomes[0].error is not None
        assert submitted == []


# ─── discover_due_funding_events ─────────────────────────────────────────


class TestDiscoverDueFundingEvents:
    def test_passes_through_to_due_events_source(self):
        ts = datetime(2026, 1, 5, 0, 0, 0, tzinfo=UTC)
        events = [
            FundingDueEvent(
                instrument_code="BTCUSDT_PERP",
                funded_at=ts,
                venue_namespace="venue_test",
                venue_funding_id="BTCUSDT-2026-01-05T00-00",
            ),
        ]
        captured_as_of: list[datetime] = []

        def source(as_of):
            captured_as_of.append(as_of)
            return events

        runner = _build_runner(due_events_source=source)
        result = runner.discover_due_funding_events(ts)
        assert result == events
        assert captured_as_of == [ts]

    def test_empty_when_source_returns_nothing(self):
        runner = _build_runner(due_events_source=lambda t: [])
        ts = datetime(2026, 1, 5, 0, 0, 0, tzinfo=UTC)
        assert runner.discover_due_funding_events(ts) == []

    def test_does_not_dispatch_or_submit(self):
        # 15a: discover only. Submission/journal-posting is not the
        # runner's job here. Verify by confirming submit_callback is
        # untouched even when due events are reported.
        submitted: list[OrderIntent] = []
        ts = datetime(2026, 1, 5, 0, 0, 0, tzinfo=UTC)
        events = [
            FundingDueEvent(
                instrument_code="BTCUSDT_PERP",
                funded_at=ts,
                venue_namespace="venue_test",
                venue_funding_id="evt_001",
            ),
        ]
        runner = _build_runner(
            due_events_source=lambda t: events,
            submit_recorder=submitted,
        )
        runner.discover_due_funding_events(ts)
        assert submitted == []



# ─── dispatch_due_funding_events ─────────────────────────────────────────


class TestDispatchDueFundingEvents:
    def test_dispatch_clock_called_once_and_propagated_to_source(self):
        ts = datetime(2026, 1, 5, 0, 0, 0, tzinfo=UTC)
        clock_calls: list[datetime] = []
        source_calls: list[datetime] = []

        def clock():
            clock_calls.append(ts)
            return ts

        def source(as_of):
            source_calls.append(as_of)
            return []

        runner = A1PaperRunner(
            clock=clock,
            funding_rate_source=lambda c, t: [],
            submit_callback=lambda i: None,
            current_position_source=lambda c: Decimal("0"),
            due_events_source=source,
            funding_event_callback=lambda e: None,
            instruments=["BTCUSDT_PERP"],
            sizing_config=_sizing_for_btcusdt("BTCUSDT_PERP", "BTCUSDT_SPOT"),
            cost_model=cost_default(),
            slippage_tier_name="btc_eth_top_tier",
        )
        result = runner.dispatch_due_funding_events()
        assert len(clock_calls) == 1
        assert source_calls == [ts]
        assert result.as_of == ts
        assert result.events == ()
        assert result.events_dispatched == 0
        assert result.error_count == 0

    def test_dispatch_calls_callback_per_event(self):
        ts = datetime(2026, 1, 5, 0, 0, 0, tzinfo=UTC)
        events = [
            FundingDueEvent(
                instrument_code="BTCUSDT_PERP",
                funded_at=ts + timedelta(hours=8 * i),
                venue_namespace="venue_test",
                venue_funding_id=f"BTCUSDT-evt-{i:03d}",
            )
            for i in range(3)
        ]
        recorded: list[FundingDueEvent] = []
        runner = _build_runner(
            due_events_source=lambda as_of: events,
            fund_recorder=recorded,
        )
        result = runner.dispatch_due_funding_events()
        assert result.events_dispatched == 3
        assert result.error_count == 0
        assert recorded == events

    def test_dispatch_empty_events_no_callback(self):
        recorded: list[FundingDueEvent] = []
        runner = _build_runner(
            due_events_source=lambda as_of: [],
            fund_recorder=recorded,
        )
        result = runner.dispatch_due_funding_events()
        assert result.events == ()
        assert recorded == []

    def test_dispatch_callback_error_captured_and_continues(self):
        ts = datetime(2026, 1, 5, 0, 0, 0, tzinfo=UTC)
        events = [
            FundingDueEvent(
                instrument_code="BTCUSDT_PERP",
                funded_at=ts,
                venue_namespace="venue_test",
                venue_funding_id="evt_0",
            ),
            FundingDueEvent(
                instrument_code="BTCUSDT_PERP",
                funded_at=ts,
                venue_namespace="venue_test",
                venue_funding_id="evt_BAD",
            ),
            FundingDueEvent(
                instrument_code="BTCUSDT_PERP",
                funded_at=ts,
                venue_namespace="venue_test",
                venue_funding_id="evt_2",
            ),
        ]
        seen: list[str] = []

        def cb(event):
            if "BAD" in event.venue_funding_id:
                raise RuntimeError("synthetic failure")
            seen.append(event.venue_funding_id)

        runner = A1PaperRunner(
            clock=lambda: ts,
            funding_rate_source=lambda c, t: [],
            submit_callback=lambda i: None,
            current_position_source=lambda c: Decimal("0"),
            due_events_source=lambda as_of: events,
            funding_event_callback=cb,
            instruments=["BTCUSDT_PERP"],
            sizing_config=_sizing_for_btcusdt("BTCUSDT_PERP", "BTCUSDT_SPOT"),
            cost_model=cost_default(),
            slippage_tier_name="btc_eth_top_tier",
        )
        result = runner.dispatch_due_funding_events()
        assert result.events_dispatched == 2
        assert result.error_count == 1
        assert "BAD" in result.error_messages[0]
        assert seen == ["evt_0", "evt_2"]

    def test_dispatch_due_events_source_error_captured(self):
        def bad(as_of):
            raise RuntimeError("vendor down")
        runner = _build_runner(due_events_source=bad)
        result = runner.dispatch_due_funding_events()
        assert result.events == ()
        assert result.error_count == 1
        assert "vendor down" in result.error_messages[0]
