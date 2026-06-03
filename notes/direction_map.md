# SuperHydra — Direction Map (standing index)

**Status:** Living index. Not a decision artifact for a single session — the standing record every candidate direction is checked against *before* it earns a screen or a spec.
**Author:** Wasseem Katt
**Date:** 2026-06-02
**Purpose:** The project's demonstrated failure mode is forgetting what was already tested — the funding-simulator supersession, the migration recon, and the QAnalytics drift toward reopening Sleeve B all share it. This map exists so that "is this direction new?" is answered by lookup, not memory. A direction described in fresh language is not a new direction; check it here first.

## How to use this map

Before opening any screen, spec, or build for a direction, find it (or its nearest relative) below. A direction is genuinely available for research **only if all three hold**:

1. it is not already in a terminal status (empirically killed / operationally rejected / structurally closed / out-of-envelope);
2. it can be stated as a **falsifiable hypothesis** (a specific construction with a pre-registrable kill criterion — not "some combination of weak signals in portfolio form", which is unfalsifiable and therefore not a hypothesis);
3. it is **in-envelope** under `edge_scoping.md §4` (operable under the $50k ceiling, solo-operator time budget, and existing infrastructure — no net-new institutional-grade infrastructure).

The intersection of {not-terminal} ∩ {falsifiable} ∩ {in-envelope} is the actual search space. As of this writing it is short.

## Status taxonomy (four terminal + two live)

- **Empirically killed** — evidence says edge not present or economics fail. Not to retest (the *specification* may be re-pre-registered, but the finding stands).
- **Operationally rejected** — may have edge; cannot be deployed under this program's envelope. Re-test eligible only if the *envelope* changes, not the data.
- **Data-limited** — unable to reach a valid verdict; retest-eligible when the data ceiling lifts (this is `edge_scoping.md §3.3`).
- **Structurally closed** — closed by setup; do not retest (`edge_scoping.md §3.2`).
- **Out-of-envelope** — may work; requires infrastructure or scale `§4` excludes. Not a kill; a scope boundary.
- **Untested** — no terminal verdict; live only if falsifiable AND in-envelope.

## The map

| Direction | Class | Status | Falsifiable hypothesis? | In-envelope? | Why | Source (commit) |
|---|---|---|---|---|---|---|
| Same-venue basis carry (Binance perp/spot) | Trading | Empirically killed | Yes | Yes | ~3.2% gross annualised; net deployable edge absent at size after friction | `edge_scoping.md §3.1` (exploration_log) |
| Cross-venue basis arbitrage | Trading | Empirically killed | Yes | Yes | No materially wider spread vs same-venue; latency/transfer friction eats it | `edge_scoping.md §3.1` (cross_venue_feasibility) |
| Cross-venue dislocation / event-driven basis | Trading | Empirically killed | Yes | Yes | Tail dislocations sparse and short-lived; insufficient event frequency (structural) | `edge_scoping.md §3.1` |
| Stablecoin dispersion (USDT/USD, Coinbase) | Trading | Empirically killed | Yes | Yes | Sparse, not a sustained phenomenon at this friction | `edge_scoping.md §3.1` |
| Naive funding carry | Trading | Empirically killed | Yes | Yes | High Sharpe (~10.7) diagnosed as smooth-cashflow artifact; economic gate fail | `edge_scoping.md §3.1` (a1_audit) |
| A2 perp-vs-spot basis | Trading | Empirically killed | Yes | Yes | Step-3 normal regime = 0 entries; stress positives depend on liquidation windows where execution is unmeasured/unviable | `a2_kill_action.md` (`924a930`) |
| Sleeve B #1 — cross-sectional momentum | Trading | Empirically killed | Yes | Yes | Signal-positive (Sharpe 1.38) but failed pre-registered 25% drawdown gate (25.92%); construction fragility | `sleeve_b_xs_momentum_kill_action.md` (`f3e078e`) |
| Sleeve B #2 — fee-yield quality | Trading | Empirically killed | Yes | Yes | Killed Stage A on data governance: point-in-time fee data structurally unavailable (DeFiLlama backfills); PIT reconstruction out of budget | `sleeve_b_quality_kill_action.md` (`bf642d1`) |
| Sleeve B #3 — vol-scaled momentum (v1) | Trading | Empirically killed | Yes | Yes | Killed Stage A pre-computation: frozen-universe construction incompatible with A2 temporal-stability gate (spread 14 > 6) | `sleeve_b_candidate_3_kill_action.md` (`bf0a23e`) |
| Sleeve B #4 — vol-scaled momentum (v2) | Trading | Empirically killed | Yes | Yes | Cleared 6/9 gates; killed on F1.4 window-sensitivity (0.711 > 0.30) + B3 — parameter-fragile momentum×vol interaction, not robust | `sleeve_b_candidate_4_kill_action.md` (`59c1156`) |
| Sleeve B #5 — joint funding/OI/basis regime detector | Trading | Empirically killed (governance) | Partially | Yes | Shelved pre-D1: six governance artifacts, zero engineering; Amendment #2 factually wrong (OI is 5-min not daily). Intuition not killed; this spec is | `sleeve_b_candidate_5_kill_action.md` (`fe34b76`) |
| Section A — vol-event persistence | Trading | Data-limited (structural event sparsity), terminal under v1 | Yes | Yes | §5 fails on event sparsity, not coverage: σ-P95 yields 131 events over 1156d; 2026-05 archive added zero events; train 94<100, OOS event-span 165<182 unchanged after rerun. Re-test needs a v2 spec (different event definition), not a rerun | `2026-06-03-section-a-rerun-outcome.md` (`060b84c`) |
| A1 — fixed-threshold funding capture (v1) | Trading | Data-limited | Yes | Yes | §5 event-rate axis failed (0 OOS events at θ=0.0200%); regime had departed before OOS. Not re-run eligible at fixed θ | `2026-06-02-a1-funding-capture-probe-v1-outcome.md` |
| A1 — burst-activation funding capture | Trading | Operationally rejected | Yes | No | Duty cycle 3–7% at locked θ; last burst 2024-12-09, ~540d ongoing dormancy. Economic status UNKNOWN (Q4–Q6 untested) — operational, not economic, reject | `a1_burst_activation_deployability_screen.md` (`e7d0c5c`) |
| Combination-portfolio (Sleeve B rescue-by-assembly) | Trading | Closed (eligibility) | Yes (object novel, §6 pass) | Yes in shape (§4 pass) — but no constituents | Object is genuinely novel and shape is in-envelope, but zero eligible constituents: every Sleeve B signal died from an upstream defect (bias #1 / fragility #4 / governance #2,#5 / invalid construction #3) that portfolio construction inherits, not repairs. Re-eligible only if clean robust signals are generated first (separate project) | `combination_portfolio_screen.md` |
| Thousand-factor ensemble (QAnalytics/Panton-style) | Trading | Out-of-envelope | No (as posed) | No | Edge, if any, lives in 5,000-factor generation + ensemble + execution/neutralization — the institutional infrastructure `§4` bullet 4 excludes. "Combination of weak signals" is not a falsifiable hypothesis | derived; QAnalytics deck (unvalidated) |
| Legacy MM (old Hydra) | Legacy | Frozen | — | — | +$108 cumulative on record; frozen under old-Hydra plan, behind the roadmap §7 firewall, out of edge-scoping remit | `old_hydra_mm_final_pnl.md`, `old_hydra_freeze_plan.md` |
| Legacy L4/L9/L3/Polymarket strategies | Legacy | Frozen / closed | — | — | Closed or frozen under old-Hydra freeze; not in scope for new-program edge search | `old_hydra_freeze_plan.md` |
| A3 — dated-futures cash-and-carry | Trading | Out-of-envelope (infrastructure), conditional | Yes (defined as A3b) | No — requires Deribit/CME onboarding not in substrate | Roadmap §3.1.3 defines it (BTC futures vs spot); deferred behind futures-venue onboarding; promotion gate "A1+A2 at scale" now unreachable (A1 op-rejected, A2 killed). Economics UNTESTED — scope block, not edge verdict | `a3_definition.md` (`6f72ebc`) |
| Volatility dislocation → liquidity recovery / spread compression | Trading | Provisional FAIL (§4 bullet 5) | Yes (object); no deployable shape | No deployable shape in-envelope | Survives §6 as distinct object, but every deployment shape is excluded (market-making), non-standalone (execution overlay), or already-killed (basis/MR/vol-persistence). Pending operator naming a shape outside those | `vol_dislocation_liquidity_recovery_s4_screen.md` (`3c7c8f4`) |

## What remains in the search space

As of `6f72ebc` / `3c7c8f4`, both previously conditional candidates have resolved:

- **A3** is defined as dated-futures cash-and-carry and is classified as **Out-of-envelope (infrastructure), conditional**. It is not eligible for a normal §4 screen unless the program first makes a standalone decision to fund Deribit/CME-style dated-futures onboarding. Its economics remain untested; this is a scope/infrastructure block, not an edge verdict.
- **Volatility dislocation → liquidity recovery / spread compression** survives the §6 same-object test but currently has **no deployable in-envelope position shape**. It is therefore **Provisional FAIL (§4 bullet 5)** unless the operator names a deployment shape outside the excluded A–D cases.
- **Section A** has resolved: the 2026-05 archive published, the rerun executed (`060b84c`), and §5 still fails — the binding constraint is structural event sparsity, not coverage. **Terminal under v1**; re-test requires a v2 spec with a different event definition, which is a fresh pre-lock decision, not a rerun.

Therefore, the live search space contains no immediately screen-ready candidate. Any next candidate must either:
1. resolve one of the pending strategic decisions above, or
2. introduce a genuinely new, falsifiable, in-envelope economic mechanism not already represented in this map.

## The earned conclusion

SuperHydra is no longer in idea-generation mode for the new-program tree, and as of this reconciliation it is past idea-validation too: both conditional candidates have resolved. A3 is out-of-envelope behind futures-venue infrastructure whose promotion gate (A1+A2 at scale) is now unreachable; vol-dislocation is a provisional §4 FAIL with no deployable in-envelope shape. Section A has now also resolved: the rerun executed against the published 2026-05 archive and §5 still failed on structural event sparsity (not coverage), making it terminal under v1. All three threads are closed.

Everything else in the tree is terminal. The cross-sectional / market-neutral / factor family (Sleeve B) is the most-explored region of the project, not an open one: five candidates, four distinct failure classes, all pre-registered and killed. Re-describing that family attractively (e.g. "market-neutral dispersion like QAnalytics") does not move it out of the killed column.

So the live search space contains no immediately screen-ready candidate. Pending Section A's rerun verdict, the next step is not "find another strategy from the existing mechanism set" — it is to find a genuinely new, falsifiable, in-envelope economic mechanism not already on this map, or to accept that the search space under the current envelope is exhausted. "No attractive next candidate" is a legitimate, earned outcome, more valuable than re-litigating a killed direction in fresh language.

## Maintenance

- Every row cites its source record and (where available) commit. Rows are not added or moved on memory — only on a committed record.
- When a screen or probe produces a verdict, the corresponding row's status moves here in the same change that records the verdict, so the map never lags the kill record.
- "Last reviewed" for this index: 2026-06-02. Re-review whenever a direction's status changes or a new candidate is proposed.

— end —
