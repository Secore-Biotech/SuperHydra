"""Integration tests for Day 20.3a replay observation.

Two test classes:
  - Pure unit tests for compute_observed_slippage (no DB).
  - Integration tests for replay_intents using a FakeFetcher
    that maps (symbol, start, end) → trades or Exception.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from data.ingestion.vendors.binance.trade import BinanceTrade
from data.ingestion.vendors.binance.trade_fetcher import (
    PermanentFetcherError,
    TransientFetcherError,
)
from execution.paper.replay_observation import (
    ReplayObservation,
    compute_observed_slippage,
)
from execution.paper.replay_runner import (
    PaperReplayIntent,
    ReplayResult,
    replay_intents,
)
from analytics.slippage_calibration import compute_slippage_calibration
from tests.integration.test_migrations import (  # noqa: F401
    _alembic,
    _connect,
    _setup_basic_0009,
    fresh_db,
)


# ─── Helpers ────────────────────────────────────────────────────────────


def _make_trade(price: str, *, time_offset_seconds: int = 0,
                base_time: datetime | None = None,
                trade_id: int | None = None) -> BinanceTrade:
    if base_time is None:
        base_time = datetime(2026, 5, 11, 12, 0, 0, tzinfo=timezone.utc)
    return BinanceTrade(
        venue="binance",
        instrument="SOLUSDT",
        id=trade_id if trade_id is not None else hash(price) % (10**9),
        price=Decimal(price),
        qty=Decimal("1.0"),
        time=base_time + timedelta(seconds=time_offset_seconds),
        is_buyer_maker=False,
    )


class FakeFetcher:
    """Maps (symbol, start, end) → trades or Exception. Records calls."""

    def __init__(self):
        self.responses: dict = {}
        self.default_response: list | Exception = []
        self.calls: list = []

    def set_response(self, symbol: str, start: datetime, end: datetime,
                     response):
        self.responses[(symbol, start, end)] = response

    def fetch_window(self, symbol: str, start: datetime, end: datetime):
        self.calls.append((symbol, start, end))
        key = (symbol, start, end)
        if key in self.responses:
            r = self.responses[key]
        else:
            r = self.default_response
        if isinstance(r, Exception):
            raise r
        return r


# ─── Pure unit tests for compute_observed_slippage ───────────────────────


class TestComputeObservedSlippage:
    REF = Decimal("100.00")

    def test_buy_single_trade_above_reference_positive_slippage(self):
        trades = [_make_trade("100.10")]
        r = compute_observed_slippage(
            trades=trades, side="buy", reference_price=self.REF,
        )
        assert r.status == "success"
        assert r.trade_count == 1
        assert r.extreme_price == Decimal("100.10")
        # (100.10 - 100.00) / 100.00 * 10000 = 10 bps
        assert r.observed_slippage_bps == Decimal("10")

    def test_buy_single_trade_below_reference_negative_slippage(self):
        """Price improvement: filled at 99.95 when wanted 100."""
        trades = [_make_trade("99.95")]
        r = compute_observed_slippage(
            trades=trades, side="buy", reference_price=self.REF,
        )
        assert r.status == "success"
        # (99.95 - 100.00) / 100.00 * 10000 = -5 bps
        assert r.observed_slippage_bps == Decimal("-5")

    def test_sell_single_trade_below_reference_positive_slippage(self):
        trades = [_make_trade("99.90")]
        r = compute_observed_slippage(
            trades=trades, side="sell", reference_price=self.REF,
        )
        assert r.status == "success"
        # (100.00 - 99.90) / 100.00 * 10000 = 10 bps
        assert r.observed_slippage_bps == Decimal("10")

    def test_sell_single_trade_above_reference_negative_slippage(self):
        """Price improvement on sell: filled at 100.05 when wanted 100."""
        trades = [_make_trade("100.05")]
        r = compute_observed_slippage(
            trades=trades, side="sell", reference_price=self.REF,
        )
        assert r.status == "success"
        # (100.00 - 100.05) / 100.00 * 10000 = -5 bps
        assert r.observed_slippage_bps == Decimal("-5")

    def test_buy_multiple_trades_takes_max(self):
        trades = [_make_trade(p) for p in
                  ["100.05", "100.20", "100.10", "100.15"]]
        r = compute_observed_slippage(
            trades=trades, side="buy", reference_price=self.REF,
        )
        assert r.status == "success"
        assert r.trade_count == 4
        assert r.extreme_price == Decimal("100.20")
        # Worst buy in window: 100.20 → (0.20 / 100) * 10000 = 20 bps
        assert r.observed_slippage_bps == Decimal("20")

    def test_sell_multiple_trades_takes_min(self):
        trades = [_make_trade(p) for p in
                  ["99.95", "99.80", "99.90", "99.85"]]
        r = compute_observed_slippage(
            trades=trades, side="sell", reference_price=self.REF,
        )
        assert r.status == "success"
        assert r.extreme_price == Decimal("99.80")
        # Worst sell in window: 99.80 → (0.20 / 100) * 10000 = 20 bps
        assert r.observed_slippage_bps == Decimal("20")

    def test_reference_equals_only_trade_zero_slippage(self):
        trades = [_make_trade("100.00")]
        r = compute_observed_slippage(
            trades=trades, side="buy", reference_price=self.REF,
        )
        assert r.observed_slippage_bps == Decimal("0")

    def test_empty_trades_returns_empty_window_status(self):
        r = compute_observed_slippage(
            trades=[], side="buy", reference_price=self.REF,
        )
        assert r.status == "empty_window"
        assert r.trade_count == 0
        assert r.observed_slippage_bps is None
        assert r.extreme_price is None

    def test_invalid_side_raises(self):
        with pytest.raises(ValueError, match="side must be"):
            compute_observed_slippage(
                trades=[_make_trade("100")],
                side="long", reference_price=self.REF,
            )

    def test_zero_reference_raises(self):
        with pytest.raises(ValueError, match="must be positive"):
            compute_observed_slippage(
                trades=[_make_trade("100")],
                side="buy", reference_price=Decimal("0"),
            )

    def test_negative_reference_raises(self):
        with pytest.raises(ValueError, match="must be positive"):
            compute_observed_slippage(
                trades=[_make_trade("100")],
                side="buy", reference_price=Decimal("-1"),
            )

    def test_non_decimal_reference_raises(self):
        with pytest.raises(TypeError, match="must be Decimal"):
            compute_observed_slippage(
                trades=[_make_trade("100")],
                side="buy", reference_price=100.0,  # float
            )


class TestReplayObservationInvariants:
    def test_success_with_none_slippage_raises(self):
        with pytest.raises(ValueError, match="status=success requires"):
            ReplayObservation(
                observed_slippage_bps=None,
                extreme_price=Decimal("100"),
                trade_count=1,
                status="success",
            )

    def test_empty_window_with_value_raises(self):
        with pytest.raises(ValueError, match="status=empty_window requires"):
            ReplayObservation(
                observed_slippage_bps=Decimal("5"),
                extreme_price=Decimal("100"),
                trade_count=0,
                status="empty_window",
            )


# ─── Integration tests for replay_intents ───────────────────────────────


def _bootstrap(cur):
    """Apply 0010 then bootstrap registry. Order matters (FK lock)."""
    _alembic("upgrade", "0010")
    return _setup_basic_0009(cur)


def _make_intent(refs: dict, **overrides) -> PaperReplayIntent:
    defaults = dict(
        paper_fill_uuid=uuid.uuid4(),
        strategy_id=refs["strategy_id"],
        portfolio_id=refs["portfolio_id"],
        account_id=refs["account_id"],
        instrument_id=refs["instrument_id"],
        symbol="SOLUSDT",
        side="buy",
        quantity=Decimal("1.5"),
        decision_reference_price=Decimal("150.00"),
        modeled_slippage_bps=Decimal("0.5"),
        cost_profile_name="binance_vip5_alt_research_v1",
        cost_profile_hash="a" * 64,
        intended_fill_at=datetime(2026, 5, 11, 12, 0, 0, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return PaperReplayIntent(**defaults)


def test_replay_success_writes_fill_with_observed_slippage(fresh_db):
    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)
        conn.commit()

        intent = _make_intent(refs)
        fetcher = FakeFetcher()
        # Trade at 150.30 vs reference 150 → 20 bps adverse on buy
        fetcher.default_response = [_make_trade("150.30")]

        [result] = replay_intents(
            conn, [intent], fetcher=fetcher, fetch_source="archive",
        )
        conn.commit()

        assert result.replay_status == "success"
        assert result.trade_count == 1
        assert result.observed_slippage_bps == Decimal("20")

        # Row visible in paper.fills with metadata.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT observed_slippage_bps, metadata FROM paper.fills "
                "WHERE paper_fill_uuid = %s;",
                (str(intent.paper_fill_uuid),),
            )
            row = cur.fetchone()
        assert row[0] == Decimal("20.0000000000")
        meta = row[1]
        assert meta["replay_status"] == "success"
        assert meta["trade_count"] == 1
        assert meta["window_seconds"] == 5
        assert meta["fetch_source"] == "archive"
        assert meta["extreme_price"] == "150.30"


def test_replay_empty_window_writes_fill_with_null_slippage(fresh_db):
    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)
        conn.commit()

        intent = _make_intent(refs)
        fetcher = FakeFetcher()
        fetcher.default_response = []  # empty trades

        [result] = replay_intents(
            conn, [intent], fetcher=fetcher, fetch_source="archive",
        )
        conn.commit()

        assert result.replay_status == "empty_window"
        assert result.trade_count == 0
        assert result.observed_slippage_bps is None

        with conn.cursor() as cur:
            cur.execute(
                "SELECT observed_slippage_bps, metadata FROM paper.fills "
                "WHERE paper_fill_uuid = %s;",
                (str(intent.paper_fill_uuid),),
            )
            row = cur.fetchone()
        assert row[0] is None
        assert row[1]["replay_status"] == "empty_window"
        assert row[1]["trade_count"] == 0
        # extreme_price should NOT be present.
        assert "extreme_price" not in row[1]


def test_replay_permanent_fetch_error_writes_fill_with_error_metadata(fresh_db):
    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)
        conn.commit()

        intent = _make_intent(refs)
        fetcher = FakeFetcher()
        fetcher.default_response = PermanentFetcherError("HTTP 404: not found")

        [result] = replay_intents(
            conn, [intent], fetcher=fetcher, fetch_source="archive",
        )
        conn.commit()

        assert result.replay_status == "fetch_error"
        assert result.trade_count == 0
        assert result.observed_slippage_bps is None

        with conn.cursor() as cur:
            cur.execute(
                "SELECT observed_slippage_bps, metadata FROM paper.fills "
                "WHERE paper_fill_uuid = %s;",
                (str(intent.paper_fill_uuid),),
            )
            row = cur.fetchone()
        assert row[0] is None
        meta = row[1]
        assert meta["replay_status"] == "fetch_error"
        assert meta["error_type"] == "PermanentFetcherError"
        assert "404" in meta["error_message"]


def test_replay_transient_fetch_error_writes_fill(fresh_db):
    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)
        conn.commit()

        intent = _make_intent(refs)
        fetcher = FakeFetcher()
        fetcher.default_response = TransientFetcherError("network glitch")

        [result] = replay_intents(
            conn, [intent], fetcher=fetcher, fetch_source="rest",
        )
        conn.commit()

        assert result.replay_status == "fetch_error"
        with conn.cursor() as cur:
            cur.execute(
                "SELECT metadata FROM paper.fills "
                "WHERE paper_fill_uuid = %s;",
                (str(intent.paper_fill_uuid),),
            )
            meta = cur.fetchone()[0]
        assert meta["error_type"] == "TransientFetcherError"
        assert meta["fetch_source"] == "rest"


def test_multiple_intents_each_produce_one_fill(fresh_db):
    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)
        conn.commit()

        i1 = _make_intent(refs, paper_fill_uuid=uuid.uuid4(),
                          decision_reference_price=Decimal("100"))
        i2 = _make_intent(refs, paper_fill_uuid=uuid.uuid4(),
                          decision_reference_price=Decimal("200"))
        i3 = _make_intent(refs, paper_fill_uuid=uuid.uuid4(),
                          decision_reference_price=Decimal("300"))
        fetcher = FakeFetcher()
        fetcher.default_response = [_make_trade("100.05")]

        results = replay_intents(
            conn, [i1, i2, i3],
            fetcher=fetcher, fetch_source="archive",
        )
        conn.commit()

        assert len(results) == 3
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM paper.fills;")
            n = cur.fetchone()[0]
        assert n == 3


def test_replay_is_idempotent_on_same_intent(fresh_db):
    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)
        conn.commit()

        intent = _make_intent(refs)
        fetcher = FakeFetcher()
        fetcher.default_response = [_make_trade("150.30")]

        replay_intents(conn, [intent], fetcher=fetcher, fetch_source="archive")
        conn.commit()
        replay_intents(conn, [intent], fetcher=fetcher, fetch_source="archive")
        conn.commit()

        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM paper.fills "
                "WHERE paper_fill_uuid = %s;",
                (str(intent.paper_fill_uuid),),
            )
            n = cur.fetchone()[0]
        # Idempotent: only one row even after two replay calls.
        assert n == 1


def test_aggregator_sees_replay_rows(fresh_db):
    """End-to-end pipeline check: replay writes → Day 20.2 aggregator reads."""
    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)
        conn.commit()

        # Three success + one empty_window + one fetch_error.
        # Slippages: 10, 20, 30 bps → median 20, p90 28.
        intents_with_responses = [
            (_make_intent(refs, paper_fill_uuid=uuid.uuid4(),
                          decision_reference_price=Decimal("100")),
             [_make_trade("100.10")]),  # buy: 10 bps
            (_make_intent(refs, paper_fill_uuid=uuid.uuid4(),
                          decision_reference_price=Decimal("100")),
             [_make_trade("100.20")]),  # buy: 20 bps
            (_make_intent(refs, paper_fill_uuid=uuid.uuid4(),
                          decision_reference_price=Decimal("100")),
             [_make_trade("100.30")]),  # buy: 30 bps
            (_make_intent(refs, paper_fill_uuid=uuid.uuid4()),
             []),  # empty_window
            (_make_intent(refs, paper_fill_uuid=uuid.uuid4()),
             PermanentFetcherError("404")),  # fetch_error
        ]

        for intent, response in intents_with_responses:
            fetcher = FakeFetcher()
            fetcher.default_response = response
            replay_intents(
                conn, [intent], fetcher=fetcher, fetch_source="archive",
            )
        conn.commit()

        calibration = compute_slippage_calibration(conn)
        assert calibration.n == 3  # only success rows contribute to stats
        assert calibration.n_excluded_null == 2  # empty + fetch_error
        assert calibration.median_bps == Decimal("20.0000000000")
        assert calibration.min_bps == Decimal("10.0000000000")
        assert calibration.max_bps == Decimal("30.0000000000")


def test_replay_rejects_invalid_fetch_source(fresh_db):
    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)
        conn.commit()

        intent = _make_intent(refs)
        fetcher = FakeFetcher()
        fetcher.default_response = []
        with pytest.raises(ValueError, match="fetch_source"):
            replay_intents(
                conn, [intent],
                fetcher=fetcher, fetch_source="websocket",
            )



# ─── Day 24 additions: extra_metadata on PaperReplayIntent ──────────────


class TestExtraMetadata:
    """Day 24 reviewer-approved extension of PaperReplayIntent.

    The extra_metadata field lets callers attach arbitrary metadata keys
    to paper.fills rows. Audit keys from replay_runner must take
    precedence on collision so callers cannot override the audit trail.
    """

    def test_extra_metadata_persists_into_fill(self, fresh_db):
        with _connect() as conn:
            with conn.cursor() as cur:
                refs = _bootstrap(cur)
            intent = _make_intent(refs, extra_metadata={
                "custom_key": "custom_value",
                "another_key": 42,
            })
            fetcher = FakeFetcher()
            fetcher.default_response = []
            replay_intents(conn, [intent], fetcher=fetcher, fetch_source="archive")
            conn.commit()

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT metadata FROM paper.fills WHERE paper_fill_uuid = %s;",
                    (intent.paper_fill_uuid,),
                )
                metadata = cur.fetchone()[0]

        assert metadata["custom_key"] == "custom_value"
        assert metadata["another_key"] == 42
        assert metadata["window_seconds"] == 5
        assert metadata["fetch_source"] == "archive"

    def test_audit_keys_take_precedence_over_caller_keys(self, fresh_db):
        with _connect() as conn:
            with conn.cursor() as cur:
                refs = _bootstrap(cur)
            intent = _make_intent(refs, extra_metadata={
                "replay_status": "fake_status",
                "window_seconds": 999,
                "fetch_source": "fake_source",
                "trade_count": -1,
                "legitimate_key": "ok",
            })
            fetcher = FakeFetcher()
            fetcher.default_response = []
            replay_intents(conn, [intent], fetcher=fetcher, fetch_source="archive")
            conn.commit()

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT metadata FROM paper.fills WHERE paper_fill_uuid = %s;",
                    (intent.paper_fill_uuid,),
                )
                metadata = cur.fetchone()[0]

        # Audit fields took precedence
        assert metadata["replay_status"] == "empty_window"
        assert metadata["window_seconds"] == 5
        assert metadata["fetch_source"] == "archive"
        assert metadata["trade_count"] == 0
        # Caller's other key still there
        assert metadata["legitimate_key"] == "ok"

    def test_extra_metadata_none_preserves_a1_behavior(self, fresh_db):
        with _connect() as conn:
            with conn.cursor() as cur:
                refs = _bootstrap(cur)
            intent = _make_intent(refs)
            fetcher = FakeFetcher()
            fetcher.default_response = []
            replay_intents(conn, [intent], fetcher=fetcher, fetch_source="archive")
            conn.commit()

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT metadata FROM paper.fills WHERE paper_fill_uuid = %s;",
                    (intent.paper_fill_uuid,),
                )
                metadata = cur.fetchone()[0]

        expected_keys = {"window_seconds", "fetch_source", "replay_status", "trade_count"}
        assert set(metadata.keys()) == expected_keys
