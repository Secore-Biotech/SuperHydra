# A1 PAPER_RESEARCH runner (Day 20.4)

This memo documents the operational role of `A1PaperResearchRunner`,
the first runner-touching commit in the Day 20 evidence-pipeline arc.

## Position in the evidence ladder

Day 20.4 is the producer that closes the previously-empty producer slot
in the Day 20 evidence pipeline:

| Layer | Module | Role |
| --- | --- | --- |
| Producer | `A1PaperResearchRunner` (Day 20.4) | Build intents from funding events |
| Orchestrator | `replay_intents()` (Day 20.3a) | Fetch + observe + write per intent |
| Writer | `write_paper_fill()` (Day 20.1) | Append-only, hash-mismatch-aware INSERT |
| Aggregator | `compute_slippage_calibration()` (Day 20.2) | Median + p90 over written rows |

Before Day 20.4, the pipeline had no production caller — tests
constructed intents directly. After Day 20.4, A1 produces them under
the research-firewalled cost profile.

## Composition shape, not inheritance

The runner composes existing pure functions:

- `expected_next_funding(window, *, discount_k, min_lookback, as_of)`
  from `strategies.a1_funding.signal.expected_funding`
- `evaluate_signal(forecast, cost_model, *, slippage_tier_name,
  funding_intervals_per_day)` from `strategies.a1_funding.signal.evaluate`
- `select_research_profile_for_a1(instrument, venue)` from
  `strategies.a1_funding.config.profile_selector` (the explicit
  firewall hole added in this commit)
- `replay_intents(conn, intents, *, fetcher, fetch_source)` from
  `execution.paper.replay_runner`

It does NOT inherit from `A1PaperRunner`, import any helper from
`A1PaperRunner`, or delegate work to `A1PaperRunner`. The class
boundary is the operational firewall.

## Explicit firewall hole: `select_research_profile_for_a1`

The Day 19a selector firewall (`TestResearchProfileFirewall`) asserts
that no input to `select_profile_for_a1` returns a research-named
profile. Day 20.4 adds an explicit second function,
`select_research_profile_for_a1`, that DOES return research profiles —
specifically for use in PAPER_RESEARCH paper.fills writes.

The function is named with `_research_` in the path so the firewall
hole is visible at every call site `grep -r "select_research_profile"
.` would find. The default selector remains the canonical, governance-
safe entry point.

The firewall regression test
`TestResearchProfileFirewallStillHolds` verifies that adding the
explicit-access function did not affect the default selector's
firewall property.

## Skip taxonomy

A funding event is **skipped** (no fill row, no intent constructed)
under any of these conditions:

| Skip class | Condition | RunSummary counter |
| --- | --- | --- |
| Below lookback | i < forecast_window_size (insufficient prior history) | `skipped_below_lookback` |
| No edge | `SignalDecision.FLAT` from evaluator | `skipped_no_edge` |
| Zero funding | forecast_rate exactly 0 (defensive, redundant with FLAT) | `skipped_zero_funding` |
| No reference price | mark_price absent AND no trades near funding_time | `skipped_no_reference` |

The first three are pre-intent decisions: the runner does not construct
a PaperReplayIntent or call replay_intents. No fill row is written.

The fourth (no reference price) is also a pre-intent skip. It is
distinct from the Day 20.3a observation-window failures (`empty_window`
and `fetch_error`), which DO produce fill rows (with NULL
observed_slippage_bps). The difference is meaningful:

- **Reference-price unavailable** (Day 20.4): we couldn't decide what
  the fill would have been measured against. There is no economically
  meaningful row to write. Skip.
- **Observation-window empty** (Day 20.3a): we DID decide on a fill
  hypothesis, but couldn't observe what would have happened. Write a
  row with NULL observed_slippage_bps; future observation may re-fill it.

## Reference price resolution

Per Day 20.3a, `decision_reference_price` is the price at
signal-evaluation time, NOT fill time. The runner resolves it in this
order:

1. **`event.mark_price`** if present in the FundingRate record. Binance
   typically provides this. No additional fetcher call.
2. **Closest trade within ±1 second** of `event.funding_time`, fetched
   via the injected `TradeFetcher`. The closest trade by absolute time
   delta is used.
3. **None → event skipped** (`skipped_no_reference` counter).

The fallback fetch is bounded to ±1s to avoid using prices from too
far away. This is intentionally a different (tighter) window than the
±5s observation window: the reference is meant to be a snapshot, not
a worst-case over an interval.

## Idempotency

`paper_fill_uuid` is derived deterministically from the funding event:

```
canonical = "a1_paper_research|{strategy_id}|{venue}|{instrument}|{funding_time_iso}"
uuid = UUID(bytes=sha256(canonical)[:16])
```

The Day 20.1 writer's `(paper_fill_uuid, content_hash)` idempotency
then handles re-runs: same UUID + same content = silent no-op; same
UUID + different content = `FillIntegrityError`.

Changing `strategy_id` between runs intentionally produces different
UUIDs (different audit lineage). The same funding event under two
distinct strategies is two distinct paper.fills rows.

## Firewall constraints, restated

The runner enforces every Day 20.1 reviewer-locked constraint:

1. **Never imports A1PaperRunner.** Verified by source grep at module
   load time.
2. **Never writes `trading.fills`.** Test:
   `test_runner_does_not_touch_trading_fills` asserts row count
   unchanged.
3. **Never writes `accounting.funding_payments`.** Day 20.5+ scope, not
   here. The runner imports nothing from accounting modules.
4. **`source_mode = 'PAPER_RESEARCH'` always.** Enforced by writer +
   DB CHECK constraint.
5. **`promotion_eligible = false` always.** Enforced by writer + DB
   CHECK constraint (`paper_fills_research_no_promotion`).
6. **Uses research-firewalled profile via the explicit hole.** Default
   resolution uses `select_research_profile_for_a1(symbol, "binance")`;
   caller may override for tests.

## Real SOL Mar 2024 fixture: research-grade evidence

The integration test
`test_real_sol_mar_2024_fixture_firewall_holds` loads the existing
14-day SOL fixture and exercises the runner end-to-end. The test does
NOT assert a specific fire count — it asserts only that:

- Every written row has `source_mode='PAPER_RESEARCH'` and
  `promotion_eligible=false`
- `trading.fills` row count is unchanged

The actual fire count is logged as research evidence. Per Day 18b's
finding, the rolling-12 forecast over SOL Mar 2024 peaks at ~7.69 bps,
which is just below the research threshold of ~7.7 bps. Whether the
runner fires 0, 1, or a small number of intents on this fixture is
**itself a finding**, not something to assert against.

If the runner fires 0 intents, that confirms the structural finding
that current fixtures do not produce sustained-edge windows under the
research profile. If it fires some, that is empirical evidence about
those specific intervals.

## Synthetic high-funding fixture: positive-path verification

`test_synthetic_high_funding_fires_intents` constructs 20 events at
sustained 10 bps funding (clearing the 7.7 bps threshold). The first
12 are skipped below lookback; events 13-20 should fire.

This is the positive-path test that verifies the runner correctly
constructs intents and routes them through replay_intents when the
input data does clear the research threshold.

## Day 20.5+ scope

Beyond Day 20.4:

- **Accounting integration**: funding_payments accrual when a research
  fill is written. Deferred per reviewer Q4.F.
- **Live data source**: produce funding events from a live data feed
  instead of fixtures. Significant new infrastructure.
- **Live A1 paper-fill recording (rung 5)**: the actual promotion-grade
  evidence path. Requires venue paper-trading or testnet integration.

## Sources

- Day 20.1 commit (`9193b65`): paper.fills writer and schema
- Day 20.2 commit (`b2b17bc`): slippage calibration aggregator
- Day 20.3a commit (`d9fd108`): replay observation machinery
- Day 19a memo (`docs/research/sol_slippage_calibration_memo.md`)
- Day 19c.3 memo (`docs/research/sol_roll_spread_estimation_memo.md`)
- Day 20.3a memo (`docs/research/replay_slippage_methodology.md`)

## SOLUSDT May 2024 candidate sweep (Day 20.5B)

Following the Day 20.5 harness landing, we ran the first candidate-
fixture sweep against `SOLUSDT_14d_20240501T000000_20240515T000000.json`
(refreshed via the existing `scripts/refresh_binance_funding_fixture.py`,
no new network code). The reviewer-locked hypothesis was: do any
14-day SOL windows besides Mar 2024 produce sustained funding above
the 7.7 bps research threshold?

### Harness output

```json
{
  "cost_profile_name": "binance_vip5_alt_research_v1",
  "events_loaded": 43,
  "events_skipped_below_lookback": 12,
  "events_skipped_below_threshold": 31,
  "events_skipped_no_reference_price": 0,
  "events_skipped_zero_funding": 0,
  "fixture": "tests/fixtures/binance_funding/SOLUSDT_14d_20240501T000000_20240515T000000.json",
  "intents_fired": 0,
  "median_observed_slippage_bps": null,
  "observed_slippage_non_null": 0,
  "observed_slippage_null": 0,
  "p90_observed_slippage_bps": null,
  "paper_fills_after": 0,
  "paper_fills_before": 0,
  "quantity_per_intent": "10.0",
  "source_mode": "PAPER_RESEARCH",
  "symbol": "SOLUSDT",
  "trading_fills_after": 0,
  "trading_fills_before": 0
}
```

### Diagnostic: funding-rate distribution

| Window | n | Min | Max | Mean | Rolling-12 forecast max | Threshold | Gap |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Mar 1-15 2024 | 43 | (~6 bps mean) | ~10+ bps | ~6 bps | **~7.69 bps** | 7.7 bps | Near-miss (~0.01 bps below) |
| **May 1-15 2024** | **43** | **-0.88 bps** | **+1.00 bps** | **0.51 bps** | **0.46 bps** | **7.7 bps** | **~7.24 bps below — order of magnitude** |

### Reading the finding

The two zero-fire results are not the same outcome.

- **Mar 2024** was a near-miss. Sustained mean ~6 bps, peak realized
  funding above 10 bps, rolling-12 forecast peaking at ~7.69 bps —
  just barely below the 7.7 bps research threshold. The structural
  finding (Day 18b) was that this window is on the threshold edge.

- **May 2024** is structurally far from clearing. Mean 0.51 bps, max
  realized 1.00 bps, rolling-12 forecast peak 0.46 bps. The market
  was simply in a low-carry regime; threshold is not the issue, the
  regime is.

This means SOL funding regimes vary substantially across short
periods. Only "high-carry" regimes approach the research threshold.
Most periods, including May 2024, are an order of magnitude below.

### Implications for Day 20.5C

The reviewer's pre-sweep decision gate stated: if intents_fired == 0
across all candidates, 20.5B closes with a negative finding and 20.5C
is deferred. That gate is met for the single-candidate sweep.

A future Day could expand the sweep to identify other high-carry
windows beyond Mar 2024. Plausible candidates worth probing:

- **2021 SOL run** (Sep-Nov 2021), historical high-funding period
- **2024 SOL Q1 broader** (Feb-Apr 2024), bracketing Mar 2024
- **Any post-2023 mania periods** where SOL perp had sustained skew

Tape replay (20.5C) only adds value if we have a fixture window
where intents fire. Until then it would replay against no fills.

### Operating posture

The infrastructure is correct. The runner is honest. The empirical
evidence shows that SOL funding does not reliably clear the research
threshold under sustained 14-day windows; the Mar 2024 edge-case
finding was not coincidence but also was not regime-typical.

Two operational reads, both honest:

1. **Threshold is correctly calibrated to be selective.** The
   research profile threshold of 7.7 bps is high enough that only
   genuinely-sustained funding regimes clear it. SOL's average
   regime is structurally below.
2. **A1 funding-rate capture on SOL alone is regime-dependent.**
   Profitable windows exist (Mar 2024 edge-case-style mean ~6 bps)
   but are not the typical case. Production A1 on SOL would need
   regime detection or instrument diversification, neither of
   which is in current Day 20 scope.

Both reads are consistent with the operating premise of A1 as a
selective capture strategy. They argue against tape replay on
low-carry data and for sweeping more historical periods to
characterize the carry-regime distribution.
