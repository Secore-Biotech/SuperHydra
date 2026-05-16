"""Test-only NoopFetcher — returns empty trade list for any window.

This fixture exists so that PAPER_RESEARCH scripts can opt in to synthetic
fills (no real venue data) via an explicit --allow-noop-fetcher CLI flag.

It MUST NOT be imported from production or research code paths without
the --allow-noop-fetcher gate.  See docs/advisor_review_checklist.md
("Test-stub leakage") for the CI enforcement rule.
"""
from __future__ import annotations


class _NoopFetcher:
    """Returns empty trade list for any window.  Day 24 has no real
    perp/spot tick data; replay observation rows have observed_slippage_bps
    NULL with replay_status='empty_window'."""

    def fetch_window(self, symbol, start, end):
        return []
