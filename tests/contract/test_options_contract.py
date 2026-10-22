"""feature 009: contracts/outputs-options.md guarantees 1-5 (tasks T037)."""

import pytest

from sweetspot.config import Preferences
from sweetspot.decision.contract import batch_to_dict
from sweetspot.decision.engine import run_decisions
from sweetspot.forecast.contract import batch_to_dict as forecast_dict
from sweetspot.forecast.models import build_model
from sweetspot.store.query import OPTION_HISTORY_SOURCE, PriceStore
from tests.forecast_builders import BASIC_CALENDAR, GameSpec, add_history, add_purchase_options, add_version, build_db, dt

AS_OF = dt("2025-08-01")
CUTS = [("2024-12-11", 0), ("2024-12-19T18:00", 50), ("2025-01-02T18:00", 0), ("2025-03-13T17:00", 50),
        ("2025-03-20T17:00", 0), ("2025-06-26T17:00", 50), ("2025-07-10T17:00", 0)]
DEFAULT = dict(kind="sub", option_id=100, name="Standard", original_cents=50000, final_cents=50000, role="default")
DELUXE = dict(kind="bundle", option_id=900, name="Deluxe", original_cents=90000, final_cents=90000, role="edition",
              external_id="itad-deluxe", verification="verified", verified_by="version-check", verified_at="2025-07-31")
MIXED = dict(kind="bundle", option_id=901, name="Two games", original_cents=99000, final_cents=99000,
             role="other-games")


@pytest.fixture
def store(db_path):
    games = [GameSpec(a, tw=CUTS, us=CUTS, name=f"Game {a}", wishlist=True) for a in (1, 2, 3)]
    build_db(db_path, games, calendar=BASIC_CALENDAR)
    for a in (1, 2, 3):
        add_version(db_path, a, "2025-07-31", external_id=f"itad-{a}", package_id=100, package_name="Standard")
    add_purchase_options(db_path, 1, "2025-07-31", [DEFAULT, DELUXE, MIXED])
    add_history(db_path, 1, "itad-deluxe", tw=[(t, 80 if c else 0, 90000) for t, c in CUTS],
                us=[(t, 80 if c else 0) for t, c in CUTS], regular_cents=90000, fetched="2025-07-31",
                source=OPTION_HISTORY_SOURCE, fetch_source="itad-option")
    s = PriceStore.open(db_path)
    yield s
    s.close()


def decide(store, choices=None):
    return run_decisions(store, store.wishlist_apps(), AS_OF, build_model("seasonal-record"), Preferences(),
                         now=dt("2025-08-01"), choices=choices)


def by_app(data):
    return {d["app_id"]: d for d in data["decisions"]}


def test_without_choices_only_new_fields_are_added(store):
    got = by_app(batch_to_dict(decide(store)))
    for d in got.values():
        assert d["version"]["source"] == "steam-default"
        assert d["version"]["option"] == {"kind": "sub", "id": 100, "name": "Standard"}
        assert d["version"]["fallback"] is None
    assert [(e["kind"], e["id"]) for e in got[1]["editions"]] == [("bundle", 900)]   # never the other-games bundle


def test_a_choice_changes_only_its_game(store):
    base = by_app(batch_to_dict(decide(store)))
    chosen = by_app(batch_to_dict(decide(store, {1: ("bundle", 900)})))
    v = chosen[1]["version"]
    assert (v["basis"], v["source"], v["itad_id"]) == ("user", "user", "itad-deluxe")
    assert v["option"] == {"kind": "bundle", "id": 900, "name": "Deluxe"} and v["package_id"] is None
    assert chosen[1]["current"]["regular_cents"] == 90000 and chosen[1]["regular_cents"] == 90000
    assert any("使用者指定的購買選項 Deluxe" in r for r in chosen[1]["reasons"])
    for app in (2, 3):
        assert chosen[app] == base[app]
    assert [(e["kind"], e["id"], e["unset_hint"]) for e in chosen[1]["editions"]] == [("sub", 100, True)]


def test_decision_version_equals_forecast_version(store):
    batch = decide(store, {1: ("bundle", 900)})
    forecast = {g["app_id"]: g for g in forecast_dict(batch.forecast)["games"]}
    for d in batch_to_dict(batch)["decisions"]:
        assert d["version"] == forecast[d["app_id"]]["version"]


def test_past_as_of_never_sees_later_purchase_options(store, db_path):
    add_purchase_options(db_path, 2, "2025-09-01", [DEFAULT, {**DELUXE, "option_id": 950, "external_id": "x"}])
    got = by_app(batch_to_dict(decide(store, {2: ("bundle", 950)})))
    assert got[2]["editions"] is None
    assert got[2]["version"]["source"] == "user-fallback"
    assert got[2]["version"]["fallback"]["code"] == "no-record"
