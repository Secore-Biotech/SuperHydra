# A1 Burst-Activation — Deployability Screen (§4 bullet 5)

**Status:** Final — paper-only screen. No economics, no exporter, no probe code, no v2 spec.
**Author:** Wasseem Katt
**Date:** 2026-06-02
**Question:** Is a burst-activation funding-capture strategy operationalisable under the program's capital ceiling, time budget, and P1 runway — *before* any v2 spec is written?
**Inputs:** `scripts/a1_phase1_funding_regime_recon.py --episodes` (episode segmentation at θ=0.0200%, gap-tolerance and minimum-length swept) and the Phase-2 walk-forward fold counts (`scripts/a1_phase2_walkforward_recon.py`). Funding fixture `fixtures/real_vol_event_fixture_v3.json`, BTCUSDT + ETHUSDT, 2023-04-01 → 2026-05-28.
**Scope guard:** This screen tests *operational deployability only*. It does not test, and does not claim to test, whether burst-window funding capture is economically positive. θ is fixed at the v1-locked 0.0200%/8h throughout.

---

## 1. Why this screen exists

The Phase-1 and Phase-2 diagnostics established that A1 v1's `DATA_LIMITED` outcome was not a wrong threshold and not merely a badly-placed single split. Fixed θ=0.0200% *did* clear the §5 sample-sufficiency floors — but only in walk-forward folds whose out-of-sample window overlapped a funding burst (Phase-2 folds 2–3). Every fold anchored in 2025 onward was starved on both train and OOS. The honest characterisation is:

> Elevated funding at θ=0.0200% is **episodic**. It is sample-sufficient only during burst regimes, and it has been dormant through the recent (2025–26) regime.

That leaves exactly one A1-shaped hypothesis still live: a **burst-activation capture** strategy — one that arms only when funding bursts are present and is otherwise dormant, rather than a continuous fixed-threshold or regime-relative probe (both of which the diagnostics ruled out). This note screens that hypothesis against `edge_scoping.md` §4 bullet 5 (deployment shape operationalisable under the program envelope) before it is allowed to consume a spec.

## 2. Evidence — burst-episode segmentation at θ=0.0200%

Episodes were segmented from the 8-hour funding series (an observation is "hot" if positive and ≥θ; episodes are contiguous runs of hot observations under a gap-bridging tolerance, dropping isolated spikes below a minimum length). Both the gap tolerance and the minimum length were swept, because those two knobs are the only places the result could be flattered or punished.

**Duty cycle (active fraction of calendar span), at locked θ=0.0200%:**

| Knob setting | BTCUSDT | ETHUSDT |
|---|---|---|
| gap-tol 0, min-days 3 (strictest) | 3.1% | 3.6% |
| gap-tol 3, min-days 3 (default) | 4.9% | 5.9% |
| gap-tol 9, min-days 5 (loosest) | 5.6% | 6.7% |

The active fraction is knob-sensitive in magnitude but never escapes single digits. Under every setting, a burst-capture strategy at the locked threshold would be live **roughly one month in every 16–32**.

**Episode structure (all settings, both symbols):**

- Episodes are short and clustered: most 3–25 days; the longest single contiguous episode is ~38 days (ETH, looser settings).
- Every episode falls inside two windows: **2023-11 → 2024-04** and **2024-11 → 2024-12**. There are no qualifying episodes anywhere else in the 38-month span.
- Historical dormant gaps between episodes run **222–249 days** at locked θ.

## 3. The decisive fact — current live dormancy

The episode list is not the operative number. The operative number is the position of the *most recent* episode relative to now:

> The last qualifying burst on **both** symbols ends **2024-12-09**. There has been no funding observation ≥θ=0.0200% on either symbol since. As of this note (2026-06-02) that is **≈540 days of continuous dormancy**, and it is ongoing.

This is not a gap *between* historical episodes — it is an open dormancy that the strategy would be sitting inside today. It is more than twice the longest historical inter-episode gap (222–249 days), and it holds across every knob setting because loosening the episode definition changes the historical duty cycle slightly but does nothing to the fact that the most recent qualifying observation is ~18 months old.

## 4. Screen questions answered

- **How many burst windows existed?** 4–10 per symbol depending on segmentation knobs, all confined to two clusters (2023-11→2024-04 and 2024-11→2024-12).
- **How long did they last?** Mostly 3–25 days per episode; longest contiguous ~38 days. No sustained multi-month regime.
- **What fraction of calendar time is active?** 3–7% at locked θ=0.0200% (report as a range; it is knob-sensitive). Single digits under all settings.
- **Would a P1 paper run likely see any active periods?** Under the current runway assumptions, a burst-capture strategy would be unlikely to encounter an active regime during the available deployment-contact window. This is stated without anchoring to a specific P1 start date deliberately: the ~540-day ongoing dormancy is large relative to any reasonable P1 horizon (60 / 90 / 180 days), so the conclusion does not depend on when the window opens. The next burst's arrival is unpredictable; historical gaps of 222+ days mean the base rate of a burst beginning inside any given 2–3 month window is low.
- **Does this satisfy `edge_scoping.md` §4 bullet 5?** No. A deployment shape that is dormant ~95% of the time, has produced nothing for ~18 months, and is unlikely to make deployment contact inside the runway is not operationalisable under the program's time budget and runway. It fails the operational limb of bullet 5.

## 5. Verdict

> **A1 burst-activation capture — FAIL (§4 bullet 5).**
> **Operational rejection.** Duty cycle 3–7% at locked θ; last qualifying burst 2024-12-09; ~540-day ongoing dormancy exceeds any reasonable deployment-contact window.
> **Economic status: UNKNOWN.** Q4–Q6 (gross carry net of basis drift and two-leg execution, inside the burst windows) were never tested. No spot-kline exporter was built. This screen does **not** establish that burst-window funding capture is unprofitable — only that, profitable or not, it cannot be operationalised for this program.

This is a deliberate distinction. A1 burst-capture is **economically untested but operationally unusable**, which is not the same as **economically disproven**. If the program's envelope changed (larger capital, longer runway, or tolerance for a strategy that idles for years between active windows), the economic question could become worth testing. Under the current envelope it is not.

## 6. Followups (none executed in this note)

- **No code, no exporter, no v2 spec.** The screen's purpose was to determine whether a spec was warranted; it is not.
- **`edge_scoping.md` classification — deliberately deferred.** §3.1 currently reads as a kill list of *empirically/economically* weakened directions. A1 burst-capture is a different category: economically untested, operationally rejected. Collapsing "economically disproven" and "economically untested but operationally unusable" into one bucket would corrupt the taxonomy. The decision — whether §3.1 gains an "operational rejections" subsection, or A1 burst-capture sits in a new category — is to be made deliberately after this note lands, not folded into it.
- **The Q4–Q6 economic question remains open on the record**, not closed. It is parked on operational grounds, not answered. Any future reconsideration would require the envelope to change first.

## 7. What this screen cost, and what it bought

Two recon scripts (committed at `07520d0`) and this note. No build, no exporter, no spec. The A1 v1 spec discipline plus three levels-only diagnostics took A1 from "promising unresolved thread" to "operationally rejected with economic status honestly marked unknown" without spending a single build cycle on a strategy that idles 95% of the time. That is the pre-lock / cheap-feasibility discipline doing exactly what `failure_mode_analysis_v1.md` argued it does — rejecting a non-deployable engine before it earns the cost of being built.

— end —
