"""Guarantee 4 of contracts/store-api.md and the static/volatile split (spec US3 AS2)."""

from datetime import UTC, date, datetime, timedelta

import pytest

from sweetspot.store.query import PriceStore
from sweetspot.store.writer import NewObservation, StoreWriter

T1 = datetime(2025, 1, 1, tzinfo=UTC)
T2 = datetime(2026, 1, 1, tzinfo=UTC)
NOW = datetime(2026, 9, 25, tzinfo=UTC)


@pytest.fixture
def store(db_path):
    w = StoreWriter.open(db_path)
    run = w.start_run("daily")
    w.add_facts(run, 620, {"name": "Portal 2 (old)", "publishers": ["Valve"], "release_date": "2011-04-18",
                           "is_indie": False, "product_type": "game", "review_count_total": 1000},
                source="steam-appdetails", retrieved_at=T1)
    w.add_facts(run, 620, {"name": "Portal 2", "review_count_total": 467117}, source="steam-appdetails",
                retrieved_at=T2)
    w.add_facts(run, 9, {"release_date": "2027-03-01", "publisher_catalog_size": 12}, source="steam-appdetails",
                retrieved_at=T2)
    for source in ("itad-history", "steam-current"):
        w.add_observations(run, [NewObservation(app_id=620, source=source, region="TW", currency="TWD",
                                                regular_cents=18800, price_cents=3700, cut_pct=80, observed_at=T2,
                                                raw_observed_at=None, retrieved_at=NOW)])
    w.ensure_product(620, "reference-broad", T1)
    w.ensure_product(9, "wishlist", T1)
    w.close()
    s = PriceStore.open(db_path)
    yield s
    s.close()


def test_static_fields_return_latest_value_regardless_of_as_of(store):
    facts = store.facts(620, as_of=datetime(2020, 1, 1, tzinfo=UTC))
    assert facts.name.value == "Portal 2" and facts.name.retrieved_at == T2
    assert facts.publishers.value == ["Valve"] and facts.publishers.source == "steam-appdetails"
    assert facts.release_date.value == date(2011, 4, 18)
    assert facts.is_indie.value is False and facts.product_type.value == "game"


def test_volatile_fields_only_use_values_known_at_as_of(store):
    assert store.facts(620, as_of=T1 - timedelta(seconds=1)).review_count_total.value is None
    assert store.facts(620, as_of=T1).review_count_total.value == 1000
    assert store.facts(620, as_of=T2 + timedelta(days=1)).review_count_total.value == 467117
    assert store.facts(9, as_of=T1).publisher_catalog_size.value is None


def test_unknown_fields_are_unknown_not_zero(store):
    facts = store.facts(620, as_of=NOW)
    assert facts.parent_app_id.value is None and facts.parent_app_id.retrieved_at is None
    assert facts.genres.value is None
    empty = store.facts(12345, as_of=NOW)
    assert empty.name.value is None and empty.released_as_of is None


def test_released_as_of_follows_release_date(store):
    assert store.facts(620, as_of=NOW).released_as_of is True
    assert store.facts(620, as_of=datetime(2011, 4, 17, tzinfo=UTC)).released_as_of is False
    assert store.facts(9, as_of=NOW).released_as_of is False


def test_same_time_observations_from_all_sources_returned(store):
    sources = [o.source for o in store.observations(620, NOW) if o.observed_at == T2]
    assert sources == ["itad-history", "steam-current"]


def test_reference_apps_lists_non_wishlist_products(store):
    assert store.reference_apps() == [620]
    assert store.reference_apps(pool="reference-broad") == [620]
    assert store.reference_apps(pool="reference-related") == []


# --- feature 008: release dates for every app in one query (research R3; tasks T005) ---------------------------

def test_release_dates_in_one_query_match_facts(db_path):
    w = StoreWriter.open(db_path)
    run = w.start_run("daily")
    w.add_facts(run, 1, {"release_date": "2020-01-01"}, source="steam-appdetails", retrieved_at=T1)
    w.add_facts(run, 1, {"release_date": "2020-02-02"}, source="steam-appdetails", retrieved_at=T2)   # latest wins
    w.add_facts(run, 2, {"release_date": None}, source="steam-appdetails", retrieved_at=T1)
    w.add_facts(run, 3, {"release_date": "soon"}, source="steam-appdetails", retrieved_at=T1)          # unparseable
    w.add_facts(run, 4, {"name": "no release date"}, source="steam-appdetails", retrieved_at=T1)
    for app in (1, 2, 3, 4):
        w.ensure_product(app, "reference-broad", T1)
    w.close()
    s = PriceStore.open(db_path)
    try:
        dates = s.release_dates([1, 2, 3, 4, 5])
        assert dates == {1: date(2020, 2, 2), 2: None, 3: None, 4: None, 5: None}
        assert dates[1] == s.facts(1, NOW).release_date.value
        assert s.release_dates([]) == {}
    finally:
        s.close()
