"""Effective-spread estimators for tape-based research calibration.

Day 19b.2 adds Roll's autocovariance estimator (Roll 1984). The
classical version: from a sequence of trade prices, compute first-
order autocovariance of price changes; if negative, the implied
half-spread is sqrt(-cov_1).

The intuition is bid-ask bounce: in a market with no information
flow, an aggressive buy lifts the offer and the next aggressive
sell hits the bid, producing negatively-correlated price changes.
The magnitude of that negative correlation is half the spread
squared. If the autocovariance is non-negative, the bid-ask-bounce
assumption fails (typically because trend or directional flow
dominates), and Roll's estimator is undefined for the window.

Limitations of Roll's estimator (documented for downstream consumers):
  - Assumes equal probability of buy-initiated and sell-initiated
    trades. Asymmetric flow biases the estimate.
  - Assumes no information flow within the window. Trending periods
    produce positive autocovariance and an undefined estimate.
  - Static-spread assumption — does not capture intraday spread
    variation. Caller buckets time windows to mitigate.
  - Trade-side aware estimators (Lee-Ready, Glosten-Harris) are
    strictly better when side information is available; Day 19b.2
    uses Roll because BinanceTrade.is_buyer_maker only tells us
    aggressor side, not the resting side at the time of the fill.

Day 19b.2 scope: research support, NOT execution-grade calibration.
A Roll estimate that disagrees with Day 19a's 1 bp research-calibrated
slippage means EITHER our spread assumption is wrong OR the
calibration window doesn't reflect A1's intended trading regime.
Either finding is worth committing.

Reference: Roll, R. (1984). "A Simple Implicit Measure of the
Effective Bid-Ask Spread in an Efficient Market." Journal of
Finance, 39(4), 1127-1139.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, getcontext
from typing import Final, Sequence


# Decimal precision for autocovariance arithmetic. The default 28
# is more than enough for typical trade-price sequences; we set it
# explicitly so the estimator's behavior doesn't depend on the
# caller's getcontext() state.
_LOCAL_PRECISION: Final[int] = 50


ESTIMATOR_NAME: Final[str] = "roll_1984"
ESTIMATOR_VERSION: Final[str] = "v1"


@dataclass(frozen=True)
class RollEstimate:
    """Output of Roll's autocovariance estimator over one window.

    Fields:
        n_trades: number of price observations in the window. Must
            be >= 3 (estimator requires two consecutive price-change
            pairs).
        autocov_1: first-order autocovariance of price changes,
            in price-units squared. Decimal for lineage.
        half_spread_price: estimated half-spread in price units.
            None if the estimate is undefined.
        full_spread_price: 2 * half_spread_price. None if undefined.
        half_spread_bps: half_spread_price / mean_price * 10000,
            in basis points. None if undefined or mean_price is zero.
        full_spread_bps: 2 * half_spread_bps. None if undefined.
        mean_price: mean of input prices, used for bps conversion.
        estimator_name: "roll_1984".
        estimator_version: "v1".
        undefined_reason: None if estimate is defined; otherwise a
            short tag explaining why ("non_negative_autocovariance",
            "zero_mean_price").

    Returning explicit None for undefined estimates rather than zero
    is a deliberate choice. Zero would falsely imply "no spread";
    None correctly says "estimator could not produce a value here."
    Downstream consumers must handle the undefined case explicitly.
    """

    n_trades: int
    autocov_1: Decimal
    half_spread_price: Decimal | None
    full_spread_price: Decimal | None
    half_spread_bps: Decimal | None
    full_spread_bps: Decimal | None
    mean_price: Decimal
    estimator_name: str = ESTIMATOR_NAME
    estimator_version: str = ESTIMATOR_VERSION
    undefined_reason: str | None = None

    def __post_init__(self) -> None:
        if self.n_trades < 3:
            raise ValueError(
                f"n_trades must be >= 3, got {self.n_trades}"
            )
        if not isinstance(self.autocov_1, Decimal):
            raise TypeError(
                f"autocov_1 must be Decimal, got {type(self.autocov_1).__name__}"
            )
        if not isinstance(self.mean_price, Decimal):
            raise TypeError(
                f"mean_price must be Decimal, got {type(self.mean_price).__name__}"
            )
        defined_fields = (
            self.half_spread_price,
            self.full_spread_price,
            self.half_spread_bps,
            self.full_spread_bps,
        )
        if self.undefined_reason is not None:
            for f in defined_fields:
                if f is not None:
                    raise ValueError(
                        f"undefined estimate must have all spread fields None; "
                        f"got {defined_fields}"
                    )
        else:
            for f, name in zip(defined_fields, [
                "half_spread_price",
                "full_spread_price",
                "half_spread_bps",
                "full_spread_bps",
            ]):
                if f is None:
                    raise ValueError(
                        f"defined estimate (no undefined_reason) must have "
                        f"all spread fields set; {name} is None"
                    )


def estimate_roll(
    prices: Sequence[Decimal],
    mean_price: Decimal | None = None,
) -> RollEstimate:
    """Compute Roll's effective-spread estimate over a price window.

    Algorithm:
      1. Compute price changes dp_t = p_t - p_{t-1} for t in [1, n).
      2. Compute first-order autocovariance:
           autocov_1 = (1/(n-2)) * sum((dp_t - mean(dp)) * (dp_{t-1} - mean(dp)))
         Sample autocovariance with bias correction. We use the
         (n-2) divisor because we have n-1 price changes and consume
         one degree of freedom for the mean.
      3. If autocov_1 < 0:
           half_spread = sqrt(-autocov_1)
         Else:
           estimate is undefined; return None for spread fields with
           reason "non_negative_autocovariance".

    Args:
        prices: sequence of trade prices. Must have len >= 3.
        mean_price: optional pre-computed mean for bps conversion.
            Defaults to mean(prices). If zero, bps fields are None
            even when half_spread_price is defined.

    Returns:
        RollEstimate with all fields populated.

    Raises:
        ValueError: if len(prices) < 3 or any price is non-positive.
    """
    n = len(prices)
    if n < 3:
        raise ValueError(f"need >= 3 prices, got {n}")
    for i, p in enumerate(prices):
        if not isinstance(p, Decimal):
            raise TypeError(
                f"prices[{i}] must be Decimal, got {type(p).__name__}"
            )
        if p <= 0:
            raise ValueError(f"prices[{i}] must be positive, got {p}")

    # Operate in a local Decimal context for stable precision.
    ctx = getcontext().copy()
    ctx.prec = _LOCAL_PRECISION

    # Compute price changes.
    deltas: list[Decimal] = []
    for i in range(1, n):
        deltas.append(ctx.subtract(prices[i], prices[i - 1]))

    # Mean of price changes.
    delta_sum = Decimal(0)
    for d in deltas:
        delta_sum = ctx.add(delta_sum, d)
    delta_mean = ctx.divide(delta_sum, Decimal(len(deltas)))

    # First-order sample autocovariance with mean-correction.
    # autocov_1 = (1/(n-2)) * sum_{t=1..n-2} (dp_t - mean) * (dp_{t-1} - mean)
    # We have n-1 deltas; (n-1)-1 = n-2 lagged products.
    if len(deltas) < 2:
        # Already prevented by n >= 3 check, but defensive.
        raise ValueError(f"need >= 2 deltas, got {len(deltas)}")

    autocov_sum = Decimal(0)
    for t in range(1, len(deltas)):
        a = ctx.subtract(deltas[t], delta_mean)
        b = ctx.subtract(deltas[t - 1], delta_mean)
        autocov_sum = ctx.add(autocov_sum, ctx.multiply(a, b))
    divisor = Decimal(len(deltas) - 1)
    autocov_1 = ctx.divide(autocov_sum, divisor)

    # Compute mean_price if not provided.
    if mean_price is None:
        price_sum = Decimal(0)
        for p in prices:
            price_sum = ctx.add(price_sum, p)
        mean_price = ctx.divide(price_sum, Decimal(n))

    # Undefined branch: non-negative autocovariance.
    if autocov_1 >= 0:
        return RollEstimate(
            n_trades=n,
            autocov_1=autocov_1,
            half_spread_price=None,
            full_spread_price=None,
            half_spread_bps=None,
            full_spread_bps=None,
            mean_price=mean_price,
            undefined_reason="non_negative_autocovariance",
        )

    # Defined branch: half_spread = sqrt(-autocov_1).
    neg_autocov = ctx.subtract(Decimal(0), autocov_1)
    half_spread_price = neg_autocov.sqrt(context=ctx)
    full_spread_price = ctx.multiply(Decimal(2), half_spread_price)

    if mean_price == 0:
        # Spread defined in price units, but bps conversion impossible.
        return RollEstimate(
            n_trades=n,
            autocov_1=autocov_1,
            half_spread_price=None,
            full_spread_price=None,
            half_spread_bps=None,
            full_spread_bps=None,
            mean_price=mean_price,
            undefined_reason="zero_mean_price",
        )

    bps_factor = Decimal("10000")
    half_spread_bps = ctx.multiply(
        ctx.divide(half_spread_price, mean_price), bps_factor
    )
    full_spread_bps = ctx.multiply(Decimal(2), half_spread_bps)

    return RollEstimate(
        n_trades=n,
        autocov_1=autocov_1,
        half_spread_price=half_spread_price,
        full_spread_price=full_spread_price,
        half_spread_bps=half_spread_bps,
        full_spread_bps=full_spread_bps,
        mean_price=mean_price,
    )
