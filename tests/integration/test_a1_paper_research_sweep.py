"""Day 20.6 narrow-sweep firewall tests.

Three new SOLUSDT 14-day fixtures, each tested with a single
parameterized firewall-only test. Per Day 20.5B Amendment to B.5:
asserts only firewall properties (PAPER_RESEARCH, promotion_eligible
false, trading.fills unchanged); does NOT assert a specific
intents_fired count. The empirical result is in the harness output
and the memo, not in test invariants.

Pattern matches test_a1_paper_research_may_2024.py.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from strategies.a1_funding.runner.paper_research_harness import (
    HarnessConfig,
    run_harness,
)
from tests.integration.test_migrations import (  # noqa: F401
    _alembic,
    _connect,
    fresh_db,
)


FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "binance_funding"


SWEEP_FIXTURES = [
    "SOLUSDT_14d_20240316T000000_20240330T000000.json",
    "SOLUSDT_14d_20240215T000000_20240229T000000.json",
    "SOLUSDT_14d_20210901T000000_20210915T000000.json",
]


@pytest.mark.parametrize("fixture_name", SWEEP_FIXTURES)
def test_sweep_fixture_firewall_holds(fresh_db, fixture_name):
    """For each Day 20.6 sweep fixture, assert only firewall properties.

    Does NOT assert intents_fired count. Result is empirical, captured
    in the memo.
    """
    fixture_path = FIXTURE_DIR / fixture_name
    if not fixture_path.exists():
        pytest.skip(f"fixture not present at {fixture_path}")

    _alembic("upgrade", "0010")

    config = HarnessConfig(
        fixture_path=fixture_path,
        symbol="SOLUSDT",
        quantity_per_intent=Decimal("10.0"),
    )
    result = run_harness(config)

    # Harness completes; fixture loaded.
    assert result["events_loaded"] > 0
    assert result["cost_profile_name"] == "binance_vip5_alt_research_v1"
    assert result["source_mode"] == "PAPER_RESEARCH"

    # Firewall: trading.fills unchanged.
    assert result["trading_fills_before"] == result["trading_fills_after"]

    # Firewall: any paper.fills written must be PAPER_RESEARCH +
    # promotion_eligible=false. DB CHECK constraints enforce this;
    # this test verifies the operational path respects it end-to-end.
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT source_mode, promotion_eligible "
                "FROM paper.fills;"
            )
            for source_mode, promotion_eligible in cur.fetchall():
                assert source_mode == "PAPER_RESEARCH"
                assert promotion_eligible is False
