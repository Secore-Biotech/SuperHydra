"""A1 paper runner skeleton.

Pure orchestration over the strategy pipeline. The runner does NOT know
about Binance, DB connections, or asyncio. All dependencies are injected
as callables. Day 15b wires real implementations; Day 15c (later) adds
a real-time scheduler wrapper around this logical-clock core.

The runner is stateless. State lives in the DB. Every method that needs
"what's the current position?" or "what's been processed already?" calls
the appropriate injected source. This is intentional — the writers we
built in Days 9-14 already enforce idempotency, so a stateless runner
that re-asks the DB on every tick is correct by construction.

Per-tick coherence: tick() calls clock() exactly once and propagates the
same `as_of` through every instrument evaluation in that tick. A
single tick has a single coherent timestamp.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Callable, Literal

from core.config.cost_model import CostModelConfig
from data.ingestion.vendors.binance.funding_rate import FundingRate

from strategies.a1_funding.config.sizing import SizingConfig
from strategies.a1_funding.sizing.order_intent import OrderIntent
from strategies.a1_funding.signal.evaluate import (
    SignalEvaluation,
    evaluate_signal,
)
from strategies.a1_funding.signal.expected_funding import (
    ExpectedFunding,
    ExpectedFundingError,
    expected_next_funding,
)
from strategies.a1_funding.sizing.sizer import size_intent


# ─── Result types ────────────────────────────────────────────────────────


# Reasons an evaluation can produce no intent. Caller can log/aggregate.
NoIntentReason = Literal[
    "insufficient_window",   # expected_next_funding raised on too-short window
    "signal_flat",           # evaluate_signal said flat
    "sizer_no_op",           # signal said trade but sizer returned None
    "current_position_matches_target",
]


@dataclass(frozen=True)
class EvaluationOutcome:
    """Result of evaluating a single instrument at a single timestamp.

    Exactly one of (intent, no_intent_reason) is set:
      - intent: an OrderIntent the caller should hand to submit_callback
      - no_intent_reason: why no intent was produced this tick
    Both `forecast` and `signal` are populated when available; they
    may be None if the pipeline raised before reaching that step.
    """
    instrument_code: str
    as_of: datetime
    forecast: ExpectedFunding | None
    signal: SignalEvaluation | None
    intent: OrderIntent | None
    no_intent_reason: NoIntentReason | None
    error: str | None  # exception message if the pipeline raised

    def __post_init__(self) -> None:
        # Exactly one of intent / no_intent_reason / error is set.
        non_null = sum(
            1 for x in (self.intent, self.no_intent_reason, self.error)
            if x is not None
        )
        if non_null != 1:
            raise ValueError(
                f"EvaluationOutcome must have exactly one of "
                f"(intent, no_intent_reason, error); got {non_null}"
            )


@dataclass(frozen=True)
class TickResult:
    """One coherent tick across all configured instruments.

    `as_of` is the single timestamp used for the entire tick (clock()
    is called exactly once at the top of tick()). Per-instrument
    outcomes are returned in the order of the runner's instruments
    list.
    """
    as_of: datetime
    outcomes: tuple[EvaluationOutcome, ...]

    @property
    def submitted_count(self) -> int:
        return sum(1 for o in self.outcomes if o.intent is not None)


@dataclass(frozen=True)
class FundingDueEvent:
    """A funding interval that has settled but does not yet have a
    funding_payment row in the DB. Day 15a treats this as opaque
    data — the caller (or Day 15b's dispatch path) decides what to
    construct FundingEventRecord rows from it.

    Returned by discover_due_funding_events; the runner does NOT
    post journals itself in 15a (separation of concerns: tick() is
    for order generation, dispatch_due_funding_events is a future
    method that converts these into journals).
    """
    instrument_code: str
    funded_at: datetime
    venue_namespace: str
    venue_funding_id: str


# ─── The runner ──────────────────────────────────────────────────────────


class A1PaperRunner:
    """Logical-clock paper runner for the A1 funding-rate engine.

    Construction:
      runner = A1PaperRunner(
          clock=lambda: datetime.now(UTC),
          funding_rate_source=fetch_window,
          submit_callback=oms_submit,
          current_position_source=read_current_qty,
          due_events_source=read_due_funding_events,
          instruments=["BTCUSDT_PERP", "ETHUSDT_PERP"],
          sizing_config=cfg,
          cost_model=cm,
          slippage_tier_name="btc_eth_top_tier",
      )

    Tick:
      result = runner.tick()
      # result.outcomes contains one EvaluationOutcome per instrument
    """

    def __init__(
        self, *,
        clock: Callable[[], datetime],
        funding_rate_source: Callable[[str, datetime], list[FundingRate]],
        submit_callback: Callable[[OrderIntent], None],
        current_position_source: Callable[[str], Decimal],
        due_events_source: Callable[[datetime], list[FundingDueEvent]],
        instruments: list[str],
        sizing_config: SizingConfig,
        cost_model: CostModelConfig,
        slippage_tier_name: str,
        discount_k: Decimal = Decimal("1"),
        min_lookback: int = 1,
        funding_intervals_per_day: int = 3,
    ) -> None:
        if not instruments:
            raise ValueError("A1PaperRunner requires at least one instrument")
        if any(not c.strip() for c in instruments):
            raise ValueError("instrument codes must be non-empty")
        if discount_k < 0:
            raise ValueError(f"discount_k must be >= 0, got {discount_k}")
        if min_lookback < 1:
            raise ValueError(f"min_lookback must be >= 1, got {min_lookback}")
        if funding_intervals_per_day < 1:
            raise ValueError(
                f"funding_intervals_per_day must be >= 1, got "
                f"{funding_intervals_per_day}"
            )
        if not slippage_tier_name.strip():
            raise ValueError("slippage_tier_name must be non-empty")

        self._clock = clock
        self._funding_rate_source = funding_rate_source
        self._submit_callback = submit_callback
        self._current_position_source = current_position_source
        self._due_events_source = due_events_source
        self._instruments = tuple(instruments)
        self._sizing_config = sizing_config
        self._cost_model = cost_model
        self._slippage_tier_name = slippage_tier_name
        self._discount_k = discount_k
        self._min_lookback = min_lookback
        self._funding_intervals_per_day = funding_intervals_per_day

    # ─── Public API ─────────────────────────────────────────────────────

    def tick(self) -> TickResult:
        """One orchestration step across all instruments at a single
        coherent timestamp.

        Calls clock() exactly once at the top, then propagates that
        as_of through every instrument's evaluation. Submits any
        non-None intents via submit_callback in declaration order.
        """
        as_of = self._clock()
        outcomes: list[EvaluationOutcome] = []
        for instrument_code in self._instruments:
            outcome = self.evaluate_and_size(instrument_code, as_of)
            outcomes.append(outcome)
            if outcome.intent is not None:
                self._submit_callback(outcome.intent)
        return TickResult(as_of=as_of, outcomes=tuple(outcomes))

    def evaluate_and_size(
        self, instrument_code: str, as_of: datetime,
    ) -> EvaluationOutcome:
        """Evaluate one instrument at the given timestamp.

        Pure orchestration: pulls the funding-rate window from the
        injected source, runs the signal pipeline, sizes the intent.
        Does NOT submit. The caller (or tick()) decides whether to
        submit the result.
        """
        # ─── 1. Pull the rate window ────────────────────────────────────
        try:
            window = self._funding_rate_source(instrument_code, as_of)
        except Exception as exc:
            return EvaluationOutcome(
                instrument_code=instrument_code,
                as_of=as_of,
                forecast=None, signal=None, intent=None,
                no_intent_reason=None,
                error=f"funding_rate_source raised: {exc}",
            )

        # ─── 2. Compute expected funding ────────────────────────────────
        try:
            forecast = expected_next_funding(
                window,
                discount_k=self._discount_k,
                min_lookback=self._min_lookback,
                as_of=as_of,
            )
        except ExpectedFundingError as exc:
            return EvaluationOutcome(
                instrument_code=instrument_code,
                as_of=as_of,
                forecast=None, signal=None, intent=None,
                no_intent_reason="insufficient_window",
                error=None,
            )
        except Exception as exc:
            return EvaluationOutcome(
                instrument_code=instrument_code,
                as_of=as_of,
                forecast=None, signal=None, intent=None,
                no_intent_reason=None,
                error=f"expected_next_funding raised: {exc}",
            )

        # ─── 3. Evaluate the signal ─────────────────────────────────────
        try:
            signal = evaluate_signal(
                forecast,
                self._cost_model,
                slippage_tier_name=self._slippage_tier_name,
                funding_intervals_per_day=self._funding_intervals_per_day,
            )
        except Exception as exc:
            return EvaluationOutcome(
                instrument_code=instrument_code,
                as_of=as_of,
                forecast=forecast, signal=None, intent=None,
                no_intent_reason=None,
                error=f"evaluate_signal raised: {exc}",
            )

        if signal.decision == "flat":
            return EvaluationOutcome(
                instrument_code=instrument_code,
                as_of=as_of,
                forecast=forecast, signal=signal, intent=None,
                no_intent_reason="signal_flat",
                error=None,
            )

        # ─── 4. Read current position, then size ────────────────────────
        try:
            current_qty = self._current_position_source(instrument_code)
        except Exception as exc:
            return EvaluationOutcome(
                instrument_code=instrument_code,
                as_of=as_of,
                forecast=forecast, signal=signal, intent=None,
                no_intent_reason=None,
                error=f"current_position_source raised: {exc}",
            )

        try:
            intent = size_intent(
                signal,
                current_perp_quantity=current_qty,
                sizing_config=self._sizing_config,
            )
        except Exception as exc:
            return EvaluationOutcome(
                instrument_code=instrument_code,
                as_of=as_of,
                forecast=forecast, signal=signal, intent=None,
                no_intent_reason=None,
                error=f"size_intent raised: {exc}",
            )

        if intent is None:
            return EvaluationOutcome(
                instrument_code=instrument_code,
                as_of=as_of,
                forecast=forecast, signal=signal, intent=None,
                no_intent_reason="sizer_no_op",
                error=None,
            )

        return EvaluationOutcome(
            instrument_code=instrument_code,
            as_of=as_of,
            forecast=forecast, signal=signal, intent=intent,
            no_intent_reason=None,
            error=None,
        )

    def discover_due_funding_events(
        self, as_of: datetime,
    ) -> list[FundingDueEvent]:
        """Return funding intervals that have settled by `as_of` but do
        not yet have a corresponding accounting.funding_payments row.

        15a delegates the actual discovery to the injected
        due_events_source. Day 15b wires this to a real DB query
        joining trading.fills (for active positions) against
        accounting.funding_payments (for what's already been posted).

        The runner does NOT post the journal here — that's the
        dispatch_due_funding_events method (added in 15b alongside the
        DB wiring). 15a only reports.
        """
        return list(self._due_events_source(as_of))

    # ─── Read-only accessors (test conveniences) ────────────────────────

    @property
    def instruments(self) -> tuple[str, ...]:
        return self._instruments
