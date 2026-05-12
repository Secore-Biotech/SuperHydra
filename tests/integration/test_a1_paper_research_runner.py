"""Integration tests for the A1 PAPER_RESEARCH runner.

Coverage:
  - Zero funding events → zero fills
  - Below min_lookback → zero fills (insufficient history)
  - Synthetic high-funding fixture → fires intents under research profile
  - cost_profile_name recorded in paper.fills matches research profile
  - trading.fills row count unchanged after run (the firewall)
  - Real SOL Mar 2024 fixture: firewall holds regardless of fire count
  - Idempotent re-run on same funding events
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from data.ingestion.vendors.binance.funding_rate import FundingRate
from data.ingestion.vendors.binance.trade import BinanceTrade
from data.ingestion.vendors.binance.trade_fetcher import (
    PermanentFetcherError,
    TransientFetcherError,
)
from strategies.a1_funding.runner.paper_research_runner import (
    A1PaperResearchRunner,
    RunSummary,
)
from tests.integration.test_migrations import (  # noqa: F401
    _alembic,
    _connect,
    _setup_basic_0009,
    fresh_db,
)


# ─── Helpers ────────────────────────────────────────────────────────────


def _bootstrap(cur):
    """Apply 0010 then bootstrap registry."""
    _alembic("upgrade", "0010")
    return _setup_basic_0009(cur)


class FakeFetcher:
    """Maps (symbol, start, end) → trades or Exception. Records calls."""

    def __init__(self):
        self.default_response: list | Exception = []
        self.responses: dict = {}
        self.calls: list = []

    def fetch_window(self, symbol, start, end):
        self.calls.append((symbol, start, end))
        key = (symbol, start, end)
        r = self.responses.get(key, self.default_response)
        if isinstance(r, Exception):
            raise r
        return r


def _trade(price: str, time: datetime, trade_id: int) -> BinanceTrade:
    return BinanceTrade(
        venue="binance",
        instrument="SOLUSDT",
        id=trade_id,
        price=Decimal(price),
        qty=Decimal("1.0"),
        time=time,
        is_buyer_maker=False,
    )


def _make_funding_event(
    *,
    funding_time: datetime,
    funding_rate: Decimal,
    mark_price: Decimal | None = Decimal("150.00"),
    instrument: str = "SOLUSDT",
) -> FundingRate:
    return FundingRate(
        venue="binance",
        instrument=instrument,
        funding_time=funding_time,
        funding_rate=funding_rate,
        mark_price=mark_price,
    )


def _synthetic_high_funding_events(
    *,
    start: datetime,
    n: int,
    rate: Decimal = Decimal("0.0010"),  # 10 bps per 8h, sustained
) -> list[FundingRate]:
    """Build n consecutive 8-hour-spaced events at the given rate.

    rate = 0.0010 → 10 bps/interval, well above 7.7 bps research threshold.
    """
    return [
        _make_funding_event(
            funding_time=start + timedelta(hours=8 * i),
            funding_rate=rate,
        )
        for i in range(n)
    ]


# ─── Tests ──────────────────────────────────────────────────────────────


def test_zero_funding_events_produces_zero_fills(fresh_db):
    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)
        conn.commit()

        runner = A1PaperResearchRunner(
            funding_source=[],
            trade_fetcher=FakeFetcher(),
            fetch_source="archive",
            strategy_id=refs["strategy_id"],
            portfolio_id=refs["portfolio_id"],
            account_id=refs["account_id"],
            instrument_id=refs["instrument_id"],
            symbol="SOLUSDT",
            quantity_per_intent=Decimal("10.0"),
        )
        summary = runner.run(conn)
        conn.commit()

        assert summary.funding_events_total == 0
        assert summary.intents_fired == 0

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM paper.fills;")
            assert cur.fetchone()[0] == 0


def test_below_min_lookback_produces_zero_fills(fresh_db):
    """Only 5 events; forecast_window_size=12 requires 12+ prior."""
    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)
        conn.commit()

        events = _synthetic_high_funding_events(
            start=datetime(2024, 3, 1, tzinfo=timezone.utc),
            n=5,
        )
        runner = A1PaperResearchRunner(
            funding_source=events,
            trade_fetcher=FakeFetcher(),
            fetch_source="archive",
            strategy_id=refs["strategy_id"],
            portfolio_id=refs["portfolio_id"],
            account_id=refs["account_id"],
            instrument_id=refs["instrument_id"],
            symbol="SOLUSDT",
            quantity_per_intent=Decimal("10.0"),
        )
        summary = runner.run(conn)
        conn.commit()

        assert summary.intents_fired == 0
        assert summary.skipped_below_lookback == 5
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM paper.fills;")
            assert cur.fetchone()[0] == 0


def test_synthetic_high_funding_fires_intents(fresh_db):
    """20 events at 10 bps sustained funding clears 7.7 bps threshold.

    First 12 are skipped (below lookback); remaining 8 should fire.
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)
        conn.commit()

        events = _synthetic_high_funding_events(
            start=datetime(2024, 3, 1, tzinfo=timezone.utc),
            n=20,
        )
        fetcher = FakeFetcher()
        # Default response: one trade at 150.30 → 20 bps slippage on buy
        fetcher.default_response = [
            _trade("150.30", datetime(2024, 3, 1, tzinfo=timezone.utc), 1)
        ]

        runner = A1PaperResearchRunner(
            funding_source=events,
            trade_fetcher=fetcher,
            fetch_source="archive",
            strategy_id=refs["strategy_id"],
            portfolio_id=refs["portfolio_id"],
            account_id=refs["account_id"],
            instrument_id=refs["instrument_id"],
            symbol="SOLUSDT",
            quantity_per_intent=Decimal("10.0"),
        )
        summary = runner.run(conn)
        conn.commit()

        # First 12 below lookback; 8 should fire.
        assert summary.funding_events_total == 20
        assert summary.skipped_below_lookback == 12
        assert summary.intents_fired == 8

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM paper.fills;")
            assert cur.fetchone()[0] == 8


def test_fills_recorded_under_research_profile(fresh_db):
    """Every fill's cost_profile_name must be the research-firewalled one."""
    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)
        conn.commit()

        events = _synthetic_high_funding_events(
            start=datetime(2024, 3, 1, tzinfo=timezone.utc),
            n=15,
        )
        fetcher = FakeFetcher()
        fetcher.default_response = [
            _trade("150.10", datetime(2024, 3, 1, tzinfo=timezone.utc), 1)
        ]
        runner = A1PaperResearchRunner(
            funding_source=events,
            trade_fetcher=fetcher,
            fetch_source="archive",
            strategy_id=refs["strategy_id"],
            portfolio_id=refs["portfolio_id"],
            account_id=refs["account_id"],
            instrument_id=refs["instrument_id"],
            symbol="SOLUSDT",
            quantity_per_intent=Decimal("10.0"),
        )
        summary = runner.run(conn)
        conn.commit()

        assert summary.intents_fired > 0
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT cost_profile_name, source_mode, "
                "promotion_eligible FROM paper.fills;"
            )
            rows = cur.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "binance_vip5_alt_research_v1"
        assert rows[0][1] == "PAPER_RESEARCH"
        assert rows[0][2] is False


def test_runner_does_not_touch_trading_fills(fresh_db):
    """The firewall test: trading.fills row count unchanged."""
    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)
            cur.execute("SELECT COUNT(*) FROM trading.fills;")
            trading_before = cur.fetchone()[0]
        conn.commit()

        events = _synthetic_high_funding_events(
            start=datetime(2024, 3, 1, tzinfo=timezone.utc),
            n=15,
        )
        fetcher = FakeFetcher()
        fetcher.default_response = [
            _trade("150.10", datetime(2024, 3, 1, tzinfo=timezone.utc), 1)
        ]
        runner = A1PaperResearchRunner(
            funding_source=events,
            trade_fetcher=fetcher,
            fetch_source="archive",
            strategy_id=refs["strategy_id"],
            portfolio_id=refs["portfolio_id"],
            account_id=refs["account_id"],
            instrument_id=refs["instrument_id"],
            symbol="SOLUSDT",
            quantity_per_intent=Decimal("10.0"),
        )
        runner.run(conn)
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM trading.fills;")
            trading_after = cur.fetchone()[0]
        assert trading_after == trading_before


def test_run_is_idempotent_on_same_funding_events(fresh_db):
    """Same funding events twice → deterministic UUIDs → idempotent."""
    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)
        conn.commit()

        events = _synthetic_high_funding_events(
            start=datetime(2024, 3, 1, tzinfo=timezone.utc),
            n=15,
        )
        fetcher = FakeFetcher()
        fetcher.default_response = [
            _trade("150.10", datetime(2024, 3, 1, tzinfo=timezone.utc), 1)
        ]

        runner1 = A1PaperResearchRunner(
            funding_source=events,
            trade_fetcher=fetcher,
            fetch_source="archive",
            strategy_id=refs["strategy_id"],
            portfolio_id=refs["portfolio_id"],
            account_id=refs["account_id"],
            instrument_id=refs["instrument_id"],
            symbol="SOLUSDT",
            quantity_per_intent=Decimal("10.0"),
        )
        s1 = runner1.run(conn)
        conn.commit()

        # Second run with the same events.
        runner2 = A1PaperResearchRunner(
            funding_source=events,
            trade_fetcher=fetcher,
            fetch_source="archive",
            strategy_id=refs["strategy_id"],
            portfolio_id=refs["portfolio_id"],
            account_id=refs["account_id"],
            instrument_id=refs["instrument_id"],
            symbol="SOLUSDT",
            quantity_per_intent=Decimal("10.0"),
        )
        s2 = runner2.run(conn)
        conn.commit()

        assert s1.intents_fired == s2.intents_fired
        # Idempotent: no new rows on second run.
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM paper.fills;")
            n = cur.fetchone()[0]
        assert n == s1.intents_fired  # not 2x


def test_no_reference_price_skips_event(fresh_db):
    """Event with mark_price=None AND no trades near funding_time → skip."""
    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)
        conn.commit()

        # 15 events; first 13 with mark_price (build forecast), last 2 with
        # mark_price=None and no trades in fetcher → should be skipped.
        events = []
        for i in range(13):
            events.append(_make_funding_event(
                funding_time=datetime(2024, 3, 1, tzinfo=timezone.utc)
                              + timedelta(hours=8 * i),
                funding_rate=Decimal("0.0010"),
                mark_price=Decimal("150.00"),
            ))
        for i in range(13, 15):
            events.append(_make_funding_event(
                funding_time=datetime(2024, 3, 1, tzinfo=timezone.utc)
                              + timedelta(hours=8 * i),
                funding_rate=Decimal("0.0010"),
                mark_price=None,
            ))

        fetcher = FakeFetcher()
        # Default empty for both observation AND reference-price lookups.
        fetcher.default_response = []

        runner = A1PaperResearchRunner(
            funding_source=events,
            trade_fetcher=fetcher,
            fetch_source="archive",
            strategy_id=refs["strategy_id"],
            portfolio_id=refs["portfolio_id"],
            account_id=refs["account_id"],
            instrument_id=refs["instrument_id"],
            symbol="SOLUSDT",
            quantity_per_intent=Decimal("10.0"),
        )
        summary = runner.run(conn)
        conn.commit()

        # First 12 below lookback; event 13 has mark_price (fires);
        # events 14 and 15 have no reference price (skipped).
        assert summary.skipped_below_lookback == 12
        assert summary.skipped_no_reference == 2
        assert summary.intents_fired == 1


def test_real_sol_mar_2024_fixture_firewall_holds(fresh_db):
    """The Q4.E test: use the real SOL Mar 2024 fixture. Don't hardcode
    a fill count; assert only firewall properties hold."""
    fixture_path = (
        Path(__file__).resolve().parent.parent
        / "fixtures" / "binance_funding"
        / "SOLUSDT_14d_20240301T000000_20240315T000000.json"
    )
    if not fixture_path.exists():
        pytest.skip(f"fixture not present at {fixture_path}")

    with fixture_path.open() as f:
        payload = json.load(f)

    events = []
    for r in payload["records"]:
        events.append(FundingRate(
            venue=r["venue"],
            instrument=r["instrument"],
            funding_time=datetime.fromisoformat(r["funding_time"]),
            funding_rate=Decimal(r["funding_rate"]),
            mark_price=Decimal(r["mark_price"]) if r["mark_price"] else None,
        ))

    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)
            cur.execute("SELECT COUNT(*) FROM trading.fills;")
            trading_before = cur.fetchone()[0]
        conn.commit()

        fetcher = FakeFetcher()
        fetcher.default_response = []  # no observation trades available

        runner = A1PaperResearchRunner(
            funding_source=events,
            trade_fetcher=fetcher,
            fetch_source="archive",
            strategy_id=refs["strategy_id"],
            portfolio_id=refs["portfolio_id"],
            account_id=refs["account_id"],
            instrument_id=refs["instrument_id"],
            symbol="SOLUSDT",
            quantity_per_intent=Decimal("10.0"),
        )
        summary = runner.run(conn)
        conn.commit()

        # Firewall properties — must hold regardless of fire count.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT source_mode, promotion_eligible "
                "FROM paper.fills;"
            )
            rows = cur.fetchall()
            for source_mode, promotion_eligible in rows:
                assert source_mode == "PAPER_RESEARCH"
                assert promotion_eligible is False

            cur.execute("SELECT COUNT(*) FROM trading.fills;")
            trading_after = cur.fetchone()[0]
        assert trading_after == trading_before

        # Document the actual fire count as research evidence.
        # Whether it is 0 or some small number is itself a finding.
        # We do NOT assert a specific count here.
        print(f"\n[real fixture] events={summary.funding_events_total}, "
              f"intents_fired={summary.intents_fired}, "
              f"skipped_below_lookback={summary.skipped_below_lookback}, "
              f"skipped_no_edge={summary.skipped_no_edge}, "
              f"skipped_no_reference={summary.skipped_no_reference}")


def test_rejects_invalid_quantity():
    with pytest.raises(ValueError, match="quantity_per_intent"):
        A1PaperResearchRunner(
            funding_source=[],
            trade_fetcher=FakeFetcher(),
            fetch_source="archive",
            strategy_id=1, portfolio_id=1, account_id=1, instrument_id=1,
            symbol="SOLUSDT",
            quantity_per_intent=Decimal("0"),
        )


def test_rejects_out_of_order_funding_events():
    """Events must be strictly ascending by funding_time."""
    t0 = datetime(2024, 3, 1, tzinfo=timezone.utc)
    events = [
        _make_funding_event(funding_time=t0, funding_rate=Decimal("0.001")),
        _make_funding_event(funding_time=t0, funding_rate=Decimal("0.001")),
    ]
    with pytest.raises(ValueError, match="strictly ascending"):
        A1PaperResearchRunner(
            funding_source=events,
            trade_fetcher=FakeFetcher(),
            fetch_source="archive",
            strategy_id=1, portfolio_id=1, account_id=1, instrument_id=1,
            symbol="SOLUSDT",
            quantity_per_intent=Decimal("10.0"),
        )
