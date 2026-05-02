# Incident Severity Policy

**Version:** 1.0
**Effective:** 2026-05-02
**Author:** Wasseem Katt + external reviewer
**Source:** External review 2026-05-02 identifying that "P0 bug class" appears throughout the policy pack without formal definition; HYDRA postmortem 2026-05-01 producing five P0-class incidents in 24 hours

This policy defines incident severity levels (P0 through P3), the response required for each, and the re-entry criteria after resolution. The other policies reference "P0 bugs" repeatedly -- this document defines what that means.

## Why this policy exists

The HYDRA postmortem of 2026-05-01 surfaced five distinct integrity failures in 24 hours: MM measurement fiction (placed orders summed as PnL), L9 configuration drift (live trading while documented as paper), Polymarket authorization drift (positions opened through unintended code path), atomic-recording failure (81 ghost positions from silent DB writes), and unredeemed-winnings omission ($1,476 in tokens uncounted by accounting).

Each of these would, in retrospect, be classified P0 under this policy. None were classified at the time because no severity classification existed. That gap is what this policy closes.

## Severity levels

### P0 -- Critical integrity or capital risk

**Triggers (any of):**
- Unauthorized live trade (strategy traded live without recorded promotion event, or strategy traded outside its `risk.strategy_constraints`)
- Risk kernel bypassed (an order reached venue without passing pre-trade checks)
- Wrong PnL source consumed by a gate or risk decision (e.g., placed orders treated as fills, modeled fills treated as confirmed-settled)
- Lost funds (capital missing from venue or wallet that should be present per ledger)
- Unreconciled live position (venue holds a position the ledger doesn't know about, or vice versa, unresolved beyond 5 minutes)
- Venue or account compromise (suspected or confirmed unauthorized access)
- Configuration drift causing live trading (strategy operating in a mode different from what flags/docs/promotions specify)
- Atomic-recording failure (orders submitted but ledger writes failed silently)
- Measurement source producing systematic error of magnitude > 5x true value (the MM-fiction class)

**Required response:**
- Immediate halt of affected strategy (or PORTFOLIO_HALT if scope unclear)
- Operator notified within 15 minutes via Telegram (or equivalent)
- Postmortem published within 7 days at `docs/postmortems/<incident_date>-<short_name>.md`
- Postmortem must include: what was believed, what was actually true, root cause, timeline, lessons, action items
- Re-entry to production blocked until: (a) root cause fixed, (b) test demonstrating fix in place, (c) operator promotion event signed
- All policies reviewed for whether the incident class is preventable architecturally; if so, schema or code changes required before any related strategy resumes

**Examples (HYDRA postmortem 2026-05-01):**
- MM measurement fiction (P0: wrong PnL source)
- L9 configuration drift (P0: unauthorized live trade)
- Polymarket auto-opening through ungated code path (P0: risk kernel bypassed)
- BUNDLE_ARB silent DB failures (P0: atomic-recording failure)
- Unredeemed winnings omission (P0: measurement source producing systematic error)

### P1 -- Operational incident affecting trading capacity

**Triggers (any of):**
- Stale data caused signal halt (strategy paused due to source freshness violation lasting > 1 hour)
- Cost model drift > 30% sustained over 7 days (per model_policy section 7)
- Model drift halt (per model_policy section 7 thresholds)
- Unresolved reconciliation under capital risk (live position with reconciliation break, but capital exposure < 5% NAV)
- Venue API rate limiting causing strategy degradation
- Reconciler unable to keep up with order flow (queue backlog > 5 minutes)
- Risk kernel rejecting > 50% of orders for any single check sustained over 24 hours (suggests calibration error or strategy-vs-policy mismatch)
- Vendor outage > 4 hours (per data_policy section 3)

**Required response:**
- Affected strategy paused or operating in degraded mode within 30 minutes
- Operator notified within 1 hour
- Postmortem published within 14 days
- Re-entry: requires fix verification but not necessarily promotion re-sign (operator judgment)

**Examples (hypothetical):**
- Tardis L2 feed stale for 90 minutes; market-neutral L/S strategy correctly paused
- Cost model predicted 8 bps slippage; realized 14 bps for 7 days running
- Binance API rate limit hit; reconciler 8 minutes behind on fill confirmations

### P2 -- Non-trading-impacting bug or degradation

**Triggers (any of):**
- Dashboard or reporting inconsistency (numbers shown wrong but ledger correct)
- Non-order-touching code bug (logging error, metric emission failure)
- Vendor degradation without trading impact (one vendor of multiple slow but signal-generating still works)
- Postmortem not yet completed within deadline (P1 -> P2 escalation if postmortem missing on day 14)
- Quarterly review overdue
- Behavioral coverage drops below threshold for non-order-touching paths

**Required response:**
- Logged within 1 business day
- Triaged within 1 week
- Fixed within 1 month or formally deferred with rationale
- No production halt required

### P3 -- Documentation or housekeeping

**Triggers (any of):**
- Documentation outdated relative to code (docs say X, code does Y, where Y is correct)
- Configuration cleanup (unwired flags, deprecated comments)
- Vendor list out of date in policy doc
- Audit trail gap that doesn't affect any current decision

**Required response:**
- Logged in tracking system
- Addressed in next quarterly review or sooner if convenient
- No deadline

## Response decision tree

When an incident is detected, classify in this order:

1. **Is capital at risk now?** (lost funds, unauthorized trades, integrity bug affecting risk decisions) -> P0
2. **Is trading capacity degraded?** (data stale, model drift, venue issues, reconciler behind) -> P1
3. **Is the bug visible to user/operator but not affecting trading?** (dashboard, logging) -> P2
4. **Is it documentation or cleanup?** -> P3

If unclear between two levels, classify at the higher (more severe) level. Reclassify down only after investigation, not based on initial impression.

## Auto-triggered incidents

Some incidents trigger automatic system response without operator intervention:

| Incident | Auto-response |
|---|---|
| Reconciliation break unresolved > 5 minutes | PORTFOLIO_HALT engaged automatically per risk_policy section 9 |
| Drawdown state transition to BLACK | PORTFOLIO_HALT per risk_policy section 9 |
| Any P0 measurement integrity bug detected | PORTFOLIO_HALT |
| Single venue outage detected | VENUE_HALT for that venue |
| Strategy code path executes that is not in coverage report | STRATEGY_HALT for that strategy |
| Cost model drift > 50% sustained 1 hour | STRATEGY_HALT for affected strategy |

Auto-triggered halts do not require operator signature at engagement (per risk_policy section 9 v1.1) but require operator review within deadline:
- P0 auto-trigger: review within 24 hours, halt persists until operator promotion to re-enable
- P1 auto-trigger: review within 72 hours
- Unreviewed past deadline: escalates to next severity level

## Re-entry criteria after P0

A strategy or system halted due to P0 incident cannot resume until ALL the following are true:

1. **Root cause identified** in committed postmortem
2. **Fix implemented** with code review by operator (or second operator if available)
3. **Regression test added** that would catch this incident class if it recurred
4. **Architectural review** of whether other strategies/systems have the same vulnerability
5. **Operator promotion event** recorded with hardware signature for live trading, GPG signature for paper
6. **24-hour observation period** post-fix in paper environment before live re-entry (if affected strategy was live)

The 24-hour observation requirement is calibrated to ensure the fix actually addresses the root cause rather than masking the symptom. The HYDRA L9 incident is illustrative: the documented "fix" (PAUSE_L4_ENTRIES flag) didn't actually prevent the underlying problem (config drift between docs and runtime state) -- observation post-fix would have caught that the flag wasn't even being read.

## Re-entry criteria after P1

Less stringent than P0:
1. Root cause identified
2. Fix implemented
3. Operator approval (no formal promotion event required)
4. Resume in same environment as before halt (paper or live)

## Re-entry criteria after P2/P3

No formal re-entry required since these don't trigger halts. Track in normal issue management.

## Severity escalation

An incident's severity can escalate:

| Original | Escalates to | Trigger |
|---|---|---|
| P1 | P0 | Postmortem reveals capital was at risk and not fully addressed in initial response |
| P2 | P1 | Bug found to affect trading decisions despite initial assessment |
| P3 | P2 | Documentation gap found to be misleading operator decisions |
| Any | Higher | Repeated occurrence (3rd P2 of same class becomes P1; 3rd P1 of same class becomes P0) |

Escalation requires updating the incident record and appending to the postmortem (don't rewrite history; record the upgrade).

## Postmortem template

Every P0 and P1 incident requires a postmortem at `docs/postmortems/YYYY-MM-DD-short_name.md` with these sections:

1. **Severity**: P0 or P1
2. **Detected**: when and how
3. **What was believed**: the system state operator/code thought was true
4. **What was actually true**: the system state on inspection
5. **Root cause**: why the gap between believed and actual existed
6. **Timeline**: when did the incident start, when was it noticed, when was it halted
7. **Capital impact**: $ at risk, $ lost (if any)
8. **Lessons**: what does this teach about preventing the class of bug
9. **Architectural fixes**: what schema, code, or policy changes prevent recurrence
10. **Other systems at risk**: which other strategies/systems could have the same bug
11. **Action items**: with owner and deadline
12. **Signoff**: operator name, date

The HYDRA postmortem of 2026-05-01 (commit 86f6afe with addendums) is the canonical example.

## Incident audit and review

A quarterly review aggregates all incidents from the quarter:
- Counts by severity
- Patterns across incidents (same root cause class repeating?)
- Effectiveness of architectural fixes implemented
- Updates to this policy if classification rules need refinement

**Sign-off:** Operator (Wasseem Katt). Both signatures required if/when a second operator joins.

**First quarterly review scheduled:** 2026-08-02

## Policy hierarchy

This policy is part of the SuperHydra Policy Pack. When policies conflict:

1. Safety/compliance/venue permission requirements
2. Risk policy
3. Measurement policy
4. Deployment gates policy
5. Data policy
6. Model policy
7. Allocator policy
8. Incident severity policy (this document)

The stricter safety/risk interpretation applies until policies are amended and re-signed. P0 classification overrides any timeline or scaling preference -- capital risk forces immediate halt regardless of where strategy is in deployment gates.

## Revision log

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-05-02 | Wasseem Katt + external reviewer | Initial policy formalizing incident severity levels, response requirements, re-entry criteria, and escalation rules. Closes the gap identified in external review where "P0 bug" was referenced across the policy pack without formal definition |
