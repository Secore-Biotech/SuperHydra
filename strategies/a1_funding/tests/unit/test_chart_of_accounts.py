"""Unit tests for execution.ledger.chart_of_accounts.

Two test suites:

  1. Round-trip tests — every account-code constructor in
     fill_journal_writer must produce a code parse_account_code accepts
     and round-trips into the right ParsedAccountCode shape.
  2. Direct tests — malformed codes, edge cases, resolver dispatch.
"""
from __future__ import annotations

import pytest
from typing import Callable

from execution.ledger.chart_of_accounts import (
    ACCOUNT_CODE_VERSION,
    SUPPORTED_VERSIONS,
    AccountSpec,
    ParsedAccountCode,
    account_name_for,
    parse_account_code,
    spec_for_account_code,
)
from execution.ledger.fill_journal_writer import (
    cash_account_code,
    fee_expense_account_code,
    funding_expense_account_code,
    funding_income_account_code,
    margin_collateral_account_code,
    perp_position_account_code,
    spot_position_account_code,
)


# ─── Resolver fakes ──────────────────────────────────────────────────────


class _Resolvers:
    """Captures resolver calls for assertion."""
    def __init__(self):
        self.asset_calls: list[str] = []
        self.instrument_calls: list[str] = []
        self.asset_table = {"USDT": 100, "BTC": 101, "USDC": 102, "ETH": 103}
        self.instrument_table = {
            "BTCUSDT": 200,
            "BTCUSDT-SPOT": 201,
            "ETHUSDT": 202,
        }

    def asset_id(self, symbol: str) -> int:
        self.asset_calls.append(symbol)
        if symbol not in self.asset_table:
            raise KeyError(f"unknown asset symbol {symbol!r}")
        return self.asset_table[symbol]

    def instrument_id(self, code: str) -> int | None:
        self.instrument_calls.append(code)
        return self.instrument_table.get(code)


@pytest.fixture
def resolvers() -> _Resolvers:
    return _Resolvers()


# ─── Round-trip tests (constructor → parser) ──────────────────────────────


class TestParseRoundTrip:
    def test_cash(self):
        code = cash_account_code(1, 1, 1, "USDT")
        p = parse_account_code(code)
        assert p.version == "v1"
        assert p.subtype == "cash"
        assert p.account_type == "asset"
        assert p.portfolio_id == 1
        assert p.strategy_id == 1
        assert p.registry_account_id == 1
        assert p.asset_symbol == "USDT"
        assert p.instrument_code is None
        assert p.perp_side is None

    def test_cash_distinct_dimensions(self):
        code = cash_account_code(7, 3, 42, "USDC")
        p = parse_account_code(code)
        assert p.portfolio_id == 7
        assert p.strategy_id == 3
        assert p.registry_account_id == 42
        assert p.asset_symbol == "USDC"

    def test_margin_collateral(self):
        code = margin_collateral_account_code(1, 1, 1, "USDT")
        p = parse_account_code(code)
        assert p.subtype == "margin_collateral"
        assert p.account_type == "asset"
        assert p.asset_symbol == "USDT"
        assert p.instrument_code is None

    def test_spot_position(self):
        code = spot_position_account_code(1, 1, 1, "BTCUSDT-SPOT")
        p = parse_account_code(code)
        assert p.subtype == "position"
        assert p.account_type == "asset"
        assert p.instrument_code == "BTCUSDT-SPOT"
        assert p.asset_symbol is None
        assert p.perp_side is None

    def test_perp_position_long(self):
        code = perp_position_account_code(1, 1, 1, "BTCUSDT", "long")
        p = parse_account_code(code)
        assert p.subtype == "position"
        assert p.instrument_code == "BTCUSDT"
        assert p.perp_side == "long"

    def test_perp_position_short(self):
        code = perp_position_account_code(1, 1, 1, "BTCUSDT", "short")
        p = parse_account_code(code)
        assert p.perp_side == "short"

    def test_perp_long_short_distinguished(self):
        long_p = parse_account_code(perp_position_account_code(1, 1, 1, "BTCUSDT", "long"))
        short_p = parse_account_code(perp_position_account_code(1, 1, 1, "BTCUSDT", "short"))
        assert long_p != short_p
        assert long_p.perp_side == "long"
        assert short_p.perp_side == "short"

    def test_fee_expense(self):
        code = fee_expense_account_code(1, 1)
        p = parse_account_code(code)
        assert p.subtype == "fee_expense"
        assert p.account_type == "expense"
        assert p.portfolio_id == 1
        assert p.strategy_id == 1
        assert p.registry_account_id is None
        assert p.asset_symbol is None
        assert p.instrument_code is None

    def test_funding_income(self):
        code = funding_income_account_code(1, 1, "BTCUSDT")
        p = parse_account_code(code)
        assert p.subtype == "funding_income"
        assert p.account_type == "income"
        assert p.instrument_code == "BTCUSDT"
        assert p.registry_account_id is None
        assert p.asset_symbol is None

    def test_funding_expense(self):
        code = funding_expense_account_code(1, 1, "BTCUSDT")
        p = parse_account_code(code)
        assert p.subtype == "funding_expense"
        assert p.account_type == "expense"
        assert p.instrument_code == "BTCUSDT"


# ─── Negative tests (malformed codes) ─────────────────────────────────────


class TestParseRejects:
    def test_empty_string(self):
        with pytest.raises(ValueError, match="non-empty"):
            parse_account_code("")

    def test_none(self):
        with pytest.raises(ValueError, match="non-empty"):
            parse_account_code(None)  # type: ignore[arg-type]

    def test_unsupported_version_v2(self):
        # CRITICAL: no silent fallback. v2 must be explicitly added.
        with pytest.raises(ValueError, match="unsupported account-code version"):
            parse_account_code("v2:cash:p1:s1:a1:USDT")

    def test_unsupported_version_v0(self):
        with pytest.raises(ValueError, match="unsupported account-code version"):
            parse_account_code("v0:cash:p1:s1:a1:USDT")

    def test_no_version_prefix(self):
        with pytest.raises(ValueError, match="unsupported account-code version"):
            parse_account_code("cash:p1:s1:a1:USDT")

    def test_unknown_subtype(self):
        with pytest.raises(ValueError, match="unknown subtype"):
            parse_account_code("v1:gambling:p1:s1:a1:USDT")

    def test_too_few_parts(self):
        with pytest.raises(ValueError, match="too few parts"):
            parse_account_code("v1:cash")

    def test_cash_wrong_part_count(self):
        # cash must have 6 parts; 5 is wrong (missing asset)
        with pytest.raises(ValueError, match="cash: expected 6 parts"):
            parse_account_code("v1:cash:p1:s1:a1")
        # 7 is also wrong (extra)
        with pytest.raises(ValueError, match="cash: expected 6 parts"):
            parse_account_code("v1:cash:p1:s1:a1:USDT:extra")

    def test_position_wrong_part_count(self):
        # 5 parts is too few (no instrument)
        with pytest.raises(ValueError, match="position: expected 6"):
            parse_account_code("v1:position:p1:s1:a1")
        # 8 parts is too many
        with pytest.raises(ValueError, match="position: expected 6"):
            parse_account_code("v1:position:p1:s1:a1:BTCUSDT:long:extra")

    def test_perp_position_invalid_side(self):
        with pytest.raises(ValueError, match="long.*short"):
            parse_account_code("v1:position:p1:s1:a1:BTCUSDT:flat")

    def test_fee_expense_with_extra_parts(self):
        with pytest.raises(ValueError, match="fee_expense: expected 4"):
            parse_account_code("v1:fee_expense:p1:s1:extra")

    def test_funding_wrong_part_count(self):
        with pytest.raises(ValueError, match="funding_income: expected 5"):
            parse_account_code("v1:funding_income:p1:s1")
        with pytest.raises(ValueError, match="funding_expense: expected 5"):
            parse_account_code("v1:funding_expense:p1:s1:BTCUSDT:extra")

    def test_invalid_portfolio_id(self):
        with pytest.raises(ValueError, match="digits expected"):
            parse_account_code("v1:cash:portfolio:s1:a1:USDT")

    def test_missing_p_prefix_on_portfolio(self):
        # parts[2] should start with 'p'
        with pytest.raises(ValueError, match="starting with 'p'"):
            parse_account_code("v1:cash:1:s1:a1:USDT")

    def test_missing_s_prefix_on_strategy(self):
        with pytest.raises(ValueError, match="starting with 's'"):
            parse_account_code("v1:cash:p1:1:a1:USDT")

    def test_missing_a_prefix_on_account(self):
        with pytest.raises(ValueError, match="starting with 'a'"):
            parse_account_code("v1:cash:p1:s1:1:USDT")

    def test_negative_int_rejected(self):
        # "-1" doesn't pass isdigit() so this fails on digits-expected
        with pytest.raises(ValueError, match="digits expected"):
            parse_account_code("v1:cash:p-1:s1:a1:USDT")

    def test_empty_int_rejected(self):
        # "p" with no digits
        with pytest.raises(ValueError, match="digits expected"):
            parse_account_code("v1:cash:p:s1:a1:USDT")


# ─── account_name_for ─────────────────────────────────────────────────────


class TestAccountNameFor:
    def test_cash_format(self):
        p = parse_account_code(cash_account_code(1, 2, 3, "USDT"))
        assert account_name_for(p) == \
            "Cash (USDT) — portfolio 1, strategy 2, account 3"

    def test_margin_collateral_format(self):
        p = parse_account_code(margin_collateral_account_code(1, 2, 3, "USDT"))
        assert account_name_for(p) == \
            "Margin collateral (USDT) — portfolio 1, strategy 2, account 3"

    def test_spot_position_format(self):
        p = parse_account_code(spot_position_account_code(1, 2, 3, "BTCUSDT-SPOT"))
        assert account_name_for(p) == \
            "Spot position BTCUSDT-SPOT — portfolio 1, strategy 2, account 3"

    def test_perp_position_long_format(self):
        p = parse_account_code(perp_position_account_code(1, 2, 3, "BTCUSDT", "long"))
        assert account_name_for(p) == \
            "Perp position BTCUSDT (long) — portfolio 1, strategy 2, account 3"

    def test_perp_position_short_format(self):
        p = parse_account_code(perp_position_account_code(1, 2, 3, "BTCUSDT", "short"))
        assert account_name_for(p) == \
            "Perp position BTCUSDT (short) — portfolio 1, strategy 2, account 3"

    def test_fee_expense_format(self):
        p = parse_account_code(fee_expense_account_code(1, 2))
        assert account_name_for(p) == "Fee expense — portfolio 1, strategy 2"

    def test_funding_income_format(self):
        p = parse_account_code(funding_income_account_code(1, 2, "BTCUSDT"))
        assert account_name_for(p) == \
            "Funding income BTCUSDT — portfolio 1, strategy 2"

    def test_funding_expense_format(self):
        p = parse_account_code(funding_expense_account_code(1, 2, "BTCUSDT"))
        assert account_name_for(p) == \
            "Funding expense BTCUSDT — portfolio 1, strategy 2"

    def test_name_deterministic(self):
        # Same parsed → byte-equal name. Audit trails depend on this.
        p1 = parse_account_code(cash_account_code(1, 1, 1, "USDT"))
        p2 = parse_account_code(cash_account_code(1, 1, 1, "USDT"))
        assert account_name_for(p1) == account_name_for(p2)


# ─── spec_for_account_code ────────────────────────────────────────────────


class TestSpecForAccountCode:
    def test_cash_resolves_asset_only(self, resolvers):
        spec = spec_for_account_code(
            cash_account_code(1, 1, 1, "USDT"),
            asset_id_resolver=resolvers.asset_id,
            instrument_id_resolver=resolvers.instrument_id,
        )
        assert spec.account_code == "v1:cash:p1:s1:a1:USDT"
        assert spec.account_type == "asset"
        assert spec.account_subtype == "cash"
        assert spec.portfolio_id == 1
        assert spec.strategy_id == 1
        assert spec.registry_account_id == 1
        assert spec.asset_id == 100  # USDT id from fake table
        assert spec.instrument_id is None
        # Resolver assertion: asset queried, instrument NOT queried
        assert resolvers.asset_calls == ["USDT"]
        assert resolvers.instrument_calls == []

    def test_margin_collateral_resolves_asset_only(self, resolvers):
        spec = spec_for_account_code(
            margin_collateral_account_code(1, 1, 1, "USDT"),
            asset_id_resolver=resolvers.asset_id,
            instrument_id_resolver=resolvers.instrument_id,
        )
        assert spec.account_subtype == "margin_collateral"
        assert spec.asset_id == 100
        assert spec.instrument_id is None

    def test_spot_position_resolves_instrument_only(self, resolvers):
        spec = spec_for_account_code(
            spot_position_account_code(1, 1, 1, "BTCUSDT-SPOT"),
            asset_id_resolver=resolvers.asset_id,
            instrument_id_resolver=resolvers.instrument_id,
        )
        assert spec.account_subtype == "position"
        assert spec.instrument_id == 201
        assert spec.asset_id is None
        assert resolvers.asset_calls == []
        assert resolvers.instrument_calls == ["BTCUSDT-SPOT"]

    def test_perp_long_resolves_instrument_only(self, resolvers):
        spec = spec_for_account_code(
            perp_position_account_code(1, 1, 1, "BTCUSDT", "long"),
            asset_id_resolver=resolvers.asset_id,
            instrument_id_resolver=resolvers.instrument_id,
        )
        assert spec.instrument_id == 200
        assert spec.asset_id is None

    def test_fee_expense_invokes_no_resolvers(self, resolvers):
        spec = spec_for_account_code(
            fee_expense_account_code(1, 1),
            asset_id_resolver=resolvers.asset_id,
            instrument_id_resolver=resolvers.instrument_id,
        )
        assert spec.account_type == "expense"
        assert spec.account_subtype == "fee_expense"
        assert spec.asset_id is None
        assert spec.instrument_id is None
        assert spec.registry_account_id is None
        assert resolvers.asset_calls == []
        assert resolvers.instrument_calls == []

    def test_funding_income_resolves_instrument_only(self, resolvers):
        spec = spec_for_account_code(
            funding_income_account_code(1, 1, "BTCUSDT"),
            asset_id_resolver=resolvers.asset_id,
            instrument_id_resolver=resolvers.instrument_id,
        )
        assert spec.account_type == "income"
        assert spec.instrument_id == 200
        assert spec.asset_id is None

    def test_funding_expense_resolves_instrument_only(self, resolvers):
        spec = spec_for_account_code(
            funding_expense_account_code(1, 1, "BTCUSDT"),
            asset_id_resolver=resolvers.asset_id,
            instrument_id_resolver=resolvers.instrument_id,
        )
        assert spec.account_type == "expense"
        assert spec.account_subtype == "funding_expense"
        assert spec.instrument_id == 200

    def test_account_name_set_from_parsed(self, resolvers):
        spec = spec_for_account_code(
            cash_account_code(1, 1, 1, "USDT"),
            asset_id_resolver=resolvers.asset_id,
            instrument_id_resolver=resolvers.instrument_id,
        )
        assert spec.account_name == \
            "Cash (USDT) — portfolio 1, strategy 2, account 3".replace(
                "1, strategy 2, account 3", "1, strategy 1, account 1"
            )


# ─── Resolver error handling ──────────────────────────────────────────────


class TestResolverErrors:
    def test_asset_resolver_returns_zero_rejected(self):
        def bad(symbol: str) -> int:
            return 0
        with pytest.raises(ValueError, match="non-positive id"):
            spec_for_account_code(
                cash_account_code(1, 1, 1, "USDT"),
                asset_id_resolver=bad,
                instrument_id_resolver=lambda c: 1,
            )

    def test_asset_resolver_returns_negative_rejected(self):
        def bad(symbol: str) -> int:
            return -5
        with pytest.raises(ValueError, match="non-positive id"):
            spec_for_account_code(
                cash_account_code(1, 1, 1, "USDT"),
                asset_id_resolver=bad,
                instrument_id_resolver=lambda c: 1,
            )

    def test_instrument_resolver_returning_none_rejected(self):
        def absent(code: str) -> int | None:
            return None
        with pytest.raises(ValueError, match="returned None for"):
            spec_for_account_code(
                spot_position_account_code(1, 1, 1, "UNKNOWN"),
                asset_id_resolver=lambda s: 1,
                instrument_id_resolver=absent,
            )

    def test_instrument_resolver_returning_zero_rejected(self):
        def zero(code: str) -> int:
            return 0
        with pytest.raises(ValueError, match="non-positive id"):
            spec_for_account_code(
                spot_position_account_code(1, 1, 1, "BTCUSDT-SPOT"),
                asset_id_resolver=lambda s: 1,
                instrument_id_resolver=zero,
            )

    def test_resolver_propagates_keyerror(self, resolvers):
        # Resolver raises KeyError for unknown symbol — propagates up
        with pytest.raises(KeyError, match="UNKNOWN"):
            spec_for_account_code(
                cash_account_code(1, 1, 1, "UNKNOWN"),
                asset_id_resolver=resolvers.asset_id,
                instrument_id_resolver=resolvers.instrument_id,
            )


# ─── Reproducibility ──────────────────────────────────────────────────────


class TestReproducibility:
    def test_parse_reproducible(self):
        code = cash_account_code(1, 1, 1, "USDT")
        p1 = parse_account_code(code)
        p2 = parse_account_code(code)
        assert p1 == p2

    def test_spec_reproducible(self, resolvers):
        code = perp_position_account_code(1, 1, 1, "BTCUSDT", "short")
        s1 = spec_for_account_code(
            code,
            asset_id_resolver=resolvers.asset_id,
            instrument_id_resolver=resolvers.instrument_id,
        )
        s2 = spec_for_account_code(
            code,
            asset_id_resolver=resolvers.asset_id,
            instrument_id_resolver=resolvers.instrument_id,
        )
        assert s1 == s2


# ─── Constants exported are sane ──────────────────────────────────────────


class TestModuleConstants:
    def test_account_code_version_is_v1(self):
        assert ACCOUNT_CODE_VERSION == "v1"

    def test_supported_versions_is_v1_only(self):
        assert SUPPORTED_VERSIONS == ("v1",)
