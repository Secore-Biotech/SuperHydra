"""A2DualFetcher — routes perp/spot fetch_window calls.

Step 3 prerequisite. The A2 runner emits two PaperReplayIntents per
trade event (perp leg + spot leg). The TradeFetcher protocol keys on
intent.symbol; a single underlying fetcher class can only serve one
of the two legs (perp archive uses different CSV schema and S3 path
than spot archive — Day 26.5 enshrined the separation).

A2DualFetcher wraps two fetcher instances and routes each fetch_window
call to the correct one based on symbol. The wrapper itself satisfies
the TradeFetcher protocol (one fetch_window method).

Routing rule per Day 28b.3 / Step 3 lock:
    intent.symbol "{base}_PERP"  → perp_fetcher.fetch_window(base, ...)
    intent.symbol "{base}_SPOT"  → spot_fetcher.fetch_window(base, ...)

The wrapper strips the leg suffix before calling the underlying fetcher
because the archive fetchers themselves expect the base symbol (e.g.
"SOLUSDT", not "SOLUSDT_PERP") — they handle perp-vs-spot via different
S3 prefixes internally.
"""
from __future__ import annotations

from datetime import datetime
from typing import Protocol


class _SupportsFetchWindow(Protocol):
    """Minimal interface; matches execution.paper.replay_runner.TradeFetcher."""

    def fetch_window(self, symbol: str, start: datetime, end: datetime):
        ...


class A2DualFetcherError(Exception):
    """Raised on unknown symbol or misconfigured leg-symbol pair."""


class A2DualFetcher:
    """Routes fetch_window calls to perp or spot fetcher by symbol suffix.

    Construction:
        perp_fetcher: underlying fetcher for the perp leg (BinanceArchiveTradeFetcher
                      or BinanceTradeFetcher live).
        spot_fetcher: underlying fetcher for the spot leg
                      (BinanceSpotArchiveTradeFetcher).
        perp_symbol:  the leg-specific symbol the runner emits for perp intents
                      (e.g. "SOLUSDT_PERP"). Used for matching only; not
                      passed to the underlying fetcher.
        spot_symbol:  the leg-specific symbol the runner emits for spot intents
                      (e.g. "SOLUSDT_SPOT"). Used for matching only; not
                      passed to the underlying fetcher.
        base_symbol:  the symbol passed to the underlying fetchers
                      (e.g. "SOLUSDT"). Both underlying fetchers expect this.

    Raises:
        A2DualFetcherError: if perp_symbol == spot_symbol (would create
            an ambiguous routing table), or if a fetch_window call
            arrives with an unrecognised symbol.
    """

    def __init__(
        self,
        *,
        perp_fetcher: _SupportsFetchWindow,
        spot_fetcher: _SupportsFetchWindow,
        perp_symbol: str,
        spot_symbol: str,
        base_symbol: str,
    ) -> None:
        if perp_symbol == spot_symbol:
            raise A2DualFetcherError(
                f"perp_symbol and spot_symbol must differ, "
                f"both were {perp_symbol!r}"
            )
        if not perp_symbol or not spot_symbol or not base_symbol:
            raise A2DualFetcherError(
                "perp_symbol, spot_symbol, and base_symbol must all be non-empty"
            )
        self._perp_fetcher = perp_fetcher
        self._spot_fetcher = spot_fetcher
        self._perp_symbol = perp_symbol
        self._spot_symbol = spot_symbol
        self._base_symbol = base_symbol

    def fetch_window(self, symbol: str, start: datetime, end: datetime):
        """Route to perp or spot fetcher based on symbol.

        The underlying fetcher is called with self._base_symbol, NOT the
        leg-specific symbol. Underlying archive fetchers do not understand
        the "_PERP"/"_SPOT" suffix convention — that's A2's leg-routing
        layer only.

        Raises:
            A2DualFetcherError: symbol does not match perp_symbol or
                spot_symbol.
        """
        if symbol == self._perp_symbol:
            return self._perp_fetcher.fetch_window(
                self._base_symbol, start, end,
            )
        if symbol == self._spot_symbol:
            return self._spot_fetcher.fetch_window(
                self._base_symbol, start, end,
            )
        raise A2DualFetcherError(
            f"unknown symbol {symbol!r}; "
            f"expected {self._perp_symbol!r} or {self._spot_symbol!r}"
        )
