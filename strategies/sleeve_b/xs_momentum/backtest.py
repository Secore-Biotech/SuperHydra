"""Main backtest orchestration.

Iterates weekly Monday rebalance dates over the OOS window. At each:
  1. Compute signal (eligibility, returns, deciles)
  2. Build portfolio (equal-weight, vol-target)
  3. Compute turnover vs previous portfolio
  4. Compute realized weekly P&L using close-to-close returns
  5. Deduct fees = turnover * fees_bps
  6. Append to weekly P&L series and audit log

Pre-registration parameters (locked):
  - holding_days = 7
  - fees_bps_round_trip = 14.5
  - lookback_days = 14 (in signal.py)
  - decile_fraction = 0.10 (in signal.py)
  - target_annual_vol = 0.15 (in portfolio.py)

Returns BacktestResult with per-week P&L breakdown and per-rebalance
audit logs. Downstream code computes Sharpe, drawdown, etc. from these.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from .portfolio import (
    COLD_START_WEEKS,
    Portfolio,
    TARGET_WEEKLY_VOL,
    TRAILING_VOL_WEEKS,
    build_portfolio,
    compute_turnover,
)
from .prices import PriceMap
from .signal import (
    DECILE_FRACTION,
    LOOKBACK_DAYS,
    MIN_ELIGIBLE_FOR_REBALANCE,
    SignalOutput,
    compute_signal,
)
from .universe import UniverseAsset


# Pre-registration-locked defaults
HOLDING_DAYS = 7
FEES_BPS_ROUND_TRIP = Decimal("14.5")


@dataclass(frozen=True)
class RebalanceLog:
    """Audit log entry for one rebalance per reviewer requirement (5)."""
    rebalance_at: date
    eligible_symbols: list[str]
    eligible_count: int
    skipped: bool
    skip_reason: str | None
    long_bucket: list[str]
    short_bucket: list[str]
    long_returns_bps: dict[str, Decimal]
    short_returns_bps: dict[str, Decimal]
    decile_size: int
    portfolio_scale: Decimal
    realized_vol_input: Decimal | None
    gross_notional: Decimal
    turnover: Decimal
    excluded_symbols: list[dict]


@dataclass(frozen=True)
class WeeklyPnL:
    """One week's realized P&L breakdown."""
    week_start: date
    week_end: date
    long_pnl_bps: Decimal
    short_pnl_bps: Decimal
    gross_pnl_bps: Decimal
    fee_drag_bps: Decimal
    net_pnl_bps: Decimal


@dataclass(frozen=True)
class BacktestResult:
    rebalance_logs: list[RebalanceLog]
    weekly_pnls: list[WeeklyPnL]

    def equity_curve_bps(self) -> list[Decimal]:
        cum = Decimal("0")
        out = []
        for w in self.weekly_pnls:
            cum += w.net_pnl_bps
            out.append(cum)
        return out


def generate_rebalance_dates(start: date, end: date) -> list[date]:
    """Generate weekly Monday rebalance dates in [start, end].

    The first rebalance is the first Monday >= start. Subsequent rebalances
    are 7 days apart. The last rebalance is the latest Monday <= end.
    """
    weekday = start.weekday()  # 0=Monday
    days_to_monday = (-weekday) % 7
    first_monday = start + timedelta(days=days_to_monday)
    out = []
    cursor = first_monday
    while cursor <= end:
        out.append(cursor)
        cursor += timedelta(days=7)
    return out


def run_backtest(
    *,
    universe: list[UniverseAsset],
    prices: PriceMap,
    start: date,
    end: date,
    fees_bps: Decimal = FEES_BPS_ROUND_TRIP,
    lookback_days: int = LOOKBACK_DAYS,
    decile_fraction: Decimal = DECILE_FRACTION,
    min_eligible: int = MIN_ELIGIBLE_FOR_REBALANCE,
    target_weekly_vol: Decimal = TARGET_WEEKLY_VOL,
    cold_start_weeks: int = COLD_START_WEEKS,
    trailing_vol_weeks: int = TRAILING_VOL_WEEKS,
    holding_days: int = HOLDING_DAYS,
) -> BacktestResult:
    """Run the full OOS backtest over [start, end].

    The universe is the frozen master universe. No reconstitution. Per
    reviewer requirement (4): the universe argument is never modified;
    no new symbols are added during the backtest.
    """
    rebalance_dates = generate_rebalance_dates(start, end)
    if not rebalance_dates:
        return BacktestResult(rebalance_logs=[], weekly_pnls=[])

    rebalance_logs: list[RebalanceLog] = []
    weekly_pnls: list[WeeklyPnL] = []
    previous_portfolio: Portfolio | None = None
    trailing_pnl_bps: list[Decimal] = []

    for r in rebalance_dates:
        signal = compute_signal(
            rebalance_at=r,
            universe=universe,
            prices=prices,
            lookback_days=lookback_days,
            decile_fraction=decile_fraction,
            min_eligible=min_eligible,
        )

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

        # P&L over the holding window [r, r+holding_days-1]
        week_end = r + timedelta(days=holding_days - 1)
        if portfolio is None:
            long_pnl_bps = Decimal("0")
            short_pnl_bps = Decimal("0")
        else:
            long_positions = [
                p for p in portfolio.positions if p.weight > 0
            ]
            short_positions = [
                p for p in portfolio.positions if p.weight < 0
            ]
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

        long_returns_bps = {
            s: signal.returns[s] * Decimal("10000")
            for s in signal.long_bucket if s in signal.returns
        }
        short_returns_bps = {
            s: signal.returns[s] * Decimal("10000")
            for s in signal.short_bucket if s in signal.returns
        }
        rebalance_logs.append(RebalanceLog(
            rebalance_at=r,
            eligible_symbols=signal.eligible,
            eligible_count=signal.eligible_count,
            skipped=signal.skipped,
            skip_reason=signal.skip_reason,
            long_bucket=signal.long_bucket,
            short_bucket=signal.short_bucket,
            long_returns_bps=long_returns_bps,
            short_returns_bps=short_returns_bps,
            decile_size=signal.long_decile_size,
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


def _compute_bucket_pnl_bps(
    *,
    positions: list,
    prices: PriceMap,
    start_date: date,
    end_date: date,
) -> Decimal:
    """Compute P&L of a bucket over [start_date, end_date], returned in bps.

    Per-position contribution: weight × (end_close / start_close - 1).
    Missing closes contribute zero (a position with no end-of-week price
    earns zero, not None — the equivalent of holding the start price).
    """
    total = Decimal("0")
    for pos in positions:
        series = prices.get(pos.symbol)
        if series is None:
            continue
        start_close = series.close_at(start_date)
        end_close = series.close_at(end_date)
        if start_close is None or end_close is None or start_close == 0:
            continue
        asset_return = (end_close - start_close) / start_close
        total += pos.weight * asset_return
    return total * Decimal("10000")
