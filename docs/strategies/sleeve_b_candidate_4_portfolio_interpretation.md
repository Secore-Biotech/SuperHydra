# Sleeve B Candidate #4 — Portfolio construction interpretation memo

**Status:** Clarification memo — subordinate to candidate #4 pre-registration
**Subordinate to:** `docs/strategies/sleeve_b_candidate_4_preregistration.md` (commit `59c1156`)
**Date:** 2026-05-16
**Trigger:** Ambiguity surfaced during D2 (Stage B backtest runner) planning

---

## 0. Scope

This memo resolves a single ambiguity in the candidate #4 pre-registration at commit `59c1156`. It does not amend the pre-registration. It does not reopen Q1, Q2, or Q3. It does not modify Stage A, Stage B, F1, F3, or any gate threshold.

This memo is committed **before D2 (backtest runner) code is written.** Locking the interpretation before the backtest runs is the same discipline that produced the Stage A gate-inheritance evolution at `39970f1`: pre-registration ambiguities are surfaced and resolved via subordinate clarification memos before the work that depends on them executes.

---

## 1. The ambiguity

Candidate #4 pre-registration §2.6 (B0 parameter lock) states:

> **Bucket construction:** Top-third long, bottom-third equal-weight short — Inherited from xs-momentum precedent.
>
> **Position sizing:** Equal weight within bucket — No vol scaling at sizing level (locked at Q1 of candidate #3).
>
> **Cost model:** Same as xs-momentum cost model — Inherited from candidate #1 pre-registration.

The pre-registration is silent on **portfolio-level vol-targeting**, which is a separate concept from per-asset sizing-level vol-scaling.

xs-momentum's portfolio construction (`strategies/sleeve_b/xs_momentum/portfolio.py`) implements:

- Equal-weighted positions within each decile
- Portfolio gross exposure scaled to hit a target portfolio-level vol of 15% annualized
- 4-week cold start period during which scaling = 1.0 (no vol-target adjustment)
- After cold start: scale = target_weekly_vol / realized_weekly_vol where realized is computed from trailing 4 weeks of net portfolio P&L

This is **portfolio-level risk overlay**, not per-asset sizing.

The pre-registration §2.6's prohibition on "vol scaling at sizing level" rules out option (B) from Q1: per-asset inverse-vol weighting within the bucket. It does not address whether the portfolio-level vol-target overlay carries forward from xs-momentum.

Two readings of the pre-registration are defensible:

- **Reading A:** xs-momentum's portfolio-level vol-targeting is inherited along with its cost model, since the §2.6 lock is silent on risk overlay and inherits the cost model explicitly.
- **Reading B:** the §2.6 silence on portfolio vol-targeting means it is excluded by default; equal-weight dollar-neutral with no portfolio-level scaling.

These produce materially different backtests. The choice cannot be made silently inside D2 without weakening the governance trail.

---

## 2. Lock

**Reading A is locked.**

Candidate #4 portfolio construction inherits xs-momentum's portfolio-level vol-targeting. Specifically:

- **Equal weight within long bucket** — every name in the long-third gets identical weight before vol-target scaling
- **Equal weight within short bucket** — every name in the short-third gets identical weight before vol-target scaling
- **Dollar-neutral by construction** — gross long notional equals gross short notional at every rebalance
- **Portfolio-level volatility targeting inherited from xs-momentum**
  - **Target annualized vol:** 15%
  - **Target weekly vol:** 15% / sqrt(52) ≈ 2.08% (xs-momentum's `TARGET_WEEKLY_VOL` constant)
  - **Cold start:** 4 weeks (during which gross scale = 1.0, no vol-target adjustment)
  - **Trailing realized portfolio-vol window:** 4 weeks (stdev of net weekly P&L in fraction-of-notional terms)
  - **No leverage cap** (inherited from xs-momentum's explicit design — if realized vol → 0, scaler → infinity; this is documented behavior in xs-momentum's portfolio.py, not a bug)
- **No per-asset inverse-vol sizing** (option (B) from Q1 remains rejected; this lock does not reopen Q1)

---

## 3. What this lock distinguishes

The candidate's signal-level vol-scaling and the portfolio's risk overlay are conceptually distinct operations:

| Operation | What it does | Where it acts |
|---|---|---|
| **Signal-level vol-scaling (locked at Q1)** | `score_i = momentum_i / vol_i` | Cross-sectional ranking — determines which names are in the long bucket vs short bucket |
| **Portfolio-level vol-targeting (this lock)** | gross_scale = target / realized_portfolio_vol | Total portfolio exposure — determines how much capital is deployed |

Both operations involve volatility, but they target different things. Signal-level vol-scaling is the candidate's economic thesis (risk-adjusted return ranking). Portfolio-level vol-targeting is a risk-management overlay applied to whatever the signal produces.

**Candidate #4 remains signal-level volatility-scaled momentum.** The inherited portfolio-level volatility target is a risk overlay that applies *on top of* the signal, not a modification of the signal itself.

This distinction is operationally important for the F1/F3 analysis in Stage B:

- **F1.3 (numerator-vs-denominator variance contribution)** decomposes the *signal's cross-sectional variance*. Portfolio-level vol-targeting doesn't enter this computation — it scales the gross exposure but doesn't change the relative ranking of names.
- **F3.3 (pure-low-vol attribution decomposition)** decomposes the *strategy's returns* into pure momentum, pure low-vol, and interaction components. Portfolio vol-targeting affects total return magnitude but not the *fraction* attributable to each component (since it scales all three components equally).

Therefore the F1/F3 gates remain operationally meaningful under Reading A. Reading A does not invalidate any pre-registered gate.

---

## 4. Why Reading A and not Reading B

Five reasons:

**4.1** The §2.6 lock inherits xs-momentum's cost model explicitly. Cost model and risk overlay are coupled — xs-momentum's promotion bar (and by extension the standards that informed candidate #4's stricter promotion thresholds) was set in the context of a vol-targeted portfolio. Inheriting one but not the other introduces an unstated divergence.

**4.2** Comparing candidate #4 against xs-momentum cleanly requires holding the portfolio framework constant. Under Reading A, the only change relative to xs-momentum is the signal definition (`momentum/vol` instead of raw momentum) and the bucketing (`thirds` instead of `deciles`). Attribution is clean: if candidate #4 has a different Sharpe than xs-momentum, the difference reflects the signal change, not a portfolio-construction change.

**4.3** Reading B introduces a second change at the same time as the signal change. That dilutes attribution. If the candidate fails Stage B, the kill action cannot cleanly say "the signal didn't work" — it would have to say "the signal didn't work under no-vol-targeting, but might have worked under vol-targeting."

**4.4** Q1 rejected option (B) — per-asset sizing-level vol-scaling — explicitly. Portfolio-level vol-targeting was not part of the Q1 deliberation. Reading B silently reads Q1 as having rejected portfolio vol-targeting too, which it did not.

**4.5** Engineering cost. Reading B requires writing candidate-#4-specific portfolio construction code from scratch. Reading A reuses xs-momentum's `build_portfolio` and `portfolio.py` directly. Lower engineering risk, more reuse of tested code.

---

## 5. What this lock does NOT do

**It does not reopen Q1.** Per-asset sizing-level vol-scaling (option (B)) remains rejected. The candidate's primary signal is `score_i = momentum_i / vol_i`, locked.

**It does not amend the pre-registration at `59c1156`.** That document remains binding as the historical record. This memo is subordinate clarification.

**It does not change any Stage A or Stage B threshold.** A1/A2/A3/A4/A5 sub-gates, F1.1/F1.2/F1.3/F1.4 sub-gates, F3.1/F3.2/F3.3 sub-gates, B1/B2/B3/B4 performance gates, mandatory diagnostics — all unchanged.

**It does not apply retroactively.** Prior candidates (#1, #2, #3) are closed under their own pre-registrations and are not affected.

**It does not modify xs-momentum's `portfolio.py` or `backtest.py`.** Candidate #4's D2 imports and uses those modules; xs-momentum's code is untouched.

---

## 6. Cherry-pick disclosure

Honest disclosure: this memo locks an interpretation after seeing the xs-momentum portfolio construction in detail. It is a clarification, not a deliberation made in isolation from the implementation.

Three structural protections against this becoming a cherry-pick:

**6.1** No backtest has been run. The lock occurs *before* any candidate #4 economic results are observed.

**6.2** The lock is committed before D2 code is written. If the operator had been silently leaning toward Reading A or Reading B based on hoped-for results, this would have shown up in delayed lock or in changing the lock after running D2 once. Neither has happened.

**6.3** The opposite reading (Reading B) was given explicit consideration in §4. The reasoning for choosing Reading A is documented and falsifiable: future readers can disagree with the reasoning, but they can see the reasoning that was applied.

This is procedurally analogous to the gate-inheritance memo at `39970f1`, which resolved an ambiguity after candidate #3's kill. The framework's discipline allows clarifications when they (a) precede the work that depends on them, (b) explicitly distinguish themselves from amendments, and (c) document the reasoning honestly.

---

## 7. Operational implications for D2

D2 (backtest runner) imports and uses:

- `strategies.sleeve_b.vol_scaled_momentum.signal.compute_signal` — new, locked at D1 commit `8cc69fc`
- `strategies.sleeve_b.xs_momentum.portfolio.build_portfolio` — inherited, vol-target as specified above
- `strategies.sleeve_b.xs_momentum.backtest.generate_rebalance_dates` — inherited (already used by Stage A script at `1189f55`)
- `strategies.sleeve_b.xs_momentum.backtest.compute_turnover` and helpers — inherited

The D2 runner script wraps these into a backtest loop that mirrors `strategies/sleeve_b/xs_momentum/backtest.py:run_backtest`, with the only substantive difference being the signal function called per rebalance.

D2 deliverable target: `scripts/run_candidate_4_backtest.py`, parallel to existing `scripts/run_sleeve_b_xs_momentum.py`.

The cold-start period (4 weeks ≈ first 4 Mondays of OOS, 2023-04-17 through 2023-05-08) will produce backtests at gross_scale = 1.0. After 2023-05-15 (the 5th Monday) the trailing-vol scaling engages.

---

## 8. References

- Candidate #4 pre-registration: `docs/strategies/sleeve_b_candidate_4_preregistration.md` (commit `59c1156`)
- D1 signal module commit: `8cc69fc` (`strategies/sleeve_b/vol_scaled_momentum/signal.py`)
- xs-momentum portfolio.py: `strategies/sleeve_b/xs_momentum/portfolio.py` (inherited construction)
- xs-momentum backtest.py: `strategies/sleeve_b/xs_momentum/backtest.py` (inherited engine pattern)
- Gate-inheritance framework evolution (procedural precedent): `docs/strategies/sleeve_b_framework_evolution_stage_a_gate_inheritance.md` (commit `39970f1`)
- Master roadmap §10 (operator authority): governs the operator decision to lock Reading A

---

*Subordinate clarification memo resolving the candidate #4 pre-registration §2.6 ambiguity on portfolio-level vol-targeting. Reading A locked: inherit xs-momentum's portfolio-level vol-targeting overlay. Candidate #4 remains signal-level volatility-scaled momentum; the inherited overlay is risk management, not sizing-level vol-scaling. Committed before D2 execution. Does not amend the pre-registration.*
