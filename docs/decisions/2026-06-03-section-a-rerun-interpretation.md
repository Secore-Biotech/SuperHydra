# Section A Rerun — §8 Interpretation (pre-run record)

**Status:** Pre-run interpretation, recorded before the rerun executes.
**Author:** Wasseem Katt
**Date:** 2026-06-03
**Context:** The 2026-05 Binance monthly archive (fundingRate + 1h klines, BTCUSDT/ETHUSDT) published; both fetch HTTP 200 as of 2026-06-03. This unblocks the data ceiling recorded in `2026-05-28-vol-event-persistence-probe-outcome.md`.

## Interpretation (locked before running)

For Section A v1, §8's "Train/OOS split (80/20, OOS ≥ 6 months, computed once)" is interpreted as freezing the **split method**, not freezing the original calendar **boundary**. The rerun uses the same deterministic 80/20 calendar-span rule (`gates.py`, split computed at 80% of loaded series span) on the extended archive, because:

1. The prior outcome record explicitly anticipated a mechanical rerun when the data ceiling lifted — an anticipation incoherent under a frozen-boundary reading.
2. `gates.py` already computes the split from the loaded series span at runtime; the method is unchanged.
3. The input extension is external and calendar-driven (the archive caught up), not a parameter change made after seeing results.
4. No locked parameter changes: same split fraction, thresholds, horizons, cost model, gates, σ estimator, direction rule.

This is the pre-declared rerun condition becoming available, not post-hoc fitting. The §8 "no amendment" / "no re-split" prohibition targets manually moving the split to rescue a result; it does not target re-running the frozen method on data that did not exist at first run.

## Binding-constraint correction

The 2026-05-28 record framed Section A as re-runnable because the archive would lift the data ceiling. That framing was incomplete: §5 failed on TWO axes — OOS span (165 < 182) AND train events (94 < 100). The archive extension clears OOS span directly (≈+30 days → ≈195). Train events rise only because the re-derived split (Reading A) moves the boundary forward, promoting prior-OOS events into train. Under a frozen-boundary reading (Reading B), train would stay 94 and the rerun could never clear §5. Reading A is therefore also the only reading under which the promised rerun can succeed.

## Pre-committed verdict branches (unchanged from the original record)

- **Branch 1.** Sample sufficiency clears and economics still fail → Section A persistence = FAILED. Log it. No reversal rescue in this spec.
- **Branch 2.** Sample sufficiency still fails → record data-coverage limitation; do not overread economics.
- **Branch 3.** Economics flip positive → suspicious edge-sensitivity; audit boundary events before any promotion talk.

Note: the under-sample economics already on record (mean net −62 to −106 bps, negative cost coverage, anti-persistence on all horizons) make Branch 1 the most likely outcome if §5 now clears. The rerun is run to reach a *formal* verdict, not because the economic picture is expected to change.
