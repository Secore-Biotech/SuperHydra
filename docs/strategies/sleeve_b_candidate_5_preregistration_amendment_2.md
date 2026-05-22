# Sleeve B Candidate #5 — Pre-registration Amendment #2 (Consolidated)

**Subject:** Consolidated data-cadence and signal-cadence corrections; F1.1/F1.2 weekly-unit rescaling
**Amends:** `fe34b76` (candidate #5 pre-registration), and supplements `8492309` (Amendment #1)
**Date:** 2026-05-22
**Status:** Pre-evidence specification correction. No D-level engineering has commenced. No evaluation data has been generated.
**Authority:** Operator decision following pre-D1 audit of pre-registration data inputs and signal-cadence consistency. Pre-registration §1.1, §1.2, and §5.2 implicitly assumed data and signal cadences that do not match either vendor reality or the consuming host strategy's actual rebalance cadence.
**Subordinate to:** Q0 §3.6 framework evolution memo committed in the same session as this amendment.

---

## 1. Why this amendment is consolidated

A pre-D1 audit on candidate #5's pre-registration surfaced four related specification errors, not the one OI-granularity error that triggered the audit. Per operator direction during the audit, all four are addressed in this single consolidated amendment rather than chained across multiple amendments. This preserves audit-trail clarity (one before-D1 governance commit instead of three or four) and demonstrates the discipline the new Q0 §3.6 framework rule encodes for future candidates.

The four errors corrected here are:

1. **OI granularity over-specified** — pre-reg implied sub-day OI cadence; Binance archives only daily.
2. **Realized vol cadence over-specified** — pre-reg specified 8h close intervals; signal is consumed only at weekly rebalances.
3. **Spot/perp price cadence over-specified** — pre-reg implied intraday cadence for basis computation; signal is consumed only at weekly rebalances.
4. **F1.1/F1.2 thresholds in wrong units** — thresholds expressed in 8h-period units, while the signal is evaluated only on weekly grid.

Errors 2-4 were not anticipated when Amendment #2 was first planned as a narrow OI-only correction; they surfaced during the audit. All four are pre-evidence and structurally interrelated (the cadence mismatch in 2-3 directly implies the unit error in 4). Bundling is therefore both procedurally cleaner and substantively correct.

The underlying governance lesson — that pre-registration drafting must include explicit data-granularity verification — is promoted to permanent framework status via the Q0 §3.6 evolution memo committed in the same session as this amendment. The lesson is no longer candidate-local.

---

## 2. Correction 1 — OI input at daily granularity

### 2.1 The problem

Pre-registration `fe34b76` §1.1 specifies:

> "Open interest ratio `O(i, t) / O_ref(i, t)` where `O_ref(i, t)` is the trailing 30-day rolling median of OI for asset *i*. Computed in USD-notional, not contracts."

And §1.2(b) applies this check at the same evaluation cadence as funding/basis (per Amendment #1: real-time persistence window N = 7 calendar days with native funding-event counts).

The implicit assumption — that OI is available at sub-day cadence over the full OOS window 2023-04-15 → 2026-04-15 — does not hold.

Verified findings (2026-05-22):

- Binance REST `/futures/data/openInterestHist` endpoint serves only the latest 1 month. Useless for OOS backfill.
- Binance public archive at `data.binance.vision/data/futures/um/daily/metrics/{symbol}/` publishes a per-day metrics file with the OI value as `sum_open_interest_value` (USD-notional). This is the only PIT-clean Binance-native OI history available.
- The archived metrics file is daily granularity. One OI reading per asset per UTC day.
- Third-party sub-day historical OI is paid and violates Q0 §2.

### 2.2 The correction

OI input is sourced from `https://data.binance.vision/data/futures/um/daily/metrics/{symbol}/{symbol}-metrics-{YYYY-MM-DD}.zip`. One observation per asset per UTC day. The relevant fields:

- `create_time` — daily snapshot timestamp (treated as end-of-day UTC for the named date)
- `sum_open_interest_value` — USD-notional OI at the snapshot time

`O_ref(i, t)` becomes the trailing 30-calendar-day rolling median of daily `sum_open_interest_value` computed strictly over days prior to the evaluation timestamp.

### 2.3 No-look-ahead rule

For any signal evaluation at timestamp `t` falling within UTC day `D`:

- The OI value used is the most recent daily OI observation whose `create_time` is strictly less than `t`'s UTC date `D` — i.e., from day `D-1` or earlier.
- The day-`D` archive is not consulted for any evaluation timestamp within day `D`, regardless of when it became technically available.

Combined with Correction 2 below (weekly signal cadence), this becomes: for each weekly rebalance date `t_rebalance`, the OI value used is the daily archive from the UTC date strictly before `t_rebalance`.

### 2.4 Role-change clarification

This correction changes the role of OI in the signal, not merely its granularity:

OI shifts from an intraday co-moving stabilizer signal into a daily positioning-state filter. Funding rate, basis, and realized vol are evaluated at weekly cadence per Corrections 2-4. OI alone operates at daily resolution.

The economic interpretation:

- Funding and basis at weekly cadence (with 7-day persistence windows) still test "is current pricing distortion persistent at the system's own rebalancing frequency?"
- Realized vol still tests "is the market currently in a high-vol state?"
- OI at daily resolution tests "is positioning sticky at the day-over-day level, ignoring intraday noise?"

A positioning-state filter at daily resolution still captures the FTX-style observation that motivated the candidate: during the Nov 2022 collapse, OI elevation was sustained over many days, not just intraday spikes. Sticky positioning that persists day-over-day is the relevant marker.

### 2.5 OI sub-condition rewording

The condition in `fe34b76` §1.2(b) is preserved structurally. Under this amendment, the reading at any signal evaluation timestamp `t` (which per Correction 2 is a weekly rebalance date `t_rebalance`):

> Let `D_prev` be the most recent UTC date strictly before `t_rebalance`'s UTC date for which a Binance daily-metrics file is available for asset `i`. The OI condition holds iff:
>
> ```
> sum_open_interest_value(i, D_prev) / median{sum_open_interest_value(i, d) : d ∈ [D_prev − 30 days, D_prev − 1 day]} > oi_threshold
> ```

The `oi_threshold` parameter values (1.30× baseline, 1.20× V2, 1.50× V3 per `fe34b76` §2) are unchanged.

---

## 3. Correction 2 — Signal cadence aligned to host strategy

### 3.1 The problem

Pre-registration `fe34b76` §1.1 specifies funding rate, basis, and realized vol with implied intraday cadence (8h funding events, 8h close intervals for realized vol). The persistence rule §1.2 describes evaluation as if the signal fires per 8-hour period.

But the signal's consumer is the regime filter at Q2 = 4.A, which operates on candidate #4's audit log (`ef788b7`). Candidate #4's audit log is at weekly cadence — 157 weekly rebalances over 2023-04-15 → 2026-04-15. The filter only needs `IMPAIRED(i, t)` at those 157 weekly timestamps. Sub-week IMPAIRED transitions are never read.

Specifying the signal at 8h cadence is therefore over-specification. The signal can be computed natively at the host strategy's weekly rebalance cadence with no information loss.

### 3.2 The correction

The signal `IMPAIRED(i, t)` is evaluated only at the weekly rebalance dates from candidate #4's audit log. For each asset `i` and each weekly rebalance date `t_rebalance`:

- **Funding sub-condition** (§1.2(a) per Amendment #1): Count native funding events for asset `i` within `[t_rebalance − 7 days, t_rebalance)`. Apply `|f| > funding_threshold` and `p_f` rule to that event set. Funding rates are still retrieved at their native cadence per Amendment #1; what changes is the evaluation timestamp.
- **OI sub-condition** (§1.2(b) per Correction 1 above): Use the daily OI archive from the UTC date strictly before `t_rebalance`.
- **Basis sub-condition** (§1.2(c)): Count native basis observations within `[t_rebalance − 7 days, t_rebalance)`. With Correction 3, basis is computed from daily price closes — one observation per UTC day in the window, approximately 7 observations.
- **Stress sub-condition** (§1.2(d)): Realized vol computed at `t_rebalance` from daily returns over the trailing 7 and 60 days per Correction 4.

The signal output is one binary `IMPAIRED(i, t_rebalance)` per asset per weekly rebalance date.

### 3.3 What does NOT change

The economic interpretation of each sub-condition is unchanged. The persistence intuition holds: "Has distortion been present across the trailing 7 days?" — the evaluation cadence is the frequency of asking that question, not the answer.

The sign-coherence requirement (funding and basis distortion must point the same direction during the persistence window) remains binding per pre-reg §1.2.

---

## 4. Correction 3 — Basis from daily closes

### 4.1 The problem

Pre-registration §1.1 specifies basis as a per-asset per-evaluation quantity computed from spot and perp prices. The implicit cadence (matching funding/realized vol per the rest of §1.1) suggests intraday.

The repository's kline cache contains only `binance_klines_1d` (verified 2026-05-22). Sub-day kline ingestion for top-30 spot and top-30 perp across the OOS window would add substantial D1 engineering scope.

Per Correction 2, the signal is consumed at weekly cadence. Sub-day basis observations are not required.

### 4.2 The correction

Basis is computed from daily close prices (1d klines, both spot and perp). For each weekly rebalance date `t_rebalance`:

- Use the trailing 7 calendar days of daily basis observations: `b(i, d) = (P_perp_close(i, d) − P_spot_close(i, d)) / P_spot_close(i, d)` for each UTC day `d ∈ [t_rebalance − 7 days, t_rebalance)`.
- Apply `|b| > basis_threshold` and `p_b` rule to the daily-observation set. With 7 daily observations and `p_b = 0.66`, the threshold condition requires `|b| > basis_threshold` on at least 5 of the 7 daily basis values.
- Sign-coherence with funding is checked using the daily basis signs.

The `basis_threshold` parameter values (50 bps baseline, 35 bps V2, 80 bps V3) are unchanged.

### 4.3 Data source

Existing `BinanceKlinesArchiveFetcher` at `data/ingestion/vendors/binance/klines_archive_fetcher.py`, interval `"1d"`. Cache at `artifacts/cache/binance_klines_1d/`. Both spot and perp daily klines are fetchable from this existing infrastructure; no new fetcher is required for basis.

---

## 5. Correction 4 — Realized vol from daily returns

### 5.1 The problem

Pre-registration §1.1 specifies stress as the ratio of trailing 7-day realized vol to trailing 60-day median realized vol, with the underlying log returns computed at 8-hour close intervals. Same issue as Correction 3: signal is consumed weekly; 8h returns are not required; the repository has only daily klines cached.

### 5.2 The correction

Realized vol is computed from daily log returns. For each weekly rebalance date `t_rebalance`:

- `realized_vol_7d(i, t_rebalance)` = standard deviation of daily log returns for asset `i` over the 7 daily closes in `[t_rebalance − 7 days, t_rebalance)`.
- `realized_vol_60d_median(i, t_rebalance)` = trailing 60-day median of `realized_vol_7d(i, ·)` computed as a rolling daily series ending at `t_rebalance`'s UTC date.
- Stress condition: `S(i, t_rebalance) = realized_vol_7d(i, t_rebalance) / realized_vol_60d_median(i, t_rebalance) > stress_threshold`.

The `stress_threshold` parameter values (1.50× baseline, 1.30× V2, 2.00× V3) are unchanged.

### 5.3 Data source

Same as Correction 3: existing `BinanceKlinesArchiveFetcher` at `1d` interval, already-existing cache.

### 5.4 Statistical note (non-binding)

Daily-return realized vol over 7 observations is statistically thin (n=7 for the numerator). The candidate accepts this. The economic intuition is about regime presence over the trailing week, not about precise vol estimation. If future operators want a more statistically robust realized vol estimator, that would be a different candidate, not an amendment to this one.

---

## 6. Correction 5 — F1.1/F1.2 thresholds rescaled to weekly units

### 6.1 The problem

Pre-registration §5.2 specifies:

- **F1.1** — Average per-asset annual firing rate must be in `[3, 60]` per year. Outside this range: FAIL.
- **F1.2** — Median consecutive-fire duration in `[3, 30]` 8h periods per config: PASS_CLEAN.

Both thresholds were defined under the implicit assumption that the signal fires per 8h period. With Correction 2, the signal fires per weekly rebalance date — 52 evaluations per asset per year, not 1095 (3 × 365).

Keeping the numerical thresholds while changing units would produce nonsense: 60 weekly firings/year means firing 60/52 ≈ 1.15 times per week, which exceeds the cadence at which the signal is even evaluated.

### 6.2 The correction

F1.1 and F1.2 are rescaled to weekly units. The economic intent is preserved (regime indicator that fires neither too rarely to be informative nor too frequently to discriminate):

- **F1.1 (rescaled)** — Average per-asset annual firing rate must be in `[1, 20]` weekly firings per year. Outside this range: FAIL.
  - Lower bound `1`: at least one weekly firing per asset per year on average — translates the original "3 8h-periods/year" intent (signal must be present in the corpus) into weekly terms.
  - Upper bound `20`: at most 20 weekly firings per asset per year on average (approximately 38% of weeks) — translates the original "60 8h-periods/year" intent (signal must discriminate) into weekly terms.

- **F1.2 (rescaled)** — Median consecutive-fire duration in `[1, 8]` weekly periods per config: PASS_CLEAN.
  - Lower bound `1`: a regime must persist at least one weekly evaluation to be a regime.
  - Upper bound `8`: median consecutive weekly fires no more than 8 weeks (approximately 2 months). The original `[3, 30]` 8h-periods upper bound (30 × 8h ≈ 10 days) translates to about 1.5 weeks naively; the rescaled `[1, 8]` weekly upper bound is more generous because the FTX-era intuition was about regimes that persist for weeks-to-months, not days.

The rescaling is intentionally generous on the upper bound to preserve the economic intent that real impaired-stabilizer regimes do last weeks. The original 8h-period upper bound was likely under-specified relative to the candidate's actual intuition.

### 6.3 F1.3 and F1.4 unchanged in unit semantics

- **F1.3** (hindsight-bias absence): not affected by cadence; the no-look-ahead requirement applies regardless.
- **F1.4** (parameter robustness via 4-config grid): the grid logic in `fe34b76` §5.2 was unit-agnostic; the four configs are still evaluated and the verdict-build rule (all 4 pass = CLEAN; 3 of 4 = WARNING; baseline-only = FAIL) stands as written.

### 6.4 F3 sub-gates unchanged

F3.1, F3.2, F3.3 (naïve funding-fade comparison, naïve vol-filter comparison, true-positive attribution) operate on the candidate's improvement to candidate #4's host strategy. The host strategy is weekly; the F3 thresholds are in Sharpe and ratio terms; no unit rescaling is required.

---

## 7. Data abstention rule update

Pre-registration `fe34b76` §1.3 abstention rule is extended to cover the new daily-data dependencies. For asset `i` to participate in the signal at weekly rebalance date `t_rebalance`, the previous abstention conditions still hold, plus:

- A daily Binance metrics file must be available for asset `i` on at least 30 of the 31 days preceding `t_rebalance`'s UTC date. More than 1 missing day → `IMPAIRED(i, t_rebalance) := 0`, `ABSTAIN(i, t_rebalance) = 1`, `abstain_reason = "insufficient_oi_history"`.
- The asset's most recent daily metrics file before `t_rebalance` must be no older than 2 UTC days. Beyond that staleness threshold → asset abstains, `abstain_reason = "stale_oi"`.
- The asset's daily 1d klines must be available for at least 67 of the 67 days preceding `t_rebalance` (60-day realized vol denominator + 7-day numerator). Missing klines → asset abstains, `abstain_reason = "insufficient_price_history"`.

Coverage ratio `C(t_rebalance) = eligible(t_rebalance) / universe_size(t_rebalance)` is reported per pre-reg §4.2.

---

## 8. Why this amendment is pre-evidence, not result-shaping

Same logic as Amendment #1 (`8492309` §3) and applied to the consolidated scope:

- No D-level engineering has commenced; no signal values have been computed.
- No B3, F1, or F3 sub-gate outputs exist for any of the four configs.
- The corrections resolve structural problems in the pre-registration's data specifications, not parameter calibrations.
- Under the pre-amendment readings of Corrections 1-3, the signal is unimplementable with PIT-clean Binance-native data within the repository's existing infrastructure. Correction 4 (F1.1/F1.2 rescaling) is a direct mechanical consequence of Correction 2 (signal cadence); leaving F1.1/F1.2 in 8h-period units while evaluating the signal weekly would produce thresholds that are nonsensical relative to the signal's actual firing cadence.
- The amendment is logged here, with full context, before D1 engineering begins. The audit trail is intact: future readers see the original pre-reg, Amendment #1, this consolidated Amendment #2, and the Q0 §3.6 framework memo in chronological order.

---

## 9. Why "rebuild candidate #5 from scratch" was rejected

Considered: shelve candidate #5, write a kill action recording the audit findings, and rebuild with a fresh pre-registration that incorporates Q0 §3.6 from the start. Rejected because:

- The originating intuition (FTX-derived impaired-stabilizers regime) is unchanged and remains structurally distinct from the prior cluster. Killing the candidate would discard a valid intuition over a drafting hygiene issue.
- The corrections in this amendment are pre-evidence and structural, not result-shaping. They are exactly the class of correction that pre-evidence amendments exist to handle.
- The promotion of Q0 §3.6 to permanent framework status (via the framework memo committed in the same session) ensures the underlying drafting-error pattern does not recur on future candidates.
- A from-scratch rebuild would itself need to clear Q0 §3.6, which now requires explicit data-granularity audits — i.e., it would do exactly the same verification work this audit just did, just framed differently. The substantive output would be similar; the procedural overhead would be greater.

---

## 10. What this amendment does NOT change

- All other locks in `fe34b76` remain binding: Lock 1 (4.A regime filter), Lock 2 (4-config grid), Lock 3 ((d) restricted universe), all Stage A gates, all Stage B B3 promotion thresholds, all F1.3 and F1.4 sub-gates, all F3 sub-gates, all kill criteria.
- Amendment #1 (`8492309`) remains binding: persistence window N means real-time duration (7 calendar days for baseline, V2, V3; 4 calendar days for V1), not native event count.
- Numerical threshold values (`funding_threshold`, `oi_threshold`, `basis_threshold`, `stress_threshold`, fractions `p_f`, `p_b`) are unchanged.
- The four-config parameter grid (baseline, V1 short persistence, V2 loose thresholds, V3 tight thresholds) is unchanged.
- The sign-coherence requirement (funding and basis distortion of the same sign during the persistence window) remains binding.
- The anti-cherry-pick clause remains in force.

What does change is the evaluation context: signal evaluated at weekly rebalance dates only; OI at daily granularity with no-look-ahead; basis and realized vol computed from daily closes; F1.1 and F1.2 thresholds expressed in weekly units.

---

## 11. Engineering implications

### 11.1 Existing infrastructure reuse

D1 deliverable scope is reduced compared to the original pre-reg's implied scope:

- **Funding fetcher:** Reuse existing `data/ingestion/vendors/binance/funding_fetcher.py` (committed `8e60933`). No D1 engineering required.
- **Spot/perp 1d klines:** Reuse existing `BinanceKlinesArchiveFetcher` at `1d` interval; existing cache at `artifacts/cache/binance_klines_1d/` is sufficient for the universe and date range. Verify cache completeness per the abstention rule §7.

### 11.2 New D1 engineering

- **OI fetcher:** New at `data/ingestion/vendors/binance/oi_fetcher.py`. Fetches daily metrics ZIPs from `data.binance.vision/data/futures/um/daily/metrics/{symbol}/`, parses CSV inside each ZIP, surfaces typed canonical structure. Cache at `artifacts/cache/binance_metrics_daily/` mirroring the klines-cache convention. Implements throttled HTTP with retry per the existing `klines_archive_fetcher.py` pattern.
- **Signal module:** New at `strategies/sleeve_b/stabilizer_regime/signal.py`. Computes `IMPAIRED(i, t_rebalance)` per §3.2 above. All four configs supported as parameters. Abstention rule per §7 above. Sign-coherence per pre-reg §1.2. Outputs audit fields per §11.3 below.
- **Unit tests:** Per the new Q0 §3.6 framework memo's spirit, unit tests must cover:
  - Funding event counting over 7-day windows for assets on uniform 8h, uniform 4h, 1h cadences, and across cadence transitions.
  - Daily OI no-look-ahead rule (correct selection of `D_prev`).
  - Daily basis observation counting over 7-day windows.
  - Realized vol from daily returns over 7-day and 60-day windows.
  - All four configs producing distinct signal values on the same fixture data.
  - All abstention conditions (insufficient funding history, insufficient OI history, stale OI, insufficient price history).
  - Sign-coherence on/off cases.

### 11.3 Audit fields (downstream)

The signal audit log per `(asset, t_rebalance, config)` must include, at minimum:

- `asset`, `t_rebalance`, `config_name`
- `funding_events_in_window` — count of native funding events in the 7-day window
- `funding_fraction_above_threshold`
- `funding_sign_dominant`
- `basis_observations_in_window` — count (approximately 7 for daily basis)
- `basis_fraction_above_threshold`
- `basis_sign_dominant`
- `sign_coherent` — boolean
- `oi_evaluation_date` — the `D_prev` used
- `oi_value_used`
- `oi_reference_median` (30-day)
- `oi_ratio` and `oi_condition_met`
- `realized_vol_7d`, `realized_vol_60d_median`, `stress_ratio`, `stress_condition_met`
- `abstain_flag`, `abstain_reason`
- `IMPAIRED` (binary final output)

Downstream F1/F3 evaluators must use these audit fields rather than re-fetching raw data.

---

## 12. Auditability

This amendment is committed as a separate, dated artifact distinct from the pre-registration, Amendment #1, and the Q0 §3.6 framework evolution memo. The pre-registration `fe34b76`, Amendment #1 `8492309`, and the framework memo are left intact; this amendment supersedes them only on the specific points enumerated in §§2-6.

Future readers see five governance artifacts in chronological order:

1. Selection memo `cbd2633`
2. Pre-registration `fe34b76`
3. Amendment #1 (persistence window N semantics) `8492309`
4. Q0 §3.6 framework evolution memo (`b315d1e`)
5. Amendment #2 (consolidated data-cadence corrections — this commit)

D-level engineering commits and the D5 verdict memo must reference all five.

This amendment is binding from its commit and may not itself be amended after evidence is seen.

---

## 13. References

- Pre-registration being amended: `fe34b76`
- Amendment #1 (persistence window N): `8492309`
- Q0 §3.6 framework evolution memo: `b315d1e`
- Selection memo: `cbd2633`
- Q0 cluster-diversity: `3ec7a32`
- Q0 base: `cb9d975`
- Stage A gate inheritance: `39970f1`
- Framework review (analytical context): `7c10ca0`
- Master pre-registration: `fe909bb`
- Candidate #4 audit log (host strategy for §3.1 regime filter): `ef788b7`
- Universe fixture: `2af9981` (committed at `tests/fixtures/sleeve_b/universe_top30_20260415.json`)
- Sleeve A1 funding fetcher (reused infrastructure): commits `0e7b377`, `8e60933`
- Binance public archive (OI data source): `https://data.binance.vision/data/futures/um/daily/metrics/`
- Existing klines archive fetcher: `data/ingestion/vendors/binance/klines_archive_fetcher.py`

---

*Consolidated Amendment #2 to candidate #5 pre-registration. Four corrections: (1) OI sourced from daily Binance archived metrics with no-look-ahead rule; (2) signal evaluated only at weekly rebalance dates of candidate #4's audit log; (3) basis computed from daily closes via existing 1d kline cache; (4) realized vol computed from daily returns; (5) F1.1 and F1.2 thresholds rescaled to weekly units ([1, 20] firings/year, [1, 8] weekly periods median duration). All other locks unchanged. The Q0 §3.6 framework evolution memo committed in the same session promotes the underlying drafting-error lesson to permanent framework status binding for future candidates.*
