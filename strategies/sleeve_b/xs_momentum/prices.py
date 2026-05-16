"""Price data structures for the Sleeve B backtest.

PriceBar: one daily OHLC bar.
PriceSeries: per-symbol bar series with O(1) date lookup, trailing-return
    computation.
PriceMap: dict[symbol -> PriceSeries].

This module is I/O-free. The run script (separate commit) populates
PriceSeries instances from BinanceKlinesArchiveFetcher; this module
operates on already-loaded data.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable, Mapping


@dataclass(frozen=True)
class PriceBar:
    """One daily OHLC bar."""
    bar_date: date
    open_price: Decimal
    close_price: Decimal


class PriceSeries:
    """Per-symbol price series with O(1) date lookup.

    Trailing-return computation uses close-to-close over a configurable
    lookback window. Returns None if either close is missing — the signal
    module treats this as data-eligibility failure.
    """

    def __init__(self, symbol: str, bars: Iterable[PriceBar]) -> None:
        self.symbol = symbol
        self._bars: dict[date, PriceBar] = {}
        for bar in bars:
            self._bars[bar.bar_date] = bar

    @property
    def first_date(self) -> date | None:
        return min(self._bars.keys()) if self._bars else None

    @property
    def last_date(self) -> date | None:
        return max(self._bars.keys()) if self._bars else None

    def has_close_at(self, d: date) -> bool:
        return d in self._bars

    def close_at(self, d: date) -> Decimal | None:
        bar = self._bars.get(d)
        return bar.close_price if bar else None

    def trailing_return(
        self,
        *,
        as_of: date,
        lookback_days: int,
    ) -> Decimal | None:
        """Trailing close-to-close return over lookback_days ending at as_of.

        Returns None if either the as_of close or the (as_of - lookback)
        close is missing. The signal module uses this to filter assets with
        incomplete data at a rebalance date.
        """
        end_close = self.close_at(as_of)
        if end_close is None:
            return None
        start_date = as_of - timedelta(days=lookback_days)
        start_close = self.close_at(start_date)
        if start_close is None or start_close == 0:
            return None
        return end_close / start_close - Decimal("1")


PriceMap = Mapping[str, PriceSeries]
