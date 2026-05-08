"""Unit tests for execution.ledger.fill_journal_writer.

Pure-function module — all tests run without a DB. The DB-side writer
(Day 11) gets its own integration tests.
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from execution.ledger.fill_journal_writer import (
    ACCOUNT_CODE_VERSION,
    JOURNAL_DRAFT_SCHEMA_VERSION,
    FillRecord,
    JournalDraft,
    LedgerEntryDraft,
    build_trade_journal,
    cash_account_code,
    compute_fill_journal_source_hash,
    fee_expense_account_code,
    funding_expense_account_code,
    funding_income_account_code,
    margin_collateral_account_code,
    perp_position_account_code,
    spot_position_account_code,
)


UTC = timezone.utc


# ─── Helpers ──────────────────────────────────────────────────────────────


def _spot_fill(**overrides) -> FillRecord:
    base = dict(
        fill_uuid="01900000-0000-7000-8000-000000000001",
        fill_content_hash="a" * 64,
        portfolio_id=1, strategy_id=1, account_id=1,
        instrument_id=10, instrument_code="BTCUSDT-SPOT",
        instrument_type="spot",
        base_asset_symbol="BTC", quote_asset_symbol="USDT",
        side="buy",
        quantity=Decimal("0.01"), price=Decimal("100000"),
        fee_usd=Decimal("0.50"),
        fill_environment="SHADOW",
        filled_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    base.update(overrides)
    return FillRecord(**base)


def _perp_fill(**overrides) -> FillRecord:
    base = dict(
        instrument_code="BTCUSDT",
        instrument_type="perp",
        side="sell",
    )
    base.update(overrides)
    return _spot_fill(**base)


# ─── Account-code tests ───────────────────────────────────────────────────


class TestAccountCodes:
    def test_v1_prefix_on_every_helper(self):
        codes = [
            cash_account_code(1, 1, 1, "USDT"),
            margin_collateral_account_code(1, 1, 1, "USDT"),
            spot_position_account_code(1, 1, 1, "BTCUSDT-SPOT"),
            perp_position_account_code(1, 1, 1, "BTCUSDT", "long"),
            perp_position_account_code(1, 1, 1, "BTCUSDT", "short"),
            fee_expense_account_code(1, 1),
            funding_income_account_code(1, 1, "BTCUSDT"),
            funding_expense_account_code(1, 1, "BTCUSDT"),
        ]
        for c in codes:
            assert c.startswith(f"{ACCOUNT_CODE_VERSION}:"), c

    def test_cash_format(self):
        assert cash_account_code(1, 1, 1, "USDT") == "v1:cash:p1:s1:a1:USDT"
        assert cash_account_code(7, 3, 42, "USDC") == "v1:cash:p7:s3:a42:USDC"

    def test_margin_format(self):
        assert (margin_collateral_account_code(1, 1, 1, "USDT")
                == "v1:margin_collateral:p1:s1:a1:USDT")

    def test_spot_position_no_side_suffix(self):
        # Spot positions are naturally long; no :long suffix
        c = spot_position_account_code(1, 1, 1, "BTCUSDT-SPOT")
        assert c == "v1:position:p1:s1:a1:BTCUSDT-SPOT"
        assert ":long" not in c
        assert ":short" not in c

    def test_perp_position_requires_side_suffix(self):
        long_c = perp_position_account_code(1, 1, 1, "BTCUSDT", "long")
        short_c = perp_position_account_code(1, 1, 1, "BTCUSDT", "short")
        assert long_c == "v1:position:p1:s1:a1:BTCUSDT:long"
        assert short_c == "v1:position:p1:s1:a1:BTCUSDT:short"
        assert long_c != short_c

    def test_perp_position_invalid_side_rejected(self):
        with pytest.raises(ValueError, match="side must be"):
            perp_position_account_code(1, 1, 1, "BTCUSDT", "flat")

    def test_fee_expense_strategy_scoped(self):
        # Fee expense is portfolio+strategy scoped, no instrument
        assert fee_expense_account_code(1, 1) == "v1:fee_expense:p1:s1"
        assert fee_expense_account_code(2, 1) != fee_expense_account_code(1, 1)

    def test_funding_accounts_carry_instrument(self):
        # Funding income/expense are per-instrument so we can attribute
        # P&L per instrument cleanly later
        assert (funding_income_account_code(1, 1, "BTCUSDT")
                == "v1:funding_income:p1:s1:BTCUSDT")
        assert (funding_expense_account_code(1, 1, "BTCUSDT")
                == "v1:funding_expense:p1:s1:BTCUSDT")

    def test_codes_distinct_across_dimensions(self):
        # Two portfolios, same strategy + asset → distinct codes
        c1 = cash_account_code(1, 1, 1, "USDT")
        c2 = cash_account_code(2, 1, 1, "USDT")
        assert c1 != c2

        # Two accounts under same portfolio+strategy → distinct codes
        c3 = cash_account_code(1, 1, 1, "USDT")
        c4 = cash_account_code(1, 1, 2, "USDT")
        assert c3 != c4


# ─── FillRecord validation ───────────────────────────────────────────────


class TestFillRecordValidation:
    def test_valid_fill_constructs(self):
        f = _spot_fill()
        assert f.quantity == Decimal("0.01")

    def test_zero_quantity_rejected(self):
        with pytest.raises(ValueError, match="quantity must be > 0"):
            _spot_fill(quantity=Decimal("0"))

    def test_negative_quantity_rejected(self):
        with pytest.raises(ValueError, match="quantity must be > 0"):
            _spot_fill(quantity=Decimal("-0.01"))

    def test_zero_price_rejected(self):
        with pytest.raises(ValueError, match="price must be > 0"):
            _spot_fill(price=Decimal("0"))

    def test_negative_fee_rejected(self):
        with pytest.raises(ValueError, match="fee_usd must be"):
            _spot_fill(fee_usd=Decimal("-0.01"))

    def test_zero_fee_accepted(self):
        # Zero-fee execution is a real edge case (rebates can produce it,
        # or test fixtures explicitly turn fees off).
        f = _spot_fill(fee_usd=Decimal("0"))
        assert f.fee_usd == 0

    def test_naive_datetime_rejected(self):
        with pytest.raises(ValueError, match="tz-aware UTC"):
            _spot_fill(filled_at=datetime(2026, 1, 1, 12, 0, 0))

    def test_non_utc_tz_rejected(self):
        from datetime import timezone, timedelta
        plus_5 = timezone(timedelta(hours=5))
        with pytest.raises(ValueError, match="tz-aware UTC"):
            _spot_fill(filled_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=plus_5))

    def test_invalid_instrument_type_rejected(self):
        with pytest.raises(ValueError, match="instrument_type"):
            _spot_fill(instrument_type="option")

    def test_invalid_side_rejected(self):
        with pytest.raises(ValueError, match="side"):
            _spot_fill(side="flat")


# ─── LedgerEntryDraft validation ──────────────────────────────────────────


class TestLedgerEntryDraftValidation:
    def _entry(self, **overrides) -> LedgerEntryDraft:
        base = dict(
            debit_credit="debit",
            ledger_account_code="v1:cash:p1:s1:a1:USDT",
            asset_symbol="USDT",
            instrument_code=None,
            quantity=Decimal("100"),
            amount_usd=Decimal("100"),
            memo="test entry",
        )
        base.update(overrides)
        return LedgerEntryDraft(**base)

    def test_valid_entry_constructs(self):
        e = self._entry()
        assert e.debit_credit == "debit"

    def test_invalid_dr_cr_rejected(self):
        with pytest.raises(ValueError, match="debit_credit"):
            self._entry(debit_credit="dr")

    def test_zero_amount_rejected(self):
        with pytest.raises(ValueError, match="amount_usd must be > 0"):
            self._entry(amount_usd=Decimal("0"))

    def test_negative_amount_rejected(self):
        with pytest.raises(ValueError, match="amount_usd must be > 0"):
            self._entry(amount_usd=Decimal("-1"))

    def test_zero_quantity_rejected_when_present(self):
        with pytest.raises(ValueError, match="quantity must be > 0"):
            self._entry(quantity=Decimal("0"))

    def test_none_quantity_allowed(self):
        # Pure cash entries (e.g. fees) carry no quantity
        e = self._entry(quantity=None)
        assert e.quantity is None

    def test_account_code_must_have_v1_prefix(self):
        with pytest.raises(ValueError, match="v1:"):
            self._entry(ledger_account_code="cash:p1:s1:a1:USDT")

    def test_account_code_must_have_v1_prefix_v2_rejected(self):
        # v2 codes are explicitly rejected by Day 9; once we add v2
        # support, this test will need updating
        with pytest.raises(ValueError, match="v1:"):
            self._entry(ledger_account_code="v2:cash:p1:s1:a1:USDT")

    def test_empty_memo_rejected(self):
        with pytest.raises(ValueError, match="memo"):
            self._entry(memo="")
        with pytest.raises(ValueError, match="memo"):
            self._entry(memo="   ")


# ─── JournalDraft balance enforcement ─────────────────────────────────────


class TestJournalDraftBalance:
    def _balanced_pair(self) -> tuple[LedgerEntryDraft, LedgerEntryDraft]:
        return (
            LedgerEntryDraft(
                debit_credit="debit",
                ledger_account_code="v1:cash:p1:s1:a1:USDT",
                asset_symbol="USDT", instrument_code=None,
                quantity=Decimal("100"), amount_usd=Decimal("100"),
                memo="dr",
            ),
            LedgerEntryDraft(
                debit_credit="credit",
                ledger_account_code="v1:cash:p1:s1:a1:USDT",
                asset_symbol="USDT", instrument_code=None,
                quantity=Decimal("100"), amount_usd=Decimal("100"),
                memo="cr",
            ),
        )

    def _draft(self, entries) -> JournalDraft:
        return JournalDraft(
            schema_version=JOURNAL_DRAFT_SCHEMA_VERSION,
            journal_type="trade", portfolio_id=1, strategy_id=1,
            journal_at=datetime(2026, 1, 1, tzinfo=UTC),
            source_type="fill", source_namespace="global",
            source_id="test-fill-uuid", source_hash="abc123",
            description="test", created_by="unit_test",
            entries=tuple(entries),
        )

    def test_balanced_pair_constructs(self):
        d = self._draft(self._balanced_pair())
        assert len(d.entries) == 2

    def test_imbalanced_rejected(self):
        # 100 DR vs 99 CR
        bad = (
            LedgerEntryDraft(
                debit_credit="debit",
                ledger_account_code="v1:cash:p1:s1:a1:USDT",
                asset_symbol="USDT", instrument_code=None,
                quantity=Decimal("100"), amount_usd=Decimal("100"),
                memo="dr",
            ),
            LedgerEntryDraft(
                debit_credit="credit",
                ledger_account_code="v1:cash:p1:s1:a1:USDT",
                asset_symbol="USDT", instrument_code=None,
                quantity=Decimal("99"), amount_usd=Decimal("99"),
                memo="cr",
            ),
        )
        with pytest.raises(ValueError, match="not balanced"):
            self._draft(bad)

    def test_single_entry_rejected(self):
        single = (self._balanced_pair()[0],)
        with pytest.raises(ValueError, match="at least 2 entries"):
            self._draft(single)

    def test_two_debits_rejected(self):
        # Two debits, no credits — definitely not balanced
        bad = (
            self._balanced_pair()[0],
            LedgerEntryDraft(
                debit_credit="debit",
                ledger_account_code="v1:cash:p1:s1:a1:USDT",
                asset_symbol="USDT", instrument_code=None,
                quantity=Decimal("100"), amount_usd=Decimal("100"),
                memo="dr2",
            ),
        )
        with pytest.raises(ValueError, match="not balanced"):
            self._draft(bad)

    def test_naive_datetime_rejected(self):
        with pytest.raises(ValueError, match="tz-aware UTC"):
            JournalDraft(
                schema_version=JOURNAL_DRAFT_SCHEMA_VERSION,
                journal_type="trade", portfolio_id=1, strategy_id=1,
                journal_at=datetime(2026, 1, 1),  # no tz
                source_type="fill", source_namespace="global",
                source_id="f", source_hash="h",
                description="d", created_by="u",
                entries=self._balanced_pair(),
            )

    def test_empty_source_hash_rejected(self):
        with pytest.raises(ValueError, match="source_hash"):
            JournalDraft(
                schema_version=JOURNAL_DRAFT_SCHEMA_VERSION,
                journal_type="trade", portfolio_id=1, strategy_id=1,
                journal_at=datetime(2026, 1, 1, tzinfo=UTC),
                source_type="fill", source_namespace="global",
                source_id="f", source_hash="",
                description="d", created_by="u",
                entries=self._balanced_pair(),
            )

    def test_schema_version_mismatch_rejected(self):
        with pytest.raises(ValueError, match="schema_version"):
            JournalDraft(
                schema_version="journal_draft.v1",  # wrong
                journal_type="trade", portfolio_id=1, strategy_id=1,
                journal_at=datetime(2026, 1, 1, tzinfo=UTC),
                source_type="fill", source_namespace="global",
                source_id="f", source_hash="h",
                description="d", created_by="u",
                entries=self._balanced_pair(),
            )


# ─── compute_fill_journal_source_hash ─────────────────────────────────────


class TestSourceHash:
    def test_deterministic(self):
        f1 = _spot_fill()
        f2 = _spot_fill()
        assert (compute_fill_journal_source_hash(f1)
                == compute_fill_journal_source_hash(f2))

    def test_changes_with_fill_uuid(self):
        f1 = _spot_fill(fill_uuid="01900000-0000-7000-8000-000000000001")
        f2 = _spot_fill(fill_uuid="01900000-0000-7000-8000-000000000002")
        assert (compute_fill_journal_source_hash(f1)
                != compute_fill_journal_source_hash(f2))

    def test_changes_with_quantity(self):
        f1 = _spot_fill(quantity=Decimal("0.01"))
        f2 = _spot_fill(quantity=Decimal("0.02"))
        assert (compute_fill_journal_source_hash(f1)
                != compute_fill_journal_source_hash(f2))

    def test_changes_with_price(self):
        f1 = _spot_fill(price=Decimal("100000"))
        f2 = _spot_fill(price=Decimal("100001"))
        assert (compute_fill_journal_source_hash(f1)
                != compute_fill_journal_source_hash(f2))

    def test_changes_with_fee(self):
        f1 = _spot_fill(fee_usd=Decimal("0.50"))
        f2 = _spot_fill(fee_usd=Decimal("0.51"))
        assert (compute_fill_journal_source_hash(f1)
                != compute_fill_journal_source_hash(f2))

    def test_changes_with_side(self):
        f1 = _spot_fill(side="buy")
        f2 = _spot_fill(side="sell")
        assert (compute_fill_journal_source_hash(f1)
                != compute_fill_journal_source_hash(f2))

    def test_changes_with_instrument_type(self):
        f1 = _spot_fill()
        f2 = _spot_fill(instrument_type="perp", instrument_code="BTCUSDT")
        assert (compute_fill_journal_source_hash(f1)
                != compute_fill_journal_source_hash(f2))

    def test_changes_with_environment(self):
        # SHADOW vs LIVE: same fill data but different env produces a
        # different hash. We don't want a SHADOW journal mis-resolved
        # against a LIVE fill or vice versa.
        f1 = _spot_fill(fill_environment="SHADOW")
        f2 = _spot_fill(fill_environment="LIVE")
        assert (compute_fill_journal_source_hash(f1)
                != compute_fill_journal_source_hash(f2))

    def test_independent_of_filled_at(self):
        # filled_at is intentionally not in the hash — re-replays of the
        # same fill at later wall-clock times should resolve to the same
        # journal. The fill's own content_hash is the source of truth.
        f1 = _spot_fill(filled_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC))
        f2 = _spot_fill(filled_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC))
        assert (compute_fill_journal_source_hash(f1)
                == compute_fill_journal_source_hash(f2))


# ─── build_trade_journal: spot ────────────────────────────────────────────


class TestBuildSpotTradeJournal:
    def test_buy_creates_4_entries(self):
        f = _spot_fill(side="buy")
        d = build_trade_journal(f, created_by="unit_test")
        # 2 trade entries + 2 fee entries
        assert len(d.entries) == 4

    def test_buy_zero_fee_creates_2_entries(self):
        f = _spot_fill(side="buy", fee_usd=Decimal("0"))
        d = build_trade_journal(f, created_by="unit_test")
        assert len(d.entries) == 2

    def test_buy_balanced(self):
        f = _spot_fill(side="buy")
        d = build_trade_journal(f, created_by="unit_test")
        debits = sum(e.amount_usd for e in d.entries if e.debit_credit == "debit")
        credits = sum(e.amount_usd for e in d.entries if e.debit_credit == "credit")
        assert debits == credits

    def test_buy_dr_position_cr_cash(self):
        f = _spot_fill(side="buy")
        d = build_trade_journal(f, created_by="unit_test")
        # First entry should be DR position
        assert d.entries[0].debit_credit == "debit"
        assert "position" in d.entries[0].ledger_account_code
        assert d.entries[0].asset_symbol == "BTC"
        # Second entry should be CR cash
        assert d.entries[1].debit_credit == "credit"
        assert "cash" in d.entries[1].ledger_account_code

    def test_sell_dr_cash_cr_position(self):
        f = _spot_fill(side="sell")
        d = build_trade_journal(f, created_by="unit_test")
        # First DR cash, then CR position
        assert d.entries[0].debit_credit == "debit"
        assert "cash" in d.entries[0].ledger_account_code
        assert d.entries[1].debit_credit == "credit"
        assert "position" in d.entries[1].ledger_account_code

    def test_position_account_uses_instrument_code(self):
        f = _spot_fill(side="buy")
        d = build_trade_journal(f, created_by="unit_test")
        position_entry = d.entries[0]
        assert position_entry.ledger_account_code == \
            "v1:position:p1:s1:a1:BTCUSDT-SPOT"

    def test_notional_matches_quantity_times_price(self):
        f = _spot_fill(quantity=Decimal("0.01"), price=Decimal("100000"))
        d = build_trade_journal(f, created_by="unit_test")
        assert d.entries[0].amount_usd == Decimal("1000")
        assert d.entries[1].amount_usd == Decimal("1000")

    def test_fee_entries_paid_in_quote_asset(self):
        f = _spot_fill(side="buy", fee_usd=Decimal("0.50"))
        d = build_trade_journal(f, created_by="unit_test")
        fee_dr, fee_cr = d.entries[2], d.entries[3]
        assert fee_dr.debit_credit == "debit"
        assert "fee_expense" in fee_dr.ledger_account_code
        assert fee_dr.asset_symbol == "USDT"
        assert fee_cr.debit_credit == "credit"
        assert "cash" in fee_cr.ledger_account_code


# ─── build_trade_journal: perp ────────────────────────────────────────────


class TestBuildPerpTradeJournal:
    def test_perp_creates_4_entries(self):
        f = _perp_fill()
        d = build_trade_journal(f, created_by="unit_test")
        assert len(d.entries) == 4

    def test_perp_zero_fee_creates_2_entries(self):
        f = _perp_fill(fee_usd=Decimal("0"))
        d = build_trade_journal(f, created_by="unit_test")
        assert len(d.entries) == 2

    def test_perp_no_position_ledger_entry(self):
        # CRITICAL: perp fill must NOT emit a position ledger entry.
        # Position-as-inventory lives in positions.position_lots, not
        # in accounting.ledger_entries.
        f = _perp_fill()
        d = build_trade_journal(f, created_by="unit_test")
        for e in d.entries:
            # No ledger account code should match the perp position pattern
            assert "v1:position:" not in e.ledger_account_code or \
                   "spot" in e.ledger_account_code.lower(), \
                   f"perp journal must not contain position entry, got {e.ledger_account_code}"

    def test_perp_balanced(self):
        f = _perp_fill()
        d = build_trade_journal(f, created_by="unit_test")
        debits = sum(e.amount_usd for e in d.entries if e.debit_credit == "debit")
        credits = sum(e.amount_usd for e in d.entries if e.debit_credit == "credit")
        assert debits == credits

    def test_perp_dr_margin_cr_cash(self):
        f = _perp_fill()
        d = build_trade_journal(f, created_by="unit_test")
        assert d.entries[0].debit_credit == "debit"
        assert "margin_collateral" in d.entries[0].ledger_account_code
        assert d.entries[1].debit_credit == "credit"
        assert "cash" in d.entries[1].ledger_account_code

    def test_perp_buy_and_sell_produce_same_journal_shape(self):
        # Per design: perp side determines lot side, not journal shape
        buy = build_trade_journal(_perp_fill(side="buy"), created_by="t")
        sell = build_trade_journal(_perp_fill(side="sell"), created_by="t")
        assert len(buy.entries) == len(sell.entries)
        # Same DR/CR pattern, account codes
        for be, se in zip(buy.entries, sell.entries):
            assert be.debit_credit == se.debit_credit
            assert be.ledger_account_code == se.ledger_account_code
            assert be.amount_usd == se.amount_usd

    def test_perp_margin_amount_equals_notional(self):
        # Day 9 simplification: full notional posted as margin. Real
        # exchanges use leverage and margin tiers; that's a Day 14+
        # refinement. For the keystone, full-notional margin keeps the
        # accounting simple and obviously balanced.
        f = _perp_fill(quantity=Decimal("0.01"), price=Decimal("100000"))
        d = build_trade_journal(f, created_by="unit_test")
        margin_entry = d.entries[0]
        assert margin_entry.amount_usd == Decimal("1000")


# ─── build_trade_journal: shared invariants ───────────────────────────────


class TestBuildTradeJournalInvariants:
    def test_journal_at_matches_fill_filled_at(self):
        ts = datetime(2026, 3, 15, 10, 30, 0, tzinfo=UTC)
        f = _spot_fill(filled_at=ts)
        d = build_trade_journal(f, created_by="t")
        assert d.journal_at == ts

    def test_source_id_is_fill_uuid(self):
        f = _spot_fill(fill_uuid="01900000-0000-7000-8000-000000000099")
        d = build_trade_journal(f, created_by="t")
        assert d.source_id == "01900000-0000-7000-8000-000000000099"

    def test_source_hash_is_idempotency_digest(self):
        f = _spot_fill()
        d = build_trade_journal(f, created_by="t")
        assert d.source_hash == compute_fill_journal_source_hash(f)

    def test_journal_type_is_trade(self):
        for f in (_spot_fill(), _perp_fill()):
            d = build_trade_journal(f, created_by="t")
            assert d.journal_type == "trade"

    def test_source_type_is_fill(self):
        for f in (_spot_fill(), _perp_fill()):
            d = build_trade_journal(f, created_by="t")
            assert d.source_type == "fill"

    def test_portfolio_strategy_propagated_from_fill(self):
        f = _spot_fill(portfolio_id=7, strategy_id=3)
        d = build_trade_journal(f, created_by="t")
        assert d.portfolio_id == 7
        assert d.strategy_id == 3

    def test_empty_created_by_rejected(self):
        f = _spot_fill()
        with pytest.raises(ValueError, match="created_by"):
            build_trade_journal(f, created_by="")
        with pytest.raises(ValueError, match="created_by"):
            build_trade_journal(f, created_by="   ")

    def test_unsupported_instrument_type_rejected(self):
        # FillRecord blocks at construction. Verify build_trade_journal
        # also rejects defensively in case the constructor is bypassed
        # (e.g. dataclasses.replace).
        from dataclasses import replace
        f = _spot_fill()
        # Bypass __post_init__ via object.__setattr__ on a frozen dataclass
        bad = _spot_fill()
        object.__setattr__(bad, "instrument_type", "option")
        with pytest.raises(ValueError, match="unsupported instrument_type"):
            build_trade_journal(bad, created_by="t")


# ─── Reproducibility / byte-equality ──────────────────────────────────────


class TestReproducibility:
    def test_same_fill_same_journal(self):
        # End-to-end byte-equality: same FillRecord instance produces
        # the same JournalDraft on every call. No clock dependencies,
        # no UUID generation, no map iteration order.
        f = _spot_fill()
        d1 = build_trade_journal(f, created_by="t")
        d2 = build_trade_journal(f, created_by="t")
        assert d1 == d2
        assert d1.source_hash == d2.source_hash
        assert d1.entries == d2.entries

    def test_perp_reproducible(self):
        f = _perp_fill()
        d1 = build_trade_journal(f, created_by="t")
        d2 = build_trade_journal(f, created_by="t")
        assert d1 == d2

    def test_different_created_by_does_not_change_entries(self):
        # created_by is on the journal but should NOT affect ledger
        # entries — entries are determined by fill content, period
        f = _spot_fill()
        d1 = build_trade_journal(f, created_by="alice")
        d2 = build_trade_journal(f, created_by="bob")
        assert d1.entries == d2.entries
        # Source hash is determined only by fill content, so it matches
        assert d1.source_hash == d2.source_hash
        # Only the created_by differs
        assert d1.created_by != d2.created_by


# ─── End-to-end smoke (still pure) ────────────────────────────────────────


class TestEndToEndPure:
    def test_spot_buy_realistic(self):
        # Simulate the spot leg of an A1 short-perp/long-spot pair.
        # 0.01 BTC bought spot at $100k, $0.50 fee.
        f = FillRecord(
            fill_uuid="01900000-0000-7000-8000-000000000spot",
            fill_content_hash="b" * 64,
            portfolio_id=1, strategy_id=1, account_id=1,
            instrument_id=11, instrument_code="BTCUSDT-SPOT",
            instrument_type="spot",
            base_asset_symbol="BTC", quote_asset_symbol="USDT",
            side="buy",
            quantity=Decimal("0.01"), price=Decimal("100000"),
            fee_usd=Decimal("0.50"),
            fill_environment="SHADOW",
            filled_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        )
        d = build_trade_journal(f, created_by="a1_paper_runner")
        assert len(d.entries) == 4

        # Trade pair: DR position $1000, CR cash $1000
        assert d.entries[0].amount_usd == Decimal("1000")
        assert d.entries[0].quantity == Decimal("0.01")
        assert d.entries[1].amount_usd == Decimal("1000")

        # Fee pair: DR fee $0.50, CR cash $0.50
        assert d.entries[2].amount_usd == Decimal("0.50")
        assert d.entries[3].amount_usd == Decimal("0.50")

        # Total balanced at $1000.50 each side
        debits = sum(e.amount_usd for e in d.entries if e.debit_credit == "debit")
        credits = sum(e.amount_usd for e in d.entries if e.debit_credit == "credit")
        assert debits == credits == Decimal("1000.50")

    def test_perp_short_realistic(self):
        # Perp short leg of an A1 pair.
        f = FillRecord(
            fill_uuid="01900000-0000-7000-8000-000000000perp",
            fill_content_hash="c" * 64,
            portfolio_id=1, strategy_id=1, account_id=1,
            instrument_id=10, instrument_code="BTCUSDT",
            instrument_type="perp",
            base_asset_symbol="BTC", quote_asset_symbol="USDT",
            side="sell",
            quantity=Decimal("0.01"), price=Decimal("100000"),
            fee_usd=Decimal("0.50"),
            fill_environment="SHADOW",
            filled_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        )
        d = build_trade_journal(f, created_by="a1_paper_runner")
        assert len(d.entries) == 4

        # Margin pair: DR margin $1000, CR cash $1000
        assert d.entries[0].ledger_account_code.startswith("v1:margin_collateral:")
        assert d.entries[0].amount_usd == Decimal("1000")
        assert d.entries[1].ledger_account_code.startswith("v1:cash:")
        assert d.entries[1].amount_usd == Decimal("1000")

        # Fee pair: DR fee $0.50, CR cash $0.50
        assert d.entries[2].ledger_account_code.startswith("v1:fee_expense:")
        assert d.entries[2].amount_usd == Decimal("0.50")
        assert d.entries[3].amount_usd == Decimal("0.50")

        # No position ledger entry for perp
        for e in d.entries:
            assert "v1:position:" not in e.ledger_account_code

        debits = sum(e.amount_usd for e in d.entries if e.debit_credit == "debit")
        credits = sum(e.amount_usd for e in d.entries if e.debit_credit == "credit")
        assert debits == credits == Decimal("1000.50")
