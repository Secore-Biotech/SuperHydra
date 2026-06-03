# Section A Rerun — Outcome (terminal under v1)

**Status:** Final — rerun executed under the §8 Reading A interpretation (`16ef6ce`). Section A is data-limited by **structural event sparsity**, not data coverage. Terminal under spec v1; re-test requires a v2 spec.
**Author:** Wasseem Katt
**Date:** 2026-06-03
**Supersedes the re-run-eligibility framing of:** `2026-05-28-vol-event-persistence-probe-outcome.md` (which expected the 2026-05 archive to unblock §5). It did not, for the reason recorded below.

## What was run

The 2026-05 Binance monthly archive (1h klines + fundingRate, BTCUSDT/ETHUSDT) published; both fetched HTTP 200 on 2026-06-03. After clearing a stale `.notfound` negative-cache marker for 2026-05 (see "Operational note"), the fixture was regenerated to `fixtures/real_vol_event_fixture_v4.json` spanning 2023-04-01 → 2026-05-31 (27,768 bars/symbol, ~1,156 days, vs 27,024 / ~1,125d originally). The probe was rerun via `harness.py` on the same locked v1 parameters (no change to split fraction, thresholds, horizons, cost model, σ estimator, direction rule).

## Result — identical verdict, by structural cause

§5 returned INSUFFICIENT_SAMPLE on all three horizons, with numbers **identical to the 2026-04-30 run**: train events 94 < 100, OOS span 165d < 182d, OOS events 37. Economics identical to full precision (mean net −101.27 / −105.59 / −62.11 bps at h=1/3/7; negative cost coverage; anti-persistence).

The identity is not a defect. It is the binding constraint revealing itself:

- The σ-event definition fires on a 24h realised-σ crossing its **trailing-90-day P95**. Across 1,156 days on BTC+ETH it produces **131 events** — unchanged from the original 1,125-day run.
- May 2026 added ~31 calendar days but **zero events**: no σ crossed its trailing-90-day P95 that month (a quiet month).
- `_split_date` anchors the 80/20 boundary to **event times** (`min`/`max` of event timestamps), not calendar span. With no new events, `min` and `max` are unchanged, so the split, the train/OOS counts, and the event-measured OOS span are all unchanged.

## Conclusion — terminal under v1

The 2026-05-28 record and the §3.3 entry framed Section A as "re-runnable when the archive publishes; mechanical." That framing mis-identified the binding constraint as **data coverage**. The rerun disproves it: the archive published, the data extended, and §5 still fails — because the constraint is **structural event sparsity** under the locked event definition, not calendar coverage. The two failing axes (train events 94<100; OOS event-span 165<182) are both functions of how rarely the σ-P95 event fires, and waiting for more calendar cannot raise an event count that the event definition itself keeps sparse.

Therefore:

> **Section A persistence (spec v1) — data-limited by structural event sparsity. TERMINAL under v1.**
> No future rerun changes this. The under-sample economics remain directionally anti-persistent on all horizons but never reach a sample-sufficient verdict, so per Branch 2 they are not a formal kill. Re-test requires a **v2 spec** with a different event definition (looser σ threshold, a different event trigger, or a different measured object) — a fresh pre-lock decision per §8, not a rerun. §8 is explicit: changing a locked parameter kills v1; there is no amendment path.

This resolves the last mechanical thread on the direction map. Section A is no longer "data-limited, re-runnable" — it is "data-limited (structural), terminal under v1."

## Operational note (defect class, for the record)

The rerun required clearing a stale `.notfound` cache marker: the kline archive fetcher had written `BTCUSDT-1h-2026-05.zip.notfound` / `ETHUSDT-...` on 2026-05-28 when May was genuinely unpublished, and (per `klines_archive_fetcher.py`) treats a cached `.notfound` as permanent — it never re-requests. The first regeneration attempt therefore produced a **split-brained fixture** (May funding via a different fetcher, but April klines from the stale marker), which would have rerun to a false-repeat of the data-limited verdict had the depth-summary date range not been checked. `.notfound` markers have no TTL and will re-bite any future month-boundary rerun. Not fixed here (out of scope); flagged for whenever the fetcher is next touched.

## Decision-rule branch

Branch 2 (sample sufficiency did not clear). The new fact vs the original Branch 2: sufficiency now provably *cannot* clear under v1, so the outcome is terminal rather than deferred.
