"""Universe loader and eligibility logic for Sleeve B xs-momentum.

The universe is loaded from the frozen fixture (commit 2af9981) at
tests/fixtures/sleeve_b/universe_top30_20260415.json. Eligibility at any
rebalance date is determined by listing-age (per D10: asset eligible iff
listing_age_days >= lookback_days, i.e., the asset has at least lookback_days
of price history to compute a trailing return).

The fixture is the contract; this module does not modify it. The frozen-
policy and reconstitution-permitted=false fields are checked on load and
the load fails closed if they are not as expected.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True)
class UniverseAsset:
    """One asset in the frozen Sleeve B universe."""
    rank: int
    symbol: str
    base_asset: str
    onboard_date: date
    adv_usdt: Decimal


def load_universe(fixture_path: Path) -> list[UniverseAsset]:
    """Load universe from the frozen fixture.

    Validates:
      - universe_membership_policy == "frozen"
      - reconstitution_permitted is False

    These checks enforce the pre-registration's freeze rule programmatically.
    If a future caller tries to load a fixture that isn't frozen, the load
    fails closed.
    """
    data = json.loads(fixture_path.read_text())
    if data.get("universe_membership_policy") != "frozen":
        raise ValueError(
            "universe fixture must have universe_membership_policy='frozen', "
            f"got {data.get('universe_membership_policy')!r}"
        )
    if data.get("reconstitution_permitted") is not False:
        raise ValueError(
            "universe fixture must have reconstitution_permitted=false, "
            f"got {data.get('reconstitution_permitted')!r}"
        )
    assets = []
    for u in data["universe"]:
        assets.append(UniverseAsset(
            rank=u["rank"],
            symbol=u["symbol"],
            base_asset=u["base_asset"],
            onboard_date=date.fromisoformat(u["onboard_date"]),
            adv_usdt=Decimal(u["adv_usdt"]),
        ))
    return assets


# D10: 14-day listing-age delay matches the lookback. The engine takes
# this as a parameter; this constant is the pre-registration-locked default.
DEFAULT_ELIGIBILITY_DELAY_DAYS = 14


def eligible_at(
    universe: list[UniverseAsset],
    as_of: date,
    *,
    listing_delay_days: int = DEFAULT_ELIGIBILITY_DELAY_DAYS,
) -> list[UniverseAsset]:
    """Return the subset of universe eligible at `as_of`.

    Per D10: asset is eligible iff (as_of - onboard_date).days >=
    listing_delay_days. For 14-day momentum, listing_delay_days == 14.

    This is purely deterministic. No discretion. The universe membership
    itself is frozen; eligibility within it is rule-based.
    """
    return [
        a for a in universe
        if (as_of - a.onboard_date).days >= listing_delay_days
    ]
