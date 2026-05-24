# A1 Audit Findings

**Date:** 2026-05-22 (session N+1 after candidate #5 kill)
**Purpose:** Reconcile the 12-month plan's "build A1 first" framing against on-disk reality.
**Output of:** Phase 2 audit session per adopted 12-month plan.
**Decision adopted:** (α) + (γ) — A1 infrastructure survives as substrate + monitoring layer; A1 original strategy does not survive as the path to deployable returns. The fresh Sleeve A engine inherits A1/A2 infrastructure but is a new hypothesis.

**Status:** Personal notes. Not committed. Not governance.

---

## 1. What exists on disk

### 1.1 A1 (`strategies/a1_funding/`)

Mature infrastructure. Originated as "funding-rate carry" engine. Built across Days 1-20 (the "Day NN" commit series in `feature/migrations-0001-foundation` branch). Last substantive commit: `08cd109` (Day 20.5 operator harness). Reclassified to "monitoring layer" by `6b410a9` (Day 20.7) on 2026-05-12.

**Status per Day 20.7:** "infrastructure mature, economic hypothesis unvalidated. Runnable as a monitoring layer. Not promoted to paper gate."

### 1.2 A2 (`strategies/a2_basis/`)

Built across Days 21-28 on ~80% of A1's substrate. Killed at `924a930` after Step 3 produced zero entries in normal regime; stress-regime positives depended on liquidation conditions with unmeasured execution.

**Status per A2 kill action:** "signal-positive under stress, execution-unmeasured under stress, inactive in normal regimes, not paper-gate eligible, shelved as currently specified."

### 1.3 Other directories present

- `strategies/market_neutral_ls/` — appears to be an empty/early scaffold for Sleeve B's market-neutral L/S concept. Created May 2.
- `strategies/_slot_2_reserved/` — placeholder directory, dated May 2.
- `strategies/sleeve_b/` — Sleeve B's home. Five candidates over April-May, all killed.
- `tests/fixtures/binance_funding/` — A1 test fixtures.

### 1.4 Carry-forward substrate (from Day 20.7 + A2 kill action)

**From A1 (10 components named in Day 20.7's carry-forward table):**

1. OMS layer
2. Risk layer
3. Cost model
4. `paper.fills` table + writer + integration tests (`9193b65`)
5. Replay observation infrastructure (T2+G2 replay + tape-grounded, `d9fd108`)
6. Slippage calibration aggregator (`b2b17bc`)
7. Operator harness pattern (PAPER_RESEARCH runner — `fd9bea7`, `08cd109`)
8. Binance funding-rate fetcher (`8e60933`) + scaffolding (`0e7b377`)
9. Empirical roll-spread methodology (`5f8b644`)
10. Archive-backed historical microstructure path (Days 19a-19c)

**From A2 (additional 9 components per A2 kill action):**

1. Archive ingestion (perp + spot Binance fetchers)
2. Paired basis fixture generation
3. `paper.fills` infrastructure with hash-match no-op idempotency
4. Position-state substrate (`paper.positions` migration 0011 + open/close helpers)
5. Exit evaluator framework (pure decision module, six structured reasons)
6. Operator harness patterns (`paper_research_harness.py` with `run_id` tagging)
7. Empirical close-out methodology with `--allow-noop-fetcher` gate and MODELED-ONLY slippage guard
8. Advisor review checklist (CI-enforceable test-stub leakage rule)
9. Leg-routing `A2DualFetcher` (reusable via `TradeFetcher` protocol)

Combined: ~19 substrate components. Most of the engineering work of two engine attempts is preserved as reusable infrastructure.

---

## 2. What failed and how

### 2.1 A1 — sparse-event threshold pathology

**Signal formulation:** `mean(12) - 1.0 × stdev(12)` on funding rate history per asset.

**Empirical finding (Day 20.6, `87d121e`):** Six SOL 14-day windows produced zero intents. BTC and ETH structurally untradeable per Day 17c's cap-bound finding.

**Diagnosis per Day 20.7:** The threshold is *more selective than the funding regime itself*. It suppresses high-mean funding windows when funding is volatile — but those volatile-high-mean windows are exactly the ones where the strategy should fire. So the formulation never sees the regimes its economic claim was built around.

**Forbidden remediations per Day 20.7's explicit clauses:**
- Not changing the threshold (calibration tampering)
- Not continuing fixture hunting
- Not deviating from the existing roadmap structure beyond the A1→A2 priority swap

### 2.2 A2 — cost-anchored threshold pathology

**Signal formulation:** z-score on perp-vs-spot basis dislocation, with a cost-anchored threshold (33.84 bps for SOL, 24.24 bps for BTC).

**Empirical finding (Step 3, `75ca27d`):** Normal-regime: zero entries. Stress-regime: positive entries, but execution conditions during those stress windows were unmeasured and unreliable.

**Diagnosis per A2 kill action:** A threshold tuned to ensure realistic costs sits well above normal-regime basis. The strategy then fires only in stress regimes — precisely the conditions where execution is hardest. **"Fires only when untradable."**

**Forbidden remediations per A2 kill action:**
- Threshold tuning alone is not a new hypothesis
- Anti-cherry-pick rule forbids lowering the 33.84 bps threshold on the existing Step 3 window
- Re-opening requires: new pre-registered hypothesis, materially different mechanism, new kill criteria before testing

### 2.3 The shared failure mode

Both A1 and A2 reduced to a common pathology: **a thresholded signal whose trigger is suppressed in the very conditions the economic claim depends on.**

This is a structural risk for any threshold-based selectivity logic in this venue and asset class. It's not specific to funding or basis; it's specific to "threshold tuned for cost-clearance applied to a signal with regime-dependent magnitude."

---

## 3. Three durable lessons from A2 kill action

These are on disk in `924a930` and apply to any new Sleeve A engine.

**Lesson 1.** Cost-anchored thresholds can create fires-only-when-untradable pathology. The threshold tuning constraint and the signal-magnitude distribution interact in ways that suppress the strategy precisely when it should fire.

**Lesson 2.** Substrate-only findings are not decision-grade. A2's Day 27B Sep 2021 finding looked positive but was "entries fired only, no closed trades, no P&L, no slippage measured." Counting entries is not measuring performance.

**Lesson 3.** Test-stub leakage is a real failure mode. A test-only `_NoopFetcher` silently substituting for a real fetcher produced positive-looking headlines for several days. The MODELED-ONLY labelling guard and advisor checklist are durable governance and apply to all future engines.

---

## 4. Reconciliation with the 12-month plan

### 4.1 Plan framing (adopted earlier this session arc)

> Phase 2 — Build ONE Real Surviving Engine. Which engine should you build first? Sleeve A1. Funding-rate carry.

### 4.2 Disk reality

A1 was already attempted, found to produce zero intents under its own pre-registered threshold, explicitly held in "monitoring layer" status with threshold remediation forbidden. A2 followed, was built on A1's substrate, failed with a structurally similar pathology, and was killed. Sleeve B then ran 5 candidates which all failed. The plan's "build A1 first" was written without consulting this state.

### 4.3 Updated framing

**Old:** Build A1 first.

**New:** Use the existing A1/A2 substrate (~19 components) to design and validate the first deployable Sleeve A engine. The new engine is a fresh hypothesis. It is not "A1 as specified in `fe909bb`." It is also not "A2 with a different threshold." Both prior engines are preserved as historical record and as runnable infrastructure.

### 4.4 What of A1 remains operational

Per (γ), A1's monitoring-layer status authorized in Day 20.7 stands. A1's runner can be deployed as a real-time funding-rate monitor — not as a strategy, not generating P&L, but generating data about funding regimes that might inform future hypothesis design. Low engineering cost; output is observation, not return.

---

## 5. Design constraints for the next Sleeve A engine

These are NOT design decisions. They are constraints any new design must satisfy.

**C1. Avoid the "fires only when untradable" pathology.** Any threshold logic must be tested against the historical distribution of the signal and the regime distribution of the venue. If the threshold suppresses trades in normal regimes and only fires in stress regimes, the design fails this constraint regardless of how attractive the economic claim is.

**C2. Substrate-only findings do not count.** Decision-grade evidence requires closed trades with measured slippage and attributed P&L. Counting entries is not measuring performance (per A2 lesson 2). No "looks positive" claims from incomplete runs.

**C3. Test-stub leakage prevention applies.** MODELED-ONLY guards and CI-enforced no-test-fetcher rules apply by default. New engine inherits the existing checklist.

**C4. Q0 §3.6 audit before pre-registration.** Per `b315d1e`, data shapes are verified by direct inspection before any pre-reg commit. Specifically: any data dependency named in the new engine's signal must have its native cadence, PIT-cleanliness, vendor-independence, OOS-window availability, and existing-infrastructure status documented before pre-reg.

**C5. Selectivity profile must match economic claim.** If the claim is "carry works because most of the time funding is positive and persistent," then the engine must be alive most of the time — sparse-event triggers contradict the economic claim. If the claim is "edge exists only in specific market conditions," then those conditions must be observably common enough in the OOS window to produce decision-grade evidence under realistic execution. Either path is valid; their combinations are not (a sparse-event engine claiming continuous-carry economics is the failure mode).

**C6. Realistic execution must be measurable in normal regimes, not only stress regimes.** Per A2 kill action — if your only positive empirical finding is during liquidation events, your execution model is untested where it matters.

**C7. Calibration tampering remains forbidden.** Threshold tuning is not a remediation for a failed strategy. Threshold values may differ in a new engine *because* the new engine has a different hypothesis, not because the threshold was tuned post-hoc to make the existing engine fire.

---

## 6. Open questions for next session

These are real questions, not rhetorical. Each one needs an answer before any new selection memo is drafted.

**Q1.** What is the new engine's *economic claim*? Not the signal, the claim about why edge exists. Possible substrates available given infrastructure: funding rate, basis, futures cash-and-carry (A3), volatility-of-funding, term-structure of funding. The claim must be falsifiable and not a tautology.

**Q2.** What is the engine's expected selectivity profile, and does it match the claim per C5? (Always-on? Episodic? Conditional?)

**Q3.** Does the claim survive Q0 §3.6 data audit before pre-reg? Required documentation per `b315d1e`: data availability over OOS, native cadence, PIT cleanliness, vendor independence, signal-cadence consistency, existing infrastructure check.

**Q4.** Does the claim survive a cheap empirical test of its simplest reduction (per tonight's exploration pattern)? Or does it require building before the smallest test can run?

**Q5.** What's the kill criterion *before* the test runs? Per A2 kill action's re-opening conditions: new pre-registration must include its own kill criteria written before any new run.

**Q6.** Does the new engine reuse only the A1/A2 substrate, or does it need new infrastructure? If new infrastructure, what specifically and why doesn't existing suffice?

**Q7.** What's the realistic distance to paper proof under (a) the new engine's own design, and (b) the master roadmap's existing Sleeve A gates? Reconcile.

**Q8.** Should A1's monitoring-layer deployment per (γ) run *before* the new engine work, in parallel with it, or after? Cheapest answer: in parallel from the start; the monitoring data has no opportunity cost.

---

## 7. What the 12-month plan now actually says

After this reconciliation:

**Phase 1** (current session arc): exploratory loop validated, A1 audit completed, plan reconciled with disk. No further governance.

**Phase 2** (1-3 months target):
- Design the first deployable Sleeve A engine using the substrate
- A1 monitoring deployment in parallel (γ)
- Cheap empirical tests of candidate hypotheses *before* selection memo
- Selection memo → pre-reg → paper run only after empirical evidence justifies
- Target: ONE engine surviving honest gates

**Phase 3** (3-6 months, deferred until at least one engine surfaces from Phase 2): platform layering as previously planned.

**Phase 4** (6-12 months, deferred until at least one engine canary-clears): capital deployment.

The structure of the 12-month plan survives. The "A1 first" assumption is replaced with "fresh Sleeve A engine on A1/A2 substrate."

---

## 8. What this audit does NOT do

Following the Day 20.7 / A2 kill / candidate #5 kill convention of explicit non-claims:

- **Does NOT invalidate the 12-month plan.** The plan's structure is intact. One sentence updates.
- **Does NOT invalidate A1's infrastructure.** A1's 10 substrate components remain in production-quality state.
- **Does NOT promote any engine.** The next Sleeve A engine is undesigned. It does not yet exist.
- **Does NOT amend any pre-registration.** No commit. No governance.
- **Does NOT trigger Sleeve B work.** Sleeve B remains in its current state (5-zero) and is out of scope for this audit.
- **Does NOT define "the new engine."** Section 5 lists constraints; section 6 lists open questions. The actual design is a future session's work.
- **Does NOT promise profit by any specific date.** "Profit soon" is honestly months away under the cleanest path through Phase 2 → Phase 3 → Phase 4 of the 12-month plan; this audit does not change that timeline.

---

## 9. On the "profit soon" pressure

Honest acknowledgement separate from the audit findings.

The plan's earliest plausible path to deployed live capital is months out. Even an optimistic scenario:
- Design + pre-reg: 1-2 weeks
- Paper proof: 2-4 weeks
- Paper gate evaluation: 1-2 weeks
- Q0 + Stage A + Stage B per master roadmap: 2-4 weeks
- Canary (Appendix A minimums: 21 days, 50 leg-pairs, 30 settled funding intervals): 4-12 weeks

Realistic floor: 3-4 months to canary, longer to scale.

This audit does not shorten that. Pressure to shorten it has historically produced the failure modes documented above — calibration tampering, fixture hunting, sparse-event rescue attempts.

If short-term P&L matters strategically, the rational place to look is the existing legacy strategies running behind the firewall (MM, L9 BTC/EBTC per master roadmap v2.2 §7), not the new program. The new program is for sustainable engine production over months and years, not for quarterly returns.

This is an honest acknowledgement, not a recommendation to change the firewall or re-onboard legacy. Just naming the timeline reality so it doesn't create unstated pressure on the new program's gate discipline.

---

## 10. Next session deliverable

**Not** a selection memo for a new Sleeve A engine.

**Not** code.

**Yes:** answer Q1-Q8 from section 6, particularly Q1 (the economic claim) and Q4 (cheapest empirical test before selection memo). Output: a one-page design space note (also `notes/`, not committed) that names 1-3 candidate hypotheses for the next Sleeve A engine, ranks them by cheapness-to-test, and identifies the test for the top one.

If the answer to Q4 is "the cheapest test is a 200-line exploratory script using existing data," then next-next session is writing that script. The pattern from tonight's `explore_stress_state_on_candidate_4.py` is the model.

If the answer to Q1 surfaces that you don't yet have a clear new economic claim, then the honest next move is to pause and figure that out before committing to engineering work. "I don't know yet" is a valid output of that session.

---

*A1 audit complete. Plan reconciled with disk. Substrate preserved. Design constraints captured. Next session opens the design space for the fresh Sleeve A engine without committing to a specific design yet.*
