# Sleeve B Candidate #5 — Selection memo

**Candidate name (working):** System-stabilizer regime detection (joint funding/OI/basis persistence)
**Date:** 2026-05-21
**Author:** Operator (Wasseem)
**Framework state binding:** `3ec7a32` (Q0 cluster-diversity), `39970f1` (gate inheritance), `cb9d975` (Q0 data viability), `fe909bb` (master pre-registration)
**Status:** Selection memo only. Not a pre-registration. Pre-registration drafted in a separate session if and only if this selection memo is committed and the originating intuition survives a 24-72h re-read.

---

## 0. Summary

Candidate #5 proposes a regime-state detection signal built from the joint persistence of three system-stabilizer metrics — perpetual funding rate, open interest, and perp-vs-spot basis — under conditions of market stress. The originating intuition is that when these three metrics fail to mean-revert *together* during stress, the persistence itself is informative about whether the market's normal arbitrage and rebalancing machinery is impaired.

This is a signal about *system state*, not about asset rankings. It is the first candidate in the program that is not a cross-sectional ranking exercise.

Originating intuition came from operator reflection on the FTX collapse period (November 2022), where:

- Funding stayed extreme for longer than rational equilibrium would predict
- OI remained elevated despite high-stress price movement
- Perp-vs-spot basis stayed distorted
- The agents who would normally compress these distortions (arb capital, leveraged longs facing margin pressure) appeared themselves to be impaired or trapped

The intuition's core claim: **the metric stopped behaving like mispricing and started behaving like a stress-state indicator.** Standard arb logic says "fade extremes"; this intuition says the opposite — during impaired-stabilizer regimes, the extreme persists *because the counter-flow doesn't exist*, and fading is the wrong response.

---

## 1. Q0 — Data Viability

Per `cb9d975` and `39970f1`.

### 1.1 Q0 §1 — Point-in-time data availability

**PASS.** The candidate requires:
- Funding rate history per asset (Binance perpetual API — historical, PIT-clean, no backfill issues)
- Open interest history per asset (Binance API — PIT-clean for OI as reported on each timestamp; aggregate OI reconstructions over time available)
- Perpetual price and spot price for basis computation (already in `BinanceKlinesArchiveFetcher` cache from prior candidates)
- Realized volatility series for stress identification (computable from price data)

All four data classes are sourced from Binance native APIs and PIT-clean as historically published. No third-party fee-yield/quality-data dependencies. No backfilled aggregator data.

### 1.2 Q0 §2 — Vendor independence

**PASS.** All data sourced from Binance native APIs. No paid third-party subscriptions required. No operator-approval-needed data acquisition.

### 1.3 Q0 §3 — Reconstruction feasibility

**PASS.** All required data is fetchable through existing infrastructure:
- `BinanceKlinesArchiveFetcher` for prices (already in repo)
- Binance funding rate history endpoint (well-documented, public, historical)
- Binance open interest endpoint (public, historical at hourly granularity)
- Existing kline cache covers the OOS window 2023-04-15 → 2026-04-15

Note: FTX (Nov 2022) is *outside* the OOS window. The originating intuition is FTX-derived but the OOS evaluation will not include FTX. This is by design — if the signal only works on the one regime that produced the intuition, it's over-fit. The OOS window must include genuine out-of-sample regime states. The intuition predicts the signal should also have been informative during other stress periods within OOS (e.g., March 2023 banking stress, August 2024 yen-carry unwind, others).

### 1.4 Q0 §3.5 — Survivorship and temporal stability

**PASS with note.** The candidate operates on a regime-detection basis, not a cross-sectional ranking basis, so the eligible-universe temporal-stability concern from candidate #3 does not apply in the same way. The signal can be computed on any single asset (e.g., BTC perp only) without requiring a temporally-stable cross-section of assets.

The frozen universe fixture at `2af9981` remains usable as the asset set for any cross-sectional variant of the strategy, but the *signal* is system-state, not asset-rank, and can operate on BTC + ETH alone if desired.

### 1.5 Q0 §4(a) — Family classification

**§3.1.11 — Cross-asset / regime.** The candidate's primary input is regime-state inference from joint behavior of system-stabilizer metrics. This fits §3.1.11's existing "regime-state" framing per the taxonomy at `3ec7a32`.

**Scoping note (binding for future readers):** This is NOT a macro correlation-regime detection candidate in the canonical "BTC-ETH correlation" or "risk-on/risk-off" sense. It is a more mechanically grounded version of regime-state detection that uses the *persistence of system-stabilizer distortion* (funding, OI, basis joint behavior) as the regime indicator. Future candidates in §3.1.11 should not assume this candidate's classification implies correlation-regime methodology. The scoping note exists to prevent taxonomy drift.

### 1.6 Q0 §4(b) — Sub-family count

**Count = 0.** No prior candidates classified under §3.1.11.

### 1.7 Q0 §4(b′) — Super-family aggregation

**Not applicable.** §3.1.11 is not part of the cross-sectional factor super-family (§3.1.2 + §3.1.3 + §3.1.4). The super-family aggregation rule per `3ec7a32` §2.1 applies only to cross-sectional candidates.

### 1.8 Q0 §4(c) — Written justification

**Not required.** Count = 0; threshold = 3. No justification triggered.

The cluster-diversity check at `3ec7a32` does not fire for this candidate. Selection proceeds without §4(c) obligation.

**Operator note (volunteered, not required):** This is the first non-cross-sectional candidate in the program. The Q0 §4 forcing function was specifically designed to make non-cluster candidates explicit selection acts. This candidate satisfies that intent without §4(c) firing, because it is outside the cluster *by mechanism*, not by category-shopping. The originating intuition came from market observation that the cluster's cross-sectional structure couldn't capture — exactly what the cluster-diversity memo §6.2 of the framework review (`7c10ca0`) anticipated.

---

## 2. Q0 cumulative state

| Sub-criterion | Result |
|---|---|
| §1 PIT availability | PASS |
| §2 Vendor independence | PASS |
| §3 Reconstruction feasibility | PASS |
| §3.5 Survivorship / temporal stability | PASS (with note) |
| §4(a) Family classification | §3.1.11 cross-asset/regime |
| §4(b) Sub-family count | 0 |
| §4(b′) Super-family count | N/A |
| §4(c) Written justification | Not required (count < 3) |

**Q0 verdict: PASS_CLEAN.** Candidate proceeds to Q1.

---

## 3. Q1 — Signal definition

The signal is a *regime classifier*, not a directional alpha signal. The output of the signal is a state — "normal" vs "impaired-stabilizer" — not a return forecast.

### 3.1 Inputs

For asset *i* (initial universe: BTC, ETH; expansion to broader universe possible if Q1 signal validates) at time *t*:

- **Funding rate persistence** *F(i, t)* — funding rate over the most recent N funding periods (e.g., 9 × 8h periods = 3 days)
- **OI persistence** *O(i, t)* — open interest level relative to its trailing-K rolling reference (e.g., trailing 30-day median)
- **Basis persistence** *B(i, t)* — perp-vs-spot basis, signed, over the same recent N periods
- **Stress indicator** *S(i, t)* — realized volatility relative to its trailing window (e.g., 7-day realized vol vs 60-day median realized vol)

### 3.2 Composite signal — initial operationalization (Q1 deliverable in pre-reg)

The pre-registration session will lock the exact formula. Initial sketch (subject to revision in pre-reg):

Define `IMPAIRED(i, t) = 1` iff all four of the following hold for a defined persistence window:

- |F(i, t)| > funding_threshold for ≥ p_f of recent N periods
- O(i, t) / O_ref(i, t) > oi_threshold (sticky high OI)
- |B(i, t)| > basis_threshold for ≥ p_b of recent N periods
- S(i, t) > stress_threshold (realized vol elevated)

Else `IMPAIRED(i, t) = 0`.

The signal is the indicator function `IMPAIRED`. Thresholds and persistence windows are pre-registered before evaluation.

### 3.3 What the signal is NOT

- It is not a funding-fade signal (the cluster's default reflex)
- It is not a momentum signal
- It is not a relative-value cross-sectional signal
- It does not directly predict next-period returns

What it predicts is regime — and the *trading rule* that operates on the regime is a separate Q2 question.

---

## 4. Q2 — Portfolio expression

The signal produces a regime state. The portfolio expression options are real and need locking in the pre-registration. Three candidate operationalizations of "what to do with the regime state":

### 4.1 Option 4.A — Regime filter on cross-sectional strategies

When `IMPAIRED == 1`, turn *off* cross-sectional strategies (or reduce gross exposure). When `IMPAIRED == 0`, run cross-sectional normally.

This is the most conservative interpretation. The signal becomes an overlay on prior cluster candidates, not a standalone strategy. Could be tested by retroactively applying to candidate #4's audit log: would gating candidate #4's exposure off during `IMPAIRED == 1` periods have changed its Sharpe and drawdown materially?

This is the closest thing to a "free win" — if `IMPAIRED` correctly identifies bad regimes for cross-sectional strategies, even a clean cross-sectional strategy gets better by avoiding the bad regimes. Not a standalone alpha, but a multiplier on existing infrastructure.

### 4.2 Option 4.B — Counter-positioning when IMPAIRED

When `IMPAIRED == 1` AND funding is extreme negative, go long (against the typical fade reflex). When `IMPAIRED == 1` AND funding is extreme positive, go short. The intuition: during impaired regimes, the persistent distortion eventually breaks violently in the direction of the distortion, *not* against it, because trapped agents cannot continue holding.

This is the directional interpretation of the intuition. More aggressive, more falsifiable, more interesting if it works.

### 4.3 Option 4.C — Don't-trade signal as a defensive overlay

Simplest. When `IMPAIRED == 1`, don't take new positions in any strategy. When `IMPAIRED == 0`, normal operation.

This is the weakest claim — purely defensive. But also the easiest to test and the least vulnerable to over-fit.

### 4.4 Pre-registration choice

The pre-registration session will lock ONE operationalization (4.A, 4.B, or 4.C) before evaluation. Mixing or hedging between them is forbidden — pre-registration discipline requires a single committed strategy.

**Operator leaning at this stage (not binding until pre-reg):** Option 4.A (regime filter on cross-sectional) is the most informationally efficient first test, because it directly tests whether `IMPAIRED` is a real regime classifier *and* leverages existing candidate #4 audit data for cheap evaluation.

---

## 5. Q3 — Evaluation gates

Stage A gates apply per `39970f1`. Stage B gates apply per master pre-registration `fe909bb` and the F1/F3 sub-gate families. Specific operationalization in the pre-registration.

Key Stage B gate considerations specific to this candidate:

- **B3 Sharpe and drawdown gates remain at current calibration** per framework review `7c10ca0` verdict A1. No platform-pivot relaxation. The candidate must clear the same bar as prior candidates.
- **F1 sub-gates (signal stability) need adaptation.** F1.1-F1.4 were calibrated for cross-sectional ranking signals. For a binary regime indicator, the equivalent stability tests are: regime-transition rate, false-trigger rate, hindsight-bias absence (signal computable at time t using only data available at t), and parameter sensitivity. The pre-registration must specify these as F1 equivalents.
- **F3 sub-gates (misattribution).** The candidate must not be a disguised funding-fade strategy. F3.3-equivalent attribution decomposition is required: would a naive funding-fade have produced similar results? If yes, the candidate is a complicated wrapper for the cluster's reflex; if no, the regime-state framing is doing real work.

---

## 6. What this candidate is NOT

- It is NOT a guarantee of clearing Stage B. The intuition is real but the operationalization will be tested honestly. The framework's discipline is unchanged.
- It is NOT the "platform pivot" from earlier in this session. The platform-vs-strategies tension exists but is deferred to a separate framework-evolution memo, if and when, after candidate #5 runs.
- It is NOT a cross-sectional ranking strategy disguised in regime language. The signal is a system-state classifier, not an asset ranker.
- It is NOT a fundamental-data candidate. All inputs are price/funding/OI/basis — Binance-native, PIT-clean.

---

## 7. Next actions

**7.1** Commit this selection memo.

**7.2** Sit with the originating intuition for 24-72 hours per operator discretion. The framework's discipline tolerates pre-registration drafting being separated from selection commitment by a buffer. The pre-registration is the binding artifact; this selection memo is the precursor.

**7.3** If after 24-72 hours the intuition still survives re-reading, draft the candidate #5 pre-registration in a separate session. Pre-registration must lock:
- Exact thresholds for F, O, B, S
- Persistence window N and required fractions p_f, p_b
- The single operationalization choice from §4 (4.A, 4.B, or 4.C)
- Stage A and Stage B gate parameters (with F1/F3 equivalents specified)
- Kill criteria

**7.4** If after 24-72 hours the intuition no longer feels real on re-read, the selection memo remains committed (as an honest record of the intuition that was articulated) but no pre-registration follows. The candidate #5 slot reopens.

**7.5** This selection memo is the historical record of the originating intuition. It is committed regardless of whether candidate #5 ultimately reaches pre-registration. Honesty requires recording what was articulated and when, even if it doesn't proceed.

---

## 8. References

- Master Sleeve B pre-registration: `fe909bb`
- Q0 Data Viability Gate: `cb9d975`
- Stage A gate inheritance: `39970f1`
- Sleeve B framework review (analytical context): `7c10ca0`
- Q0 cluster-diversity sub-criterion: `3ec7a32`
- Prior kill actions (corpus context):
  - A2 basis: `924a930`
  - xs-momentum: `f3e078e`
  - Quality: `bf642d1`
  - Candidate #3: `bf0a23e`
  - Candidate #4: `5619d09`

---

*Selection memo for Sleeve B candidate #5 — system-stabilizer regime detection. Family §3.1.11 (cross-asset/regime) with scoping note distinguishing from canonical correlation-regime detection. Q0 PASS_CLEAN across all sub-criteria including §4 cluster-diversity (count 0, no §4(c) firing). Originating intuition: persistent joint distortion of funding/OI/basis under stress signals impaired system stabilizers; trading rule (regime filter / counter-position / defensive overlay) locked at pre-registration. Pre-registration deferred by 24-72h buffer per §7.2 to honor anti-chat-momentum discipline.*
