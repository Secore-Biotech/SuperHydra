# Token Unlock Mechanics — Deep Pre-Screen

**Status:** Open pre-screen. Decides whether Token Unlocks is a **primary-engine** candidate (→ signal research) or **overlay-only** (→ removed from primary-engine search space). No signal, model, or backtest until it clears. Gate 2A is partly chair/record-evaluable; Gate 3A is the operator gate.
**Author:** Wasseem Katt
**Date:** 2026-06-03
**Context:** Token Unlocks was the sole survivor of `mechanism_discovery_program_v1.md` (`1f544d9`) — the only family with no obvious failure across the four discovery gates. This deep pre-screen tests the two gates that the discovery pass left provisional, both sharpened by what the project record then revealed (see "New evidence").

## New evidence since the discovery pass

The discovery note marked Gate 2 and Gate 3 "Provisional PASS." The repo record then qualified both:

- **`docs/policies/data_policy.md`** names the data sources (Tokenomist / TokenUnlocks / Token Terminal, free tier "may suffice initially") and the `intelligence.token_unlocks` schema is designed in `ledger-schema-design-v0.2`. So the **source-and-schema half of Gate 2 is pre-scoped** — better than the discovery note assumed.
- **But** the same policy classifies tokenomics/unlocks as a **Phase-7+ category, "post-canary of L/S engine,"** described as **"Tokenomics overlay or L/S enhancement,"** with a procurement trigger requiring the *engine that needs it* to have entered Research stage first. The project's own architecture filed unlocks as an **enhancement to an existing engine, not a primary engine.** That is not proof it cannot be primary — but it is documented evidence the original design did not conceive it that way, and the project has repeatedly learned to respect that kind of evidence (cf. A3's "promote when A1/A2 at scale" gate).

This sharpens both remaining gates. The mechanism (Gate 1) is unchanged and strong: known schedule, known supply event, known participants, plausible forced-absorption mechanism. The open questions are data integrity and — decisively — whether a *standalone* trade exists.

## The two hypotheses under "Token Unlock Mechanics"

- **Hypothesis A (primary engine):** unlocks are a standalone alpha source — open a position before an unlock, close after, strategy exists independently. A primary-engine claim.
- **Hypothesis B (overlay):** unlocks improve decisions made by *another* engine (L/S book, factor book) — tilt, filter, risk adjustment. An enhancement claim.

The data-policy language ("overlay or L/S enhancement") sounds much closer to B. This pre-screen exists to determine which is true, because only A is a primary-engine candidate, and the project currently has **no L/S engine** for B to enhance (the search that would have produced one is exhausted). If Token Unlocks is B-shaped, it inherits A3's problem: real and in-envelope-on-data, but blocked on a prerequisite engine that does not exist.

## Gate 2A — Point-in-Time Correctness

**Question:** Can historical unlock schedules be reconstructed *as known at the time*, not as finally realized?

Required to PASS:
- Historical schedule availability over an OOS window ≥ 24 months (per Risk Standard v1.0 §3).
- **Revision history / announcement timing:** unlocks get rescheduled. The data must preserve the *as-of-date* schedule (what was known on date T), not silently overwrite with the final schedule. This is the **exact failure mode that killed Sleeve B #2** (DeFiLlama backfilled fee data, destroying PIT integrity).
- PIT integrity confirmable from the named free-tier sources.

**FAIL condition:** if the sources only provide the *final* realized schedule (revisions overwritten), the data is backfill-contaminated and Gate 2A fails for the same reason as Sleeve B #2 — and the realized-vs-anticipated-impact hypothesis cannot even be measured, because "anticipated" is unrecoverable.

**Note:** unlocks are *announced in advance*, which is structurally more PIT-friendly than backfilled fee data — the as-of schedule existed publicly. The question is whether the data *vendor preserves* it. This is checkable cheaply against the free tier before any build.

## Gate 3A — Standalone Deployment Shape (the decisive gate)

**Question:** Can unlock impact be traded as a *primary engine* — a standalone, deployable strategy under Risk Standard v1.0?

Required to PASS (Hypothesis A):
- **Entry rule** — a specific, pre-registrable position taken before an unlock.
- **Exit rule** — a specific close after.
- **Holding period** — consistent with weekly cadence and the family-capital envelope.
- **Risk model** — position sizing under Risk Standard v1.0 (DD ≤ 20%, the altcoin-liquidity-depth caveat for thin vesting names).
- **Capital deployment model** — how capital is allocated across concurrent/sequential unlock events without concentration breaching the standard.

**FAIL condition:** if the only coherent way to use unlock information is to *tilt an existing book* (Hypothesis B) — i.e. there is no standalone position that stands on its own, only an adjustment to positions a core engine already holds — then Token Unlocks is **overlay-only**, classified as an enhancement, and **removed from the primary-engine search space.** This is the same test that closed vol-dislocation: a mechanism and even a measurable effect are not enough; a deployable standalone strategy is the bar.

**The A3 parallel to weigh:** if Gate 3A resolves to overlay-only, Token Unlocks is real, data-accessible, in-envelope on cost — but blocked on a prerequisite (a core L/S engine) the exhausted search did not produce. That is A3's shape, not a kill. It would be recorded as overlay-blocked, re-eligible only if a core engine it can enhance comes to exist.

## Decision

- **PASS (both gates):** Token Unlocks is a primary-engine candidate. A signal research program opens, pointed at this one family, candidates tested against Risk Standard v1.0. Not before.
- **FAIL Gate 2A:** data category closed (PIT-contaminated, Sleeve B #2 precedent). Recorded on the direction map.
- **FAIL Gate 3A:** reclassified overlay-only, removed from primary-engine search space, recorded as overlay-blocked (A3-shaped). Recorded on the direction map.

## What a FAIL would mean for the project

If Token Unlocks fails Gate 3A (the most likely failure, given the data policy's own "overlay/enhancement" framing), then:

> Discovery Program → 7 mechanism families → 1 provisional survivor → 0 surviving **standalone** primary-engine families inside the current envelope.

That is a stronger and more precise conclusion than the direction map alone could produce. Not "no signals survived" but **"no standalone mechanism family survived inside the current envelope"** — which sharpens the project's fork to its true form: the binding constraint is the *envelope* (solo operator, family capital, no core engine to enhance, weekly cadence), not a shortage of real mechanisms. The strongest mechanisms (liquidation, MEV) need an execution envelope you don't have; the most accessible (unlocks) may need a *core engine* you don't have. Both are envelope constraints, not idea shortages.

## Next step (one, cheap, operator-driven)

- **Gate 2A:** check the free-tier sources (Tokenomist / TokenUnlocks) for whether historical schedules preserve as-of-date / revision history. A data-availability check, not a build.
- **Gate 3A:** the operator judgment — is there a standalone entry/exit/holding/risk/capital model for trading unlock impact, or does the trade only make sense as a tilt on a book that doesn't exist? This is the gate that decides primary-engine vs overlay-only.

Paper only. No signal, no backtest, until both clear.

— end —
