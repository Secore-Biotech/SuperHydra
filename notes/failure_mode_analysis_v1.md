# Failure-Mode Analysis v1 — DATA_LIMITED vs FAIL across two probe outcomes

**Status:** Analysis note — not a probe spec, not code, not a v2 design. Informs the next probe's pre-lock checklist.
**Author:** Wasseem Katt
**Date:** 2026-06-02
**Implements:** the locked meta-session task — assess H1 and H2 against the two recorded DATA_LIMITED outcomes and produce a note proportional to what two outcomes support.
**Inputs read:** `docs/decisions/2026-05-28-vol-event-persistence-probe-outcome.md` (Section A, in full); `docs/decisions/2026-06-02-a1-funding-capture-probe-v1-outcome.md` (A1 v1, in full); `notes/edge_scoping.md §3.1` (the five empirically-killed scoping entries, in full). The Sleeve B probe-kill corpus (`sleeve_b_*`) was reviewed for contrast but is a distinct set from §3.1 — see §4.

---

## 1. The mechanical distinction (what actually separates DATA_LIMITED from FAIL)

Every probe carries two gates in series: a sample-sufficiency gate (§5) and an edge gate (§6 economic / robustness). The two recorded categories are distinguished by **which gate terminates the probe**, not by how far the probe ran:

- **DATA_LIMITED** = terminated at the **sample-sufficiency gate**. The edge gate never received a statistically valid evaluation. The outcome is a statement about the *data window*, not the *edge*.
- **FAIL** = sample-sufficiency cleared, and the **edge gate** evaluated and rejected. The outcome is a statement about the *edge*.

This is exactly the operator-locked decision rule in the Section A record, read structurally: Branch 1 ("sample sufficiency clears and economics still fail → FAILED") is the FAIL path; Branch 2 ("sample sufficiency still fails → record data-coverage limitation; do not overread economic gate as a kill") is the DATA_LIMITED path. The empirical kills confirm the other side: candidate #4 cleared sufficiency and was killed by the F1.4 robustness sub-gate; candidate #3 was killed by the A2 temporal-stability gate on a sufficient fixture. Those entries reached *terminal edge verdicts* — they did not stop short.

The consequence for both hypotheses below: DATA_LIMITED is not a measure of effort spent or distance travelled. It is a specific failure of the §5 gate to be satisfiable by the available data at the locked event definition.

## 2. The headline finding — the two probes fail on **opposite axes of the same gate**

The §5 gate has two independent inputs: an **event-rate** axis (do enough qualifying events exist in the OOS window?) and a **window-length** axis (is the OOS calendar span long enough?). The two outcomes fail on opposite axes, with the *other* axis passing cleanly:

| Probe | OOS event count | OOS span (days) | Train events | Failing axis |
|---|---|---|---|---|
| **A1 v1** | **0** (floor ≥ 30) — FAIL | 230.7 (floor ≥ 182) — PASS | 349 (floor ≥ 100) — PASS | **event-rate = 0** |
| **Section A** | 37 (floor ≥ 30) — PASS | **165** (floor ≥ 182) — FAIL | **94** (floor ≥ 100) — FAIL | **window too short** |

A1 had ample calendar and a sufficient train sample but the locked threshold (θ = 0.0200%/8h) produced **zero** qualifying events in the OOS regime. Section A had a healthy event *rate* (37 OOS events cleared the floor) but **ran out of calendar** — the 1h series ends at 2026-04-30 because the May 2026 Binance monthly archive had not yet published, leaving the OOS span 17 days short and the train count 6 events short. Section A's own record notes the §5 reasons are identical across all three horizons "because the split parameters depend on calendar span only."

These are orthogonal. A1's failure is invariant to window length (zero events at any span); Section A's failure is invariant to event rate (its rate was fine — it lacked span). Any framing that treats them as one mechanism is collapsing two distinct things.

## 3. Assessment of H1

> H1: both are forms of regime-trapping between train and OOS — a signature of FIXED-parameter probes vs REGIME-ROBUST formulations.

**Verdict: half-right, and the wrong half is load-bearing.**

H1 is correct for A1 and the records back it explicitly: the OOS window is "structurally compressed relative to train," the 0.0200% region is "empty, not thinly populated," and the record names it "a regime statement." A1 is a genuine regime-trap — a hard-coded threshold calibrated on a train regime that had *departed* before OOS began. For A1, H1's implication holds: a regime-conditional or rolling threshold would not have inherited this trap by design.

H1 is **wrong for Section A**. Section A's record is unambiguous that the cause is "a structural data ceiling, not a fetcher defect" — the future archive had not published — and that the re-run is "mechanical" once it does. Nothing about Section A is a regime mismatch: its event rate was adequate, and the *same* threshold on a longer window is expected to clear §5. Section A failed because it was **calibrated to require a window longer than the available history**, not because a regime moved. Calling this "the future hadn't arrived → regime-trapping" stretches the word "regime" past its meaning.

So H1's "fixed vs regime-robust" axis is real, but it is supported by **one** of the two outcomes. Generalizing it to a signature of the category overfits A1's mechanism onto Section A's calendar problem. The honest split: regime-robustness addresses A1's axis (event-rate collapse); it does **nothing** for Section A's axis (insufficient span). A rolling/relative threshold on Section A would still have run out of calendar.

## 4. Assessment of H2

> H2: the two DATA_LIMITED outcomes ran far enough to surface their failure mode while the §3.1 empirically-killed entries failed earlier — so DATA_LIMITED IS the shape of "the discipline worked."

**Verdict: H2 points at a real boundary but misnames its mechanism — twice. The boundary is not depth, and not "the discipline worked." It is *structural vs contingent insufficiency*.**

§3.1 (now read) holds five entries — same-venue basis carry (net edge absent at size), cross-venue basis arb (friction eats the spread), cross-venue dislocation / event-driven basis (tail dislocations sparse and short-lived — "insufficient event frequency"), stablecoin dispersion (sparse, not sustained), and naive funding carry (Sharpe ~10.7 diagnosed as a smooth-cashflow artifact). They are sourced from `exploration_log.md` / `a1_audit_findings.md` / `cross_venue_feasibility.md`, and **none ran the formal §5/§6 machinery** — they are scoping-stage kills, a different set from the Sleeve B probe corpus. (Kickoff says "four"; the file lists five. Immaterial to the assessment.)

**The "failed earlier" premise is literally true but is not the operative distinction.** The §3.1 entries died at the scoping/feasibility stage, before any spec was locked — so on raw depth they did stop short. But depth here is a spectrum, not a binary: §3.1 scoping kills (measurement only) → A1 (spec + pre-build density check, no build) → Section A (spec + full build + run). A1 sits far closer to the §3.1 scoping kills than to Section A. "Ran far" is a property of Section A specifically, not of the DATA_LIMITED *category* — so depth does not cleanly separate the categories.

**The real boundary is a permanence judgment.** Two §3.1 entries — cross-venue dislocation and stablecoin dispersion — fail on the *same axis as A1* (event-rate / frequency insufficiency), yet are classified KILLED, not DATA_LIMITED. The difference is neither axis nor depth: it is whether the insufficiency was judged **structural** or **contingent**. §3.1 treats its sparsity as intrinsic — tail dislocations are inherently rare, the basis is structurally too tight, the spread structurally absent — so the edge is declared not to exist. A1 treats its zero-OOS-event count as **potentially regime-contingent** (train carried ~6% density at θ; the OOS emptiness is, in the record's words, "a regime statement") — without yet establishing whether the emptiness is regime-specific, threshold-specific, or a structural property of elevated funding in mature markets, and Section A treats its shortfall as a **resolvable data ceiling** (the archive will publish). So:

> **DATA_LIMITED** = insufficiency judged *not necessarily permanent*; the kill verdict is withheld because a different window, regime, or formulation might clear it.
> **§3.1 empirical kill** = insufficiency judged *intrinsic to the phenomenon*; the edge is declared absent.

Event-rate insufficiency on its own lands in *either* category. The routing is the permanence call, and it is orthogonal to both depth (how far the probe ran) and cost (when the feasibility check fired).

**H2's spirit survives, relocated twice.** DATA_LIMITED is not "the discipline ran far," and it is not uniformly "the discipline worked" — Section A's discipline worked late and expensively (full build before the span shortfall surfaced; ≈16 commits vs A1's 4). What DATA_LIMITED actually marks is **"a kill was withheld because the insufficiency might be contingent."** The cost-timing story (pre-build vs post-build feasibility check) is a *separate* axis that explains the 4-vs-16-commit differential; it is not what distinguishes the category from §3.1.

**§3.1 also corroborates §1's economic side.** Naive funding carry — high statistical Sharpe killed as a non-deployable cashflow artifact — is exactly a §5-passes / §6-fails kill, and §3.1's own annotation calls it "the canonical example of why §5 separates statistical from economic gates." Same-venue basis carry and cross-venue arb are likewise economic rejections (edge measured, doesn't beat friction). So three of the five §3.1 entries are economic (FAIL-shaped) kills and two are event-rate kills routed away from DATA_LIMITED by the permanence judgment — consistent with the §1 gate-of-termination framing for anything that reaches the gates, and extending it with the contingent/structural axis for things that don't.

## 5. What this earns for the next probe's pre-lock checklist

Two outcomes support exactly **one** durable checklist item, and it generalizes A1's §9 step-2 from an A1-specific step to a universal pre-lock gate:

> **Pre-lock OOS-feasibility check.** Before locking any probe whose event definition includes a hard numerical threshold, run a feasibility pass against the *actual available history*, evaluated **on the OOS partition specifically**, at the locked threshold. It must confirm both axes independently:
> 1. **event-rate axis** — the locked threshold yields ≥ the §5 OOS event floor in the OOS window (catches A1's mode);
> 2. **window-length axis** — available calendar gives ≥ the §5 span floor *and* ≥ the train-count floor, with the train/OOS split applied (catches Section A's mode).
> Run this **pre-build**. If either axis fails, the spec is DATA_LIMITED at the spec layer and no build is authorised.

A1 ran axis 1 and it fired. Neither probe ran axis 2 pre-build, which is why Section A's identical-in-principle failure cost a full build. The checklist item is "run *both* axes, before building" — that is the single thing the cost differential between the two outcomes actually buys.

## 6. What two outcomes do NOT yet support

Honesty cap, so this note isn't over-read later:

- **No conclusion about §5/§6 gate *calibration*.** Both probes were blocked at §5; neither produced a valid §6 read. The thresholds (20 bps mean net, 2.5× cost coverage, the §5 floors themselves) remain untested. The under-sample economic numbers in Section A are directional only, by the locked rule.
- **No claim that regime-robust formulations are categorically safer.** They address one of the two observed axes (event-rate). Section A shows a probe can be DATA_LIMITED with no regime component at all. "Regime-robust" is a fix for A1's class, not a general immunity.
- **No third-category taxonomy beyond what the records already state.** A1's record already distinguishes spec-layer (pre-implementation) from post-implementation DATA_LIMITED. This note adds *why* that distinction tracks cost (feasibility check run before vs after build) and that the two live cases sit on orthogonal §5 axes. It does not claim those are the only two axes a third outcome could occupy.

The signal is two points. The orthogonal-axes observation and the single checklist item are what they cleanly support. A third DATA_LIMITED outcome is the next thing that would either confirm the two-axis decomposition or add a mode it misses — which is the stated reason to write this now, before that third outcome dilutes it.

— end —
