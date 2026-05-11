"""Slippage calibration analytics.

Day 20.2 deliverable: pure read-side aggregator over paper.fills.

Closes the loop on the paper.fills evidence container by providing the
aggregation function that turns recorded fills into calibration stats
(median, p90, range). Day 20.3 will wire A1 to record fills; this
module reads what gets written.

Reviewer-locked rules:
  - source_mode = 'PAPER_RESEARCH' (always filtered)
  - promotion_eligible = false (always filtered, defense-in-depth with
    the DB CHECK constraint that already forbids PAPER_RESEARCH from
    being promotion_eligible=true)
  - observed_slippage_bps IS NULL rows excluded from stats but counted
    separately as n_excluded_null for transparency
  - No DB writes (read-only); pure aggregation
  - Returns SlippageCalibration dataclass; caller interprets

The output is research-only research support, NOT execution-grade
calibration. PAPER_RESEARCH fills remain non-promotion-eligible
regardless of what statistics this module computes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final


# Percentile quantiles computed in a single SQL pass.
QUANTILE_P25: Final[float] = 0.25
QUANTILE_P50: Final[float] = 0.50
QUANTILE_P75: Final[float] = 0.75
QUANTILE_P90: Final[float] = 0.90


@dataclass(frozen=True)
class SlippageCalibration:
    """Aggregate calibration stats over a filtered set of paper.fills rows.

    All bps values are reported in basis points. NULL observed_slippage_bps
    rows are excluded from the statistics but counted as n_excluded_null;
    callers reporting calibration evidence should always surface both n
    and n_excluded_null together.

    If n == 0 (no rows with non-null observed slippage matched the
    filter), all *_bps fields are None.

    Filter fields (cost_profile_name, instrument_id, window_start,
    window_end) record what filters produced the result, for downstream
    audit. None means "no filter applied at this dimension".
    """

    n: int
    n_excluded_null: int
    median_bps: Decimal | None
    p25_bps: Decimal | None
    p75_bps: Decimal | None
    p90_bps: Decimal | None
    min_bps: Decimal | None
    max_bps: Decimal | None

    # Filter provenance.
    cost_profile_name: str | None
    instrument_id: int | None
    window_start: datetime | None
    window_end: datetime | None

    def __post_init__(self) -> None:
        if self.n < 0:
            raise ValueError(f"n must be >= 0, got {self.n}")
        if self.n_excluded_null < 0:
            raise ValueError(
                f"n_excluded_null must be >= 0, got {self.n_excluded_null}"
            )
        bps_fields = (
            self.median_bps, self.p25_bps, self.p75_bps,
            self.p90_bps, self.min_bps, self.max_bps,
        )
        if self.n == 0:
            for f in bps_fields:
                if f is not None:
                    raise ValueError(
                        f"n=0 requires all bps fields None; got {bps_fields}"
                    )
        else:
            for f in bps_fields:
                if f is None:
                    raise ValueError(
                        f"n>0 requires all bps fields set; got {bps_fields}"
                    )


def compute_slippage_calibration(
    conn,
    *,
    cost_profile_name: str | None = None,
    instrument_id: int | None = None,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> SlippageCalibration:
    """Aggregate observed_slippage_bps across paper.fills rows.

    Reviewer-locked hard filters (always applied):
      - source_mode = 'PAPER_RESEARCH'
      - promotion_eligible = false

    Optional caller filters:
      - cost_profile_name: equality match
      - instrument_id: equality match
      - window_start: filled_at >= window_start (inclusive)
      - window_end: filled_at < window_end (exclusive)

    Rows with observed_slippage_bps IS NULL are excluded from the
    statistics but counted in n_excluded_null.

    Single SQL query computes all aggregates in one pass via
    PERCENTILE_CONT for percentiles and COUNT/MIN/MAX for the rest.
    """
    # Defensive validation on optional filters. The DB will reject bad
    # types but we catch early for cleaner error messages.
    if window_start is not None and window_start.tzinfo is None:
        raise ValueError("window_start must be timezone-aware")
    if window_end is not None and window_end.tzinfo is None:
        raise ValueError("window_end must be timezone-aware")
    if (window_start is not None and window_end is not None
            and window_end <= window_start):
        raise ValueError(
            f"window_end ({window_end}) must be strictly after "
            f"window_start ({window_start})"
        )

    # Build WHERE clause incrementally.
    where_clauses = [
        "source_mode = 'PAPER_RESEARCH'",
        "promotion_eligible = false",
    ]
    params: list = []

    if cost_profile_name is not None:
        where_clauses.append("cost_profile_name = %s")
        params.append(cost_profile_name)
    if instrument_id is not None:
        where_clauses.append("instrument_id = %s")
        params.append(instrument_id)
    if window_start is not None:
        where_clauses.append("filled_at >= %s")
        params.append(window_start)
    if window_end is not None:
        where_clauses.append("filled_at < %s")
        params.append(window_end)

    where_sql = " AND ".join(where_clauses)

    sql = f"""
        SELECT
            COUNT(observed_slippage_bps) AS n,
            SUM(CASE WHEN observed_slippage_bps IS NULL THEN 1 ELSE 0 END)
                AS n_excluded_null,
            PERCENTILE_CONT({QUANTILE_P25})
                WITHIN GROUP (ORDER BY observed_slippage_bps) AS p25,
            PERCENTILE_CONT({QUANTILE_P50})
                WITHIN GROUP (ORDER BY observed_slippage_bps) AS median,
            PERCENTILE_CONT({QUANTILE_P75})
                WITHIN GROUP (ORDER BY observed_slippage_bps) AS p75,
            PERCENTILE_CONT({QUANTILE_P90})
                WITHIN GROUP (ORDER BY observed_slippage_bps) AS p90,
            MIN(observed_slippage_bps) AS min_bps,
            MAX(observed_slippage_bps) AS max_bps
        FROM paper.fills
        WHERE {where_sql};
    """

    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()

    # row is always present (single-row aggregate); on empty input,
    # values may be 0 or NULL.
    n = int(row[0])
    n_excluded_null = int(row[1] or 0)

    if n == 0:
        return SlippageCalibration(
            n=0,
            n_excluded_null=n_excluded_null,
            median_bps=None,
            p25_bps=None,
            p75_bps=None,
            p90_bps=None,
            min_bps=None,
            max_bps=None,
            cost_profile_name=cost_profile_name,
            instrument_id=instrument_id,
            window_start=window_start,
            window_end=window_end,
        )

    # PERCENTILE_CONT interpolates in double precision; quantize back
    # to the schema's NUMERIC(20,10) precision to avoid float-noise
    # artifacts in equality comparisons downstream.
    _Q = Decimal("1.0000000000")  # 10 decimal places, matches schema
    def _q(v):
        return Decimal(v).quantize(_Q) if v is not None else None
    return SlippageCalibration(
        n=n,
        n_excluded_null=n_excluded_null,
        median_bps=_q(row[3]),
        p25_bps=_q(row[2]),
        p75_bps=_q(row[4]),
        p90_bps=_q(row[5]),
        min_bps=_q(row[6]),
        max_bps=_q(row[7]),
        cost_profile_name=cost_profile_name,
        instrument_id=instrument_id,
        window_start=window_start,
        window_end=window_end,
    )
