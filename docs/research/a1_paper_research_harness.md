# A1 PAPER_RESEARCH operator harness (Day 20.5)

Day 20.5 makes `A1PaperResearchRunner` (Day 20.4) operator-callable
from the CLI. No new economics, no new infrastructure — just the
glue that lets an operator sweep fixtures without writing more
integration tests for each hypothesis.

## Usage

```
python -m strategies.a1_funding.runner.paper_research_harness \
    --fixture tests/fixtures/binance_funding/SOLUSDT_14d_20240301T000000_20240315T000000.json \
    --symbol SOLUSDT \
    --quantity 10.0
```

Output is JSON to stdout. Default is compact; pass `--pretty` for
indented output suitable for human inspection.

## What it produces

```json
{
  "fixture": "...",
  "symbol": "SOLUSDT",
  "quantity_per_intent": "10.0",
  "cost_profile_name": "binance_vip5_alt_research_v1",
  "source_mode": "PAPER_RESEARCH",
  "events_loaded": 43,
  "events_skipped_below_lookback": 12,
  "events_skipped_below_threshold": 31,
  "events_skipped_zero_funding": 0,
  "events_skipped_no_reference_price": 0,
  "intents_fired": 0,
  "paper_fills_before": 0,
  "paper_fills_after": 0,
  "observed_slippage_non_null": 0,
  "observed_slippage_null": 0,
  "median_observed_slippage_bps": null,
  "p90_observed_slippage_bps": null,
  "trading_fills_before": 0,
  "trading_fills_after": 0
}
```

JSON-by-default is intentional: it makes fixture sweeps scriptable.
Pipe to `jq`, accumulate across multiple `--fixture` runs, build
spreadsheets.

## What it does NOT do

Hard constraints (reviewer-locked):

- **No network calls.** The harness uses a `NoopFetcher` that returns
  no trades. `decision_reference_price` comes from `event.mark_price`;
  events without `mark_price` are skipped (`skipped_no_reference_price`).
- **No archive fetcher.** Real tape replay belongs to Day 20.5C
  (network/archive integration); explicitly not this commit.
- **No accounting writes.** Funding-payment accrual remains deferred
  (reviewer Q4.F).
- **No trading.fills writes.** Day 20.4's firewall holds; the harness
  reports `trading_fills_before == trading_fills_after` as evidence.
- **No new logic.** All economic decisions go through
  `A1PaperResearchRunner` (composition).

## Idempotent registry bootstrap

The harness uses stable codes for registry rows (`a1_paper_research`
strategy, `paper_research_portfolio`, `paper_research_account`,
`binance` venue, `<symbol>_paper_research` instrument) and bootstraps
them via get-or-create semantics. This differs from
`_setup_basic_0009`, which is test-scoped and uses random UUID
suffixes for isolation.

The result: running the harness 100 times against the same fixture
produces one strategy row, one portfolio row, etc., and many
paper.fills rows (one per fired intent per run, deduped via
deterministic UUIDs from Day 20.4).

Idempotency is verified by
`test_harness_registry_bootstrap_is_idempotent`.

## Per-run slippage stats

`median_observed_slippage_bps` and `p90_observed_slippage_bps` are
computed via the Day 20.2 aggregator, filtered by `instrument_id` and
windowed to this run's funding-time range (widened by ±1s to avoid
boundary-exclusive edge effects). This gives consistent semantics
with offline aggregation:

```
analytics.slippage_calibration.compute_slippage_calibration(
    conn,
    instrument_id=...,
    window_start=run_start - 1s,
    window_end=run_end + 1s,
)
```

If no fills were written this run, both stats are `null` and the
counts are 0.

## Empirical finding (real SOL Mar 2024 fixture)

Captured by `test_harness_real_sol_fixture_matches_day_20_4_finding`:

| Field | Value |
| --- | --- |
| events_loaded | 43 |
| events_skipped_below_lookback | 12 |
| events_skipped_below_threshold | 31 |
| intents_fired | 0 |
| paper_fills_after | 0 |
| trading_fills delta | 0 |

This corroborates the Day 18b structural finding (rolling-12 forecast
peaks at ~7.69 bps, below the 7.7 bps research threshold) and the
Day 20.4 commit body's empirical evidence. The harness is now the
operator's tool to retest this finding against any new fixture.

## Day 20.5B / 20.5C scope

Beyond Day 20.5:

- **20.5B (Fixture sweep):** Build new fixtures for plausibly higher-
  funding windows (e.g. May/June 2024 SOL); use this harness to
  sweep them and document fire counts.
- **20.5C (Network/archive integration):** Wire the
  `BinanceArchiveTradeFetcher` (Day 19c.1) into the harness so it can
  do real tape-grounded replay observation. Requires `@pytest.mark.
  network` discipline.

Both are deferred from Day 20.5 to keep the operator loop clean and
local-first.

## Sources

- Day 20.1 commit (`9193b65`): `paper.fills` writer
- Day 20.2 commit (`b2b17bc`): slippage calibration aggregator
- Day 20.3a commit (`d9fd108`): replay observation machinery
- Day 20.4 commit (`fd9bea7`): A1 PAPER_RESEARCH runner
- Day 18b finding (`tests/integration/test_a1_paper_runner_backfill_real.py`)
