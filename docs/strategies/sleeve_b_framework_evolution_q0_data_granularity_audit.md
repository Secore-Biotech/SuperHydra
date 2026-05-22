# Sleeve B Framework Evolution — Q0 §3.6 Data-Granularity Audit

**Subject:** New Q0 sub-criterion — explicit data-granularity audit required during pre-registration drafting
**Date:** 2026-05-22
**Authority:** Operator (Wasseem)
**Framework state binding:** Subordinate to `fe909bb` (master pre-registration), `cb9d975` (Q0 base), `39970f1` (Stage A gate inheritance), `3ec7a32` (cluster-diversity sub-criterion).
**Analytical basis:** Three drafting errors caught during pre-D1 audit on candidate #5 (`cbd2633`/`fe34b76` plus amendments `8492309` and Amendment #2 drafted in the same session as this memo).
**Status:** Binding for all candidate pre-registrations drafted at or after this commit. Not retroactive to candidates whose pre-registrations are already committed.

---

## 1. Why this evolution exists

Candidate #5 (`cbd2633` → `fe34b76`) reached its pre-D1 audit phase carrying three specification errors in its pre-registration:

**Error 1** — Funding cadence. Pre-reg `fe34b76` §1.1/§1.2 implicitly assumed uniform 8-hour Binance funding cadence across the universe. Reality: Binance has supported 4-hour cadence for selected USDⓈ-M perpetual contracts since 2023-10-12, with 1h/2h/4h/8h algorithmically configurable for high-volatility or newly-listed contracts. Corrected via Amendment #1 (`8492309`).

**Error 2** — OI granularity. Pre-reg §1.1 implicitly assumed sub-day Binance-native PIT-clean OI was available across the OOS window. Reality: Binance archives OI only at daily granularity (`data.binance.vision/data/futures/um/daily/metrics/`); the REST endpoint is limited to the most recent 30 days; vendor-independent sub-day historical OI requires paid third-party data that violates Q0 §2. Corrected via consolidated Amendment #2 (committed in the same session as this framework memo).

**Error 3** — Price cadence mismatch. Pre-reg §1.1 specified realized vol "computed from log returns at 8-hour close intervals" and basis "at all N periods τ" implying intraday cadence. Reality: the candidate's signal is consumed only at weekly rebalance dates (157 weekly Mondays per candidate #4's audit log at `ef788b7`). Sub-day price cadence is over-specified for the signal's actual application; daily prices suffice. Corrected via consolidated Amendment #2.

All three are the same class of error: **data input availability and cadence assumed during pre-registration drafting without explicit verification.** Two were caught only because of a manual pre-D1 audit triggered by an unrelated discovery; one would have surfaced during D1 engineering or D3 evaluation. None were caught by the existing Q0 sub-criteria.

This pattern is too costly to leave unaddressed. Each amendment to a pre-registration weakens the anti-cherry-pick discipline, even when pre-evidence. Three amendments to one candidate's pre-registration is not sustainable governance. The fix is not "draft more carefully"; the fix is making the verification explicit and mandatory.

## 2. The new sub-criterion

**Q0 §3.6 — Data-granularity audit.**

Before a candidate pre-registration may be committed, the selection memo or pre-registration drafting session must include an explicit data-granularity audit for every data input named in the candidate's signal specification.

For each named data input, the audit must verify and document in writing:

**(a) Availability over the full OOS window.** Confirm via vendor documentation or direct API check that the data exists for the entire pre-registered evaluation period (e.g., 2023-04-15 → 2026-04-15 for Sleeve B's current OOS window). Note any gaps, transition dates, or onset dates that affect coverage.

**(b) Cadence of native availability.** State explicitly the cadence at which the data is published by the vendor (e.g., "8h funding events for assets on 8h funding interval, 4h for assets on 4h interval since 2023-10-12"). If the cadence is non-uniform across the universe or across time, document the heterogeneity.

**(c) PIT-cleanliness.** Confirm the data source publishes timestamps as known at publication time, not as backfilled aggregates. For canonical archives this is usually automatic; for derived metrics (medians, rolling windows, normalized values) it must be verified.

**(d) Vendor independence.** Confirm Q0 §2 status — is the data available from a vendor whose terms are compatible with the candidate's vendor-independence claim? Paid data subscriptions must be flagged explicitly; if a paid source is the only path, the candidate is either re-scoped or Q0 §2 must be amended through a separate framework evolution.

**(e) Cadence consistency with signal application.** The signal's data cadence must be consistent with the cadence at which the signal is read. If a signal is applied weekly (e.g., as an overlay on a weekly-rebalance host strategy), specifying intraday cadence for its inputs is over-specification that creates implementation ambiguity. The audit must verify alignment.

**(f) Existing infrastructure check.** Verify whether the data is already fetchable via existing repository infrastructure. If yes, the pre-registration must reference the existing module rather than treating the fetcher as a new D-level deliverable. New fetcher development is justified only when no existing module covers the input.

## 3. How the audit is documented

The audit is documented in the candidate's selection memo (preferred) or in a dedicated data-availability appendix attached to the pre-registration. Required form: one row per data input, with columns covering (a)-(f) above.

Example template:

```
| Input        | Window coverage  | Native cadence    | PIT-clean | Vendor independence | Signal-cadence consistency | Existing infrastructure                 |
|--------------|------------------|-------------------|-----------|---------------------|----------------------------|------------------------------------------|
| Funding rate | Full OOS         | 8h/4h/1h variable | Yes       | Binance-native      | Weekly rebalances suffice  | data/ingestion/vendors/binance/funding_  |
|              |                  | (per Amendment #1)|           |                     |                            | fetcher.py at 8e60933                     |
| OI history   | Full OOS         | Daily only        | Yes       | Binance-native      | Weekly rebalances; daily   | NEW: data/ingestion/vendors/binance/oi_  |
|              |                  |                   |           |                     | OI sufficient              | fetcher.py to be built at D1             |
| ...          | ...              | ...               | ...       | ...                 | ...                        | ...                                      |
```

The selection memo's Q0 section must include this table or its equivalent. Pre-registration drafting may not proceed without it.

## 4. Failure modes this prevents

The Q0 §3.6 sub-criterion is specifically designed to prevent the three error classes seen in candidate #5:

- **Cadence-assumption errors.** Forcing column "Native cadence" to be filled requires the drafter to research and state the vendor's actual publication cadence, including heterogeneity.
- **Granularity-availability errors.** Forcing column "Window coverage" requires verifying the data exists at the necessary granularity for the full pre-registered OOS window, not assuming.
- **Signal-cadence inconsistency.** Forcing column "Signal-cadence consistency" requires the drafter to compare the data cadence to the cadence at which the signal is consumed, surfacing over-specification before commit.

These error classes are not exhaustive. The audit will not catch every drafting mistake. But it will catch the most expensive class: errors that propagate through pre-registration into engineering before being discovered.

## 5. Cost vs benefit

Q0 §3.6 adds drafting overhead. For a candidate with 4-6 named data inputs, the audit table is approximately one column-row pair per input, with verification work behind each cell. Realistic time cost: 30-60 minutes per candidate.

The alternative cost — pre-registration amendments triggered by errors caught later — is materially larger. Each amendment costs:

- A separate governance commit
- Audit-trail complexity (future readers must reconstruct three or more chained artifacts to understand what the candidate actually tests)
- Erosion of the anti-cherry-pick discipline (the framework's claim that pre-registrations are binding weakens with each amendment)

Net: Q0 §3.6 is a small upfront cost that prevents a larger downstream cost class.

## 6. Scope limits

**6.1 Applies to:** all candidate pre-registrations whose drafting begins at or after this commit. The new sub-criterion is part of Q0 from this point forward.

**6.2 Does not apply to:** candidates whose pre-registrations are already committed (candidates #1-#5). Candidate #5's data-granularity issues are being addressed through pre-evidence amendments rather than retroactive Q0 application.

**6.3 Does not modify:** Q0 §1-§3.5 (PIT data availability, vendor independence, reconstruction feasibility, survivorship and temporal stability), Q0 §4 (cluster-diversity check from `3ec7a32`). All prior sub-criteria remain binding.

**6.4 Does not promote:** any specific data-source claim or vendor list to "official" status. The audit is about the drafter doing verification work, not about creating a master list of approved data sources.

## 7. Interaction with existing Q0 sub-criteria

Q0 §3.6 layers on top of, and partially overlaps with, Q0 §3 (reconstruction feasibility from `cb9d975`) and Q0 §1 (PIT availability). The relationships:

- **Q0 §1 (PIT availability)** asks "is the data PIT-clean?" — a yes/no per input.
- **Q0 §3 (reconstruction feasibility)** asks "can the candidate's evaluation be reconstructed from available infrastructure?" — a feasibility verdict.
- **Q0 §3.5 (survivorship/temporal stability)** asks "is the eligible universe stable enough through time to support the candidate's claim?" — a stability verdict.
- **Q0 §3.6 (data-granularity audit, this memo)** asks "what cadence, where, with what infrastructure, with what known gaps?" — a structured documentation requirement.

§3.6 does not replace §1 or §3 or §3.5; it makes their verification explicit and documented. A candidate that passes §1, §3, §3.5 without the §3.6 audit would be passing those sub-criteria on an unverified basis. That was the candidate #5 failure mode.

## 8. Auditability and reversibility

This framework evolution is committed as a separate dated memo, subordinate to `fe909bb` (master), `cb9d975` (Q0 base), `39970f1` (gate inheritance), and `3ec7a32` (cluster diversity). It is referenced by all subsequent candidate selection memos and pre-registrations.

This memo may itself be amended through a future framework review. If after several candidates it becomes clear that §3.6 is over-burdensome, under-effective, or capturing a different concern than intended, a subsequent framework-evolution memo can refine it. The next framework review (whenever scheduled per `7c10ca0`'s cadence) is the natural moment to assess §3.6's effectiveness.

The lesson from candidate #5 itself — that ad-hoc amendments during candidate drafting are governance-corrosive — applies recursively here. Future Q0 sub-criteria additions should also go through deliberate framework-evolution sessions, not through ad-hoc additions during candidate drafting.

---

## 9. References

- Master Sleeve B pre-registration: `fe909bb`
- Q0 Data Viability Gate (base sub-criteria §1-§3): `cb9d975`
- Stage A gate inheritance: `39970f1`
- Q0 cluster-diversity sub-criterion (§4): `3ec7a32`
- Framework review (analytical context, May 2026): `7c10ca0`
- Candidate #5 pre-registration: `fe34b76`
- Candidate #5 Amendment #1 (persistence window N): `8492309`
- Candidate #5 Amendment #2 (consolidated data-cadence corrections): committed in same session as this memo
- Sleeve A1 funding fetcher (existing infrastructure example): commits `0e7b377`, `8e60933`
- Binance public archive root: `https://data.binance.vision/`

---

*Q0 §3.6 — Data-granularity audit. New permanent sub-criterion binding for all candidate pre-registrations drafted at or after this commit. Requires explicit, documented verification of data input cadence, availability, PIT-cleanliness, vendor independence, signal-cadence consistency, and existing infrastructure status before pre-registration commit. Derived from three drafting errors caught during candidate #5's pre-D1 audit. Not retroactive to candidates #1-#5; their corrections are handled through pre-evidence amendments.*
