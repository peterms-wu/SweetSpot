"""feature 010 (spec FR-018; tasks T034): the bundle block at an as_of only uses what was recorded by then. The
second test proves the first one catches a peek: reading the latest record regardless of as_of changes the block."""

from pathlib import Path

import pytest

from sweetspot.config import Preferences
from sweetspot.decision.contract import batch_to_dict
from sweetspot.decision.engine import run_decisions
from sweetspot.forecast.models import build_model
from sweetspot.store.query import PriceStore
from tests.contract.test_bundles_contract import AS_OF, CUTS, DEFAULT, PAIR
from tests.forecast_builders import BASIC_CALENDAR, GameSpec, add_purchase_options, add_version, build_db

LATER = {**PAIR, "final_cents": 70000, "bundle_discount_pct": 30, "name": "Game 1 x Game 2 (later)",
         "contents": PAIR["contents"] + [{"app_id": 3, "type": 0, "parent_app_id": None}]}


def make(path: Path, *, later: bool) -> Path:
    build_db(path, [GameSpec(a, tw=CUTS, us=CUTS, name=f"Game {a}", wishlist=True) for a in (1, 2, 3)],
             calendar=BASIC_CALENDAR)
    for a in (1, 2, 3):
        add_version(path, a, "2025-07-31", external_id=f"itad-{a}", package_id=100, package_name="Standard")
    for a in (1, 2):
        add_purchase_options(path, a, "2025-07-31", [DEFAULT, {**PAIR, "is_default": False}])
        if later:                               # recorded after AS_OF: a different discount, price and contents
            add_purchase_options(path, a, "2025-08-15", [DEFAULT, {**LATER, "is_default": False}])
    return path


def bundles_at(path: Path, *, peek: bool = False) -> list:
    store = PriceStore.open(path)
    try:
        if peek:
            real = store.purchase_options
            store.purchase_options = lambda apps, as_of: real(apps, as_of.replace(year=as_of.year + 1))
        batch = run_decisions(store, store.wishlist_apps(), AS_OF, build_model("seasonal-record"), Preferences(),
                              now=AS_OF)
    finally:
        store.close()
    data = batch_to_dict(batch)
    return [data["bundles"], {d["app_id"]: d["bundles"] for d in data["decisions"]}]


@pytest.fixture
def pair(tmp_path):
    return make(tmp_path / "a" / "sweetspot.db", later=False), make(tmp_path / "b" / "sweetspot.db", later=True)


def test_later_records_change_nothing(pair):
    before, with_later = pair
    assert bundles_at(with_later) == bundles_at(before)
    assert bundles_at(before)[0][0]["discount_pct"] == 10


def test_the_check_catches_a_peek(pair):
    before, with_later = pair
    peeked = bundles_at(with_later, peek=True)
    assert peeked != bundles_at(before)
    assert peeked[0][0]["discount_pct"] == 30
