"""Integration tests for slippage calibration analytics.

Day 20.2: aggregator over paper.fills evidence container.

Uses the existing fresh_db / _connect / _setup_basic_0009 + _alembic 0010
pattern. PaperFillCandidate + write_paper_fill from Day 20.1 are used
to populate test data; the aggregator reads it.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from tests.integration.test_migrations import (  # noqa: F401
    _alembic,
    _connect,
    _setup_basic_0009,
    fresh_db,
)
from execution.paper.fill_writer import (
    PaperFillCandidate,
    write_paper_fill,
)
from analytics.slippage_calibration import (
    SlippageCalibration,
    compute_slippage_calibration,
)


def _bootstrap(cur):
    """Apply 0010 then bootstrap registry. Order matters (FK lock — see
    Day 20.1 commit body for details)."""
    _alembic("upgrade", "0010")
    return _setup_basic_0009(cur)


def _seed_fill(
    conn,
    refs,
    *,
    observed_slippage_bps: Decimal | None,
    cost_profile_name: str = "binance_vip5_alt_research_v1",
    instrument_id: int | None = None,
    filled_at: datetime | None = None,
    quantity: Decimal = Decimal("1.5"),
) -> int:
    """Insert one paper.fills row with the given observed slippage.

    Returns the fill's row id.
    """
    if filled_at is None:
        filled_at = datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc)
    candidate = PaperFillCandidate(
        paper_fill_uuid=uuid.uuid4(),
        source_mode="PAPER_RESEARCH",
        strategy_id=refs["strategy_id"],
        portfolio_id=refs["portfolio_id"],
        account_id=refs["account_id"],
        instrument_id=instrument_id if instrument_id is not None
                     else refs["instrument_id"],
        side="buy",
        quantity=quantity,
        price=Decimal("150.00"),
        modeled_slippage_bps=Decimal("0.5"),
        observed_slippage_bps=observed_slippage_bps,
        cost_profile_name=cost_profile_name,
        cost_profile_hash="a" * 64,
        filled_at=filled_at,
    )
    fill_id, _, _ = write_paper_fill(conn, candidate)
    return fill_id


# ─── Empty / trivial cases ──────────────────────────────────────────────


def test_empty_table_returns_zero_n(fresh_db):
    with _connect() as conn:
        with conn.cursor() as cur:
            _bootstrap(cur)
        conn.commit()

        result = compute_slippage_calibration(conn)
        assert result.n == 0
        assert result.n_excluded_null == 0
        assert result.median_bps is None
        assert result.p25_bps is None
        assert result.p75_bps is None
        assert result.p90_bps is None
        assert result.min_bps is None
        assert result.max_bps is None


def test_single_fill_returns_single_value_for_all_stats(fresh_db):
    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)
        conn.commit()

        _seed_fill(conn, refs, observed_slippage_bps=Decimal("0.5"))
        conn.commit()

        result = compute_slippage_calibration(conn)
        assert result.n == 1
        assert result.n_excluded_null == 0
        # All percentiles collapse to the single value.
        assert result.median_bps == Decimal("0.5000000000")
        assert result.p25_bps == Decimal("0.5000000000")
        assert result.p75_bps == Decimal("0.5000000000")
        assert result.p90_bps == Decimal("0.5000000000")
        assert result.min_bps == Decimal("0.5000000000")
        assert result.max_bps == Decimal("0.5000000000")


# ─── Percentile correctness ─────────────────────────────────────────────


def test_multiple_fills_median_and_p90_correct(fresh_db):
    """Insert values 1..10 in bps. Verify median ≈ 5.5, p90 ≈ 9.1."""
    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)
        conn.commit()

        for i in range(1, 11):
            _seed_fill(conn, refs, observed_slippage_bps=Decimal(i))
        conn.commit()

        result = compute_slippage_calibration(conn)
        assert result.n == 10
        assert result.n_excluded_null == 0
        # Median of 1..10 = 5.5
        assert result.median_bps == Decimal("5.5000000000")
        # p25 of 1..10 = 3.25
        assert result.p25_bps == Decimal("3.2500000000")
        # p75 of 1..10 = 7.75
        assert result.p75_bps == Decimal("7.7500000000")
        # p90 of 1..10 = 9.1
        assert result.p90_bps == Decimal("9.1000000000")
        assert result.min_bps == Decimal("1.0000000000")
        assert result.max_bps == Decimal("10.0000000000")


# ─── NULL handling ──────────────────────────────────────────────────────


def test_null_observed_excluded_from_stats_counted_separately(fresh_db):
    """Insert 3 valid values + 2 NULL observed_slippage rows.
    Stats over the 3 valid; n_excluded_null = 2."""
    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)
        conn.commit()

        _seed_fill(conn, refs, observed_slippage_bps=Decimal("1.0"))
        _seed_fill(conn, refs, observed_slippage_bps=Decimal("2.0"))
        _seed_fill(conn, refs, observed_slippage_bps=Decimal("3.0"))
        _seed_fill(conn, refs, observed_slippage_bps=None)
        _seed_fill(conn, refs, observed_slippage_bps=None)
        conn.commit()

        result = compute_slippage_calibration(conn)
        assert result.n == 3
        assert result.n_excluded_null == 2
        assert result.median_bps == Decimal("2.0000000000")
        assert result.min_bps == Decimal("1.0000000000")
        assert result.max_bps == Decimal("3.0000000000")


# ─── Filters ────────────────────────────────────────────────────────────


def test_filter_by_cost_profile_name(fresh_db):
    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)
        conn.commit()

        # Insert 3 under profile A, 2 under profile B.
        for v in [Decimal("1"), Decimal("2"), Decimal("3")]:
            _seed_fill(conn, refs, observed_slippage_bps=v,
                       cost_profile_name="profile_A")
        for v in [Decimal("10"), Decimal("20")]:
            _seed_fill(conn, refs, observed_slippage_bps=v,
                       cost_profile_name="profile_B")
        conn.commit()

        result_a = compute_slippage_calibration(
            conn, cost_profile_name="profile_A")
        assert result_a.n == 3
        assert result_a.cost_profile_name == "profile_A"
        assert result_a.median_bps == Decimal("2.0000000000")

        result_b = compute_slippage_calibration(
            conn, cost_profile_name="profile_B")
        assert result_b.n == 2
        assert result_b.median_bps == Decimal("15.0000000000")

        result_all = compute_slippage_calibration(conn)
        assert result_all.n == 5


def test_filter_by_instrument_id(fresh_db):
    """Need a second instrument_id to filter on."""
    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)

            # Create a second instrument under the same venue.
            cur.execute(
                "INSERT INTO registry.instruments "
                "(instrument_code, display_name, venue_id, "
                " base_asset_id, quote_asset_id, instrument_type, status) "
                "VALUES ('ETH_TEST', 'ETH/USDT Test Perp', %s, "
                " %s, %s, 'perp', 'active') RETURNING id;",
                (refs["venue_id"], refs["btc_id"], refs["btc_id"]),
            )
            second_instrument_id = cur.fetchone()[0]
        conn.commit()

        _seed_fill(conn, refs, observed_slippage_bps=Decimal("1"))
        _seed_fill(conn, refs, observed_slippage_bps=Decimal("2"))
        _seed_fill(conn, refs, observed_slippage_bps=Decimal("100"),
                   instrument_id=second_instrument_id)
        conn.commit()

        result_first = compute_slippage_calibration(
            conn, instrument_id=refs["instrument_id"])
        assert result_first.n == 2
        assert result_first.instrument_id == refs["instrument_id"]
        assert result_first.median_bps == Decimal("1.5000000000")

        result_second = compute_slippage_calibration(
            conn, instrument_id=second_instrument_id)
        assert result_second.n == 1
        assert result_second.median_bps == Decimal("100.0000000000")


def test_filter_by_window_inclusive_start_exclusive_end(fresh_db):
    """window_start <= filled_at < window_end."""
    with _connect() as conn:
        with conn.cursor() as cur:
            refs = _bootstrap(cur)
        conn.commit()

        t0 = datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc)

        _seed_fill(conn, refs, observed_slippage_bps=Decimal("1"),
                   filled_at=t0)                          # exactly start
        _seed_fill(conn, refs, observed_slippage_bps=Decimal("2"),
                   filled_at=t0 + timedelta(seconds=30))  # in window
        _seed_fill(conn, refs, observed_slippage_bps=Decimal("3"),
                   filled_at=t0 + timedelta(minutes=1))   # exactly end (out)
        _seed_fill(conn, refs, observed_slippage_bps=Decimal("4"),
                   filled_at=t0 - timedelta(seconds=1))   # before start (out)
        conn.commit()

        window_start = t0
        window_end = t0 + timedelta(minutes=1)
        result = compute_slippage_calibration(
            conn,
            window_start=window_start,
            window_end=window_end,
        )
        assert result.n == 2
        assert result.median_bps == Decimal("1.5000000000")
        assert result.window_start == window_start
        assert result.window_end == window_end


# ─── Filter-validation paths ────────────────────────────────────────────


def test_naive_window_raises_value_error():
    """Pure validation; no DB needed."""
    # Use a dummy connection-less call by importing the validator path.
    # The function validates timezone-awareness before touching the DB,
    # so we can call it with conn=None for the validation step.
    with pytest.raises(ValueError, match="timezone-aware"):
        compute_slippage_calibration(
            conn=None,
            window_start=datetime(2026, 5, 11, 12, 0),  # naive
        )


def test_window_end_before_start_raises_value_error():
    with pytest.raises(ValueError, match="strictly after"):
        compute_slippage_calibration(
            conn=None,
            window_start=datetime(2026, 5, 11, 13, 0, tzinfo=timezone.utc),
            window_end=datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc),
        )
