"""feature 010: contracts/outputs-bundles.md — the batch's `bundles` and `bundle_rule`, each decision's `bundles`,
failure isolation (constitution III), the official record and old records (tasks T018)."""

from dataclasses import replace

import pytest

from sweetspot.config import Preferences
from sweetspot.decision import bundles as bundle_rule
from sweetspot.decision import engine
from sweetspot.decision.changes import compare
from sweetspot.decision.contract import batch_to_dict
from sweetspot.decision.engine import run_decisions
from sweetspot.decision.records import load_record, write_record
from sweetspot.forecast.models import build_model
from sweetspot.store.query import PriceStore
from tests.forecast_builders import BASIC_CALENDAR, GameSpec, add_purchase_options, add_version, build_db, dt

AS_OF = dt("2025-08-01")
CUTS = [("2024-12-11", 0), ("2024-12-19T18:00", 50), ("2025-01-02T18:00", 0), ("2025-03-13T17:00", 50),
        ("2025-03-20T17:00", 0), ("2025-06-26T17:00", 50), ("2025-07-10T17:00", 0)]
DEFAULT = dict(kind="sub", option_id=100, name="Standard", original_cents=50000, final_cents=50000, role="default")
PAIR = dict(kind="bundle", option_id=900, name="Game 1 x Game 2", original_cents=90000, final_cents=90000,
            role="other-games", bundle_discount_pct=10, before_bundle_cents=100000,
            contents=[{"app_id": 1, "type": None, "parent_app_id": None},
                      {"app_id": 2, "type": 0, "parent_app_id": None}])
BATCH_KEYS = {"id", "name", "checked_at", "grade", "discount_pct", "price_cents", "price_twd", "contents", "check",
              "separate_cents", "separate_twd", "wishlist_cents", "wishlist_twd", "extra_cents", "extra_twd",
              "extra_games", "extra_dlc", "extra_game_names", "plan", "advice", "owned_note"}
ADVICE_KEYS = {"status", "reason_code", "reason_text", "kind", "sale", "levels", "estimate_cents", "estimate_twd",
               "joint_probability", "saving_cents", "saving_twd", "timing", "hit_rate", "confidence", "text"}


@pytest.fixture
def store(db_path):
    build_db(db_path, [GameSpec(a, tw=CUTS, us=CUTS, name=f"Game {a}", wishlist=True) for a in (1, 2, 3)],
             calendar=BASIC_CALENDAR)
    for a in (1, 2, 3):
        add_version(db_path, a, "2025-07-31", external_id=f"itad-{a}", package_id=100, package_name="Standard")
    add_purchase_options(db_path, 1, "2025-07-31", [DEFAULT, PAIR])
    add_purchase_options(db_path, 2, "2025-07-31", [DEFAULT, {**PAIR, "is_default": False}])
    s = PriceStore.open(db_path)
    yield s
    s.close()


def decide(store, choices=None):
    return run_decisions(store, store.wishlist_apps(), AS_OF, build_model("seasonal-record"), Preferences(),
                         now=AS_OF, choices=choices)


def test_batch_and_decisions_carry_the_bundle_fields(store):
    data = batch_to_dict(decide(store))
    assert data["bundle_rule"] == {"name": "bundle-advice", "version": "1.0.0"}
    [b] = data["bundles"]
    assert set(b) == BATCH_KEYS and b["id"] == 900 and b["grade"] == "pure"
    assert set(b["advice"]) == ADVICE_KEYS
    assert {d["app_id"]: d["bundles"] for d in data["decisions"]} == {1: [900], 2: [900], 3: []}


def test_no_purchase_option_record_means_unknown(db_path):
    build_db(db_path, [GameSpec(1, tw=CUTS, us=CUTS, wishlist=True)], calendar=BASIC_CALENDAR)
    s = PriceStore.open(db_path)
    try:
        data = batch_to_dict(decide(s))
    finally:
        s.close()
    assert data["bundles"] is None and data["decisions"][0]["bundles"] is None


def test_a_failing_step_leaves_the_decisions_alone(store, monkeypatch):
    before = batch_to_dict(decide(store))

    def boom(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(bundle_rule, "build_bundles", boom)
    after = batch_to_dict(decide(store))
    assert after["bundles"] is None and all(d["bundles"] is None for d in after["decisions"])
    strip = lambda data: [{k: v for k, v in d.items() if k != "bundles"} for d in data["decisions"]]  # noqa: E731
    assert strip(after) == strip(before)


def test_one_failing_bundle_keeps_the_rest(store, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(bundle_rule, "_advise", boom)
    [b] = batch_to_dict(decide(store))["bundles"]
    assert (b["advice"]["status"], b["advice"]["reason_code"]) == ("none", "error")


def test_the_official_record_keeps_the_bundles(store, tmp_path):
    data = batch_to_dict(decide(store))
    loaded = load_record(write_record(tmp_path, data))
    assert loaded["bundles"] == data["bundles"] and loaded["bundle_rule"] == data["bundle_rule"]


def test_old_records_without_the_fields_still_compare(store):
    data = batch_to_dict(decide(store))
    old = {k: v for k, v in data.items() if k not in ("bundles", "bundle_rule")}
    old["decisions"] = [{k: v for k, v in d.items() if k != "bundles"} for d in data["decisions"]]
    changes, _ = compare(data, old, file="old.json.gz", as_of=old["as_of"])
    assert not any(changes.values())


def test_engine_only_reads_the_finished_decisions(store, monkeypatch):
    """The rule never changes a decision: every decision field but `bundles` equals a run without bundles."""
    seen = {}
    real = bundle_rule.build_bundles

    def spy(records, decisions, forecasts, **kw):
        seen["decisions"] = [replace(d) for d in decisions]
        return real(records, decisions, forecasts, **kw)

    monkeypatch.setattr(bundle_rule, "build_bundles", spy)
    batch = decide(store)
    assert [replace(d, bundles=None) for d in batch.decisions] == [replace(d, bundles=None) for d in seen["decisions"]]
    assert engine.BUNDLE_RULE == {"name": "bundle-advice", "version": "1.0.0"}
