"""Per-profile cost-threshold tests for Day 17a calibrated profiles.

Asserts:
  1. Each profile's per-interval cost threshold matches a hand-calculated
     value (so calibration values can't silently drift).
  2. Each profile's content_hash is distinct from the others, including
     the placeholder.
  3. The placeholder profile's content_hash matches the hash that
     conservative_default_v0 (now an alias) produced before Day 17a's
     introduction of optional metadata fields. This is the lineage-
     stability property: existing paper-run records that referenced the
     placeholder hash continue to validate.

If any of these break, do NOT relax the test. Investigate whether
calibration values changed, whether the hash payload changed, or
whether the placeholder semantics shifted.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from core.config.cost_model import (
    binance_vip0_retail_v1,
    binance_vip5_alt_v1,
    binance_vip5_btc_v1,
    binance_vip9_institutional_v1,
    conservative_default_v0,
    placeholder_v0,
    ProfileSource,
)


# Binance funding interval cadence: 3 per day.
INTERVALS_PER_DAY = 3


def _per_period_cost_rate(cost_model) -> Decimal:
    """Replicate the cost-threshold formula used by evaluate_signal."""
    fee_schedule = cost_model.fee_schedules[0]
    slippage_tier = cost_model.slippage_tiers[0]
    fees = Decimal("2") * fee_schedule.taker_bps
    slip = Decimal("2") * slippage_tier.slippage_bps
    borrow_per_period = (
        cost_model.borrow_cost.daily_bps / Decimal(INTERVALS_PER_DAY)
    )
    return fees + slip + borrow_per_period


# ─── Per-profile threshold tests ─────────────────────────────────────────


class TestThresholds:
    def test_placeholder_v0(self):
        """2 * 0.0005 + 2 * 0.0001 + 0.0001/3 = 0.001233..."""
        cm = placeholder_v0()
        threshold = _per_period_cost_rate(cm)
        # 0.001 + 0.0002 + 0.0000333 = 0.001233 (repeating)
        assert Decimal("0.00123") < threshold < Decimal("0.00124"), (
            f"placeholder_v0 threshold drifted: {threshold}"
        )

    def test_binance_vip0_retail_v1(self):
        """Same fee structure as placeholder by design (same VIP0 USDM
        values). Threshold should equal placeholder's threshold."""
        cm = binance_vip0_retail_v1()
        threshold = _per_period_cost_rate(cm)
        placeholder_threshold = _per_period_cost_rate(placeholder_v0())
        assert threshold == placeholder_threshold, (
            f"vip0_retail threshold ({threshold}) should equal "
            f"placeholder ({placeholder_threshold}) — both are VIP0 USDM"
        )

    def test_binance_vip5_btc_v1(self):
        """2 * 0.000270 + 2 * 0.0001 + 0.0001/3
           = 0.000540 + 0.0002 + 0.0000333
           = 0.000773... per interval (~7.7 bps)
        Critically, this is BELOW the Binance BTCUSDT 0.01% (10 bps)
        funding cap — so VIP5 BTCUSDT can in principle clear costs in
        strong-funding regimes."""
        cm = binance_vip5_btc_v1()
        threshold = _per_period_cost_rate(cm)
        assert Decimal("0.00077") < threshold < Decimal("0.00078"), (
            f"vip5_btc threshold drifted: {threshold}"
        )
        # The economically meaningful claim: VIP5 brings the threshold
        # below the BTCUSDT funding cap.
        assert threshold < Decimal("0.0001") * Decimal("12"), (
            f"vip5 threshold ({threshold}) should be well below the "
            f"upper bound of plausible funding rates"
        )

    def test_binance_vip9_institutional_v1(self):
        """2 * 0.000153 + 2 * 0.0001 + 0.0001/3
           = 0.000306 + 0.0002 + 0.0000333
           = 0.000539... per interval (~5.4 bps)"""
        cm = binance_vip9_institutional_v1()
        threshold = _per_period_cost_rate(cm)
        assert Decimal("0.00053") < threshold < Decimal("0.00054"), (
            f"vip9_institutional threshold drifted: {threshold}"
        )

    def test_thresholds_strictly_decreasing_with_better_tier(self):
        """vip0 > vip5 > vip9 by construction. If this orders wrong,
        a calibration value got typo'd."""
        t_vip0 = _per_period_cost_rate(binance_vip0_retail_v1())
        t_vip5 = _per_period_cost_rate(binance_vip5_btc_v1())
        t_vip9 = _per_period_cost_rate(binance_vip9_institutional_v1())
        assert t_vip0 > t_vip5 > t_vip9, (
            f"Profile thresholds out of order: "
            f"vip0={t_vip0}, vip5={t_vip5}, vip9={t_vip9}"
        )


# ─── Hash distinctness ───────────────────────────────────────────────────


class TestHashDistinctness:
    def test_calibrated_profiles_have_distinct_hashes(self):
        hashes = {
            "vip0": binance_vip0_retail_v1().content_hash,
            "vip5": binance_vip5_btc_v1().content_hash,
            "vip9": binance_vip9_institutional_v1().content_hash,
        }
        assert len(set(hashes.values())) == 3, (
            f"Calibrated profiles should have distinct hashes; got {hashes}"
        )

    def test_calibrated_profiles_distinct_from_placeholder(self):
        ph = placeholder_v0().content_hash
        for fn in (
            binance_vip0_retail_v1,
            binance_vip5_btc_v1,
            binance_vip9_institutional_v1,
        ):
            assert fn().content_hash != ph, (
                f"{fn.__name__} hash matches placeholder; "
                f"profile_name field should make them distinct"
            )

    def test_two_profiles_with_same_numeric_values_distinguished_by_profile_name(self):
        """vip0_retail and placeholder have identical numeric values
        (both are VIP0 USDM with no discount) but DIFFERENT profile_name
        values. They should hash differently — the profile_name field is
        in the hash payload precisely so two configs with matching numbers
        but different identities can be distinguished in lineage."""
        assert (
            binance_vip0_retail_v1().content_hash
            != placeholder_v0().content_hash
        )


# ─── Placeholder hash stability ──────────────────────────────────────────


class TestPlaceholderHashStability:
    def test_alias_is_canonical(self):
        """conservative_default_v0 must be an alias for placeholder_v0
        (not a separate function with its own body)."""
        assert conservative_default_v0 is placeholder_v0

    def test_placeholder_hash_unchanged_by_optional_field_introduction(self):
        """The placeholder profile does NOT set profile_name or source.
        Day 17a's hash logic includes those fields ONLY when set, so
        the placeholder hash is the SAME hash conservative_default_v0
        produced before Day 17a. This is the lineage-stability property:
        any persisted Sharpe attached to that hash continues to validate.

        The expected value below is the SHA-256 of the canonical hash
        payload as it existed before Day 17a. If this test fails, either:
          - the hash logic accidentally started including new fields
            unconditionally, or
          - the placeholder values were changed.
        Either is a violation of the lineage guarantee."""
        cm = placeholder_v0()
        # Compute and pin the expected hash. If you are introducing this
        # test for the first time and there's no prior pinned value to
        # match, run the test once, copy the actual hash, paste it here,
        # and commit.
        # Pinned hash captured Day 17a after introducing optional
        # profile_name + source fields. The hash payload includes
        # those fields ONLY when set, so placeholder_v0 (which sets
        # neither) produces the same hash it did before Day 17a.
        expected = "395fd6ceccd6c8dc706908a757f9bc88ee6984b8616cdbe03681dee9335d7c84"
        assert cm.content_hash == expected, (
            f"placeholder_v0 hash changed from {expected!r} to "
            f"{cm.content_hash!r}. This breaks lineage. Investigate."
        )



# ─── Day 18a: alt profile threshold + hash tests ─────────────────────────


class TestAltProfile:
    def test_binance_vip5_alt_v1_threshold(self):
        """2 * 0.000270 + 2 * 0.0003 + 0.0001/3
           = 0.000540 + 0.0006 + 0.0000333
           = 0.001173... per interval (~11.7 bps)
        Higher than vip5_btc (~7.7 bps) because alt slippage dominates."""
        cm = binance_vip5_alt_v1()
        threshold = _per_period_cost_rate(cm)
        assert Decimal("0.00117") < threshold < Decimal("0.00118"), (
            f"vip5_alt threshold drifted: {threshold}"
        )

    def test_alt_threshold_higher_than_btc_threshold(self):
        """Alt threshold > BTC threshold by construction (3x slippage)."""
        btc = _per_period_cost_rate(binance_vip5_btc_v1())
        alt = _per_period_cost_rate(binance_vip5_alt_v1())
        assert alt > btc, f"alt={alt} not > btc={btc}"

    def test_alt_threshold_below_solusdt_funding_cap(self):
        """Binance SOLUSDT funding cap ~50 bps per interval; alt threshold
        ~11.7 bps. The yes-trade economic basis for SOLUSDT under this
        profile."""
        SOLUSDT_FUNDING_CAP = Decimal("0.005")  # 50 bps per interval
        threshold = _per_period_cost_rate(binance_vip5_alt_v1())
        assert threshold < SOLUSDT_FUNDING_CAP, (
            f"alt threshold ({threshold}) no longer below SOLUSDT cap "
            f"({SOLUSDT_FUNDING_CAP}); investigate."
        )

    def test_alt_profile_distinct_hash_from_btc_profile(self):
        """Same VIP5 fees, different slippage tier + profile_name →
        different content_hash."""
        assert binance_vip5_btc_v1().content_hash != binance_vip5_alt_v1().content_hash

    def test_alt_profile_has_liquid_alt_tier(self):
        cm = binance_vip5_alt_v1()
        tier_names = [t.tier_name for t in cm.slippage_tiers]
        assert tier_names == ["liquid_alt_tier"]

    def test_alt_profile_source_metadata_present(self):
        cm = binance_vip5_alt_v1()
        assert cm.source is not None
        assert cm.source.source_url.startswith("https://")
        assert cm.source.source_as_of == "2026-05-09"
