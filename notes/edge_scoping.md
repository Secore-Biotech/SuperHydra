# notes/edge_scoping.md

*Search-space filter for SuperHydra research directions. Draft v0.2.*

---

## 0. What this document is — and is not

**Is:** a search-space filter, applied *upstream* of any research effort. It constrains which edge classes are worth probing at all, given the operator and infrastructure reality of this setup.

**Is not:** governance, a promotion gate, or a strategy proposal. Roadmap v2.2 remains authoritative for promotion (Appendix B research-to-paper, Appendix A paper-to-canary). This document determines what gets *to* Appendix B in the first place.

A direction can fail this filter even if it would hypothetically clear Appendix B. That is the point.

---

## 1. Central filter

The setup is **non-institutional infrastructure operated by a single senior engineer**. The exploration loop (2024–2025, see `notes/exploration_log.md`) repeatedly tested institutional / HFT / MM-style edges and the empirical loop did *not* fail — it correctly identified those as the wrong game for this setup.

An edge class is **structurally closed to this setup** if its plausible alpha requires any of:

- Co-location, dedicated network, or sub-100ms decision latency
- Maker rebate harvesting that depends on entity-tier fee schedules
- Prime-brokered capital cost or balance-sheet financing
- Regulatory or jurisdictional arbitrage requiring entity scale
- Continuous two-sided quoting infrastructure at MM operational depth
- Direct competition with desks whose edge is structurally *their cost basis*, not their alpha

This is not a claim that edges don't exist in those spaces. It is a claim that they don't exist *for this setup*. Stop retesting them.

---

## 2. Operator constraints (load-bearing)

These are not soft preferences. They define what "structurally plausible" means in this document. Values below are operator-authored and bind the filter operationally. They are not aspirational — they are the numbers that would still be endorsed after a bad month.

| Constraint | Value |
|---|---|
| Weekly research / build time (sustained, not peak) | 30+ hrs/week |
| Research runway before deployment contact must occur | 2 months to P1 entry: first paper trade on production OMS/risk/ledger path |
| Drawdown tolerance on program capital | 10% / $5,000 on $50k ceiling |
| Engineering depth | Senior-engineer-grade — architecture, debugging, infra, deployment, plumbing |
| Quant depth | Non-specialist — assume no edge against career quants on alpha modelling |
| Deployable capital ceiling | $50,000 (roadmap v2.2 §6) |
| Initial canary size per engine | $500–$2,000 (roadmap v2.2 §6) |

The engineering-vs-quant asymmetry is the most important line in this table. A direction whose edge *requires* specialist quant depth to defend is closed regardless of how interesting it looks; a direction whose edge benefits from disciplined engineering and plumbing is *open territory* relative to this setup.

### 2.1 Runway expiry fallback

If 2 months elapse with no Section A probe having cleared Appendix B and no engine entering P1 paper on the production OMS/risk/ledger path, the runway has expired.

At expiry, operator must take one of:

1. **Filter re-derivation.** Section A is closed, new structural closures are appended to §3.2, and this document moves to v0.3.

2. **Legacy re-onboarding as deployment-contact source.** Port L4 V3, MM, or another legacy engine onto the new stack as the first canary-track engine. This requires a separate roadmap v2.2 §7.2 amendment because current §7.2 forbids re-onboarding before Sleeve A canary clearance.

3. **Logged runway extension.** Maximum one additional month. Must be logged in roadmap §10 with candidate state at expiry, reason for extension, new expiry date, and what would change the decision.

The runway is a forcing function. It produces a logged decision at expiry. It does not magically produce engines.

---

## 3. Structurally closed — negative space

### 3.1 Empirically weakened or killed (measured, not assumed)

Source: `notes/exploration_log.md`, `notes/a1_audit_findings.md`, `notes/cross_venue_feasibility.md`.

- **Same-venue basis carry (Binance perp/spot).** Structurally tight, ~±2–5 bps typical. Hedged carry ~3.2% gross annualised before realistic friction. Net deployable edge does not exist at this size.
- **Cross-venue basis arbitrage.** No materially wider spread observed vs same-venue. Latency/transfer friction eats the difference.
- **Cross-venue dislocation density / event-driven basis.** Tail dislocations are sparse and short-lived. Insufficient event frequency to constitute a sleeve.
- **Stablecoin dispersion (USDT/USD on Coinbase).** Sparse. Not a sustained phenomenon at this setup's friction.
- **Naive funding carry.** High measured Sharpe (~10.7) diagnosed as smooth-cashflow artifact, not deployable edge. **This is the canonical example of why §5 separates statistical from economic gates.**

### 3.2 Structurally closed by setup (do not retest)

- Latency-bound microstructure
- HFT signal extraction
- Maker rebate harvesting requiring tier-grade fee schedule
- Continuous two-sided quoting at MM operational depth
- Any direction whose realistic friction floor exceeds plausible edge density at retail-tier costs
- Any direction requiring entity-scale rate negotiation, OTC access, or balance-sheet financing
- Any direction whose minimum viable capital exceeds the $50k ceiling
- Any direction whose edge persistence is shorter than the setup's realistic decision-to-fill cycle time

---

### 3.3 Data-limited / unresolved (probed, sample-short or coverage-blocked)

Probes that ran end-to-end on the production code path with clean data hygiene, but did **not** clear the sample-sufficiency thresholds locked in §5 of their respective probe specs. Per the operator-locked decision rule for under-sample probes, the economic gate is NOT overread as a formal kill, even when the under-sample evidence is directionally unfavorable. These probes stay in research; they do not advance to promotion, and they are not pre-registered as killed. They become eligible for re-run when the data ceiling that limited them is lifted, with the decision-rule branch for each outcome pre-specified before re-run.

This category is deliberately distinct from §3.1 (empirically killed) and §3.2 (structurally closed by setup). An entry here is **inconclusive**, not closed. The distinction matters because §3.1 / §3.2 entries are pre-registered as not-to-retest, whereas §3.3 entries are explicitly retest-eligible under the originating spec when data permits.

**Entries:**

- **Vol-event persistence (BTCUSDT/ETHUSDT, 24h σ → 1/3/7-day directional).** Probe outcome: data-coverage limited; persistence hypothesis directionally disfavored, formal verdict inconclusive. Sample sufficiency short by 6 train events and 17 OOS days on the locked 80/20 calendar split; data ceiling at 2026-04-30 (Binance's published monthly archive horizon at run time). Economic gate FAIL under-sample on all three horizons (mean net −62 to −106 bps, win rate 38–41%, cost coverage negative). Direction is informative for future scoping but does not authorise reversal or any spec rescue in this entry, per probe spec §8 non-precedent rule. Full record: `docs/decisions/2026-05-28-vol-event-persistence-probe-outcome.md`. **UPDATE 2026-06-03 (`060b84c`):** archive published; rerun executed; §5 still fails on structural event sparsity (131 events over 1156d, May added zero), not coverage. Section A is **terminal under v1** — not re-runnable. Re-test requires a v2 spec with a different event definition. See `docs/decisions/2026-06-03-section-a-rerun-outcome.md`.

- **A1 funding-capture v1 (BTCUSDT/ETHUSDT, fixed θ=0.0200%/8h, long-spot + short-perp, positive-funding only).** Probe outcome: data-limited at the spec layer; verdict locked before any probe code was written. The §9 step 2 OOS sample-sufficiency check at the locked θ produced 0 OOS events on both BTCUSDT and ETHUSDT across a 230.7-day OOS window (2025-10-09 → 2026-05-28). The funding distribution in the OOS window is structurally compressed relative to train: the 0.0200% region is empty in recent data, not thinly populated. Per spec §8, θ is immutable in v1; per §7.4, all three horizons (1, 3, 7 funding intervals) return `DATA_LIMITED` since the trigger fires zero times in OOS regardless of horizon. No probe implementation was built — no spot-kline exporter, no `strategies/funding_capture/` modules, no carry-forward technical debt. Full record: `docs/decisions/2026-06-02-a1-funding-capture-probe-v1-outcome.md`. **Re-run eligibility differs from the Section A entry:** A1 v1 is *not* re-run-eligible when more data arrives. The data exists; the *regime* produces no events at the locked θ. Resolving this requires a v2 spec with a different event definition (lower θ, regime-conditional θ, or a different hypothesis class), not more data.

## 4. Structurally plausible — open space

A direction is plausibly open *only if all of the following hold*:

1. **Frequency compatibility.** Decisioning operates at minutes-to-days, not microseconds-to-seconds.
2. **Measured object is not in §3.** Not a known-weakened phenomenon, and not a known-closed class.
3. **Capital / fee / financing reachability.** Edge does not require capital scale, fee tier, or financing terms the setup cannot reach.
4. **Implementation footprint.** Fits within the existing migration stack (0001–0011) without requiring net-new institutional-grade infrastructure. New migrations are acceptable; new categories of infrastructure (e.g. co-location, dedicated dark-fibre, prime-broker integration) are not.
5. **Deployment shape is operationalisable.** Operationalisable means:
   - executable within the actual weekly time budget in §2,
   - survivable without routine human intervention outside the actual sustained time budget in §2,
   - and deployable under the $50k capital ceiling without hidden infrastructure assumptions (e.g. multiple new exchange accounts, overnight human monitoring, bespoke ops tooling).

Bullet 5 is the one most often skipped. A direction whose successful version *still cannot be operationalised* under the program's capital, time, and infrastructure envelope is not "open" — it is research entertainment. Probes whose success state has no deployment shape are filtered out before execution.

---

## 5. Probe specification — must be pre-locked before any code is written

Every probe must specify, in writing, before execution:

- **Measured object.** Exactly what phenomenon is being measured. Not a vague theme.
- **Holding window.** The time horizon a hypothetical trade would be in the market.
- **Cost assumptions.** Calibrated to operator-tier friction (fees, slippage, transfer cost, funding cost). Not modelled friction. Not "TBD".
- **Statistical gate.** Significance threshold, sample size, OOS window per Appendix B §B.2.
- **Economic gate.** Does the result survive realistic friction with positive net economics? Separate from Sharpe — see hedged-carry lesson in §3.1.
- **Expected deployment shape.** If results clear both gates, what does the deployed strategy look like under §4 bullet 5? If the answer is "we'd figure that out later," the probe is not yet ready to run.

**A statistically strong result that fails the economic gate is treated as a failed probe.** The project has already produced extremely strong statistical-looking artifacts that were economically fake; this is not a hypothetical risk.

A probe missing any of the above is not executed.

---

## 6. Section A — slower structural-flow effects (the live open question)

Section A is the currently live candidate open direction. It remains open **only if the measured object changes** relative to the directions already killed in §3.1. This category remains open only because the prior probes measured intraday dislocation itself, not slower-horizon post-event state transition.

- **Open** if the probe measures slower-horizon state-transition effects — e.g. multi-day return persistence, multi-day volatility compression, or funding normalisation — as the primary object.
- **Closed** (rotation, not pivot) if the probe is the same intraday dislocation phenomenon wrapped in a longer observation window. A timeframe change on the same statistical object is not a new direction.

"Positioning behaviour" is *not* an acceptable framing for the measured object — it is broad enough that nearly everything in the project so far could be reframed under it. The measured object must be a specific slower-horizon state transition, not stress generally.

The probe specification (§5) must be fully pre-locked before any code is written. The exploration loop's failure mode in the killed directions was partly that probes were executed before the economic gate was defined, allowing smooth-cashflow artifacts to read as edge.

---

## 7. Tie-breaker rule (binding)

When two directions both clear Appendix B (roadmap v2.2 research-to-paper checklist), **prefer the direction that reaches deployment contact sooner**.

- No "overwhelming evidence" carve-out.
- No exception for "more elegant" or "higher modelled Sharpe" once both candidates are above the Appendix B floor.
- The tie-breaker is strict.

Reasoning: the observed failure mode of this project is **prolonged research without deployment contact**, not premature deployment. Above the Appendix B floor, additional modelled elegance is not worth additional runway. Below that floor, this rule does not apply — Appendix B still gates.

This does not authorise deploying weak strategies. It states that beyond the Appendix B floor, "this one looks prettier in research" is not a sufficient reason to consume more weeks of runway.

**Audit-trail requirement.** The first decision that triggers §7 must be logged in the roadmap v2.2 §10 decision log with explicit reference to this section, capturing: the two candidates, the Appendix B clearance evidence for each, and the deployment-latency comparison that drove the choice. Without this audit trail on first use, §7 risks becoming aspirational rather than operational.

---

## 8. Relationship to roadmap v2.2

| Layer | Role | Authority |
|---|---|---|
| `edge_scoping.md` (this doc) | Upstream search-space filter | Constrains what gets researched |
| Roadmap v2.2 Appendix B | Research-to-paper gate | Required for paper promotion |
| Roadmap v2.2 Appendix A | Paper-to-canary gate | Required for live promotion |
| Roadmap v2.2 §6 | Capital allocation | Governs scaling once live |
| Roadmap v2.2 §10 decision log | Decision audit trail | Records §7 invocations (see §7 above) |

This document does not override any roadmap section. It filters earlier in the pipeline.

---

## 9. Deliberately not in v0.2

- A list of "next probes to run." This document constrains the space; it does not pick the next probe.
- Whether Section A probes should be sequenced or parallelised.
- Any judgment on whether legacy strategies (MM, L9) belong in scope — they sit behind the firewall (roadmap v2.2 §7) and are out of this document's remit.

---

## 10. Open items / follow-ups

- **First §7 invocation:** when §7 first bites on a real decision, ensure the audit-trail entry per §7 is created in the roadmap §10 decision log. Watch for this; it is the operational test of the rule.
- **Runway expiry watch:** §2.1 fallback options are mechanical at expiry. If option 2 (legacy re-onboarding) becomes the chosen path, the roadmap v2.2 §7.2 amendment is the gating work, not this document.
- **§3.2 maintenance:** treat as a living list. New structural closures, discovered through future probes or external evidence, get appended here with a one-line rationale.
- **§4 bullet 5 maturation:** if multiple future directions are rejected on this bullet alone, consider promoting it to its own checklist analogous to Appendix B §B.5 (operational fit).

---

*v0.2.*
