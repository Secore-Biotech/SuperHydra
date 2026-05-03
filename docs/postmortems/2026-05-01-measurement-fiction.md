# Postmortem: Measurement Fiction Discovery

**Date:** 2026-05-01  
**Severity:** Critical — capital allocation framework was consuming fictional data  
**Author:** Wasseem  

---

## What was believed

At the start of the May 1 audit session, HYDRA's internal reporting showed:

| Strategy | Cumulative PnL | Sharpe | Status |
|----------|---------------|--------|--------|
| MM (Market Maker) | +$40.59 | +19.98 | "Closest to passing gate — 12 days away" |
| L1 Funding Arb | +$1.25 | +11.50 | Active, steady |
| L4 Directional ML | — | — | V4 ensemble evaluation in progress |

The capitalization gate framework (`gate_status.py`) identified MM as the strategy closest to qualifying for additional capital deployment. The gate required 30 days of track record, Sharpe > 1.0, drawdown < 10%, and 90-day PnL > $27 (to cover $324/90d infrastructure cost). MM appeared to be 12 days from clearing these thresholds.

The portfolio was understood to be running multiple independent strategies generating alpha across different market microstructures — market-making, funding rate arbitrage, directional ML, and macro signal routing.

---

## What was actually true

### MM realized cash: $3.63

Only **10 completed buy→sell roundtrips** ever occurred, all between 2026-04-26 16:44 and 2026-04-28 08:23 — a 40-hour window. Every trade was $3.00 size. Total realized PnL: **$3.6328**.

The 10 fills:

| Time | Market | Buy | Sell | PnL |
|------|--------|-----|------|-----|
| Apr 26 16:44 | cricpsl-isl-mul | 0.370 | 0.400 | $0.2250 |
| Apr 26 16:44 | cricpsl-isl-mul | 0.410 | 0.440 | $0.2045 |
| Apr 26 16:46 | cricpsl-isl-mul | 0.440 | 0.470 | $0.1915 |
| Apr 26 16:47 | cricpsl-isl-mul | 0.430 | 0.460 | $0.1957 |
| Apr 26 23:52 | mex-san-mon1 | 0.130 | 0.170 | $0.7059 |
| Apr 26 23:52 | mex-san-mon1 | 0.140 | 0.170 | $0.5294 |
| Apr 27 09:06 | will-west-ham-be-relegated | 0.360 | 0.390 | $0.2308 |
| Apr 27 12:40 | cs2-big5-nemi1 | 0.160 | 0.200 | $0.6000 |
| Apr 27 20:50 | lal-esp-lev-2026-04-27 | 0.130 | 0.160 | $0.5625 |
| Apr 28 08:23 | lol-foxy-drxc-2026-04-28 | 0.450 | 0.480 | $0.1875 |

### MM open inventory: $48–51 in unmatched longs

17 unmatched LONG YES positions remain on-chain in low-probability outcomes: esports (CS2, LoL), football (West Ham relegation, La Liga), NHL, BJP election markets. Median entry price $0.18. These are not hedged.

**BUY:SELL ratio: 4.2:1.** The strategy is not market-neutral. It is a longshot accumulator — buying YES on low-probability events and occasionally selling when the spread narrows, but predominantly accumulating inventory.

**Mark-to-market range on inventory:** $0 (all positions expire worthless) to $100+ (some low-probability events resolve YES). The true value is unresolvable without on-chain position queries to each Polymarket market.

### L4 V4 ensemble: broken

The V4 ensemble evaluation was running with `USE_V4_ENSEMBLE: false` in `hydra_flags.json` and `PAUSE_L4_ENTRIES: true`. The ensemble trainer (`ensemble_trainer_v2.py`) used a single 60-day train/test split, not a rolling window. The retrain timer (`hydra-retrain.timer`) was inactive/dead. L4's live trading record: 488 live positions with PnL of **-$18.10**.

### L1 Funding Arb: noise scale

165 funding events from 2026-03-23 to 2026-05-01. Total PnL of live events: **$1.25**. Total including dry_run: $1.75. At this scale, Sharpe of +11.50 is a statistical artifact of tiny, correlated funding payments — not a signal of strategy quality.

---

## Root cause analysis

### Primary bug: mm_roundtrips contains placed orders, not confirmed fills

The `mm_roundtrips` table (272 rows) recorded every instance where the MM identified a spread opportunity and placed orders. The schema:

```sql
CREATE TABLE mm_roundtrips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    market_slug TEXT,
    buy_price REAL,
    sell_price REAL,
    spread_captured REAL,  -- fractional spread width (e.g. 0.03), NOT dollars
    size_usd REAL,
    label TEXT DEFAULT 'MARKET_MAKE'
);
```

`spread_captured` stores the spread width between posted buy and sell prices (e.g., 0.03 = 3 cents). There is **no status column** distinguishing placed from filled. There is no fill confirmation, no order ID linking to exchange records, no settlement timestamp.

`portfolio_sharpe.py` computed MM PnL as:
```
SUM(spread_captured × size_usd) = SUM(0.03..0.04 × $5.00) = $40.59
```

This treats every posted spread opportunity as a confirmed, settled roundtrip. The actual fills (10) represent 3.7% of the recorded opportunities (272). The overstatement factor: **11.2×**.

### Secondary bug: gate_status.py inherited the same data source

`gate_status.py` read from the same computation, producing a fictional Sharpe and a fictional "12 days to gate" estimate.

### Why it wasn't caught

1. **No placed-vs-filled typing.** The `mm_roundtrips` table had no status column. A row existing was implicitly treated as a confirmed trade.
2. **Silent empty-table handling.** When data was missing or tables were empty, aggregation queries returned misleading numbers (e.g., zero-row SUMs producing $0.00 instead of raising "no data" errors).
3. **No realized-vs-unrealized typing on PnL outputs.** Every number produced by the reporting pipeline was presented as a single dollar figure with no tag indicating whether it was realized cash, unrealized mark-to-market, or hypothetical.
4. **No manual cross-check.** At no point was any strategy's reported PnL compared against exchange or venue settlement records.

---

## Timeline of the bug

| Date | Event |
|------|-------|
| **2026-04-05** | `mm_trades` table begins recording (first dry_run entries) |
| **2026-04-09 12:43** | First `mm_roundtrips` row inserted (id=1, eth-updown-15m). This is when the fictional PnL counter starts |
| **2026-04-26 08:20** | First `market_maker.log` entry (MM_SKIP_TOO_FAR messages) |
| **2026-04-26 16:44** | First actual `SPREAD_CAPTURED` log event — first real fill |
| **2026-04-28 08:23** | Last `SPREAD_CAPTURED` event (10th and final confirmed roundtrip) |
| **2026-04-28 08:23** | Last `mm_roundtrips` row (id=272). MM effectively stops trading |
| **2026-04-28 → present** | MM runs but logs only `MM_SKIP_BALANCE` — $0.05 available, needs $9.00 per trade. All capital locked in unmatched inventory |
| **~2026-04-28** | `portfolio_sharpe.py` reports MM Sharpe of +19.98 and PnL of +$40.59, computed from 272 hypothetical roundtrips |
| **~2026-04-30** | `gate_status.py` reports MM as "closest to passing, 12 days away" |
| **2026-05-01** | Audit discovers the discrepancy. Bug fixed in both scripts to parse `SPREAD_CAPTURED` log lines only |

**Duration of fictional reporting: ~22 days** (Apr 9 first roundtrip row → May 1 discovery). The +19.98 Sharpe number was being reported for approximately the last 3 days of that window (after enough data accumulated for the Sharpe calculation to look impressive).

---

## Other strategies at risk of same bug class

### L1 Funding Arb
- **PnL source:** `funding_events` table in `/root/hydra/data/hydra.db`, column `funding_amt`
- **Placed vs filled?** Table has `dry_run` column (1=paper, 0=live). Live events (dry_run=0) represent actual Binance funding payments received.
- **Cross-checked against exchange?** No. Funding payments should be verifiable via Binance funding history API.
- **Risk: MEDIUM.** The dry_run column provides some protection, but the $1.25 PnL has never been verified against Binance records. The Sharpe of +11.50 is a statistical artifact at this noise scale regardless.

### L2 Contrarian Momentum
- **PnL source:** Unknown — service is active but no dedicated positions table found in audit.
- **Cross-checked?** No.
- **Risk: HIGH.** Active service with no visible audit trail for PnL computation.

### L4 Directional ML (V3/V4)
- **PnL source:** `positions` table in `/root/hydra/data/layer4.db`. 513 rows, 488 live (dry_run=0).
- **Placed vs filled?** Table tracks positions with entry/exit prices. Live positions show realized PnL of **-$18.10**.
- **Cross-checked?** No. Binance trade history not compared.
- **Risk: MEDIUM.** The negative PnL suggests the numbers are at least directionally honest (a fictional system would more likely show gains), but the entry/exit prices have not been verified against fills.

### L9 EBTC (BYC Signal)
- **PnL source:** PAPER_MODE=True. No live trades. Paper signals logged.
- **Cross-checked?** N/A — paper only.
- **Risk: LOW** for capital loss (no live trading). **MEDIUM** for signal quality measurement (paper PnL could suffer same hypothetical-vs-real confusion if/when it goes live).

### PM Bot (Polymarket BTC Bot)
- **PnL source:** `trades` table in `/root/trades.db`. 346 rows, mostly BUNDLE_ARB (FIFA) and short-timeframe crypto plays.
- **Cross-checked?** No. On-chain Polymarket positions not reconciled.
- **Risk: HIGH.** Same venue (Polymarket) as MM, same lack of on-chain verification. Bundle arb outcomes show 0 wins/losses (still pending resolution) — PnL could be entirely unrealized.

### L3 Stat Arb
- **Status:** DECOMMISSIONED 2026-04-30. Service stopped and disabled.
- **Risk: N/A** (dead). But for the record: L3 had orphaned positions that required manual closure on May 1 (6 pairs). Its PnL was never verified.

### L10–L19 (Paper strategies)
- **Status:** Services inactive/dead. Layer 14 (Multi-Coin Funding Arb) has code but PAPER_MODE=True.
- **Risk: LOW** (no capital deployed). Same architectural risk if any were promoted to live.

### Summary

| Strategy | PnL Source | Verified? | Risk |
|----------|-----------|-----------|------|
| MM | mm_roundtrips (BROKEN — now fixed to log parse) | Partially (log vs DB) | **FIXED** |
| L1 Funding | funding_events table | No | MEDIUM |
| L2 Momentum | Unknown | No | **HIGH** |
| L4 ML | layer4.db positions | No | MEDIUM |
| L9 EBTC | Paper only | N/A | LOW |
| PM Bot | trades.db | No | **HIGH** |
| L3 Stat Arb | Decommissioned | N/A | N/A |
| L10-L19 | Paper only | N/A | LOW |

---

## What was nearly lost

The capitalization gate framework was converging on a recommendation to deploy additional capital to MM. The decision path:

1. `gate_status.py` reported MM Sharpe of +19.98, PnL of +$40.59, on track to clear the 30-day threshold
2. MM was flagged as "closest to passing — 12 days away"
3. The gate's PnL threshold is $27/90d (covering $324 infrastructure cost). The fictional $40.59 already exceeded this
4. The remaining blocker was track record duration (30 days required, ~19 days recorded)
5. At day 30 (~May 9), the gate would have recommended deploying the **minimum capital threshold of $50** to MM

**Dollar amount at risk: $50 minimum deployment**, drawn from the $800 total capital pool (6.25% of total capital).

This $50 would have been deployed into a strategy that:
- Had a real Sharpe of approximately **0.5** (not 19.98) — below the 1.0 gate threshold if correctly measured
- Was not market-neutral but an **unhedged longshot accumulator** with 4.2:1 buy:sell ratio
- Had **$48–51 already locked** in illiquid, low-probability positions with no exit path
- Had been out of trading capital since April 28 (balance: $0.05)

The $50 deployment would have immediately been consumed by the same accumulation pattern — buying YES on low-probability outcomes — with no mechanism to capture spreads (since the strategy cannot maintain two-sided quotes with sufficient capital for only one side).

Beyond the direct $50 at risk: a "successful" gate passage for MM would have validated the measurement framework itself, making it the template for promoting other strategies. Every subsequent capital allocation decision would have been built on the same fictional foundation.

---

## Lessons (non-negotiable for SuperHydra)

### 1. Every PnL number must be tagged REALIZED, UNREALIZED, or MIXED with breakdown
No function, report, alert, or dashboard may emit a dollar figure without an explicit `pnl_type` tag. Mixed figures must include the realized and unrealized components separately. This is a type system constraint, not a style preference.

### 2. Empty data sources produce explicit errors, never silent zeros or misleading aggregates
`SUM()` over zero rows returns 0.0, which looks like "no profit" rather than "no data." Every aggregation must check row count first and raise `NoDataError` if the source is empty or below a minimum sample size.

### 3. Every measurement source must be manually cross-checked against ground truth before being trusted
Before any strategy's PnL enters a gate calculation, its reported numbers must be compared — at least once — against the exchange or venue's own records (Binance trade history, Polymarket on-chain positions, etc.). This cross-check must be documented with a timestamp.

### 4. Same code path runs in research, paper, and live — no bifurcation
The mm_roundtrips table existed because the recording path diverged from the execution path. One path logged "I identified a spread" (272 times), another path logged "I completed a fill" (10 times). A single code path — from signal through execution through settlement — eliminates this class of divergence.

### 5. Strategies are named accurately for what they do, not what they were intended to do
The MM was called a "market maker" but operated as a longshot accumulator. The name shaped expectations (delta-neutral, high-frequency, tight spreads) that concealed the actual risk profile (directional, infrequent, wide spreads on illiquid markets). Name the strategy for observed behavior.

### 6. Postmortems are written when bugs are found, not when bugs become catastrophic
This bug existed for 22 days. It was discovered during a routine audit, not because it caused a loss. The postmortem exists because the bug was found, not because it caused damage. This standard must hold: every measurement bug gets a postmortem, regardless of whether capital was lost.

---

## Action items carried forward to SuperHydra

### A1: Canonical Ledger
Implement a single `ledger` table as the source of truth for all PnL:
- Every row represents a confirmed, settled transaction
- Required fields: `strategy_id`, `venue`, `instrument`, `side`, `fill_price`, `fill_size`, `fill_ts`, `settlement_ts`, `venue_order_id`, `pnl_type` (REALIZED | UNREALIZED), `pnl_usd`
- No strategy may report PnL from any other source

### A2: Source Typing
All data tables must declare their semantic type in a schema registry:
- `SIGNAL` — a strategy identified an opportunity
- `ORDER` — an order was placed
- `FILL` — an order was confirmed filled
- `SETTLEMENT` — a position was closed and PnL realized
Code that computes PnL must assert it is reading from `FILL` or `SETTLEMENT` sources only.

### A3: Audit Trail / Cross-Check Registry
Maintain a `verification_log` table:
- `strategy_id`, `verified_date`, `source` (internal DB), `ground_truth` (exchange API), `match` (bool), `discrepancy_usd`, `verified_by`
- Gate calculations must check that `verified_date` is within 7 days

### A4: NoDataError Convention
All aggregation functions must raise `NoDataError` (not return 0.0) when:
- Source table has 0 rows
- Source table has fewer rows than `min_sample_size` parameter
- All rows are `dry_run=1` when computing live PnL

### A5: PnL Type System
Enforce at the function signature level:
```python
class RealizedPnL(NamedTuple):
    usd: float
    trade_count: int
    source: str  # must be FILL or SETTLEMENT table

class UnrealizedPnL(NamedTuple):
    usd: float
    position_count: int
    mark_source: str  # must be live price feed
    mark_ts: datetime

class MixedPnL(NamedTuple):
    realized: RealizedPnL
    unrealized: UnrealizedPnL
```
No function may return a bare `float` as PnL.

### A6: Strategy Behavioral Audit
Before any strategy passes a gate:
- Compute actual buy:sell ratio, average hold time, and inventory turnover
- Compare against the strategy's declared profile (market-neutral, directional, arb, etc.)
- Flag mismatches as gate blockers

### A7: Kill Switch on Measurement Failure
If any strategy's PnL computation raises `NoDataError` or fails cross-check verification, the gate framework must:
- Set the strategy to `BLOCKED` status
- Emit an alert
- Refuse to process any capital allocation until the measurement issue is resolved

---

## Signoff

**Date:** 2026-05-01  
**Author:** Wasseem  

**Lesson in one sentence:** A PnL number computed from placed orders instead of confirmed fills is not a measurement error — it is a fiction, and a system that trusts it will allocate real capital to imaginary alpha.

---

## Addendum: Discovered during freeze planning — L9 configuration drift

*Added 2026-05-01 22:10 UTC during Prompt D (freeze plan execution)*

### What was believed

L9 BYC EBTC was understood to be running in paper mode (`PAPER_MODE = True`). The memory record from 2026-04-16 stated: "PAPER_MODE = True — execute_long/execute_close log L9_LIVE_SKIP and return early." The freeze plan initially listed L9 as "keep running in paper mode through 2026-05-15."

The 0.001 BTC long position on the Binance account was understood to predate L9 — placed manually, not strategy-managed.

### What was actually true

`PAPER_MODE = False` (line 65 of `layer9_ebtc.py`). L9 has been executing **live trades** since 2026-04-16 07:19 UTC — within 5 minutes of its first `PAPER_MODE=True` test run.

**Full L9 live trading history (from Binance income records):**

| Date | Action | Price | Realized PnL |
|------|--------|-------|-------------|
| Apr 16 07:14 | First startup (PAPER_MODE=True) | — | — |
| Apr 16 07:19 | **PAPER_MODE flipped to False** | — | — |
| Apr 17 00:34–08:58 | 5× L9_LIVE_FAIL (Binance 451 geoblock from SG) | — | — |
| Apr 19 04:00 | Pre-existing position closed (stop-loss) | ~$75,500 | +$1.34 |
| Apr 19 04:33 | **L9 first live entry** | $75,547.40 | — |
| Apr 22 06:45 | Stop-loss triggered, immediate re-entry | ~$77,900 / $77,921.30 | +$2.37 |
| Apr 24 00:47 | Stop-loss triggered, immediate re-entry | ~$78,400 / $78,410.00 | +$0.77 |
| **May 1 22:06** | **Position closed (freeze plan)** | $78,221.90 | -$0.19 |

**Total realized: +$4.12 net** (including pre-existing position) or **+$2.86 net** (L9 trades only).

**Critical detail:** All position closes prior to the freeze were stop-losses triggered by Binance, not L9's `execute_close()` function. BYC never dropped below 0.4 (the RISK_OFF threshold). L9's close logic was never tested in production.

**Missing stop-loss:** At the time of freeze closure, no active stop-loss order was visible for the open position (orderId 3000001334344117 from Apr 24 was not in `fetch_open_orders`). The position was running without downside protection for an unknown duration.

### Root cause

**This is configuration drift, not measurement fiction.** The numbers L9 reported were real — its trades actually filled, the PnL is confirmed against Binance income records, and the position sizes match. The bug is different:

1. **PAPER_MODE was flipped live within 5 minutes of first test**, with no validation period, no documented decision, and no alert to any monitoring system.
2. **The memory record from Apr 16 was correct at 07:14 but stale by 07:19** — a 5-minute window made the documentation wrong for the next 15 days.
3. **No mechanism distinguished "currently paper" from "currently live"** at the system level. The flag was a local variable in a Python file, not a centralized registry.
4. **Stop-loss orders could silently disappear** (cancelled during service restarts, API timeouts, or geoblock events) with no monitoring or alerting.

### Why it matters

The L9 drift is less dangerous than the MM measurement fiction ($2.86 real PnL vs $2.86 reported — the numbers happened to be correct) but more insidious:

- A strategy silently operating in live mode means **capital is at risk without the operator knowing**
- The freeze plan almost left L9 running "in paper mode" — it would have continued executing live BTC futures trades while the operator believed the system was frozen
- If BTC had dropped 20% during the "paper" freeze window, L9 would have held through (no close logic triggered, possibly no stop-loss active) — a ~$15 unplanned loss on a system believed to be dormant

### Lessons — configuration audit (third category)

In addition to measurement integrity and flag wiring, SuperHydra requires:

**7. PAPER_MODE / live status must be a centralized, auditable state — not a local variable**
- A strategy's execution mode (paper/live/frozen) must be stored in a single registry (e.g., `hydra_flags.json` or a database table)
- Changing execution mode must log the transition with timestamp, previous state, new state, and operator
- System-level dashboards must show execution mode for every strategy in a single view

**8. Stop-loss orders must be monitored independently of the strategy that placed them**
- A background watchdog must periodically verify that every live position has an active stop-loss on the exchange
- Missing stop-loss → immediate Telegram alert + automatic re-placement or position close

**9. Documentation of live state must be machine-generated, not human-written**
- Memory records, README files, and postmortems that state "PAPER_MODE = True" must be generated from the actual current value, not from what a human wrote 15 days ago
- If a state claim in documentation diverges from runtime state, the documentation is wrong, not the code

### Action item added to SuperHydra

**A8: Execution Mode Registry**
```python
# In SuperHydra's central config:
STRATEGY_MODES = {
    "L1": {"mode": "LIVE", "changed_at": "2026-05-01T11:02:37Z", "changed_by": "systemd"},
    "L9": {"mode": "FROZEN", "changed_at": "2026-05-01T22:06:00Z", "changed_by": "freeze_plan"},
    # ...
}
# Transitions require: log entry, Telegram alert, 60s delay before first live order
```

**A9: Stop-Loss Watchdog**
- Runs every 5 minutes
- For each strategy with mode=LIVE: query exchange for open positions, verify matching stop-loss order exists
- Missing stop → alert + auto-place stop at strategy's configured LIVE_STOP_PCT

---

**Signoff (addendum):** Wasseem, 2026-05-01. Configuration drift is silent capital risk — a system that thinks it's paper-trading while placing real orders is more dangerous than one with wrong PnL numbers, because wrong PnL at least gets caught when someone checks the balance.

---

## Addendum: full MM attribution

*Added 2026-05-02 during attribution analysis (commit b5071db)*

The original postmortem audited only the MM spread book: 10 completed buy→sell roundtrips capturing $3.63 in realized spreads. This was the correct accounting for what `portfolio_sharpe.py` claimed to measure — but it was a tiny subset of MM's actual activity.

The full attribution analysis (see `/root/hydra/docs/postmortems/2026-05-01-polymarket-attribution.md`) found:

| Metric | Spread book (original audit) | Full MM activity |
|--------|------------------------------|------------------|
| Positions | 10 roundtrips | 315 positions |
| Cost basis | ~$30 (10 × $3 trades) | $2,187.99 |
| Resolved losses | $0 | $1,459.86 |
| Net PnL | +$3.63 | **-$691.62** |
| Share of wallet losses | 0.3% | 64% |

The strategy named "Market Maker" was operationally a **directional crypto-binary betting bot with a small spread-capture sidecar**. Over 20 days of live trading (Apr 8–28), it submitted 157,394 orders with a buy:sell ratio that never dropped below 3:1 on any single day. It accumulated one-sided long inventory across 315 markets — primarily 5-minute and 15-minute crypto Up/Down bets — and occasionally captured spreads when both sides filled (10 times out of 157,394 orders).

The original postmortem correctly identified the measurement bug (placed orders counted as fills) and the strategy-naming problem (accumulator called a market maker). What it missed was the scale: the $3.63 spread book was not the main story. The main story was $2,188 deployed into structurally losing bets, producing the wallet's single largest loss contributor at -$692.

### Lesson generalization

A strategy's name does not constrain what its code actually does. The name "Market Maker" created an expectation of delta-neutral, high-frequency spread capture. The code implemented directional accumulation of binary longshots. The name was never updated because no one reviewed the code's actual behavior after initial deployment.

**Architectural rule for SuperHydra:** Strategy code is reviewed quarterly to verify alignment between:
1. **Name** — what the strategy is called in dashboards and reports
2. **Claimed thesis** — the documented edge (e.g., "capture bid-ask spread on binary markets")
3. **Actual order patterns** — computed from the last 30 days of fill data (buy:sell ratio, average hold time, inventory turnover, market type distribution)

A mismatch between any two triggers a mandatory review and either a name change, a code fix, or a strategy shutdown. This review is automated: a weekly job computes order pattern metrics and flags deviations from the strategy's registered profile.

---

## Addendum: structural negative-EV finding

*Added 2026-05-02*

96% of HYDRA's lifetime Polymarket losses came from short-duration crypto binary bets — 5-minute and 15-minute Up/Down markets. The loss breakdown:

| Category | Losses | Share |
|----------|--------|-------|
| MM on crypto binaries | ~$590 | 55% |
| Unattributed crypto binaries (pre-bot) | ~$300 | 28% |
| PM:CRYPTO_ARB (NORMAL_LAG) | $47 | 4% |
| MM on crypto hourly/price | ~$100 | 9% |
| **Crypto binary subtotal** | **~$1,037** | **96%** |
| All other (sports, events, bundles) | ~$35 | 4% |

### Why these markets are structurally unwinnable at retail size

Polymarket's 5-minute and 15-minute crypto Up/Down markets are binary outcomes: BTC goes up or down over a fixed window. The theoretical probability is ~50/50 (slightly skewed by short-term momentum, but not enough to matter at these timescales).

The market microstructure destroys any edge:
- **Bid-ask spread:** 5–7% on typical Up/Down markets (e.g., YES bid $0.47, YES ask $0.53)
- **Polymarket fee:** ~2% round-trip
- **Total cost of entry+exit:** 7–9% per trade

For a 50/50 game with 7–9% round-trip cost, the break-even win rate is approximately **54–55%**. HYDRA's realized win rate on resolved crypto binary positions was **28%** — consistent with a participant paying the spread on the wrong side (buying the less-liquid outcome at the ask, which resolves to $0 more often than $1).

No measurement fix, no infrastructure improvement, no idempotency wrapper, no better signal processing changes the EV of an unwinnable game. The MM could have had perfect code, perfect accounting, perfect monitoring — and it would still have lost ~$700 on these markets because the game itself has negative expected value at retail size.

### The $210 lesson

The single largest loss in the portfolio was a $209.89 bet on "BTC Up" in a 5-minute window on March 18, placed before either bot was operational (from the unattributed pre-bot phase). This was likely a manual REPL trade — someone testing the Polymarket API by placing a large directional bet on a coin-flip market. It resolved to $0 in 5 minutes. This one trade accounts for 20% of all resolved losses.

### Architectural rule for SuperHydra

Every strategy's research-phase entry requires explicit computation of the underlying game's expected value at the intended position size, after spread, fees, and slippage:

```
EV = (win_probability × payout) - (loss_probability × cost) - fees - spread_cost

If EV < 0 at intended size: REJECT before any code is written.
If EV is positive but < 2× fees: FLAG as fragile edge, require 1000+ backtested samples.
If EV is positive and > 2× fees: PROCEED to paper trading.
```

This computation is a gate — not a guideline. It is checked by the strategy registration system before a strategy ID is issued. A strategy that cannot demonstrate positive EV in its research notebook does not get a strategy ID, does not get a wallet, does not get a database table, does not get a systemd service.

The BUNDLE_ARB strategy is the counterexample: it computes EV explicitly (sum of YES prices < $1.00 → guaranteed profit on resolution minus fees), and it is the only PM Bot strategy that is not obviously negative-EV. Whether its edge survives fees and execution costs is an open question, but at least the question is well-posed.

---

## Addendum: atomic order recording

*Added 2026-05-02*

Of the 559 Polymarket positions in the wallet, 81 (14%) have no corresponding entry in either local database (`trades.db` or `market_maker.db`). These unattributed positions cost $415.11 and lost $299.90.

### The three failure modes

**1. BUNDLE_ARB batch with silent DB write failure (~42 positions, ~$62 cost basis)**

On approximately 2026-04-09 21:25 UTC, the BUNDLE_ARB strategy placed ~42 orders buying $1–2 YES on every candidate in the 2028 Democratic Presidential Nomination market. The orders were submitted to Polymarket's CLOB and filled on-chain. The local `trades.db` write either failed silently (e.g., SQLite lock contention, disk full, unhandled exception in the DB commit path) or was never attempted (process crash between order submission and DB write).

The bot continued operating after this failure — subsequent BUNDLE_ARB batches on Apr 9 22:13 onward are recorded normally. This means the failure was transient and undetected. No alert fired. No reconciliation check caught the gap.

**2. Pre-bot manual/REPL trades (~24 positions, ~$310 cost basis)**

Before the PM Bot's `trades.db` was initialized (~Mar 26), someone placed ~$310 in trades from the wallet — including the $209.89 BTC 5-minute bet. These were likely placed via Python REPL or a one-off script during API testing. They bypassed all accounting because no accounting system existed yet.

**3. Miscellaneous unrecorded trades (~15 positions, ~$43 cost basis)**

Assorted positions that don't match any bot's pattern — novelty markets, pre-bot sports bets, one-off tests.

### Why this matters

The unattributed positions account for **$299.90 in losses** — 28% of the wallet's total. Without the attribution analysis, these losses were invisible: they didn't appear in any strategy's PnL, any dashboard, or any gate calculation. They were capital that evaporated with no trace in the accounting system.

The BUNDLE_ARB batch failure is the most dangerous variant because it happened during normal bot operation: the strategy was running, the orders were real, and the bot believed it had no open positions in the 2028 Dem Nomination market (because its DB had no record). If the strategy had been configured to re-enter when it detected "no open position," it could have doubled down unknowingly.

### Architectural rule for SuperHydra

Order submission and ledger recording are **atomic operations**. The Order Management System (OMS) enforces this at the adapter layer:

1. **Write-ahead**: Before submitting an order to any venue, write an `ORDER_INTENT` record to the ledger with status `PENDING`. This record includes strategy_id, venue, instrument, side, size, price, and a unique correlation_id.

2. **Submit**: Send the order to the venue. On success, update the ledger record to `SUBMITTED` with the venue's order_id. On failure, update to `FAILED`.

3. **Confirm**: When a fill confirmation arrives (webhook or poll), update to `FILLED` with fill_price, fill_size, fill_ts.

4. **Reconcile**: A background reconciler runs every 60 seconds. It queries the venue for all recent fills and compares against the ledger. Any fill without a matching `SUBMITTED` or `FILLED` record triggers:
   - Immediate Telegram alert: "UNRECORDED FILL: {venue} {instrument} {side} {size} @ {price}"
   - Halt-new-orders state for the affected strategy
   - The unrecorded fill is written to the ledger with status `RECONCILED` and a flag for manual review

5. **No exceptions**: REPL trades, debug trades, manual intervention, and any other non-strategy-initiated orders must also route through the OMS. The venue adapter layer enforces this: the only code path that can sign and submit an order to Polymarket (or Binance, or any venue) is the OMS's `submit_order()` function. Direct API calls from strategy code are architecturally impossible — the private key is held by the OMS, not by individual strategies.

This eliminates all three failure modes:
- Silent DB write failures are caught by the reconciler within 60 seconds
- Pre-system manual trades cannot happen because the private key is only accessible through the OMS
- One-off test trades must go through the OMS, which records them

---

**Signoff (final addendum):** Wasseem, 2026-05-02. Three addendums, three architectural rules: review what code actually does (not what it's named), reject games with negative EV before writing code, and make order recording atomic. These are not optional improvements — they are preconditions for trusting any number the system produces.
