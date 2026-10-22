"""Guarantees 1, 2, 3 and 5 of contracts/store-api.md."""

from datetime import UTC, datetime, timedelta

import pytest

from sweetspot.store.query import PriceStore
from sweetspot.store.writer import NewObservation, StoreWriter

NOW = datetime(2026, 9, 25, tzinfo=UTC)
D = [datetime(2025, 1, 1, tzinfo=UTC) + timedelta(days=30 * i) for i in range(6)]


def obs(day, *, region="TW", source="itad-history", price=10000, regular=20000, cut=50, tracking=False,
        currency="TWD"):
    if region != "TW":
        currency = price = regular = None
    return NewObservation(app_id=620, source=source, region=region, currency=currency, regular_cents=regular,
                          price_cents=price, cut_pct=cut, observed_at=day, raw_observed_at=None, retrieved_at=NOW,
                          is_tracking_start=tracking)


@pytest.fixture
def store(db_path):
    w = StoreWriter.open(db_path)
    run = w.start_run("daily")
    w.add_observations(run, [
        obs(D[0], tracking=True, price=20000, cut=0),
        obs(D[1]),
        obs(D[2], source="steam-current"),
        obs(D[2], source="itad-history"),
        obs(D[3], price=-1),  # anomaly
        obs(D[4]),
        obs(D[1], region="US", cut=50),
        obs(D[4], region="US", cut=75),
    ])
    w.close()
    s = PriceStore.open(db_path)
    yield s
    s.close()


@pytest.mark.parametrize("i", range(6))
def test_guarantee_1_no_observation_after_as_of(store, i):
    as_of = D[i] + timedelta(days=1)
    for region in ("TW", "US"):
        assert all(o.observed_at <= as_of for o in store.observations(620, as_of, region=region,
                                                                       include_tracking_start=True))


def test_as_of_boundary_is_inclusive(store):
    assert D[1] in {o.observed_at for o in store.observations(620, D[1])}
    assert D[1] not in {o.observed_at for o in store.observations(620, D[1] - timedelta(microseconds=1))}


def test_guarantee_2_anomalies_excluded(store):
    assert D[3] not in {o.observed_at for o in store.observations(620, NOW)}


def test_tracking_start_included_by_default_and_flagged(store):
    first = store.observations(620, NOW)[0]
    assert first.observed_at == D[0] and first.is_tracking_start
    assert [o.observed_at for o in store.observations(620, NOW, include_tracking_start=False)][0] == D[1]


def test_guarantee_3_aux_region_has_no_amounts(store):
    aux = store.observations(620, NOW, region="US")
    assert [o.cut_pct for o in aux] == [50, 75]
    assert all(o.price_cents is None and o.regular_cents is None for o in aux)


def test_guarantee_5_sorted_by_time_then_source(store):
    result = store.observations(620, NOW)
    keys = [(o.observed_at, o.source) for o in result]
    assert keys == sorted(keys)
    assert [o.source for o in result if o.observed_at == D[2]] == ["itad-history", "steam-current"]


def test_naive_as_of_is_rejected(store):
    with pytest.raises(ValueError):
        store.observations(620, datetime(2025, 1, 1))


def test_store_is_read_only(store):
    with pytest.raises(Exception):
        store.conn.execute("CREATE TABLE x (a INTEGER)")
