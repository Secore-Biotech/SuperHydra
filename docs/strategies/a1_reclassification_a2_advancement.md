# A1 reclassification and A2 advancement

Strategic decision memo. Day 20 arc closure, Sleeve A re-prioritization.

**The decision to advance A2 is not a rejection of A1's infrastructure
investment; it is a prioritization decision based on observed edge
frequency under current evidence.**

---

## Status classification

```
A1 (funding-rate capture):
  infrastructure mature
  economic hypothesis unvalidated
  remains runnable as monitoring/research layer
  not promoted to paper gate

A2 (perp-vs-spot basis):
  promoted to next implementation candidate
```

---

## 1. Evidence summary

### Six SOL windows tested under research profile, zero fires

| Window | Mean | Max realized | Rolling-12 forecast peak | Threshold | Fires |
| --- | --- | --- | --- | --- | --- |
| Mar 1-15 2024 | ~6 bps | ~10+ bps | **7.69 bps** | 7.7 | 0 (near-miss) |
| Sep 1-15 2021 | 3.88 bps | 12.15 bps | 4.24 bps | 7.7 | 0 |
| Feb 15-29 2024 | 3.32 bps | 8.90 bps | 3.44 bps | 7.7 | 0 |
| Mar 16-30 2024 | 2.37 bps | 5.24 bps | 2.61 bps | 7.7 | 0 |
| May 1-15 2024 | 0.51 bps | 1.00 bps | 0.46 bps | 7.7 | 0 |

Five SOL 14-day windows under the research profile threshold (7.7 bps),
plus the underlying Day 20.4 fixture (Mar 1-15 2024) which itself returned
zero. Six windows of real funding data, zero intents fired across all
of them. The synthetic-fixture test at sustained 10 bps fires as
expected; real data does not approach that bar.

### BTC/ETH structural no-trade (Day 17c)

BTCUSDT funding rate cap is 1 bp per interval; threshold under any A1
profile is ≥ 7.7 bps. Cap-bound, structurally untradeable. ETH inherits
the same characteristic. **BTC/ETH cannot fire A1 under any cost
profile.** This is not a calibration issue; it is a venue constraint.

### The structural finding (Day 20.6)

Sep 2021 SOL — the strongest historical SOL high-funding regime widely
cited as a SOL mania period — had individual events reaching 12.15 bps
but a rolling-12 forecast peak of only 4.24 bps. The forecast formula
`mean(12) - 1.0 × stdev(12)` is more selective than the funding regime
itself. High mean is suppressed by the stdev penalty when funding is
volatile, and SOL high-funding regimes are characterized precisely by
that volatility.

**The forecast formulation, not the threshold value, is what makes A1
unlikely to fire.** This is structural to A1's edge-quantification
approach, not a tuning question. Lowering the threshold to manufacture
fires would invalidate the evidence chain; this is forbidden by
roadmap discipline.

### Three independent corroborating findings

- **Day 18b**: rolling-12 mean structural test predicted Mar 2024 would
  not clear by construction
- **Day 19a**: Kaiko + Amberdata independent slippage calibration
  confirms 1 bp/leg
- **Day 19c.3**: Roll's effective-spread on tape confirms market-wide
  spread is 0.15-0.19 bps/leg

Triangulated: infrastructure correct, cost model honest, signal
forecast selective by design, SOL regimes structurally below the bar.

---

## 2. Decision

### A1 reclassification: research-positive / strategy-unproven

A1 funding-rate capture **remains in the research phase**. It does not
advance to paper-trading gate as the primary Sleeve A engine.

- **Infrastructure investment is sound and complete.** Day 20.1-20.6
  produced production-grade evidence pipeline.
- **Strategy hypothesis is not falsified, but is not validated either.**
  A1 might fire on instruments not yet calibrated, or in regimes not
  yet sampled, but the burden of proof has shifted: extraordinary
  fixture-hunting effort would be needed to find positive evidence,
  and that effort is not justified speculatively.
- **A1 stays operational as a monitoring layer.** The runner and
  harness continue to be runnable; if a future operator notices a
  sustained high-funding regime in real time, they can sweep it with
  a fresh fixture in minutes.

### A2 basis: next Sleeve A implementation candidate

Per the roadmap, Sleeve A consists of A1 (funding-rate capture), A2
(perp-vs-spot basis), and A3 (cash-and-carry). A1 was first because
it is mechanically simplest. **A2 moves up the priority order** for
these reasons:

1. **Basis is more persistent than funding.** Perp-vs-spot basis tends
   to be a stable risk-premium, less spiky than funding rates. The
   "12-interval sustained edge" problem that Day 20 surfaced is
   funding-specific.
2. **A2 reuses ~80% of A1's infrastructure.** OMS, risk layer, cost
   model, paper.fills writer, replay observation, harness — all carry
   forward. The economic logic differs; the operational substrate
   does not.
3. **A2 is the natural diversification path.** Even if A1 eventually
   fires in some regime, A2 provides return stream independence.

### What this is NOT

- **Not abandoning A1.** The code, evidence, and infrastructure stay.
  A1 remains in the strategy registry as a research-phase entity.
- **Not promoting A1.** No paper-gate advancement. No canary plan.
- **Not changing the threshold.** Calibration tampering remains
  forbidden. Lowering the threshold to manufacture fires would
  invalidate the entire evidence chain.
- **Not continuing fixture hunting.** Day 20.5C tape replay stays
  deferred indefinitely.

---

## 3. Carry-forward assets

Everything built in the Day 17-20 arc remains useful and is consumed
by future work:

| Asset | Consumer |
| --- | --- |
| `data/ingestion/vendors/binance/funding_fetcher.py` | A2 needs current basis + funding (basis often funding-derived) |
| `data/ingestion/vendors/binance/trade_fetcher.py` + `BinanceArchiveTradeFetcher` | A2 needs trade data for spot+perp price observation |
| `core/config/cost_model.py` framework | A2 inherits the same cost-model schema; new profiles for basis-trade slippage |
| `strategies/a1_funding/config/profile_selector.py` pattern | A2 gets its own selector with the same firewall discipline |
| `paper.fills` schema + writer (Day 20.1) | A2 writes its evidence to the same table |
| `compute_slippage_calibration()` aggregator (Day 20.2) | A2 generates the same per-instrument slippage stats |
| Replay observation machinery (Day 20.3a) | A2 observation pattern is the same: intent → fetch trades → compute slippage |
| `A1PaperResearchRunner` composition pattern (Day 20.4) | A2 gets an equivalent runner, same composition shape |
| Operator harness pattern (Day 20.5) | A2 gets its own harness via the same template |
| Funding fixture corpus (5 SOL windows + 1 BTC) | A2 may not need funding fixtures, but the refresh script generalizes |

**Estimated A2 infrastructure cost: ~30% of A1's**, because most of
the substrate transfers. The economic content is new; the plumbing
is shared.

The infrastructure investment in A1 is therefore not stranded. It
becomes the foundation A2 builds on, and remains operational for A1
itself if future evidence warrants reconsidering.

---

## 4. Day 21 — A2 basis engine design brief

This is the next session's opener, not this session's work. The
questions A2 needs to answer in scope-locking:

### A2.1 Economic mechanic

A2 captures the **perp-vs-spot basis**: when perp trades above spot,
short the perp and long the spot (and vice versa), collect the
convergence. Distinct from A1's funding capture (which is also
implicitly basis-related) — A2 trades the *price spread*, A1 trades
the *funding rate*.

### A2.2 Open questions for Day 21 scoping

| # | Question |
| --- | --- |
| 21.1 | **Signal source**: realized basis (last N minutes), or implied basis from funding-rate term-structure, or both? |
| 21.2 | **Threshold formulation**: same `mean - k*stdev` shape, or different (e.g. z-score, percentile-based)? Likely different given basis dynamics. |
| 21.3 | **Instrument scope**: SOL only (matching A1 calibration), or BTC/ETH (where A1 was structurally locked out but basis may be tradable)? |
| 21.4 | **Capital co-deployment with A1**: do A1 and A2 share account and instrument, or run separately? If shared, accounting/position semantics need attention. |
| 21.5 | **First milestone**: what does "A2 canary" mean operationally? A2 is two-legged (perp + spot), so it touches venues differently than A1's single-leg-on-Binance pattern. |

### A2.3 Estimated commit shape for Day 21+

- **Day 21**: design brief mirroring this memo's format. Reviewer locks
  A2.1-A2.5. **No code.**
- **Day 22+**: mirror the Day 20 sub-arc shape — signal evaluator →
  cost model → runner → harness → sweep. Estimated 4-6 commits.

---

## 5. Cross-references

- Day 17b memo: A1 cost-profile selector
- Day 17c memo: BTCUSDT structural no-trade finding
- Day 18b memo: rolling-12 forecast structural test
- Day 19a memo: SOL slippage calibration (Kaiko + Amberdata)
- Day 19c.3 memo: Roll's effective-spread estimation
- Day 20.1 commit (`9193b65`): `paper.fills` writer
- Day 20.2 commit (`b2b17bc`): slippage calibration aggregator
- Day 20.3a commit (`d9fd108`): replay observation machinery
- Day 20.4 commit (`fd9bea7`): A1 PAPER_RESEARCH runner + Mar 2024 finding
- Day 20.5 commit (`08cd109`): operator CLI harness
- Day 20.5B commit (`0ab72c3`): May 2024 low-carry finding
- Day 20.6 commit (`87d121e`): three-fixture sweep + threshold formulation finding

---

## 6. Reviewer-locked status

| Item | Status |
| --- | --- |
| A1 phase classification | research / strategy-unproven (no paper gate advancement) |
| A1 runtime status | runnable for monitoring; harness available |
| A1 calibration discipline | preserved (no threshold tampering) |
| A2 sequence position | next Sleeve A implementation candidate |
| A2 first artifact | Day 21 design brief (no code) |
| Day 20.5C tape replay | deferred indefinitely |
| Sleeve B research track | continues independently per roadmap |
| Tier 2 (microstructure, regime) overlays | deferred per roadmap until A1 or A2 reaches paper |
| Sleeve A as a whole | preserved; A1 + A2 + A3 structure unchanged |

The Day 20 arc closes here as a successful infrastructure delivery
with honest negative empirical evidence. Day 21 opens with the A2
design brief.
