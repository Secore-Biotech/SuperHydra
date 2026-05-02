# Measurement Policy

**Version:** 1.1
**Effective:** 2026-05-02 (revised from v1.0 same date)
**Author:** Wasseem Katt
**Source:** Lessons from HYDRA postmortem 2026-05-01 plus external review 2026-05-02 identifying REALIZED-only blind spot and SHADOW vs LIVE PnL terminology conflict
**Supersedes:** v1.0 (same date)

This policy codifies the measurement discipline required to prevent the failure modes that produced -$1,073 of HYDRA lifetime losses across five distinct measurement integrity bugs in 24 hours. Every rule below is non-negotiable and applies to all SuperHydra code, paper or live.

## Why v1.1

v1.0 introduced a dangerous blind spot: requiring REALIZED-only PnL for everything would prevent the MM-style measurement fiction but enable a different failure mode where a strategy realizes small winners while letting losers run, producing a clean realized Sharpe while accumulating hidden mark-to-market drawdown. v1.1 distinguishes the contexts where each measurement type applies.

v1.0 also created a terminology conflict: "REALIZED" was defined as cash settled from a venue, but deployment_gates referred to shadow-run modeled fills as REALIZED. v1.1 fixes this with explicit environment and settlement-type fields.

## 1. PnL environment and settlement source typing

Every PnL number produced by SuperHydra carries two orthogonal classifications:

**Environment (`pnl_environment`):**
- `LIVE` -- strategy operating with real capital on a live venue
- `SHADOW` -- strategy operating against live data but with paper adapter producing modeled fills
- `REPLAY` -- strategy operating against historical data for retrospective analysis
- `BACKTEST` -- strategy operating during research-phase walk-forward training/testing

**Settlement type (`pnl_settlement_type`):**
- `CONFIRMED_SETTLED` -- cash actually settled, traceable to a venue fill or on-chain transaction; only valid in LIVE environment
- `MODELED_FILL` -- fill produced by the cost model against live or historical L2 order book; valid in SHADOW, REPLAY, BACKTEST
- `SIMULATED_FILL` -- fill produced without L2 modeling (e.g., assumed mid-price); valid in REPLAY/BACKTEST only and flagged as lower-fidelity
- `UNREALIZED_MTM` -- mark-to-market valuation of an open position at a specific mark price; valid in any environment

The combination matters:
- `LIVE + CONFIRMED_SETTLED` is the only thing that counts toward the deployment-gate Sharpe used for promotion decisions
- `SHADOW + MODELED_FILL` is the basis for shadow-phase Sharpe used to qualify for canary admission
- `LIVE + UNREALIZED_MTM` is the basis for risk monitoring (drawdown state, daily loss limits)
- `BACKTEST + SIMULATED_FILL` is research-phase only and explicitly does not satisfy any gate

## 2. Source-of-truth typing (revised from v1.0)

Every PnL aggregate must additionally tag the realized/unrealized split:
- `REALIZED` -- cash component (closed trades minus fees), regardless of environment
- `UNREALIZED` -- mark-to-market on open positions
- `MIXED` -- combination, with explicit breakdown showing realized $X, unrealized $Y

Aggregate displays must show the breakdown. Collapsed PnL numbers without realized/unrealized typing are forbidden.

## 3. Where each measurement applies

This is the v1.1 corrective for the REALIZED-only blind spot.

**Promotion gates (deployment_gates.md):**
- Sharpe calculation: REALIZED only, with environment and settlement_type appropriate to the gate (LIVE+CONFIRMED_SETTLED for canary->scale; SHADOW+MODELED_FILL for shadow->canary)
- Reasoning: prevents MM-style fiction where placed orders were summed as PnL
- Additional gate criterion: conservative NAV drawdown must also pass (see below)

**Risk monitoring (risk_policy.md):**
- Daily loss limit: change in conservative NAV (REALIZED + UNREALIZED MTM)
- Weekly loss limit: change in conservative NAV
- Drawdown state machine: conservative NAV peak-to-trough
- Margin and liquidation distance: live position state, not realized-only
- Reasoning: a strategy that lets losers run accumulates real exposure that the risk system must see immediately, not after the loss is realized

**Capital allocation (allocator_policy.md):**
- Sleeve sizing decisions: conservative NAV including unrealized
- Reasoning: capital allocated to a sleeve with hidden open losses is over-allocated relative to its true risk profile

**Investor reporting and final NAV:**
- Conservative NAV (REALIZED + UNREALIZED MTM at conservative_exit mark prices per data_policy section on mark types)
- Reasoning: NAV stated to investors must reflect liquidation value, not best-case scenario

**Single rule:** REALIZED-only is the right metric for *confirmed-fill discipline and promotion Sharpe*. Conservative NAV is the right metric for *risk, drawdown, capital allocation, and final reporting*. The two are not in conflict; they answer different questions.

## 4. Confirmed-fill discipline (unchanged from v1.0)

Order placement events and confirmed fills are stored in separate tables: `order_intents` for placements, `fills` for confirmations. PnL aggregations only read from `fills`.

A row in `fills` requires a venue confirmation ID (Binance order ID, Polymarket transaction hash, etc.). Rows without confirmation IDs are rejected at the schema level.

**Maximum lag between placement and fill confirmation:** 60 seconds for live trading, 5 seconds for canary alert thresholds. Beyond 60 seconds, the order is flagged `STALE_NEEDS_RECONCILIATION` and the reconciler must reach out to venue API to determine actual state. Orders that remain unresolved after 5 minutes trigger an operator alert and a halt-new-orders state for the affected strategy.

In SHADOW environment, the same discipline applies but the "venue confirmation" is the modeled-fill record from the paper adapter, which must be deterministic and reproducible from the L2 snapshot used.

## 5. Empty-source safety (unchanged from v1.0)

Any code that reads from a data source must explicitly handle the empty/missing case. Three valid responses:
- Return zero with explicit `source_empty=true` flag
- Raise `NoDataError` exception
- Return None and require caller to handle

**Default behavior for new ledger code: raise `NoDataError`.** Forces caller to handle.

Silent zero returns from missing tables are a P0 bug class. Any code that aggregates over a query result must verify the query returned rows before computing aggregate. The MM measurement fiction (272 placed orders summed as PnL because the fills table was queried wrong) is the canonical anti-example.

## 6. Cross-check requirements (unchanged from v1.0)

Before any new measurement source is trusted:
- 5 or more random samples manually verified against venue records
- Source tagged `VERIFIED` only after manual cross-check signed off by operator (recorded in `measurement_audit` table)
- Sources without verification status are tagged `UNVERIFIED` and flagged in any output that uses them

**Quarterly re-verification required.** A source not re-verified in 90 days reverts to `UNVERIFIED`. Vendor outages or schema changes trigger immediate re-verification regardless of last-verified date.

## 7. Atomic order recording (unchanged from v1.0)

Order submission to a venue and ledger recording must be atomic. Implementation is write-ahead:
1. Ledger row created first with status `SUBMITTING`
2. Venue API called
3. Row updated to `SUBMITTED` with venue ID

If venue call fails, the row remains `SUBMITTING` and triggers reconciler within 60 seconds.

**No bypass paths.** Every order -- strategy-initiated, REPL, debug, manual -- routes through the same OMS write-ahead path. Direct venue API calls without ledger rows are a P0 bug class.

**REPL/debug trades during development:** routed through OMS like any other trade. A separate `paper_repl` strategy slot exists for human-initiated trades. Live REPL trades are forbidden by default and require explicit operator promotion (same gate as a strategy going live).

## 8. Promotion-gated execution (unchanged from v1.0)

No strategy is permitted to execute live without a recorded promotion event in the `promotions` table. Promotion events contain:
- Strategy name
- `promoted_by` (operator ID)
- `promoted_at` (timestamp)
- `promotion_signature` (cryptographic signature of operator)
- `gate_evidence` (link to validation report demonstrating gate criteria met)

A strategy without a current promotion record is forbidden from `submit_order` calls at the OMS layer.

**Signature mechanism:** GPG-signed JSON during paper-only Phases 1-4. Hardware key (Yubikey) required when Phase 5 canary live begins.

## 9. Behavioral coverage (unchanged from v1.0)

Every code path in a strategy must be exercised at least once in test before that path is permitted to fire in production (paper or live). Specifically: open-position logic, close-position logic, stop-loss logic, take-profit logic, and error-handling paths each must have at least one passing integration test.

**Coverage thresholds:**
- Order-touching code paths: 100% required
- Supporting logic (logging, metric emission, configuration): 80% required

Untested code paths are flagged at deployment. Strategy is rejected from promotion if any order-touching path lacks coverage.

## 10. Configuration audit (unchanged from v1.0)

Every flag in config files must be wired to actual code. Unwired flags are deleted, not left as documentation. Quarterly audit verifies docs-to-flags-to-code consistency.

Flag changes are logged to `flag_audit_log` with timestamp, operator, before/after values. Any flag change that affects strategy behavior triggers a re-promotion requirement.

**Re-promotion required for changes to:**
- Live-vs-paper flags
- Capital allocation flags
- Risk limit flags
- Strategy-active state flags

**Re-promotion not required for:**
- Logging level
- Metric emission frequency
- Pure observability flags

## 11. Game expected-value gate (unchanged from v1.0)

Before any strategy is admitted to research phase, the underlying game's expected value at intended size must be computed and shown positive after spread, fees, and slippage.

**Admission threshold:**
- EV >= 0.5% per round-trip net of all costs at intended capital size: research-phase admission granted
- 0% <= EV < 0.5% (marginal): explicit operator override required with documented rationale
- EV < 0%: auto-rejected, no override permitted

The PM Bot 5-minute crypto binary strategy (96% of HYDRA's lifetime losses, 7-9% structural cost on coin flips) is the canonical anti-example.

## 12. Quarterly measurement review

A measurement audit runs quarterly. It:
- Re-verifies all `VERIFIED` measurement sources against ground truth
- Reviews all `UNVERIFIED` sources for either upgrade or deprecation
- Audits flag-vs-code consistency
- Reviews any P0 bug-class incidents from the quarter
- Validates that REALIZED vs conservative-NAV measurements are being used in their correct contexts (the v1.1 corrective)
- Updates this policy doc if lessons learned

**Sign-off:** Operator (Wasseem Katt) for solo operation. Both signatures required if/when a second operator joins.

**First quarterly review scheduled:** 2026-08-02

## 13. Policy hierarchy and conflict resolution

This policy is part of the SuperHydra Policy Pack. When policies conflict:

1. Safety/compliance/venue permission requirements
2. Risk policy
3. Measurement policy (this document)
4. Deployment gates policy
5. Data policy
6. Model policy
7. Allocator policy
8. Incident severity policy

The stricter safety/risk interpretation applies until policies are amended and re-signed. Conflicts must be resolved via policy revision, not via runtime override.

## Revision log

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-05-02 | Wasseem Katt | Initial policy, derived from HYDRA postmortem and redemption audit |
| 1.1 | 2026-05-02 | Wasseem Katt + external reviewer | Added pnl_environment and pnl_settlement_type orthogonal classifications. Resolved REALIZED-only blind spot by specifying which measurement applies to which context (promotion vs risk vs allocation vs reporting). Added policy hierarchy and conflict-resolution rule. Added quarterly review item to validate correct measurement-context usage. |
