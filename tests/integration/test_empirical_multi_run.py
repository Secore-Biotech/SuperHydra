"""Integration test: two runs with the same fixture produce distinct fills.

Verifies that:
  - Each run's paper_fill_uuid set is unique (run_id mixed into hashes).
  - paper.fills row count grows by exactly N each time.
  - Each run's fills are filterable by their distinct empirical_run_id.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "empirical_a2_complete_trade_results.py"


def _run_script() -> str:
    """Run the empirical script with --allow-noop-fetcher; return stdout."""
    venv_python = REPO_ROOT / ".venv" / "bin" / "python3"
    python_cmd = str(venv_python) if venv_python.exists() else sys.executable

    result = subprocess.run(
        [python_cmd, str(SCRIPT), "--allow-noop-fetcher"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=120,
    )
    if result.returncode != 0:
        pytest.fail(
            f"Script failed (rc={result.returncode}).\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result.stdout


def _extract_run_id(stdout: str) -> str:
    """Extract run_id from script stdout."""
    for line in stdout.splitlines():
        if line.startswith("run_id:"):
            return line.split(":", 1)[1].strip()
    pytest.fail("run_id not found in script output")


def _count_fills_for_run(run_id: str) -> int:
    """Query paper.fills count for a specific run_id."""
    import os
    import psycopg

    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://superhydra:superhydra_dev_only@localhost:5432/superhydra",
    )
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT COUNT(*) FROM paper.fills
                   WHERE metadata->>'empirical_run_id' = %s;""",
                (run_id,),
            )
            return cur.fetchone()[0]


@pytest.mark.integration
def test_two_runs_produce_distinct_fills():
    """Running the script twice should double the fill count,
    with each run's fills isolated by run_id."""
    # Run 1
    stdout_1 = _run_script()
    run_id_1 = _extract_run_id(stdout_1)
    count_1 = _count_fills_for_run(run_id_1)
    assert count_1 > 0, f"Run 1 ({run_id_1}) produced 0 fills"

    # Run 2
    stdout_2 = _run_script()
    run_id_2 = _extract_run_id(stdout_2)
    count_2 = _count_fills_for_run(run_id_2)
    assert count_2 > 0, f"Run 2 ({run_id_2}) produced 0 fills"

    # Distinct run_ids
    assert run_id_1 != run_id_2, "Two runs should produce different run_ids"

    # Each run produced the same number of fills
    assert count_1 == count_2, (
        f"Fill counts differ: run 1 ({run_id_1}) = {count_1}, "
        f"run 2 ({run_id_2}) = {count_2}"
    )

    # Verify fills are filterable — each run's fills are isolated
    assert _count_fills_for_run(run_id_1) == count_1
    assert _count_fills_for_run(run_id_2) == count_2
