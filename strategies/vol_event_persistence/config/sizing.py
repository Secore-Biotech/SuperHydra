"""Sizing configuration for vol_event_persistence.

A minimal per-instrument fixed-quantity model. Each event entry trades a
fixed base-asset quantity for the instrument. The probe's pass/fail is
measured in basis points (spec §6), which is quantity-independent, so the
absolute quantity is a simulation nominal rather than a spec-locked value;
it lives here, not in config.pre_lock.

The config carries a deterministic content hash so an emitted intent can
be traced to the exact sizing values in force when it was generated.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

SIZING_CONFIG_SCHEMA_VERSION: Final[str] = "sizing_config.v0"


class SizingConfigError(Exception):
    """Raised when a sizing rule is missing or structurally invalid."""


@dataclass(frozen=True)
class PerpSizingRule:
    """Fixed per-event quantity for one (venue, instrument).

    Fields:
        venue: lowercase venue code
        instrument: vendor-canonical perp code
        quantity_per_event: base-asset quantity per event entry (positive)
    """

    venue: str
    instrument: str
    quantity_per_event: Decimal

    def __post_init__(self) -> None:
        if not self.venue or not self.venue.islower():
            raise SizingConfigError(
                f"venue must be lowercase non-empty, got {self.venue!r}"
            )
        if not self.instrument:
            raise SizingConfigError("instrument must be non-empty")
        if not isinstance(self.quantity_per_event, Decimal):
            raise SizingConfigError("quantity_per_event must be Decimal")
        if self.quantity_per_event <= Decimal("0"):
            raise SizingConfigError(
                f"quantity_per_event must be positive, got {self.quantity_per_event}"
            )


@dataclass(frozen=True)
class SizingConfig:
    """A set of per-instrument sizing rules.

    Fields:
        rules: tuple of PerpSizingRule, one per instrument. No two rules
            may share an instrument.
    """

    rules: tuple[PerpSizingRule, ...]

    def __post_init__(self) -> None:
        if not self.rules:
            raise SizingConfigError("SizingConfig must contain at least one rule")
        instruments = [r.instrument for r in self.rules]
        if len(set(instruments)) != len(instruments):
            raise SizingConfigError(
                f"duplicate instruments in sizing rules: {sorted(instruments)}"
            )

    def rule_for(self, instrument: str) -> PerpSizingRule:
        """Return the sizing rule for an instrument, or raise."""
        for r in self.rules:
            if r.instrument == instrument:
                return r
        available = sorted(r.instrument for r in self.rules)
        raise SizingConfigError(
            f"no sizing rule for instrument {instrument!r}; available: {available}"
        )

    def content_hash(self) -> str:
        """Deterministic content hash for lineage.

        Order-independent: rules are sorted by (venue, instrument) before
        hashing, so two configs with the same rules in different order
        produce the same hash.
        """
        canonical = "\n".join(
            f"{r.venue}:{r.instrument}:{r.quantity_per_event}"
            for r in sorted(self.rules, key=lambda r: (r.venue, r.instrument))
        )
        payload = f"{SIZING_CONFIG_SCHEMA_VERSION}\n{canonical}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
