"""Chart-of-accounts parser and account-spec generator.

Day 10 deliverable. Pure-function only. No DB access.

Inverts the account-code constructors in ``fill_journal_writer``: given
a v1 account code (e.g. ``"v1:cash:p1:s1:a1:USDT"``), this module
produces a fully-typed ``AccountSpec`` ready for the DB-side resolver
(Day 11) to upsert into ``accounting.ledger_accounts``.

Two layers:

  * ``parse_account_code(code)``       → ``ParsedAccountCode`` (pure shape)
  * ``spec_for_journal_entry(entry)``  → ``AccountSpec``         (resolved dims)

The parser is strict: only ``v1:`` codes are accepted, and every subtype
has a fixed dimension shape. Malformed codes raise. There is no silent
fallback to a different version — callers either use v1 or update this
parser when v2 lands.

Account-code shapes (must match fill_journal_writer constructors)::

    v1:cash:p<P>:s<S>:a<A>:<asset_symbol>
    v1:margin_collateral:p<P>:s<S>:a<A>:<asset_symbol>
    v1:position:p<P>:s<S>:a<A>:<instrument_code>           (spot)
    v1:position:p<P>:s<S>:a<A>:<instrument_code>:long      (perp)
    v1:position:p<P>:s<S>:a<A>:<instrument_code>:short     (perp)
    v1:fee_expense:p<P>:s<S>
    v1:funding_income:p<P>:s<S>:<instrument_code>
    v1:funding_expense:p<P>:s<S>:<instrument_code>
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal


SUPPORTED_VERSIONS: tuple[str, ...] = ("v1",)
ACCOUNT_CODE_VERSION = "v1"

AccountType = Literal["asset", "liability", "equity", "income", "expense"]
PerpSide = Literal["long", "short"]


# Subtype → (account_type, dimension_kind)
#
# dimension_kind controls how many ":<value>" tail segments the parser
# consumes after :p<P>:s<S>:
#   "account_asset"    — :a<A>:<asset_symbol>            (cash, margin_collateral)
#   "account_spot"     — :a<A>:<instrument_code>         (spot position)
#   "account_perp"     — :a<A>:<instrument_code>:<side>  (perp position)
#   "strategy_only"    — (no further parts)              (fee_expense)
#   "instrument_only"  — :<instrument_code>              (funding_income/_expense)
_SUBTYPE_TABLE: dict[str, tuple[AccountType, str]] = {
    "cash":              ("asset",   "account_asset"),
    "margin_collateral": ("asset",   "account_asset"),
    "position":          ("asset",   "_position_dispatch"),  # special: spot vs perp
    "fee_expense":       ("expense", "strategy_only"),
    "funding_income":    ("income",  "instrument_only"),
    "funding_expense":   ("expense", "instrument_only"),
}


# ─── Pure data ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ParsedAccountCode:
    """Structural decomposition of a v1 account code. Identifiers are
    parsed as ints; symbols/codes are kept as strings. The resolver
    layer (Day 11) turns symbols into ids."""
    version: str
    subtype: str
    account_type: AccountType
    portfolio_id: int
    strategy_id: int
    registry_account_id: int | None     # None for strategy_only / instrument_only
    asset_symbol: str | None             # None when account is per-instrument
    instrument_code: str | None          # None when account is per-asset
    perp_side: PerpSide | None           # 'long'|'short' for perp positions only


@dataclass(frozen=True)
class AccountSpec:
    """All the columns required to insert into accounting.ledger_accounts.

    Pure data; the resolver inserts ON CONFLICT (account_code) DO NOTHING
    and returns the row id. ``account_code`` is the natural key.
    """
    account_code: str
    account_name: str
    account_type: AccountType
    account_subtype: str
    portfolio_id: int | None
    strategy_id: int | None
    registry_account_id: int | None
    asset_id: int | None
    instrument_id: int | None


# ─── Parser ───────────────────────────────────────────────────────────────


def _parse_int_with_prefix(part: str, prefix: str) -> int:
    if not part.startswith(prefix):
        raise ValueError(
            f"expected token starting with {prefix!r}, got {part!r}"
        )
    raw = part[len(prefix):]
    if not raw or not raw.isdigit():
        raise ValueError(
            f"token {part!r}: digits expected after {prefix!r}, got {raw!r}"
        )
    return int(raw)


def parse_account_code(code: str) -> ParsedAccountCode:
    """Strict parser for v1 account codes.

    Raises ValueError for any code that doesn't match the supported
    shapes. Does NOT silently accept future-version codes — when v2
    lands, this function gets extended explicitly.
    """
    if not isinstance(code, str) or not code:
        raise ValueError(f"account_code must be a non-empty string, got {code!r}")

    parts = code.split(":")
    if len(parts) < 4:
        raise ValueError(
            f"account_code has too few parts (got {len(parts)}): {code!r}"
        )

    version, subtype = parts[0], parts[1]

    if version not in SUPPORTED_VERSIONS:
        raise ValueError(
            f"unsupported account-code version {version!r} in {code!r}; "
            f"supported: {SUPPORTED_VERSIONS}"
        )
    if subtype not in _SUBTYPE_TABLE:
        raise ValueError(
            f"unknown subtype {subtype!r} in {code!r}; "
            f"supported: {sorted(_SUBTYPE_TABLE)}"
        )

    account_type, dim_kind = _SUBTYPE_TABLE[subtype]

    # Common prefix: every shape carries p<P>:s<S> at parts[2:4]
    portfolio_id = _parse_int_with_prefix(parts[2], "p")
    strategy_id = _parse_int_with_prefix(parts[3], "s")

    # Defaults
    registry_account_id: int | None = None
    asset_symbol: str | None = None
    instrument_code: str | None = None
    perp_side: PerpSide | None = None
    final_subtype = subtype

    # Dispatch on dimension_kind
    if dim_kind == "account_asset":
        # :a<A>:<asset_symbol>
        if len(parts) != 6:
            raise ValueError(
                f"{subtype}: expected 6 parts (got {len(parts)}): {code!r}"
            )
        registry_account_id = _parse_int_with_prefix(parts[4], "a")
        asset_symbol = parts[5]
        if not asset_symbol or ":" in asset_symbol:
            raise ValueError(f"invalid asset_symbol in {code!r}")

    elif dim_kind == "_position_dispatch":
        # spot:  :a<A>:<instrument_code>          → 6 parts
        # perp:  :a<A>:<instrument_code>:<side>   → 7 parts
        if len(parts) == 6:
            # spot
            registry_account_id = _parse_int_with_prefix(parts[4], "a")
            instrument_code = parts[5]
        elif len(parts) == 7:
            # perp
            registry_account_id = _parse_int_with_prefix(parts[4], "a")
            instrument_code = parts[5]
            side = parts[6]
            if side not in ("long", "short"):
                raise ValueError(
                    f"position perp side must be 'long' or 'short' in {code!r}; "
                    f"got {side!r}"
                )
            perp_side = side  # type: ignore[assignment]
        else:
            raise ValueError(
                f"position: expected 6 (spot) or 7 (perp) parts (got {len(parts)}): {code!r}"
            )
        if not instrument_code or ":" in instrument_code:
            raise ValueError(f"invalid instrument_code in {code!r}")

    elif dim_kind == "strategy_only":
        # :p<P>:s<S>  (no tail)
        if len(parts) != 4:
            raise ValueError(
                f"{subtype}: expected 4 parts (got {len(parts)}): {code!r}"
            )

    elif dim_kind == "instrument_only":
        # :p<P>:s<S>:<instrument_code>
        if len(parts) != 5:
            raise ValueError(
                f"{subtype}: expected 5 parts (got {len(parts)}): {code!r}"
            )
        instrument_code = parts[4]
        if not instrument_code or ":" in instrument_code:
            raise ValueError(f"invalid instrument_code in {code!r}")

    else:  # pragma: no cover  (table-driven; only reachable if table grows wrong)
        raise ValueError(
            f"unhandled dim_kind {dim_kind!r} for subtype {subtype!r}"
        )

    return ParsedAccountCode(
        version=version,
        subtype=final_subtype,
        account_type=account_type,
        portfolio_id=portfolio_id,
        strategy_id=strategy_id,
        registry_account_id=registry_account_id,
        asset_symbol=asset_symbol,
        instrument_code=instrument_code,
        perp_side=perp_side,
    )


# ─── account_name generator ───────────────────────────────────────────────


def account_name_for(parsed: ParsedAccountCode) -> str:
    """Human-readable account name. Used for the ``account_name`` column,
    which is REQUIRED but only displayed in audit/log surfaces. Must be
    deterministic so audit trails match.
    """
    p, s, a = parsed.portfolio_id, parsed.strategy_id, parsed.registry_account_id

    if parsed.subtype == "cash":
        return f"Cash ({parsed.asset_symbol}) — portfolio {p}, strategy {s}, account {a}"
    if parsed.subtype == "margin_collateral":
        return (
            f"Margin collateral ({parsed.asset_symbol}) — "
            f"portfolio {p}, strategy {s}, account {a}"
        )
    if parsed.subtype == "position":
        if parsed.perp_side is None:
            return (
                f"Spot position {parsed.instrument_code} — "
                f"portfolio {p}, strategy {s}, account {a}"
            )
        return (
            f"Perp position {parsed.instrument_code} ({parsed.perp_side}) — "
            f"portfolio {p}, strategy {s}, account {a}"
        )
    if parsed.subtype == "fee_expense":
        return f"Fee expense — portfolio {p}, strategy {s}"
    if parsed.subtype == "funding_income":
        return f"Funding income {parsed.instrument_code} — portfolio {p}, strategy {s}"
    if parsed.subtype == "funding_expense":
        return f"Funding expense {parsed.instrument_code} — portfolio {p}, strategy {s}"
    raise ValueError(f"no account_name template for subtype {parsed.subtype!r}")


# ─── Spec generator ───────────────────────────────────────────────────────


# Type aliases for resolver callables
AssetIdResolver = Callable[[str], int]
InstrumentIdResolver = Callable[[str], int | None]


def spec_for_account_code(
    account_code: str,
    *,
    asset_id_resolver: AssetIdResolver,
    instrument_id_resolver: InstrumentIdResolver,
) -> AccountSpec:
    """Pure function. Decompose a v1 account code, then resolve its
    asset_symbol / instrument_code into ids via the supplied callables,
    and produce a fully-typed ``AccountSpec`` ready for the DB resolver.

    Resolver callables MUST be pure with respect to the symbol/code they
    accept. The DB-backed resolvers in Day 11 are wrappers over
    ``SELECT id FROM registry.assets WHERE symbol = %s``.

    For ``fee_expense`` (no per-asset, no per-instrument scope), neither
    resolver is invoked. The resulting AccountSpec carries asset_id=None
    and instrument_id=None — which the dimension-consistency trigger in
    0005 accepts because nullable account dimensions are not enforced
    against the journal's dimensions.
    """
    parsed = parse_account_code(account_code)
    name = account_name_for(parsed)

    asset_id: int | None = None
    instrument_id: int | None = None
    if parsed.asset_symbol is not None:
        asset_id = asset_id_resolver(parsed.asset_symbol)
        if asset_id is None or asset_id <= 0:
            raise ValueError(
                f"asset_id_resolver returned non-positive id "
                f"{asset_id!r} for symbol {parsed.asset_symbol!r}"
            )
    if parsed.instrument_code is not None:
        instrument_id = instrument_id_resolver(parsed.instrument_code)
        if instrument_id is None:
            raise ValueError(
                f"instrument_id_resolver returned None for "
                f"instrument_code {parsed.instrument_code!r}"
            )
        if instrument_id <= 0:
            raise ValueError(
                f"instrument_id_resolver returned non-positive id "
                f"{instrument_id!r} for {parsed.instrument_code!r}"
            )

    return AccountSpec(
        account_code=account_code,
        account_name=name,
        account_type=parsed.account_type,
        account_subtype=parsed.subtype,
        portfolio_id=parsed.portfolio_id,
        strategy_id=parsed.strategy_id,
        registry_account_id=parsed.registry_account_id,
        asset_id=asset_id,
        instrument_id=instrument_id,
    )
