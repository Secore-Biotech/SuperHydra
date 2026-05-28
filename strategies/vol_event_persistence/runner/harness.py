"""Operator harness for the vol_event_persistence probe.

Fixture-driven, pure probe execution. Loads one combined JSON fixture
(klines + funding), runs the event pipeline per instrument, evaluates the
§5/§6 gates per horizon, and emits a JSON verdict to stdout.

Usage:
    python -m strategies.vol_event_persistence.runner.harness \
        --fixture path/to/fixture.json [--pretty]

Hard constraints (probe phase):
    - no DB
    - no network
    - no paper.fills
    - no trading.fills
    - no registry bootstrap
    - pure probe execution only

If the probe clears the §5/§6 gates, P1 wiring (persistence, OMS/risk,
registry bootstrap) is a separate deliverable — explicitly NOT here.

Fixture schema (vol_event_fixture.v1): a single object with "klines" and
"funding" arrays. Kline objects use "taker_buy_base_volume" in the
fixture; this maps to the canonical BinanceKline.taker_buy_volume field
(the parser handles the rename so the operator-facing JSON stays legible).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

from data.ingestion.vendors.binance.funding_rate import FundingRate
from data.ingestion.vendors.binance.kline import BinanceKline
from strategies.vol_event_persistence.config import pre_lock
from strategies.vol_event_persistence.gates import (
    GateStatus,
    ProbeGateResult,
    evaluate_gates,
)
from strategies.vol_event_persistence.runner.event_pipeline import (
    RunResult,
    run_pipeline,
)

HARNESS_SCHEMA_VERSION = "vol_event_probe_report.v1"
FIXTURE_SCHEMA_VERSION = "vol_event_fixture.v1"


class HarnessError(Exception):
    """Raised on malformed fixtures or unusable CLI input."""


# ─── Fixture parsing (pure: dict -> canonical dataclasses) ──────────────────


def _parse_dt(s: str) -> datetime:
    ts = datetime.fromisoformat(s)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def _parse_kline(d: dict[str, Any]) -> BinanceKline:
    try:
        return BinanceKline(
            venue=d["venue"],
            instrument=d["instrument"],
            interval=d["interval"],
            open_time=_parse_dt(d["open_time"]),
            open=Decimal(str(d["open"])),
            high=Decimal(str(d["high"])),
            low=Decimal(str(d["low"])),
            close=Decimal(str(d["close"])),
            volume=Decimal(str(d["volume"])),
            quote_volume=Decimal(str(d["quote_volume"])),
            trade_count=int(d["trade_count"]),
            # Fixture uses taker_buy_base_volume; canonical field is
            # taker_buy_volume. Map here.
            taker_buy_volume=Decimal(str(d["taker_buy_base_volume"])),
            taker_buy_quote_volume=Decimal(str(d["taker_buy_quote_volume"])),
        )
    except KeyError as e:
        raise HarnessError(f"kline missing field {e}") from e


def _parse_funding(d: dict[str, Any]) -> FundingRate:
    try:
        mark = d.get("mark_price")
        return FundingRate(
            venue=d["venue"],
            instrument=d["instrument"],
            funding_time=_parse_dt(d["funding_time"]),
            funding_rate=Decimal(str(d["funding_rate"])),
            mark_price=Decimal(str(mark)) if mark is not None else None,
        )
    except KeyError as e:
        raise HarnessError(f"funding missing field {e}") from e


def parse_fixture(
    obj: dict[str, Any],
) -> tuple[list[BinanceKline], list[FundingRate]]:
    """Parse a vol_event_fixture.v1 object into canonical dataclasses."""
    version = obj.get("schema_version")
    if version != FIXTURE_SCHEMA_VERSION:
        raise HarnessError(
            f"fixture schema_version {version!r}, expected "
            f"{FIXTURE_SCHEMA_VERSION!r}"
        )
    if "klines" not in obj or "funding" not in obj:
        raise HarnessError("fixture must contain 'klines' and 'funding' arrays")
    klines = [_parse_kline(k) for k in obj["klines"]]
    funding = [_parse_funding(f) for f in obj["funding"]]
    return klines, funding


def load_fixture(
    path: Path,
) -> tuple[list[BinanceKline], list[FundingRate]]:
    """Read and parse a fixture file. The only I/O in the harness."""
    try:
        text = path.read_text()
    except OSError as e:
        raise HarnessError(f"cannot read fixture {path}: {e}") from e
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        raise HarnessError(f"fixture is not valid JSON: {e}") from e
    return parse_fixture(obj)


# ─── Pure probe execution ───────────────────────────────────────────────────


def _group_by_instrument(
    klines: Sequence[BinanceKline], funding: Sequence[FundingRate]
) -> dict[str, tuple[list[BinanceKline], list[FundingRate]]]:
    grouped: dict[str, tuple[list[BinanceKline], list[FundingRate]]] = {}
    for k in klines:
        grouped.setdefault(k.instrument, ([], []))[0].append(k)
    for f in funding:
        grouped.setdefault(f.instrument, ([], []))[1].append(f)
    return grouped


def run_probe(
    klines: Sequence[BinanceKline], funding: Sequence[FundingRate]
) -> dict[str, Any]:
    """Run the full probe over all instruments in the data. Pure; no I/O.

    Pipelines run per instrument (events are per-instrument); the resulting
    ForwardReturn series are pooled across instruments before gating, since
    the gate is a per-horizon statement about the strategy, not per-symbol.
    """
    grouped = _group_by_instrument(klines, funding)
    symbols = sorted(grouped)

    all_returns = []
    run_results: dict[str, RunResult] = {}
    for sym in symbols:
        ks, fs = grouped[sym]
        result = run_pipeline(ks, fs, pre_lock.VENUE_CODE, sym)
        run_results[sym] = result
        all_returns.extend(result.forward_returns)

    gate_result = evaluate_gates(all_returns)
    return _build_report(symbols, run_results, gate_result)


def _build_report(
    symbols: list[str],
    run_results: dict[str, RunResult],
    gate_result: ProbeGateResult,
) -> dict[str, Any]:
    events_by_horizon: dict[int, int] = {h: 0 for h in pre_lock.HORIZONS_DAYS}
    for rr in run_results.values():
        for fr in rr.forward_returns:
            events_by_horizon[fr.horizon_days] = (
                events_by_horizon.get(fr.horizon_days, 0) + 1
            )

    gate_verdict_by_horizon = {}
    for hr in gate_result.per_horizon:
        gate_verdict_by_horizon[hr.horizon_days] = {
            "passed": hr.passed,
            "statistical": {
                "status": hr.statistical.status.value,
                "reasons": list(hr.statistical.reasons),
                "train_events": hr.statistical.train_events,
                "oos_events": hr.statistical.oos_events,
                "oos_span_days": hr.statistical.oos_span_days,
                "train_sharpe": _s(hr.statistical.train_sharpe),
                "oos_sharpe": _s(hr.statistical.oos_sharpe),
                "oos_rolling_failures": hr.statistical.oos_rolling_failures,
            },
            "economic": {
                "status": hr.economic.status.value,
                "reasons": list(hr.economic.reasons),
                "mean_net_bps": _s(hr.economic.mean_net_bps),
                "median_net_bps": _s(hr.economic.median_net_bps),
                "win_rate": _s(hr.economic.win_rate),
                "cost_coverage": _s(hr.economic.cost_coverage),
                "final_3mo_net_bps": _s(hr.economic.final_3mo_net_bps),
                "final_3mo_event_count": hr.economic.final_3mo_event_count,
            },
        }

    skip_summary = {}
    data_quality_status = {}
    for sym, rr in run_results.items():
        s = rr.summary
        skip_summary[sym] = {
            "bars_total": s.bars_total,
            "sigma_windows_total": s.sigma_windows_total,
            "sigma_windows_valid": s.sigma_windows_valid,
            "sigma_windows_skipped_gap": s.sigma_windows_skipped_gap,
            "anchors_skipped_insufficient_history":
                s.anchors_skipped_insufficient_history,
            "percentile_events_total": s.percentile_events_total,
            "event_candidates": s.event_candidates,
            "events_flat": s.events_flat,
            "events_valid": s.events_valid,
            "events_skipped_missing_entry": s.events_skipped_missing_entry,
            "events_skipped_missing_exit": s.events_skipped_missing_exit,
            "events_skipped_funding_gap": s.events_skipped_funding_gap,
            "events_skipped_truncated_horizon":
                s.events_skipped_truncated_horizon,
            "forward_returns_built": s.forward_returns_built,
        }
        data_quality_status[sym] = {
            "data_quality_suspect": s.data_quality_suspect,
            "suspect_skip_rate": _s(s.suspect_skip_rate),
        }

    return {
        "schema_version": HARNESS_SCHEMA_VERSION,
        "symbols": symbols,
        "events_by_horizon": {str(h): n for h, n in sorted(events_by_horizon.items())},
        "gate_verdict_by_horizon": {
            str(h): v for h, v in sorted(gate_verdict_by_horizon.items())
        },
        "probe_pass": gate_result.probe_passed,
        "skip_summary": skip_summary,
        "data_quality_status": data_quality_status,
    }


def _s(x: Decimal | None) -> str | None:
    return None if x is None else str(x)


# ─── CLI ─────────────────────────────────────────────────────────────────────


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="vol_event_persistence probe (fixture-driven, DB-free)."
    )
    parser.add_argument("--fixture", required=True, type=Path,
                        help="path to a vol_event_fixture.v1 JSON file")
    parser.add_argument("--pretty", action="store_true",
                        help="indented JSON output")
    args = parser.parse_args(argv)

    try:
        klines, funding = load_fixture(args.fixture)
        report = run_probe(klines, funding)
    except HarnessError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        return 2

    report["fixture_path"] = str(args.fixture)
    indent = 2 if args.pretty else None
    print(json.dumps(report, indent=indent, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
