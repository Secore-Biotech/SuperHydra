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
    open_position,
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
    replay_results: list[ReplayResult]


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
        """Process observations and write paper.fills rows.

        Caller owns the transaction; this method does not commit.
        """
        intents: list[PaperReplayIntent] = []
        skip_insufficient = 0
        skip_stale = 0
        skip_zero_stdev = 0
        skip_z_below = 0
        skip_cost_not_cleared = 0
        skip_already_positioned = 0
        evaluations_total = 0
        # Day 28a: in-memory anti-reentry state. Position writes go to
        # paper.positions after replay_intents succeeds.
        positioned = False
        perp_intent_captured = None
        spot_intent_captured = None
        position_opened_at = None

        n = len(self._observations)
        for i in range(n):
            # Build window: last window_size observations up to and
            # including index i. For i < window_size-1, the window is
            # shorter than window_size, and the evaluator's min_lookback
            # check handles insufficient cases.
            window_size = self._signal_config.window_size
            start = max(0, i - window_size + 1)
            window = self._observations[start:i + 1]
            current_obs = self._observations[i]

            # as_of must be strictly after the latest sample. Use latest
            # sample + 1 second for deterministic synthetic-fixture runs.
            # In production this would be the real evaluation moment.
            as_of = current_obs.sampled_at + timedelta(seconds=1)

            evaluation = evaluate_a2_signal(
                window,
                self._cost_threshold_bps,
                as_of=as_of,
                config=self._signal_config,
            )
            evaluations_total += 1

            # Skip taxonomy
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

            # Day 28a: hard-block anti-reentry. Once we have fired,
            # all subsequent non-FLAT decisions are skipped.
            if positioned:
                skip_already_positioned += 1
                continue

            # Non-FLAT decision: construct 2 intents (perp + spot legs).
            new_intents = self._build_intents(current_obs, evaluation)
            intents.extend(new_intents)

            # Capture position data for the post-replay paper.positions
            # write. _build_intents returns [perp_intent, spot_intent].
            perp_intent_captured = new_intents[0]
            spot_intent_captured = new_intents[1]
            position_opened_at = as_of
            positioned = True

        results = replay_intents(
            conn, intents,
            fetcher=self._trade_fetcher,
            fetch_source=self._fetch_source,
        )

        # Day 28a: persist paper.positions for the (at most one) intent that
        # fired. paper.positions is materialized state; source of truth remains
        # paper.fills. The UNIQUE (strategy_id, instrument_id) constraint is
        # the DB-level backstop for the in-loop anti-reentry flag above.
        if positioned:
            a2_iuuid = perp_intent_captured.extra_metadata["a2_intent_uuid"]
            open_position(
                conn,
                strategy_id=self._strategy_id,
                portfolio_id=self._portfolio_id,
                account_id=self._account_id,
                instrument_id=self._perp_instrument_id,
                quantity=(
                    perp_intent_captured.quantity
                    if perp_intent_captured.side == "buy"
                    else -perp_intent_captured.quantity
                ),
                avg_entry_price=perp_intent_captured.decision_reference_price,
                opened_at=position_opened_at,
                metadata={
                    "a2_intent_uuid": a2_iuuid,
                    "a2_leg": "perp",
                    "entry_paper_fill_uuid": str(perp_intent_captured.paper_fill_uuid),
                },
            )
            open_position(
                conn,
                strategy_id=self._strategy_id,
                portfolio_id=self._portfolio_id,
                account_id=self._account_id,
                instrument_id=self._spot_instrument_id,
                quantity=(
                    spot_intent_captured.quantity
                    if spot_intent_captured.side == "buy"
                    else -spot_intent_captured.quantity
                ),
                avg_entry_price=spot_intent_captured.decision_reference_price,
                opened_at=position_opened_at,
                metadata={
                    "a2_intent_uuid": a2_iuuid,
                    "a2_leg": "spot",
                    "entry_paper_fill_uuid": str(spot_intent_captured.paper_fill_uuid),
                },
            )

        # Number of A2 intents fired = half the replay results (one per leg).
        a2_intents_fired = len(intents) // 2

        return A2RunSummary(
            evaluations_total=evaluations_total,
            evaluations_skipped_insufficient_lookback=skip_insufficient,
            evaluations_skipped_stale_window=skip_stale,
            evaluations_skipped_zero_or_near_zero_stdev=skip_zero_stdev,
            evaluations_skipped_z_below_threshold=skip_z_below,
            evaluations_skipped_cost_not_cleared=skip_cost_not_cleared,
            evaluations_skipped_already_positioned=skip_already_positioned,
            a2_intents_fired=a2_intents_fired,
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
