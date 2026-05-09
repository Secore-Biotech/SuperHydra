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
class ProfileSource:
    """Source attribution for a calibrated cost profile.

    Documents WHERE the numeric values came from and WHEN they were
    valid. Two profiles claiming to model the same venue/tier should
    cite the same source URL; differing values across profiles with
    matching sources indicate a calibration bug.

    Fields:
      source_url: canonical URL where the venue's official fee schedule
        is documented. For Binance: docs URL or fee-schedule page.
      source_as_of: ISO date string (YYYY-MM-DD) when the values were
        captured from source. Profiles SHOULD be re-verified periodically;
        this field tells the next maintainer when verification is due.
      notes: free-text, included in hash. Use this to record edge cases
        (e.g. "BNB discount applied"; "VIP5 maker -0.0001 floor").
    """

    source_url: str
    source_as_of: str  # YYYY-MM-DD
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.source_url or not self.source_url.startswith(("http://", "https://")):
            raise ValueError(
                f"source_url must be an http(s) URL, got {self.source_url!r}"
            )
        # Crude format check: YYYY-MM-DD has 10 chars with dashes at
        # positions 4 and 7.
        if (
            len(self.source_as_of) != 10
            or self.source_as_of[4] != "-"
            or self.source_as_of[7] != "-"
        ):
            raise ValueError(
                f"source_as_of must be YYYY-MM-DD, got {self.source_as_of!r}"
            )


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
    profile_name: str | None = None  # e.g. "binance_vip5_btc_v1"; in hash if set
    source: ProfileSource | None = None  # in hash if set

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
        # New optional fields are included in the hash ONLY when set.
        # This preserves placeholder_v0's hash stability: a config
        # that doesn't set profile_name/source produces the same hash
        # it produced before these fields were added.
        if self.profile_name is not None:
            payload["profile_name"] = self.profile_name
        if self.source is not None:
            payload["source"] = {
                "url": self.source.source_url,
                "as_of": self.source.source_as_of,
                "notes": self.source.notes,
            }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


def placeholder_v0() -> CostModelConfig:
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



# ─── Backward-compatible alias ───────────────────────────────────────────
# `conservative_default_v0` was the original name of the placeholder cost
# model. Day 17a renamed the canonical implementation to `placeholder_v0`
# to make the placeholder vs. calibrated distinction explicit. The old
# name is preserved as an alias so existing imports continue to work.
# New code should use `placeholder_v0()`.
conservative_default_v0 = placeholder_v0


# ─── Calibrated Binance profiles (Day 17a) ───────────────────────────────


def binance_vip0_retail_v1() -> CostModelConfig:
    """Conservative public-user profile: Binance VIP0, no BNB discount.

    Represents the worst realistic Binance retail user. This is the
    baseline against which all other Binance profiles claim improvement.

    Reference values (Binance official fee schedules):
      - USDM-Futures VIP0: maker 2 bps (0.02%), taker 5 bps (0.05%)
      - Spot VIP0:         maker 10 bps (0.1%), taker 10 bps (0.1%)
    A1 trades the perp leg on USDM-Futures and hedges on Spot, so the
    per-leg fees here are the futures schedule (the spot leg is much
    more expensive — see binance_vip5_btc_v1 for a profile that models
    a maker-rebate spot hedge).

    Slippage:
      - btc_eth_top_tier: 1 bp (top-of-book BTC/ETH typical fill cost)

    Borrow:
      - daily_bps: 1 bp/day floor — same conservative non-zero as
        placeholder_v0 pending empirical calibration.
    """
    return CostModelConfig(
        schema_version=COST_MODEL_SCHEMA_VERSION,
        fee_schedules=(
            FeeSchedule(
                venue="binance",
                maker_bps=Decimal("0.0002"),  # 2 bps VIP0 USDM maker
                taker_bps=Decimal("0.0005"),  # 5 bps VIP0 USDM taker
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
            discount_k=Decimal("1.0"),
        ),
        borrow_cost=BorrowCost(
            daily_bps=Decimal("0.0001"),  # 1 bp/day
        ),
        notes="Binance VIP0 retail, no BNB discount; calibrated Day 17a.",
        profile_name="binance_vip0_retail_v1",
        source=ProfileSource(
            source_url="https://www.binance.com/en/fee/futureFee",
            source_as_of="2026-05-09",
            notes="USDM-Futures VIP0 schedule.",
        ),
    )


def binance_vip5_btc_v1() -> CostModelConfig:
    """Realistic mid-VIP retail profile with BNB discount: Binance VIP5,
    BNB-fee-discount enabled. This is the default reference profile for
    A1 BTC/ETH economics.

    Reference values (Binance official fee schedules):
      - USDM-Futures VIP5: maker 1.2 bps (0.012%), taker 3.0 bps (0.03%)
      - 10% BNB discount on eligible USDM-Futures fees per Binance FAQ
        => effective maker 1.08 bps, taker 2.7 bps

    Slippage:
      - btc_eth_top_tier: 1 bp

    Borrow:
      - daily_bps: 1 bp/day floor
    """
    return CostModelConfig(
        schema_version=COST_MODEL_SCHEMA_VERSION,
        fee_schedules=(
            FeeSchedule(
                venue="binance",
                # 1.2 bps * 0.9 (BNB discount) = 1.08 bps
                maker_bps=Decimal("0.000108"),
                # 3.0 bps * 0.9 (BNB discount) = 2.7 bps
                taker_bps=Decimal("0.000270"),
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
            discount_k=Decimal("1.0"),
        ),
        borrow_cost=BorrowCost(
            daily_bps=Decimal("0.0001"),  # 1 bp/day
        ),
        notes=(
            "Binance VIP5 USDM-Futures with 10% BNB discount on fees; "
            "calibrated Day 17a per Binance public fee schedule."
        ),
        profile_name="binance_vip5_btc_v1",
        source=ProfileSource(
            source_url="https://www.binance.com/en/fee/futureFee",
            source_as_of="2026-05-09",
            notes=(
                "USDM-Futures VIP5 schedule, 10% BNB discount applied "
                "per Binance Futures FAQ."
            ),
        ),
    )


def binance_vip9_institutional_v1() -> CostModelConfig:
    """Aggressive institutional profile: Binance VIP9, BNB-fee-discount
    enabled. Few users qualify; this profile represents the best-case
    economics A1 can achieve on Binance.

    Reference values (Binance official fee schedules):
      - USDM-Futures VIP9: maker 0 bps, taker 1.7 bps (0.017%)
        (VIP9 maker is sometimes negative as a rebate; we model 0
        conservatively pending empirical confirmation.)
      - 10% BNB discount on eligible USDM-Futures fees
        => effective maker 0 bps, taker 1.53 bps

    Slippage:
      - btc_eth_top_tier: 1 bp

    Borrow:
      - daily_bps: 1 bp/day floor
    """
    return CostModelConfig(
        schema_version=COST_MODEL_SCHEMA_VERSION,
        fee_schedules=(
            FeeSchedule(
                venue="binance",
                # VIP9 maker 0 bps * 0.9 (BNB discount) = 0 bps
                maker_bps=Decimal("0"),
                # 1.7 bps * 0.9 (BNB discount) = 1.53 bps
                taker_bps=Decimal("0.000153"),
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
            discount_k=Decimal("1.0"),
        ),
        borrow_cost=BorrowCost(
            daily_bps=Decimal("0.0001"),  # 1 bp/day
        ),
        notes=(
            "Binance VIP9 institutional with 10% BNB discount; "
            "VIP9 maker conservatively modeled at 0 (rebate path "
            "pending empirical confirmation); calibrated Day 17a."
        ),
        profile_name="binance_vip9_institutional_v1",
        source=ProfileSource(
            source_url="https://www.binance.com/en/fee/futureFee",
            source_as_of="2026-05-09",
            notes=(
                "USDM-Futures VIP9 schedule, 10% BNB discount applied. "
                "Maker rebate path not yet modeled."
            ),
        ),
    )



def binance_vip5_alt_v1() -> CostModelConfig:
    """Calibrated profile for liquid altcoin perps on Binance USDM at
    VIP5 with BNB discount. Day 18a addition.

    The fee schedule is IDENTICAL to binance_vip5_btc_v1 because Binance
    USDM-Futures does not differentiate fees by instrument class — VIP5
    fees apply to all USDM contracts. The profile is nonetheless a
    distinct CostModelConfig with its own profile_name (and therefore
    its own content_hash) because per-instrument-class economics are
    captured at profile-identity level, not just by numeric values. If
    Binance later charges differently for alts, this profile updates
    independently of binance_vip5_btc_v1.

    The substantive difference is the slippage tier:
      btc_eth_top_tier:   1 bp per leg (BTC/ETH top-of-book)
      liquid_alt_tier:    3 bps per leg (SOL-class liquid alts)

    Threshold under this profile:
      2 * 0.000270 (taker) + 2 * 0.0003 (slip) + 0.0001/3 (borrow)
      = 0.000540 + 0.0006 + 0.0000333
      = 0.001173 (~11.7 bps per interval)

    Compared to:
      Binance SOLUSDT funding cap: ~50 bps per interval (structural)
      historical SOL funding spikes: 20-50+ bps in volatile regimes

    So SOLUSDT under this profile is economically tradeable in strong
    funding regimes — the threshold is well below the cap and below
    realistic positive-funding observations. This is the basis for
    Day 18b (real SOL funding fixture probe) and Day 18c (yes-trade
    integration test).
    """
    return CostModelConfig(
        schema_version=COST_MODEL_SCHEMA_VERSION,
        fee_schedules=(
            FeeSchedule(
                venue="binance",
                # 1.2 bps * 0.9 (BNB discount) = 1.08 bps, same as BTC
                maker_bps=Decimal("0.000108"),
                # 3.0 bps * 0.9 (BNB discount) = 2.7 bps, same as BTC
                taker_bps=Decimal("0.000270"),
            ),
        ),
        slippage_tiers=(
            SlippageTier(
                tier_name="liquid_alt_tier",
                slippage_bps=Decimal("0.0003"),  # 3 bps per leg
            ),
        ),
        funding_uncertainty=FundingUncertainty(
            lookback_days=30,
            discount_k=Decimal("1.0"),
        ),
        borrow_cost=BorrowCost(
            daily_bps=Decimal("0.0001"),  # 1 bp/day floor
        ),
        notes=(
            "Binance VIP5 USDM-Futures with 10% BNB discount, alt "
            "slippage tier (3 bps per leg). Day 18a addition for "
            "liquid altcoin perps (SOLUSDT initial calibration target)."
        ),
        profile_name="binance_vip5_alt_v1",
        source=ProfileSource(
            source_url="https://www.binance.com/en/fee/futureFee",
            source_as_of="2026-05-09",
            notes=(
                "USDM-Futures VIP5 schedule, 10% BNB discount applied. "
                "Slippage tier estimated from typical SOLUSDT top-of-"
                "book spread + small-size adverse fill cost; pending "
                "empirical calibration from live fills."
            ),
        ),
    )



def binance_vip5_alt_research_v1() -> CostModelConfig:
    """RESEARCH-CALIBRATED PROFILE — NOT FOR GOVERNANCE USE.

    Day 19a addition. Lowers the alt slippage assumption from 3 bps per
    leg (binance_vip5_alt_v1) to 1 bp per leg, based on published
    market-microstructure observations of liquid altcoin perp spreads
    on Binance. This profile is intentionally NOT returned by
    select_profile_for_a1; using it requires calling it directly,
    which forces an explicit decision rather than silent promotion.

    Evidence basis (see docs/research/sol_slippage_calibration_memo.md
    for full memo):
      - Kaiko cheatsheet for bid-ask spreads (Q1 2024): SOL-USDT pair
        on Binance had widest IQR and most outliers among major pairs,
        though Binance was tightest among venues for SOL.
      - Amberdata Digital Asset Snapshot (January 2026): SOL average
        spread 1.01 bps across venues, Binance SOLUSDT tightest at
        0.79 bps. BTC: 0.09 bps; ETH: 0.10 bps. SOL is ~10x BTC/ETH.

    Per-leg slippage at 1 bp models:
      - Half-spread (~0.4 bps for taker) +
      - Modest impact for small-clip ($1.5k-$3k) sizes +
      - Adverse-selection cushion

    Threshold:
      2 * 0.000270 (taker) + 2 * 0.0001 (slip) + 0.0001/3 (borrow)
      = 0.000540 + 0.0002 + 0.0000333
      = 0.000773 (~7.7 bps per interval)

    This threshold matches binance_vip5_btc_v1 exactly (same fees,
    same per-leg slippage). The economic claim is "SOL liquidity at
    A1 clip size is comparable to BTC liquidity at A1 clip size" —
    a defensible claim from spreads data but NOT yet validated by
    real fills on the venue.

    Why "research" not "empirical":
      - The 1 bp number comes from third-party aggregated spread data,
        not A1's own fill records.
      - Spread alone does not equal effective adverse fill cost;
        impact and adverse selection from informed flow matter too.
      - The clip size ($1.5k-$3k for a 0.01-BTC-equivalent SOL hedge)
        is small enough that impact is plausibly negligible, but
        unverified at the venue level.
      - Spread observations vary by regime; Q1 2024 / Jan 2026 data
        may not generalize to volatile periods (March 2024 memecoin
        frenzy, etc.).

    What promotes this to binance_vip5_alt_empirical_v1 in a future
    Day:
      - Tape-based effective-spread estimation across volatile and
        quiet regimes
      - Live A1 paper fills on the venue
      - Both consistent with ~1 bp per leg before promoting

    Until then: this profile may be used for research backtests and
    sensitivity analysis, but its threshold should NOT serve as the
    A1-P0-to-P1 gate evidence.
    """
    return CostModelConfig(
        schema_version=COST_MODEL_SCHEMA_VERSION,
        fee_schedules=(
            FeeSchedule(
                venue="binance",
                # Same VIP5 USDM-Futures fees with 10% BNB discount
                # as binance_vip5_btc_v1 / binance_vip5_alt_v1.
                maker_bps=Decimal("0.000108"),
                taker_bps=Decimal("0.000270"),
            ),
        ),
        slippage_tiers=(
            SlippageTier(
                tier_name="liquid_alt_research_tier",
                slippage_bps=Decimal("0.0001"),  # 1 bp per leg
            ),
        ),
        funding_uncertainty=FundingUncertainty(
            lookback_days=30,
            discount_k=Decimal("1.0"),
        ),
        borrow_cost=BorrowCost(
            daily_bps=Decimal("0.0001"),  # 1 bp/day floor
        ),
        notes=(
            "RESEARCH-ONLY profile. Slippage 1 bp/leg from third-party "
            "spread data (Kaiko + Amberdata). NOT for governance use; "
            "promotion to binance_vip5_alt_empirical_v1 requires tape "
            "or live-fill validation. See docs/research/"
            "sol_slippage_calibration_memo.md."
        ),
        profile_name="binance_vip5_alt_research_v1",
        source=ProfileSource(
            source_url="https://research.kaiko.com/insights/a-cheatsheet-for-bid-ask-spreads",
            source_as_of="2026-05-09",
            notes=(
                "Slippage tier 1 bp/leg derived from Kaiko Q1 2024 "
                "spread cheatsheet (SOL-USDT on Binance) and Amberdata "
                "Jan 2026 snapshot (Binance SOLUSDT tightest at 0.79 "
                "bps; SOL ~10x BTC/ETH). Research-calibrated; awaiting "
                "tape and live-fill validation. Fees identical to "
                "binance_vip5_alt_v1 (Binance does not differentiate "
                "USDM-Futures fees by instrument class)."
            ),
        ),
    )
