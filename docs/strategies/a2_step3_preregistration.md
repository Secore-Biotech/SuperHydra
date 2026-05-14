# A2 Step 3 — Pre-Registered Normal-Regime Test

**Committed:** 2026-05-14
**Status:** committed before any Step 3 run has been executed.
**Reviewer:** required to approve before run.

## Why this document exists

Today's investigation established that A2's headline "55 bps mean net P&L"
result was an artifact of a single 2021-09-07 stress event combined with
silent infrastructure failures (NoopFetcher, no observed slippage). The
infrastructure is now sound. The strategy itself remains unmeasured in
any normal-regime sense.

This document commits — in advance of running — to the next test's
specification and the decision rules that follow from each possible result.
No post-hoc rationalisation of the result is permitted.

## Hypothesis under test

A2 can earn measurable net P&L in a normal-volatility basis regime on
SOLUSDT (perp + spot, Binance), distinct from the stress-event P&L
artifact of the Sep 2021 El Salvador liquidation cascade.

## Test specification

| Parameter | Value |
|---|---|
| Universe | SOLUSDT (perp + spot, Binance) |
| Window | 2023-10-01 00:00:00 UTC → 2023-10-15 00:00:00 UTC |
| Window rationale | Moderate-vol SOL period, post-FTX recovery, no known major events |
| Fetcher | Real Binance trade fetcher REQUIRED. --allow-noop-fetcher is INVALID for this test. Any run producing the [MODELED-ONLY] label is non-decision-grade and does not satisfy Step 3. |
| Slippage measurement | Observed slippage in bps populated on every fill |
| Cost assumption | Binance perp taker 4.5 bps + spot taker 10.0 bps = 14.5 bps round-trip fees, applied independently of observed slippage |
| Per-trade P&L computation | Gross P&L - fees - observed slippage = net P&L (bps) |
| Pre-run expected basis vol stdev | 2.5–5.0 bps (between Mar 2024 = 2.10 and Sep 2021 = 7.54) |
| Pre-run expected entries | 0–10, depending on threshold calibration |

## Pre-committed kill criteria

| Outcome | Decision |
|---|---|
| 0 entries fired | Strategy is purely a stress-event harvester. Recommend pivot to a different signal family or shelve A2. |
| 1–3 entries, mean net P&L (after fees + observed slippage) ≤ 0 bps | No normal-regime edge demonstrated. Recommend pivot or shelving. |
| 1–3 entries, mean net P&L > 0 bps | Insufficient sample. Do not promote. Justify expanded multi-window test (≥20 windows). |
| ≥4 entries, mean net P&L between 0 and +5 bps after costs | Marginal. Discuss with reviewer before allocating more research time. |
| ≥4 entries, mean net P&L > +5 bps after costs | Promising. Justify expanded multi-window test with in-sample/out-of-sample split. |

## Reporting requirements

The Step 3 output memo must include:

- `run_id`, fetcher class name (must be the real Binance fetcher, not _NoopFetcher), window timestamps
- Per-trade table: entry/exit timestamps, perp/spot prices, gross P&L,
  observed slippage bps (perp and spot legs separately), fees bps, net P&L bps
- Per-trade duration (entry → exit elapsed time)
- Distribution: mean, median, stdev, min, max of net P&L bps
- Cross-reference: confirm no fill fell within the Sep 2021 stress window
  or any other pre-identified stress window (build a stress registry as
  followup if needed)
- Explicit kill-criterion evaluation: name the row of the table above
  that applies, and state the resulting recommendation

## Anti-cherry-pick protection

If this test produces a null or negative result, the response is the
documented kill action. The temptation to "try a different window because
2023-10 might have been unusually quiet" is forbidden by this document.
A different window may be a Step 4, but it must be its own pre-registered
test with its own kill criteria, and Step 3's result must be reported and
preserved regardless.

## Sequencing

1. This document is committed to repo before any Step 3 run.
2. Real Binance trade fetcher is implemented and tested.
3. Step 3 is executed exactly once.
4. Result is recorded and the kill criterion is applied.
5. Subsequent steps (Step 4 multi-window, or strategy pivot) are pre-
   registered as their own documents.
