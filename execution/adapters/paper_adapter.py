"""Paper trading execution adapter — abstract base.

The roadmap (§3.1.1) requires that paper runs use the exact OMS / risk /
ledger code path that canary uses. The only thing that changes between
paper and canary is the execution surface: paper synthesizes fills
deterministically; canary submits to a real venue.

This module defines the contract every paper adapter must satisfy.
A concrete implementation lives separately and is wired in Day 8 of the
A1 build (the vertical smoke test). Nothing in this file performs any
fill synthesis — it's a contract definition only.

Determinism requirement: a paper adapter must be deterministic with
respect to (order_intent, market_snapshot, cost_model_hash, simulation_seed).
The same four inputs must produce the same fill output. This is what makes
paper Sharpe reproducible.

Audit requirement: every paper fill emitted carries the cost_model_hash
and simulation_seed as lineage. The reconciler reads this lineage when
deciding whether two paper runs are comparable.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Final


# Bumped any time the adapter contract changes shape in a way that could
# affect paper-Sharpe reproducibility.
PAPER_ADAPTER_CONTRACT_VERSION: Final[str] = "paper_adapter.v0"


@dataclass(frozen=True)
class MarketSnapshot:
    """Minimum market state required for a deterministic paper fill.

    Concrete adapters may consume richer snapshots; this is the minimum
    contract. The shape is deliberately tight so the determinism property
    is easy to verify: same instrument + same prices + same as_of_at →
    same fill.
    """

    instrument: str
    bid_price: Decimal
    ask_price: Decimal
    bid_size: Decimal
    ask_size: Decimal
    as_of_at: object  # datetime; typed loosely to avoid import cycle in skeleton

    def __post_init__(self) -> None:
        if not self.instrument:
            raise ValueError("instrument must be non-empty")
        if not isinstance(self.bid_price, Decimal):
            raise TypeError("bid_price must be Decimal")
        if not isinstance(self.ask_price, Decimal):
            raise TypeError("ask_price must be Decimal")
        if self.bid_price <= 0 or self.ask_price <= 0:
            raise ValueError(
                f"prices must be positive, got bid={self.bid_price} ask={self.ask_price}"
            )
        if self.bid_price > self.ask_price:
            raise ValueError(
                f"bid_price ({self.bid_price}) must not exceed ask_price ({self.ask_price})"
            )
        if not isinstance(self.bid_size, Decimal) or not isinstance(self.ask_size, Decimal):
            raise TypeError("sizes must be Decimal")
        if self.bid_size < 0 or self.ask_size < 0:
            raise ValueError("sizes must be non-negative")


@dataclass(frozen=True)
class PaperFill:
    """The fill a paper adapter emits.

    Carries lineage so reconciliation can prove that two paper runs used
    the same cost model + same seed. Without lineage, paper Sharpe
    comparisons across runs are meaningless.
    """

    instrument: str
    side: str  # "buy" | "sell"
    quantity: Decimal
    price: Decimal
    is_maker: bool
    cost_model_hash: str  # from CostModelConfig.content_hash
    simulation_seed: int
    as_of_at: object  # datetime

    def __post_init__(self) -> None:
        if self.side not in ("buy", "sell"):
            raise ValueError(f"side must be 'buy' or 'sell', got {self.side!r}")
        if not isinstance(self.quantity, Decimal) or self.quantity <= 0:
            raise ValueError("quantity must be a positive Decimal")
        if not isinstance(self.price, Decimal) or self.price <= 0:
            raise ValueError("price must be a positive Decimal")
        if not isinstance(self.is_maker, bool):
            raise TypeError("is_maker must be bool")
        if not self.cost_model_hash:
            raise ValueError("cost_model_hash is required for lineage")


class PaperAdapter(ABC):
    """Contract for any paper-fill simulator.

    A concrete adapter receives an order intent + a market snapshot + a
    cost model + a simulation seed, and returns one or more PaperFill
    rows. Implementations must be deterministic: the same inputs must
    produce the same fills.
    """

    contract_version: str = PAPER_ADAPTER_CONTRACT_VERSION

    @abstractmethod
    def fill(
        self,
        order_intent: object,  # typed loosely to avoid import cycle
        snapshot: MarketSnapshot,
        cost_model_hash: str,
        simulation_seed: int,
    ) -> list[PaperFill]:
        """Synthesize fills for an order intent.

        Must be a pure function of its inputs. Must not perform I/O.
        Must not write to the ledger directly — the OMS / reconciler
        owns ledger writes (per roadmap §3.1.1 paper-run mechanics).

        Returns:
            zero or more PaperFill rows. An empty list represents a
            no-fill outcome (e.g. limit price unmarketable). The list
            must be deterministic in length and content given the inputs.
        """
        raise NotImplementedError

    @abstractmethod
    def describe(self) -> dict:
        """Return a JSON-serializable description of the adapter's
        configuration and version, for inclusion in paper-run metadata.

        Used by reconciliation to detect adapter changes between runs.
        """
        raise NotImplementedError
