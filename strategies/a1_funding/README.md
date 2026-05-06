# strategies/a1_funding

**Engine A1 — Funding-rate capture.** Sleeve A's first build-to-trade engine.

## What this is

Mechanical capture of perp funding rates on liquid BTC and ETH instruments at a single venue (Binance). Long perp + short spot when funding pays longs to shorts (negative funding); inverse when positive. Bounded by fixed per-instrument caps; sized against expected next-period funding net of cost-model drag.

This engine is the program's first end-to-end build because:

- Edge is defensible at small scale and well-understood.
- P&L is mechanically attributable: funding accrual minus borrow minus fees minus slippage.
- Risk is naturally bounded by spot-perp leg-pair construction.
- It is the cleanest target for the round-3-shipped 0009 risk evaluator and the 0007/0008 OMS+positions stack.

## Gates

This engine moves through phases independently. Other engines (A2 basis, A3 cash-and-carry) do not inherit promotion.

- **P0 — Research & build.** Signal generator built, cost model defined, paper plumbing wired through the production OMS / risk / ledger path. Promotion to P1: paper run reproducible end-to-end on production code path.
- **P1 — Paper proof.** ≥ 60-day paper run. Promotion to P2: paper Sharpe ≥ 2.0, cost-model error tightening, no reconciliation drift.
- **P2 — Drift compression.** Microstructure overlay engaged in execution-improvement mode, regime overlay reduces gross exposure in fragile states. Promotion to P3: cost-model error and live-vs-shadow drift both compress materially.
- **P3 — Canary.** Live at canary capital ($500–$2,000 per engine). Promotion to P4: full Appendix A canary evidence pack cleared.
- **P4 — Scale.** Capital scales toward 2.4–2.5+ live target.

## Canary evidence pack (per Appendix A.1)

| Metric | Threshold |
|---|---|
| Minimum live days | 21 |
| Minimum executed leg-pairs | 50 |
| Minimum settled funding intervals | 30 |
| Unexplained reconciliation breaks | 0 |
| Realised-vs-modelled cost drift | within ±20% relative |
| Single-event cost drift (review trigger) | > 50% relative or > 15 bps absolute |
| Venue reject rate | ≤ 1% |
| Drawdown — peak-to-trough | ≤ 10% canary capital |
| Manual-intervention tolerance | ≤ 1 unplanned per 7 live days |

Plus: A.1.1 economic pass condition (positive realised net economics + live Sharpe within band vs shadow).

## Kill criteria (per §9.1)

- Fails to clear paper Sharpe ≥ 2.0 after 90 days of honest paper running → engine retired.
- Live Sharpe in canary < 50% of shadow Sharpe (after Appendix A min window + min event count both met) → engine retired or rebuilt; no patching.
- Reconciliation fails three times in canary without identified root cause within 24 hours → capital fully withdrawn.
- Operational cost > 2× engine paper P&L sustained over a quarter → engine retired.

## Layout

```
a1_funding/
├── README.md          (this file)
├── config/            engine-specific config (instrument list, per-instrument caps)
├── signal/            funding-rate signal generator
├── sizing/            leg-pair sizer with fixed per-instrument caps
├── runner/            paper runner; canary runner (later)
├── attribution/       P&L derivation from ledger; reconciliation
└── tests/
    └── unit/          unit tests for signal, sizing, attribution
```

Shared infrastructure lives elsewhere:

- Funding-rate ingestion: `data/ingestion/vendors/binance/funding_rate.py`
- Paper fill adapter contract: `execution/adapters/paper_adapter.py`
- Cost model schema: `core/config/cost_model.py`

## Day-1 status

Skeleton only. No signal, sizing, or runner code yet. The package is importable; cost-model defaults exist; paper-fill contract is defined. Day 2-7 fills `signal/`, `sizing/`, and the cost-model calibration. Day 8 runs the vertical smoke test through OMS / risk / paper adapter / journal / position snapshot.
