"""feature 009 (data-model §4): purchase-option records and edition lows, point in time."""

import pytest

from sweetspot.store.query import ITAD_SOURCES, OPTION_HISTORY_SOURCE, PriceStore
from tests.forecast_builders import GameSpec, add_history, add_purchase_options, build_db, dt

CP = 1091500
DEFAULT = dict(kind="sub", option_id=367653, name="Cyberpunk 2077", original_cents=159900, final_cents=159900,
               role="default")
ULT = dict(kind="bundle", option_id=32470, name="終極版", original_cents=220600, final_cents=220600, role="edition",
           external_id="itad-ult", verification="verified", verified_by="version-check", verified_at="2026-09-20")
MIXED = dict(kind="bundle", option_id=77855, name="Two games", original_cents=55600, final_cents=55600,
             role="other-games")


@pytest.fixture
def store(db_path):
    build_db(db_path, [GameSpec(CP, tw=[("2024-12-11", 0), ("2025-06-26T17:00", 70), ("2025-07-10T17:00", 0)],
                                wishlist=True)])
    add_purchase_options(db_path, CP, "2026-09-20", [DEFAULT, ULT])
    add_purchase_options(db_path, CP, "2026-09-26", [DEFAULT, {**ULT, "final_cents": 88200}, MIXED])
    add_history(db_path, CP, "itad-ult", tw=[("2024-12-11", 0, 220600), ("2025-06-26T17:00", 60, 220600),
                                             ("2025-07-10T17:00", 0, 220600)], regular_cents=220600,
                fetched="2026-09-26", source=OPTION_HISTORY_SOURCE, fetch_source="itad-option")
    s = PriceStore.open(db_path)
    yield s
    s.close()


def test_latest_step_at_or_before_as_of(store):
    now = store.purchase_options([CP, 99], dt("2026-09-27"))
    assert 99 not in now
    assert [(r.kind, r.option_id, r.role, r.final_cents) for r in now[CP]] == [
        ("sub", 367653, "default", 159900), ("bundle", 32470, "edition", 88200), ("bundle", 77855, "other-games", 55600)]
    ult = now[CP][1]
    assert (ult.external_id, ult.verification, ult.is_default, ult.position) == ("itad-ult", "verified", False, 1)
    assert ult.checked_at == dt("2026-09-26")


def test_no_leak_from_later_steps(store):
    """A step recorded after as_of is invisible; this test fails if the as_of filter is dropped."""
    before = store.purchase_options([CP], dt("2026-09-21"))
    assert [(r.option_id, r.final_cents) for r in before[CP]] == [(367653, 159900), (32470, 220600)]
    assert store.purchase_options([CP], dt("2026-09-19")) == {}


def test_bundle_discount_and_contents_round_trip(db_path):
    """feature 010 (data-model §1): the two v5 columns and each content's final_cents are stored and read back;
    rows written without them read back as None (unknown, not 0)."""
    build_db(db_path, [GameSpec(1903340, tw=[("2025-01-23", 0)], wishlist=True)])
    contents = [{"app_id": 1903340, "type": None, "parent_app_id": None, "final_cents": 79000},
                {"app_id": 2592160, "type": 0, "parent_app_id": None, "final_cents": None}]
    pair = dict(kind="bundle", option_id=74895, name="E33 x Dispatch", original_cents=132800, final_cents=115000,
                role="other-games", contents=contents, bundle_discount_pct=10, before_bundle_cents=147600)
    old = dict(kind="bundle", option_id=53645, name="E33 + Sifu", original_cents=140100, final_cents=122300,
               role="other-games")
    add_purchase_options(db_path, 1903340, "2026-09-27", [pair, old])
    s = PriceStore.open(db_path)
    try:
        rows = s.purchase_options([1903340], dt("2026-09-28"))[1903340]
    finally:
        s.close()
    new, before = rows
    assert (new.bundle_discount_pct, new.before_bundle_cents, new.contents) == (10, 147600, contents)
    assert (before.bundle_discount_pct, before.before_bundle_cents, before.contents) == (None, None, None)


def test_edition_lows_read_the_edition_rows(store):
    lows = store.option_lows([(CP, "itad-ult", OPTION_HISTORY_SOURCE)], dt("2026-09-27"))
    low = lows[(CP, "itad-ult")]
    assert (low.low_cents, low.low_at, low.first_at) == (88240, dt("2025-06-26T17:00"), dt("2024-12-11"))


def test_default_version_lows_read_the_default_history(store):
    lows = store.option_lows([(CP, f"itad-{CP}", ITAD_SOURCES[0])], dt("2026-09-27"))
    assert lows[(CP, f"itad-{CP}")].low_cents == 15000          # -70% of NT$500 in the default history


def test_no_history_is_none_not_zero(store):
    assert store.option_lows([(CP, "itad-none", OPTION_HISTORY_SOURCE)], dt("2026-09-27")) == {}


# --- US1: what a choice resolves to (research R4) -------------------------------------------------------------

def test_a_verified_edition_becomes_the_users_key(store):
    defaults = store.history_keys([CP], dt("2026-09-27"))
    got = store.option_keys({CP: ("bundle", 32470)}, dt("2026-09-27"), defaults)[CP]
    assert (got.source, got.key.basis, got.key.external_id, got.same_as_default) == ("user", "user", "itad-ult", False)
    assert got.record.option_id == 32470 and got.fallback_code is None and not got.key.stopped


def test_choosing_the_steam_default_keeps_the_default_history(store):
    defaults = store.history_keys([CP], dt("2026-09-27"))
    got = store.option_keys({CP: ("sub", 367653)}, dt("2026-09-27"), defaults)[CP]
    assert (got.source, got.same_as_default) == ("user", True)
    assert got.key == defaults[CP]


def test_an_edition_on_the_default_product_uses_the_default_rows(db_path):
    build_db(db_path, [GameSpec(CP, tw=[("2024-12-11", 0)], wishlist=True)])
    add_purchase_options(db_path, CP, "2026-09-26", [DEFAULT, {**ULT, "external_id": f"itad-{CP}"}])
    s = PriceStore.open(db_path)
    defaults = s.history_keys([CP], dt("2026-09-27"))
    got = s.option_keys({CP: ("bundle", 32470)}, dt("2026-09-27"), defaults)[CP]
    assert got.same_as_default and got.key.external_id == f"itad-{CP}"
    s.close()


def test_the_choice_stays_when_steam_changes_its_default(store, db_path):
    add_purchase_options(db_path, CP, "2026-09-28", [{**DEFAULT, "role": "edition", "is_default": False,
                                                      "external_id": "itad-std", "verification": "verified",
                                                      "verified_by": "version-check", "verified_at": "2026-09-28"},
                                                     {**ULT, "role": "default", "is_default": True,
                                                      "external_id": None, "verification": None, "verified_by": None,
                                                      "verified_at": None}])
    s = PriceStore.open(db_path)
    defaults = s.history_keys([CP], dt("2026-09-29"))
    got = s.option_keys({CP: ("sub", 367653)}, dt("2026-09-29"), defaults)[CP]
    assert (got.source, got.key.external_id) == ("user", "itad-std")     # still the chosen package (FR-006)
    s.close()


def test_a_stopped_edition_is_capped_not_dropped(db_path):
    build_db(db_path, [GameSpec(CP, tw=[("2024-12-11", 0)], wishlist=True)])
    add_history(db_path, CP, "itad-ult", tw=[("2024-12-11", 0, 220600), ("2025-06-26T17:00", 60, 220600)],
                regular_cents=220600, fetched="2026-09-26", source=OPTION_HISTORY_SOURCE, fetch_source="itad-option")
    add_purchase_options(db_path, CP, "2026-09-20", [DEFAULT, {**ULT, "itad_steam_deals": 1}])
    add_purchase_options(db_path, CP, "2026-09-26", [DEFAULT, {**ULT, "itad_steam_deals": 0}])
    s = PriceStore.open(db_path)
    got = s.option_keys({CP: ("bundle", 32470)}, dt("2026-09-27"), s.history_keys([CP], dt("2026-09-27")))[CP]
    assert got.source == "user" and got.key.stopped
    assert got.key.last_confirmed == dt("2026-09-20")          # the last step that still saw a Steam price
    s.close()


# --- US3: choices that cannot be used fall back to the Steam default (research R4) -----------------------------

REJECTED = dict(kind="sub", option_id=1265945, name="Definitive", original_cents=74900, final_cents=74900,
                role="edition", external_id="itad-def", verification="rejected", verified_by="version-check",
                verified_at="2026-09-26", reason_code="bundle", reason_detail="bundle/47759")
NO_ITAD = dict(kind="bundle", option_id=77856, name="豪華版", original_cents=83700, final_cents=83700, role="edition")


@pytest.mark.parametrize("choice,code,detail", [
    (("sub", 1), "not-offered", None),
    (("bundle", 77855), "not-edition", "還包含其他遊戲"),
    (("bundle", 77856), "not-in-itad", None),
    (("sub", 1265945), "rejected", "ITAD 的商品還對應到組合包 bundle/47759，價格歷史可能混了組合包的價格"),
])
def test_fallbacks(store, db_path, choice, code, detail):
    add_purchase_options(db_path, CP, "2026-09-27", [DEFAULT, ULT, MIXED, NO_ITAD, REJECTED])
    s = PriceStore.open(db_path)
    defaults = s.history_keys([CP], dt("2026-09-28"))
    got = s.option_keys({CP: choice}, dt("2026-09-28"), defaults)[CP]
    assert (got.source, got.fallback_code, got.fallback_detail) == ("user-fallback", code, detail)
    assert got.key == defaults[CP] and got.requested == choice
    s.close()


def test_no_record_before_the_first_step(store):
    defaults = store.history_keys([CP], dt("2026-09-19"))
    got = store.option_keys({CP: ("bundle", 32470)}, dt("2026-09-19"), defaults)[CP]
    assert (got.source, got.fallback_code) == ("user-fallback", "no-record")


def test_a_missed_step_keeps_the_last_record_and_its_time(store):
    """FR-009: nothing is written on a source error; the last step (2026-09-26) still decides, with its time."""
    got = store.option_keys({CP: ("bundle", 32470)}, dt("2026-09-30"), store.history_keys([CP], dt("2026-09-30")))[CP]
    assert got.source == "user" and got.record.checked_at == dt("2026-09-26")


# --- feature 013: one option's daily rows over a period (tasks T002) -------------------------------------------

def test_option_steps_lists_one_option_over_a_period(store, db_path):
    add_purchase_options(db_path, CP, "2026-09-28", [DEFAULT, {**ULT, "final_cents": 99300}])
    add_purchase_options(db_path, CP, "2026-09-30", [DEFAULT, {**ULT, "final_cents": 88200}])
    add_purchase_options(db_path, 99, "2026-09-28", [{**ULT, "final_cents": 1}])
    got = store.option_steps(CP, "bundle", 32470, dt("2026-09-26"), dt("2026-09-30"))
    assert [(r.checked_at, r.final_cents) for r in got] == [(dt("2026-09-26"), 88200), (dt("2026-09-28"), 99300)]
    assert all(r.kind == "bundle" and r.option_id == 32470 and r.app_id == CP for r in got)


def test_option_steps_without_rows_is_empty(store):
    assert store.option_steps(CP, "sub", 1, dt("2026-09-01"), dt("2026-10-01")) == []
    assert store.option_steps(CP, "bundle", 32470, dt("2026-10-01"), dt("2026-10-08")) == []
