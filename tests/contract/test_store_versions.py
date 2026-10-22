"""feature 006 data-model §4: which ITAD product each app reads at a point in time."""

import pytest

from sweetspot.store.query import PriceStore
from tests.forecast_builders import GameSpec, add_history, add_version, build_db, dt


@pytest.fixture
def store(db_path):
    build_db(db_path, [GameSpec(1, tw=[("2024-12-11", 0), ("2025-01-27", 70)], wishlist=True),
                       GameSpec(2, tw=[("2024-12-11", 0)], wishlist=True),
                       GameSpec(3, tw=[("2024-12-11", 0)], wishlist=True),
                       GameSpec(4, tw=[("2024-12-11", 0)])])
    add_history(db_path, 1, "itad-new", tw=[("2025-06-26", 80), ("2025-07-10", 0)], regular_cents=67000)
    add_version(db_path, 1, "2026-09-27T01:00", external_id="itad-new", package_name="Essentials")
    add_version(db_path, 2, "2026-09-27T01:00", external_id="itad-2b", verification="rejected",
                reason_code="bundle", reason_detail="bundle/99003")
    add_version(db_path, 3, "2026-09-27T01:00", external_id=None, status="ambiguous")
    s = PriceStore.open(db_path)
    yield s
    s.close()


AFTER, BEFORE = dt("2026-09-28"), dt("2026-09-26")


def test_versions_are_the_latest_row_at_or_before_as_of(store):
    got = store.versions([1, 2, 3, 4], AFTER)
    assert set(got) == {1, 2, 3}
    assert (got[1].external_id, got[1].package_name, got[1].checked_at) == ("itad-new", "Essentials",
                                                                           dt("2026-09-27T01:00"))
    assert store.versions([1], BEFORE) == {}


def test_history_keys_basis(store):
    keys = store.history_keys([1, 2, 3, 4], AFTER)
    assert (keys[1].external_id, keys[1].basis, keys[1].basis_reason) == ("itad-new", "version", None)
    assert (keys[2].external_id, keys[2].basis) == ("itad-2b", "rejected")
    assert (keys[3].external_id, keys[3].basis, keys[3].basis_reason) == ("itad-3", "own", "ambiguous")
    assert (keys[4].external_id, keys[4].basis, keys[4].basis_reason) == ("itad-4", "own", "no-record")


def test_series_follow_the_key(store):
    ids = store.key_ids(store.history_keys([1], AFTER))
    rows = store.series_rows([1], "TW", AFTER, keys=ids)[1]
    assert [(r.cut_pct, r.regular_cents) for r in rows] == [(80, 67000), (0, 67000)]


def test_no_future_version_leaks_into_an_earlier_as_of(store):
    """Before the first version row the app reads its own product, even though a later row exists."""
    keys = store.history_keys([1], BEFORE)
    assert (keys[1].external_id, keys[1].basis, keys[1].basis_reason) == ("itad-1", "own", "no-record")
    rows = store.series_rows([1], "TW", AFTER, keys=store.key_ids(keys))[1]
    assert [r.cut_pct for r in rows] == [0, 70]


def test_the_leak_test_catches_a_peeking_query(store, monkeypatch):
    """Proof that the test above can fail: a versions() that ignores as_of is caught."""
    real = PriceStore.versions

    def peeking(self, app_ids, as_of):
        return real(self, app_ids, dt("2100-01-01"))

    monkeypatch.setattr(PriceStore, "versions", peeking)
    keys = store.history_keys([1], BEFORE)
    assert keys[1].basis == "version"          # the peek is visible, so the real test would fail


# --- US2: version changes and stopped tracking (data-model §1) ---------------------------------------------------

@pytest.fixture
def history_db(db_path):
    build_db(db_path, [GameSpec(1, tw=[("2024-12-11", 0), ("2025-01-27", 70)], wishlist=True,
                                known_until={"TW": "2026-09-20"})])
    add_history(db_path, 1, "itad-b", tw=[("2025-06-26", 80)], regular_cents=67000, fetched="2026-09-25")
    return db_path


def keys_at(db_path, when):
    s = PriceStore.open(db_path)
    try:
        return s.history_keys([1], dt(when))[1]
    finally:
        s.close()


def test_first_row_unlike_the_own_mapping_is_a_change(history_db):
    add_version(history_db, 1, "2026-09-27T01:00", external_id="itad-b", package_name="Essentials")
    change = keys_at(history_db, "2026-09-28").change
    assert (change.from_itad_id, change.from_title, change.to_itad_id, change.to_title, change.detected_at) == (
        "itad-1", None, "itad-b", "Essentials", dt("2026-09-27T01:00"))


def test_same_product_as_own_is_no_change_and_package_changes_are_not_changes(history_db):
    add_version(history_db, 1, "2026-09-27T01:00", external_id="itad-1", package_id=10)
    add_version(history_db, 1, "2026-09-28T01:00", external_id="itad-1", package_id=11)
    assert keys_at(history_db, "2026-09-29").change is None


def test_back_and_forth_is_recorded_each_time(history_db):
    add_version(history_db, 1, "2026-09-27T01:00", external_id="itad-b", package_name="B")
    add_version(history_db, 1, "2026-09-28T01:00", external_id="itad-1", package_name="A")
    change = keys_at(history_db, "2026-09-29").change
    assert (change.from_itad_id, change.to_itad_id, change.detected_at) == ("itad-b", "itad-1", dt("2026-09-28T01:00"))
    assert keys_at(history_db, "2026-09-27T12:00").change.to_itad_id == "itad-b"      # as of that day


def test_unconfirmed_rows_do_not_count_as_changes(history_db):
    add_version(history_db, 1, "2026-09-27T01:00", external_id="itad-1")
    add_version(history_db, 1, "2026-09-28T01:00", external_id=None, status="ambiguous")
    key = keys_at(history_db, "2026-09-29")
    assert key.basis == "own" and key.change is None


def test_stopped_tracking_caps_known_until_at_the_last_confirmation(history_db):
    add_version(history_db, 1, "2026-09-25T01:00", external_id="itad-1", itad_steam_deals=0)
    key = keys_at(history_db, "2026-09-26")
    assert key.stopped and key.last_confirmed == dt("2025-01-27")        # only the last observation
    s = PriceStore.open(history_db)
    try:
        known = s.capped_known_until(s.history_known_until_all("TW", keys={1: "itad-1"}), {1: key})
    finally:
        s.close()
    assert known[1] == dt("2025-01-27")


def test_last_confirmation_includes_rows_that_still_saw_a_steam_price(history_db):
    add_version(history_db, 1, "2026-09-24T01:00", external_id="itad-1", itad_steam_deals=1)
    add_version(history_db, 1, "2026-09-25T01:00", external_id="itad-1", itad_steam_deals=0)
    key = keys_at(history_db, "2026-09-26")
    assert key.stopped and key.last_confirmed == dt("2026-09-24T01:00")


def test_unknown_deal_count_or_no_store_price_is_not_stopped(history_db):
    add_version(history_db, 1, "2026-09-25T01:00", external_id="itad-1", itad_steam_deals=None)
    assert not keys_at(history_db, "2026-09-26").stopped
    add_version(history_db, 1, "2026-09-26T01:00", external_id="itad-1", itad_steam_deals=0, price_cents=None)
    assert not keys_at(history_db, "2026-09-27").stopped


def test_old_price_checks_do_not_stop_anything(history_db):
    """FR-016: only version rows decide; pre-006 current_price_checks without a Steam price change nothing."""
    import sqlite3

    conn = sqlite3.connect(history_db)
    conn.execute("INSERT INTO current_price_checks (run_id, app_id, match, checked_at) VALUES "
                 "('r', 1, NULL, '2026-09-24T00:00:00.000000Z')")
    conn.commit()
    conn.close()
    key = keys_at(history_db, "2026-09-26")
    assert not key.stopped and key.basis == "own"
