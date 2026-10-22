"""contracts/store-api-additions.md: history_known_until, series_rows, itad_mapping_state, sample_pools."""

import sqlite3
from datetime import timedelta

import pytest

from sweetspot.store.query import OldDatabaseError, PriceStore
from sweetspot.store.writer import NewObservation
from tests.forecast_builders import GameSpec, add_history, build_db, dt

ITAD_SOURCES = ("itad-history", "legacy-itad")


def _current(app_id: int, when: str, cut: int) -> NewObservation:
    return NewObservation(app_id=app_id, source="steam-current", region="TW", currency="TWD", regular_cents=50000,
                          price_cents=50000 * (100 - cut) // 100, cut_pct=cut, observed_at=dt(when),
                          raw_observed_at=None, retrieved_at=dt(when))


@pytest.fixture
def store(db_path):
    games = [
        GameSpec(1, tw=[("2024-12-11", 0), ("2025-03-13T17:00", 60), ("2025-03-20T17:00", 0)],
                 us=[("2019-01-01", 0), ("2025-03-13T17:00", 60)], known_until={"TW": "2026-09-20", "US": "2026-09-21"},
                 extra_tw=[_current(1, "2026-09-24T10:00", 0)], wishlist=True),
        GameSpec(2, tw=[("2024-12-11", 10), ("2025-06-26T17:00", 50)], source="legacy-itad", pool="broad"),
        GameSpec(3, tw=[("2024-12-11", 0), ("2025-01-10", 30)], mapping="rejected", pool="related-publisher"),
        GameSpec(4, first_seen_via="legacy-import"),
    ]
    build_db(db_path, games)
    s = PriceStore.open(db_path)
    yield s
    s.close()


def test_history_known_until_uses_latest_fetch_or_legacy_retrieval(store):
    assert store.history_known_until(1, "TW") == dt("2026-09-20")
    assert store.history_known_until(1, "US") == dt("2026-09-21")
    assert store.history_known_until(2, "TW") == dt("2026-09-24")   # legacy-itad retrieved_at
    assert store.history_known_until(2, "US") is None
    assert store.history_known_until(4, "TW") is None


def test_series_rows_excludes_steam_current_and_future(store):
    as_of = dt("2025-03-15")
    rows = store.series_rows([1, 2, 3], "TW", as_of)
    assert set(rows) == {1, 2, 3}
    for app_id, obs in rows.items():
        assert all(o.observed_at <= as_of for o in obs)
        assert all(o.source in ITAD_SOURCES for o in obs)
        expected = [o for o in store.observations(app_id, as_of, "TW") if o.source in ITAD_SOURCES]
        assert obs == expected
    assert [o.cut_pct for o in rows[1]] == [0, 60]


def test_series_rows_matches_observations_at_many_points(store):
    start = dt("2024-12-01")
    for step in range(0, 700, 37):
        as_of = start + timedelta(days=step)
        for region in ("TW", "US"):
            rows = store.series_rows([1, 2, 3, 4], region, as_of)
            for app_id in (1, 2, 3, 4):
                expected = [o for o in store.observations(app_id, as_of, region) if o.source in ITAD_SOURCES]
                assert rows.get(app_id, []) == expected


def test_itad_mapping_state_is_latest_verification(store):
    assert store.itad_mapping_state(1) == "verified"
    assert store.itad_mapping_state(3) == "rejected"


def test_sample_pools_priority(store):
    pools = store.sample_pools()
    assert pools[1] == "wishlist"
    assert pools[2] == "broad"
    assert pools[3] == "related"
    assert pools[4] == "legacy"


def test_new_methods_do_not_write(store):
    before = store.conn.total_changes
    store.history_known_until(1, "TW")
    store.series_rows([1, 2], "TW", dt("2026-01-01"))
    store.itad_mapping_state(1)
    store.sample_pools()
    assert store.conn.total_changes == before


# --- feature 006: reading one ITAD product per app (data-model §4) ----------------------------------------------

@pytest.fixture
def two_versions(db_path):
    """App 1: own product itad-1 (cuts 0/60) and another product itad-new (cuts 0/80, fetched later).
    App 5: own rows written before 006 (external_id NULL)."""
    games = [
        GameSpec(1, tw=[("2024-12-11", 0), ("2025-03-13T17:00", 60)], us=[("2024-12-11", 0)],
                 known_until={"TW": "2026-09-20", "US": "2026-09-20"}, wishlist=True,
                 extra_tw=[_current(1, "2026-09-24T10:00", 0)]),
        GameSpec(5, tw=[("2024-12-11", 0), ("2025-06-26T17:00", 40)], external_id="itad-5"),
    ]
    build_db(db_path, games)
    add_history(db_path, 1, "itad-new", tw=[("2025-06-26", 0), ("2025-09-29T17:00", 80)],
                us=[("2025-06-26", 0), ("2025-09-29T17:00", 80)], regular_cents=67000, fetched="2026-09-25")
    conn = sqlite3.connect(db_path)          # app 5's rows as a pre-006 database left them
    conn.execute("DROP TRIGGER trg_price_observations_no_update")
    conn.execute("UPDATE price_observations SET external_id = NULL WHERE app_id = 5")
    conn.execute("UPDATE history_fetches SET external_id = NULL WHERE app_id = 5")
    conn.commit()
    conn.close()
    s = PriceStore.open(db_path)
    yield s
    s.close()


def test_own_keys_are_the_latest_itad_mapping(two_versions):
    assert two_versions.own_keys([1, 5, 99]) == {1: "itad-1", 5: "itad-5", 99: None}


def test_series_rows_filtered_by_key(two_versions):
    as_of = dt("2026-09-26")
    new = two_versions.series_rows([1], "TW", as_of, keys={1: "itad-new"})[1]
    assert [(o.cut_pct, o.regular_cents) for o in new] == [(0, 67000), (80, 67000)]
    own = two_versions.series_rows([1], "TW", as_of, keys={1: "itad-1"})[1]
    assert [o.cut_pct for o in own] == [0, 60]
    mixed = two_versions.series_rows([1], "TW", as_of)[1]      # no keys: v2 behaviour, every row
    assert len(mixed) == 4
    us = two_versions.series_rows([1], "US", as_of, keys={1: "itad-new"})[1]
    assert [o.cut_pct for o in us] == [0, 80]


def test_null_rows_count_as_the_apps_own_product(two_versions):
    as_of = dt("2026-09-26")
    assert [o.cut_pct for o in two_versions.series_rows([5], "TW", as_of, keys={5: "itad-5"})[5]] == [0, 40]
    assert two_versions.series_rows([5], "TW", as_of, keys={5: "itad-other"}).get(5, []) == []
    assert two_versions.history_known_until_all("TW", keys={5: "itad-5"})[5] == dt("2025-06-27T17:00")


def test_known_until_follows_the_product(two_versions):
    assert two_versions.history_known_until_all("TW", keys={1: "itad-new"})[1] == dt("2026-09-25")
    assert two_versions.history_known_until_all("TW", keys={1: "itad-1"})[1] == dt("2026-09-20")
    assert two_versions.history_known_until_all("TW")[1] == dt("2026-09-25")   # no keys: v2 behaviour


def test_own_keys_reproduce_the_v2_series(store):
    as_of = dt("2026-09-26")
    keys = store.own_keys([1, 2, 3, 4])
    for region in ("TW", "US"):
        assert store.series_rows([1, 2, 3, 4], region, as_of, keys=keys) == store.series_rows([1, 2, 3, 4], region, as_of)
        assert store.history_known_until_all(region, keys=keys) == store.history_known_until_all(region)


def test_latest_observations_ignore_other_products(two_versions):
    as_of = dt("2025-10-01")
    latest = two_versions.latest_observations([1], "TW", as_of, keys={1: "itad-1"})[1]
    assert latest.cut_pct == 60                   # itad-new's -80% is another product
    latest = two_versions.latest_observations([1], "TW", as_of, keys={1: "itad-new"})[1]
    assert latest.cut_pct == 80
    now = two_versions.latest_observations([1], "TW", dt("2026-09-26"), keys={1: "itad-new"})[1]
    assert now.source == "steam-current"          # store snapshots are never filtered


def test_old_database_is_refused_by_read_only_store(db_path):
    build_db(db_path, [GameSpec(1)])
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE schema_meta SET value = '2' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()
    with pytest.raises(OldDatabaseError, match="資料庫是舊版（v2），請先執行 sweetspot update 升級"):
        PriceStore.open(db_path)


# --- feature 009: an edition's history under its own source (research R3) -------------------------------------

OPTION = "itad-option-history"


@pytest.fixture
def with_edition(db_path):
    """App 1: own product itad-1 and a Steam snapshot on 2026-09-24; an edition itad-ult whose history (source
    itad-option-history) has rows NEWER than the snapshot, the case P3 showed would be read as the store price."""
    games = [GameSpec(1, tw=[("2024-12-11", 0), ("2025-03-13T17:00", 60), ("2025-03-20T17:00", 0)],
                      us=[("2024-12-11", 0)], known_until={"TW": "2026-09-20", "US": "2026-09-20"}, wishlist=True,
                      extra_tw=[_current(1, "2026-09-24T10:00", 0)])]
    build_db(db_path, games)
    add_history(db_path, 1, "itad-ult", tw=[("2024-12-11", 0), ("2026-09-25T00:00", 70)],
                us=[("2024-12-11", 0), ("2026-09-25T00:00", 70)], regular_cents=220600, fetched="2026-09-26",
                source=OPTION, fetch_source="itad-option")
    s = PriceStore.open(db_path)
    yield s
    s.close()


def test_edition_rows_are_never_read_as_the_store_price(with_edition):
    as_of = dt("2026-09-26")
    latest = with_edition.latest_observations([1], "TW", as_of, keys={1: "itad-1"})[1]
    assert latest.source == "steam-current" and latest.cut_pct == 0
    unkeyed = with_edition.latest_observations([1], "TW", as_of)[1]
    assert unkeyed.source == "steam-current"
    assert OPTION not in {o.source for o in with_edition.observations(1, as_of, "TW", keys={1: "itad-1"})}
    assert OPTION not in {o.source for o in with_edition.observations(1, as_of, "TW")}


def test_edition_rows_are_read_only_when_asked_for_with_their_key(with_edition):
    as_of = dt("2026-09-26")
    latest = with_edition.latest_observations([1], "TW", as_of, keys={1: "itad-ult"})[1]
    assert (latest.source, latest.cut_pct) == (OPTION, 70)        # newer than the snapshot: the edition's price
    assert OPTION not in {o.source for o in with_edition.series_rows([1], "TW", as_of)[1]}
    assert OPTION not in {o.source for o in with_edition.series_rows([1], "TW", as_of, keys={1: "itad-1"})[1]}
    rows = with_edition.series_rows([1], "TW", as_of, keys={1: "itad-ult"}, sources=(OPTION,))[1]
    assert [(o.source, o.cut_pct, o.regular_cents) for o in rows] == [(OPTION, 0, 220600), (OPTION, 70, 220600)]
    assert with_edition.series_rows([1], "TW", as_of, keys={1: "itad-1"}, sources=(OPTION,)).get(1, []) == []


def test_build_series_accepts_the_edition_source(with_edition):
    from sweetspot.forecast.series import build_series
    as_of = dt("2026-09-26")
    rows = with_edition.series_rows([1], "TW", as_of, keys={1: "itad-ult"}, sources=(OPTION,))[1]
    series = build_series(rows, "TW", as_of)
    assert [(s.cut, s.regular_cents) for s in series.states] == [(0, 220600), (70, 220600)]


def test_known_until_of_an_edition_counts_only_its_fetches(with_edition):
    assert with_edition.history_known_until_all("TW", keys={1: "itad-ult"})[1] == dt("2026-09-26")
    assert with_edition.history_known_until_all("TW", keys={1: "itad-1"})[1] == dt("2026-09-20")
