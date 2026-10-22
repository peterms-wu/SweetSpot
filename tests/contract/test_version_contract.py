"""contracts/outputs-version.md guarantees 1-7 (feature 006, tasks T039)."""

import pytest

from sweetspot.config import Preferences
from sweetspot.decision.changes import compare
from sweetspot.decision.contract import batch_to_dict
from sweetspot.decision.engine import run_decisions
from sweetspot.forecast.models import build_model
from sweetspot.store.query import PriceStore
from tests.forecast_builders import BASIC_CALENDAR, GameSpec, add_history, add_version, build_db, dt

AS_OF = dt("2025-08-01")
SALES = [("2024-12-11", 0), ("2024-12-19T18:00", 50), ("2025-01-02T18:00", 0), ("2025-03-13T17:00", 40),
         ("2025-03-20T17:00", 0), ("2025-06-26T17:00", 60), ("2025-07-10T17:00", 0)]


@pytest.fixture
def data(db_path):
    build_db(db_path, [GameSpec(1, tw=SALES, wishlist=True, name="Switched"),
                       GameSpec(2, tw=SALES, wishlist=True, name="Rejected"),
                       GameSpec(3, tw=SALES, wishlist=True, name="Stopped"),
                       GameSpec(4, tw=SALES, wishlist=True, name="Ambiguous"),
                       GameSpec(5, tw=SALES, wishlist=True, name="No record"),
                       GameSpec(6, release_date="2027-01-01", wishlist=True, name="Future")],
             calendar=BASIC_CALENDAR)
    add_history(db_path, 1, "itad-new", tw=SALES, regular_cents=67000, fetched="2025-07-31")
    add_version(db_path, 1, "2025-07-31", external_id="itad-new", package_name="Deluxe")
    add_version(db_path, 2, "2025-07-31", external_id="itad-bad", verification="rejected", reason_code="bundle",
                reason_detail="bundle/1")
    add_version(db_path, 3, "2025-07-31", external_id="itad-3", itad_steam_deals=0)
    add_version(db_path, 4, "2025-07-31", external_id=None, status="ambiguous")
    s = PriceStore.open(db_path)
    model = build_model("seasonal-freq", {"min_sales": 2})
    batch = run_decisions(s, s.wishlist_apps(), AS_OF, model, Preferences(), now=AS_OF, rule="2.1.0")
    s.close()
    out = batch_to_dict(batch)
    return {g["app_id"]: g for g in out["forecast"]["games"]}, {d["app_id"]: d for d in out["decisions"]}, out


def test_1_every_analysable_game_has_a_version(data):
    games, _, _ = data
    for app, g in games.items():
        if g["status"] not in ("unreleased", "free", "unsupported-bundle"):
            assert g["version"] is not None, app


def test_2_basis_and_reasons(data):
    games, _, _ = data
    assert {a: games[a]["version"]["basis"] for a in (1, 2, 3, 4, 5)} == {
        1: "version", 2: "rejected", 3: "version", 4: "own", 5: "own"}
    assert games[4]["version"]["basis_reason"] == "ambiguous" and games[5]["version"]["basis_reason"] == "no-record"


def test_3_rejected_iff_unverified(data):
    games, _, _ = data
    for g in games.values():
        v = g["version"]
        if v is not None:
            assert (v["basis"] == "rejected") == (g["status"] == "unverified")
    assert "bundle/1" in games[2]["status_reason"]


def test_4_stopped_has_last_confirmed_equal_to_known_until(data):
    games, decisions, _ = data
    v = games[3]["version"]
    assert v["tracking"] == "stopped" and v["last_confirmed"] == v["known_until"] == "2025-07-10T17:00:00Z"
    assert decisions[3]["confidence"] == "low" and "history-stopped" in decisions[3]["tags"]
    for g in games.values():
        if g["version"] and g["version"]["tracking"] != "stopped":
            assert g["version"]["last_confirmed"] is None


def test_5_decisions_copy_the_forecast_version(data):
    games, decisions, _ = data
    for app, d in decisions.items():
        assert d["version"] == games[app]["version"], app


def test_6_times_are_utc_and_not_after_generation(data):
    games, _, out = data
    generated = out["generated_at"]
    for g in games.values():
        v = g["version"] or {}
        for key in ("history_start", "known_until", "last_confirmed", "checked_at"):
            if v.get(key):
                assert v[key].endswith("Z") and v[key] <= generated, (key, v[key])
        if v.get("change"):
            assert v["change"]["detected_at"].endswith("Z") and v["change"]["detected_at"] <= generated


def test_7_old_records_without_versions_still_compare(data):
    _, _, out = data
    old = {**out, "decisions": [{k: v for k, v in d.items() if k != "version"} for d in out["decisions"]]}
    changes, _ = compare(out, old, file="f", as_of="a")
    assert changes[1]["version"]["from"] == "Switched" and changes[1]["version"]["to"] == "Deluxe"
    assert changes[3] is None and changes[5] is None
