# Sleeve B Candidate #5 — Pre-registration

**Candidate:** System-stabilizer regime detection (joint funding/OI/basis persistence under stress)
**Family:** §3.1.11 cross-asset / regime-state, with scoping note (selection memo §1.5)
**Date:** 2026-05-21
**Operator:** Wasseem
**Framework state binding:** `fe909bb` (master), `cb9d975` (Q0), `39970f1` (gate inheritance), `3ec7a32` (cluster diversity)
**Subordinate to:** Selection memo at `cbd2633`
**Anti-cherry-pick discipline:** Binding from commit. No mid-window threshold adjustment. No retroactive interpretation. No parameter substitution. Single committed strategy, four pre-registered configs, fixed evaluation logic.

---

## 0. Summary

Candidate #5 pre-registers a regime-state classifier built from the joint persistence of three system-stabilizer metrics — perpetual funding rate, open interest, and perp-vs-spot basis — under conditions of market stress. The signal output is binary (`IMPAIRED ∈ {0, 1}`) per asset per time. The portfolio expression (Q2 = 4.A per selection memo Lock 1) is a regime filter on candidate #4's cross-sectional strategy: when `IMPAIRED == 1`, that asset is removed from the cross-sectional bucket; when `IMPAIRED == 0`, normal operation.

The pre-registration locks four parameter configs (baseline + 3 variants) before any evaluation. All four are evaluated in parallel as primary evidence. Stage B verdict is built on joint behavior across the four configs, not on baseline-with-sensitivity-bolt-on.

The originating intuition is FTX-derived (Nov 2022) but FTX is *outside* the OOS window 2023-04-15 → 2026-04-15 by design — if the signal works only on the regime that produced the intuition, it is over-fit and the OOS evaluation should reveal that.

Promotion threshold is unchanged from candidate #4: the candidate must clear the same Stage B bar that candidate #4 failed (Sharpe ≥ 1.5 clean / 1.75 PASS_WARNING; drawdown ≤ 25% clean / 20% PASS_WARNING). No platform-pivot threshold relaxation. Per `7c10ca0` verdict A1, gates remain at current calibration.

---

## 1. Signal definition (Q1)

### 1.1 Per-asset inputs

For asset *i* at time *t* (8-hour funding-period granularity), four inputs:

**Funding rate.** Binance perpetual funding rate `f(i, t)` published at the funding epoch closest to *t*. Sign convention: positive funding = longs pay shorts.

**Open interest ratio.** `O(i, t) / O_ref(i, t)` where `O_ref(i, t)` is the trailing 30-day rolling median of OI for asset *i*. Computed in USD-notional, not contracts.

**Perp-vs-spot basis.** `b(i, t) = (P_perp(i, t) − P_spot(i, t)) / P_spot(i, t)` reported in basis points. Sign convention: positive basis = perp trading above spot.

**Stress indicator.** Realized vol ratio `S(i, t) = realized_vol_7d(i, t) / realized_vol_60d_median(i)`. Realized vol computed from log returns at 8-hour close intervals over the trailing 7 days for the numerator and trailing 60 days for the denominator (median, not mean — robustness to single spikes).

### 1.2 Per-asset signal

For persistence window length `N` (number of 8h periods), define:

`IMPAIRED(i, t) = 1` iff ALL FOUR of:

```
(a) |f(i, τ)| > funding_threshold for ≥ p_f of recent N periods τ ∈ [t-N, t-1]
(b) O(i, t) / O_ref(i, t) > oi_threshold
(c) |b(i, τ)| > basis_threshold for ≥ p_b of recent N periods τ ∈ [t-N, t-1]
(d) S(i, t) > stress_threshold
```

Else `IMPAIRED(i, t) = 0`.

**Sign-coherence requirement.** The funding and basis distortions in (a) and (c) must be of the *same sign* during the persistence window — both positive (long-pressured) or both negative (short-pressured). Mixed signs do not count as "joint distortion" since they cancel in interpretation. Specifically:

- For (a) and (c) to count together, the *signed* funding and the *signed* basis must point in the same direction for ≥ min(p_f, p_b) of the recent N periods.

This rules out a class of false positives where funding is extreme positive while basis is extreme negative (or vice versa) — a real but different market structure that this signal is not claiming to detect.

### 1.3 Data abstention rule (universe scope per Lock 3)

For asset *i* to participate in the signal at time *t*, the following data must be available:

- Funding rate history for all N periods τ ∈ [t-N, t-1]
- OI value at *t* and at least 30 days of trailing OI history for `O_ref` computation
- Spot and perp prices at all N periods τ ∈ [t-N, t-1] for basis computation
- 60 days of trailing log return history at 8h granularity for realized vol denominator
- 7 days of trailing log return history for realized vol numerator

If any required data is missing or has gaps exceeding 3 consecutive periods, asset *i* abstains: `IMPAIRED(i, t) := 0` and a flag `ABSTAIN(i, t) = 1` is recorded in the audit log.

`ABSTAIN` is reported in the evidence pack but is NOT counted as a signal firing. The pre-registration explicitly records coverage ratio C(t) = (eligible assets at t) / (universe size at t) for every t in the evaluation window.

---

## 2. Pre-registered parameter configs (Lock 2)

Four configs, locked before evaluation:

| Config | N | p_f | p_b | funding_threshold | oi_threshold | basis_threshold | stress_threshold |
|---|---|---|---|---|---|---|---|
| **Baseline** | 21 (7d) | 0.66 | 0.66 | 0.03%/8h | 1.30× ref | 50 bps | 1.50× ref |
| **V1 short persistence** | 12 (4d) | 0.66 | 0.66 | 0.03%/8h | 1.30× ref | 50 bps | 1.50× ref |
| **V2 loose thresholds** | 21 (7d) | 0.50 | 0.50 | 0.02%/8h | 1.20× ref | 35 bps | 1.30× ref |
| **V3 tight thresholds** | 21 (7d) | 0.80 | 0.80 | 0.05%/8h | 1.50× ref | 80 bps | 2.00× ref |

Rationale:

- **Baseline** is the operator-locked working hypothesis.
- **V1 short persistence** tests whether the regime signal works on shorter persistence windows (or whether 7-day persistence is load-bearing).
- **V2 loose thresholds** tests whether the signal still works when thresholds are relaxed — i.e., is the signal coming from the strict tail of distortion or from the broader distortion?
- **V3 tight thresholds** tests whether the signal is mostly noise that disappears once thresholds are made stricter — analogous to candidate #4's F1.4 test of parameter robustness.

**No parameter substitution.** These four configs are locked. No additional configs may be tested mid-window. If post-hoc analysis suggests a fifth config would be informative, that's a finding for a future candidate or framework evolution, not for this evaluation.

---

## 3. Portfolio expression (Q2 = 4.A per Lock 1)

### 3.1 The regime filter

Candidate #5's portfolio expression is an overlay on candidate #4's cross-sectional strategy. Candidate #4's audit log at `ef788b7` contains 157 weekly rebalances with full signal and per-asset position data on the top-30 universe.

For each rebalance date *t* in candidate #4's run:

```
For each asset i in candidate #4's long or short bucket at t:
    Compute IMPAIRED(i, t) under the active config
    If IMPAIRED(i, t) == 1:
        Remove asset i from candidate #4's bucket at t
    Else:
        Keep asset i in candidate #4's bucket at t
```

The remaining long/short buckets are re-equal-weighted within bucket. Portfolio-level vol-targeting (per Reading A locked at `689ddd9`) is recomputed against the filtered buckets' weekly P&L history.

This produces a *filtered candidate #4* time series. Four such time series are produced (one per config). Each is compared against the unfiltered candidate #4 baseline at `ef788b7`.

### 3.2 What this is and is not

- This is NOT a standalone alpha strategy. It is a regime classifier whose value is demonstrated through improvement of a known host strategy.
- This IS a falsifiable test of the regime-state interpretation. If filtering produces no material improvement, or produces improvement that does not survive the parameter grid, the regime-state interpretation is empirically weak.
- Future operationalizations (4.B counter-positioning, 4.C don't-trade overlay) are not part of this pre-registration. They remain available for future candidates.

---

## 4. Stage A gates

Stage A is the framework's pre-evaluation gate stack. Per `39970f1`, inherited gates must be verified per-candidate. Candidate #5's Stage A verification:

### 4.1 A1 — Reproducibility

Engine code must produce identical results given identical inputs. Standard requirement. Verified at engineering D1 (signal module) via unit tests against fixed input fixtures.

**Gate threshold:** PASS_CLEAN if engine produces byte-identical signal audit logs across two runs with the same input fixtures and same config; PASS_WARNING if minor non-determinism (e.g., ordering of equal-priority entries) but economic results identical; FAIL otherwise.

### 4.2 A2 — Temporal stability of eligible universe

The candidate operates on the top-30 frozen universe (`2af9981`). Per `39970f1`, A2 distinguishes endogenous instability (data variation) from deterministic universe expansion (listing growth).

For candidate #5, the relevant question is: does the *signal-eligible* asset count (per §1.3 data abstention rule) vary endogenously over the OOS window? Coverage ratio C(t) must be:

- C(t) ≥ 0.50 for ≥ 80% of the evaluation period: **PASS_CLEAN**
- C(t) ≥ 0.30 for ≥ 80% of the evaluation period (but not the above): **PASS_WARNING** — Stage B sub-gates tighten
- Else: **FAIL** — candidate shelved without Stage B evaluation

This is a per-candidate A2, distinct from candidate #3's spread-based A2 (which was the inherited gate that failed there). The metric here is *coverage* through time, not spread of count.

### 4.3 A3 — Data integrity

All inputs must be PIT-clean per Q0 §1 (already PASS in selection memo). At Stage A, verify in practice that the funding/OI/basis/price data actually retrieved matches the PIT-clean claim by spot-checking 5 random dates against an independent source (e.g., Coinglass historical, where available).

**Gate threshold:** PASS_CLEAN if all 5 spot-checks match within tolerance; PASS_WARNING if minor discrepancies attributable to publication-time differences (still PIT-honest); FAIL on any discrepancy attributable to backfill.

### 4.4 A4 — Methodology lock

Confirm pre-registration is committed before any evaluation runs. Trivial gate but binding.

**Gate threshold:** PASS_CLEAN if this pre-reg's commit hash is referenced in every Stage B output; FAIL otherwise.

### 4.5 A5 — Anti-cherry-pick verification

The pre-registered parameter grid is fixed at this commit. Any deviation — adding a fifth config, modifying threshold ranges, substituting a parameter — triggers immediate kill.

**Gate threshold:** PASS_CLEAN if all four configs as defined in §2 are evaluated and no others; FAIL otherwise.

### 4.6 Stage A FAIL is shelve-without-Stage-B

Per the inherited Sleeve B discipline: any single Stage A sub-gate FAIL shelves the candidate. No Stage B evaluation. No exemption.

---

## 5. Stage B gates

### 5.1 B3 promotion thresholds (unchanged from current calibration)

Per `7c10ca0` verdict A1, B3 gates remain at:

| Metric | Clean | PASS_WARNING |
|---|---|---|
| Sharpe (filtered candidate #4 vs unfiltered baseline) | improvement ≥ 0.30 | improvement ≥ 0.50 |
| Drawdown (filtered max DD) | ≤ 25% absolute AND reduced by ≥ 3pp vs baseline | ≤ 20% absolute AND reduced by ≥ 5pp vs baseline |
| Sharpe gate (filtered absolute) | ≥ 1.50 absolute | ≥ 1.75 absolute |

**Two-part requirement.** The filter must *both* improve relative to baseline AND clear absolute thresholds. A filter that produces "smaller losses" without crossing into promotion-grade absolute Sharpe is not a promotion candidate.

**Per-config requirement.** All four configs must independently clear B3 (at PASS_CLEAN level for at least one config, PASS_WARNING acceptable for the rest). If only baseline clears and the variants fail, the regime-state interpretation is parameter-fragile (candidate #4's failure mode) and the candidate is shelved.

### 5.2 F1-equivalent sub-gates (adapted for binary regime signal)

Candidate #4's F1 sub-gates were calibrated for cross-sectional ranking signals. For a binary regime classifier, the equivalents are:

**F1.1 — Regime transition rate.** Number of `IMPAIRED == 1` periods per asset per year. If trivially small (e.g., < 3 periods/year averaged across assets), the signal is too rare to be informative. If trivially large (e.g., > 50% of periods), the signal is over-firing.

**Gate threshold:** Average per-asset annual firing rate must be in [3, 60] periods/year per config. Outside this range: FAIL.

**F1.2 — Regime duration distribution.** Median duration of consecutive `IMPAIRED == 1` periods per asset. If too short (e.g., < 3 periods median), regime detection is just noise. If too long (e.g., > 30 periods median), the indicator is sticky and not capturing regime changes.

**Gate threshold:** Median consecutive-fire duration in [3, 30] 8h periods per config: PASS_CLEAN.

**F1.3 — Hindsight-bias absence verification.** At each time *t*, the signal must be computable using only data available at *t*. Specifically: realized vol denominators use trailing 60d, not centered windows. Funding history uses funding *published* by *t*, not retrospectively backfilled.

**Gate threshold:** Engine implementation verified via unit test using leak-checker fixture (signal recomputed across time slices, never references future data). PASS_CLEAN required; FAIL on any leak.

**F1.4 — Parameter robustness (parameter grid evaluation).** The four-config grid IS the F1.4 evaluation. The verdict is built on joint behavior:

- If baseline clears B3 and all 3 variants also clear B3 (PASS_WARNING acceptable): **PASS_CLEAN** F1.4
- If baseline + 2 variants clear: **PASS_WARNING** F1.4
- If baseline + 1 variant clear, or baseline alone: **FAIL** F1.4 (parameter-fragile, candidate #4 mode)
- If baseline fails but variants pass: **FAIL** F1.4 (suggests baseline poorly chosen and signal is not robust)

This is structurally similar to candidate #4's F1.4 sensitivity gate, adapted to grid-based evaluation rather than (max-min)/median sensitivity computation.

### 5.3 F3-equivalent sub-gates (adapted for regime filter)

Candidate #4's F3 sub-gates tested misattribution (was the strategy actually disguised low-vol or BTC/ETH concentration?). For a regime filter, the analogous question is: is the filter doing something distinct from a naïve alternative?

**F3.1 — Naïve funding-fade comparison.** Compare candidate #5's filter performance against a naïve "fade extreme funding" overlay that uses only funding (not OI, not basis, not stress). If the simpler signal produces equivalent or better filter improvement, candidate #5's joint-persistence interpretation is not earning its complexity.

**Gate threshold:** Candidate #5 must outperform naïve funding-fade overlay by ≥ 0.10 Sharpe improvement on filtered candidate #4. Otherwise: FAIL — the candidate is a complicated wrapper for the cluster's reflex.

**F3.2 — High-vol-period detection comparison.** Compare against a naïve "filter out high-vol assets" overlay using only the realized vol ratio. If a vol filter alone produces equivalent results, the regime-state interpretation is not adding information beyond simple vol-targeting.

**Gate threshold:** Candidate #5 must outperform naïve high-vol filter by ≥ 0.10 Sharpe improvement. Otherwise: FAIL.

**F3.3 — Filter timing attribution.** For each `IMPAIRED == 1` firing in candidate #5's audit, classify whether the firing was on an asset that *would have lost money* in candidate #4 in the subsequent week (true positive) or *would have made money* (false positive). The filter's value attribution is:

```
Improvement = Σ (P&L of removed-because-IMPAIRED positions that would have lost)
            − Σ (P&L of removed-because-IMPAIRED positions that would have gained)
```

The ratio of true-positive-attributable improvement to total improvement must be ≥ 0.60 — i.e., the filter must actually be removing bad positions more than it removes good ones.

**Gate threshold:** Improvement ratio ≥ 0.60: PASS_CLEAN. Between 0.40 and 0.60: PASS_WARNING. Below 0.40: FAIL — the filter is removing positions arbitrarily, not informatively.

---

## 6. Stage B engineering deliverables

The proven D1-D5 protocol from candidate #4 applies. Per candidate #4 kill action §7.6, the pattern is reproducible. Five deliverables in five sessions:

**D1 — Signal module.** `strategies/sleeve_b/stabilizer_regime/signal.py`. Implements `compute_signal` per §1. Unit tests cover §1.3 abstention logic, §1.2 sign-coherence, all four configs.

**D2 — Backtest / filter application.** `scripts/run_candidate_5_filter.py` and supporting modules. Applies the regime filter to candidate #4's audit log per §3.1. Produces filtered weekly P&L for all four configs.

**D3 — F1 equivalent evaluator.** `scripts/run_candidate_5_f1.py`. Computes F1.1-F1.4 per §5.2.

**D4 — F3 equivalent evaluator.** `scripts/run_candidate_5_f3.py`. Computes F3.1-F3.3 per §5.3.

**D5 — Final verdict memo + kill action OR promotion action.** Synthesizes D2-D4 against B3 thresholds and F1/F3 sub-gates. Produces either kill action (mirroring prior kill action structure) or promotion action (first-of-its-kind structural template — to be specified at D5 drafting time if reached).

Pre-registration locks the protocol; D-level engineering specifics are operationalized at each D's commit.

---

## 7. Kill criteria

Candidate #5 is shelved if ANY of the following fires:

**7.1** Stage A any sub-gate FAIL → shelve before Stage B.

**7.2** B3 baseline fails to clear absolute Sharpe and drawdown thresholds → shelve.

**7.3** F1.4 produces FAIL (per §5.2 grid logic) → shelve regardless of baseline B3 result.

**7.4** F3.1 FAIL (does not outperform naïve funding-fade) → shelve. The candidate must earn its complexity.

**7.5** F3.2 FAIL (does not outperform naïve vol filter) → shelve.

**7.6** F3.3 FAIL (improvement ratio < 0.40) → shelve. The filter must remove bad positions more than good ones.

**7.7** Any integrity failure (per master roadmap §12) → automatic shelve, regardless of metrics.

**Anti-cherry-pick clause:** No threshold relaxation after evidence is seen. No mid-window kill criterion negotiation. No deferring decisions to "see more data." Pre-registered gates fire when their thresholds are crossed.

---

## 8. What this pre-registration does NOT establish

- It does NOT promise that filtering candidate #4 will improve its Sharpe. The filter might be neutral or counterproductive — that's the test.
- It does NOT establish the regime-state interpretation as correct. Only evidence does that.
- It does NOT pre-register portfolio expressions 4.B (counter-positioning) or 4.C (don't-trade overlay). Those remain available for future candidates.
- It does NOT amend or supersede any prior pre-registration or framework artifact. Master `fe909bb`, Q0 `cb9d975`, gate inheritance `39970f1`, framework review `7c10ca0`, and cluster diversity `3ec7a32` all remain binding.
- It does NOT pre-empt the "platform pivot" strategic question raised earlier this week. That question is deferred to a separate framework-evolution memo, if and when, after candidate #5 evaluates.

---

## 9. Budget and pacing

Per `fe909bb`, Sleeve B master budget runs to 2026-06-27 kill date. Candidate #5 selection memo committed at `cbd2633` on 2026-05-21. Candidate #5 engineering budget: approximately 5 sessions across D1-D5, mirroring candidate #4's cadence. Realistic completion window: 1-2 weeks of engineering time.

If engineering deliverables exceed 8 sessions for D1-D5 (excluding pre-registration drafting), that itself is a signal that the candidate is more complex than its premise warrants. Sessions are not gates but excess is informative.

---

## 10. References

- Master Sleeve B pre-registration: `fe909bb`
- Q0 Data Viability Gate: `cb9d975`
- Stage A gate inheritance: `39970f1`
- Sleeve B framework review (May 2026): `7c10ca0`
- Q0 cluster-diversity sub-criterion: `3ec7a32`
- Candidate #5 selection memo: `cbd2633`
- Candidate #4 audit log (host strategy for §3.1 regime filter): `ef788b7`
- Prior kill actions (corpus context): `924a930`, `f3e078e`, `bf642d1`, `bf0a23e`, `5619d09`
- Portfolio interpretation memo (Reading A, inherited): `689ddd9`

---

*Pre-registration for Sleeve B candidate #5. Signal: per-asset binary regime classifier from joint persistence of funding/OI/basis distortion under stress. Portfolio expression: 4.A regime filter on candidate #4's cross-sectional strategy. Universe: top-30 fixture, restricted by data completeness (assets abstain if incomplete). Parameter discipline: baseline + 3 pre-registered variants, evaluated in parallel. Stage A gates: A1-A5 with per-candidate A2 calibrated for coverage. Stage B gates: B3 unchanged from current calibration, F1.1-F1.4 adapted for binary regime signal, F3.1-F3.3 adapted for regime filter (must outperform naïve funding-fade and naïve vol filter; improvement must be true-positive-attributable). Anti-cherry-pick discipline binding from commit.*
