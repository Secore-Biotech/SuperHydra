"""Backtest engine for Sleeve B candidate #4 — volatility-scaled momentum.

Per pre-registration (commit 59c1156) and the portfolio interpretation memo
(commit 689ddd9, Reading A):

  - Signal: vol_scaled_momentum.signal.compute_signal (D1, commit 8cc69fc)
  - Portfolio: xs_momentum.portfolio.build_portfolio (inherited per Reading A)
    - Equal weight within bucket
    - Portfolio-level vol target 15% annualized
    - Cold start 4 weeks, trailing vol 4 weeks
    - No leverage cap
  - Turnover/fees: xs_momentum.backtest helpers (inherited)
  - P&L: xs_momentum.backtest._compute_bucket_pnl_bps (inherited)

This module exists because candidate #4's SignalOutput has different fields
than xs-momentum's (scores/momentum_components/vol_components instead of
returns; long_bucket_size instead of long_decile_size). The audit log
must preserve those fields for downstream F1/F3 evaluators (D3/D4).

WeeklyPnL is reused via import — identical structure across both engines.
RebalanceLog is candidate-#4-specific.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from strategies.sleeve_b.vol_scaled_momentum.signal import (
    MIN_ELIGIBLE_FOR_REBALANCE,
    MOMENTUM_LOOKBACK_DAYS,
    SignalOutput,
    VOL_LOOKBACK_DAYS,
    compute_signal,
)
from strategies.sleeve_b.xs_momentum.backtest import (
    FEES_BPS_ROUND_TRIP,
    HOLDING_DAYS,
    WeeklyPnL,
    _compute_bucket_pnl_bps,
    generate_rebalance_dates,
)
from strategies.sleeve_b.xs_momentum.portfolio import (
    COLD_START_WEEKS,
    Portfolio,
    TARGET_WEEKLY_VOL,
    TRAILING_VOL_WEEKS,
    build_portfolio,
    compute_turnover,
)
from strategies.sleeve_b.xs_momentum.prices import PriceMap
from strategies.sleeve_b.xs_momentum.universe import UniverseAsset


# Pre-registration-locked defaults (inherited / re-exported for runner clarity).
# Bucketing parameter is third_fraction (from signal.py), not decile_fraction.


@dataclass(frozen=True)
class RebalanceLog:
    """Audit log entry for one candidate #4 rebalance.

    Preserves the cross-sectional score AND its momentum / vol decomposition
    so downstream F1.3 (variance contribution) and F3.3 (return attribution)
    can compute without recomputing the signal.
    """
    rebalance_at: date
    eligible_symbols: list[str]
    eligible_count: int
    skipped: bool
    skip_reason: str | None
    long_bucket: list[str]
    short_bucket: list[str]
    scores: dict[str, Decimal]                  # symbol -> momentum/vol
    momentum_components: dict[str, Decimal]     # symbol -> trailing 30d simple return
    vol_components: dict[str, Decimal]          # symbol -> annualized 45d log-return vol
    long_bucket_size: int
    short_bucket_size: int
    portfolio_scale: Decimal
    realized_vol_input: Decimal | None
    gross_notional: Decimal
    turnover: Decimal
    excluded_symbols: list[dict]


@dataclass(frozen=True)
class BacktestResult:
    rebalance_logs: list[RebalanceLog]
    weekly_pnls: list[WeeklyPnL]

    def equity_curve_bps(self) -> list[Decimal]:
        cum = Decimal("0")
        out: list[Decimal] = []
        for w in self.weekly_pnls:
            cum += w.net_pnl_bps
            out.append(cum)
        return out


def run_backtest(
    *,
    universe: list[UniverseAsset],
    prices: PriceMap,
    start: date,
    end: date,
    holding_days: int = HOLDING_DAYS,
    fees_bps: Decimal = FEES_BPS_ROUND_TRIP,
    momentum_lookback_days: int = MOMENTUM_LOOKBACK_DAYS,
    vol_lookback_days: int = VOL_LOOKBACK_DAYS,
    min_eligible: int = MIN_ELIGIBLE_FOR_REBALANCE,
    target_weekly_vol: Decimal = TARGET_WEEKLY_VOL,
    cold_start_weeks: int = COLD_START_WEEKS,
    trailing_vol_weeks: int = TRAILING_VOL_WEEKS,
) -> BacktestResult:
    """Run the candidate #4 OOS backtest over [start, end].

    The universe is the frozen master universe. No reconstitution.
    """
    rebalance_dates = generate_rebalance_dates(start, end)
    if not rebalance_dates:
        return BacktestResult(rebalance_logs=[], weekly_pnls=[])

    rebalance_logs: list[RebalanceLog] = []
    weekly_pnls: list[WeeklyPnL] = []
    previous_portfolio: Portfolio | None = None
    trailing_pnl_bps: list[Decimal] = []

    for r in rebalance_dates:
        signal: SignalOutput = compute_signal(
            rebalance_at=r,
            universe=universe,
            prices=prices,
            momentum_lookback_days=momentum_lookback_days,
            vol_lookback_days=vol_lookback_days,
            min_eligible=min_eligible,
        )

        # build_portfolio works via duck typing on signal — it only accesses
        # skipped, long_bucket, short_bucket, rebalance_at. All present on
        # candidate #4's SignalOutput. Confirmed at pre-D2 inspection.
        portfolio = build_portfolio(
            signal=signal,
            trailing_weekly_pnl_bps=trailing_pnl_bps,
            target_weekly_vol=target_weekly_vol,
            cold_start_weeks=cold_start_weeks,
            trailing_vol_weeks=trailing_vol_weeks,
        )

        turnover = compute_turnover(
            previous=previous_portfolio, current=portfolio,
        )

        # P&L over [r, r + holding_days - 1]
        week_end = r + timedelta(days=holding_days - 1)
        if portfolio is None:
            long_pnl_bps = Decimal("0")
            short_pnl_bps = Decimal("0")
        else:
            long_positions = [p for p in portfolio.positions if p.weight > 0]
            short_positions = [p for p in portfolio.positions if p.weight < 0]
            long_pnl_bps = _compute_bucket_pnl_bps(
                positions=long_positions,
                prices=prices,
                start_date=r,
                end_date=week_end,
            )
            short_pnl_bps = _compute_bucket_pnl_bps(
                positions=short_positions,
                prices=prices,
                start_date=r,
                end_date=week_end,
            )
        gross_pnl_bps = long_pnl_bps + short_pnl_bps
        fee_drag_bps = turnover * fees_bps
        net_pnl_bps = gross_pnl_bps - fee_drag_bps

        weekly_pnls.append(WeeklyPnL(
            week_start=r,
            week_end=week_end,
            long_pnl_bps=long_pnl_bps,
            short_pnl_bps=short_pnl_bps,
            gross_pnl_bps=gross_pnl_bps,
            fee_drag_bps=fee_drag_bps,
            net_pnl_bps=net_pnl_bps,
        ))
        trailing_pnl_bps.append(net_pnl_bps)

        rebalance_logs.append(RebalanceLog(
            rebalance_at=r,
            eligible_symbols=signal.eligible,
            eligible_count=signal.eligible_count,
            skipped=signal.skipped,
            skip_reason=signal.skip_reason,
            long_bucket=signal.long_bucket,
            short_bucket=signal.short_bucket,
            scores=signal.scores,
            momentum_components=signal.momentum_components,
            vol_components=signal.vol_components,
            long_bucket_size=signal.long_bucket_size,
            short_bucket_size=signal.short_bucket_size,
            portfolio_scale=(
                portfolio.gross_notional_scale if portfolio else Decimal("0")
            ),
            realized_vol_input=(
                portfolio.realized_vol_input if portfolio else None
            ),
            gross_notional=(
                portfolio.gross_notional() if portfolio else Decimal("0")
            ),
            turnover=turnover,
            excluded_symbols=signal.excluded_symbols,
        ))

        previous_portfolio = portfolio

    return BacktestResult(
        rebalance_logs=rebalance_logs, weekly_pnls=weekly_pnls,
    )
