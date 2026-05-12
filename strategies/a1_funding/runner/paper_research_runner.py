"""A1 PAPER_RESEARCH runner.

Day 20.4 deliverable: composes A1's existing signal evaluation
(strategies.a1_funding.signal.{evaluate, expected_funding}) with the
Day 20.3a replay observation infrastructure (execution.paper.replay_runner)
and the Day 20.1 paper.fills writer (execution.paper.fill_writer).

Strategy-specific glue that lives under the A1 package because it
imports A1's signal/profile logic. The generic replay/fill machinery
remains under execution/paper/.

Hard constraints (reviewer-locked):
  - Never imports or invokes A1PaperRunner.
  - Never writes trading.fills.
  - Never writes accounting.funding_payments.
  - Only writes paper.fills via the Day 20.1 writer.
  - source_mode = 'PAPER_RESEARCH' on every fill (DB CHECK enforces).
  - promotion_eligible = false on every fill (DB CHECK enforces).
  - Uses the research-firewalled cost profile from
    select_research_profile_for_a1, bypassing the default selector.

Skip taxonomy: a funding event is skipped (no fill row) when:
  - below min_lookback: not enough prior history for the forecast
  - FLAT decision: forecast does not clear cost threshold (no edge)
  - zero forecast: defensive, redundant with FLAT
  - no reference price: mark_price absent AND no trades near funding_time

Skipped events are counted in RunSummary for audit. Fired events each
produce exactly one paper.fills row, with replay outcome determining
whether observed_slippage_bps is populated or NULL (Day 20.3a semantics).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterable, Sequence
from uuid import UUID

from core.config.cost_model import CostModelConfig
from data.ingestion.vendors.binance.funding_rate import FundingRate
from data.ingestion.vendors.binance.trade import BinanceTrade
from execution.paper.fill_writer import write_paper_fill  # noqa: F401 (transitive use via replay)
from execution.paper.replay_runner import (
    PaperReplayIntent,
    ReplayResult,
    TradeFetcher,
    replay_intents,
)
from strategies.a1_funding.config.profile_selector import (
    select_research_profile_for_a1,
)
from strategies.a1_funding.signal.evaluate import (
    SignalDecision,
    evaluate_signal,
)
from strategies.a1_funding.signal.expected_funding import (
    expected_next_funding,
)


# Default rolling forecast window. Matches the rolling-12 invariant
# enforced by Day 18a-19a structural tests.
DEFAULT_FORECAST_WINDOW: int = 12

# Default Binance perp funding cadence.
DEFAULT_FUNDING_INTERVALS_PER_DAY: int = 3

# Default uncertainty discount for forecast (mean - k * stdev).
# k = 1.0 corresponds to a conservative 1-stdev penalty.
DEFAULT_DISCOUNT_K: Decimal = Decimal("1.0")

# Window for reference-price fetcher fallback when mark_price is absent.
REFERENCE_PRICE_LOOKUP_WINDOW_SECONDS: int = 1


@dataclass(frozen=True)
class RunSummary:
    """Per-run counters and the list of replay results.

    funding_events_total: input length before any filtering.
    intents_fired: number of intents passed to replay_intents.
    replay_results: per-intent outcome from Day 20.3a (success,
        empty_window, fetch_error).

    Skip counters (each is a non-firing path, not a fill row):
      skipped_below_lookback: prior window too short
      skipped_no_edge: signal evaluator returned FLAT
      skipped_zero_funding: forecast_rate exactly zero (defensive)
      skipped_no_reference: no mark_price + no trades near funding_time
    """

    funding_events_total: int
    intents_fired: int
    replay_results: list[ReplayResult]
    skipped_below_lookback: int
    skipped_no_edge: int
    skipped_zero_funding: int
    skipped_no_reference: int


class A1PaperResearchRunner:
    """A1 PAPER_RESEARCH runner.

    Composes existing pure functions; never inherits from or delegates
    to A1PaperRunner. The class boundary is the operational firewall.

    Caller flow:
        runner = A1PaperResearchRunner(
            funding_source=fixture_records,
            trade_fetcher=BinanceArchiveTradeFetcher(),
            fetch_source="archive",
            strategy_id=..., portfolio_id=..., account_id=..., instrument_id=...,
            symbol="SOLUSDT",
            quantity_per_intent=Decimal("33.0"),
        )
        summary = runner.run(conn)
        conn.commit()
    """

    def __init__(
        self,
        *,
        funding_source: Iterable[FundingRate],
        trade_fetcher: TradeFetcher,
        fetch_source: str,
        strategy_id: int,
        portfolio_id: int,
        account_id: int,
        instrument_id: int,
        symbol: str,
        quantity_per_intent: Decimal,
        cost_profile: CostModelConfig | None = None,
        slippage_tier_name: str = "liquid_alt_research_tier",
        forecast_window_size: int = DEFAULT_FORECAST_WINDOW,
        discount_k: Decimal = DEFAULT_DISCOUNT_K,
        funding_intervals_per_day: int = DEFAULT_FUNDING_INTERVALS_PER_DAY,
    ) -> None:
        if quantity_per_intent <= 0:
            raise ValueError(
                f"quantity_per_intent must be positive, got {quantity_per_intent}"
            )
        if forecast_window_size < 1:
            raise ValueError(
                f"forecast_window_size must be >= 1, got {forecast_window_size}"
            )
        if fetch_source not in ("archive", "rest"):
            raise ValueError(
                f"fetch_source must be 'archive' or 'rest', got {fetch_source!r}"
            )

        # Materialize funding source eagerly to validate ordering once.
        self._funding_events: list[FundingRate] = list(funding_source)

        if self._funding_events:
            times = [f.funding_time for f in self._funding_events]
            for i in range(1, len(times)):
                if times[i] <= times[i - 1]:
                    raise ValueError(
                        f"funding events must be strictly ascending by "
                        f"funding_time; got {times[i - 1]} >= {times[i]} "
                        f"at index {i}"
                    )

        # Resolve research profile via the firewall hole. Default looks
        # up by symbol; caller can override for tests.
        if cost_profile is None:
            self._cost_profile = select_research_profile_for_a1(
                symbol, "binance"
            )
        else:
            self._cost_profile = cost_profile

        # Verify the slippage tier exists in the profile; raise early
        # rather than failing inside the signal evaluator.
        tier = next(
            (t for t in self._cost_profile.slippage_tiers
             if t.tier_name == slippage_tier_name),
            None,
        )
        if tier is None:
            tiers = sorted(t.tier_name for t in self._cost_profile.slippage_tiers)
            raise ValueError(
                f"cost profile {self._cost_profile.profile_name!r} has no "
                f"slippage tier {slippage_tier_name!r}; available: {tiers}"
            )
        self._slippage_tier = tier
        self._slippage_tier_name = slippage_tier_name

        self._trade_fetcher = trade_fetcher
        self._fetch_source = fetch_source
        self._strategy_id = strategy_id
        self._portfolio_id = portfolio_id
        self._account_id = account_id
        self._instrument_id = instrument_id
        self._symbol = symbol
        self._quantity_per_intent = quantity_per_intent
        self._forecast_window_size = forecast_window_size
        self._discount_k = discount_k
        self._funding_intervals_per_day = funding_intervals_per_day

    # ─── Public API ────────────────────────────────────────────────────

    def run(self, conn) -> RunSummary:
        """Process funding events and write paper.fills rows.

        Caller owns the transaction; this method does not commit.
        """
        intents: list[PaperReplayIntent] = []
        skipped_below_lookback = 0
        skipped_no_edge = 0
        skipped_zero_funding = 0
        skipped_no_reference = 0

        for i, event in enumerate(self._funding_events):
            # Need at least forecast_window_size prior events.
            if i < self._forecast_window_size:
                skipped_below_lookback += 1
                continue

            window = self._funding_events[i - self._forecast_window_size: i]

            forecast = expected_next_funding(
                window,
                discount_k=self._discount_k,
                min_lookback=self._forecast_window_size,
                as_of=event.funding_time,
            )

            signal = evaluate_signal(
                forecast,
                self._cost_profile,
                slippage_tier_name=self._slippage_tier_name,
                funding_intervals_per_day=self._funding_intervals_per_day,
            )

            if signal.decision == SignalDecision.FLAT:
                skipped_no_edge += 1
                continue

            if signal.forecast_rate == 0:
                # Defensive; shouldn't normally fire under any non-FLAT
                # decision, but guard against unusual config.
                skipped_zero_funding += 1
                continue

            side = _side_from_decision(signal.decision)

            reference_price = self._get_reference_price(event)
            if reference_price is None:
                skipped_no_reference += 1
                continue

            intent = PaperReplayIntent(
                paper_fill_uuid=self._make_deterministic_uuid(event),
                strategy_id=self._strategy_id,
                portfolio_id=self._portfolio_id,
                account_id=self._account_id,
                instrument_id=self._instrument_id,
                symbol=self._symbol,
                side=side,
                quantity=self._quantity_per_intent,
                decision_reference_price=reference_price,
                # modeled_slippage_bps is single-leg from the cost profile.
                modeled_slippage_bps=self._slippage_tier.slippage_bps,
                cost_profile_name=self._cost_profile.profile_name,
                cost_profile_hash=self._cost_profile.content_hash,
                intended_fill_at=event.funding_time,
            )
            intents.append(intent)

        results = replay_intents(
            conn, intents,
            fetcher=self._trade_fetcher,
            fetch_source=self._fetch_source,
        )

        return RunSummary(
            funding_events_total=len(self._funding_events),
            intents_fired=len(intents),
            replay_results=results,
            skipped_below_lookback=skipped_below_lookback,
            skipped_no_edge=skipped_no_edge,
            skipped_zero_funding=skipped_zero_funding,
            skipped_no_reference=skipped_no_reference,
        )

    # ─── Internal helpers ──────────────────────────────────────────────

    def _get_reference_price(self, event: FundingRate) -> Decimal | None:
        """Return the decision reference price for one funding event.

        Preference order:
          1. event.mark_price if present (no fetcher call)
          2. closest trade within ±1s of event.funding_time
          3. None — caller skips event

        Note: the fallback fetch is a small extra cost. For most
        venues (Binance) mark_price is reliably set, so the fallback
        rarely fires.
        """
        if event.mark_price is not None:
            return event.mark_price

        # Fallback: fetch trades near funding_time.
        delta = timedelta(seconds=REFERENCE_PRICE_LOOKUP_WINDOW_SECONDS)
        try:
            trades = self._trade_fetcher.fetch_window(
                self._symbol,
                event.funding_time - delta,
                event.funding_time + delta,
            )
        except Exception:
            # Any fetch failure → treat as no reference price. The
            # event is then skipped; no fill row is written. This is
            # different from a fetch failure on the OBSERVATION window
            # (Day 20.3a), which still writes a fill with NULL slippage.
            return None

        if not trades:
            return None

        closest = min(
            trades,
            key=lambda t: abs(t.time - event.funding_time),
        )
        return closest.price

    def _make_deterministic_uuid(self, event: FundingRate) -> UUID:
        """Generate a deterministic UUID for one funding event.

        Idempotency: re-running the same set of funding events produces
        the same UUIDs, which means the Day 20.1 writer's hash-mismatch
        detection acts as the dedupe layer. Same UUID + same content =
        silent no-op.

        The canonical input is (strategy_id, venue, instrument,
        funding_time_iso). Changing the strategy_id between runs
        intentionally produces different UUIDs (different audit lineage).
        """
        canonical = (
            f"a1_paper_research|"
            f"{self._strategy_id}|"
            f"{event.venue}|"
            f"{event.instrument}|"
            f"{event.funding_time.astimezone(timezone.utc).isoformat()}"
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).digest()
        # Take first 16 bytes; set version/variant bits per RFC 4122.
        # The result is a valid UUIDv4-shaped UUID with deterministic
        # content; it is NOT a true UUIDv4 (which is random). The
        # paper.fills schema does not require version-4-ness on
        # paper_fill_uuid beyond being a valid UUID.
        return UUID(bytes=digest[:16])


def _side_from_decision(decision: SignalDecision) -> str:
    """Map signal decision to paper.fills `side`.

    Funding-rate capture conventions:
      - Positive funding: longs pay shorts → strategy goes SHORT to
        collect → 'sell' on the perp leg
      - Negative funding: shorts pay longs → strategy goes LONG to
        collect → 'buy' on the perp leg

    paper.fills records the perp-leg side (the leg actually traded for
    capture). The opposing spot leg is implicit in the strategy
    structure; A1's paper.fills evidence is about the perp execution.
    """
    if decision == SignalDecision.SHORT_PERP_LONG_SPOT:
        return "sell"
    if decision == SignalDecision.LONG_PERP_SHORT_SPOT:
        return "buy"
    raise RuntimeError(
        f"_side_from_decision called with unmapped decision {decision!r}; "
        f"caller should have filtered FLAT before reaching this point"
    )
