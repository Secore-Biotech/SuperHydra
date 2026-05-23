# 0009 — DURABLE HANDOFF FOR V1.11 DRAFTING

## Status
- Structural design phase, 10 reviewer rounds complete
- Latest design: v1.10 (this conversation)
- Latest reviewer feedback: R11 (1 patch + 2 sub-questions)
- v1.11 not yet drafted
- SQL drafting has NOT begun. Reviewer has approved-in-principle for 4 rounds (v1.7, v1.8, v1.9, v1.10), each contingent on one more structural patch.
- All schema verification complete except `mark_price_set_items` uniqueness query (non-blocking)

## Where this lives
Save this document to `docs/migrations/0009_v1_10_handoff.md`. Save R11's reviewer response (the cancel-remaining-quantity feedback) alongside it as `docs/migrations/0009_R11_feedback.md`. The next session opens by reading both.

## DB state
- alembic head: `0008` 
- 51 tables, 58 functions across registry/accounting/trading/positions
- risk schema exists (created in 0001), empty
- All schema verifications cited below were run against this state

## Verified schema dependencies (do not re-derive)

**positions.position_snapshots** (bigint id):
portfolio_id, strategy_id, account_id, instrument_id, quantity NUMERIC(38,18), avg_cost_basis NUMERIC(38,18) NULL, realized_pnl_usd, position_environment TEXT, snapshot_at TIMESTAMPTZ, fill_cutoff_at TIMESTAMPTZ, last_fill_id BIGINT NULL

**accounting.mark_price_sets** (uuid id):
id, set_hash, purpose, created_by, created_at. NO as_of_at column.

**accounting.mark_prices** (bigint id):
instrument_id, mark_type, price NUMERIC, source_timestamp TIMESTAMPTZ, source, source_namespace, source_id, confidence, raw_record_hash, created_at. **NO UNIQUE beyond PK.**

**accounting.mark_price_set_items**:
mark_price_set_id UUID NOT NULL, mark_price_id BIGINT NOT NULL, created_at. UNIQUE constraints not yet verified — query is in carry-forward list.

**accounting.nav_snapshots** (bigint id):
valuation_run_id UUID, portfolio_id, strategy_id NULL, snapshot_date DATE, nav_total, nav_realized, nav_unrealized, nav_accrued_funding, nav_accrued_fees, nav_accrued_borrow, nav_breakdown, twr_daily, deposits_today, withdrawals_today, nav_environment TEXT, nav_settlement_type TEXT, computation_metadata JSONB, created_at. **UNIQUE on (valuation_run_id, portfolio_id, strategy_id, snapshot_date) NULLS NOT DISTINCT.**

**accounting.valuation_runs** (uuid id):
portfolio_id BIGINT, run_type TEXT, valuation_date DATE, mark_price_set_id UUID NOT NULL, journal_cutoff_at TIMESTAMPTZ, engine_version, calculation_hash, run_metadata, created_by, created_at. **NO UNIQUE beyond PK** — multiple runs per portfolio per date are allowed.

**accounting.strategy_pnl** (bigint id):
valuation_run_id UUID, strategy_id, portfolio_id, pnl_date DATE, pnl_realized_gross, pnl_unrealized, pnl_fees, pnl_funding, pnl_borrow, pnl_total, pnl_type, pnl_environment, pnl_settlement_type, created_at.

**Existing controlled function risk can call:**
`positions.compute_position_snapshot(p_portfolio_id, p_strategy_id, p_account_id, p_instrument_id, p_position_environment, p_snapshot_at, p_fill_cutoff_at, p_computation_version, p_created_by, p_metadata DEFAULT '{}')`

## Architecture summary (v1.10 locked)

| Item | Count |
|---|---|
| Tables | 9 |
| Controlled write functions | 6 |
| Read helpers | 3 |
| Trigger functions (projected) | ~14 |
| Total functions in risk schema | ~23 |
| Supported limit dimensions | 3 (max_position_quantity, max_notional_usd, max_drawdown_usd) |
| Declared-but-not-enforced dimensions | 2 (max_leverage, max_concentration_pct) |
| Circuit breaker actions | 4 (warn_only, block_new_risk, throttle, hard_stop) |
| Environment isolation | full (LIVE, SHADOW, REPLAY, BACKTEST) |
| Versioning | logical/version split for limits and CBs |
| De-risk-escape-hatch | applied to instrument limits AND drawdown via canonical predicate |
| Action schema | full, including cancel target |

### Tables
1. `risk.limits` (identity-only)
2. `risk.limit_versions` (append-only)
3. `risk.regime_transitions` (append-only)
4. `risk.evaluations` (append-only)
5. `risk.evaluation_inputs` (append-only, typed FK lineage)
6. `risk.evaluation_limit_results` (append-only, one row per applicable limit per evaluation)
7. `risk.circuit_breakers` (identity-only)
8. `risk.circuit_breaker_versions` (append-only)
9. `risk.circuit_breaker_states` (append-only, keyed to breaker identity not version)

### Controlled functions
- `risk.upsert_limit`
- `risk.upsert_circuit_breaker` (auto-creates initial `armed` state on first creation)
- `risk.record_regime_transition`
- `risk.set_circuit_breaker_state`
- `risk.evaluate_action`
- `risk.replay_evaluation`

### Read helpers
- `risk.resolve_active_limit_versions`
- `risk.resolve_active_circuit_breakers`
- `risk.current_regime`

## All accumulated patches across v1.1 → v1.10

(Compact form. Full text in conversation history; this is the consolidated set the next drafter must incorporate.)

**From R1 (v1.1, 17 patches):** all-applicable-limits resolution; advisory-lock interop with positions namespace; logical/version split for limits and CBs; idempotency keys; typed-FK evaluation_inputs lineage; severity bucket + ratio model; regime per-environment scope; retroactive-insert policy for limits and regimes; environment isolation; et al.

**From R2 (v1.2, 6 patches):** dimension×scope compatibility matrix (CHECK at config time); mark as-of triple (mark_price_set_id + source_timestamp + mark_type); UTC `as_of_at → snapshot_date` mapping; aggregate-notional forbidden in v1; reduce-only formalization; verdict taxonomy (allowed/blocked/degraded).

**From R3 (v1.3, 6 patches):** unsupported dimensions in LIVE rejected at config; rename `breaches` → `evaluation_limit_results`; drawdown `nav_window_hash`; CB action taxonomy (warn_only/block_new_risk/throttle/hard_stop); explicit notional formula; regime scope = portfolio NOT NULL + strategy NULLABLE.

**From R3-precision + R4 (v1.4, 8 patches):** marks_source_timestamp ≤ as_of_at; NAV `latest ≤ as_of_date` with staleness bound; missing regime in LIVE → degraded; verdict_raw + verdict_effective split; NAV requires anchor valuation_run_id; mark lookup raises on >1 rows + records exact mark_price_id; mark_price_set_id ↔ valuation_run.mark_price_set_id consistency check; CB states keyed to breaker identity; regime control-plane via CB versions' applies_in_regimes.

**From R5 (v1.5, 3 patches):** drawdown window pinned to anchor's run_type; explicit anchor-run validation; upsert_circuit_breaker auto-creates armed initial state.

**From R6 (v1.6, 1 patch):** instrument-limit de-risk-escape-hatch via blocking BOOLEAN.

**From R7 (v1.7, 1 patch):** one row per applicable limit always; complete outcome matrix.

**From R8 (v1.8, 1 patch):** CB-inclusive verdict resolution.

**From R9 (v1.9, 1 patch + 2 audit additions):** drawdown de-risk-escape-hatch; future-migration constraint for declared-but-not-enforced dimensions; LIVE missing-inputs blocking de-risking documented as intentional fail-closed.

**From R10 (v1.10, 4 patches):** canonical `is_genuinely_risk_reducing` predicate; cancel target semantics with `p_cancel_target_order_id`; predicate applied consistently to drawdown / instrument-limits / CB block_new_risk; result_reason taxonomy refined.

## R11 reviewer feedback — input for v1.11 drafting

**Patch (verbatim):**
> Cancel target effect must use remaining open quantity. For `source_type='cancel'`:
> - `target_remaining_qty := target.quantity - target.filled_quantity`
> - `target_signed_remaining_qty := +target_remaining_qty for buy, -target_remaining_qty for sell`
> - `Q_if_target_remaining_filled := Q + target_signed_remaining_qty`
> - `target_was_reducing := abs(Q_if_target_remaining_filled) < abs(Q) AND (sign(Q_if_target_remaining_filled) = sign(Q) OR Q_if_target_remaining_filled = 0)`
> - `is_genuinely_risk_reducing := NOT target_was_reducing`

**Sub-question 1:** When cancel target's remaining open quantity is zero, three options. Reviewer leans Option C: classify as `is_genuinely_risk_reducing = false`, `result_reason = 'evaluated:cancel_no_effect'`, `blocking = false` unless CB hard_stop applies.

**Sub-question 2:** Make instrument-limit rows for cancel explicit. Add to design: "For source_type='cancel', instrument-scope limits evaluate against current exposure (Q, not new Q'). Cancel's blocking effect is determined by is_genuinely_risk_reducing, computed from canceled order's remaining open quantity."

## Carry-forward conventions (SQL phase)

1. `(transitioned_at, id)` ordering for "latest regime" computations.
2. `(state_transitioned_at, id)` ordering for "latest CB state" computations.
3. `(filled_at, id)` ordering for fill chronology (matches 0008 pattern).
4. Run pre-SQL verification query for `mark_price_set_items` UNIQUE before SQL drafting.

## Open questions still in flight

1. Sign-flip exit-breach result_reason: separate `evaluated:exit_with_flip` or reuse `evaluated:reducing_exit_complete`? (Lean: separate.)
2. Cancel-of-cancel — assumed not possible per 0007 model; document the assumption.
3. Manual source_type semantics — confirmed by reviewer: same flow as intent/order through the canonical predicate.
4. NAV staleness bound default value (lean: 36h LIVE, NULL non-LIVE).
5. Throttle parameters in `circuit_breaker_versions` — lean: JSONB blob, runtime owns interpretation.

## Pacing data (for next-session expectation-setting)

10 structural rounds complete. Patch density: 17, 6, 6, 8, 3, 1, 1, 1, 3, 4. The R6-R11 sequence is "1 patch per round, each catching a different operational-correctness bug in adjacent design terrain." Rate of new bugs found has not decreased. Next-session drafter should NOT expect v1.11 to be final; should expect 1-3 more structural rounds before SQL approval.

After structural approval: 4-6 SQL drafting rounds expected (similar to 0007's 4 rounds and 0008's 5 rounds for similar table/function counts).

## Next-session opening prompt (verbatim, copy-paste ready)

> Continuing 0009 risk migration. Read `docs/migrations/0009_v1_10_handoff.md` and `docs/migrations/0009_R11_feedback.md`. DB at `alembic 0008 (head)`. Run `dbup` if needed.
>
> Draft v1.11 incorporating R11's cancel-remaining-quantity patch plus the two sub-question resolutions (lean Option C for zero-remaining-quantity, lean separate result_reason for sign-flip exits). Hold the holistic audit principle: when applying a fix, audit symmetrical applications across drawdown / instrument-limits / CB block_new_risk / result_reason taxonomy.
>
> If during drafting any new design issue surfaces that wasn't caught by R1-R11, flag it explicitly as "v1.11 self-discovered" and incorporate it.
>
> Send v1.11 to reviewer. Expect 1-3 more structural rounds before SQL drafting begins.
