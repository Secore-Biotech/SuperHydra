# Measurement Policy

**Version:** 1.0
**Effective:** 2026-05-02
**Author:** Wasseem Katt
**Source:** Lessons from HYDRA postmortem 2026-05-01 (commits 86f6afe, 7344517, 5f8ce5f, b5071db) and redemption audit 2026-05-02 (commit 40d8fb3)

This policy codifies the measurement discipline required to prevent the failure modes that produced -$1,073 of HYDRA lifetime losses across five distinct measurement integrity bugs in 24 hours. Every rule below is non-negotiable and applies to all SuperHydra code, paper or live.

## 1. Source-of-truth typing

Every PnL number produced by SuperHydra must be tagged with one of three types:
- `REALIZED` -- cash actually settled, traceable to a venue fill or on-chain transaction
- `UNREALIZED` -- mark-to-market on open positions
- `MIXED` -- combination, with explicit breakdown showing realized $X, unrealized $Y

Aggregate displays (dashboards, reports, gate evaluations) must show typed totals, never collapse types into a single "PnL" number without breakdown.

**Sharpe calculation for deployment gates uses REALIZED only.** UNREALIZED can be displayed but does not count for promotion decisions. Reasoning: unrealized inventory drift can mask losses, and a gate based on unrealized is gameable. The MM strategy lesson -- $40.59 reported, $3.63 realized -- is the canonical example.

## 2. Confirmed-fill discipline

Order placement events and confirmed fills are stored in separate tables: `order_intents` for placements, `fills` for confirmations. PnL aggregations only read from `fills`.

A row in `fills` requires a venue confirmation ID (Binance order ID, Polymarket transaction hash, etc.). Rows without confirmation IDs are rejected at the schema level.

**Maximum lag between placement and fill confirmation:** 60 seconds for live trading, 5 seconds for canary alert thresholds. Beyond 60 seconds, the order is flagged `STALE_NEEDS_RECONCILIATION` and the reconciler must reach out to venue API to determine actual state. Orders that remain unresolved after 5 minutes trigger an operator alert and a halt-new-orders state for the affected strategy.

## 3. Empty-source safety

Any code that reads from a data source must explicitly handle the empty/missing case. Three valid responses:
- Return zero with explicit `source_empty=true` flag
- Raise `NoDataError` exception
- Return None and require caller to handle

**Default behavior for new ledger code: raise `NoDataError`.** Forces caller to handle. Explicit flag and None are valid alternatives where there is documented reason in the code itself.

Silent zero returns from missing tables are a P0 bug class. Any code that aggregates over a query result must verify the query returned rows before computing aggregate. The MM measurement fiction (272 placed orders summed as PnL because the fills table was queried wrong) is the canonical anti-example.

## 4. Cross-check requirements

Before any new measurement source is trusted, it must be cross-checked against ground truth:
- 5 or more random samples manually verified against venue records
- Source tagged `VERIFIED` only after manual cross-check signed off by operator (recorded in `measurement_audit` table)
- Sources without verification status are tagged `UNVERIFIED` and flagged in any output that uses them

**Quarterly re-verification required for active sources.** A source that has not been re-verified in 90 days reverts to `UNVERIFIED`. Vendor outages or schema changes trigger immediate re-verification regardless of last-verified date.

## 5. Atomic order recording

Order submission to a venue and ledger recording must be atomic. Implementation is write-ahead:
1. Ledger row created first with status `SUBMITTING`
2. Venue API called
3. Row updated to `SUBMITTED` with venue ID

If venue call fails, the row remains `SUBMITTING` and triggers reconciler within 60 seconds.

**No bypass paths.** Every order -- strategy-initiated, REPL, debug, manual -- routes through the same OMS write-ahead path. Direct venue API calls without ledger rows are a P0 bug class. The 81 unattributed Polymarket positions (BUNDLE_ARB silent DB failures plus REPL trades) are the canonical anti-example.

**REPL/debug trades during development:** routed through OMS like any other trade. A separate `paper_repl` strategy slot exists for human-initiated trades. Live REPL trades are forbidden by default and require explicit operator promotion (same gate as a strategy going live).

## 6. Promotion-gated execution

No strategy is permitted to execute live without a recorded promotion event in the `promotions` table. Promotion events contain:
- Strategy name
- `promoted_by` (operator ID)
- `promoted_at` (timestamp)
- `promotion_signature` (cryptographic signature of operator)
- `gate_evidence` (link to validation report demonstrating gate criteria met)

A strategy without a current promotion record is forbidden from `submit_order` calls at the OMS layer. The OMS rejects orders from un-promoted strategies before they reach the venue adapter.

**Signature mechanism:** GPG-signed JSON during paper-only Phases 1-4. Hardware key (Yubikey) required when Phase 5 canary live begins. The L9 lesson -- strategy went live 5 minutes after first paper test, 15 days of accidental live trading -- is the canonical anti-example.

## 7. Behavioral coverage

Every code path in a strategy must be exercised at least once in test before that path is permitted to fire in production (paper or live). Specifically: open-position logic, close-position logic, stop-loss logic, take-profit logic, and error-handling paths each must have at least one passing integration test that verifies the path executes correctly against the test venue.

**Coverage thresholds:**
- Order-touching code paths: 100% required
- Supporting logic (logging, metric emission, configuration): 80% required

Untested code paths are flagged at deployment. Strategy is rejected from promotion if any order-touching path lacks coverage. The L9 close logic that was never tested in 15 days of accidental live trading is the canonical anti-example.

## 8. Configuration audit

Every flag in config files (`hydra_flags.json` equivalent) must be wired to actual code. Unwired flags are deleted, not left as documentation. Quarterly audit verifies docs-to-flags-to-code consistency.

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

The HYDRA flag audit (3 of 7 flags wired, 4 unwired but appearing operational) is the canonical anti-example.

## 9. Game expected-value gate

Before any strategy is admitted to research phase, the underlying game's expected value at intended size must be computed and shown positive after spread, fees, and slippage. Strategies playing structurally negative-EV games are rejected before code is written.

**Admission threshold:**
- EV >= 0.5% per round-trip net of all costs at intended capital size: research-phase admission granted
- 0% <= EV < 0.5% (marginal): explicit operator override required with documented rationale
- EV < 0%: auto-rejected, no override permitted

The PM Bot 5-minute crypto binary strategy (96% of HYDRA's lifetime losses, 7-9% structural cost on coin flips) is the canonical anti-example. No measurement fix or infrastructure improvement can save a structurally negative-EV game.

## 10. Quarterly measurement review

A measurement audit runs quarterly. It:
- Re-verifies all `VERIFIED` measurement sources against ground truth
- Reviews all `UNVERIFIED` sources for either upgrade or deprecation
- Audits flag-vs-code consistency
- Reviews any P0 bug-class incidents from the quarter
- Updates this policy doc if lessons learned

**Sign-off:** Operator (Wasseem Katt) for solo operation. If/when SuperHydra has a second person, both must sign.

**First quarterly review scheduled:** 2026-08-02

## Revision log

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-05-02 | Wasseem Katt | Initial policy, derived from HYDRA postmortem and redemption audit |
