"""Cost model configuration.

Per the SuperHydra roadmap (§3.1.1, A1 first-30-day deliverables), the cost
model covers four components: maker/taker fees, slippage, funding-rate
uncertainty, and borrow cost. The model must be reproducible: the same
config produces the same paper Sharpe.

Reproducibility is enforced by versioning + content hashing. Every paper
run records the cost model's content hash; reconciliation tooling can then
prove that the same paper run produces the same numbers.

Defaults are deliberately conservative. The roadmap explicitly forbids
importing legacy strategy assumptions blindly. Values here are placeholders
to be tightened with empirical evidence.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from decimal import Decimal
from typing import Final


COST_MODEL_SCHEMA_VERSION: Final[str] = "cost_model.v0"


@dataclass(frozen=True)
class FeeSchedule:
    """Maker/taker fee schedule for one venue.

    Rates are expressed as decimal fractions of notional. A 5 bps taker fee
    is Decimal('0.0005'). Maker can be negative (rebate).
    """

    venue: str
    maker_bps: Decimal  # e.g. Decimal('0.0002') = 2 bps
    taker_bps: Decimal  # e.g. Decimal('0.0005') = 5 bps

    def __post_init__(self) -> None:
        if not self.venue or not self.venue.islower():
            raise ValueError(f"venue must be lowercase non-empty, got {self.venue!r}")
        if not isinstance(self.maker_bps, Decimal):
            raise TypeError("maker_bps must be Decimal")
        if not isinstance(self.taker_bps, Decimal):
            raise TypeError("taker_bps must be Decimal")


@dataclass(frozen=True)
class SlippageTier:
    """Slippage assumption for one liquidity tier.

    Conservative model: fixed bps adverse to the trade direction. Real
    slippage is fill-size-dependent; the v0 cost model accepts a flat tier
    bps until enough live evidence exists to fit a size-dependent curve.
    """

    tier_name: str  # e.g. "btc_eth_top_tier"
    slippage_bps: Decimal


@dataclass(frozen=True)
class FundingUncertainty:
    """Forward-funding-rate uncertainty.

    Used to discount expected funding capture: the strategy never sizes
    against the point estimate alone; it sizes against (expected - k*sigma)
    so that adverse funding moves don't surprise the carry.

    Initial implementation uses rolling-30d stdev of funding rates. The
    config carries the lookback length and the discount multiple k.
    """

    lookback_days: int  # e.g. 30
    discount_k: Decimal  # e.g. Decimal('1.0') = subtract 1 sigma

    def __post_init__(self) -> None:
        if self.lookback_days <= 0:
            raise ValueError(f"lookback_days must be positive, got {self.lookback_days}")
        if not isinstance(self.discount_k, Decimal):
            raise TypeError("discount_k must be Decimal")


@dataclass(frozen=True)
class BorrowCost:
    """Borrow / financing cost on the spot leg of a carry pair.

    For BTC/ETH at scale on top venues, borrow approximates funding rate
    in steady state but diverges in stressed regimes. Conservative default
    is a non-zero floor expressed as bps/day, applied to the short-spot leg.
    """

    daily_bps: Decimal  # bps/day, applied to notional


@dataclass(frozen=True)
class CostModelConfig:
    """Full cost model — one snapshot, hashable.

    Content hash is the durable handle. Every paper run records the hash
    in its ledger metadata so reconciliation can prove that two runs used
    the same model.
    """

    schema_version: str
    fee_schedules: tuple[FeeSchedule, ...]
    slippage_tiers: tuple[SlippageTier, ...]
    funding_uncertainty: FundingUncertainty
    borrow_cost: BorrowCost
    notes: str = ""  # free-text, included in hash so changing notes changes hash

    def __post_init__(self) -> None:
        if self.schema_version != COST_MODEL_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {COST_MODEL_SCHEMA_VERSION!r}, "
                f"got {self.schema_version!r}"
            )
        if not self.fee_schedules:
            raise ValueError("at least one FeeSchedule required")
        if not self.slippage_tiers:
            raise ValueError("at least one SlippageTier required")
        # Detect duplicate venue entries — a single config must not have
        # two fee schedules for the same venue.
        venues = [fs.venue for fs in self.fee_schedules]
        if len(set(venues)) != len(venues):
            raise ValueError(f"duplicate venues in fee_schedules: {venues}")
        tiers = [t.tier_name for t in self.slippage_tiers]
        if len(set(tiers)) != len(tiers):
            raise ValueError(f"duplicate tier_names in slippage_tiers: {tiers}")

    @property
    def content_hash(self) -> str:
        """Stable SHA-256 over the full cost model.

        Used by paper-run lineage and reconciliation. Two cost models
        with different hashes are treated as distinct configurations
        regardless of how similar their values are.
        """
        payload = {
            "schema_version": self.schema_version,
            "fee_schedules": [
                {"venue": fs.venue, "maker": str(fs.maker_bps), "taker": str(fs.taker_bps)}
                for fs in sorted(self.fee_schedules, key=lambda fs: fs.venue)
            ],
            "slippage_tiers": [
                {"tier": t.tier_name, "bps": str(t.slippage_bps)}
                for t in sorted(self.slippage_tiers, key=lambda t: t.tier_name)
            ],
            "funding_uncertainty": {
                "lookback_days": self.funding_uncertainty.lookback_days,
                "discount_k": str(self.funding_uncertainty.discount_k),
            },
            "borrow_cost": {
                "daily_bps": str(self.borrow_cost.daily_bps),
            },
            "notes": self.notes,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


def conservative_default_v0() -> CostModelConfig:
    """Conservative seed config per roadmap §3.1.1.

    These values are explicitly placeholders. They exist so the system can
    boot with a hashable cost model, not because they're calibrated.
    Calibration is empirical and will replace these values in a later
    config version, at which point the content hash changes and any paper
    Sharpe attached to the old hash is preserved as historical lineage.
    """
    return CostModelConfig(
        schema_version=COST_MODEL_SCHEMA_VERSION,
        fee_schedules=(
            # Binance USDT-margined perps (placeholder; real values depend
            # on tier and BNB-discount status). Conservative: assume taker.
            FeeSchedule(
                venue="binance",
                maker_bps=Decimal("0.0002"),  # 2 bps
                taker_bps=Decimal("0.0005"),  # 5 bps
            ),
        ),
        slippage_tiers=(
            SlippageTier(
                tier_name="btc_eth_top_tier",
                slippage_bps=Decimal("0.0001"),  # 1 bp
            ),
        ),
        funding_uncertainty=FundingUncertainty(
            lookback_days=30,
            discount_k=Decimal("1.0"),  # subtract one rolling-30d sigma
        ),
        borrow_cost=BorrowCost(
            daily_bps=Decimal("0.0001"),  # 1 bp/day floor; conservative non-zero
        ),
        notes=(
            "v0 conservative defaults per roadmap §3.1.1. "
            "Placeholders pending empirical calibration. "
            "Do not interpret these values as production assumptions."
        ),
    )
