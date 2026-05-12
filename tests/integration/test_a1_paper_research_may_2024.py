"""Lightweight firewall test for the SOL May 2024 fixture.

Day 20.5B candidate fixture: 14-day SOLUSDT window ending 2024-05-15.

Per reviewer Amendment to B.5: this test does NOT assert a specific
intents_fired count. The empirical result lives in the harness output
and the memo. The test only asserts firewall properties hold:

  - fixture loads
  - harness/runner completes without error
  - trading.fills row count unchanged
  - any paper.fills written are PAPER_RESEARCH
  - any paper.fills written are promotion_eligible=false

This pattern matches the Day 20.4 real-fixture test
(test_real_sol_mar_2024_fixture_firewall_holds) which uses the same
firewall-only assertion style.
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


MAY_2024_FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "fixtures" / "binance_funding"
    / "SOLUSDT_14d_20240501T000000_20240515T000000.json"
)


def test_may_2024_fixture_firewall_holds(fresh_db):
    """Day 20.5B fixture: any results must respect firewall constraints."""
    if not MAY_2024_FIXTURE.exists():
        pytest.skip(f"fixture not present at {MAY_2024_FIXTURE}")

    _alembic("upgrade", "0010")

    config = HarnessConfig(
        fixture_path=MAY_2024_FIXTURE,
        symbol="SOLUSDT",
        quantity_per_intent=Decimal("10.0"),
    )
    result = run_harness(config)

    # Fixture loads, harness completes.
    assert result["events_loaded"] > 0
    assert result["cost_profile_name"] == "binance_vip5_alt_research_v1"
    assert result["source_mode"] == "PAPER_RESEARCH"

    # Firewall: trading.fills unchanged regardless of paper outcome.
    assert result["trading_fills_before"] == result["trading_fills_after"]

    # Firewall: any paper.fills written must be PAPER_RESEARCH +
    # promotion_eligible=false. The DB CHECK constraints already
    # enforce this at the schema level, but this is the operational
    # confirmation that the harness path respects it end-to-end.
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT source_mode, promotion_eligible "
                "FROM paper.fills;"
            )
            for source_mode, promotion_eligible in cur.fetchall():
                assert source_mode == "PAPER_RESEARCH"
                assert promotion_eligible is False
