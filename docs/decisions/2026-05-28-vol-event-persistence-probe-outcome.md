# Vol-Event Persistence Probe — Outcome (Section A)

**Status:** Final — data-coverage limited; persistence hypothesis directionally disfavored, formal verdict inconclusive
**Author:** Wasseem Katt
**Date:** 2026-05-28
**Implements:** roadmap v2.2 §10 (decision logging requirement; probe outcomes recorded with timestamp, gate reference, and justification); notes/section_a_probe_spec_v1.md (probe spec §5 statistical gate, §6 economic gate, §8 immutable locks)
**Related:** notes/edge_scoping.md (to be updated with "Data-limited / unresolved" category referencing this entry); strategies/vol_event_persistence/ commits 65a3082..ae162df (build) and 15a9d15 (post-build funding-jitter fix surfaced by first real run)

This entry records the outcome of the Section A vol-event persistence probe. The probe tested whether perpetual futures on BTCUSDT and ETHUSDT exhibit directional persistence following a 24-hour realised-volatility event (σ crossing its trailing 90-day P95). It ran end-to-end on real Binance USDM-Futures 1h klines and funding for 2023-04-01 through 2026-04-30, on the production code path that canary would use. The outcome is **data-coverage limited**: the locked sample-sufficiency thresholds were not cleared, and per the operator-locked decision rule (branch 3) the under-sample economic evidence is recorded as directionally informative but not as a formal kill.

This entry is the first probe-outcome record in `docs/decisions/`. All prior entries in this directory are design documents.

## Probe parameters

- **Universe:** BTCUSDT, ETHUSDT — Binance USDM-Futures.
- **History window:** 2023-04-01T00:00:00Z to 2026-04-30T23:00:00Z (1,126 days × 24 hourly bars per symbol = 27,024 bars/symbol).
- **σ estimator:** rolling 25-hour window over hourly log returns, daily anchor at 00:00 UTC, 90-day trailing P95 percentile threshold.
- **Horizons:** 1, 3, 7 days; entry at anchor open, exit at horizon-end last hourly open.
- **Direction rule:** LONG if pre-event log return > 0, SHORT if < 0, FLAT if exactly 0 (locked per probe spec §3.3).
- **Cost model:** 10 bps round-trip execution; funding signed by direction (LONG pays positive funding; corroborated against FundingRate canonical doc).
- **Train/OOS split:** 80/20 calendar-time, locked at probe-build time per §8 (no re-split).
- **Sample sufficiency thresholds (§5):** train events ≥100, OOS events ≥30, OOS span ≥182 days.
- **Economic thresholds (§6):** mean net ≥20 bps; median net >0; win rate >50%; cost coverage ≥2.5×; final-3-month net P&L >0.

## What happened

Probe v0.1 ran in two phases. The first real-data run flagged both symbols `data_quality_suspect: true` with funding-gap skip rates of 59% and 62%. Root cause: `_sum_funding_bps` performed exact-instant dict lookups against funding timestamps that carry sub-second jitter in real venue data (e.g. `2023-04-02T00:00:00.013000+00:00`). The 188 pre-existing unit tests all used exact `:00` timestamps in synthetic fixtures and were structurally blind to this class.

The funding lookup was reworked to interval-membership semantics — sum `funding_rate` over records whose `funding_time` ∈ `(A, A + horizon·24h]` — paired with a cadence-agnostic consecutive-gap guard (>12h gap overlapping the holding window → `SKIP_FUNDING_GAP`). The new logic is jitter-immune by construction and preserves the original guard's purpose (catch a missing settlement) without the brittle exact-instant assumption. Four jitter regression tests were added so this class cannot return. Suite: 192/192. Fix committed at `15a9d15` with full behavioral-impact documentation.

The second run on the same fixture produced clean data hygiene (zero gap skips, zero suspect symbols) and a stable verdict. A subsequent extension attempt to 2026-06-01 hit Binance's monthly archive ceiling: the May 2026 archive has not been published yet (today is 2026-05-28; Binance publishes monthly archives a few days into the following month). The 1h kline series therefore ends at 2026-04-30 regardless of fetch attempts. This is a structural data ceiling, not a fetcher defect.

## Verdict

**`probe_pass: false`**. Statistical gate (§5) returned `INSUFFICIENT_SAMPLE` on all three horizons, with identical reasons across horizons because the split parameters depend on calendar span only:

| Metric | Threshold | Realised | Status |
|---|---|---|---|
| Train events | ≥ 100 | 94 | FAIL (short by 6) |
| OOS events | ≥ 30 | 37 | PASS |
| OOS span (days) | ≥ 182 | 165 | FAIL (short by 17) |
| OOS rolling failures | ≤ 1 | 0 | PASS |

Economic gate (§6), computed under-sample on the 131 events per horizon:

| Horizon | Mean net (bps) | Median net (bps) | Win rate | Cost coverage | Final-3mo net (bps, 12 events) |
|---|---|---|---|---|---|
| h=1 | −101.27 | −108.05 | 41.2% | −7.78 | −2219.22 |
| h=3 | −105.59 | −108.11 | 38.2% | −6.49 | −1660.14 |
| h=7 | −62.11 | −68.01 | 41.2% | −2.38 | −984.74 |

Every economic threshold is missed at every horizon. Cost coverage is negative across the board, which means mean gross is negative — the directional move opposes the persistence hypothesis. The numbers are directionally consistent with **anti-persistence**: events that the locked direction rule trades LONG are mean-reverting (and vice versa for SHORT). The final-3-month windows are deeply negative on all horizons, indicating the directionally adverse pattern is not concentrated in the early sample.

## Decision rule application

The operator-locked decision rule, set before the run produced its first real number, was:

> **Branch 1.** If sample sufficiency clears and economics still fail: Section A persistence probe = FAILED. Write §10 decision log. Do not rescue with reversal in the same spec.
> **Branch 2.** If sample sufficiency still fails: Record data-coverage limitation. Do not overread economic gate as formal kill.
> **Branch 3.** If economics flip positive: Treat as suspicious edge-sensitivity. Audit boundary events before any promotion talk.

Sample sufficiency did not clear. Extension to fill the gap is currently blocked by Binance's archive publishing schedule, not by any fetcher or pipeline issue. Branch 2 therefore applies. The economic evidence is recorded as directionally disfavoring the persistence hypothesis but **not as a formally sample-sufficient verdict**.

## Outcome

Section A persistence probe = **DATA-COVERAGE LIMITED**.

> Persistence hypothesis directionally disfavored.
> Formal verdict inconclusive under locked rules.

Promotion gate not cleared. No P1 wiring authorised. The probe stays in research; the persistence hypothesis is not pursued further on its own merit.

## Non-precedent rule

Per probe spec §8 and roadmap v2.2 §10 non-precedent language: this outcome does not authorise reversal or any alternative spec rescue. A reversal hypothesis ("trade against the pre-event direction on vol-spike events"), if pursued in future, scopes as a fresh probe with its own §5/§6 gates, its own pre-registered scoping, and its own decision-log entry. It is not a tweak to this one, and the under-sample anti-persistence signal in this entry is not evidence for promoting such a probe — it is the directional observation that would justify the *cost* of building one.

## Followups

- **Optional re-run after 2026-06 monthly archive publishes** (early June 2026). Re-running on extended data is mechanical: the exporter, harness, and gates are committed and produce a deterministic output on a given fixture. The decision rule pre-specifies the branch in each outcome:
    - If sample sufficiency clears and economics still fail → Branch 1: formal kill; new §10 entry referencing this one as predecessor.
    - If sample sufficiency clears and economics flip → Branch 3: audit boundary events before any promotion talk.
    - If sample sufficiency still fails (further data ceiling effect) → Branch 2 again; this entry stands.
- **notes/edge_scoping.md update** to be filed as a separate commit, adding a new category "Data-limited / unresolved" with this probe as its first entry. The category sits alongside the existing "structurally closed" and "empirically killed" classifications and is deliberately distinct from both.
- **No code or infrastructure followups.** The pipeline, gates, harness, exporter, and jitter fix are all committed and production-shaped. No carry-forward technical debt.

## Provenance

- Probe spec: `notes/section_a_probe_spec_v1.md` (committed at `a28dbea`).
- Edge scoping at probe-design time: `notes/edge_scoping.md` v0.2 (committed at `937dee9`).
- Probe build: commits `65a3082` (init) through `ae162df` (harness), eleven commits total. See `git log strategies/vol_event_persistence/` for the full sequence.
- Post-build funding-jitter fix: commit `15a9d15`. This commit is referenced because the first real-data harness output would not be trustworthy without it; the verdict above is computed on the post-fix pipeline.
- Fixtures used: `fixtures/real_vol_event_fixture.json` (initial), `fixtures/real_vol_event_fixture_v2.json` (post-fix), `fixtures/real_vol_event_fixture_v3.json` (extension attempt; identical kline ceiling). Fixtures are retained on the operator workstation but not committed (large JSON, reproducible from the exporter).
- Test suite at time of verdict: 192/192 green, including four jitter regression tests added in `15a9d15`.

— end —
