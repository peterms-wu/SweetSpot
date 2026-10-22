"""research R6: backtest dataset, schedules and per-region ids (tasks T024)."""

from dataclasses import replace

import pytest

from sweetspot.forecast.backtest.dataset import build_dataset, default_cutoff
from sweetspot.forecast.engine import all_apps, load_games
from sweetspot.forecast.series import PriceSeries
from sweetspot.store.query import PriceStore
from tests.forecast_builders import BASIC_CALENDAR, GameSpec, build_db, dt

CUTOFF = dt("2026-09-24")
TW = [("2024-12-11", 0), ("2025-03-13T17:00", 50), ("2025-03-20T17:00", 0)]
US = [("2023-01-01", 0), ("2023-07-01", 60), ("2023-07-10", 0), ("2024-01-01", 0)]


def make(db_path, tw_extra=(), us_extra=()):
    games = [
        GameSpec(1, tw=TW + list(tw_extra), us=US + list(us_extra), wishlist=True),
        GameSpec(2, tw=TW, pool="related-developer"),
        GameSpec(3, tw=TW, us=US, pool="broad"),
        GameSpec(4, tw=TW, first_seen_via="legacy-import", source="legacy-itad"),
        GameSpec(5, tw=[("2024-12-11", 0)], regular_cents=0),           # free at the cutoff
        GameSpec(6, tw=TW, product_type="bundle"),
        GameSpec(7),                                                    # no history
    ]
    build_db(db_path, games, calendar=BASIC_CALENDAR)
    return PriceStore.open(db_path)


def dataset_for(store, **kw):
    games = load_games(store, all_apps(store), kw.get("cutoff", CUTOFF))
    events = store.sales(kw.get("cutoff", CUTOFF), include_estimates=False)
    return build_dataset(store, games, events, **{"cutoff": CUTOFF, **kw}), games, events


@pytest.fixture
def store(db_path):
    s = make(db_path)
    yield s
    s.close()


def test_eligible_apps_and_pools(store):
    ds, _, _ = dataset_for(store)
    assert ds.regions["TW"].apps == (1, 2, 3, 4)
    assert ds.regions["US"].apps == (1, 3)
    assert ds.pools == {1: "wishlist", 2: "related", 3: "broad", 4: "legacy"}


def test_schedules(store):
    ds, _, _ = dataset_for(store)
    tw = ds.regions["TW"].schedule
    assert tw[0] == dt("2025-02-01")              # first ended TW sale in the data: winter 2024 (ends 01-02)
    assert tw[-1] == dt("2026-09-01")             # last month start before the cutoff
    assert all(a < b for a, b in zip(tw, tw[1:]))
    us = ds.regions["US"].schedule
    assert us[0] == dt("2023-08-01")              # summer 2023 ends 07-13 (series starts 2023-01-01)
    assert us[-1] == dt("2025-09-01")             # cutoff − 12 months, floored to a month start


def test_default_cutoff_is_latest_known_until_floored_to_the_day(store):
    assert default_cutoff(store) == dt("2026-09-24")   # latest: the legacy import retrieval of app 4


def test_apps_limit_changes_the_ids(store):
    full, _, _ = dataset_for(store)
    small, _, _ = dataset_for(store, apps_limit=2)
    assert small.regions["TW"].apps == (1, 2)
    assert small.regions["TW"].dataset_id != full.regions["TW"].dataset_id


def test_ids_are_stable_and_region_scoped(store):
    a, games, events = dataset_for(store)
    b, _, _ = dataset_for(store)
    assert a.regions["TW"].dataset_id == b.regions["TW"].dataset_id
    tw_only = build_dataset(store, games, events, cutoff=CUTOFF, regions=("TW",))
    assert set(tw_only.regions) == {"TW"}
    assert tw_only.regions["TW"].dataset_id == a.regions["TW"].dataset_id
    assert len(a.regions["TW"].dataset_id) == 64


def test_every_component_changes_the_id(store):
    base, games, events = dataset_for(store)
    tw_id = base.regions["TW"].dataset_id

    def tw_id_of(**kw):
        g = kw.pop("games", games)
        ev = kw.pop("events", events)
        return build_dataset(store, g, ev, **{"cutoff": CUTOFF, **kw}).regions["TW"].dataset_id

    assert tw_id_of(cutoff=dt("2026-08-01")) != tw_id
    assert tw_id_of(levels=(10, 20)) != tw_id
    assert tw_id_of(windows={"TW": (0, 6), "US": (12, 60)}) != tw_id
    assert tw_id_of(events=[e for e in events if (e.season, e.year) != ("summer", 2023)]) != tw_id
    moved = dict(games)
    s: PriceSeries = games[2].series["TW"]
    moved[2] = replace(games[2], series={"TW": replace(s, known_until=dt("2026-01-01"))})
    assert tw_id_of(games=moved) != tw_id


def test_observation_changes(db_path, tmp_path):
    base_store = make(db_path)
    base, _, _ = dataset_for(base_store)
    base_store.close()
    tw_store = make(tmp_path / "tw" / "sweetspot.db", tw_extra=[("2025-06-26T17:00", 30)])
    tw, _, _ = dataset_for(tw_store)
    tw_store.close()
    us_store = make(tmp_path / "us" / "sweetspot.db", us_extra=[("2024-06-27T17:00", 40)])
    us, _, _ = dataset_for(us_store)
    us_store.close()
    assert tw.regions["TW"].dataset_id != base.regions["TW"].dataset_id
    assert tw.regions["US"].dataset_id == base.regions["US"].dataset_id      # US target never sees TW data
    assert us.regions["TW"].dataset_id != base.regions["TW"].dataset_id      # TW target sees US data
    assert us.regions["US"].dataset_id != base.regions["US"].dataset_id


# --- feature 004: tuning / validation split (research R4; tasks T004) ------------------------------------

ALL_TW_ID = "cb5fe6c5137a5f338343e8a82cb76308b3839da0caf58f3246385829c89a1209"
ALL_US_ID = "1b78efb9e030caa6c3de0192d780fc4e07d04c942e8c761c8903c00d399a97ee"


def test_split_all_keeps_the_002_ids(store):
    ds, _, _ = dataset_for(store)
    assert ds.split == "all"
    assert ds.regions["TW"].dataset_id == ALL_TW_ID
    assert ds.regions["US"].dataset_id == ALL_US_ID
    assert ds.regions["TW"].population_apps == ds.regions["TW"].apps


def test_tuning_and_validation_partition_the_games(store):
    full, _, _ = dataset_for(store)
    tuning, _, _ = dataset_for(store, split="tuning")
    validation, _, _ = dataset_for(store, split="validation")
    for region in ("TW", "US"):
        t, v, a = tuning.regions[region], validation.regions[region], full.regions[region]
        assert not set(t.apps) & set(v.apps)
        assert sorted(t.apps + v.apps) == sorted(a.apps)
        assert t.population_apps == v.population_apps == a.apps
        assert len({t.dataset_id, v.dataset_id, a.dataset_id}) == 3
    assert tuning.regions["TW"].apps == (2, 4)
    assert validation.regions["TW"].apps == (1, 3)
    assert tuning.split == "tuning" and validation.split == "validation"


def test_a_population_only_game_changes_the_validation_id(db_path, tmp_path):
    """App 2 is in the tuning part, but it feeds the population share the validation games are forecast with."""
    def ids(path, extra):
        games = [GameSpec(1, tw=TW, wishlist=True), GameSpec(2, tw=TW + list(extra), pool="broad"), GameSpec(3, tw=TW)]
        build_db(path, games, calendar=BASIC_CALENDAR)
        s = PriceStore.open(path)
        try:
            ds, _, _ = dataset_for(s, split="validation", regions=("TW",))
        finally:
            s.close()
        return ds.regions["TW"].apps, ds.regions["TW"].dataset_id

    apps_a, id_a = ids(tmp_path / "a" / "sweetspot.db", ())
    apps_b, id_b = ids(tmp_path / "b" / "sweetspot.db", [("2025-06-26T17:00", 80), ("2025-07-10T17:00", 0)])
    assert apps_a == apps_b == (1, 3)
    assert id_a != id_b


def test_apps_limit_applies_after_the_split(store):
    ds, _, _ = dataset_for(store, split="validation", apps_limit=1)
    assert ds.regions["TW"].apps == (1,)
    assert ds.regions["TW"].population_apps == (1, 2, 3, 4)


def test_unknown_split_is_rejected(store):
    with pytest.raises(ValueError):
        dataset_for(store, split="test")


# --- feature 006 (spec FR-016, research R4) ----------------------------------------------------------------------

def test_version_rows_after_the_cutoff_leave_the_dataset_id_unchanged(db_path):
    from tests.forecast_builders import add_history, add_version

    store = make(db_path)
    before = dataset_for(store)[0].regions["TW"].dataset_id
    store.close()
    add_history(db_path, 1, "itad-new", tw=[("2024-12-11", 0), ("2025-03-13T17:00", 90), ("2025-03-20T17:00", 0)],
                fetched="2026-09-25")
    add_version(db_path, 1, "2026-09-25T01:00", external_id="itad-new")          # recorded after the cutoff
    store = PriceStore.open(db_path)
    try:
        assert dataset_for(store)[0].regions["TW"].dataset_id == before
        later = dataset_for(store, cutoff=dt("2026-09-26"))[0]                    # a later cutoff reads the version
        games = load_games(store, all_apps(store), dt("2026-09-26"))
        assert max(s.cut for s in games[1].series["TW"].states) == 90
        assert later.regions["TW"].dataset_id != before
    finally:
        store.close()
