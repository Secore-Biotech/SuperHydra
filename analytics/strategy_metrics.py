"""Strategy P&L analytics — interval bucketing + Sharpe.

Two functions:

  compute_interval_returns(conn, ...) -> list[IntervalReturn]
      DB-side: reads accounting.funding_payments + accounting.ledger_entries
      over a time window, buckets by funding-cycle intervals, returns one
      IntervalReturn per bucket.

  compute_sharpe(returns, *, intervals_per_year) -> SharpeResult
      Pure-function: Sharpe over a precomputed return series.

Important: Sharpe is computed over USD P&L observations, not percent
returns. Capital-normalized (return-as-fraction-of-capital) Sharpe
requires a capital-at-risk denominator and will be a later enhancement.
The metric this module produces is informative for ranking strategies
on a fixed-capital basis but is NOT directly comparable to Sharpe
numbers reported by a percent-return convention.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Iterable


# ─── Result types ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class IntervalReturn:
    """One funding-cycle bucket of P&L.

    Fields:
        interval_start: inclusive boundary
        interval_end: exclusive boundary
        funding_pnl_usd: net of received - paid funding payments whose
            funded_at lies in [interval_start, interval_end)
        fee_pnl_usd: sum of fee_expense ledger entries whose journal
            created_at lies in the interval. Sign is negative (fees
            reduce P&L).
        mark_pnl_usd: mark-to-market P&L on positions at interval
            boundaries. May be Decimal(0) when boundary marks are
            unavailable; capital-normalized Sharpe / mark reconstruction
            is a later enhancement.
        total_pnl_usd: sum of the three above.
    """
    interval_start: datetime
    interval_end: datetime
    funding_pnl_usd: Decimal
    fee_pnl_usd: Decimal
    mark_pnl_usd: Decimal
    total_pnl_usd: Decimal

    def __post_init__(self) -> None:
        if self.interval_end <= self.interval_start:
            raise ValueError(
                f"interval_end must be > interval_start; "
                f"got {self.interval_start} → {self.interval_end}"
            )
        # Validate the sum is consistent with components. Use a tiny
        # tolerance because Decimal arithmetic is exact but inputs may
        # have been rounded by the caller.
        expected = self.funding_pnl_usd + self.fee_pnl_usd + self.mark_pnl_usd
        if expected != self.total_pnl_usd:
            raise ValueError(
                f"total_pnl_usd ({self.total_pnl_usd}) does not match "
                f"funding+fee+mark ({expected})"
            )


@dataclass(frozen=True)
class SharpeResult:
    """Pure Sharpe over a USD-P&L series.

    Fields:
        n_intervals: number of observations
        mean_return_usd: arithmetic mean of total_pnl_usd over the series
        stdev_return_usd: sample standard deviation (n-1 denominator)
        annualization_factor: sqrt(intervals_per_year)
        sharpe: (mean / stdev) * annualization_factor
        intervals_per_year: input that drove annualization

    Notes:
        - Sharpe is over USD P&L per interval, NOT percent returns.
        - Caller must select intervals_per_year matching the bucketing.
          For Binance perp funding: 3 intervals/day × 365 = 1095.
    """
    n_intervals: int
    mean_return_usd: Decimal
    stdev_return_usd: Decimal
    annualization_factor: Decimal
    sharpe: Decimal
    intervals_per_year: int


class SharpeError(Exception):
    pass


# ─── Pure-function Sharpe ────────────────────────────────────────────────


def compute_sharpe(
    interval_returns: list[IntervalReturn],
    *,
    intervals_per_year: int,
) -> SharpeResult:
    """Compute USD-P&L Sharpe over a precomputed interval-return series.

    Sharpe = (mean / stdev) * sqrt(intervals_per_year)

    Raises SharpeError on:
      - n < 2 (no stdev defined)
      - stdev == 0 (degenerate; gate metric must be auditable)
      - intervals_per_year < 1
    """
    if intervals_per_year < 1:
        raise SharpeError(
            f"intervals_per_year must be >= 1, got {intervals_per_year}"
        )
    n = len(interval_returns)
    if n < 2:
        raise SharpeError(
            f"Sharpe requires at least 2 observations, got {n}"
        )

    pnls = [ir.total_pnl_usd for ir in interval_returns]
    mean = sum(pnls) / Decimal(n)

    # Sample variance with n-1 denominator (Bessel's correction).
    sq_dev_sum = sum((x - mean) ** 2 for x in pnls)
    variance = sq_dev_sum / Decimal(n - 1)
    stdev = _decimal_sqrt(variance)

    if stdev == Decimal("0"):
        raise SharpeError(
            f"Sharpe undefined: stdev of {n} observations is zero "
            f"(returns are degenerate)"
        )

    ann_factor = _decimal_sqrt(Decimal(intervals_per_year))
    sharpe = (mean / stdev) * ann_factor

    return SharpeResult(
        n_intervals=n,
        mean_return_usd=mean,
        stdev_return_usd=stdev,
        annualization_factor=ann_factor,
        sharpe=sharpe,
        intervals_per_year=intervals_per_year,
    )


# ─── DB-side bucketing ───────────────────────────────────────────────────


def compute_interval_returns(
    conn,
    *,
    strategy_id: int,
    instrument_id: int,
    window_start: datetime,
    window_end: datetime,
    interval_duration: timedelta,
) -> list[IntervalReturn]:
    """Bucket P&L by funding-cycle intervals.

    For each interval [interval_start, interval_end):
      - funding_pnl_usd: received minus paid from accounting.funding_payments
        where funded_at is in the bucket
      - fee_pnl_usd: -SUM of accounting.ledger_entries where
        ledger_account starts with 'v1:fee_expense:' AND the journal's
        created_at is in the bucket
      - mark_pnl_usd: Decimal(0) for Day 16c (boundary marks not
        reconstructed yet)
      - total_pnl_usd: sum

    Funding bucketing uses funded_at; fee bucketing uses
    trading.fills.filled_at via the journal->fill link. This matches
    reality: a funding payment "happens" at funded_at, a fee "happens"
    at the underlying fill's economic timestamp (not when the journal
    happened to be posted, which can be arbitrarily delayed).

    Caller scopes to (portfolio_id, strategy_id, instrument_id). Cross-
    strategy or cross-instrument analysis is not in scope for this
    function — call once per scope and combine outside.
    """
    if window_end <= window_start:
        raise ValueError(
            f"window_end must be > window_start; "
            f"got {window_start} → {window_end}"
        )
    if interval_duration <= timedelta(0):
        raise ValueError(
            f"interval_duration must be positive, got {interval_duration}"
        )

    boundaries = _bucket_boundaries(window_start, window_end, interval_duration)

    intervals: list[IntervalReturn] = []
    with conn.cursor() as cur:
        for i in range(len(boundaries) - 1):
            i_start = boundaries[i]
            i_end = boundaries[i + 1]

            # Funding P&L: received - paid.
            cur.execute(
                """
                SELECT
                    COALESCE(SUM(CASE
                        WHEN direction = 'received' THEN amount_usd
                        WHEN direction = 'paid' THEN -amount_usd
                        ELSE 0
                    END), 0)
                FROM accounting.funding_payments
                WHERE strategy_id = %s
                  AND instrument_id = %s
                  AND funded_at >= %s
                  AND funded_at < %s
                """,
                (strategy_id, instrument_id, i_start, i_end),
            )
            funding_pnl = cur.fetchone()[0]

            # Fee P&L: ledger entries to fee_expense accounts. Time
            # bucketing is by trading.fills.filled_at (the trade's
            # economic timestamp), not the journal's created_at (which
            # is just when the journal was posted to the DB and may be
            # arbitrarily delayed in test or replay scenarios).
            cur.execute(
                """
                SELECT COALESCE(SUM(le.amount_usd), 0)
                FROM accounting.ledger_entries le
                JOIN accounting.journals j ON j.id = le.journal_id
                JOIN accounting.ledger_accounts la
                    ON la.id = le.ledger_account_id
                JOIN trading.fills f ON f.journal_id = j.id
                WHERE f.filled_at >= %s
                  AND f.filled_at < %s
                  AND j.status = 'posted'
                  AND j.voided_at IS NULL
                  AND la.account_code LIKE 'v1:fee_expense:%%'
                  AND le.debit_credit = 'debit'
                """,
                (i_start, i_end),
            )
            fee_total = cur.fetchone()[0]
            fee_pnl = -fee_total

            mark_pnl = Decimal("0")
            total_pnl = funding_pnl + fee_pnl + mark_pnl

            intervals.append(IntervalReturn(
                interval_start=i_start,
                interval_end=i_end,
                funding_pnl_usd=funding_pnl,
                fee_pnl_usd=fee_pnl,
                mark_pnl_usd=mark_pnl,
                total_pnl_usd=total_pnl,
            ))

    return intervals


# ─── Helpers ─────────────────────────────────────────────────────────────


def _bucket_boundaries(
    window_start: datetime,
    window_end: datetime,
    interval_duration: timedelta,
) -> list[datetime]:
    """Inclusive list of interval boundaries from window_start to
    window_end. The last boundary is window_end (exclusive of any data
    at exactly window_end)."""
    boundaries = [window_start]
    cursor = window_start
    while cursor + interval_duration < window_end:
        cursor += interval_duration
        boundaries.append(cursor)
    boundaries.append(window_end)
    return boundaries


def _decimal_sqrt(x: Decimal) -> Decimal:
    """Newton's method square root over Decimal. Sufficient for our
    small dynamic-range gate metric (Sharpe in [0, 50] for realistic
    inputs)."""
    if x < 0:
        raise ValueError(f"sqrt of negative: {x}")
    if x == 0:
        return Decimal("0")

    # Initial guess via float, refined by Newton iterations.
    guess = Decimal(str(float(x) ** 0.5))
    for _ in range(40):
        if guess == Decimal("0"):
            break
        next_guess = (guess + x / guess) / Decimal("2")
        if next_guess == guess:
            break
        guess = next_guess
    return guess
