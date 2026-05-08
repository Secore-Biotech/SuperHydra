"""Fill → balanced journal builder.

Day 9 deliverable. Pure-function only. No DB access.

Given a fill record (real or synthetic), this module builds an in-memory
``JournalDraft`` of the journal + ledger entries that, once persisted,
will satisfy the accounting layer's invariants:

  * Sum of debits equals sum of credits (USD).
  * At least 2 ledger entries.
  * Each ledger entry's account dimensions (portfolio, strategy, asset,
    instrument) are consistent with the journal's dimensions and the
    fill's instrument.

Two trade shapes, dispatched on ``instrument_type``:

  spot
      Cash buys an asset (or sells one). Journal records the
      cash↔position swap plus the fee. ``position`` ledger account
      represents inventory.

  perp
      Cash is encumbered as initial margin; no cash leaves the account
      at fill time. Journal records the margin posting plus the fee.
      Perp *quantity* is tracked in ``positions.position_lots``, not
      in ledger_entries — the journal is purely cash and margin.

The DB-side writer (Day 11) consumes ``JournalDraft`` and is the only
caller that touches the accounting schema. Everything in this module
is deterministic and unit-testable without a postgres connection.

Account-code convention (v1)
----------------------------

All ledger account codes follow::

    v1:<subtype>:p<portfolio_id>:s<strategy_id>:a<account_id>[:<asset_or_instr>][:<side>]

Examples::

    v1:cash:p1:s1:a1:USDT
    v1:margin_collateral:p1:s1:a1:USDT
    v1:position:p1:s1:a1:BTCUSDT-spot
    v1:position:p1:s1:a1:BTCUSDT-perp:long
    v1:position:p1:s1:a1:BTCUSDT-perp:short
    v1:fee_expense:p1:s1

The ``v1:`` prefix is a forward-compatibility shim. When the convention
evolves the new accounts coexist as ``v2:...`` and historical journals
keep referencing ``v1:...`` accounts unchanged. Ledger accounts are
historical records; once a posted journal references one, the code is
permanent.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal


JOURNAL_DRAFT_SCHEMA_VERSION = "journal_draft.v0"
ACCOUNT_CODE_VERSION = "v1"

InstrumentType = Literal["spot", "perp"]
DebitCredit = Literal["debit", "credit"]
JournalType = Literal["trade", "fee", "funding"]
SourceType = Literal["fill", "funding_event"]
Side = Literal["buy", "sell"]


# ─── Pure data ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FillRecord:
    """Subset of ``trading.fills`` columns that ``build_trade_journal``
    needs. Constructed by callers from either a real DB row or a synthetic
    test fixture. All money is Decimal — float would silently corrupt the
    balance check."""
    fill_uuid: str
    fill_content_hash: str  # idempotency input
    portfolio_id: int
    strategy_id: int
    account_id: int
    instrument_id: int
    instrument_code: str  # e.g. "BTCUSDT", "BTCUSDT-SPOT"
    instrument_type: InstrumentType
    base_asset_symbol: str  # e.g. "BTC"
    quote_asset_symbol: str  # e.g. "USDT"
    side: Side
    quantity: Decimal  # > 0
    price: Decimal  # > 0, USD-equivalent for our purposes
    fee_usd: Decimal  # ≥ 0
    fill_environment: Literal["LIVE", "SHADOW", "REPLAY", "BACKTEST"]
    filled_at: datetime  # UTC

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"FillRecord.quantity must be > 0, got {self.quantity}")
        if self.price <= 0:
            raise ValueError(f"FillRecord.price must be > 0, got {self.price}")
        if self.fee_usd < 0:
            raise ValueError(f"FillRecord.fee_usd must be >= 0, got {self.fee_usd}")
        if self.filled_at.tzinfo is None or self.filled_at.utcoffset() != timezone.utc.utcoffset(None):
            raise ValueError("FillRecord.filled_at must be tz-aware UTC")
        if self.instrument_type not in ("spot", "perp"):
            raise ValueError(f"unsupported instrument_type: {self.instrument_type}")
        if self.side not in ("buy", "sell"):
            raise ValueError(f"unsupported side: {self.side}")
        # We allow fee_usd to be 0 in case a fixture deliberately models a
        # zero-fee execution; the journal still needs at least 2 entries
        # but the trade-pair alone provides them.


@dataclass(frozen=True)
class LedgerEntryDraft:
    """One side of a debit/credit pair. Account is referenced by code,
    not id — id resolution happens at write time so the chart-of-accounts
    can evolve independently."""
    debit_credit: DebitCredit
    ledger_account_code: str
    asset_symbol: str
    instrument_code: str | None
    quantity: Decimal | None  # None for pure cash entries (e.g. fees)
    amount_usd: Decimal  # > 0
    memo: str

    def __post_init__(self) -> None:
        if self.debit_credit not in ("debit", "credit"):
            raise ValueError(f"debit_credit must be 'debit' or 'credit', got {self.debit_credit!r}")
        if self.amount_usd <= 0:
            raise ValueError(f"amount_usd must be > 0, got {self.amount_usd}")
        if self.quantity is not None and self.quantity <= 0:
            raise ValueError(f"quantity must be > 0 if present, got {self.quantity}")
        if not self.ledger_account_code.startswith(f"{ACCOUNT_CODE_VERSION}:"):
            raise ValueError(
                f"ledger_account_code must start with {ACCOUNT_CODE_VERSION}:; "
                f"got {self.ledger_account_code!r}"
            )
        if not self.memo.strip():
            raise ValueError("memo must be non-empty")


@dataclass(frozen=True)
class JournalDraft:
    """Pre-DB representation of an ``accounting.journals`` row plus its
    ``accounting.ledger_entries`` rows. Frozen and Decimal-typed; the
    writer can serialize this byte-equally across runs.

    Invariants enforced at construction:
      * ≥ 2 entries
      * sum(debits) == sum(credits) in USD
      * journal_at is tz-aware UTC
      * source_hash is non-empty (idempotency key)
    """
    schema_version: str
    journal_type: JournalType
    portfolio_id: int
    strategy_id: int
    journal_at: datetime
    source_type: SourceType
    source_namespace: str  # 'global' or venue namespace
    source_id: str  # e.g. fill_uuid
    source_hash: str  # idempotency digest
    description: str
    created_by: str
    entries: tuple[LedgerEntryDraft, ...]

    def __post_init__(self) -> None:
        if self.schema_version != JOURNAL_DRAFT_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version mismatch: expected {JOURNAL_DRAFT_SCHEMA_VERSION}, "
                f"got {self.schema_version}"
            )
        if len(self.entries) < 2:
            raise ValueError(
                f"journal must have at least 2 entries; got {len(self.entries)}"
            )
        if self.journal_at.tzinfo is None:
            raise ValueError("journal_at must be tz-aware UTC")
        if not self.source_hash.strip():
            raise ValueError("source_hash must be non-empty (idempotency key)")
        if not self.created_by.strip():
            raise ValueError("created_by must be non-empty")

        debits = sum(
            (e.amount_usd for e in self.entries if e.debit_credit == "debit"),
            Decimal("0"),
        )
        credits = sum(
            (e.amount_usd for e in self.entries if e.debit_credit == "credit"),
            Decimal("0"),
        )
        if debits != credits:
            raise ValueError(
                f"journal not balanced: debits={debits}, credits={credits}, "
                f"diff={debits - credits}"
            )


# ─── Account-code helpers ─────────────────────────────────────────────────


def _v1(*parts: str) -> str:
    """Join account-code parts with the v1: prefix and ':' separator.
    Reject empty parts to prevent silent collisions."""
    if not parts:
        raise ValueError("at least one account-code part required")
    for p in parts:
        if not p or ":" in p:
            raise ValueError(f"invalid account-code part: {p!r}")
    return f"{ACCOUNT_CODE_VERSION}:" + ":".join(parts)


def cash_account_code(portfolio_id: int, strategy_id: int,
                      account_id: int, asset_symbol: str) -> str:
    return _v1("cash", f"p{portfolio_id}", f"s{strategy_id}",
               f"a{account_id}", asset_symbol)


def margin_collateral_account_code(portfolio_id: int, strategy_id: int,
                                   account_id: int, asset_symbol: str) -> str:
    return _v1("margin_collateral", f"p{portfolio_id}", f"s{strategy_id}",
               f"a{account_id}", asset_symbol)


def spot_position_account_code(portfolio_id: int, strategy_id: int,
                               account_id: int, instrument_code: str) -> str:
    return _v1("position", f"p{portfolio_id}", f"s{strategy_id}",
               f"a{account_id}", instrument_code)


def perp_position_account_code(portfolio_id: int, strategy_id: int,
                               account_id: int, instrument_code: str,
                               side: Literal["long", "short"]) -> str:
    if side not in ("long", "short"):
        raise ValueError(f"perp side must be 'long' or 'short', got {side!r}")
    return _v1("position", f"p{portfolio_id}", f"s{strategy_id}",
               f"a{account_id}", instrument_code, side)


def fee_expense_account_code(portfolio_id: int, strategy_id: int) -> str:
    return _v1("fee_expense", f"p{portfolio_id}", f"s{strategy_id}")


def funding_income_account_code(portfolio_id: int, strategy_id: int,
                                instrument_code: str) -> str:
    return _v1("funding_income", f"p{portfolio_id}", f"s{strategy_id}",
               instrument_code)


def funding_expense_account_code(portfolio_id: int, strategy_id: int,
                                 instrument_code: str) -> str:
    return _v1("funding_expense", f"p{portfolio_id}", f"s{strategy_id}",
               instrument_code)


# ─── Idempotency ──────────────────────────────────────────────────────────


def compute_fill_journal_source_hash(fill: FillRecord) -> str:
    """Stable hash over the fields that, if changed, would mean the
    journal we previously posted for this fill is no longer a faithful
    record. Used as the idempotency key in ``accounting.journals.source_hash``.

    If the writer ever sees a fill with the same ``fill_uuid`` but a
    different ``source_hash``, that's an integrity failure: the fill was
    rewritten under our feet, and the previously-posted journal is now
    stale. The writer raises rather than emits a second journal."""
    h = hashlib.sha256()
    h.update(fill.fill_uuid.encode("ascii"))
    h.update(b"|")
    h.update(fill.fill_content_hash.encode("ascii"))
    h.update(b"|")
    h.update(fill.side.encode("ascii"))
    h.update(b"|")
    h.update(str(fill.quantity).encode("ascii"))
    h.update(b"|")
    h.update(str(fill.price).encode("ascii"))
    h.update(b"|")
    h.update(str(fill.fee_usd).encode("ascii"))
    h.update(b"|")
    h.update(fill.instrument_type.encode("ascii"))
    h.update(b"|")
    h.update(fill.fill_environment.encode("ascii"))
    return h.hexdigest()


# ─── Internal builders ────────────────────────────────────────────────────


def _build_spot_trade_entries(fill: FillRecord) -> tuple[LedgerEntryDraft, ...]:
    """Spot fill → asset↔cash swap + optional fee.

    Buy:
      DR position(base_asset, instrument)  qty   $notional
      CR cash(quote_asset)                  $notional       $notional
      DR fee_expense                         —              $fee
      CR cash(quote_asset)                   $fee           $fee

    Sell mirrors this: cash up, position down.
    """
    notional = (fill.quantity * fill.price).quantize(Decimal("0.000000000001"))
    pos_acct = spot_position_account_code(
        fill.portfolio_id, fill.strategy_id,
        fill.account_id, fill.instrument_code,
    )
    cash_acct = cash_account_code(
        fill.portfolio_id, fill.strategy_id,
        fill.account_id, fill.quote_asset_symbol,
    )
    fee_acct = fee_expense_account_code(fill.portfolio_id, fill.strategy_id)

    entries: list[LedgerEntryDraft] = []

    if fill.side == "buy":
        # Cash → position. Position grows.
        entries.append(LedgerEntryDraft(
            debit_credit="debit",
            ledger_account_code=pos_acct,
            asset_symbol=fill.base_asset_symbol,
            instrument_code=fill.instrument_code,
            quantity=fill.quantity,
            amount_usd=notional,
            memo=f"spot buy {fill.quantity} {fill.base_asset_symbol} @ {fill.price}",
        ))
        entries.append(LedgerEntryDraft(
            debit_credit="credit",
            ledger_account_code=cash_acct,
            asset_symbol=fill.quote_asset_symbol,
            instrument_code=None,
            quantity=notional,
            amount_usd=notional,
            memo=f"cash spent on spot buy",
        ))
    else:  # sell
        entries.append(LedgerEntryDraft(
            debit_credit="debit",
            ledger_account_code=cash_acct,
            asset_symbol=fill.quote_asset_symbol,
            instrument_code=None,
            quantity=notional,
            amount_usd=notional,
            memo=f"cash received from spot sell",
        ))
        entries.append(LedgerEntryDraft(
            debit_credit="credit",
            ledger_account_code=pos_acct,
            asset_symbol=fill.base_asset_symbol,
            instrument_code=fill.instrument_code,
            quantity=fill.quantity,
            amount_usd=notional,
            memo=f"spot sell {fill.quantity} {fill.base_asset_symbol} @ {fill.price}",
        ))

    if fill.fee_usd > 0:
        entries.append(LedgerEntryDraft(
            debit_credit="debit",
            ledger_account_code=fee_acct,
            asset_symbol=fill.quote_asset_symbol,
            instrument_code=None,
            quantity=None,
            amount_usd=fill.fee_usd,
            memo="taker fee",
        ))
        entries.append(LedgerEntryDraft(
            debit_credit="credit",
            ledger_account_code=cash_acct,
            asset_symbol=fill.quote_asset_symbol,
            instrument_code=None,
            quantity=fill.fee_usd,
            amount_usd=fill.fee_usd,
            memo="fee paid in cash",
        ))

    return tuple(entries)


def _build_perp_trade_entries(fill: FillRecord) -> tuple[LedgerEntryDraft, ...]:
    """Perp fill → margin posting + optional fee.

    Per the design: a perp fill does NOT move position quantity into
    ledger_entries. Position-as-inventory lives in positions.position_lots.
    The journal records cash being encumbered as initial margin, plus
    the fee paid out of cash. Notional is the encumbrance amount.

    Buy or sell of perp: same shape — open a margin obligation, lock cash.
    Side determines whether the eventual position lot is long or short,
    not the journal shape.
    """
    notional = (fill.quantity * fill.price).quantize(Decimal("0.000000000001"))
    margin_acct = margin_collateral_account_code(
        fill.portfolio_id, fill.strategy_id,
        fill.account_id, fill.quote_asset_symbol,
    )
    cash_acct = cash_account_code(
        fill.portfolio_id, fill.strategy_id,
        fill.account_id, fill.quote_asset_symbol,
    )
    fee_acct = fee_expense_account_code(fill.portfolio_id, fill.strategy_id)

    entries: list[LedgerEntryDraft] = [
        LedgerEntryDraft(
            debit_credit="debit",
            ledger_account_code=margin_acct,
            asset_symbol=fill.quote_asset_symbol,
            instrument_code=None,
            quantity=notional,
            amount_usd=notional,
            memo=f"initial margin posted for perp {fill.side} "
                 f"{fill.quantity} {fill.instrument_code}",
        ),
        LedgerEntryDraft(
            debit_credit="credit",
            ledger_account_code=cash_acct,
            asset_symbol=fill.quote_asset_symbol,
            instrument_code=None,
            quantity=notional,
            amount_usd=notional,
            memo="cash encumbered as margin",
        ),
    ]

    if fill.fee_usd > 0:
        entries.extend([
            LedgerEntryDraft(
                debit_credit="debit",
                ledger_account_code=fee_acct,
                asset_symbol=fill.quote_asset_symbol,
                instrument_code=None,
                quantity=None,
                amount_usd=fill.fee_usd,
                memo="taker fee",
            ),
            LedgerEntryDraft(
                debit_credit="credit",
                ledger_account_code=cash_acct,
                asset_symbol=fill.quote_asset_symbol,
                instrument_code=None,
                quantity=fill.fee_usd,
                amount_usd=fill.fee_usd,
                memo="fee paid in cash",
            ),
        ])

    return tuple(entries)


# ─── Public builder ───────────────────────────────────────────────────────


def build_trade_journal(fill: FillRecord, *, created_by: str) -> JournalDraft:
    """Build a balanced journal draft from a SHADOW or LIVE trade fill.

    Dispatches on ``fill.instrument_type``:
      * ``spot`` → asset↔cash swap + fee
      * ``perp`` → margin posting + fee (position quantity goes to
        position_lots, not the ledger)

    The returned draft is unposted (writer is responsible for INSERT +
    post_journal). Same fill → byte-equal draft on every call.
    """
    if not created_by.strip():
        raise ValueError("created_by must be non-empty")

    if fill.instrument_type == "spot":
        entries = _build_spot_trade_entries(fill)
    elif fill.instrument_type == "perp":
        entries = _build_perp_trade_entries(fill)
    else:
        raise ValueError(f"unsupported instrument_type: {fill.instrument_type}")

    return JournalDraft(
        schema_version=JOURNAL_DRAFT_SCHEMA_VERSION,
        journal_type="trade",
        portfolio_id=fill.portfolio_id,
        strategy_id=fill.strategy_id,
        journal_at=fill.filled_at,
        source_type="fill",
        source_namespace="global",
        source_id=fill.fill_uuid,
        source_hash=compute_fill_journal_source_hash(fill),
        description=(
            f"trade fill {fill.fill_uuid} "
            f"({fill.instrument_type} {fill.side} "
            f"{fill.quantity} {fill.instrument_code} @ {fill.price})"
        ),
        created_by=created_by,
        entries=entries,
    )
