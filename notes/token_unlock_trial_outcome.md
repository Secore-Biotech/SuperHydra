# Token Unlock — Tokenomist Trial Outcome (cheap gates cleared)

**Status:** Trial phase complete. First candidate in the entire new-program search to clear every cheap gate without a kill. Two questions remain (drift signal existence + temporal distribution), both requiring paid Elite-tier data. Decision: a bounded, trial-justified Elite-tier spend, or close here.
**Author:** Wasseem Katt
**Date:** 2026-06-03
**Inputs:** Tokenomist 3-day trial (49 tokens / ~1yr backward), `scripts/tokenomist_unlock_poc.py`, pre-registered spec `token_unlock_drift_poc_spec.md`, audit `token_unlock_event_universe_audit.md`.

## What the trial resolved

**Gate 2A (PIT integrity) — RESOLVED.** Unlock Events carry `unlockDate` + `latestUpdateDate` (revision flag) but NO revision history (no as-of-date schedule archive). So the announced-schedule-change version of the trade is not buildable — but the **drift-based version** (priced-in = pre-unlock abnormal drift vs token's own history; needs only dates + prices, not PIT history) is unaffected. Drift-based path confirmed as the only and intended route.

**Data viability — RESOLVED (favorable).** The v5 schema carries everything the drift POC + impact estimator need: `unlockDate`, `cliffAmount`, `cliffValue`, `valueToMarketCap` (precomputed %-of-mcap — sidesteps the supply-join that blocked the DeFiLlama route), `allocationBreakdown[].standardAllocationName` (recipient type per event), `referencePrice`. Auth (x-api-key) and endpoints (`/v5/token/list`, `/v5/unlock/events/{slug}`) work.

**Sample density — RESOLVED (favorable, the key positive result).** Trial: 49 tokens × ~1yr → 43 events >=5% of mcap = ~0.88 events/token/year. Full universe = **633 tracked tokens**. Extrapolation: 633 x 0.88 = ~557 events/year; over a 24-month §3 window = ~1,100 events; 36 months = ~1,670. Even with a 5-10x haircut for trial-token selection bias (trial 50 are likely the largest/most-tracked) and density variance, the universe clears Risk Standard v1 §3 sample floors comfortably. **Token unlocks are NOT Section-A-sparse at the universe level** — the first probe in the arc where the sample question came back clearly favorable rather than fatal.

## What the trial could NOT resolve (both require Elite-tier)

**Temporal distribution (the residual Section-A risk) — UNANSWERABLE on trial.** The trial returns only ~1yr backward, so all 43 events fell in 2025-26 — a trial-window artifact, not the true distribution. 633 tokens existing now does not reveal WHEN their >=5% cliffs occurred. If large cliffs cluster 12-18mo post-launch and launches cluster in market waves (2021, 2024-25), the calendar distribution could still be lumpy enough to starve an OOS partition. Universe-level count is sufficient; temporal spread is unconfirmed. Needs Elite-tier (2yr backward) to check.

**Drift signal existence — UNANSWERABLE on trial.** 43 events split by direction (~20/side) has no statistical power. Whether pre-unlock abnormal drift predicts/diverges from realized impact cannot be read off the trial window. Needs the fuller event set (Elite 2yr + full universe) to run the pre-registered drift POC with power.

## Verdict

> **Token Unlocks clears every cheap gate.** Standalone shape confirmed (Gate 3A), PIT-independent drift path confirmed (Gate 2A), data viable, and sample density extrapolates to comfortably sufficient over a §3 window (633 tokens × ~0.88 events/token/yr). This is the **first candidate in the entire new-program search to survive the full screening cascade without a kill.** It is NOT yet a validated edge: the two questions that decide it — does the drift signal exist, and is the temporal distribution §3-compliant — both require paid Elite-tier data (2yr backward, full 633-token universe) and cannot be answered on the free trial.

## The costed decision (now trial-justified, not blind)

> **Pay for Tokenomist Elite (2yr backward, full universe) to run the pre-registered drift POC + the §3 temporal-distribution check?**

The trial de-risked this: you are not paying blind. The free preview confirmed the data is real, drift-compatible, PIT-path-viable, and density-sufficient. Under family-capital logic, a bounded Elite-tier spend to run the real drift POC — given the candidate cleared every cheap gate it could — is a rational, proportionate bet, materially more justified than before the trial. The remaining risk is concentrated in two specific, now-isolated questions, not in vague uncertainty.

- **If yes →** acquire Elite data, run `tokenomist_unlock_poc.py` extended to the drift calculation (price join + the pre-registered direction rule), check temporal distribution across 2yr, apply §3. First real signal evaluation of the entire effort.
- **If no →** Token Unlocks recorded as **trial-cleared, paid-data-gated**: the only candidate to survive the cheap gates, blocked solely on a paid-data spend. Discovery Program reaches a *different* terminal state than the others — not "killed" but "cleared-but-unfunded-for-data." The envelope constraint here is data cost, the cheapest of all the walls hit (execution/capital/data-depth), and the most easily removed by a small deliberate spend.

## Significance for the project

Every prior probe died on a cheap gate (sparse, fragile, biased, out-of-envelope, execution-blocked). Token Unlocks is the first to reach the paid-data threshold with all cheap gates green. That does not mean it has an edge — it means it has *earned the cost of finding out*. The search is no longer "is there any candidate worth pursuing" but "is the one surviving candidate worth a bounded data spend to evaluate properly." That is a materially better position than the exhaustion conclusion the project was prepared to accept.

— end —
