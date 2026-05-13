# A2 First Real-Data Run — SOL March 2024

Window: 2024-03-16T00:00:00Z to 2024-03-30T00:00:00Z (14 UTC days)
Symbol: SOLUSDT, single venue (Binance)
Cadence: 60s per-minute snapshots

## What was tested

Day 26 produced the substrate (spot archive fetcher, perp+spot pairing, refresh
script) to convert real Binance trade archives into A2-compatible
BasisObservation records. This is the first run of the Day 25 A2 PAPER_RESEARCH
harness against real data instead of the synthetic constant/spike fixtures.

Calibration: same z-score evaluator (window 60, threshold 2.0), same cost model
(binance_vip5_alt_v1 perp, binance_vip5_spot_placeholder_v0 spot), same
round-trip threshold computed via Day 22 helper (33.84 bps for SOL with 20%
uncertainty margin).

## Ingestion stats

| Metric | Value |
|---|---:|
| Perp aggTrades fetched | 25,474,955 |
| Spot aggTrades fetched | 11,094,596 |
| Perp buckets (60s) | 20,160 |
| Spot buckets (60s) | 20,160 |
| Common buckets | 20,160 (100% overlap) |
| Perp-only buckets | 0 |
| Spot-only buckets | 0 |
| BasisObservation records emitted | 20,160 |

Every minute of the 14-day window had at least one trade in BOTH markets.
Maximum possible coverage.

## Harness result

| Outcome | Count | % of evaluations |
|---|---:|---:|
| Total evaluations | 20,160 | 100.0% |
| Skipped: insufficient lookback | 29 | 0.1% |
| Skipped: stale window | 0 | 0.0% |
| Skipped: zero stdev | 0 | 0.0% |
| Skipped: z below threshold | 18,847 | 93.5% |
| Skipped: cost not cleared | 1,284 | 6.4% |
| **A2 intents fired** | **0** | **0.0%** |
| Paper.fills rows written | 0 | — |

## Interpretation

Zero fires. But the failure mode is structurally different from A1's six-window
zero-fire result, and more informative.

A1 failed mostly at signal persistence. The rolling-12 forecast never reached
the cost-anchored 7.7 bps threshold even when individual funding events hit
12+ bps in isolation (Day 20.6 keystone finding). The signal mechanism was too
smoothed for the regime it was trying to detect.

A2's failures split into two distinct classes:

1. **93.5%** never reached 2σ on the z-score gate. The basis-dislocation signal
   did not fire at all. Basis sat in a narrow distribution for most of the
   window.

2. **6.4%** cleared the z-score gate but failed the cost gate. These are the
   genuinely informative observations: the signal formulation correctly
   identified statistically anomalous dislocations, but the dislocations
   themselves were too small in basis-points to clear the 33.84 bps round-trip
   cost.

The 6.4% bucket is empirical evidence that the A2 signal mechanism works — it
detects real dislocations — but the dislocations in March 2024 SOL were too
small to be profitable after costs. This is fundamentally different from
"strategy dead." It is "this window does not have the right conditions."

## What this is and is not

This is: one window, one symbol, one cost calibration. Evidence that A2 in its
current calibration would not have traded SOL March 2024.

This is not: a verdict on A2 as a strategy. March 2024 was a low-realized-
volatility regime for SOL basis. Different historical windows may produce
different results.

## Next empirical question

Does any historical SOL window have basis dislocations large enough to clear
the ~34 bps economic gate?

Day 20.6's keystone finding established that September 2021 SOL had funding
events at 12.15 bps in isolation — the strongest historical funding regime for
SOL in the windows tested. Whether basis dislocations followed similar
magnitudes is unknown. That window is the natural next probe.

Sep 2021 SOL would also test the substrate against a much older Binance
archive (validates fetcher resilience across pre-2024 schema variants).

Reviewer-locked next step: targeted Sep 2021 SOL probe before any sweep
automation. One carefully chosen high-volatility window is more informative
than orchestration infrastructure built without empirical justification.

## Substrate notes (Day 26 + 26.5 lessons)

1. **The Day 26.1 firewall was empirically validated.** Spot aggTrades CSV has
   8 columns (perp has 7); the extra `is_best_match` column is spot-specific.
   The reviewer-locked decision to write a new spot fetcher class rather than
   modify A1's perp parser path turned out to be the right call: the schemas
   genuinely differ. Option B (spot-local parser) preserved the firewall and
   produced the cleanest fix.

2. **The transport invocation pattern was wrong in the first Day 26 cut.** The
   HttpTransport protocol has a `.get(url, timeout_seconds=...)` method; the
   spot fetcher initially treated the transport as a bare callable. This was
   caught by the empirical run, not by unit tests. Future fetcher-like
   additions should explicitly cover the transport call path in tests, or
   share that code with a verified interface.

3. **The dev DB needs `alembic upgrade head` before CLI harness runs against
   persistent data.** Tests use `fresh_db` which migrates per test; that hides
   the requirement. The harness error message was clear (`relation
   "registry.venues" does not exist`) and the fix was one command.

## Artifacts

- Fixture: `tests/fixtures/a2_basis/SOLUSDT_basis_14d_20240316T000000_20240330T000000.json`
- Substrate: `data/ingestion/vendors/binance/spot_archive_trade_fetcher.py` (Day 26 + 26.5)
- Test coverage: `data/ingestion/vendors/binance/tests/test_spot_archive_trade_fetcher.py` (21 tests)
- Harness: `strategies/a2_basis/runner/paper_research_harness.py` (Day 25)
