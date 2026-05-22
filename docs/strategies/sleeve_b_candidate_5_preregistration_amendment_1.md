# Sleeve B Candidate #5 — Pre-registration Amendment #1

**Subject:** Clarification of persistence window `N` semantics under non-uniform Binance funding intervals
**Amends:** `fe34b76` (candidate #5 pre-registration)
**Date:** 2026-05-22
**Status:** Pre-evidence interpretive clarification. No D-level engineering has commenced. No evaluation data has been generated.
**Authority:** Operator decision following research into Binance funding interval rules. Pre-registration §1.1 and §1.2 implicitly assumed uniform 8h funding across the top-30 universe; this assumption is incorrect.

---

## 1. The ambiguity

Pre-registration `fe34b76` §1.1 and §1.2 reference "N periods" without specifying what "period" means when an asset's funding interval differs from the canonical 8h.

Binance documentation (verified 2026-05-22) establishes:

- Default funding cadence is 8h (settlements at 00:00, 08:00, 16:00 UTC)
- Selected USDⓈ-M perpetual contracts have been on 4h funding since 2023-10-12 (settlements at 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC), applied automatically when maximum leverage is ≤ 25x
- High-volatility or newly-listed contracts may be on 1h, 2h, 4h, or 8h funding per Binance's algorithmic configuration
- As recently as January 2026, transition rules between 1h and 4h cadences operate based on funding magnitude thresholds
- The endpoint `GET /fapi/v1/fundingInfo` provides per-contract funding interval metadata

The OOS evaluation window (2023-04-15 to 2026-04-15) spans the 2023-10-12 cadence transition. A non-trivial fraction of the top-30 universe is on 4h funding for portions of the OOS window. Some assets may have been on 1h funding during high-volatility episodes.

Pre-registration §1.2(a) requires `|f(i, τ)| > funding_threshold for ≥ p_f of recent N periods τ`. As written, "N periods" is ambiguous when periods are not uniformly 8h apart.

## 2. The clarification

`N` in pre-registration §1 and §2 is hereby clarified to mean **real-time duration**, not native event count. Specifically:

- **Baseline config:** N = 7 calendar days (replacing the parenthetical "N = 21 (7d)" reading where 21 referred to 8h periods)
- **V1 short persistence:** N = 4 calendar days (replacing "N = 12 (4d)")
- **V2 loose thresholds:** N = 7 calendar days
- **V3 tight thresholds:** N = 7 calendar days

For an asset on 8h native funding, a 7-day window contains approximately 21 funding events. For an asset on 4h native funding, 7 days contains approximately 42 events. For an asset on 1h native funding, 7 days contains approximately 168 events.

The fraction parameters `p_f` and `p_b` apply to the fraction of **native funding events within the real-time window**, not to a fixed event count. For an asset on 8h funding with N = 7 days and `p_f = 0.66`, the threshold condition requires `|f| > funding_threshold` on at least ⌈21 × 0.66⌉ = 14 of the 21 events in the window. For an asset on 4h funding, the same `p_f = 0.66` requires at least ⌈42 × 0.66⌉ = 28 of the 42 events.

No aggregation of native funding events into synthetic 8h buckets is performed. The signal evaluates the asset's funding history at its native cadence.

## 3. Why this clarification is pre-evidence, not result-shaping

Anti-cherry-pick discipline (binding per `fe34b76` header and §7) prohibits threshold adjustment, parameter substitution, and retroactive interpretation after evidence is seen. This amendment is committed before any D-level engineering work has begun. No signal values have been computed. No filter performance has been evaluated. No B3, F1, or F3 sub-gate outputs exist.

The amendment resolves a structural ambiguity in the pre-registration's specification, not a parameter calibration. Under either of the alternative readings of `N` (Option 1: native event count; Option 3: 8h-only universe restriction), the candidate's economic claim — that *persistent* joint distortion of funding/OI/basis under stress is informative about regime state — would be tested. The clarification chooses the reading that best preserves the candidate's economic claim across assets with heterogeneous funding cadences.

Specifically:

- **Option 1 (native event count)** would assign a 4h asset a 3.5-day persistence window while assigning an 8h asset a 7-day persistence window for the same `N`. This produces inconsistent regime detection semantics across the universe and weakens the signal's economic interpretation.
- **Option 3 (8h-only universe)** would discard asset coverage based on data structure rather than economic relevance, materially reducing the universe size on which the regime filter operates.
- **Option 2 (the chosen reading)**: real-time duration, native event count fractions. Consistent semantics across assets; no universe loss; honors the original economic intent.

## 4. Engineering implications

The signal module (`strategies/sleeve_b/stabilizer_regime/signal.py` at D1) must:

1. Query per-asset funding interval metadata from the Binance API (`GET /fapi/v1/fundingInfo`) or infer interval from funding event timestamp deltas.
2. Compute `p_f` and `p_b` against the actual count of native funding events within the real-time window N.
3. Handle interval transitions within the OOS window. If an asset transitions from 8h to 4h funding mid-history (e.g., at 2023-10-12), the persistence window crossing the transition uses the events as published at their actual cadences.

The shared funding fetcher at `data/ingestion/vendors/binance/funding_fetcher.py` (per pre-reg §6 D1 deliverable) must:

1. Return funding records as published, with actual settlement timestamps preserved.
2. Surface per-asset interval metadata as a separate output field.
3. Not normalize, interpolate, or aggregate funding events.

The signal-module unit tests must cover:

- Asset on uniform 8h funding throughout OOS window.
- Asset on uniform 4h funding throughout OOS window.
- Asset transitioning from 8h to 4h mid-window.
- Asset transitioning from 4h to 1h mid-window.
- Asset transitioning from 1h back to 4h mid-window (per Jan 2026 rules).

## 5. What this amendment does NOT change

- All other locks in `fe34b76` remain binding: Lock 1 (4.A regime filter), Lock 2 (4-config grid), Lock 3 ((d) restricted universe), all Stage A and Stage B gate thresholds, all F1/F3 sub-gate specifications, all kill criteria.
- Threshold values (funding_threshold, oi_threshold, basis_threshold, stress_threshold) are unchanged.
- Fraction parameters `p_f` and `p_b` numerical values are unchanged. Only their interpretation (fraction of *what*) is clarified.
- The data abstention rule §1.3 is unchanged. An asset whose funding history is incomplete for the 7-day window still abstains. The clarification only resolves how to count events within the window.
- The anti-cherry-pick clause remains in force from this commit forward.

## 6. Auditability

This amendment is committed as a separate, dated artifact distinct from the pre-registration itself. The pre-registration `fe34b76` is left intact; the amendment is appended. Both are referenced by the D-level engineering commits and the eventual D5 verdict memo. Future readers of the candidate's outputs will see both documents and the order in which they landed (pre-reg → amendment → engineering → evidence).

The amendment is binding from its commit and may not itself be amended after evidence is seen.

---

## 7. References

- Pre-registration being amended: `fe34b76`
- Selection memo: `cbd2633`
- Master Sleeve B pre-registration: `fe909bb`
- Q0 cluster-diversity sub-criterion: `3ec7a32`
- Framework state binding (unchanged): per `fe34b76` header.

---

*Amendment #1 to candidate #5 pre-registration. Clarifies that the persistence window N denotes real-time duration (calendar days), not native event count, and that fraction parameters apply to the count of native funding events within the real-time window. Pre-evidence interpretive correction. No threshold or parameter values changed.*
