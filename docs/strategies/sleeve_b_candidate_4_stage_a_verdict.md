# Sleeve B Candidate #4 — Stage A verdict memo

**Status:** Stage A complete
**Date:** 2026-05-16
**Subordinate to:** `docs/strategies/sleeve_b_candidate_4_preregistration.md` (commit `59c1156`)
**OOS window:** 2023-04-15 → 2026-04-15
**Rebalance dates evaluated:** 157 (weekly Mondays)

---

## 0. Summary

| Sub-gate | Status (per §2.5 of pre-reg) | Verdict |
|---|---|---|
| A1 — Static coverage | PASS_DIRECT | **PASS_WARNING** |
| A2 — Temporal stability | PASS_ADAPTED | **PASS_CLEAN** |
| A3 — Source agreement | NOT_APPLICABLE | N/A |
| A4 — PIT discipline | PASS_DIRECT | **PASS_CLEAN** |
| A5 — Taxonomy sensitivity | PASS_DIRECT | **PASS** |

**Stage B authorization: CONSTRAINED (per §4.B3: A1 PASS_WARNING tightens Stage B thresholds)**

---

## 1. A1 — Static coverage

- C(T) range: [16, 30]
- min C(T) = 16 (first observed at 2023-04-17)
- max C(T) = 30 (first observed at 2026-02-02)

**Classification rule:**

| min C(T) | Classification |
|---|---|
| < 15 | FAIL |
| 15–17 | PASS_WARNING |
| ≥ 18 | PASS_CLEAN |

**A1 verdict: PASS_WARNING**

---

## 2. A2 — Temporal stability (corrected per 39970f1 §2.2)

Four-step evaluation:

- D(T) range: [16, 30] — deterministic expansion from fixture
- C(T) range: [16, 30] — actual OHLCV-verified eligibility
- E(T) = C(T) − D(T) range: [0, 0]
- Spread of E (max − min) = 0

**Classification rule:**

| Spread of E | Classification |
|---|---|
| > 6 | FAIL |
| ≤ 6 | PASS_CLEAN |

**A2 verdict: PASS_CLEAN**

**Non-zero E(T) events:** 0. E(T) ≡ 0 across all rebalance dates.

OHLCV availability matches listing-age eligibility exactly. No delistings,
suspensions, or extended OHLCV gaps observed in the universe across OOS.

---

## 3. A3 — Source agreement

**NOT_APPLICABLE.** Single-venue construction (Binance USDT-M perps). No
cross-source comparison is required or meaningful for this candidate.

---

## 4. A4 — PIT discipline

**PASS_CLEAN.** Binance daily kline endpoint is venue-native immutable historical
with no documented backfill mechanism. Klines fetched at any future date for
a given historical interval return identical values to klines fetched at that
interval's close. The cache at `~/.cache/hydra-next/binance_klines_1d/` serves
from immutable monthly archives.

No evidence of Binance kline revision was surfaced during Stage A execution.

---

## 5. A5 — Taxonomy sensitivity

**PASS.** The metric `momentum / realized_vol` has no reasonable taxonomy
alternatives. Window-length choices (30-day momentum, 45-day vol) are parameters
locked at §2.6 of the pre-registration, not taxonomy decisions. No sensitivity
test is required or meaningful.

---

## 6. D(T) trajectory

Computed from the frozen fixture by applying the 45-day listing-age rule to each
asset's onboard_date. Monotone non-decreasing across OOS by construction.

Key transition dates:

| Rebalance date | D(T) |
|---|---|
| 2023-04-17 | 16 |
| 2023-06-19 | 18 |
| 2024-05-20 | 19 |
| 2024-05-27 | 20 |
| 2025-03-10 | 22 |
| 2025-05-12 | 24 |
| 2025-06-02 | 25 |
| 2025-07-14 | 26 |
| 2025-10-20 | 27 |
| 2025-11-17 | 28 |
| 2025-12-01 | 29 |
| 2026-02-02 | 30 |

Total deterministic expansion across OOS: 14 names (16 → 30).

---

## 7. Excluded names

Names that were not eligible at every rebalance date, with first-eligible date:

| Symbol | Onboard date | First-eligible date |
|---|---|---|
| SIRENUSDT | 2025-03-22 | 2025-05-06 |
| RAVEUSDT | 2025-12-14 | 2026-01-28 |
| TAOUSDT | 2024-04-11 | 2024-05-26 |
| HYPEUSDT | 2025-05-30 | 2025-07-14 |
| RIVERUSDT | 2025-10-17 | 2025-12-01 |
| 1000PEPEUSDT | 2023-05-05 | 2023-06-19 |
| STOUSDT | 2025-04-12 | 2025-05-27 |
| PAXGUSDT | 2025-03-27 | 2025-05-11 |
| PIPPINUSDT | 2025-01-24 | 2025-03-10 |
| ARIAUSDT | 2025-09-03 | 2025-10-18 |
| SUIUSDT | 2023-05-03 | 2023-06-17 |
| NOMUSDT | 2025-10-01 | 2025-11-15 |
| ENAUSDT | 2024-04-02 | 2024-05-17 |
| TRUMPUSDT | 2025-01-18 | 2025-03-04 |

---

## 8. Stage B authorization

**CONSTRAINED (per §4.B3: A1 PASS_WARNING tightens Stage B thresholds)**

Stage B operates under the warning-tightened threshold structure of §4.B3:
Sharpe ≥ 1.75 AND drawdown ≤ 20% required for promotion eligibility.

---

## 9. Audit data

Full rebalance-date series for D(T), C(T), E(T):

| Rebalance date | D(T) | C(T) | E(T) |
|---|---|---|---|
| 2023-04-17 | 16 | 16 | 0 |
| 2023-04-24 | 16 | 16 | 0 |
| 2023-05-01 | 16 | 16 | 0 |
| 2023-05-08 | 16 | 16 | 0 |
| 2023-05-15 | 16 | 16 | 0 |
| 2023-05-22 | 16 | 16 | 0 |
| 2023-05-29 | 16 | 16 | 0 |
| 2023-06-05 | 16 | 16 | 0 |
| 2023-06-12 | 16 | 16 | 0 |
| 2023-06-19 | 18 | 18 | 0 |
| 2023-06-26 | 18 | 18 | 0 |
| 2023-07-03 | 18 | 18 | 0 |
| 2023-07-10 | 18 | 18 | 0 |
| 2023-07-17 | 18 | 18 | 0 |
| 2023-07-24 | 18 | 18 | 0 |
| 2023-07-31 | 18 | 18 | 0 |
| 2023-08-07 | 18 | 18 | 0 |
| 2023-08-14 | 18 | 18 | 0 |
| 2023-08-21 | 18 | 18 | 0 |
| 2023-08-28 | 18 | 18 | 0 |
| 2023-09-04 | 18 | 18 | 0 |
| 2023-09-11 | 18 | 18 | 0 |
| 2023-09-18 | 18 | 18 | 0 |
| 2023-09-25 | 18 | 18 | 0 |
| 2023-10-02 | 18 | 18 | 0 |
| 2023-10-09 | 18 | 18 | 0 |
| 2023-10-16 | 18 | 18 | 0 |
| 2023-10-23 | 18 | 18 | 0 |
| 2023-10-30 | 18 | 18 | 0 |
| 2023-11-06 | 18 | 18 | 0 |
| 2023-11-13 | 18 | 18 | 0 |
| 2023-11-20 | 18 | 18 | 0 |
| 2023-11-27 | 18 | 18 | 0 |
| 2023-12-04 | 18 | 18 | 0 |
| 2023-12-11 | 18 | 18 | 0 |
| 2023-12-18 | 18 | 18 | 0 |
| 2023-12-25 | 18 | 18 | 0 |
| 2024-01-01 | 18 | 18 | 0 |
| 2024-01-08 | 18 | 18 | 0 |
| 2024-01-15 | 18 | 18 | 0 |
| 2024-01-22 | 18 | 18 | 0 |
| 2024-01-29 | 18 | 18 | 0 |
| 2024-02-05 | 18 | 18 | 0 |
| 2024-02-12 | 18 | 18 | 0 |
| 2024-02-19 | 18 | 18 | 0 |
| 2024-02-26 | 18 | 18 | 0 |
| 2024-03-04 | 18 | 18 | 0 |
| 2024-03-11 | 18 | 18 | 0 |
| 2024-03-18 | 18 | 18 | 0 |
| 2024-03-25 | 18 | 18 | 0 |
| 2024-04-01 | 18 | 18 | 0 |
| 2024-04-08 | 18 | 18 | 0 |
| 2024-04-15 | 18 | 18 | 0 |
| 2024-04-22 | 18 | 18 | 0 |
| 2024-04-29 | 18 | 18 | 0 |
| 2024-05-06 | 18 | 18 | 0 |
| 2024-05-13 | 18 | 18 | 0 |
| 2024-05-20 | 19 | 19 | 0 |
| 2024-05-27 | 20 | 20 | 0 |
| 2024-06-03 | 20 | 20 | 0 |
| 2024-06-10 | 20 | 20 | 0 |
| 2024-06-17 | 20 | 20 | 0 |
| 2024-06-24 | 20 | 20 | 0 |
| 2024-07-01 | 20 | 20 | 0 |
| 2024-07-08 | 20 | 20 | 0 |
| 2024-07-15 | 20 | 20 | 0 |
| 2024-07-22 | 20 | 20 | 0 |
| 2024-07-29 | 20 | 20 | 0 |
| 2024-08-05 | 20 | 20 | 0 |
| 2024-08-12 | 20 | 20 | 0 |
| 2024-08-19 | 20 | 20 | 0 |
| 2024-08-26 | 20 | 20 | 0 |
| 2024-09-02 | 20 | 20 | 0 |
| 2024-09-09 | 20 | 20 | 0 |
| 2024-09-16 | 20 | 20 | 0 |
| 2024-09-23 | 20 | 20 | 0 |
| 2024-09-30 | 20 | 20 | 0 |
| 2024-10-07 | 20 | 20 | 0 |
| 2024-10-14 | 20 | 20 | 0 |
| 2024-10-21 | 20 | 20 | 0 |
| 2024-10-28 | 20 | 20 | 0 |
| 2024-11-04 | 20 | 20 | 0 |
| 2024-11-11 | 20 | 20 | 0 |
| 2024-11-18 | 20 | 20 | 0 |
| 2024-11-25 | 20 | 20 | 0 |
| 2024-12-02 | 20 | 20 | 0 |
| 2024-12-09 | 20 | 20 | 0 |
| 2024-12-16 | 20 | 20 | 0 |
| 2024-12-23 | 20 | 20 | 0 |
| 2024-12-30 | 20 | 20 | 0 |
| 2025-01-06 | 20 | 20 | 0 |
| 2025-01-13 | 20 | 20 | 0 |
| 2025-01-20 | 20 | 20 | 0 |
| 2025-01-27 | 20 | 20 | 0 |
| 2025-02-03 | 20 | 20 | 0 |
| 2025-02-10 | 20 | 20 | 0 |
| 2025-02-17 | 20 | 20 | 0 |
| 2025-02-24 | 20 | 20 | 0 |
| 2025-03-03 | 20 | 20 | 0 |
| 2025-03-10 | 22 | 22 | 0 |
| 2025-03-17 | 22 | 22 | 0 |
| 2025-03-24 | 22 | 22 | 0 |
| 2025-03-31 | 22 | 22 | 0 |
| 2025-04-07 | 22 | 22 | 0 |
| 2025-04-14 | 22 | 22 | 0 |
| 2025-04-21 | 22 | 22 | 0 |
| 2025-04-28 | 22 | 22 | 0 |
| 2025-05-05 | 22 | 22 | 0 |
| 2025-05-12 | 24 | 24 | 0 |
| 2025-05-19 | 24 | 24 | 0 |
| 2025-05-26 | 24 | 24 | 0 |
| 2025-06-02 | 25 | 25 | 0 |
| 2025-06-09 | 25 | 25 | 0 |
| 2025-06-16 | 25 | 25 | 0 |
| 2025-06-23 | 25 | 25 | 0 |
| 2025-06-30 | 25 | 25 | 0 |
| 2025-07-07 | 25 | 25 | 0 |
| 2025-07-14 | 26 | 26 | 0 |
| 2025-07-21 | 26 | 26 | 0 |
| 2025-07-28 | 26 | 26 | 0 |
| 2025-08-04 | 26 | 26 | 0 |
| 2025-08-11 | 26 | 26 | 0 |
| 2025-08-18 | 26 | 26 | 0 |
| 2025-08-25 | 26 | 26 | 0 |
| 2025-09-01 | 26 | 26 | 0 |
| 2025-09-08 | 26 | 26 | 0 |
| 2025-09-15 | 26 | 26 | 0 |
| 2025-09-22 | 26 | 26 | 0 |
| 2025-09-29 | 26 | 26 | 0 |
| 2025-10-06 | 26 | 26 | 0 |
| 2025-10-13 | 26 | 26 | 0 |
| 2025-10-20 | 27 | 27 | 0 |
| 2025-10-27 | 27 | 27 | 0 |
| 2025-11-03 | 27 | 27 | 0 |
| 2025-11-10 | 27 | 27 | 0 |
| 2025-11-17 | 28 | 28 | 0 |
| 2025-11-24 | 28 | 28 | 0 |
| 2025-12-01 | 29 | 29 | 0 |
| 2025-12-08 | 29 | 29 | 0 |
| 2025-12-15 | 29 | 29 | 0 |
| 2025-12-22 | 29 | 29 | 0 |
| 2025-12-29 | 29 | 29 | 0 |
| 2026-01-05 | 29 | 29 | 0 |
| 2026-01-12 | 29 | 29 | 0 |
| 2026-01-19 | 29 | 29 | 0 |
| 2026-01-26 | 29 | 29 | 0 |
| 2026-02-02 | 30 | 30 | 0 |
| 2026-02-09 | 30 | 30 | 0 |
| 2026-02-16 | 30 | 30 | 0 |
| 2026-02-23 | 30 | 30 | 0 |
| 2026-03-02 | 30 | 30 | 0 |
| 2026-03-09 | 30 | 30 | 0 |
| 2026-03-16 | 30 | 30 | 0 |
| 2026-03-23 | 30 | 30 | 0 |
| 2026-03-30 | 30 | 30 | 0 |
| 2026-04-06 | 30 | 30 | 0 |
| 2026-04-13 | 30 | 30 | 0 |
