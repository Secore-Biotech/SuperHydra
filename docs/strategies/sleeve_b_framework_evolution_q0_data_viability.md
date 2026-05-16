# Sleeve B framework evolution — Q0 Data Viability Gate

**Status:** Framework evolution memo — binding for candidate #3 onward
**Subordinate to:** `docs/strategies/sleeve_b_research_preregistration.md` (commit `fe909bb`)
**Date:** 2026-05-16
**Origin:** Lessons from candidate #2 kill (`docs/strategies/sleeve_b_quality_kill_action.md`, commit `bf642d1`)

---

## 0. Scope and authority

This memo is a **subordinate framework evolution**, not an amendment.

- It does not modify the master Sleeve B pre-registration at commit `fe909bb`.
- It does not modify the candidate #2 pre-registration at commit `4d307e6`.
- It does not apply retroactively to candidates #1 (xs-momentum) or #2 (fee-yield quality), both of which have already been killed under their own pre-registrations.
- It is binding for Sleeve B candidate selection from candidate #3 onward.

Where this memo is more restrictive than the master, this memo governs for future candidates. Where it is silent, the master governs. The master remains immutable.

This memo is itself subject to anti-cherry-pick discipline. Once committed, it is binding until a successor framework evolution memo is committed under the same discipline. No mid-candidate amendment.

---

## 1. Why this memo exists

Candidate #2 was killed at Stage A Phase 1 because the chosen metric (protocol fee yield) depended on data that was not available point-in-time under operationally feasible conditions. The kill consumed approximately half a day of Sleeve B budget — a clean, cheap, structural failure.

The lesson made explicit by that kill:

> **For systematic crypto research, data integrity is a first-class candidate-selection dimension, not a Phase 1 discovery.**

Candidates that depend on data infrastructure SuperHydra does not have, cannot afford under current economics, or cannot reconstruct honestly should be eliminated **before** signal-family enthusiasm enters the selection process — not after a pre-registration has been written, an inventory document drafted, and a Phase 1 budget partially consumed.

This memo formalises that lesson into a permanent pre-selection screen called **Q0 — Data Viability**.

---

## 2. The Q0 screen — definition

Q0 is a binary gate executed *before* Q1 (metric selection within a candidate family). It asks one question:

> **Can this candidate family be evaluated honestly using currently available PIT-clean data, within the Sleeve B budget, without paid third-party vendor dependence that has not been operator-approved?**

If yes, Q0 passes and the candidate is eligible to enter the standard Q1 → Q2 → Q3 pre-registration drafting flow.

If no, the candidate is **declined at Q0 without pre-registration**. The decline is logged in a one-paragraph candidate-selection memo and the next family is evaluated. No Phase 1 inventory, no Stage A budget consumption, no engineering work.

Q0 is not a Stage A sub-gate. It does not require a pre-registration commit. It is a screening step in the selection process itself, executed by the operator at family-shortlisting time.

---

## 3. Q0 sub-criteria

A candidate family passes Q0 only if **all** of the following are true. Any single failure declines the candidate.

### 3.1 PIT-clean data availability — mandatory

The data required to compute the candidate's primary metric must be available at each rebalance date in the OOS window with **publication-time-correct values** — values that reflect what was known at that historical date, not values that have been retroactively revised.

PIT-clean sources accepted under current infrastructure:

- Binance OHLCV (price, volume) — venue-native, immutable historical
- Binance funding rates — venue-native, immutable historical
- Binance open interest — venue-native, with the standard caveat that OI is reported and can be revised by venue policy
- Direct on-chain reconstruction from immutable block data (ETH, SOL, AVAX, BNB, AVAX) — PIT by construction
- Any source explicitly committed to the repo with verified PIT discipline

PIT-non-clean sources blocked by default:

- DeFiLlama (structurally backfilled per their own documentation, established by candidate #2 inventory)
- Token Terminal public-facing data (not PIT-grade)
- Any aggregator that backfills historical data on adapter or methodology changes
- Any vendor whose API does not expose publication timestamps or as-of metadata

### 3.2 Budget feasibility — mandatory

The data acquisition cost over the full Sleeve B research-to-canary window must fit within SuperHydra's current economic constraints. Specifically:

- No candidate may require paid third-party data subscriptions unless §3.3 conditions are met
- Engineering cost to reconstruct data must fit within the per-candidate budget (master Sleeve B budget minus already-consumed portion, currently ~40 days from 2026-05-16)
- Multi-week reconstruction projects (e.g., adapter replay across hundreds of weeks × dozens of protocols) are out of scope by default

### 3.3 Third-party paid-data exception clause

A candidate that fails §3.1 or §3.2 may still pass Q0 **only if all** of the following are true:

- A specific paid vendor is identified by name and tier
- The all-in cost (subscription + integration effort) is documented in writing
- The operator explicitly approves the spend, logged against §10 of the master roadmap with a written rationale
- The approval references the current state of Sleeve A and Sleeve B: how many engines have reached canary, how much live capital is deployed, and why the proposed data spend is justified by current program economics rather than by candidate enthusiasm

Default: paid PIT-capable data acquisition is **declined**. The exception clause exists for completeness but is not the path of least resistance.

### 3.4 Taxonomy clarity — mandatory

The primary metric must have a single, unambiguous definition that does not require operator-locked taxonomy decisions to specify. Metrics with intrinsic taxonomy ambiguity (e.g., "what counts as protocol fees: MEV tips? LP fees? validator priority?") are declined unless the candidate family has a settled, widely-accepted definition in the literature.

This criterion exists to prevent candidates from passing Q0 nominally while smuggling a Stage A A5 failure into Stage A.

### 3.5 No hidden survivorship dependence — preferred (not mandatory)

The universe and the metric should not implicitly require survivorship-adjusted data. Where survivorship is unavoidable (most crypto universes have survivorship issues), the candidate family must have a path to honest survivorship disclosure consistent with the master pre-registration's frozen-universe approach.

This is preferred rather than mandatory because perfect survivorship-free universes are rare in crypto, but candidates that *worsen* the existing survivorship picture are blocked.

### 3.6 Simple economic story — preferred (not mandatory)

The candidate's edge claim should be expressible in one paragraph against a known mechanism (e.g., funding-rate dynamics, momentum-reversal asymmetry, volatility risk premium, liquidity premium). Complex multi-step economic stories that depend on chained assumptions are deprioritised.

Preferred because some legitimate candidates may have non-trivial stories, but the prior is for simplicity given the program's current maturity.

---

## 4. Q0 pass / fail logic

| Sub-criterion | Status | Effect on Q0 |
|---|---|---|
| §3.1 PIT-clean data | Mandatory | Any failure → Q0 FAIL, candidate declined |
| §3.2 Budget feasibility | Mandatory | Any failure → Q0 FAIL, candidate declined |
| §3.3 Paid-data exception | Conditional | Operator approval required if §3.1 or §3.2 fails on paid-data path |
| §3.4 Taxonomy clarity | Mandatory | Any failure → Q0 FAIL, candidate declined |
| §3.5 Survivorship | Preferred | Failure logged, candidate may still pass with disclosure |
| §3.6 Simple story | Preferred | Failure logged, candidate may still pass with documentation |

**Q0 PASS** → candidate proceeds to Q1 metric-selection conversation.
**Q0 FAIL** → candidate declined with one-paragraph memo. Move to next family.

---

## 5. Q0 output artifact

When Q0 is executed for a candidate family, the operator records a **Q0 verdict line** in the candidate-selection memo for that selection cycle. The line states:

- Candidate family name
- Q0 verdict (PASS / FAIL)
- For each mandatory sub-criterion: state (PASS / FAIL / N/A)
- One-paragraph rationale if FAIL
- If PASS, brief note on which preferred criteria were not met (if any)

The selection memo is committed to `docs/strategies/` before any Q1 work begins. It is not a pre-registration and is not anti-cherry-pick-binding in the same sense — operator may revisit Q0 for the same family later if conditions change (e.g., new data source becomes available, operator approves spend). Revisits must be logged.

---

## 6. Worked example — applying Q0 to the candidate-#2 case

The reviewer-locked candidate-#2 recommendation was fee-yield quality. Applying Q0 retrospectively (for illustration, not as a retroactive judgment):

| Sub-criterion | Verdict |
|---|---|
| §3.1 PIT-clean data | FAIL — primary source (DeFiLlama) is structurally backfilled; alternative (Token Terminal) requires paid subscription |
| §3.2 Budget feasibility | FAIL on the free-data path (reconstruction is multi-week engineering); paid path requires §3.3 |
| §3.3 Paid-data exception | Did not pass — operator declined acquisition in real time |
| §3.4 Taxonomy clarity | FAIL — "fee yield" requires significant taxonomy locking (MEV tips, LP fees, etc.) |
| §3.5 Survivorship | Workable with disclosure |
| §3.6 Simple story | Borderline — defensible but multi-component |

**Q0 verdict (retrospective):** FAIL. Candidate #2 would have been declined at Q0 under this memo, without pre-registration or Phase 1 inventory.

This is the cost-savings illustration: under Q0, candidate #2 would have consumed perhaps an hour of selection-memo time rather than half a day of Phase 1 budget. The kill action document would not have been needed (no kill, just a decline). This is the structural value Q0 adds going forward.

---

## 7. What Q0 does NOT change

- **Stage A and Stage B unchanged.** Candidates that pass Q0 still face the full pre-registered Stage A coverage gate and Stage B performance gate as introduced for candidate #2 and locked in its pre-registration at commit `4d307e6`. Q0 is an additional pre-selection screen, not a replacement for downstream gates.
- **Master pre-registration unchanged.** The master at commit `fe909bb` remains binding. Q0 is subordinate.
- **Retroactive judgments excluded.** Candidates #1 and #2 are closed under their own pre-registrations. This memo does not reopen them or change their kill classifications.
- **Sleeve A unchanged.** Q0 governs Sleeve B candidate selection only. Sleeve A engines (A1 funding-rate, A2 basis, A3 cash-and-carry) operate under the master roadmap's existing structure.
- **Migration work unchanged.** Hydra-next migrations proceed on their own track.

---

## 8. What Q0 protects against

Three failure modes Q0 specifically guards:

**8.1** Spending Phase 1 budget on candidates whose data infrastructure is fundamentally unavailable. Candidate #2 paid this cost in full.

**8.2** Operator enthusiasm for an attractive signal family overriding economic discipline on data spend. The §3.3 exception clause exists but is deliberately friction-loaded.

**8.3** Drift toward "approximately-honest" PIT reconstruction. Q0 blocks candidates that would force the program into sparse Wayback snapshots, partial adapter replays, or other reconstruction paths that degrade decision-grade evidence.

---

## 9. Working candidate-#3 prior under Q0

For the next candidate-selection session, the reviewer-locked working prior is:

> Risk-adjusted momentum / low-volatility hybrid, evaluated under Q0 before Q1.

This prior is subject to confirmation by Q0:

| Sub-criterion | Expected verdict |
|---|---|
| §3.1 PIT-clean | PASS — Binance OHLCV is venue-native PIT-clean |
| §3.2 Budget | PASS — uses existing data infrastructure, no acquisition cost |
| §3.3 Paid exception | N/A — not invoked |
| §3.4 Taxonomy | PASS — momentum and volatility are settled definitions |
| §3.5 Survivorship | PASS — uses frozen top-30 universe per master pre-registration |
| §3.6 Simple story | PASS — addresses xs-momentum's failure mode with a known construction technique |

Expected Q0 verdict: **PASS**. Subject to operator confirmation at candidate-#3 opening time. The Q0 verdict line for candidate #3 must be committed before Q1 metric-selection conversation begins.

If Q0 surfaces something unexpected (e.g., the hybrid construction turns out to require non-OHLCV data), the candidate is declined and the next family is evaluated. Same as candidate #2's structural lesson: signal enthusiasm does not override data discipline.

---

## 10. Future amendments

This memo is binding for candidate #3 onward. It may be superseded by a future framework evolution memo only under the same discipline that produced this one: a separate document, subordinate to the master, committed before the candidate it governs, with explicit non-retroactive scope.

No in-place amendments. No silent reinterpretation. If Q0 needs to change, it changes via a successor memo.

---

## 11. References

- Master Sleeve B pre-registration: `docs/strategies/sleeve_b_research_preregistration.md` (commit `fe909bb`)
- Candidate #2 pre-registration: `docs/strategies/sleeve_b_quality_preregistration.md` (commit `4d307e6`)
- Candidate #2 Phase 1 inventory: `docs/strategies/sleeve_b_quality_stage_a_data_inventory.md` (commit `a61dbc7`)
- Candidate #2 kill action: `docs/strategies/sleeve_b_quality_kill_action.md` (commit `bf642d1`)
- Candidate #1 kill action: `docs/strategies/sleeve_b_xs_momentum_kill_action.md` (commit `f3e078e`)
- Master roadmap §10 (operator authority): governing document for any §3.3 exception approvals

---

*Q0 Data Viability Gate framework evolution memo. Binding for Sleeve B candidate #3 onward. Subordinate to master pre-registration at `fe909bb`. Non-retroactive. Lessons from candidate #2 made permanent without amending immutable governance.*
