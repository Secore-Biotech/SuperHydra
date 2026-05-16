"""Regression test: --allow-noop-fetcher produces MODELED-ONLY label.

Verifies that running empirical_a2_complete_trade_results.py with
--allow-noop-fetcher causes the [MODELED-ONLY / NON-DECISION-GRADE]
label to appear in stdout output, confirming the safety guard fires
when >=90% of fills have NULL observed_slippage_bps.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "empirical_a2_complete_trade_results.py"
MODELED_ONLY_TAG = "[MODELED-ONLY / NON-DECISION-GRADE]"


@pytest.mark.integration
def test_noop_fetcher_produces_modeled_only_label():
    """With --allow-noop-fetcher the slippage guard must fire and
    prepend MODELED-ONLY to the memo title and stdout P&L lines."""
    assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

    venv_python = REPO_ROOT / ".venv" / "bin" / "python3"
    python_cmd = str(venv_python) if venv_python.exists() else sys.executable

    result = subprocess.run(
        [python_cmd, str(SCRIPT), "--allow-noop-fetcher"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=120,
    )

    combined = result.stdout + result.stderr
    assert MODELED_ONLY_TAG in combined, (
        f"Expected '{MODELED_ONLY_TAG}' in script output but it was absent.\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
