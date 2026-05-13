"""Replay orchestrator: fetch trades, compute observation, write fill row.

Day 20.3a deliverable: takes a list of replay intents and produces
exactly one paper.fills row per intent, regardless of observation
success. The fill row's observed_slippage_bps is populated on success,
NULL otherwise; metadata records the exact replay status and trade
count.

Three replay outcomes per intent:
  - success: trades found, observation computed, slippage recorded
  - empty_window: fetcher returned no trades in window, slippage NULL
  - fetch_error: fetcher raised, slippage NULL, error captured in metadata

Reviewer-locked design (Day 20.3):
  - Window: ±5 seconds around intended_fill_at (hardcoded constant)
  - fetch_source: caller-declared ('archive' or 'rest')
  - source_mode: PAPER_RESEARCH only (DB enforces; writer rejects others)
  - promotion_eligible: false (DB enforces via CHECK)
  - Every intent writes one row; no silent skips

Idempotency: paper_fill_uuid is caller-provided. The Day 20.1 writer's
hash-mismatch detection means re-running the same intent twice with
identical content is a silent no-op; re-running with different content
raises FillIntegrityError. Callers wanting deterministic replay should
derive paper_fill_uuid from intent identity (e.g. hash of intent_uuid
or similar stable input).

A1 runner integration is Day 20.4; this module is strategy-agnostic.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final, Protocol
from uuid import UUID

from data.ingestion.vendors.binance.trade import BinanceTrade
from data.ingestion.vendors.binance.trade_fetcher import (
    PermanentFetcherError,
    TransientFetcherError,
)
from execution.paper.fill_writer import (
    PaperFillCandidate,
    write_paper_fill,
)
from execution.paper.replay_observation import (
    ReplayObservation,
    compute_observed_slippage,
)


WINDOW_SECONDS: Final[int] = 5  # hardcoded per reviewer Day 20.3 scope
VALID_FETCH_SOURCES: Final[frozenset[str]] = frozenset({"archive", "rest"})

# Cap error_message in metadata so an enormous traceback string does not
# explode the JSONB column.
_MAX_ERROR_MESSAGE_LEN: Final[int] = 500


class TradeFetcher(Protocol):
    """Either BinanceTradeFetcher (REST) or BinanceArchiveTradeFetcher.

    Both expose fetch_window(symbol, start, end) → list[BinanceTrade].
    """

    def fetch_window(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> list[BinanceTrade]: ...


@dataclass(frozen=True)
class PaperReplayIntent:
    """A single intent to observe via replay.

    Fields chosen so PaperFillCandidate can be constructed from this
    plus the observation result alone. No strategy-specific logic.

    paper_fill_uuid: caller-controlled; should be deterministic from
        intent identity for idempotent replay.
    decision_reference_price: price at signal-evaluation time. This is
        what the slippage is measured against, NOT the fill price.
    intended_fill_at: timestamp the orchestrator centers the ±5s window on.
    """

    paper_fill_uuid: UUID
    strategy_id: int
    portfolio_id: int
    account_id: int
    instrument_id: int
    symbol: str
    side: str
    quantity: Decimal
    decision_reference_price: Decimal
    modeled_slippage_bps: Decimal
    cost_profile_name: str
    cost_profile_hash: str
    intended_fill_at: datetime
    order_intent_id: int | None = None
    order_id: int | None = None
    extra_metadata: dict | None = None

    def __post_init__(self) -> None:
        if self.intended_fill_at.tzinfo is None:
            raise ValueError("intended_fill_at must be timezone-aware")
        if self.decision_reference_price <= 0:
            raise ValueError(
                f"decision_reference_price must be positive, "
                f"got {self.decision_reference_price}"
            )


@dataclass(frozen=True)
class ReplayResult:
    """One row's outcome from replay_intents.

    Order corresponds to the input intents list.
    """

    paper_fill_uuid: UUID
    replay_status: str  # 'success' | 'empty_window' | 'fetch_error'
    trade_count: int
    observed_slippage_bps: Decimal | None


def replay_intents(
    conn,
    intents: list[PaperReplayIntent],
    *,
    fetcher: TradeFetcher,
    fetch_source: str,
    window_seconds: int = WINDOW_SECONDS,
) -> list[ReplayResult]:
    """Replay each intent against the fetcher and write paper.fills rows.

    Args:
        conn: psycopg connection. Caller owns transaction; this function
            does not commit.
        intents: list of PaperReplayIntent. Each produces exactly one
            paper.fills row.
        fetcher: TradeFetcher implementation (REST or archive).
        fetch_source: 'archive' or 'rest'; recorded in metadata.
        window_seconds: ±window in seconds (default 5 per reviewer).

    Returns:
        List of ReplayResult, one per input intent, in input order.
    """
    if fetch_source not in VALID_FETCH_SOURCES:
        raise ValueError(
            f"fetch_source must be 'archive' or 'rest', got {fetch_source!r}"
        )
    if window_seconds <= 0:
        raise ValueError(
            f"window_seconds must be positive, got {window_seconds}"
        )

    results: list[ReplayResult] = []
    for intent in intents:
        result = _replay_one(
            conn, intent, fetcher, fetch_source, window_seconds,
        )
        results.append(result)
    return results


def _replay_one(
    conn,
    intent: PaperReplayIntent,
    fetcher: TradeFetcher,
    fetch_source: str,
    window_seconds: int,
) -> ReplayResult:
    """Replay a single intent: fetch + observe + write."""
    window_delta = timedelta(seconds=window_seconds)
    window_start = intent.intended_fill_at - window_delta
    window_end = intent.intended_fill_at + window_delta

    observed_slippage_bps: Decimal | None = None
    # Caller-supplied metadata first (so audit keys take precedence on collision).
    metadata: dict = dict(intent.extra_metadata or {})
    metadata.update({
        "window_seconds": window_seconds,
        "fetch_source": fetch_source,
    })
    replay_status: str
    trade_count: int

    try:
        trades = fetcher.fetch_window(
            intent.symbol, window_start, window_end,
        )
    except (PermanentFetcherError, TransientFetcherError) as e:
        metadata["replay_status"] = "fetch_error"
        metadata["trade_count"] = 0
        metadata["error_type"] = type(e).__name__
        metadata["error_message"] = str(e)[:_MAX_ERROR_MESSAGE_LEN]
        replay_status = "fetch_error"
        trade_count = 0
    else:
        obs = compute_observed_slippage(
            trades=trades,
            side=intent.side,
            reference_price=intent.decision_reference_price,
        )
        metadata["replay_status"] = obs.status
        metadata["trade_count"] = obs.trade_count
        replay_status = obs.status
        trade_count = obs.trade_count
        if obs.status == "success":
            observed_slippage_bps = obs.observed_slippage_bps
            metadata["extreme_price"] = str(obs.extreme_price)

    candidate = PaperFillCandidate(
        paper_fill_uuid=intent.paper_fill_uuid,
        source_mode="PAPER_RESEARCH",
        strategy_id=intent.strategy_id,
        portfolio_id=intent.portfolio_id,
        account_id=intent.account_id,
        instrument_id=intent.instrument_id,
        order_intent_id=intent.order_intent_id,
        order_id=intent.order_id,
        side=intent.side,
        quantity=intent.quantity,
        # The recorded "price" is the decision-time reference. The actual
        # fill price (or extreme thereof) is recorded in metadata, not
        # in the price column, because we don't have a single canonical
        # "fill price" — the window is a range.
        price=intent.decision_reference_price,
        modeled_slippage_bps=intent.modeled_slippage_bps,
        observed_slippage_bps=observed_slippage_bps,
        cost_profile_name=intent.cost_profile_name,
        cost_profile_hash=intent.cost_profile_hash,
        filled_at=intent.intended_fill_at,
        metadata=metadata,
    )

    write_paper_fill(conn, candidate)

    return ReplayResult(
        paper_fill_uuid=intent.paper_fill_uuid,
        replay_status=replay_status,
        trade_count=trade_count,
        observed_slippage_bps=observed_slippage_bps,
    )
