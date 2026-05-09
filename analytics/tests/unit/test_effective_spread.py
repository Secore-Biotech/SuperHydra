"""Unit tests for Roll's effective-spread estimator."""
from __future__ import annotations

from decimal import Decimal

import pytest

from analytics.effective_spread import (
    ESTIMATOR_NAME,
    ESTIMATOR_VERSION,
    RollEstimate,
    estimate_roll,
)


# ─── Synthetic bid-ask-bounce series ────────────────────────────────────


class TestBidAskBounceRecovery:
    """The textbook test: construct a price series with a known spread
    and bid-ask bounce, verify the estimator recovers the spread."""

    def test_strict_alternation_recovers_full_bid_ask_gap(self):
        """STRICT alternation (deterministic, not random q_t):
          bid=99.95, ask=100.05, gap=0.10
          series=[99.95, 100.05, 99.95, 100.05, ...]
        Price changes alternate: +0.10, -0.10, +0.10, -0.10, ...
        With strict (not random) alternation, lagged product is
        always -(0.10)^2 = -0.01, so autocov_1 = -0.01 (NOT -(0.10/2)^2).
        Estimated half_spread = sqrt(0.01) = 0.10.

        Roll's classical derivation assumes random buy/sell indicator
        q_t with E[q_t * q_{t-1}] = 0; under that assumption,
        autocov = -(s/2)^2 and the estimator recovers s/2 as the
        half-spread. Strict alternation has E[q_t * q_{t-1}] = -1
        instead of 0, which doubles the magnitude of the autocovariance
        and inflates the estimate by sqrt(2).

        This test documents the deterministic-alternation behavior
        (the estimate reports the full bid-ask gap as the half-spread,
        because the bounce is pathologically perfect). The
        with_drift test uses near-random sign flips to recover the
        textbook Roll bias."""
        bid = Decimal("99.95")
        ask = Decimal("100.05")
        # 21 prices = 20 deltas (even), so delta_mean is exactly zero.
        prices = [bid if i % 2 == 0 else ask for i in range(21)]
        # Pass mean=100 explicitly: 11 bids + 10 asks gives sample mean
        # 99.998..., not 100, which would shift bps slightly. Using
        # the true midpoint isolates the spread math from the imbalance.
        result = estimate_roll(prices, mean_price=Decimal("100"))

        assert result.undefined_reason is None
        assert result.n_trades == 21
        # autocov_1 = -(gap)^2 = -(0.10)^2 = -0.01 for strict alternation.
        # half_spread_price = sqrt(0.01) = 0.10.
        assert abs(result.half_spread_price - Decimal("0.10")) < Decimal("1e-25")
        assert abs(result.full_spread_price - Decimal("0.20")) < Decimal("1e-25")
        # Mean price = 100.0 → half_spread_bps = 10 bps.
        assert abs(result.half_spread_bps - Decimal("10.0")) < Decimal("1e-23")
        assert abs(result.full_spread_bps - Decimal("20.0")) < Decimal("1e-23")

    def test_strict_alternation_with_drift_still_estimable(self):
        """Strict alternation around drifting midpoint. Under strict
        alternation, the estimator is biased high by sqrt(2) vs
        textbook Roll (see test above). Drift introduces additional
        bias. Test asserts only that the estimator returns a defined
        non-degenerate result in the right order of magnitude."""
        # midpoint drifts from 100 to 100.1 over 100 trades.
        # half-gap = 0.05. drift per trade = 0.001.
        prices = []
        half_gap = Decimal("0.05")
        for i in range(100):
            mid = Decimal("100") + Decimal("0.001") * Decimal(i)
            tick = mid + (half_gap if i % 2 == 0 else -half_gap)
            prices.append(tick)
        result = estimate_roll(prices)
        assert result.undefined_reason is None
        # Estimate is biased by strict-alternation factor sqrt(2)
        # plus drift. Just assert it lands in a reasonable corridor:
        # bigger than 0.04 (rules out near-zero), smaller than 0.20
        # (rules out absurd estimates).
        assert Decimal("0.04") < result.half_spread_price < Decimal("0.20")


# ─── Undefined-estimate paths ───────────────────────────────────────────


class TestUndefinedEstimate:
    def test_constant_price_returns_undefined(self):
        """Zero variance in price changes → autocov_1 = 0 → undefined."""
        prices = [Decimal("100")] * 10
        result = estimate_roll(prices)
        assert result.undefined_reason == "non_negative_autocovariance"
        assert result.half_spread_price is None
        assert result.full_spread_price is None
        assert result.half_spread_bps is None
        assert result.full_spread_bps is None
        assert result.autocov_1 == 0

    def test_strictly_trending_returns_undefined(self):
        """Monotonic rise: positive autocov, not bid-ask bounce."""
        prices = [Decimal("100") + Decimal("0.01") * Decimal(i) for i in range(20)]
        result = estimate_roll(prices)
        # Price changes are constant +0.01; autocov over that is 0
        # (with mean correction applied), which is non-negative → undefined.
        assert result.undefined_reason == "non_negative_autocovariance"

    def test_positive_autocov_from_momentum_returns_undefined(self):
        """Series with momentum (positive lag-1 correlation in dp):
        runs of same-sign moves. autocov > 0."""
        # +1, +1, +1, -1, -1, -1, +1, +1, +1, -1, -1, -1, ...
        # mean delta = 0 over a balanced window; positive correlation
        # in adjacent deltas because adjacent moves are same-sign 5 of 6 times.
        prices = [Decimal("100")]
        for run_idx in range(10):
            sign = Decimal("0.05") if run_idx % 2 == 0 else Decimal("-0.05")
            for _ in range(3):
                prices.append(prices[-1] + sign)
        result = estimate_roll(prices)
        assert result.undefined_reason == "non_negative_autocovariance"


# ─── Validation ─────────────────────────────────────────────────────────


class TestValidation:
    def test_too_few_prices_raises(self):
        with pytest.raises(ValueError, match="need >= 3 prices"):
            estimate_roll([Decimal("100"), Decimal("100.05")])

    def test_one_price_raises(self):
        with pytest.raises(ValueError, match="need >= 3 prices"):
            estimate_roll([Decimal("100")])

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="need >= 3 prices"):
            estimate_roll([])

    def test_non_decimal_raises(self):
        with pytest.raises(TypeError, match="must be Decimal"):
            estimate_roll([100.0, 100.05, 100.0])  # type: ignore[list-item]

    def test_zero_price_raises(self):
        with pytest.raises(ValueError, match="must be positive"):
            estimate_roll([Decimal("100"), Decimal("0"), Decimal("100")])

    def test_negative_price_raises(self):
        with pytest.raises(ValueError, match="must be positive"):
            estimate_roll([Decimal("100"), Decimal("-1"), Decimal("100")])


# ─── Bps conversion ─────────────────────────────────────────────────────


class TestBpsConversion:
    def test_bps_uses_supplied_mean_price(self):
        """If caller provides a different mean_price, bps reflects it.
        Test the RATIO is correct regardless of the absolute spread
        value — bps for mean=100 should be exactly 2x bps for mean=200."""
        prices = [
            Decimal("99.95"), Decimal("100.05"),
            Decimal("99.95"), Decimal("100.05"),
            Decimal("99.95"), Decimal("100.05"),
        ]
        result_default = estimate_roll(prices)
        result_with_mean = estimate_roll(prices, mean_price=Decimal("200"))
        # Same half_spread_price; different bps.
        assert result_default.half_spread_price == result_with_mean.half_spread_price
        # bps ratio = mean ratio = 2.
        ratio = result_default.half_spread_bps / result_with_mean.half_spread_bps
        assert abs(ratio - Decimal("2")) < Decimal("1e-25")

    def test_zero_mean_price_yields_undefined_bps(self):
        """If supplied mean_price is zero, bps is undefined even though
        half_spread_price is computable. Returns undefined estimate
        with reason 'zero_mean_price'."""
        prices = [
            Decimal("0.001"), Decimal("0.002"),
            Decimal("0.001"), Decimal("0.002"),
            Decimal("0.001"), Decimal("0.002"),
        ]
        result = estimate_roll(prices, mean_price=Decimal("0"))
        assert result.undefined_reason == "zero_mean_price"
        assert result.half_spread_price is None
        assert result.full_spread_price is None
        assert result.half_spread_bps is None
        assert result.full_spread_bps is None
        # autocov_1 was negative (defined estimate would have been
        # possible); check that we computed it before failing.
        assert result.autocov_1 < 0


# ─── Determinism + dataclass invariants ─────────────────────────────────


class TestDeterminism:
    def test_same_inputs_produce_same_estimate(self):
        prices = [Decimal("99.95"), Decimal("100.05")] * 10
        a = estimate_roll(prices)
        b = estimate_roll(prices)
        assert a.half_spread_price == b.half_spread_price
        assert a.autocov_1 == b.autocov_1
        assert a.half_spread_bps == b.half_spread_bps

    def test_estimator_name_and_version_set(self):
        prices = [Decimal("99.95"), Decimal("100.05")] * 10
        result = estimate_roll(prices)
        assert result.estimator_name == ESTIMATOR_NAME
        assert result.estimator_version == ESTIMATOR_VERSION
        assert result.estimator_name == "roll_1984"
        assert result.estimator_version == "v1"


class TestDataclassInvariants:
    def test_undefined_with_defined_field_raises(self):
        """RollEstimate post-init enforces consistency."""
        with pytest.raises(ValueError, match="undefined estimate must have"):
            RollEstimate(
                n_trades=10,
                autocov_1=Decimal("0.001"),
                half_spread_price=Decimal("0.05"),  # inconsistent with reason
                full_spread_price=None,
                half_spread_bps=None,
                full_spread_bps=None,
                mean_price=Decimal("100"),
                undefined_reason="non_negative_autocovariance",
            )

    def test_defined_with_none_field_raises(self):
        """Defined estimate must populate all spread fields."""
        with pytest.raises(ValueError, match="defined estimate"):
            RollEstimate(
                n_trades=10,
                autocov_1=Decimal("-0.001"),
                half_spread_price=None,  # inconsistent
                full_spread_price=Decimal("0.10"),
                half_spread_bps=Decimal("10"),
                full_spread_bps=Decimal("20"),
                mean_price=Decimal("100"),
            )

    def test_n_too_small_raises(self):
        with pytest.raises(ValueError, match="n_trades must be"):
            RollEstimate(
                n_trades=2,
                autocov_1=Decimal("0"),
                half_spread_price=None,
                full_spread_price=None,
                half_spread_bps=None,
                full_spread_bps=None,
                mean_price=Decimal("100"),
                undefined_reason="non_negative_autocovariance",
            )
