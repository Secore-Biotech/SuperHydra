# A1 Funding-Capture Probe v1 — Outcome (Spec-Layer DATA_LIMITED)

**Status:** Final — data-limited at the spec layer; no probe implementation was built
**Author:** Wasseem Katt
**Date:** 2026-06-02
**Implements:** roadmap v2.2 §10 (decision logging requirement; probe outcomes recorded with timestamp, gate reference, and justification); notes/a1_probe_spec_v1.md §8 (immutable locks), §7.4 (under-sample decision rule), §9 (workflow before execution)
**Related:** docs/decisions/2026-05-28-vol-event-persistence-probe-outcome.md (Section A — first probe-outcome record in this directory and the precedent for the under-sample decision rule applied here); notes/edge_scoping.md v0.2 §3.3 (Data-limited / unresolved category)

This entry records the outcome of the A1 funding-capture probe v1. The probe
tested whether expected positive funding above a pre-locked threshold predicts
realised positive funding cashflow net of execution and basis drift on Binance
USDM-Futures perp / spot leg-pairs for BTCUSDT and ETHUSDT, across holding
horizons of 1, 3, and 7 funding intervals.

The outcome is **DATA_LIMITED at the spec layer.** This is a deliberately
distinct classification from Section A's `DATA_LIMITED`, which arose
*post-implementation* from a data ceiling. A1 v1's `DATA_LIMITED` arose
*pre-implementation* from a §9 step 2 diagnostic check: at the locked
threshold θ=0.0200% per 8h, the OOS window contains zero qualifying funding
observations on either symbol, making §5.3 sample sufficiency structurally
unclearable as written. Per §8 (θ immutable in v1) and §7.4 (under-sample
horizons return `DATA_LIMITED`), the v1 outcome is locked before any probe
code is written.

## What happened

The A1 probe specification v1 was authored and committed at `3e401a0`
following a structured locking sequence: measured object, universe,
event definition, cost model, statistical and economic gates, immutable
locks, and pre-execution workflow. Threshold θ=0.0200% per 8h was chosen
from a train-only density reconnaissance (committed at `0d390e3`) that
revealed:

- A large mass of Binance funding observations at exactly 0.0100% per 8h
  (the formula's default-rate output when premium-index and interest-rate
  components are within a band).
- A cliff in event count immediately above this mass: train-only density
  drops from ~42-43% at θ=0.0100% to ~8-9% at θ=0.0125%, settling at
  ~6% at θ=0.0200%.
- A pre-spec rationale for setting θ above the default-rate mass:
  thresholds at or below it would fire on the default state rather than
  on genuinely elevated funding.

θ=0.0200% was locked as the smallest value cleanly above the default-rate
mass that retained enough train density for §5.3 with comfortable margin.
At spec commit, the OOS density had not been checked — that check was
reserved for §9 step 2, post-commit and pre-build, per the locked workflow.

Per §9 step 2, the density script was extended (committed at the next
commit hash) to support a `--threshold` mode that runs the OOS sample-
sufficiency check at a single locked θ against the §5.3 floors. The
script reported, at θ=0.0200% on `real_vol_event_fixture_v3.json`:

| Metric                 | Value             | §5.3 floor | Status |
|------------------------|-------------------|------------|--------|
| Pooled train events    | 349 (BTC 163 + ETH 186) | ≥ 100   | PASS   |
| Pooled OOS events      | **0** (BTC 0, ETH 0)    | ≥ 30    | **FAIL** |
| OOS span (days)        | 230.7             | ≥ 182      | PASS   |

The train/OOS split (calendar-time 80/20) landed at
`2025-10-09T22:24:00 UTC`. The OOS window therefore spans approximately
the last 7.6 months of available funding data (2025-10 → 2026-05-28).
Across both symbols and across the entire OOS window, **zero funding
observations cleared θ=0.0200% per 8h.**

## What this finding means

This is not marginal sample-sufficiency failure. It is a regime statement.
In the last ~7.6 months of Binance perpetual funding on BTCUSDT and
ETHUSDT, no funding observation has reached 0.0200% per 8h — a substantial
contraction from the train period where ~6% of observations cleared that
level. The funding distribution in the OOS window is structurally compressed
relative to the train distribution; the 0.0200% region is empty, not
thinly populated.

The finding is recorded as a fact about Binance funding regime behavior
in the 2025-10 to 2026-05 window. It is informative for any future
funding-capture spec design and is one of the substantive outputs of
this exercise even though no v1 probe code was written.

## Verdict

A1 funding-capture probe v1 = **DATA_LIMITED at the spec layer**.

- All three horizons (1, 3, 7 funding intervals) would have status
  `INSUFFICIENT_SAMPLE` on actual run because the trigger fires zero
  times in OOS regardless of horizon length.
- Per §7.4 probe-level rule: if all three horizons are
  `INSUFFICIENT_SAMPLE`, the probe outcome is `DATA_LIMITED` overall.
- Per §8: θ is immutable in v1. The verdict is not contingent on
  what a different θ might produce; that is a v2 spec question.
- No probe implementation was built. No spot-kline exporter was built.
  No `strategies/funding_capture/` modules exist. No carry-forward
  technical debt from this outcome.

## Decision rule application

The §7.4 under-sample rule, locked at spec commit, is applied without
modification:

> If a horizon's status is `INSUFFICIENT_SAMPLE`, economic-gate metrics
> are computed and reported but classified as `NOT_EVALUATED` for
> purposes of probe pass/fail. The horizon's outcome is `DATA_LIMITED`
> regardless of whether the under-sample economic numbers are
> favourable or unfavourable.

For A1 v1 specifically, no economic metrics are computable because no
OOS events exist to compute them on. The under-sample rule reduces to
its simplest form: outcome is `DATA_LIMITED`, no probe runs, no further
analysis is conducted under v1.

## Discipline-success framing

This outcome is a success of the pre-lock discipline, not a failure of
the probe. The §9 step 2 OOS density check is precisely the audit-trail
checkpoint the spec was structured around: a pre-execution diagnostic
that catches an unrunnable spec *before* any build cost is incurred.

The previous Section A outcome (docs/decisions/2026-05-28-...) cost a
full probe build, a fixture export, a debug cycle for the funding-jitter
defect, and a verdict run before the data ceiling was conclusively
established. That outcome was honest and the discipline held — but it
arrived at the cost of weeks of work. A1 v1's outcome arrived at the
cost of one descriptive script run after one spec-locking conversation.
Both are correct outcomes; the cost differential is the spec discipline
paying off.

The §8 immutability rule's pre-commitment to "no θ revision in v1"
matters here. At the moment the OOS density returned zero, the path of
least resistance was to lower θ — e.g. to 0.0150%, which would have
produced OOS events — and continue. The spec, written before any data,
ruled that move out as a v2 question. The discipline held. Recording
this is part of why the entry exists.

## Non-precedent rule

Per spec §8 and the inherited principle from Section A: this outcome
does not authorise spec amendment or rescue. A v2 spec, if pursued in
future, scopes as a fresh probe specification with its own §5/§6 gates,
its own pre-locked event definition (which may be a different θ, a
regime-conditional threshold, or a different hypothesis class entirely),
and its own decision-log entry. It is not a tweak to v1, and the
existence of train events at higher θ values in this entry is **not**
evidence for promoting any v2 design — it is only the directional
observation that would justify the cost of designing one.

## Followups

- **No code followups.** No probe was built. No fixtures, exporters,
  or modules need updating.
- **`notes/edge_scoping.md` §3.3** to be updated in the same commit
  as this entry, adding A1 v1 alongside Section A as the second entry
  in the `Data-limited / unresolved` category. The two entries share
  the category but have different causes (Section A: data ceiling at
  archive boundary; A1 v1: regime emptiness at locked threshold).
- **v2 design is a separate future exercise.** Not in this session,
  not in this entry, not implied by this outcome. v2 design, if
  pursued, requires its own scoping conversation, its own locks, and
  its own decision-log entry.

## Provenance

- A1 v1 spec: `notes/a1_probe_spec_v1.md` (committed at `3e401a0`).
- Density reconnaissance script: `scripts/a1_density_recon.py`
  (initial version at `0d390e3`; `--threshold` OOS-check extension
  at the next commit hash following this entry's commit sequence).
- Fixture used: `fixtures/real_vol_event_fixture_v3.json` (the same
  fixture that produced Section A's DATA_LIMITED outcome; suitable
  for the OOS density check because the check requires only funding
  data, no spot or perp klines).
- Section A precedent: `docs/decisions/2026-05-28-vol-event-persistence-probe-outcome.md`.

— end —
