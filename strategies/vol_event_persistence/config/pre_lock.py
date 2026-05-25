"""Pre-locked parameters from notes/section_a_probe_spec_v1.md §8.

These constants are FROZEN. Any change to a value here invalidates v1
and requires a new spec (v2) with new pre-locks and a new registry row.
There is no amendment path after results are seen. Lowering cost
assumptions is the canonical curve-fit failure mode this module is
designed to prevent.

See notes/section_a_probe_spec_v1.md §8 for the invariance contract.
"""
from __future__ import annotations
from decimal import Decimal

# ===== Universe (spec §1, §2) =====
UNIVERSE: tuple[str, ...] = ("BTCUSDT", "ETHUSDT")
INSTRUMENT_CLASS: str = "perpetual"

# ===== Registry bootstrap codes =====
# Used by paper_research_harness when it bootstraps registry rows.
# Strategy name is purpose-keyed, not version-keyed; a v2 probe gets a
# new registry row, not a version suffix here.
VENUE_CODE: str = "binance"
STRATEGY_NAME: str = "vol_event_persistence"
PORTFOLIO_CODE: str = "vol_event_persistence_paper_research"
ACCOUNT_CODE: str = "vol_event_persistence_paper_research"
INSTRUMENT_CODES: tuple[str, ...] = ("BTCUSDT", "ETHUSDT")
ENGINE_LABEL: str = "vol_event_persistence"

# ===== Hypothesis (spec §1, §8) =====
# Reversal-class hypotheses are out of scope; see spec §10.
HYPOTHESIS: str = "persistence_only"

# ===== Realised-vol estimator (spec §2) =====
VOL_RETURN_BAR: str = "1h"
VOL_WINDOW_HOURS: int = 24
VOL_ANNUALISATION_FACTOR: int = 24 * 365

# ===== Trigger threshold (spec §2, single threshold) =====
PERCENTILE_THRESHOLD: Decimal = Decimal("0.95")
PERCENTILE_LOOKBACK_DAYS: int = 90
PERCENTILE_EXCLUDES_CURRENT: bool = True

# ===== Event-time anchoring (spec §2) =====
EVAL_TIME_UTC: str = "00:00:00"
MAX_EVENTS_PER_ASSET_PER_DAY: int = 1

# ===== Holding windows (spec §3, pre-locked) =====
HORIZONS_DAYS: tuple[int, ...] = (1, 3, 7)

# ===== Cost model (spec §4, operator-tier, floor not ceiling) =====
TAKER_FEE_BPS_PER_SIDE: Decimal = Decimal("4")
SLIPPAGE_BPS_PER_SIDE: Decimal = Decimal("1")
ROUND_TRIP_COST_BPS_FLOOR: Decimal = Decimal("10")
FUNDING_HANDLING: str = "per_event_realised_signed"

# ===== Sample split (spec §5, computed once) =====
TRAIN_FRACTION: Decimal = Decimal("0.80")
OOS_FRACTION: Decimal = Decimal("0.20")
OOS_MIN_MONTHS: int = 6
OOS_SHOT_COUNT: int = 1

# ===== Statistical gate (spec §5) =====
TRAIN_SHARPE_MIN: Decimal = Decimal("2.0")
OOS_SHARPE_MIN: Decimal = Decimal("1.5")
TRAIN_EVENTS_MIN: int = 100
OOS_EVENTS_MIN: int = 30
OOS_ROLLING_FAILURES_MAX: int = 1

# ===== Economic gate (spec §6) =====
ECONOMIC_MEAN_NET_BPS_MIN: Decimal = Decimal("20")
ECONOMIC_MEDIAN_NET_BPS_MIN: Decimal = Decimal("0")
ECONOMIC_WIN_RATE_MIN: Decimal = Decimal("0.50")
ECONOMIC_COST_COVERAGE_MIN: Decimal = Decimal("2.5")
ECONOMIC_FINAL_3MO_PNL_MIN: Decimal = Decimal("0")

# ===== Spec reference =====
SPEC_PATH: str = "notes/section_a_probe_spec_v1.md"
SPEC_VERSION: str = "v1"
