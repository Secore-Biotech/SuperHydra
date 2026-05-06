"""Sizing configuration for engine A1.

A1 is allowed to trade a small set of instruments at fixed per-instrument
caps. This config holds those bounds plus the metadata needed to produce
spot-and-perp leg pairs.

The roadmap (§3.1.1) explicitly requires fixed per-instrument caps for the
P0 build. No optimisation, no Kelly, no covariance — a flat cap per
instrument plus a flat overall notional cap. Anything more sophisticated
is a P2+ overlay.

The config is content-hashed (same shape as CostModelConfig) so a paper
run's lineage records the exact sizing bounds in force at decision time.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final


SIZING_CONFIG_SCHEMA_VERSION: Final[str] = "sizing_config.v0"


# ─── Errors ───────────────────────────────────────────────────────────────


class SizingConfigError(Exception):
    pass


# ─── Per-instrument metadata ─────────────────────────────────────────────


@dataclass(frozen=True)
class InstrumentSizingRule:
    """The size bounds and metadata for one perp-spot pair.

    Fields:
        venue: lowercase venue code (matches CostModelConfig.fee_schedules)
        perp_instrument: vendor canonical perp code (e.g. "BTCUSDT" perp)
        spot_instrument: vendor canonical spot code (e.g. "BTCUSDT" spot
            on the same venue, or a different venue's spot if cross-venue
            sizing is later allowed; for P0 we keep it same-venue)
        max_quantity: absolute cap on signed position quantity for the
            perp leg, in base-asset units. The spot leg mirrors at
            equal nominal.
        slippage_tier_name: which SlippageTier from the cost model applies
            (e.g. "btc_eth_top_tier"). Used by the evaluator; the sizer
            doesn't recompute costs but carries the tag for lineage.
        min_quantity: minimum nominal trade size. Smaller intents are
            suppressed (zero-quantity orders are noise; small odd lots
            distort the cost model). In base-asset units.
    """

    venue: str
    perp_instrument: str
    spot_instrument: str
    max_quantity: Decimal
    slippage_tier_name: str
    min_quantity: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if not self.venue or not self.venue.islower():
            raise SizingConfigError(
                f"venue must be lowercase non-empty, got {self.venue!r}"
            )
        if not self.perp_instrument:
            raise SizingConfigError("perp_instrument must be non-empty")
        if not self.spot_instrument:
            raise SizingConfigError("spot_instrument must be non-empty")
        if not isinstance(self.max_quantity, Decimal):
            raise TypeError("max_quantity must be Decimal")
        if self.max_quantity <= Decimal("0"):
            raise SizingConfigError(
                f"max_quantity must be positive, got {self.max_quantity}"
            )
        if not isinstance(self.min_quantity, Decimal):
            raise TypeError("min_quantity must be Decimal")
        if self.min_quantity < Decimal("0"):
            raise SizingConfigError(
                f"min_quantity must be >= 0, got {self.min_quantity}"
            )
        if self.min_quantity >= self.max_quantity:
            raise SizingConfigError(
                f"min_quantity ({self.min_quantity}) must be strictly less "
                f"than max_quantity ({self.max_quantity})"
            )
        if not self.slippage_tier_name:
            raise SizingConfigError("slippage_tier_name must be non-empty")


# ─── Top-level config ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class SizingConfig:
    """Sizing bounds for the A1 engine.

    Fields:
        schema_version: tag for lineage / migration
        rules: per-instrument sizing rules. Indexed by perp_instrument.
        max_total_notional_usd: aggregate cap across all positions, in
            USD. The sizer enforces this as a hard ceiling — if proposed
            new positions would exceed it, sizes are scaled down or the
            new intent is suppressed (depending on whether the existing
            book is already at cap).
        notes: free-text, included in content hash
    """

    schema_version: str
    rules: tuple[InstrumentSizingRule, ...]
    max_total_notional_usd: Decimal
    notes: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != SIZING_CONFIG_SCHEMA_VERSION:
            raise SizingConfigError(
                f"schema_version must be {SIZING_CONFIG_SCHEMA_VERSION!r}, "
                f"got {self.schema_version!r}"
            )
        if not self.rules:
            raise SizingConfigError("at least one InstrumentSizingRule required")
        if not isinstance(self.max_total_notional_usd, Decimal):
            raise TypeError("max_total_notional_usd must be Decimal")
        if self.max_total_notional_usd <= Decimal("0"):
            raise SizingConfigError(
                f"max_total_notional_usd must be positive, got {self.max_total_notional_usd}"
            )
        # Detect duplicate perp_instrument or spot_instrument across rules.
        perps = [r.perp_instrument for r in self.rules]
        spots = [r.spot_instrument for r in self.rules]
        if len(set(perps)) != len(perps):
            raise SizingConfigError(f"duplicate perp_instrument across rules: {perps}")
        if len(set(spots)) != len(spots):
            raise SizingConfigError(f"duplicate spot_instrument across rules: {spots}")

    def rule_for_perp(self, perp_instrument: str) -> InstrumentSizingRule:
        for r in self.rules:
            if r.perp_instrument == perp_instrument:
                return r
        raise SizingConfigError(
            f"no sizing rule for perp instrument {perp_instrument!r}; "
            f"known: {sorted(r.perp_instrument for r in self.rules)}"
        )

    @property
    def content_hash(self) -> str:
        """Stable SHA-256 digest of the canonical content. Rule order
        does not affect the hash (rules are sorted internally)."""
        payload = {
            "schema_version": self.schema_version,
            "max_total_notional_usd": str(self.max_total_notional_usd),
            "notes": self.notes,
            "rules": [
                {
                    "venue": r.venue,
                    "perp": r.perp_instrument,
                    "spot": r.spot_instrument,
                    "max_qty": str(r.max_quantity),
                    "min_qty": str(r.min_quantity),
                    "tier": r.slippage_tier_name,
                }
                for r in sorted(self.rules, key=lambda r: r.perp_instrument)
            ],
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


def conservative_default_v0() -> SizingConfig:
    """Conservative seed: BTCUSDT and ETHUSDT on Binance, tiny caps.

    These are placeholders. Real bounds get tuned with empirical evidence
    once the engine has live data. Hash changes when bounds change, so
    historical paper Sharpe stays attributable to the exact bounds in
    force at the time.
    """
    return SizingConfig(
        schema_version=SIZING_CONFIG_SCHEMA_VERSION,
        rules=(
            InstrumentSizingRule(
                venue="binance",
                perp_instrument="BTCUSDT",
                spot_instrument="BTCUSDT",
                max_quantity=Decimal("0.01"),  # 0.01 BTC ≈ $1k at $100k
                min_quantity=Decimal("0.001"),
                slippage_tier_name="btc_eth_top_tier",
            ),
            InstrumentSizingRule(
                venue="binance",
                perp_instrument="ETHUSDT",
                spot_instrument="ETHUSDT",
                max_quantity=Decimal("0.1"),   # 0.1 ETH
                min_quantity=Decimal("0.01"),
                slippage_tier_name="btc_eth_top_tier",
            ),
        ),
        max_total_notional_usd=Decimal("2000"),  # $2k aggregate ceiling
        notes=(
            "v0 conservative defaults per roadmap §3.1.1. "
            "Tiny caps appropriate for paper-stage P0; tightened or "
            "loosened only with empirical evidence from canary."
        ),
    )
