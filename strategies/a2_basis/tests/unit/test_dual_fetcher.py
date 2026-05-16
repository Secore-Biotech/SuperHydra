"""Unit tests for A2DualFetcher routing.

Pure tests; no DB, no network. Verifies:
  - Routing by symbol works for both legs
  - Underlying fetcher called with base_symbol (not leg-specific)
  - Unknown symbol raises A2DualFetcherError
  - Construction validation (duplicate symbols, empty inputs)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from strategies.a2_basis.data.dual_fetcher import (
    A2DualFetcher,
    A2DualFetcherError,
)


class _RecordingFetcher:
    """Records the arguments of every fetch_window call."""

    def __init__(self, return_value: list[Any] | None = None) -> None:
        self.calls: list[tuple[str, datetime, datetime]] = []
        self._return_value = return_value or []

    def fetch_window(self, symbol: str, start: datetime, end: datetime):
        self.calls.append((symbol, start, end))
        return self._return_value


START = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
END = datetime(2024, 6, 1, 12, 5, 0, tzinfo=timezone.utc)


# ─── Construction validation ────────────────────────────────────────────


class TestConstruction:
    def test_duplicate_symbols_raises(self):
        with pytest.raises(A2DualFetcherError, match="must differ"):
            A2DualFetcher(
                perp_fetcher=_RecordingFetcher(),
                spot_fetcher=_RecordingFetcher(),
                perp_symbol="SOLUSDT",
                spot_symbol="SOLUSDT",
                base_symbol="SOLUSDT",
            )

    def test_empty_perp_symbol_raises(self):
        with pytest.raises(A2DualFetcherError, match="non-empty"):
            A2DualFetcher(
                perp_fetcher=_RecordingFetcher(),
                spot_fetcher=_RecordingFetcher(),
                perp_symbol="",
                spot_symbol="SOLUSDT_SPOT",
                base_symbol="SOLUSDT",
            )

    def test_empty_spot_symbol_raises(self):
        with pytest.raises(A2DualFetcherError, match="non-empty"):
            A2DualFetcher(
                perp_fetcher=_RecordingFetcher(),
                spot_fetcher=_RecordingFetcher(),
                perp_symbol="SOLUSDT_PERP",
                spot_symbol="",
                base_symbol="SOLUSDT",
            )

    def test_empty_base_symbol_raises(self):
        with pytest.raises(A2DualFetcherError, match="non-empty"):
            A2DualFetcher(
                perp_fetcher=_RecordingFetcher(),
                spot_fetcher=_RecordingFetcher(),
                perp_symbol="SOLUSDT_PERP",
                spot_symbol="SOLUSDT_SPOT",
                base_symbol="",
            )


# ─── Routing ────────────────────────────────────────────────────────────


class TestRouting:
    def _dual(self):
        return (
            _RecordingFetcher(return_value=[{"leg": "perp"}]),
            _RecordingFetcher(return_value=[{"leg": "spot"}]),
        )

    def test_perp_symbol_routes_to_perp_fetcher(self):
        perp, spot = self._dual()
        d = A2DualFetcher(
            perp_fetcher=perp,
            spot_fetcher=spot,
            perp_symbol="SOLUSDT_PERP",
            spot_symbol="SOLUSDT_SPOT",
            base_symbol="SOLUSDT",
        )
        result = d.fetch_window("SOLUSDT_PERP", START, END)
        assert result == [{"leg": "perp"}]
        assert len(perp.calls) == 1
        assert len(spot.calls) == 0

    def test_spot_symbol_routes_to_spot_fetcher(self):
        perp, spot = self._dual()
        d = A2DualFetcher(
            perp_fetcher=perp,
            spot_fetcher=spot,
            perp_symbol="SOLUSDT_PERP",
            spot_symbol="SOLUSDT_SPOT",
            base_symbol="SOLUSDT",
        )
        result = d.fetch_window("SOLUSDT_SPOT", START, END)
        assert result == [{"leg": "spot"}]
        assert len(spot.calls) == 1
        assert len(perp.calls) == 0

    def test_underlying_called_with_base_symbol_not_leg_symbol(self):
        """Critical: archive fetchers expect 'SOLUSDT', not 'SOLUSDT_PERP'.
        The wrapper strips the leg suffix before delegating."""
        perp, spot = self._dual()
        d = A2DualFetcher(
            perp_fetcher=perp,
            spot_fetcher=spot,
            perp_symbol="SOLUSDT_PERP",
            spot_symbol="SOLUSDT_SPOT",
            base_symbol="SOLUSDT",
        )
        d.fetch_window("SOLUSDT_PERP", START, END)
        d.fetch_window("SOLUSDT_SPOT", START, END)
        assert perp.calls[0][0] == "SOLUSDT"  # not "SOLUSDT_PERP"
        assert spot.calls[0][0] == "SOLUSDT"  # not "SOLUSDT_SPOT"

    def test_unknown_symbol_raises(self):
        perp, spot = self._dual()
        d = A2DualFetcher(
            perp_fetcher=perp,
            spot_fetcher=spot,
            perp_symbol="SOLUSDT_PERP",
            spot_symbol="SOLUSDT_SPOT",
            base_symbol="SOLUSDT",
        )
        with pytest.raises(A2DualFetcherError, match="unknown symbol"):
            d.fetch_window("BTCUSDT_PERP", START, END)

    def test_no_call_when_unknown_symbol(self):
        perp, spot = self._dual()
        d = A2DualFetcher(
            perp_fetcher=perp,
            spot_fetcher=spot,
            perp_symbol="SOLUSDT_PERP",
            spot_symbol="SOLUSDT_SPOT",
            base_symbol="SOLUSDT",
        )
        with pytest.raises(A2DualFetcherError):
            d.fetch_window("BTCUSDT_PERP", START, END)
        # Neither underlying fetcher should have been called
        assert len(perp.calls) == 0
        assert len(spot.calls) == 0

    def test_start_end_passed_through(self):
        perp, spot = self._dual()
        d = A2DualFetcher(
            perp_fetcher=perp,
            spot_fetcher=spot,
            perp_symbol="SOLUSDT_PERP",
            spot_symbol="SOLUSDT_SPOT",
            base_symbol="SOLUSDT",
        )
        d.fetch_window("SOLUSDT_PERP", START, END)
        assert perp.calls[0] == ("SOLUSDT", START, END)
