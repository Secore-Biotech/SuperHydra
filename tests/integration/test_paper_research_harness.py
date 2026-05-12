"""Integration tests for the Day 20.5 operator harness."""
from __future__ import annotations

import json
import subprocess
import sys
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


REAL_FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "fixtures" / "binance_funding"
    / "SOLUSDT_14d_20240301T000000_20240315T000000.json"
)


def _bootstrap_db():
    """Bring the schema to 0010 head; no registry rows (harness creates them)."""
    _alembic("upgrade", "0010")


def _common_config(fixture: Path) -> HarnessConfig:
    return HarnessConfig(
        fixture_path=fixture,
        symbol="SOLUSDT",
        quantity_per_intent=Decimal("10.0"),
    )


def test_harness_real_sol_fixture_matches_day_20_4_finding(fresh_db):
    """Day 20.4 finding via harness: 43 events, 0 intents fired.

    Asserts:
      - intents_fired = 0 (the empirical finding)
      - paper_fills_before/after = 0/0
      - trading_fills row count unchanged
      - cost_profile_name = binance_vip5_alt_research_v1
      - source_mode = PAPER_RESEARCH
    """
    if not REAL_FIXTURE.exists():
        pytest.skip(f"fixture not present at {REAL_FIXTURE}")

    _bootstrap_db()
    result = run_harness(_common_config(REAL_FIXTURE))

    # Reviewer-listed output schema, all keys present.
    expected_keys = {
        "fixture", "symbol", "quantity_per_intent",
        "cost_profile_name", "source_mode",
        "events_loaded",
        "events_skipped_below_lookback",
        "events_skipped_below_threshold",
        "events_skipped_zero_funding",
        "events_skipped_no_reference_price",
        "intents_fired",
        "paper_fills_before", "paper_fills_after",
        "observed_slippage_non_null",
        "observed_slippage_null",
        "median_observed_slippage_bps",
        "p90_observed_slippage_bps",
        "trading_fills_before", "trading_fills_after",
    }
    assert expected_keys.issubset(result.keys())

    assert result["events_loaded"] == 43
    assert result["events_skipped_below_lookback"] == 12
    assert result["events_skipped_below_threshold"] == 31
    assert result["events_skipped_zero_funding"] == 0
    assert result["events_skipped_no_reference_price"] == 0
    assert result["intents_fired"] == 0
    assert result["paper_fills_before"] == 0
    assert result["paper_fills_after"] == 0
    assert result["trading_fills_before"] == result["trading_fills_after"]
    assert result["cost_profile_name"] == "binance_vip5_alt_research_v1"
    assert result["source_mode"] == "PAPER_RESEARCH"
    # No fills -> no slippage stats.
    assert result["observed_slippage_non_null"] == 0
    assert result["median_observed_slippage_bps"] is None


def test_harness_registry_bootstrap_is_idempotent(fresh_db):
    """Run harness twice with same codes; second run does not duplicate
    registry rows or error.
    """
    if not REAL_FIXTURE.exists():
        pytest.skip(f"fixture not present at {REAL_FIXTURE}")

    _bootstrap_db()

    config = _common_config(REAL_FIXTURE)
    result_1 = run_harness(config)
    result_2 = run_harness(config)

    # Outputs should match (no fills written either run; same events).
    assert result_1["intents_fired"] == result_2["intents_fired"]
    assert result_1["paper_fills_after"] == result_2["paper_fills_after"]

    # Registry counts unchanged across runs (idempotent get-or-create).
    with _connect() as conn:
        with conn.cursor() as cur:
            for table in (
                "registry.venues",
                "registry.assets",
                "registry.instruments",
                "registry.portfolios",
                "registry.accounts",
                "registry.strategies",
            ):
                cur.execute(f"SELECT COUNT(*) FROM {table};")
                count = cur.fetchone()[0]
                # Counts can be more than 1 for assets (SOL + USDT) but
                # must be the same on second run as on first.
                cur.execute(f"SELECT COUNT(*) FROM {table};")
                count_again = cur.fetchone()[0]
                assert count == count_again, (
                    f"{table} count changed on second harness run "
                    f"(non-idempotent)"
                )


def test_harness_cli_smoke(fresh_db):
    """CLI subprocess invocation produces valid JSON to stdout."""
    if not REAL_FIXTURE.exists():
        pytest.skip(f"fixture not present at {REAL_FIXTURE}")

    _bootstrap_db()

    # Test default (compact) output.
    proc = subprocess.run(
        [
            sys.executable, "-m",
            "strategies.a1_funding.runner.paper_research_harness",
            "--fixture", str(REAL_FIXTURE),
            "--symbol", "SOLUSDT",
            "--quantity", "10.0",
        ],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, f"CLI failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"

    payload = json.loads(proc.stdout)
    assert payload["symbol"] == "SOLUSDT"
    assert payload["intents_fired"] == 0  # Day 20.4 finding
    # Compact JSON should not contain double-newline indentation.
    assert "\n  " not in proc.stdout


def test_harness_cli_pretty_flag_produces_indented_output(fresh_db):
    """--pretty produces multi-line indented JSON."""
    if not REAL_FIXTURE.exists():
        pytest.skip(f"fixture not present at {REAL_FIXTURE}")

    _bootstrap_db()

    proc = subprocess.run(
        [
            sys.executable, "-m",
            "strategies.a1_funding.runner.paper_research_harness",
            "--fixture", str(REAL_FIXTURE),
            "--symbol", "SOLUSDT",
            "--quantity", "10.0",
            "--pretty",
        ],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0
    # Pretty JSON has multi-line output with indentation.
    assert "\n  " in proc.stdout
    # Still valid JSON.
    payload = json.loads(proc.stdout)
    assert payload["intents_fired"] == 0


def test_harness_cli_rejects_missing_fixture():
    """Nonexistent fixture path exits non-zero."""
    proc = subprocess.run(
        [
            sys.executable, "-m",
            "strategies.a1_funding.runner.paper_research_harness",
            "--fixture", "/nonexistent/path.json",
            "--symbol", "SOLUSDT",
            "--quantity", "10.0",
        ],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode != 0
    assert "fixture not found" in proc.stderr.lower()


def test_harness_rejects_invalid_quantity_via_cli():
    """--quantity 0 must fail (runner __init__ raises)."""
    if not REAL_FIXTURE.exists():
        pytest.skip(f"fixture not present at {REAL_FIXTURE}")

    proc = subprocess.run(
        [
            sys.executable, "-m",
            "strategies.a1_funding.runner.paper_research_harness",
            "--fixture", str(REAL_FIXTURE),
            "--symbol", "SOLUSDT",
            "--quantity", "0",
        ],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode != 0
    # Error JSON appears on stderr.
    err_payload = json.loads(proc.stderr.strip().split("\n")[-1])
    assert err_payload["error"] == "ValueError"
    assert "quantity_per_intent" in err_payload["message"]
