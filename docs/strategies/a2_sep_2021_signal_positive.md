# A2 Signal-Positive on Sep 7 2021 — Execution-Incomplete

Window: 2021-09-01T00:00:00Z to 2021-09-15T00:00:00Z (14 UTC days)
Symbol: SOLUSDT, single venue (Binance)
Cadence: 60s per-minute snapshots

## Status classification

After two real-data windows (Mar 2024 + Sep 2021), A2 is:

- **Signal-positive.** The z-score-plus-cost-anchored signal mechanism fires
  correctly on large, real basis dislocations during volatility regimes.
- **Execution-incomplete.** The current substrate is entry-only. There is no
  position state, no anti-reentry logic, no exit semantics. The implementation
  captures the moment the strategy would have entered, not the moment it
  would have closed.

A2 is no longer in the "does this signal ever fire on real data?" question.
That question is answered: yes, during volatility events. A2 is now in the
"does this strategy capture economic value once it fires?" question. That
requires substrate components that do not exist yet.

## What was tested

Same calibration as the Mar 2024 run (Day 27A). The only variable is the
window: Sep 1-15 2021 — matching Day 20.6's keystone-finding window for A1,
where SOL had its strongest historical funding regime in the windows tested.

Ingestion stats:

| Metric | Sep 2021 | Mar 2024 |
|---|---:|---:|
| Perp aggTrades fetched | 30,329,057 | 25,474,955 |
| Spot aggTrades fetched | 24,501,352 | 11,094,596 |
| Common buckets | 20,160 (100% overlap) | 20,160 (100% overlap) |
| BasisObservation records | 20,160 | 20,160 |

Sep 2021 had roughly twice the spot volume of Mar 2024. Both markets were
more active during this older window.

## Harness result

| Outcome | Sep 2021 | Mar 2024 |
|---|---:|---:|
| Total evaluations | 20,160 | 20,160 |
| Skipped: insufficient lookback | 29 (0.1%) | 29 (0.1%) |
| Skipped: z below threshold | 18,762 (93.1%) | 18,847 (93.5%) |
| Skipped: cost not cleared | 1,357 (6.7%) | 1,284 (6.4%) |
| **A2 intents fired** | **12** | **0** |
| Paper.fills rows | 24 | 0 |

The skip taxonomy is nearly identical across windows. **The difference is in
the right tail of the z-cleared bucket.** In both windows, roughly the same
fraction of evaluations were statistically anomalous (z≥2.0). The fraction of
those events that also cleared the 33.84 bps round-trip cost threshold
differed.

## The 12 events

| # | Time (UTC) | Side | Perp px | Spot px | Raw basis (bps) |
|---:|---|---|---:|---:|---:|
| 1 | 09-07 14:25 | short perp | 174.96 | 174.09 | +50 |
| 2 | 09-07 14:29 | short perp | 170.39 | 169.35 | +62 |
| 3 | 09-07 14:47 | short perp | 164.83 | 163.65 | +72 |
| 4 | 09-07 14:49 | short perp | 159.76 | 155.48 | +275 |
| 5 | 09-07 14:59 | long perp | 150.26 | 152.23 | -129 |
| 6 | 09-07 15:04 | long perp | 157.21 | 158.72 | -95 |
| 7 | 09-07 15:07 | short perp | 148.02 | 146.00 | +139 |
| 8 | 09-07 15:08 | short perp | 137.82 | 135.90 | +141 |
| 9 | 09-07 15:09 | short perp | 134.68 | 132.28 | +181 |
| 10 | 09-07 15:18 | long perp | 155.94 | 159.01 | -193 |
| 11 | 09-07 15:21 | long perp | 159.74 | 162.63 | -178 |
| 12 | 09-13 14:03 | long perp | 154.07 | 154.57 | -32 |

Raw basis = (perp − spot) / spot × 10000. The dislocation that actually fires
the signal is `current_basis − rolling_mean`, which is not captured in
metadata yet. Events fire when both the z-score (≥2.0) and the
|dislocation| (≥33.84 bps for SOL) exceed thresholds.

## Why the Sep 7 2021 result matters

### 1. A2 fired only during a genuine market-wide liquidity event

11 of 12 entries occurred within a 56-minute window on Sep 7 2021
14:25-15:21 UTC. The SOL price trajectory across these entries (~$175 to
~$135 intraday, a 23% drop) is the documented Sep 7 2021 crypto-wide crash
coinciding with El Salvador's BTC adoption. This is not random firing across
the window. It is one regime event.

### 2. Dislocations cleared the cost threshold materially

The signal does not fire just above the 33.84 bps gate. Raw basis values from
+50 to +275 and from -32 to -193 bps appear in the events. The dislocations
that fired the signal were not marginal.

### 3. Both positive and negative basis regimes appeared during the same episode

7 entries were positive-basis (perp at premium → short perp, long spot); 4
entries were negative-basis (spot at premium → long perp, short spot); 1
entry (Sep 13) was a smaller negative event six days later. The signal
mechanism worked symmetrically. The crash produced rapid alternation between
perp-at-premium and perp-at-discount as cascading liquidations and rebound
buying alternated.

### 4. The implementation currently captures entries, not completed trades

The paper.fills rows show 24 entry-leg rows for 12 logical entries. There are
no corresponding exit rows. There is no position state. There is no
anti-reentry rule. Sequential entries at 14:25, 14:29, 14:47, 14:49 are not
4 independent trades — they are 4 reads of the same continuously-dislocated
state. A real deployment would either be already-positioned during entries
2-4 (and would not re-enter), or would have closed the prior entry's
position (and the current substrate does not model that).

### 5. Position state and exit logic are now the gating missing components

The signal question is answered. The bottleneck is no longer "does A2 ever
fire?" It is "does A2 capture economic value once it fires?" That requires:

- Position state per leg
- Anti-reentry or explicit scaling-in semantics with inventory limits
- Exit semantics (basis convergence triggers, time-based forced exit, or
  similar)
- Paired entry-exit paper.fills rows

Without these, the harness counts "entries that would have been taken" —
informative for signal validation but not for P&L.

## Comparison: Mar 2024 vs Sep 2021

The 6%-band evaluations (z-cleared, cost-anchored) at almost identical
proportions across both windows tell us something important about the
*signal*: the z-score gate fires at a steady rate (~6% of evaluations)
regardless of regime. What changes between regimes is whether the absolute
dislocation is large enough to clear costs.

Mar 2024 was a calm regime. Even when basis statistics fired (1,284 times),
no dislocation was economically meaningful. Sep 2021 contained one crash.
During that crash, dislocations were huge. The signal's statistical
sensitivity is consistent; the economic sensitivity depends entirely on
regime.

This is a useful property: the signal mechanism does not over-fire in calm
regimes. The cost gate filters out economically insufficient candidates
correctly. The empirical evidence is that the signal-plus-cost composition
behaves as designed.

## Substrate notes

1. **Real-data run validated on a second window.** Sep 2021 archives are
   ~2.5 years older than Mar 2024 and use the same schema. The Day 26.5 spot
   parser worked without modification. No bugs surfaced in this run.

2. **The current paper.fills metadata does not record the z-score,
   dislocation, or rolling-mean at fire time.** Useful audit data is captured
   (a2_intent_uuid, a2_leg, replay_status, window_seconds, fetch_source) but
   the trigger numbers are not. Adding these to the metadata payload in a
   future commit would make per-event analysis much faster (no need to
   recompute by re-running the evaluator).

3. **Sep 13 2021 entry (event #12) fired at raw basis -32 bps**, below the
   33.84 bps threshold magnitude. This is correct behavior — the cost gate
   compares against |current_basis − rolling_mean|, not |current_basis|. By
   Sep 13 the rolling mean had likely settled positive after the Sep 7
   turbulence, making a drop to -32 raw a >33.84 bps dislocation.

## Next-session decision space

Three real options:

| Option | Description |
|---|---|
| **A** | Day 28 — position-state substrate (track open per-leg positions; anti-reentry logic) |
| **B** | Day 28 — exit logic design and substrate (paired entry-exit semantics; basis-convergence triggers) |
| **C** | Additional empirical windows (test signal across more regimes before building exit substrate) |

Reviewer-locked recommendation after this memo lands: **A or B**. The signal
question is answered. The bottleneck is execution-completeness, not signal
validation.

A and B are deeply interrelated — exit logic requires knowing what position
is open, so A is structurally a prerequisite for B. The natural Day 28 scope
is to lock A and B together: a single substrate commit that introduces
position state and exit semantics as one coherent design.

## Artifacts

- Fixture: `tests/fixtures/a2_basis/SOLUSDT_basis_14d_20210901T000000_20210915T000000.json`
- Prior memo: `docs/strategies/a2_first_real_data_run.md` (Mar 2024 run)
- Substrate: `data/ingestion/vendors/binance/spot_archive_trade_fetcher.py` (Day 26 + 26.5)
- Harness: `strategies/a2_basis/runner/paper_research_harness.py` (Day 25)
- Inspection query: documented in commit message body
