"""Unit tests for execution.adapters.paper_adapter.

The base class is abstract; we test:
  - MarketSnapshot validation (tz, prices, sizes, bid<=ask)
  - PaperFill validation (side, sign, lineage required)
  - Concrete subclass can be instantiated and called
  - Abstract methods raise on a partial implementation

We do NOT test fill simulation logic — there is no concrete adapter yet.
That arrives Day 8 with the vertical smoke test.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from execution.adapters.paper_adapter import (
    PAPER_ADAPTER_CONTRACT_VERSION,
    MarketSnapshot,
    PaperAdapter,
    PaperFill,
)


UTC = timezone.utc


# ─── MarketSnapshot validation ───────────────────────────────────────────


def _snap(**overrides):
    base = dict(
        instrument="BTCUSDT",
        bid_price=Decimal("50000"),
        ask_price=Decimal("50001"),
        bid_size=Decimal("1"),
        ask_size=Decimal("1"),
        as_of_at=datetime(2026, 1, 15, 8, 0, 0, tzinfo=UTC),
    )
    base.update(overrides)
    return MarketSnapshot(**base)


def test_snapshot_rejects_empty_instrument():
    with pytest.raises(ValueError, match="instrument"):
        _snap(instrument="")


def test_snapshot_rejects_float_prices():
    with pytest.raises(TypeError):
        _snap(bid_price=50000.0)


def test_snapshot_rejects_zero_or_negative_prices():
    with pytest.raises(ValueError, match="positive"):
        _snap(bid_price=Decimal("0"))
    with pytest.raises(ValueError, match="positive"):
        _snap(ask_price=Decimal("-1"))


def test_snapshot_rejects_crossed_book():
    """bid > ask is a crossed book; for a passive paper-fill simulator this
    is invalid input (the venue would never publish it)."""
    with pytest.raises(ValueError, match="bid_price"):
        _snap(bid_price=Decimal("50002"), ask_price=Decimal("50001"))


def test_snapshot_allows_locked_book():
    """bid == ask is unusual but legal — a locked book."""
    s = _snap(bid_price=Decimal("50000"), ask_price=Decimal("50000"))
    assert s.bid_price == s.ask_price


def test_snapshot_rejects_negative_sizes():
    with pytest.raises(ValueError, match="non-negative"):
        _snap(bid_size=Decimal("-1"))
    with pytest.raises(ValueError, match="non-negative"):
        _snap(ask_size=Decimal("-1"))


def test_snapshot_allows_zero_sizes():
    """Zero size on one side is legal — paper fills against that side
    will return no fill, which is correct behaviour."""
    s = _snap(bid_size=Decimal("0"))
    assert s.bid_size == Decimal("0")


# ─── PaperFill validation ────────────────────────────────────────────────


def _fill(**overrides):
    base = dict(
        instrument="BTCUSDT",
        side="buy",
        quantity=Decimal("1"),
        price=Decimal("50000"),
        is_maker=False,
        cost_model_hash="0" * 64,
        simulation_seed=42,
        as_of_at=datetime(2026, 1, 15, 8, 0, 0, tzinfo=UTC),
    )
    base.update(overrides)
    return PaperFill(**base)


def test_fill_rejects_invalid_side():
    with pytest.raises(ValueError, match="side"):
        _fill(side="long")
    with pytest.raises(ValueError, match="side"):
        _fill(side="BUY")


def test_fill_rejects_zero_quantity():
    with pytest.raises(ValueError, match="quantity"):
        _fill(quantity=Decimal("0"))


def test_fill_rejects_negative_quantity():
    with pytest.raises(ValueError, match="quantity"):
        _fill(quantity=Decimal("-1"))


def test_fill_rejects_zero_price():
    with pytest.raises(ValueError, match="price"):
        _fill(price=Decimal("0"))


def test_fill_rejects_non_bool_is_maker():
    with pytest.raises(TypeError):
        _fill(is_maker="false")


def test_fill_rejects_empty_cost_model_hash():
    with pytest.raises(ValueError, match="cost_model_hash"):
        _fill(cost_model_hash="")


# ─── Abstract base ───────────────────────────────────────────────────────


def test_cannot_instantiate_abstract_paper_adapter():
    with pytest.raises(TypeError):
        PaperAdapter()  # missing concrete impls of fill() and describe()


def test_concrete_subclass_instantiable():
    """A concrete subclass that implements both abstract methods is
    instantiable and exposes contract_version."""

    class MinimalAdapter(PaperAdapter):
        def fill(self, order_intent, snapshot, cost_model_hash, simulation_seed):
            return []

        def describe(self) -> dict:
            return {"adapter": "minimal", "version": "0"}

    a = MinimalAdapter()
    assert a.contract_version == PAPER_ADAPTER_CONTRACT_VERSION
    assert a.describe() == {"adapter": "minimal", "version": "0"}
    assert a.fill(None, _snap(), "0" * 64, 1) == []


def test_partial_subclass_still_abstract():
    """A subclass that implements only one of the two abstract methods
    must still be uninstantiable. Catches accidental contract-skipping."""

    class IncompleteFill(PaperAdapter):
        def fill(self, order_intent, snapshot, cost_model_hash, simulation_seed):
            return []
        # describe() not implemented

    with pytest.raises(TypeError):
        IncompleteFill()

    class IncompleteDescribe(PaperAdapter):
        def describe(self) -> dict:
            return {}
        # fill() not implemented

    with pytest.raises(TypeError):
        IncompleteDescribe()


def test_contract_version_constant():
    assert PAPER_ADAPTER_CONTRACT_VERSION == "paper_adapter.v0"
