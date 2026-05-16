# A2 Perp-vs-Spot Basis — Kill Action

**Committed:** 2026-05-16
**Author:** Operator
**Status:** A2 perp-vs-spot basis is shelved as currently specified.

## Headline

A2 perp-vs-spot basis is shelved as currently specified. The pre-registered Step 3 normal-regime test produced zero entries on the only window committed to be tested. Per the pre-registration's anti-cherry-pick rule, no further fixture hunting, threshold tuning, or window selection under this specification is permitted. Future A2 work requires a new pre-registered hypothesis.

## Reclassification

A2's practical status, going forward, is:

- signal-positive under stress
- execution-unmeasured under stress
- inactive in normal regimes
- not paper-gate eligible
- shelved as currently specified

## Why the strategy was shelved

A2 was shelved because:

1. **Normal-regime Step 3 produced zero entries.** SOLUSDT 2023-10-01..15, basis stdev 3.17 bps, max raw basis −33.66 bps, zero observations exceeded the 33.84 bps cost-anchored entry threshold.
2. **Stress-regime positives depended on liquidation conditions.** The headline Sep 2021 finding (8 closed trades, mean net 55 bps conservative) was confined to a 70-minute SOL liquidation cascade on 2021-09-07; 7 of 8 trades fired during that window.
3. **Realistic execution during those stress windows is unmeasured and unreliable.** Sep 2021 fills had `observed_slippage_bps = NULL` and `replay_status = empty_window` across all 32 fills (test-stub leakage via `_NoopFetcher`); even with real fills, the regime had widened spreads, degraded depth, and exchange rate-limiting that make retail-scale execution doubtful.
4. **The strategy therefore failed the pre-registered viability gate.** The pre-registration's kill criterion for "0 entries fired" is binding: "Strategy is purely a stress-event harvester. Recommend pivot to a different signal family or shelve A2."

A2 occupies a narrow band: it only fires when execution is hardest. The cost-anchored threshold ensures trades clear costs in expectation, but in normal regimes the threshold is never reached, and in stress regimes when it is reached, execution viability is the binding constraint rather than signal quality.

## Evidence trail

The full empirical record:

- `docs/strategies/a2_first_real_data_run.md` (Day 27A) — SOL Mar 2024: zero entries on first real-data window
- `docs/strategies/a2_sep_2021_signal_positive.md` (Day 27B) — SOL Sep 2021: 12 substrate-only entries, signal-positive execution-incomplete
- `docs/strategies/a2_complete_trade_results.md` (Day 28b.3 corrected) — 8 closed trades, status: signal-positive execution-unmeasured, not paper-gate eligible
- `docs/strategies/a2_step3_preregistration.md` (committed before Step 3 run) — kill criteria pre-committed
- `docs/strategies/a2_step3_result.md` (Step 3) — zero entries, kill criterion triggered

## What survives

The following infrastructure was built during A2 development and is fully reusable by any future strategy work. The infrastructure investment is preserved; the strategy hypothesis is rejected:

- **Archive ingestion**: `BinanceArchiveTradeFetcher` (perp), `BinanceSpotArchiveTradeFetcher` (spot)
- **Paired basis fixture generation**: `scripts/refresh_a2_basis_fixture.py` and the pairing logic
- **paper.fills infrastructure**: migration 0010, the writer with hash-match silent no-op, content-hash idempotency
- **Replay observation machinery**: `execution/paper/replay_runner.py`, `compute_observed_slippage`, the TradeFetcher protocol
- **Position-state substrate**: migration 0011 `paper.positions`, `open_position`/`close_position`/`paper_position_count` helpers
- **Exit evaluator framework**: `strategies/a2_basis/signal/evaluate_exit.py` — pure decision module, six structured reasons, easy to lift into another strategy
- **Operator harness patterns**: `paper_research_harness.py`, JSON output, nested per-leg blocks, `run_id` tagging for multi-run isolation
- **Empirical close-out methodology**: `scripts/empirical_a2_complete_trade_results.py` with the `--allow-noop-fetcher` gate and the `[MODELED-ONLY / NON-DECISION-GRADE]` slippage guard
- **Advisor review checklist**: `docs/advisor_review_checklist.md` — CI-enforceable rule against test-stub leakage in empirical scripts
- **Leg-routing fetcher**: `A2DualFetcher` — composes perp + spot fetchers via the TradeFetcher protocol; reusable for any two-leg strategy

The conclusion is not "wasted work." It is: **strategy hypothesis rejected, research substrate validated**.

## What is shelved

The A2-specific components remain in the repo as a completed research artifact but receive no further development:

- `strategies/a2_basis/signal/evaluate.py` — the z-score entry evaluator with cost-anchored dislocation threshold
- A2-specific runner logic in `paper_research_runner.py` (the interleaved entry/exit loop is reusable; the SOL-specific cost threshold and signal config are A2)
- A2 cost model parameters (33.84 bps for SOL, 24.24 bps for BTC)
- A2 fixtures (Mar 2024, Sep 2021, Oct 2023, and the synthetic test fixtures)

## What this does NOT mean

- It does not invalidate the pre-registration discipline. The discipline is what made this result a definitive answer rather than ongoing research drift.
- It does not invalidate basis trading generally. A different basis-trade specification (different threshold mechanism, different signal family, different universe, different cost model) is a separate hypothesis with its own kill criteria.
- It does not invalidate the infrastructure. See "What survives" above.
- It does not foreclose a future A2 re-opening. See "Conditions for re-opening" below.

## Conditions for re-opening

A2 can be re-opened only if:

1. A new pre-registered hypothesis exists (`docs/strategies/a2_v2_preregistration.md` or similar) committed before any new run.
2. The new hypothesis must specify a materially different mechanism than the current cost-anchored z-score signal: e.g., a different signal family, a different cost model, a different universe (instrument set), or a different execution layer.
3. Threshold tuning alone is not a new hypothesis. Lowering the 33.84 bps threshold to manufacture entries on the existing Step 3 window is explicitly forbidden by the original pre-registration's anti-cherry-pick rule.
4. The new pre-registration must include its own kill criteria, written before the test runs.

## Implications for roadmap v2.2

Sleeve A as currently specified (carry/funding/basis with three engines):

- **A1 (funding-rate capture)**: classification "research/strategy-unproven" per Day 20.7 memo; no canary-ready engine yet
- **A2 (perp-vs-spot basis)**: shelved per this memo
- **A3 (cash-and-carry)**: deferred (futures-venue onboarding not warranted on day one)

Sleeve A has produced zero canary-ready engines after seventeen commits of focused A2 work. The roadmap v2.2 live target (2.4–2.5+ Sharpe) was anchored on Sleeve A as the stabilizer + Sleeve B as the primary engine. With A2 shelved and A1 unproven, the Sleeve A premise needs reconsideration. This memo does not amend the roadmap; the roadmap update is deferred to a separate decision.

## What was learned

Three durable lessons from the A2 arc:

1. **Cost-anchored thresholds can create a "fires-only-when-untradable" pathology.** A threshold tuned to ensure trades clear realistic costs (cost + safety margin) sits well above normal-regime basis dislocations. The strategy then fires only in stress regimes, which are precisely the conditions where execution is hardest. This is not a property of the threshold itself; it is a property of the signal-cost relationship in this asset and venue combination.

2. **Substrate-only findings are not decision-grade.** The Day 27B Sep 2021 finding ("12 entries on the crash") looked positive but was not closed trades, not P&L, not slippage-measured. The Day 28b.3 corrected memo demonstrated that the apparent "55 bps mean net P&L" was an artifact of `_NoopFetcher` returning empty trade lists, not real edge. **Counting entries is not measuring performance.**

3. **Test-stub leakage is a real failure mode.** A test-only `_NoopFetcher` silently substituting for a real fetcher produced what looked like a positive headline result for several days. The `[MODELED-ONLY / NON-DECISION-GRADE]` labelling guard and the advisor checklist now prevent recurrence; both are durable governance artifacts that outlive A2.

The pre-registration discipline (commit `8ee5ecb`, May 14) is what turned an initially positive-looking result into a definitively negative answer. Without it, the natural path would have been to chase another window, lower the threshold, or rationalize the stress-only firing pattern. The discipline held; the answer is final.

## Next step

Per reviewer decision, the next research effort is Sleeve B (market-neutral long/short), not A1 retry, not A3 onboarding. Sleeve B was supposed to run in parallel with Sleeve A from week 1 per roadmap v2.2 and has not yet been exercised. The next artifact is a Sleeve B pre-registration memo specifying the signal family and kill criterion before any implementation.

## Source commits

- `00a2f87` Day 21: A2 design brief
- `d45ffa6` Day 22: cost model
- `cd4c0e5` Day 23: z-score signal evaluator
- `38e4cd1` Day 24: PAPER_RESEARCH runner
- `82c9133` Day 25: operator CLI harness
- `2ea7e63` Day 26: real basis data ingestion
- `29c3ed4` Day 26.5 + Day 27(A): spot parser fix + Mar 2024 zero-fire
- `c6cae17` Day 27(B): Sep 2021 signal-positive (substrate-only)
- `0c420b1` Day 28a: position state + hard-block anti-reentry
- `4f49794` Day 28b.1: pure exit evaluator
- `73dc273` Day 28b.2: interleaved entry/exit loop + P&L
- `e0b5550` Day 28b.3: empirical close-out (corrected memo)
- `8ee5ecb` Step 3 pre-registration
- `7225ecc` Step 2: A2DualFetcher + leg-specific symbols
- `75ca27d` Step 3 result: kill criterion triggered

---

*A2 is shelved. The infrastructure is preserved. The pre-registration discipline made this result count.*
