# Token Unlock Mechanics — Event Universe Audit (Gate 2A + Sample)

**Status:** Open audit. Decides whether the standalone unlock-mispricing trade (Gate 3A PASS — shape confirmed) can satisfy Risk Standard v1.0 §3 sample requirements, or is sample-limited like Section A. No signal, no backtest. The thresholds below are **pre-locked before counting** — the count must not set the thresholds.
**Author:** Wasseem Katt
**Date:** 2026-06-03
**Prereq result:** `token_unlock_deep_prescreen.md` Gate 3A returned **standalone shape EXISTS** (the mispricing trade — priced-in drift vs estimated realized impact, token-versus-own-history, no benchmark book required — is not overlay-only). The binding question relocated to data depth and sample sufficiency. This audit answers it.

## Why thresholds are locked before the count

The audit's parameters (minimum unlock size, liquidity floor, universe) determine the event count. If chosen *after* seeing which values yield enough events to clear §3, the audit becomes reverse-engineered — the A1-density-recon failure mode (tune the event definition until events appear). Per the discipline that held Section A, A1, and the combination screen, the thresholds are locked here, justified by economics, and the count is reported *at these thresholds only*. If the count fails, it fails — loosening a threshold to rescue it is a deliberate v2 audit, not an amendment (§8 pattern).

## Pre-locked thresholds (economic justification, not count-driven)

- **Minimum unlock size: ≥ 5% of circulating supply.** Justification: below ~5%, the supply shock is plausibly within normal daily-volume absorption and unlikely to produce a measurable priced-in-vs-realized divergence. 5% is the floor at which an unlock is economically a *shock* rather than noise. (Locked; not tuned to the count.)
- **Liquidity floor: token must have sufficient depth that a family-capital-scale position (per Risk Standard v1.0 sizing) is executable without self-impact dominating the trade.** Operationalize as a minimum average daily volume threshold over the pre-unlock window — exact number to be set from the slippage-calibration precedent (`sol_slippage_calibration_memo.md`), locked before counting.
- **Exchange availability:** token must be listed on a venue in the current substrate (Binance USDM/spot, or a venue reachable without new onboarding — no new venue integration, per §4).
- **Window: 2021-present** (or earliest PIT-clean date — see Gate 2A). Pre-2021 crypto unlock data is sparse and PIT-integrity is doubtful.

## The questions (in order)

**1. Gate 2A — PIT integrity (the gate that feeds everything below).**
Do the named sources (Tokenomist / TokenUnlocks / Token Terminal, per `data_policy.md`) preserve **as-of-date** schedules and revision history, or only the final realized schedule? If only final, "priced-in vs realized" is unmeasurable (anticipated impact is unrecoverable) and the mechanism dies here — Sleeve B #2 precedent. **Earliest date from which PIT-correct history exists** sets the usable window.

**2. Gross qualifying event count.** Number of unlock events 2021-present satisfying all locked thresholds (≥5% float, liquidity floor, exchange availability). A count.

**3. Temporal distribution (the Section A guard — the load-bearing check).** Events per year across the window. Section A died not on gross count (131 events) but because the train/OOS split left 94/37 — the OOS partition starved. The unlock universe inherits this exact risk if events cluster in one era (e.g. the 2021 unlock wave) and the recent OOS window is thin. So: **does a §3-compliant split (≥24 months OOS) leave ≥ the sample floor in BOTH train and OOS partitions?** A thousand events all in 2021 fails this as surely as Section A did.

**4. PIT-clean poolable count.** Of the qualifying events, how many have PIT-correct schedule + price + liquidity data — the actual usable sample, not the gross count.

## Decision rule (pre-committed, before the count)

- **PASS:** PIT-clean poolable events clear the §3 sample floor in **both** train and OOS partitions over ≥24 months, at the locked thresholds. → Token Unlocks earns a signal research program, pointed at the standalone mispricing trade, candidates tested against Risk Standard v1.0.
- **FAIL (sample):** insufficient poolable events, or temporal clustering starves a partition. → Token Unlocks classified **sample-limited** — standalone shape confirmed, but the in-envelope data universe cannot support evaluation. Recorded on the direction map. Same terminal class as Section A: real, but unevaluable in-envelope.
- **FAIL (Gate 2A):** sources don't preserve PIT schedules. → data-limited, Sleeve B #2 class. Recorded.

No threshold-loosening rescue. If the count fails at ≥5% float, dropping to 3% to rescue it is a new pre-registered audit with its own economic justification, not an amendment to this one.

## What each outcome means for the project

- **PASS** → the first signal research program of the entire new-program effort opens, on genuinely fresh ground (a mechanism absent from the direction map, with a confirmed standalone shape and sufficient sample). This would be the first time since the map closed that a direction earned a build.
- **FAIL (either kind)** → the Discovery Program reaches terminal exhaustion: 7 families → 1 survivor → 0 evaluable standalone primary engines in the current envelope. And the constraint is now identified from a **third independent angle**: not execution (liquidation/MEV), not capital (A3 venue), but **data depth / sample** (unlocks). Three different mechanisms, three different envelope walls. That triangulates the conclusion: the binding constraint is the envelope — solo-operator, family-capital, current-substrate — not a shortage of real mechanisms. At which point the fork is explicit: expand the envelope (data depth, venues, capital) or accept the systematic-edge search under this envelope is complete.

## Next step (one, cheap, operator-driven)

Answer question 1 (Gate 2A PIT check against the free-tier sources) and questions 2–4 (the event counts and temporal distribution) at the locked thresholds. This is a data-availability audit — checking sources and counting — not a build. The count is decisive either way: it opens the first signal program or it closes the Discovery Program with a triangulated, hard-to-challenge conclusion.

— end —
