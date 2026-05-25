# vol_event_persistence

Research-phase engine for the Section A probe defined in
`notes/section_a_probe_spec_v1.md`.

## Purpose

Test whether 24h realised-volatility shocks on BTCUSDT / ETHUSDT
Binance perpetuals are followed by multi-day return persistence at
horizons 1d / 3d / 7d large enough to survive operator-tier perp
trading costs (≥ 20 bps mean net per trade, full economic gate per
spec §6).

## Status

Phase: **research**.

This package is sleeve-neutral. It is not a Sleeve C declaration, not
a deployment commitment, and not a candidate for promotion until the
pre-locked probe clears statistical and economic gates per spec §5
and §6. If the probe fails, the package is sunset rather than rebuilt.

## Pre-lock contract

Immutable probe constants live in `config/pre_lock.py`. Every value
there is frozen per spec §8. Changing a constant invalidates v1 and
requires a new spec with a fresh pre-lock. There is no amendment
path after results are inspected.

In particular:
- Lowering cost assumptions is forbidden. Costs can be raised if
  realised friction is worse than modelled; the gate thresholds do
  not move to accommodate.
- Persistence is the only hypothesis tested. Reversal-class
  hypotheses are out of scope and would require a separate package.
- P95 is the only volatility threshold. Threshold sensitivity is a
  v2 question, evaluated only if v1 clears.

## Layout

```
strategies/vol_event_persistence/
├── __init__.py
├── README.md                ← this file
└── config/
    ├── __init__.py
    └── pre_lock.py          ← immutable spec constants
```

Subsequent commits will add `signal/`, `sizing/`, `runner/`,
`attribution/`, and `tests/` under this package, mirroring the
A1 layout. The current commit is package shell + pre-lock only.

## Spec linkage

| Section | Purpose |
|---|---|
| spec §1 | measured object: forward perp return conditional on vol regime break |
| spec §2 | event definition: σ_24h > P95(trailing 90d) at 00:00 UTC daily |
| spec §3 | holding windows: {1d, 3d, 7d}, no others |
| spec §4 | cost model: taker fees + slippage + per-event realised funding |
| spec §5 | statistical gate: 80/20 train/OOS split, single-shot OOS |
| spec §6 | economic gate: ≥ 20 bps mean net, plus four supporting conditions |
| spec §7 | deployment shape: single-leg perp, no options, no second venue |
| spec §8 | immutability list — load-bearing for `config/pre_lock.py` |

## Runway

Section A probe runway is anchored in `notes/edge_scoping.md` §2.1:
2 months to P1 entry from 2026-05-25, expiry 2026-07-25. Calendar
guards from spec §9 apply.
