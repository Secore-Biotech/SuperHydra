"""A1 sizer.

Pure function. Given a `SignalEvaluation`, the current signed perp
position, and a `SizingConfig`, produce an `OrderIntent` describing the
two-leg trade that moves position to target — or None if no trade is
needed.

Position convention:
  - `current_perp_quantity` is signed: positive = long perp, negative =
    short perp.
  - "Target position" is determined by `SignalDecision`:
      LONG_PERP_SHORT_SPOT  → target perp position = +max_quantity
      SHORT_PERP_LONG_SPOT  → target perp position = -max_quantity
      FLAT                  → target perp position = 0
  - The order quantity is `target - current` (signed). A positive delta
    means buy; negative means sell. Absolute value goes into the leg's
    `quantity` field; direction goes into `side`.
  - If `|target - current|` < `min_quantity`, the intent is suppressed
    (returns None). This avoids odd-lot orders from rounding noise.

Hedge construction:
  - The spot leg always opposes the perp leg in side.
  - Quantities are equal (equal-nominal hedge at P0).

What this function does NOT do:
  - It does not check `max_total_notional_usd`. That ceiling is enforced
    at the portfolio level by the runner (which knows about other
    instruments' positions); a single-instrument sizer can't see the
    aggregate. The runner's portfolio cap is a separate Day 8 concern.
  - It does not consider current spot position. P0 assumes the spot leg
    is implicitly hedged (we don't try to recover an imbalanced spot
    position by undersizing the perp leg). If the spot side is not
    hedged 1:1 with the perp side, that's a reconciliation alarm, not
    a sizing decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from strategies.a1_funding.config.sizing import (
    SizingConfig,
    SizingConfigError,
)
from strategies.a1_funding.signal.evaluate import (
    SignalDecision,
    SignalEvaluation,
)
from strategies.a1_funding.sizing.order_intent import (
    InstrumentKind,
    OrderIntent,
    OrderLeg,
    OrderSide,
)


SIZER_SCHEMA_VERSION: Final[str] = "sizer.v0"


# ─── Errors ───────────────────────────────────────────────────────────────


class SizerError(Exception):
    pass


# ─── Sizer ────────────────────────────────────────────────────────────────


def size_intent(
    signal: SignalEvaluation,
    current_perp_quantity: Decimal,
    sizing_config: SizingConfig,
) -> OrderIntent | None:
    """Compute the OrderIntent (or None) for one signal evaluation.

    Args:
        signal: the SignalEvaluation produced by evaluate_signal()
        current_perp_quantity: signed current perp position in base-asset
            units. Positive=long, negative=short, zero=flat.
        sizing_config: the SizingConfig in force at this decision moment

    Returns:
        OrderIntent if a trade is needed; None otherwise.

    Raises:
        SizerError on configuration mismatches or invariant violations.
    """
    if not isinstance(current_perp_quantity, Decimal):
        raise SizerError(
            f"current_perp_quantity must be Decimal, got "
            f"{type(current_perp_quantity).__name__}"
        )

    # Resolve the sizing rule for this instrument.
    try:
        rule = sizing_config.rule_for_perp(signal.instrument)
    except SizingConfigError as e:
        raise SizerError(str(e)) from e

    # Venue consistency check: signal.venue must match rule.venue.
    if signal.venue != rule.venue:
        raise SizerError(
            f"signal venue {signal.venue!r} does not match sizing rule "
            f"venue {rule.venue!r} for instrument {signal.instrument!r}"
        )

    # Map decision to target perp position (signed).
    if signal.decision == SignalDecision.LONG_PERP_SHORT_SPOT:
        target = rule.max_quantity
    elif signal.decision == SignalDecision.SHORT_PERP_LONG_SPOT:
        target = -rule.max_quantity
    elif signal.decision == SignalDecision.FLAT:
        target = Decimal("0")
    else:
        # Defensive — SignalDecision is a closed enum, but guard anyway.
        raise SizerError(f"unknown SignalDecision: {signal.decision!r}")

    delta = target - current_perp_quantity

    # If delta is zero, no trade.
    if delta == Decimal("0"):
        return None

    # If the magnitude of the trade is below min_quantity, suppress.
    abs_delta = abs(delta)
    if abs_delta < rule.min_quantity:
        return None

    # Build the two legs. Direction:
    #   delta > 0 → buy perp (move position up), so spot must sell
    #   delta < 0 → sell perp (move position down), so spot must buy
    if delta > Decimal("0"):
        perp_side = OrderSide.BUY
        spot_side = OrderSide.SELL
    else:
        perp_side = OrderSide.SELL
        spot_side = OrderSide.BUY

    perp_leg = OrderLeg(
        venue=rule.venue,
        instrument=rule.perp_instrument,
        kind=InstrumentKind.PERP,
        side=perp_side,
        quantity=abs_delta,
    )
    spot_leg = OrderLeg(
        venue=rule.venue,
        instrument=rule.spot_instrument,
        kind=InstrumentKind.SPOT,
        side=spot_side,
        quantity=abs_delta,
    )

    return OrderIntent(
        as_of=signal.as_of,
        perp_leg=perp_leg,
        spot_leg=spot_leg,
        cost_model_hash=signal.cost_model_hash,
        sizing_config_hash=sizing_config.content_hash,
        signal_decision=signal.decision.value,
    )
