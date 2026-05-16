# Sleeve B Candidate #2 — Kill action

**Candidate:** Revenue-bearing quality (fee-yield)
**Kill date:** 2026-05-16
**Stage at kill:** Stage A, Phase 1
**Kill mode:** Metric-definition kill (data access)
**Killing gate:** A4 — point-in-time discipline unavailable
**Subordinate to:** `docs/strategies/sleeve_b_quality_preregistration.md` (commit `4d307e6`)
**Phase 1 inventory:** `docs/strategies/sleeve_b_quality_stage_a_data_inventory.md` (commit `a61dbc7`)

---

## 0. Summary

Candidate #2 is formally shelved at Stage A, Phase 1, before any return computation, eligible-universe construction, or signal evaluation. The candidate did not fail on Sharpe, drawdown, breadth, or signal quality. It failed on the structural unavailability of point-in-time fee data for the OOS window 2023-04-15 → 2026-04-15 under operationally feasible conditions.

This is the third Sleeve B / A-Sleeve kill executed under pre-registered governance:

| Sleeve | Stage of kill | Kill mode |
|---|---|---|
| A2 (perp-vs-spot basis) | Paper (commit `924a930`) | Signal absence — zero entries |
| Sleeve B candidate #1 (xs-momentum) | OOS backtest (commit `f3e078e`) | Construction fragility — DD 25.92% > 25% |
| Sleeve B candidate #2 (fee-yield quality) | Stage A Phase 1 (this kill) | Metric-definition kill — A4 PIT unavailable |

Each kill was at a different stage of the pipeline. Each was caught before the next failure mode could compound. This is the framework operating as designed.

---

## 1. Sequence of evidence

The kill rests on a chain of findings established during Phase 1 recon, all documented in the inventory at commit `a61dbc7`:

**1.1** Token Terminal access state confirmed by operator as Q1 = (a): no subscription, no API key, public web data only.

**1.2** TT public-facing data is not PIT-grade, is rate-limited, and is incompatible with the OOS window coverage requirement. TT cannot serve as a Stage A primary source under current access state.

**1.3** A3 was reformulated under reviewer ruling as a forced substitution (DeFiLlama vs on-chain spot-check on ETH/SOL/AVAX), with explicit asymmetry disclosure. The reformulation was locked in the Phase 1 inventory and is not in itself the cause of this kill.

**1.4** DeFiLlama recon established that historical fee data is **structurally backfilled by design**, confirmed by three independent statements in DeFiLlama's own documentation:
- *"Historical Data Integrity: When protocols add new components (like treasury wallets, new contracts, etc.), we backfill historical data to maintain completeness and accuracy."*
- *"Methodology Consistency: ... Whenever the methodology evolves, our team propagates the update to every relevant adapter."*
- SDK adapter spec: `timetravel (bool [default: true]) — if we can backfill data with your adapter.`

**1.5** DeFiLlama exposes no publication timestamps or as-of metadata via its API. Values returned today for date T are not the values that were published at date T.

**1.6** PIT reconstruction paths evaluated and rejected:
- Adapter replay from DefiLlama-Adapters GitHub history: ~4,700 historical executions required across 30 protocols × 157 weekly rebalance dates, plus methodology-version awareness; multi-week engineering work that exceeds Stage A budget by an order of magnitude.
- Wayback Machine snapshots: capture aggregator-view HTML only, not protocol-level API responses; even with full snapshot density, reconstruction would yield aggregator-grade data, not protocol-level rebalance-date series; cannot support per-protocol fee yield computation at the required granularity.
- The reviewer ruling explicitly declined to spend Phase 1 budget on Wayback probing on grounds that even successful probing would only enable Stage B as non-decision-grade exploratory.

**1.7** Paid PIT-capable data acquisition (Token Terminal Pro / API, Artemis, Messari Enterprise) is the only path to restore A4 PASS_CLEAN. Estimated cost band: $500–$2,000 per month depending on vendor and tier.

**1.8** Operator decision: **decline paid PIT-capable data acquisition for candidate #2.** Rationale documented in §3 below.

---

## 2. Stage A verdict

Per the pre-registration at commit `4d307e6`:

> **A4 — Point-in-time discipline:** Unavailable / no reproducible publication snapshots → FAIL, shelve.

**Verdict: Stage A FAIL via A4.**

A4 alone is sufficient to fail Stage A under the pre-registered verdict logic. Sub-gates A1, A2, A3, A5 were not computed and are not required for the kill. The pre-registration explicitly states that any single sub-gate FAIL triggers shelve without further sub-gate evaluation.

This is a clean pre-registered kill. No anti-cherry-pick concern. No mid-window threshold adjustment. No retroactive interpretation. A4 was specified as the strictest gate in §3.A4 of the pre-registration, and A4 failed for exactly the reason §3.A4 anticipated: backfilled aggregator data with no reproducible publication-date snapshots and no operator approval to acquire PIT-capable alternatives.

---

## 3. Operator rationale for declining acquisition

Decision logged against §10 of the master roadmap (operational authority).

Five factors:

**3.1 The framework is operating as designed.** Stage A's purpose is to surface candidates that cannot produce decision-grade evidence under available infrastructure, *before* engineering time and backtest cycles are spent. Killing here is the framework succeeding, not failing.

**3.2 Economic sequencing.** SuperHydra has zero live capital deployed, zero canary-ready engines, no Sleeve A engine surviving to paper, and one Sleeve B candidate already killed. Acquiring a $500–$2,000/month data subscription before any candidate has earned its way to canary inverts the cost discipline of the master roadmap. Infrastructure cost should follow proven edge, not precede it.

**3.3 The data-dependency itself is candidate weakness.** A candidate family that cannot produce honest evidence under operationally feasible conditions is *itself* a weaker candidate, independent of any signal it might generate. This is a structural property of the family, not a circumstantial obstacle.

**3.4 Reconstruction-path slippery slope.** Allowing "DeFiLlama + partial Wayback" as a bridge would silently degrade Stage A from decision-grade to approximately-honest. That degradation is precisely the failure mode anti-cherry-pick discipline is built to prevent. The honest call is to fail Stage A cleanly rather than build a fragile workaround.

**3.5 Opportunity cost.** ~38 days of Sleeve B research budget remain. Spending 1–2 more weeks plus subscription cost plus integration effort on a candidate that has not cleared Stage A is poor capital allocation when other candidate families may not have the PIT dependency at all.

---

## 4. What this kill does NOT establish

**It does NOT establish that fee-yield is a poor signal in crypto.** The candidate may have edge or may not. Stage A failure is silent on signal quality. The kill is purely about data infrastructure feasibility.

**It does NOT establish that DeFiLlama is unsuitable for all research.** DeFiLlama is operationally fine for current-state and forward-looking analysis. The unsuitability is specific to PIT-grade historical reconstruction over a multi-year OOS window for a cross-sectional rank factor.

**It does NOT close the door on fee-yield as a future candidate.** If SuperHydra economics later justify paid PIT-capable data acquisition (e.g., after Sleeve A reaches canary and capital deployment generates infrastructure budget), fee-yield can be re-evaluated as a fresh candidate against a fresh pre-registration. Past kill does not bypass future gates; future candidate would face the same Appendix B / Stage A / Stage B structure unmodified.

**It does NOT amend the master Sleeve B pre-registration at commit `fe909bb`.** The master remains binding. Candidate #2's pre-registration at commit `4d307e6` remains binding as the historical record. This kill action is the close of candidate #2 under those rules, not a revision of them.

---

## 5. Budget accounting

| Item | Budget | Consumed | Result |
|---|---|---|---|
| Phase 1 (recon) | 2 days | ~0.5 days | Underrun |
| Stage A total | 10 days | ~0.5 days | Underrun |
| Candidate #2 total | 41 days | ~0.5 days | ~40.5 days returned to Sleeve B |
| Master Sleeve B budget | Per `fe909bb`, default kill date 2026-06-27 | Roughly half of one day consumed | Substantively intact |

The Stage A two-stage design returned ~98% of candidate #2's budget to the program by failing at metric-definition rather than at performance. This is the structural value of the gate sequencing introduced for candidate #2 — failure was made cheap.

---

## 6. Strategic finding

The most important lesson from this candidate is not about fee-yield specifically. It is about the binding constraint of systematic crypto research:

> **For some candidate families, the bottleneck is not edge — it is data integrity.**

This is a recurring institutional lesson in quantitative research. The framework surfaced it at the cheapest possible stage, before any signal computation, before any infrastructure build, before any engineering commitment beyond a single inventory document.

That recognition is the deliverable of this kill, alongside the formal close-out of the candidate.

---

## 7. Next actions

**7.1** Commit this kill action document to the repo.

**7.2** Stop all candidate #2 work. No further Phase 2 / Stage B / paper / canary activity is authorised against this candidate.

**7.3** Re-open candidate-family selection for Sleeve B #3 in a separate session. Selection should:
- Revisit the original comparative pass that ranked quality #2
- Filter explicitly for data-access feasibility under current infrastructure (Binance / CCXT / on-chain reconstruction without paid subscriptions)
- Treat data-PIT availability as a Stage A precondition assessed *before* family selection is finalized, not after
- Re-rank candidates with PIT-availability as a first-class criterion

**7.4** No part of this kill action modifies migration work (hydra-next), legacy strategy operation, or Sleeve A development. Those proceed unchanged.

---

## 8. References

- Master Sleeve B pre-registration: `docs/strategies/sleeve_b_research_preregistration.md` (commit `fe909bb`)
- Candidate #2 pre-registration: `docs/strategies/sleeve_b_quality_preregistration.md` (commit `4d307e6`)
- Phase 1 data inventory: `docs/strategies/sleeve_b_quality_stage_a_data_inventory.md` (commit `a61dbc7`)
- Prior kill actions: `docs/strategies/sleeve_b_xs_momentum_kill_action.md` (commit `f3e078e`)
- Master roadmap §10 (operator authority): governing document for the decline-acquisition decision logged in §3 above

---

*Kill action document for Sleeve B candidate #2 — revenue-bearing quality (fee-yield). Stage A FAIL via A4 (point-in-time discipline unavailable). Operator declined paid PIT-capable data acquisition. Logged against §10 of the master roadmap. Sleeve B research budget substantively preserved for candidate #3.*
