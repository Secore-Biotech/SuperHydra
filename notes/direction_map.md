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
| Section A — vol-event persistence | Trading | Data-limited | Yes | Yes | §5 window-length axis failed (165d OOS span, 94 train events); event-rate axis passed. Re-run eligible when 2026-05 archive publishes | `2026-05-28-vol-event-persistence-probe-outcome.md` |
| A1 — fixed-threshold funding capture (v1) | Trading | Data-limited | Yes | Yes | §5 event-rate axis failed (0 OOS events at θ=0.0200%); regime had departed before OOS. Not re-run eligible at fixed θ | `2026-06-02-a1-funding-capture-probe-v1-outcome.md` |
| A1 — burst-activation funding capture | Trading | Operationally rejected | Yes | No | Duty cycle 3–7% at locked θ; last burst 2024-12-09, ~540d ongoing dormancy. Economic status UNKNOWN (Q4–Q6 untested) — operational, not economic, reject | `a1_burst_activation_deployability_screen.md` (`e7d0c5c`) |
| Thousand-factor ensemble (QAnalytics/Panton-style) | Trading | Out-of-envelope | No (as posed) | No | Edge, if any, lives in 5,000-factor generation + ensemble + execution/neutralization — the institutional infrastructure `§4` bullet 4 excludes. "Combination of weak signals" is not a falsifiable hypothesis | derived; QAnalytics deck (unvalidated) |
| Legacy MM (old Hydra) | Legacy | Frozen | — | — | +$108 cumulative on record; frozen under old-Hydra plan, behind the roadmap §7 firewall, out of edge-scoping remit | `old_hydra_mm_final_pnl.md`, `old_hydra_freeze_plan.md` |
| Legacy L4/L9/L3/Polymarket strategies | Legacy | Frozen / closed | — | — | Closed or frozen under old-Hydra freeze; not in scope for new-program edge search | `old_hydra_freeze_plan.md` |
| A3 — cash-and-carry | Trading | **Untested** | Yes (if specified) | **TBD — pending §4 screen** | Never honestly tested. Distinct object (locked carry from dated futures/perp structure) IF dated-futures, not perp funding (else it's same-venue basis carry, already killed). Capital efficiency at $50k is the likely binding constraint | roadmap; pending screen |
| Volatility dislocation (vol shock → ?, not persistence) | Trading | **Untested** | TBD | TBD | Genuinely distinct from Section A persistence ONLY if a different measured object, not a longer-horizon view of the same intraday dislocation. Must clear `§6` same-object test before counting as new | roadmap; pending §6 screen |

## What remains in the search space

After the full record, the intersection {not-terminal} ∩ {plausibly falsifiable} ∩ {plausibly in-envelope} contains exactly two candidates, both conditional:

1. **A3 cash-and-carry** — live only if (a) it is dated-futures carry, not perp-funding carry (the latter is `§3.1` same-venue basis carry, already killed), and (b) it survives the `§4` capital-efficiency screen at $50k. Either failure moves it to empirically-killed or out-of-envelope. **Next action if pursued: the §4 paper screen, before any spec.**

2. **Volatility dislocation** — live only if it is a genuinely different measured object from Section A's persistence test, surviving the `§6` same-object screen. If it is "the same statistical object in a longer window," `§6` already kills it. **Next action if pursued: the §6 screen, before any spec.**

Everything else in the new-program tree is terminal. The cross-sectional / market-neutral / factor family (Sleeve B) is the most-explored region of the project, not an open one: five candidates, four distinct failure classes (signal absence, construction fragility, data governance, parameter fragility), all pre-registered and killed. Re-describing that family attractively (e.g. "market-neutral dispersion like QAnalytics") does not move it out of the killed column.

## The earned conclusion

SuperHydra is no longer in idea-generation mode for the new-program tree. It is in idea-validation mode, with at most two conditional candidates left to validate. If both A3 and vol-dislocation fail their screens, the honest outcome is that the next step is not "find another strategy from the existing mechanism set" — it is to find an economic mechanism not already represented anywhere on this map, or to accept that the search space under the current envelope is exhausted. "No attractive next candidate" is a legitimate, earned outcome, and is more valuable than re-litigating a killed direction in fresh language.

## Maintenance

- Every row cites its source record and (where available) commit. Rows are not added or moved on memory — only on a committed record.
- When a screen or probe produces a verdict, the corresponding row's status moves here in the same change that records the verdict, so the map never lags the kill record.
- "Last reviewed" for this index: 2026-06-02. Re-review whenever a direction's status changes or a new candidate is proposed.

— end —
