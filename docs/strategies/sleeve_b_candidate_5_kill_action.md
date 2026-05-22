# Sleeve B Candidate #5 — Kill Action

**Candidate:** System-stabilizer regime detection (joint funding/OI/basis persistence)
**Status:** Shelved pre-D1
**Date:** 2026-05-22
**Operator:** Wasseem
**D-level reached:** None. No engineering code committed. Zero signal evaluations.

---

## 1. What is being killed

The candidate #5 pre-registration at `fe34b76`, together with its two amendments (`8492309` Amendment #1, `433523f` Amendment #2), is shelved without proceeding to D1 engineering. The signal as specified in those documents will not be implemented.

The originating intuition — that persistent joint distortion of funding, open interest, and basis under market stress indicates impaired system stabilizers and informs regime state — is **not** killed. It remains a valid market observation. This kill action ends the specific governance stack built around testing that intuition under this pre-registration; it does not foreclose a future candidate built on the same intuition with a clean pre-registration.

## 2. Why it is being killed

This candidate is not being killed by alpha evidence. No signal was computed. No backtest ran. No gate fired. The kill is governance-driven: the pre-registration accumulated too many pre-D1 corrections before any code was written, and the most recent of those corrections was itself factually wrong.

The sequence on disk:

| # | Commit | Artifact | Outcome |
|---|---|---|---|
| 1 | `cbd2633` | Selection memo | Originating intuition recorded |
| 2 | `fe34b76` | Pre-registration | Signal/portfolio/gates committed |
| 3 | `8492309` | Amendment #1 — persistence window N semantics | Funding-cadence heterogeneity correction (Error 1) |
| 4 | `b315d1e` | Framework evolution Q0 §3.6 — data-granularity audit | Promoted lesson to framework |
| 5 | `433523f` | Amendment #2 — consolidated data-cadence corrections | OI granularity (Error 2), signal-cadence consistency (Error 3), F1 unit rescaling |
| 6 | This commit | Kill action | Halts the candidate |

Six governance artifacts. Zero engineering deliverables. That ratio alone would be a concern. The triggering event for this kill is more specific:

**Amendment #2's central correction — Error 2 — was factually wrong.**

Amendment #2 §2.1 and §2.4 claimed that "Binance archives OI only at daily granularity. One OI reading per asset per UTC day." It then specified OI as a "daily positioning-state filter" with a no-look-ahead rule for intraday evaluations. This claim was based on reading a Binance public-data GitHub issue from 2023 (issue #211) that stated "we can get the open interest for the day only" — interpreted as daily granularity.

A pre-D1 inspection of an actual archive ZIP (`BTCUSDT-metrics-2024-01-15.zip`, 11.6 KB, 289 lines including header) on 2026-05-22 produced ground truth: the archive contains **288 rows at 5-minute intervals** (00:00, 00:05, 00:10, ...) within each daily file. The header confirms columns `create_time, symbol, sum_open_interest, sum_open_interest_value, count_toptrader_long_short_ratio, sum_toptrader_long_short_ratio, count_long_short_ratio, sum_taker_long_short_vol_ratio`. OI is available at **5-minute granularity in the historical archive**.

The 2023 GitHub issue's "for the day only" phrasing was about daily archive packaging (one file per day vs monthly), not about intraday granularity. Amendment #2 misread it. Q0 §3.6's analytical basis cited Error 2 as one of three errors justifying the new framework rule; with Error 2 now disproven, two of the three remain (Errors 1 and 3 are still valid), but the specific framing of Q0 §3.6's evidence base is partly wrong on disk.

## 3. Why we are not committing Amendment #3 to fix Amendment #2

This was the closest alternative considered and explicitly rejected. Drafting an Amendment #3 that reverses Amendment #2's OI correction and re-specifies OI at 5-minute granularity would be technically possible. It would also teach the wrong operating habit: continue patching the governance stack until the pre-registration becomes implementable, regardless of how many corrections that takes.

That habit is exactly what the framework discipline was designed to prevent. Five framework artifacts written in response to five-zero kills, plus three governance commits in response to drafting errors discovered after pre-registration, indicates a system reproducing itself in markdown rather than producing engineering evidence. An Amendment #3 would extend the pattern.

The cleaner move is to stop, kill the pre-registration as written, and let a future candidate be drafted from a clean state — with the actual data shape verified before the pre-registration is committed.

## 4. What this kill action does NOT do

- It does **not** invalidate the originating intuition. Sticky OI elevation, persistent funding-rate distortion, and non-normalizing basis under stress remain plausible markers of impaired-stabilizer regimes.
- It does **not** invalidate the discovery that OI is available at 5-minute granularity. That fact is real and is now part of the program's knowledge.
- It does **not** invalidate Errors 1 and 3 from Q0 §3.6's analytical basis. Funding cadence heterogeneity (Error 1) and signal-cadence over-specification (Error 3) are real findings. The Q0 §3.6 framework rule remains binding for future candidates.
- It does **not** retire candidate #4's audit log at `ef788b7`. That log remains the legitimate host strategy for any future regime-filter candidate.
- It does **not** require reversion of any commit. All artifacts remain on disk as historical record.

## 5. What this kill action does

- Closes candidate #5's track. No D1, no D2, no D3, no D4, no D5 will be drafted under the `fe34b76` pre-registration.
- Records the pattern: six governance commits, zero engineering deliverables, one factually-wrong correction, before D1.
- Establishes that the next candidate to use this intuition must be a fresh selection memo and fresh pre-registration with full data verification *before* commit, not a continuation of this stack.

## 6. Process accounting

Five Sleeve B candidates have now been killed:

| # | Candidate | Kill mode |
|---|---|---|
| 1 | xs-momentum | Stage B D4 drawdown gate failure |
| 2 | quality factor | Q0 §1 PIT data unavailable |
| 3 | random-pair stat-arb | Q0 §3.5 universe instability |
| 4 | vol-scaled momentum | Stage B D4 sub-Sharpe (`5619d09`) |
| 5 | system-stabilizer regime detection | Pre-D1 governance-stack contamination (this commit) |

Candidate #5 is the first kill in the program **not driven by signal evidence**. The prior four were killed because their signals or data did not meet pre-registered thresholds — that is the framework working as designed. Candidate #5 is killed because the governance stack around the candidate accumulated too many corrections to remain credible before any signal was computed.

This is a different class of kill and should be read differently. The intuition was not falsified; the candidate was not allowed to falsify it because the drafting process produced contradictory specifications. That's a process failure, not a market finding.

## 7. What can be carried forward

To a future candidate that uses the same originating intuition:

- **Verified data fact:** Binance public archive at `https://data.binance.vision/data/futures/um/daily/metrics/{symbol}/{symbol}-metrics-{YYYY-MM-DD}.zip` provides per-asset 5-minute open interest data (288 rows per day) with columns `create_time, symbol, sum_open_interest, sum_open_interest_value, count_toptrader_long_short_ratio, sum_toptrader_long_short_ratio, count_long_short_ratio, sum_taker_long_short_vol_ratio`. Historical depth covers the 2023-04-15 → 2026-04-15 OOS window for major Binance USDⓈ-M perpetual contracts.

- **Verified data fact:** Binance funding-rate cadence is heterogeneous (8h default, 4h for selected ≤25x leverage contracts since 2023-10-12, 1h/2h/4h/8h algorithmically configurable). `data/ingestion/vendors/binance/funding_fetcher.py` (`8e60933`) handles native cadences correctly.

- **Verified data fact:** Binance 1d klines for spot and perp are cached at `artifacts/cache/binance_klines_1d/` and fetchable via `BinanceKlinesArchiveFetcher` from `2af9981` onward.

- **Host strategy still available:** Candidate #4's audit log at `ef788b7` has 157 weekly rebalance rows over the OOS window. Any future regime-filter candidate can use this as the apples-to-apples host without re-running candidate #4's backtest.

- **Framework binding:** Q0 §3.6 (`b315d1e`) applies. Any future pre-registration must include the data-granularity audit table before commit. For OI specifically, the audit row must reflect the verified 5-minute granularity, not the daily granularity claimed (incorrectly) in Amendment #2.

A future candidate using this intuition is not pre-committed; the operator may or may not draft one. If one is drafted, it is a fresh selection memo and a fresh pre-registration, not a continuation.

## 8. Lessons (binding observations, not framework promotions)

These are observations to carry into future operator behavior. None of them is promoted to a permanent framework rule via this kill action; framework promotions belong to deliberate framework-evolution sessions, not to kill actions.

**8.1** A web search reading a single source can be wrong even when it seems specific. Ground truth via direct inspection (curl + unzip) is cheap. For any data dependency, inspect at least one real file before specifying behavior that depends on its shape.

**8.2** Pre-evidence amendments are governance-corrosive even when individually defensible. Two amendments to one pre-registration is uncomfortable; three indicates the pre-registration was not ready to be committed. The framework's anti-cherry-pick discipline rests on pre-registrations being stable; chained corrections weaken that even when no evidence has been seen.

**8.3** The pattern "audit reveals errors → consolidate into amendment → amendment itself contains a factual error" is the failure mode this kill action is responding to. It is not preventable by writing better amendments. It is preventable by drafting pre-registrations against verified data shapes from the start.

**8.4** Killing a candidate over governance contamination is uncomfortable but cheaper than continuing. The cost of this kill action is one document plus the loss of work already invested in candidate #5's stack. The cost of continuing would have been Amendment #3, then D1 against a half-verified data shape, then likely Amendment #4 if D1 surfaced more issues, then engineering effort under an increasingly fragile spec.

## 9. State at kill

```
HEAD: 433523f (Amendment #2)
This commit lands as: kill action at HEAD+1
Origin: 433523f (after this commit, will be HEAD+1)

Candidate #5 governance stack (preserved as historical record):
  cbd2633  Selection memo
  fe34b76  Pre-registration
  8492309  Amendment #1
  b315d1e  Framework evolution Q0 §3.6
  433523f  Amendment #2 (contains the factual error described in §2)
  THIS     Kill action

Engineering deliverables: none
Capital impact: none
Cumulative Sleeve B kills: 5
First non-signal-evidence kill in the program
```

## 10. References

- Pre-registration shelved: `fe34b76`
- Amendment #1: `8492309`
- Amendment #2 (contains factual error per §2 above): `433523f`
- Q0 §3.6 framework evolution: `b315d1e`
- Selection memo: `cbd2633`
- Q0 base: `cb9d975`
- Q0 cluster-diversity: `3ec7a32`
- Stage A gate inheritance: `39970f1`
- Framework review (May 2026): `7c10ca0`
- Master Sleeve B pre-registration: `fe909bb`
- Candidate #4 audit log (would-have-been host strategy): `ef788b7`
- Universe fixture: `2af9981`
- Binance OI archive (data inspected 2026-05-22 to produce ground truth): `https://data.binance.vision/data/futures/um/daily/metrics/`

---

*Candidate #5 shelved at pre-D1 governance/data-specification stage. No engineering commenced. Originating intuition preserved as valid market observation but not implemented under this pre-registration. Future candidates using the same intuition require fresh selection memo and fresh pre-registration with verified data shapes from first draft. Q0 §3.6 binding for any such future candidate. Sleeve B cumulative kill count: 5. First non-signal-evidence kill in the program.*
