# notes/section_a_probe_spec_v1.md

*Section A probe v1 — pre-lock spec. Draft.*

Pre-lock means every parameter below is fixed before code runs. No post-hoc reparameterisation. If results come back ambiguous, the probe is **inconclusive**, not "tuned."

---

## 0. What this is

The first concrete probe under `notes/edge_scoping.md` §6 (Section A — slower structural-flow effects). The hypothesis:

> After a 24h realised-volatility shock on BTC or ETH perps, conditional forward returns at horizons of 1d / 3d / 7d differ from the unconditional baseline by enough to survive operator-tier perp trading costs.

This probe is locked against the rotation-vs-pivot critique (`edge_scoping.md` §6) because the measured object is **forward return after a realised-vol regime break**, which is structurally distinct from candidate_4's measured object (contemporaneous strategy P&L conditional on backward-looking funding-stress flags).

Reference: `notes/edge_scoping.md` §5 (probe requirements), §6 (Section A scope), §4 bullet 5 (deployment shape), §7 (tie-breaker — return persistence chosen over vol compression because the deployment path runs on existing perp rails).

---

## 1. Measured object

**Conditional forward return on BTC and ETH perpetual futures, where the conditioning event is a 24h realised-volatility regime break.**

Concretely, for each detected event at time `t`:

- Forward log-return at horizons `h ∈ {1d, 3d, 7d}`, measured close-to-close from `t`.
- Pre-event direction defined as: sign of cumulative log-return over the 24h event window ending at `t`.
- Hypothesis is **persistence only**: forward return same sign as pre-event direction. Reversal-class hypotheses (mean-reversion after vol shock) are explicitly out of scope for v1 and would require a separate spec (see §10).

**Universe:** BTC and ETH perpetual futures on Binance only. No alts, no cross-venue, no spot.

**Why this is not a rotation of candidate_4:**
- candidate_4 dependent variable: contemporaneous strategy P&L. This probe: forward perp return.
- candidate_4 trigger: trailing-window funding-stress flag. This probe: realised-vol regime break.
- candidate_4 mechanism: regime exclusion (zero-out filter). This probe: directional position taken on the perp itself.

---

## 2. Event definition (pre-locked)

**Realised volatility computation:**
- Source: 1h klines on Binance perpetual futures, BTCUSDT and ETHUSDT.
- Returns: hourly close-to-close log returns.
- Window: 24 consecutive hourly bars ending at the bar closing at `t`.
- Estimator: `σ_24h = stdev(hourly_log_returns) × sqrt(24 × 365)` (annualised).

**Evaluation cadence:**
- Once per day, evaluating the 24h window ending at `00:00 UTC`.
- One event detection per asset per day maximum.

**Trigger threshold:**
- Event fires when `σ_24h > P95(σ_24h over trailing 90 days)`.
- Trailing-90d percentile computed from the same daily-evaluated `σ_24h` series, excluding the current observation.
- Single threshold. No P90 or P99 sensitivity evaluations in v1 — threshold sensitivity is deferred to v2 if v1 fails (see §10).

**Event-time anchoring:**
- `t` = 00:00 UTC on event detection day.
- Forward returns measured from the perp close at `t`.
- This makes the probe daily-resolution and immune to intraday timing artifacts.

---

## 3. Holding windows (pre-locked)

Three horizons, evaluated in parallel: **1d / 3d / 7d**.

No post-hoc selection of "the best" horizon. All three are reported. If horizon `h*` is the only one that clears gates, deployment uses `h*`. If multiple clear, deployment uses whichever has the highest economic-gate margin (defined in §6 below). If none clear, the probe fails.

No alternative horizons (e.g. 5d, 14d) are evaluated. Adding horizons post-hoc is a multiple-comparisons hole.

---

## 4. Cost assumptions (pre-locked, operator-tier)

Calibrated to Binance retail tier — no VIP, no BNB-discount, no MM rebate.

| Component | Assumption |
|---|---|
| Entry order type | Market (taker) |
| Exit order type | Market (taker) |
| Taker fee | 4 bps per side, 8 bps round-trip |
| Slippage | 1 bp per side, 2 bps round-trip (conservative for $50k ceiling on BTC/ETH perps) |
| Funding cost | Per-event realised, summed over holding window, signed by position direction |
| Borrow cost | N/A (perps) |
| Transfer cost | N/A (single venue) |
| Floor on round-trip cost | 10 bps + signed realised funding |

**Funding handling:** funding is paid/received every 8h. For each event, the cost model uses the actual realised funding-rate sequence over the holding window, signed by the trade direction (long pays positive funding, short receives it). Funding is not assumed flat — it is computed from historical funding records per event.

**Cost-model pre-lock invariant:** these numbers cannot be lowered if results come back below the economic gate. They can be *raised* (e.g. discovering realised slippage is worse) but the post-raise economics must still clear the same thresholds. Lowering costs to make the probe pass is the canonical curve-fit failure mode this spec is designed to prevent.

---

## 5. Statistical gate

**Sample split:**
- **Train:** earliest 80% of available period (sufficient kline + funding history; target ≥ 3 years).
- **OOS:** latest 20%, minimum 6 months. **Never inspected during parameter selection.** OOS results are computed exactly once, after all training-side decisions are frozen.

**Per-horizon strategy construction:**
- For each horizon `h`, the strategy is fully specified by the persistence hypothesis: at each event, take a position in the same direction as the pre-event 24h return. No parameters are fitted.
- This produces three candidate strategies (one per horizon), each with **zero free parameters**. Training data is used only to verify the persistence hypothesis is present, not to select between persistence and reversal.

**Statistical pass conditions (must hold for at least one horizon):**

| Metric | Train | OOS |
|---|---|---|
| Net Sharpe (annualised, after §4 costs) | ≥ 2.0 | ≥ 1.5 |
| Minimum events in window | ≥ 100 | ≥ 30 (combined BTC + ETH) |
| Rolling 30-day Sharpe in OOS | n/a | no more than one full-window failure (per Appendix B §B.2) |

**Hard inconclusive / fail clauses:**
- If OOS sample < 30 events combined → probe is **inconclusive**, not pass and not fail. Runway implications discussed in §9.
- If OOS mean net return is negative at a given horizon → that horizon is **failed** (persistence hypothesis did not hold OOS). This is *not* a signal to test reversal in v1 — see §10.
- If all three horizons fail OOS → v1 is failed. Whether reversal becomes v2 is a separate decision under §2.1 of `edge_scoping.md`.

---

## 6. Economic gate

A statistically strong result that fails this gate is a failed probe (`edge_scoping.md` §5).

**Per-horizon, OOS-measured (the strategy with persistence/reversal locked from training):**

| Metric | Threshold |
|---|---|
| Mean net return per trade | ≥ 20 bps (after full §4 cost model) |
| Median net return per trade | > 0 |
| Win rate | > 50% |
| Cost coverage ratio (mean gross / mean cost) | ≥ 2.5× |
| Regime-shift sanity: net P&L over the final 3 months of OOS | > 0 |

**Why these numbers (locked rationale, not adjustable):**
- **20 bps mean net** = 2× the round-trip cost floor (10 bps). 15 bps (1.5×) was the earlier draft threshold; raised to 2× because the project's prior probes consistently produced "interesting but operationally fragile" outcomes at the 1.5× level, and 2× coverage is the lowest threshold at which the edge survives plausible cost-model error rather than depending on it.
- **Median > 0** kills right-skew artifacts (one huge winner masking many small losers).
- **Win rate > 50%** kills thin-tail dependencies. Combined with positive expectancy, ensures the edge isn't concentrated in a handful of events.
- **2.5× cost coverage** protects against silent cost-model error (slippage worse than assumed, funding more punitive than modelled).
- **Final-3-months sanity** kills strategies that worked across the full OOS window but died at the end — a common pattern when the underlying phenomenon decays.

If a horizon clears the statistical gate but fails *any* economic-gate metric, that horizon fails. If all three horizons fail the economic gate, the probe fails — even if some look statistically interesting.

---

## 7. Expected deployment shape (per §4 bullet 5)

If the probe clears both gates at horizon `h*`, the deployed strategy is:

**Detection:**
- Daily job at 00:00 UTC. Computes 24h `σ` on BTCUSDT and ETHUSDT perps. Compares to trailing-90d percentile maintained as a rolling state. Triggers event flag(s).

**Execution:**
- On event flag, opens market-order perp position in the locked direction. Size determined by roadmap v2.2 §6 (canary $500–$2,000 per engine, scaling per the ladder).

**Exit:**
- At `t + h*`, market-order close. Single exit, no path-dependent management.

**Infrastructure additions:**
- Realised-vol calculator (24h, hourly returns).
- Trailing-90d percentile state.
- Event detector + handler hook into existing OMS.
- Forward-return P&L attribution (already in existing ledger).

All within migration 0001-0011 stack. No new venue, no options leg, no continuous quoting, no second exchange account.

**Operational footprint:**
- Zero routine human intervention. One trigger per day evaluation; events fire only when vol exceeds threshold.
- Engine state is self-contained: realised-vol, percentile cache, position state.
- Risk-control integration per Appendix E (control-state has zero outage tolerance).

**Capital footprint:**
- Canary: $500–$2,000 per event. Compatible with roadmap §6 ladder.
- Full scale: $50k ceiling. Per-engine concentration cap (roadmap §6.1) binds before sizing per event becomes the constraint.

This passes `edge_scoping.md` §4 bullets 1–5. No hidden infrastructure assumptions.

---

## 8. Pre-lock immutability

The following are **frozen** the moment this spec is committed:

- Universe (BTC/ETH perps on Binance only)
- Hypothesis (persistence only — no reversal evaluation, no directional fitting)
- Realised-vol estimator (hourly returns, 24h window, annualised, P95 threshold — single threshold, no sensitivities)
- Event-time anchoring (00:00 UTC daily evaluation)
- Holding windows (1d / 3d / 7d, no others)
- Cost-model floor (4 bps fee per side, 1 bp slippage per side, per-event realised funding)
- Train/OOS split (80/20, OOS ≥ 6 months, computed once)
- Statistical gate thresholds (Sharpe ≥ 2.0 train / ≥ 1.5 OOS, sample floors)
- Economic gate thresholds (20 bps mean net, median > 0, win rate > 50%, 2.5× cost coverage, final-3mo > 0)

If any of these need to change after results are seen, **this spec is dead** and a v2 spec must be written from scratch with new pre-lock parameters. There is no "amendment" path. Amendments are post-hoc fitting.

---

## 9. Runway impact

Approximate effort estimate against 30+ hrs/week sustained budget (`edge_scoping.md` §2):

| Phase | Estimate | Cumulative |
|---|---|---|
| Build vol-calc + percentile state + event detector | 10–15 hrs | week 1 |
| Build backtest harness on existing cost model | 15–20 hrs | week 2 |
| Train-side run + analysis | 10–15 hrs | week 3 |
| OOS run (single-shot) + economic gate evaluation | 5–8 hrs | week 3 |
| If pass: P1 paper wiring on production OMS/risk/ledger | 20–30 hrs | weeks 4–5 |
| If fail: probe write-up, kill record, next-probe scoping | 5–8 hrs | week 4 |

**Calendar guards:**
- Probe pass/fail decision by **end of week 3**.
- If pass, P1 entry by **end of week 5**. This leaves ~3 weeks of runway slack before §2.1 expiry on 2026-07-25.
- If fail or inconclusive, ~5 weeks of runway remain. Enough for one alternative probe before expiry. Likely candidates: vol-compression (different object, same trigger), or return persistence with a different trigger family.

**Estimate caveat.** These estimates assume no major data-quality or accounting surprises. Historical project experience suggests simulator/debugging work often expands nonlinearly once implementation begins — timestamp alignment, OOS split verification, event overlap handling, and sanity-check instrumentation are the usual sources. If actual progress trails the estimate by more than a week at any checkpoint, treat that as runway pressure, not absorbable noise.

**Hard rule:** if the spec turns out to require substantial rework before week 3 (e.g. data gaps, funding-record holes), that is a signal the §2.1 fallback may bind. Pause and re-evaluate before sinking another two weeks.

---

## 10. Out of scope for v1

- Alts beyond BTC/ETH. v2 may broaden if v1 clears.
- Cross-venue (OKX, Bybit, etc). v2 may add if v1 clears and venue concentration cap (roadmap §6.2) becomes binding.
- Options-based vol expression. Vol-compression as object is deferred per §7 of `edge_scoping.md`.
- Continuous-vol regimes (long-horizon vol-state filters). This probe is event-triggered only.
- Position-management overlays (stops, trailing exits, partial profit). Single entry, single exit at pre-locked horizon.
- Multi-horizon position blending. If multiple horizons pass, deployment picks one based on economic-gate margin, not weighted blend.
- **Reversal-class hypotheses.** v1 tests persistence only. If v1 fails because realised vol shocks show reversal-shaped behaviour, that is a v2 hypothesis with its own pre-lock spec. v1 does not auto-mutate into a reversal probe — that would be the curve-fit failure mode this spec is designed to prevent.
- **Threshold sensitivity (P90, P99, etc).** v1 tests P95 only. Whether the effect is robust across vol-shock thresholds is a v2 question, evaluated only if v1 clears.

---

*Draft. Not committed. Review / critique before commit.*
