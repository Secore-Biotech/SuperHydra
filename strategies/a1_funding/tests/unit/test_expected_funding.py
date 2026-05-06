"""Unit tests for strategies.a1_funding.signal.expected_funding.

Coverage:
  - Validation: empty window, multi-venue, multi-instrument, unsorted,
    non-Decimal discount, negative discount, naive as_of, look-ahead
  - Single-observation: stdev = 0, forecast == mean
  - Multi-observation: mean and stdev computed in Decimal correctly
  - Reproducibility: same inputs → byte-equal output across calls
  - Discount monotonicity: higher discount_k → smaller forecast (when stdev > 0)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from data.ingestion.vendors.binance.funding_rate import FundingRate
from strategies.a1_funding.signal.expected_funding import (
    EXPECTED_FUNDING_SCHEMA_VERSION,
    ExpectedFunding,
    ExpectedFundingError,
    expected_next_funding,
)


UTC = timezone.utc


def _fr(
    funding_time: datetime,
    rate: str,
    venue: str = "binance",
    instrument: str = "BTCUSDT",
) -> FundingRate:
    return FundingRate(
        venue=venue,
        instrument=instrument,
        funding_time=funding_time,
        funding_rate=Decimal(rate),
    )


def _window(
    rates: list[str],
    *,
    start: datetime = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
    interval: timedelta = timedelta(hours=8),
    venue: str = "binance",
    instrument: str = "BTCUSDT",
) -> list[FundingRate]:
    out = []
    for i, r in enumerate(rates):
        out.append(_fr(start + i * interval, r, venue, instrument))
    return out


# ─── Validation ──────────────────────────────────────────────────────────


def test_empty_window_raises():
    with pytest.raises(ExpectedFundingError, match="empty"):
        expected_next_funding(
            [], discount_k=Decimal("1"),
            as_of=datetime(2026, 1, 5, tzinfo=UTC),
        )


def test_multi_venue_raises():
    w = [
        _fr(datetime(2026, 1, 1, 0, 0, tzinfo=UTC), "0.0001", venue="binance"),
        _fr(datetime(2026, 1, 1, 8, 0, tzinfo=UTC), "0.0002", venue="okx"),
    ]
    with pytest.raises(ExpectedFundingError, match="multiple venues"):
        expected_next_funding(
            w, discount_k=Decimal("1"),
            as_of=datetime(2026, 1, 5, tzinfo=UTC),
        )


def test_multi_instrument_raises():
    w = [
        _fr(datetime(2026, 1, 1, 0, 0, tzinfo=UTC), "0.0001", instrument="BTCUSDT"),
        _fr(datetime(2026, 1, 1, 8, 0, tzinfo=UTC), "0.0002", instrument="ETHUSDT"),
    ]
    with pytest.raises(ExpectedFundingError, match="multiple instruments"):
        expected_next_funding(
            w, discount_k=Decimal("1"),
            as_of=datetime(2026, 1, 5, tzinfo=UTC),
        )


def test_unsorted_window_raises():
    w = [
        _fr(datetime(2026, 1, 1, 8, 0, tzinfo=UTC), "0.0001"),
        _fr(datetime(2026, 1, 1, 0, 0, tzinfo=UTC), "0.0002"),  # earlier!
    ]
    with pytest.raises(ExpectedFundingError, match="sorted"):
        expected_next_funding(
            w, discount_k=Decimal("1"),
            as_of=datetime(2026, 1, 5, tzinfo=UTC),
        )


def test_non_decimal_discount_raises():
    w = _window(["0.0001"])
    with pytest.raises(ExpectedFundingError, match="Decimal"):
        expected_next_funding(
            w, discount_k=1.0,  # float
            as_of=datetime(2026, 1, 5, tzinfo=UTC),
        )


def test_negative_discount_raises():
    w = _window(["0.0001"])
    with pytest.raises(ExpectedFundingError, match=">= 0"):
        expected_next_funding(
            w, discount_k=Decimal("-0.5"),
            as_of=datetime(2026, 1, 5, tzinfo=UTC),
        )


def test_naive_as_of_raises():
    w = _window(["0.0001"])
    with pytest.raises(ExpectedFundingError, match="timezone-aware"):
        expected_next_funding(
            w, discount_k=Decimal("1"),
            as_of=datetime(2026, 1, 5),  # naive
        )


def test_look_ahead_raises():
    """as_of must be strictly after the last window observation."""
    w = _window(["0.0001"], start=datetime(2026, 1, 5, 0, 0, 0, tzinfo=UTC))
    with pytest.raises(ExpectedFundingError, match="look-ahead"):
        expected_next_funding(
            w, discount_k=Decimal("1"),
            as_of=datetime(2026, 1, 5, 0, 0, 0, tzinfo=UTC),  # equal — disallowed
        )
    with pytest.raises(ExpectedFundingError, match="look-ahead"):
        expected_next_funding(
            w, discount_k=Decimal("1"),
            as_of=datetime(2026, 1, 4, tzinfo=UTC),  # before
        )


def test_min_lookback_enforced():
    w = _window(["0.0001", "0.0002"])
    with pytest.raises(ExpectedFundingError, match="min_lookback"):
        expected_next_funding(
            w, discount_k=Decimal("1"), min_lookback=5,
            as_of=datetime(2026, 1, 5, tzinfo=UTC),
        )


def test_min_lookback_below_one_raises():
    w = _window(["0.0001"])
    with pytest.raises(ExpectedFundingError, match="min_lookback"):
        expected_next_funding(
            w, discount_k=Decimal("1"), min_lookback=0,
            as_of=datetime(2026, 1, 5, tzinfo=UTC),
        )


# ─── Single observation ──────────────────────────────────────────────────


def test_single_observation_stdev_zero():
    w = _window(["0.00012345"])
    result = expected_next_funding(
        w, discount_k=Decimal("1"),
        as_of=datetime(2026, 1, 5, tzinfo=UTC),
    )
    assert result.stdev_rate == Decimal("0")
    assert result.mean_rate == Decimal("0.00012345")
    # discount * 0 = 0; forecast == mean
    assert result.forecast_rate == Decimal("0.00012345")


def test_single_observation_window_stats_correct():
    ft = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    w = [_fr(ft, "0.0005")]
    result = expected_next_funding(
        w, discount_k=Decimal("1"),
        as_of=datetime(2026, 1, 5, tzinfo=UTC),
    )
    assert result.window_size == 1
    assert result.window_start == ft
    assert result.window_end == ft


# ─── Multi-observation: math correctness ─────────────────────────────────


def test_two_observation_mean_correct():
    w = _window(["0.0001", "0.0003"])
    result = expected_next_funding(
        w, discount_k=Decimal("0"),  # zero discount → forecast == mean
        as_of=datetime(2026, 1, 5, tzinfo=UTC),
    )
    assert result.mean_rate == Decimal("0.0002")
    assert result.forecast_rate == result.mean_rate


def test_two_observation_stdev_correct():
    """Sample stdev (n-1 denominator) of [0.0001, 0.0003] is 0.0001*sqrt(2)/sqrt(2)
    Wait — let's just compute: variance = ((-0.0001)^2 + (0.0001)^2) / 1 = 2e-8;
    stdev = sqrt(2e-8) ≈ 0.0001414213..."""
    w = _window(["0.0001", "0.0003"])
    result = expected_next_funding(
        w, discount_k=Decimal("0"),
        as_of=datetime(2026, 1, 5, tzinfo=UTC),
    )
    expected_stdev = (Decimal("0.0002") - Decimal("0.0001")).copy_abs()
    # Actually with mean=0.0002, deviations are -0.0001 and +0.0001;
    # squared = 1e-8 each; sum = 2e-8; /(n-1)=1 → variance=2e-8;
    # stdev = sqrt(2) * 1e-4
    # Just check it's positive and matches the formula closely.
    assert result.stdev_rate > Decimal("0")
    # Verify it's close to sqrt(2) * 1e-4
    expected = Decimal("2").sqrt() * Decimal("0.0001")
    assert abs(result.stdev_rate - expected) < Decimal("1e-15")


def test_three_observation_uniform_stdev_zero():
    """All-equal window → stdev=0 → forecast == mean."""
    w = _window(["0.0001"] * 3)
    result = expected_next_funding(
        w, discount_k=Decimal("5"),  # discount irrelevant when stdev=0
        as_of=datetime(2026, 1, 5, tzinfo=UTC),
    )
    assert result.stdev_rate == Decimal("0")
    assert result.forecast_rate == Decimal("0.0001")


def test_negative_funding_handled():
    """Negative funding rates are valid; mean and forecast should both
    reflect that."""
    w = _window(["-0.0001", "-0.0002", "-0.0003"])
    result = expected_next_funding(
        w, discount_k=Decimal("0"),
        as_of=datetime(2026, 1, 5, tzinfo=UTC),
    )
    assert result.mean_rate == Decimal("-0.0002")


# ─── Discount behaviour ──────────────────────────────────────────────────


def test_higher_discount_smaller_forecast_when_stdev_positive():
    """With non-zero stdev, raising discount_k must lower forecast."""
    w = _window(["0.0001", "0.0003"])
    a = expected_next_funding(
        w, discount_k=Decimal("0"),
        as_of=datetime(2026, 1, 5, tzinfo=UTC),
    )
    b = expected_next_funding(
        w, discount_k=Decimal("1"),
        as_of=datetime(2026, 1, 5, tzinfo=UTC),
    )
    c = expected_next_funding(
        w, discount_k=Decimal("3"),
        as_of=datetime(2026, 1, 5, tzinfo=UTC),
    )
    assert a.forecast_rate > b.forecast_rate > c.forecast_rate


def test_zero_discount_yields_mean():
    w = _window(["0.0001", "0.0005", "0.0003"])
    result = expected_next_funding(
        w, discount_k=Decimal("0"),
        as_of=datetime(2026, 1, 5, tzinfo=UTC),
    )
    assert result.forecast_rate == result.mean_rate


# ─── Reproducibility — the headline property ─────────────────────────────


def test_reproducibility_byte_equal_across_calls():
    """Same inputs → byte-equal output. This is the property that makes
    paper-Sharpe reproducible."""
    w1 = _window(["0.0001", "0.0003", "-0.0002", "0.00015"])
    w2 = _window(["0.0001", "0.0003", "-0.0002", "0.00015"])

    a = expected_next_funding(
        w1, discount_k=Decimal("1.5"),
        as_of=datetime(2026, 1, 5, tzinfo=UTC),
    )
    b = expected_next_funding(
        w2, discount_k=Decimal("1.5"),
        as_of=datetime(2026, 1, 5, tzinfo=UTC),
    )

    # Equality via dataclass __eq__ — every field must match.
    assert a == b

    # And explicitly: forecast_rate is byte-equal as Decimal.
    assert a.forecast_rate == b.forecast_rate
    assert str(a.forecast_rate) == str(b.forecast_rate)


def test_reproducibility_idempotent_on_same_window():
    """Calling the same function twice on the same window must produce
    byte-equal results — no hidden mutation, no clock dependency."""
    w = _window(["0.0001", "0.0002", "0.0003"])
    as_of = datetime(2026, 1, 5, tzinfo=UTC)
    a = expected_next_funding(w, discount_k=Decimal("1"), as_of=as_of)
    b = expected_next_funding(w, discount_k=Decimal("1"), as_of=as_of)
    assert a == b


def test_window_does_not_mutate_input():
    """Defensive: the function must not modify its input list (sort
    in-place or otherwise)."""
    w = _window(["0.0001", "0.0002", "0.0003"])
    snapshot = list(w)  # shallow copy
    expected_next_funding(
        w, discount_k=Decimal("1"),
        as_of=datetime(2026, 1, 5, tzinfo=UTC),
    )
    assert w == snapshot


# ─── Output metadata ─────────────────────────────────────────────────────


def test_output_carries_window_metadata():
    w = _window(["0.0001", "0.0002", "0.0003"])
    result = expected_next_funding(
        w, discount_k=Decimal("1"),
        as_of=datetime(2026, 1, 5, tzinfo=UTC),
    )
    assert result.window_size == 3
    assert result.window_start == w[0].funding_time
    assert result.window_end == w[-1].funding_time
    assert result.discount_k == Decimal("1")
    assert result.venue == "binance"
    assert result.instrument == "BTCUSDT"


def test_output_carries_schema_version():
    w = _window(["0.0001"])
    result = expected_next_funding(
        w, discount_k=Decimal("1"),
        as_of=datetime(2026, 1, 5, tzinfo=UTC),
    )
    assert result.schema_version == EXPECTED_FUNDING_SCHEMA_VERSION
    assert result.schema_version == "expected_funding.v0"
