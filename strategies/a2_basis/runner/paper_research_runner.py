"""A2 PAPER_RESEARCH runner.

Day 24 deliverable: composes the Day 23 z-score signal evaluator with
the Day 22 cost-threshold helper and the Day 20.3a replay observation
infrastructure to produce paper.fills evidence for the A2 perp-vs-spot
basis engine.

Hard constraints (Day 24 reviewer lock):
  - No A1 imports
  - No trading.fills writes
  - Two paper.fills rows per A2 intent (one perp leg, one spot leg)
  - Shared a2_intent_uuid in metadata
  - Per-leg paper_fill_uuid deterministic from intent_uuid
  - Single-venue Binance only
  - No operator CLI (deferred to Day 25)
  - No real data ingestion (deferred to Day 26+)
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterable
from uuid import UUID

from core.config.cost_model import CostModelConfig
from execution.paper.replay_runner import (
    PaperReplayIntent,
    ReplayResult,
    TradeFetcher,
    replay_intents,
)
from strategies.a2_basis.config.profile_selector import (
    A2CostBundle,
    select_research_profile_for_a2,
)
from strategies.a2_basis.signal.cost_threshold import (
    compute_a2_round_trip_threshold_bps,
)
from strategies.a2_basis.data.positions import (
    close_position,
    open_position,
)
from strategies.a2_basis.signal.evaluate_exit import (
    A2ExitConfig,
    A2ExitDecision,
    A2ExitEvaluation,
    A2ExitReason,
    evaluate_a2_exit_signal,
)
from strategies.a2_basis.signal.evaluate import (
    A2SignalConfig,
    A2SignalDecision,
    A2SignalEvaluation,
    BasisObservation,
    evaluate_a2_signal,
)


# Default uncertainty margin per Day 22 reviewer lock.
DEFAULT_UNCERTAINTY_MARGIN_FRACTION: Decimal = Decimal("0.2")


# ─── Tier name selection (mirrors Day 22 profile_selector semantics) ────


_BTC_ETH_INSTRUMENTS: frozenset[str] = frozenset({"BTCUSDT", "ETHUSDT"})
_LIQUID_ALT_INSTRUMENTS: frozenset[str] = frozenset({"SOLUSDT"})


def _slippage_tier_names_for(base_symbol: str) -> tuple[str, str]:
    """Return (perp_tier_name, spot_tier_name) for the given symbol.

    Mirrors profile_selector's instrument-to-tier mapping. Kept in sync
    with that module by sharing the same instrument sets.
    """
    if base_symbol in _BTC_ETH_INSTRUMENTS:
        return ("btc_eth_top_tier", "spot_btc_eth_top_tier")
    if base_symbol in _LIQUID_ALT_INSTRUMENTS:
        return ("liquid_alt_tier", "spot_liquid_alt_tier")
    raise ValueError(
        f"No A2 slippage tier mapping for {base_symbol!r}. "
        f"Currently supported: {sorted(_BTC_ETH_INSTRUMENTS | _LIQUID_ALT_INSTRUMENTS)}"
    )


# ─── Fixture loader ──────────────────────────────────────────────────────


def load_basis_fixture(path: Path) -> list[BasisObservation]:
    """Load a list of BasisObservation from a JSON fixture file.

    Fixture format:
      {
        "venue": "binance",
        "symbol": "SOLUSDT",
        "observations": [
          {"sampled_at": "2024-01-01T12:00:00Z",
           "perp_price": "100.00", "spot_price": "100.00"},
          ...
        ]
      }
    """
    data = json.loads(path.read_text())
    observations: list[BasisObservation] = []
    for obs in data["observations"]:
        ts_str = obs["sampled_at"]
        # Handle ISO 8601 with trailing Z (Python <3.11 quirk)
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        sampled_at = datetime.fromisoformat(ts_str)
        observations.append(BasisObservation(
            sampled_at=sampled_at,
            perp_price=Decimal(obs["perp_price"]),
            spot_price=Decimal(obs["spot_price"]),
        ))
    return observations


# ─── Run summary ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class A2RunSummary:
    """Per-run counters and replay results for one A2 paper-research run.

    evaluations_total: how many times the evaluator was called (one per
        observation past min_lookback boundary; observations before
        min_lookback don't even reach the evaluator)
    evaluations_skipped_*: count by FLAT reason
    a2_intents_fired: number of non-FLAT decisions (each produces 2
        paper.fills rows: one perp, one spot)
    replay_results: per-leg replay outcomes. len(replay_results) ==
        2 * a2_intents_fired.
    """

    evaluations_total: int
    evaluations_skipped_insufficient_lookback: int
    evaluations_skipped_stale_window: int
    evaluations_skipped_zero_or_near_zero_stdev: int
    evaluations_skipped_z_below_threshold: int
    evaluations_skipped_cost_not_cleared: int
    evaluations_skipped_already_positioned: int
    a2_intents_fired: int
    # Day 28b.2 — exit-side counters (mirrored by reason)
    exit_evaluations_total: int
    exit_evaluations_hold_insufficient_lookback: int
    exit_evaluations_hold_stale_window: int
    exit_evaluations_hold_zero_or_near_zero_stdev: int
    exit_evaluations_hold_still_dislocated: int
    a2_exits_fired_basis_converged: int
    a2_exits_fired_time_forced: int
    positions_open_at_end_of_run: int
    replay_results: list[ReplayResult]



# ─── P&L computation helper ──────────────────────────────────────────────


def _compute_leg_pnl_bps(
    *,
    entry_price: Decimal,
    exit_price: Decimal,
    entry_side: str,
) -> Decimal:
    """Profit-positive realized P&L for one leg, in bps.

    DAY 28B.2 PROFIT-POSITIVE SEMANTIC (reviewer lock Q2):

        Result > 0  ⇔  leg made money
        Result == 0 ⇔  flat
        Result < 0  ⇔  leg lost money

    FORMULAS BY LEG DIRECTION:

      LONG leg (entry_side == "buy"):
        Bought at entry_price; sold at exit_price.
        Profit when exit > entry (price went up).
            pnl_bps = (exit_price - entry_price) / entry_price * 10000

      SHORT leg (entry_side == "sell"):
        Sold at entry_price; bought back at exit_price.
        Profit when exit < entry (price went down).
            pnl_bps = (entry_price - exit_price) / entry_price * 10000

    EXAMPLE — SHORT_PERP_LONG_SPOT trade:
        Entry: perp_side="sell" at 100.85; spot_side="buy" at 100.00.
        Exit:  perp at 100.00; spot at 100.00.

        perp_pnl_bps = (100.85 - 100.00) / 100.85 * 10000
                     = 0.85 / 100.85 * 10000
                     = 84.28 bps profit  (short converged: good)

        spot_pnl_bps = (100.00 - 100.00) / 100.00 * 10000
                     = 0.00 bps  (spot flat: neutral)

        gross_pnl_bps = 84.28 bps
        round_trip_cost_bps = 33.84 (SOL — includes ~20% safety margin)
        net_pnl_bps = 84.28 - 33.84 = 50.44 bps profit

    NORMALIZATION:
        Denominator is entry_price. Convention: P&L measured as
        percentage of capital deployed at entry, expressed in bps
        (1 bp = 0.01%).

    Raises:
        ValueError: if entry_side is not "buy" or "sell".
    """
    if entry_side == "buy":
        return (exit_price - entry_price) / entry_price * Decimal(10000)
    if entry_side == "sell":
        return (entry_price - exit_price) / entry_price * Decimal(10000)
    raise ValueError(f"Unexpected entry_side: {entry_side!r}")


# ─── Runner ──────────────────────────────────────────────────────────────


class A2PaperResearchRunner:
    """A2 PAPER_RESEARCH runner.

    Composition only — does not inherit from or delegate to any A1 code.
    Strategy-specific glue under the A2 package; generic replay/fill
    machinery remains under execution/paper/.

    Caller flow:
        runner = A2PaperResearchRunner(
            basis_source=load_basis_fixture(fixture_path),
            trade_fetcher=NoopFetcher(),
            fetch_source="archive",
            strategy_id=..., portfolio_id=..., account_id=...,
            perp_instrument_id=..., spot_instrument_id=...,
            venue="binance",
            base_symbol="SOLUSDT",
            quantity_per_intent=Decimal("10.0"),
        )
        summary = runner.run(conn)
        conn.commit()
    """

    def __init__(
        self,
        *,
        basis_source: Iterable[BasisObservation],
        trade_fetcher: TradeFetcher,
        fetch_source: str,
        strategy_id: int,
        portfolio_id: int,
        account_id: int,
        perp_instrument_id: int,
        spot_instrument_id: int,
        venue: str,
        base_symbol: str,
        quantity_per_intent: Decimal,
        exit_config: A2ExitConfig | None = None,
        cost_bundle: A2CostBundle | None = None,
        uncertainty_margin_fraction: Decimal = DEFAULT_UNCERTAINTY_MARGIN_FRACTION,
        signal_config: A2SignalConfig | None = None,
    ) -> None:
        if quantity_per_intent <= 0:
            raise ValueError(
                f"quantity_per_intent must be positive, got {quantity_per_intent}"
            )
        if fetch_source not in ("archive", "rest"):
            raise ValueError(
                f"fetch_source must be 'archive' or 'rest', got {fetch_source!r}"
            )

        # Materialize observations eagerly to validate ordering once.
        self._observations: list[BasisObservation] = list(basis_source)

        if self._observations:
            times = [o.sampled_at for o in self._observations]
            for i in range(1, len(times)):
                if times[i] <= times[i - 1]:
                    raise ValueError(
                        f"observations must be strictly ascending by "
                        f"sampled_at; got {times[i - 1]} >= {times[i]} "
                        f"at index {i}"
                    )

        # Resolve cost bundle (perp + spot profiles).
        if cost_bundle is None:
            self._cost_bundle = select_research_profile_for_a2(
                base_symbol, venue,
            )
        else:
            self._cost_bundle = cost_bundle

        # Resolve tier names from base_symbol.
        perp_tier_name, spot_tier_name = _slippage_tier_names_for(base_symbol)
        self._perp_tier_name = perp_tier_name
        self._spot_tier_name = spot_tier_name

        # Pre-compute cost threshold once per run; same for every evaluation.
        cost = compute_a2_round_trip_threshold_bps(
            self._cost_bundle,
            perp_slippage_tier_name=perp_tier_name,
            spot_slippage_tier_name=spot_tier_name,
            uncertainty_margin_fraction=uncertainty_margin_fraction,
        )
        self._cost_threshold_bps = cost.total_threshold_bps
        # Day 28b.2: exit-side configuration. Defaults to A2ExitConfig()
        # which encodes the reviewer-locked 4h max-holding window.
        self._exit_config = exit_config or A2ExitConfig()
        self._round_trip_cost = cost

        # Resolve per-leg modeled slippage in bps (for paper.fills rows).
        perp_tier = next(
            t for t in self._cost_bundle.perp_profile.slippage_tiers
            if t.tier_name == perp_tier_name
        )
        spot_tier = next(
            t for t in self._cost_bundle.spot_profile.slippage_tiers
            if t.tier_name == spot_tier_name
        )
        # Slippage stored as fraction-of-notional (Decimal 0.0001 = 1 bp)
        # in the cost model; paper.fills's modeled_slippage_bps column
        # uses the same fraction representation per Day 20.1's writer.
        self._perp_modeled_slippage_bps = perp_tier.slippage_bps
        self._spot_modeled_slippage_bps = spot_tier.slippage_bps

        self._trade_fetcher = trade_fetcher
        self._fetch_source = fetch_source
        self._strategy_id = strategy_id
        self._portfolio_id = portfolio_id
        self._account_id = account_id
        self._perp_instrument_id = perp_instrument_id
        self._spot_instrument_id = spot_instrument_id
        self._venue = venue
        self._base_symbol = base_symbol
        self._quantity_per_intent = quantity_per_intent
        self._signal_config = signal_config or A2SignalConfig()

    # ─── Public API ────────────────────────────────────────────────────

    def run(self, conn) -> A2RunSummary:
        """Process observations with interleaved entry/exit logic.

        Day 28b.2: per reviewer-locked design (Q5a/Q5b/Q5c):
          - Each observation triggers exactly one of three paths:
            (1) exit-eval if currently positioned,
            (2) entry-eval if not positioned,
            (3) skip with appropriate counter.
          - DELETE paper.positions inside the loop on close (same txn).
          - Re-entry allowed unbounded within a single run.
          - Positions still open at end-of-run are written to paper.positions
            (paper.fills carries the full audit; paper.positions is the
            materialized state of CURRENTLY-OPEN positions only).

        Caller owns the transaction; this method does not commit.
        """
        intents: list[PaperReplayIntent] = []
        # Entry counters (existing Day 24/28a)
        skip_insufficient = 0
        skip_stale = 0
        skip_zero_stdev = 0
        skip_z_below = 0
        skip_cost_not_cleared = 0
        skip_already_positioned = 0
        evaluations_total = 0
        entries_fired = 0
        # Exit counters (Day 28b.2)
        exit_evaluations_total = 0
        exit_skip_insufficient_lookback = 0
        exit_skip_stale_window = 0
        exit_skip_zero_or_near_zero_stdev = 0
        exit_skip_still_dislocated = 0
        exits_fired_basis_converged = 0
        exits_fired_time_forced = 0
        # In-memory state for the (at most one) currently-open position.
        # Re-used across re-entries within the same run.
        positioned = False
        open_perp_intent: PaperReplayIntent | None = None
        open_spot_intent: PaperReplayIntent | None = None
        open_position_opened_at: datetime | None = None
        open_a2_intent_uuid: str | None = None
        # Half of the entry round-trip cost threshold, per Day 28b.2 lock.
        convergence_threshold_bps = self._cost_threshold_bps / Decimal(2)

        n = len(self._observations)
        for i in range(n):
            window_size = self._signal_config.window_size
            start = max(0, i - window_size + 1)
            window = self._observations[start:i + 1]
            current_obs = self._observations[i]
            as_of = current_obs.sampled_at + timedelta(seconds=1)

            if positioned:
                # ─── EXIT-EVALUATION PATH ─────────────────────────────
                exit_eval = evaluate_a2_exit_signal(
                    window,
                    convergence_threshold_bps=convergence_threshold_bps,
                    entry_time=open_position_opened_at,
                    as_of=as_of,
                    config=self._exit_config,
                )
                exit_evaluations_total += 1

                if exit_eval.decision == A2ExitDecision.HOLD:
                    if exit_eval.reason == A2ExitReason.INSUFFICIENT_LOOKBACK:
                        exit_skip_insufficient_lookback += 1
                    elif exit_eval.reason == A2ExitReason.STALE_WINDOW:
                        exit_skip_stale_window += 1
                    elif exit_eval.reason == A2ExitReason.ZERO_OR_NEAR_ZERO_STDEV:
                        exit_skip_zero_or_near_zero_stdev += 1
                    elif exit_eval.reason == A2ExitReason.STILL_DISLOCATED:
                        exit_skip_still_dislocated += 1
                    continue

                # CLOSE: build paired exit intents with P&L.
                exit_intents = self._build_exit_intents(
                    current_obs=current_obs,
                    exit_eval=exit_eval,
                    entry_perp_intent=open_perp_intent,
                    entry_spot_intent=open_spot_intent,
                    a2_intent_uuid=open_a2_intent_uuid,
                )
                intents.extend(exit_intents)

                # DELETE the paper.positions rows. Idempotent: if no row
                # exists (typical when entry+exit happen in same run and
                # we never wrote a row to begin with), it's a no-op.
                close_position(
                    conn,
                    strategy_id=self._strategy_id,
                    instrument_id=self._perp_instrument_id,
                )
                close_position(
                    conn,
                    strategy_id=self._strategy_id,
                    instrument_id=self._spot_instrument_id,
                )

                # Reset in-memory state. Re-entry on a later observation
                # is allowed (Q5b: unbounded).
                positioned = False
                open_perp_intent = None
                open_spot_intent = None
                open_position_opened_at = None
                open_a2_intent_uuid = None

                if exit_eval.reason == A2ExitReason.BASIS_CONVERGED:
                    exits_fired_basis_converged += 1
                elif exit_eval.reason == A2ExitReason.TIME_FORCED:
                    exits_fired_time_forced += 1
                continue

            # ─── ENTRY-EVALUATION PATH ────────────────────────────────
            evaluation = evaluate_a2_signal(
                window,
                self._cost_threshold_bps,
                as_of=as_of,
                config=self._signal_config,
            )
            evaluations_total += 1

            if evaluation.decision == A2SignalDecision.FLAT:
                if evaluation.reason == "insufficient_lookback":
                    skip_insufficient += 1
                elif evaluation.reason == "stale_window":
                    skip_stale += 1
                elif evaluation.reason == "zero_or_near_zero_stdev":
                    skip_zero_stdev += 1
                elif evaluation.reason == "z_below_threshold":
                    skip_z_below += 1
                elif evaluation.reason == "cost_not_cleared":
                    skip_cost_not_cleared += 1
                continue

            # Non-FLAT decision: construct entry intents and capture
            # in-memory state for the open position.
            new_intents = self._build_intents(current_obs, evaluation)
            intents.extend(new_intents)
            entries_fired += 1
            open_perp_intent = new_intents[0]
            open_spot_intent = new_intents[1]
            open_position_opened_at = as_of
            open_a2_intent_uuid = new_intents[0].extra_metadata["a2_intent_uuid"]
            positioned = True

        # End of loop. Replay all accumulated intents at once.
        results = replay_intents(
            conn, intents,
            fetcher=self._trade_fetcher,
            fetch_source=self._fetch_source,
        )

        # Day 28b.2 Q5c: positions still open at end-of-run are written
        # to paper.positions. Closed positions never touch the table.
        positions_open_at_end_of_run = 0
        if positioned:
            positions_open_at_end_of_run = 1
            a2_iuuid = open_perp_intent.extra_metadata["a2_intent_uuid"]
            open_position(
                conn,
                strategy_id=self._strategy_id,
                portfolio_id=self._portfolio_id,
                account_id=self._account_id,
                instrument_id=self._perp_instrument_id,
                quantity=(
                    open_perp_intent.quantity
                    if open_perp_intent.side == "buy"
                    else -open_perp_intent.quantity
                ),
                avg_entry_price=open_perp_intent.decision_reference_price,
                opened_at=open_position_opened_at,
                metadata={
                    "a2_intent_uuid": a2_iuuid,
                    "a2_leg": "perp",
                    "entry_paper_fill_uuid": str(open_perp_intent.paper_fill_uuid),
                },
            )
            open_position(
                conn,
                strategy_id=self._strategy_id,
                portfolio_id=self._portfolio_id,
                account_id=self._account_id,
                instrument_id=self._spot_instrument_id,
                quantity=(
                    open_spot_intent.quantity
                    if open_spot_intent.side == "buy"
                    else -open_spot_intent.quantity
                ),
                avg_entry_price=open_spot_intent.decision_reference_price,
                opened_at=open_position_opened_at,
                metadata={
                    "a2_intent_uuid": a2_iuuid,
                    "a2_leg": "spot",
                    "entry_paper_fill_uuid": str(open_spot_intent.paper_fill_uuid),
                },
            )

        return A2RunSummary(
            evaluations_total=evaluations_total,
            evaluations_skipped_insufficient_lookback=skip_insufficient,
            evaluations_skipped_stale_window=skip_stale,
            evaluations_skipped_zero_or_near_zero_stdev=skip_zero_stdev,
            evaluations_skipped_z_below_threshold=skip_z_below,
            evaluations_skipped_cost_not_cleared=skip_cost_not_cleared,
            evaluations_skipped_already_positioned=skip_already_positioned,
            a2_intents_fired=entries_fired,
            exit_evaluations_total=exit_evaluations_total,
            exit_evaluations_hold_insufficient_lookback=exit_skip_insufficient_lookback,
            exit_evaluations_hold_stale_window=exit_skip_stale_window,
            exit_evaluations_hold_zero_or_near_zero_stdev=exit_skip_zero_or_near_zero_stdev,
            exit_evaluations_hold_still_dislocated=exit_skip_still_dislocated,
            a2_exits_fired_basis_converged=exits_fired_basis_converged,
            a2_exits_fired_time_forced=exits_fired_time_forced,
            positions_open_at_end_of_run=positions_open_at_end_of_run,
            replay_results=results,
        )

    # ─── Internal helpers ──────────────────────────────────────────────

    def _build_intents(
        self,
        current_obs: BasisObservation,
        evaluation: A2SignalEvaluation,
    ) -> list[PaperReplayIntent]:
        """Build the two PaperReplayIntents (perp leg + spot leg) for one A2 fire."""
        # Deterministic UUIDs per Day 24.3 reviewer lock.
        intent_uuid = self._make_intent_uuid(current_obs.sampled_at)
        perp_leg_uuid = self._make_leg_uuid(intent_uuid, "perp")
        spot_leg_uuid = self._make_leg_uuid(intent_uuid, "spot")

        # Side mapping.
        perp_side, spot_side = _sides_from_decision(evaluation.decision)

        # Shared metadata across legs.
        a2_intent_uuid_str = str(intent_uuid)

        perp_intent = PaperReplayIntent(
            paper_fill_uuid=perp_leg_uuid,
            strategy_id=self._strategy_id,
            portfolio_id=self._portfolio_id,
            account_id=self._account_id,
            instrument_id=self._perp_instrument_id,
            symbol=self._base_symbol,
            side=perp_side,
            quantity=self._quantity_per_intent,
            decision_reference_price=current_obs.perp_price,
            modeled_slippage_bps=self._perp_modeled_slippage_bps,
            cost_profile_name=self._cost_bundle.perp_profile.profile_name,
            cost_profile_hash=self._cost_bundle.perp_profile.content_hash,
            intended_fill_at=current_obs.sampled_at,
            extra_metadata={
                "a2_intent_uuid": a2_intent_uuid_str,
                "a2_leg": "perp",
                "a2_phase": "entry",
            },
        )

        spot_intent = PaperReplayIntent(
            paper_fill_uuid=spot_leg_uuid,
            strategy_id=self._strategy_id,
            portfolio_id=self._portfolio_id,
            account_id=self._account_id,
            instrument_id=self._spot_instrument_id,
            symbol=self._base_symbol,
            side=spot_side,
            quantity=self._quantity_per_intent,
            decision_reference_price=current_obs.spot_price,
            modeled_slippage_bps=self._spot_modeled_slippage_bps,
            cost_profile_name=self._cost_bundle.spot_profile.profile_name,
            cost_profile_hash=self._cost_bundle.spot_profile.content_hash,
            intended_fill_at=current_obs.sampled_at,
            extra_metadata={
                "a2_intent_uuid": a2_intent_uuid_str,
                "a2_leg": "spot",
                "a2_phase": "entry",
            },
        )

        return [perp_intent, spot_intent]

    def _make_intent_uuid(self, eval_time: datetime) -> UUID:
        """Deterministic UUID for one A2 intent.

        Idempotency: re-running the same observations produces the same
        intent UUID. The Day 20.1 writer's hash-mismatch detection
        means re-running with identical content is a silent no-op.
        """
        canonical = (
            f"a2_basis_research|intent|"
            f"{self._strategy_id}|"
            f"{self._venue}|"
            f"{self._base_symbol}|"
            f"{eval_time.astimezone(timezone.utc).isoformat()}"
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).digest()
        return UUID(bytes=digest[:16])

    def _make_leg_uuid(self, intent_uuid: UUID, leg: str) -> UUID:
        """Deterministic UUID for one leg (perp or spot) of an A2 intent."""
        if leg not in ("perp", "spot"):
            raise ValueError(f"leg must be 'perp' or 'spot', got {leg!r}")
        canonical = f"a2_basis_research|{leg}|{intent_uuid}"
        digest = hashlib.sha256(canonical.encode("utf-8")).digest()
        return UUID(bytes=digest[:16])


    def _build_exit_intents(
        self,
        *,
        current_obs: BasisObservation,
        exit_eval: A2ExitEvaluation,
        entry_perp_intent: PaperReplayIntent,
        entry_spot_intent: PaperReplayIntent,
        a2_intent_uuid: str,
    ) -> list[PaperReplayIntent]:
        """Build the two PaperReplayIntents for an exit (close).

        Per Day 28b.2 reviewer locks:
          - Q1: deterministic UUID from (strategy_id, instrument_id,
                exit_sampled_at, side, quantity, a2_intent_uuid).
          - Q2: profit-positive P&L plus per-leg fields for audit.
          - Q3: same cost_profile_name as entry.
          - Q4 not relevant here (summary-side concern).
          - Q5a not relevant here (timing concern in run()).

        Exit fills mirror the structure of entry fills with these key
        differences in extra_metadata:
          - a2_phase = "exit" (vs entry's "entry")
          - a2_exit_reason carries the A2ExitReason value
          - a2_entry_paper_fill_uuid points to the entry leg
          - research_perp_pnl_bps, research_spot_pnl_bps: per-leg P&L
          - research_gross_pnl_bps: sum across legs (pre-cost)
          - research_round_trip_cost_bps: full round-trip cost
            (uses self._cost_threshold_bps; see comment on
            research_round_trip_cost_bps in this method)
          - research_pnl_bps: net realized P&L = gross - cost
        """
        # Inverse sides: closing a SHORT means BUYing back; closing a LONG
        # means SELLing.
        perp_exit_side = "buy" if entry_perp_intent.side == "sell" else "sell"
        spot_exit_side = "buy" if entry_spot_intent.side == "sell" else "sell"

        # Per-leg P&L, profit-positive (see _compute_leg_pnl_bps docstring).
        perp_pnl_bps = _compute_leg_pnl_bps(
            entry_price=entry_perp_intent.decision_reference_price,
            exit_price=current_obs.perp_price,
            entry_side=entry_perp_intent.side,
        )
        spot_pnl_bps = _compute_leg_pnl_bps(
            entry_price=entry_spot_intent.decision_reference_price,
            exit_price=current_obs.spot_price,
            entry_side=entry_spot_intent.side,
        )
        gross_pnl_bps = perp_pnl_bps + spot_pnl_bps

        # research_round_trip_cost_bps: conservative estimate using the
        # entry threshold (which includes a ~20% safety margin per the
        # Day 22 cost model). This means research_pnl_bps is slightly
        # pessimistic vs the true post-fee P&L; refinement to actual
        # round-trip cost (sans margin) is a Day 28b.3+ improvement.
        round_trip_cost_bps = self._cost_threshold_bps
        net_pnl_bps = gross_pnl_bps - round_trip_cost_bps

        # Deterministic exit UUIDs (Q1 lock).
        perp_exit_uuid = self._make_exit_leg_uuid(
            a2_intent_uuid=a2_intent_uuid,
            leg="perp",
            exit_sampled_at=current_obs.sampled_at,
            side=perp_exit_side,
        )
        spot_exit_uuid = self._make_exit_leg_uuid(
            a2_intent_uuid=a2_intent_uuid,
            leg="spot",
            exit_sampled_at=current_obs.sampled_at,
            side=spot_exit_side,
        )

        # Common P&L metadata applied to both legs.
        common_pnl_metadata = {
            "a2_phase": "exit",
            "a2_exit_reason": exit_eval.reason.value,
            "a2_holding_duration_seconds": exit_eval.holding_duration_seconds,
            "research_perp_pnl_bps": str(perp_pnl_bps),
            "research_spot_pnl_bps": str(spot_pnl_bps),
            "research_gross_pnl_bps": str(gross_pnl_bps),
            "research_round_trip_cost_bps": str(round_trip_cost_bps),
            "research_pnl_bps": str(net_pnl_bps),
        }
        if exit_eval.current_basis_bps is not None:
            common_pnl_metadata["a2_exit_basis_bps"] = str(
                exit_eval.current_basis_bps
            )

        perp_intent = PaperReplayIntent(
            paper_fill_uuid=perp_exit_uuid,
            strategy_id=self._strategy_id,
            portfolio_id=self._portfolio_id,
            account_id=self._account_id,
            instrument_id=self._perp_instrument_id,
            symbol=self._base_symbol,
            side=perp_exit_side,
            quantity=self._quantity_per_intent,
            decision_reference_price=current_obs.perp_price,
            modeled_slippage_bps=self._perp_modeled_slippage_bps,
            cost_profile_name=self._cost_bundle.perp_profile.profile_name,
            cost_profile_hash=self._cost_bundle.perp_profile.content_hash,
            intended_fill_at=current_obs.sampled_at,
            extra_metadata={
                **common_pnl_metadata,
                "a2_intent_uuid": a2_intent_uuid,
                "a2_leg": "perp",
                "a2_entry_paper_fill_uuid": str(entry_perp_intent.paper_fill_uuid),
            },
        )
        spot_intent = PaperReplayIntent(
            paper_fill_uuid=spot_exit_uuid,
            strategy_id=self._strategy_id,
            portfolio_id=self._portfolio_id,
            account_id=self._account_id,
            instrument_id=self._spot_instrument_id,
            symbol=self._base_symbol,
            side=spot_exit_side,
            quantity=self._quantity_per_intent,
            decision_reference_price=current_obs.spot_price,
            modeled_slippage_bps=self._spot_modeled_slippage_bps,
            cost_profile_name=self._cost_bundle.spot_profile.profile_name,
            cost_profile_hash=self._cost_bundle.spot_profile.content_hash,
            intended_fill_at=current_obs.sampled_at,
            extra_metadata={
                **common_pnl_metadata,
                "a2_intent_uuid": a2_intent_uuid,
                "a2_leg": "spot",
                "a2_entry_paper_fill_uuid": str(entry_spot_intent.paper_fill_uuid),
            },
        )

        return [perp_intent, spot_intent]

    def _make_exit_leg_uuid(
        self,
        *,
        a2_intent_uuid: str,
        leg: str,
        exit_sampled_at: datetime,
        side: str,
    ) -> UUID:
        """Deterministic UUID for an exit-leg fill.

        Per Day 28b.2 Q1 lock: inputs are strategy_id, instrument_id,
        exit_sampled_at, side, quantity, a2_intent_uuid.

        Including a2_intent_uuid eliminates the (rare) collision risk
        where a future re-entry-then-exit on the same instrument at the
        same sampled_at + side + quantity would otherwise produce the
        same UUID as a prior exit.
        """
        instrument_id = (
            self._perp_instrument_id if leg == "perp"
            else self._spot_instrument_id
        )
        canonical = (
            f"a2_basis_research|exit|"
            f"{self._strategy_id}|"
            f"{instrument_id}|"
            f"{exit_sampled_at.astimezone(timezone.utc).isoformat()}|"
            f"{side}|"
            f"{self._quantity_per_intent}|"
            f"{a2_intent_uuid}"
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).digest()
        return UUID(bytes=digest[:16])


def _sides_from_decision(decision: A2SignalDecision) -> tuple[str, str]:
    """Map A2 decision to (perp_side, spot_side).

    A2 basis-trade conventions:
      - SHORT_PERP_LONG_SPOT (positive dislocation, expect convergence down):
        perp short = 'sell'; spot long = 'buy'
      - LONG_PERP_SHORT_SPOT (negative dislocation, expect convergence up):
        perp long = 'buy'; spot short = 'sell'
    """
    if decision == A2SignalDecision.SHORT_PERP_LONG_SPOT:
        return ("sell", "buy")
    if decision == A2SignalDecision.LONG_PERP_SHORT_SPOT:
        return ("buy", "sell")
    raise RuntimeError(
        f"_sides_from_decision called with unmapped decision {decision!r}; "
        f"FLAT decisions should have been filtered before reaching this point"
    )
