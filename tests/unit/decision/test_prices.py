"""Current price, confirmation time, regular-price mismatch and non-seasonal discounts (tasks T009; research R3, R4)."""

import pytest

from sweetspot.decision.prices import CurrentPrice, current_prices, non_seasonal_deeper
from sweetspot.forecast.series import PriceSeries, PriceState
from sweetspot.store.query import PriceStore
from sweetspot.store.writer import NewObservation
from tests.decision_builders import steam_current
from tests.forecast_builders import BASIC_CALENDAR, GameSpec, build_db, dt

AS_OF = dt("2026-09-25T12:00")
ITAD_ROWS = [("2025-01-01", 0, 50000), ("2026-06-25T17:00", 60, 50000), ("2026-07-09T17:00", 0, 50000)]


def _no_regular(app_id, when):
    moment = dt(when)
    return NewObservation(app_id=app_id, source="steam-current", region="TW", currency="TWD", regular_cents=None,
                          price_cents=40000, cut_pct=None, observed_at=moment, raw_observed_at=None,
                          retrieved_at=moment, is_tracking_start=False)


@pytest.fixture
def store(db_path):
    games = [
        GameSpec(1, tw=ITAD_ROWS, known_until={"TW": "2026-09-02"},
                 extra_tw=[steam_current(1, "2026-09-24T16:00", 25000, 50000),
                           steam_current(1, "2026-09-26T00:00", 10000, 50000)]),        # after as_of: ignored
        GameSpec(2, tw=ITAD_ROWS, known_until={"TW": "2026-09-25T06:00"}),             # ITAD only
        GameSpec(3, tw=[("2025-01-01", 70, 30000)], regular_cents=30000,
                 extra_tw=[steam_current(3, "2026-09-25T02:53", 13400, 67000)]),       # Dying Light shape
        GameSpec(4, tw=ITAD_ROWS, extra_tw=[_no_regular(4, "2026-09-25T01:00")]),
        GameSpec(5),                                                                     # no observations
        GameSpec(6, tw=ITAD_ROWS, known_until={"TW": "2026-09-02"},
                 extra_tw=[steam_current(6, "2026-09-25T01:00", 60000, 50000)]),   # price > regular: quarantined
    ]
    build_db(db_path, games, calendar=BASIC_CALENDAR)
    s = PriceStore.open(db_path)
    yield s
    s.close()


def prices(store, as_of=AS_OF):
    history = {1: 50000, 2: 50000, 3: 30000, 4: 50000, 5: None, 6: 50000}
    return current_prices(store, sorted(history), as_of, history)


def test_latest_observation_of_any_source_wins(store):
    p = prices(store)[1]
    assert (p.price_cents, p.regular_cents, p.cut_pct, p.source) == (25000, 50000, 50, "steam-current")
    assert p.observed_at == dt("2026-09-24T16:00")
    assert p.confirmed_at == dt("2026-09-24T16:00")         # later than the ITAD known-until (09-02)
    assert p.stale is False and p.regular_mismatch is False


def test_itad_only_confirmed_by_history_fetch(store):
    p = prices(store)[2]
    assert (p.price_cents, p.source) == (50000, "itad-history")
    assert p.confirmed_at == dt("2026-09-25T06:00")


def test_confirmation_is_capped_at_as_of(store):
    p = prices(store, dt("2026-09-25T03:00"))[2]
    assert p.confirmed_at == dt("2026-09-25T03:00")


@pytest.mark.parametrize("as_of, stale", [(dt("2026-09-25T16:00"), False), (dt("2026-09-25T16:00:01"), True)])
def test_stale_after_more_than_24_hours(store, as_of, stale):
    assert prices(store, as_of)[1].stale is stale


def test_regular_mismatch_uses_the_current_regular(store):
    p = prices(store)[3]
    assert (p.price_cents, p.regular_cents, p.history_regular_cents) == (13400, 67000, 30000)
    assert p.regular_mismatch is True


def test_missing_regular_falls_back_to_the_forecast(store):
    p = prices(store)[4]
    assert (p.price_cents, p.regular_cents, p.regular_mismatch) == (40000, 50000, False)


def test_no_observation_is_unknown_not_zero(store):
    p = prices(store)[5]
    assert p == CurrentPrice(None, None, None, None, None, None, True, None, False)


def test_quarantined_observation_is_ignored(store):
    p = prices(store)[6]
    assert p.source == "itad-history" and p.price_cents == 50000


# --- non-seasonal discounts (research R4) ---------------------------------------------------------------

WINTER = (dt("2024-12-19T18:00"), dt("2025-01-02T18:00"))
SPRING = (dt("2025-03-13T17:00"), dt("2025-03-20T17:00"))


def series(*states):
    return PriceSeries("TW", tuple(PriceState(dt(t), cut, i == 0, 50000) for i, (t, cut) in enumerate(states)),
                       dt("2025-06-01"))


def test_non_seasonal_deeper_than_own_seasonal_max_is_reported():
    s = series(("2024-12-11", 0), ("2024-12-19T18:00", 50), ("2025-01-02T18:00", 0),
               ("2025-02-10", 60), ("2025-02-20", 0), ("2025-03-13T17:00", 40), ("2025-03-20T17:00", 0))
    found = non_seasonal_deeper(s, [WINTER, SPRING], own_max_cut=50, as_of=dt("2025-06-01"))
    assert (found.cut, found.start) == (60, dt("2025-02-10"))
    assert non_seasonal_deeper(s, [WINTER, SPRING], own_max_cut=60, as_of=dt("2025-06-01")) is None


def test_state_overlapping_a_seasonal_sale_is_not_non_seasonal():
    s = series(("2024-12-11", 0), ("2024-12-15", 70), ("2025-01-05", 0))      # starts before winter, runs into it
    assert non_seasonal_deeper(s, [WINTER], own_max_cut=0, as_of=dt("2025-06-01")) is None


def test_no_seasonal_history_counts_as_zero_and_later_states_are_ignored():
    s = series(("2026-08-20", 0), ("2026-09-07", 20), ("2026-09-21", 0), ("2026-10-01", 40))
    found = non_seasonal_deeper(s, [], own_max_cut=None, as_of=dt("2026-09-25"))
    assert (found.cut, found.start) == (20, dt("2026-09-07"))


# --- feature 006 --------------------------------------------------------------------------------------------------

def test_history_regular_and_confirmation_follow_the_version(db_path):
    from tests.forecast_builders import add_history, add_version

    build_db(db_path, [GameSpec(3, tw=[("2025-01-01", 70, 30000)], regular_cents=30000,
                                known_until={"TW": "2026-09-25T08:00"},     # the old product: fetched later
                                extra_tw=[steam_current(3, "2026-09-24T02:53", 13400, 67000)])],
             calendar=BASIC_CALENDAR)
    add_history(db_path, 3, "itad-new", tw=[("2025-06-26", 80, 67000)], regular_cents=67000, fetched="2026-09-25T06:00")
    add_version(db_path, 3, "2026-09-25T06:00", external_id="itad-new", regular_cents=67000, price_cents=13400)
    s = PriceStore.open(db_path)
    try:
        got = current_prices(s, [3], AS_OF, {3: 67000})[3]
    finally:
        s.close()
    assert got.regular_mismatch is False and got.history_regular_cents == 67000
    assert got.confirmed_at == dt("2026-09-25T06:00")        # the new product's fetch, not the old one's


# --- feature 009: the chosen option's current price (research R5) ---------------------------------------------

def _chosen(db_path, snapshot_at, history_rows):
    from sweetspot.store.query import OPTION_HISTORY_SOURCE
    from tests.forecast_builders import add_history, add_purchase_options
    add_history(db_path, 1, "itad-ult", tw=history_rows, regular_cents=90000, fetched="2026-09-25",
                source=OPTION_HISTORY_SOURCE, fetch_source="itad-option")
    add_purchase_options(db_path, 1, snapshot_at, [
        dict(kind="sub", option_id=100, original_cents=50000, final_cents=25000, role="default"),
        dict(kind="bundle", option_id=900, original_cents=90000, final_cents=45000, role="edition",
             external_id="itad-ult", verification="verified", verified_by="version-check", verified_at=snapshot_at)])
    s = PriceStore.open(db_path)
    keys = s.option_keys({1: ("bundle", 900)}, AS_OF, s.history_keys([1], AS_OF))
    return s, keys


def test_chosen_price_comes_from_the_purchase_option_record(store, db_path):
    s, keys = _chosen(db_path, "2026-09-25T01:00", [("2025-01-01", 0, 90000), ("2026-06-25T17:00", 60, 90000)])
    price = current_prices(s, [1, 2], AS_OF, {1: 90000, 2: 50000}, option_keys=keys)
    ult = price[1]
    assert (ult.price_cents, ult.regular_cents, ult.cut_pct, ult.source) == (45000, 90000, 50, "steam-option")
    assert ult.confirmed_at == dt("2026-09-25T01:00") and not ult.stale and not ult.regular_mismatch
    assert price[2] == current_prices(store, [2], AS_OF, {2: 50000})[2]      # other games untouched
    s.close()


def test_a_newer_edition_history_row_wins_and_the_mismatch_uses_its_history(store, db_path):
    s, keys = _chosen(db_path, "2026-09-20T01:00", [("2025-01-01", 0, 90000), ("2026-09-24T17:00", 70, 90000)])
    ult = current_prices(s, [1], AS_OF, {1: 80000}, option_keys=keys)[1]
    assert (ult.price_cents, ult.cut_pct, ult.source) == (27000, 70, "itad-option-history")
    assert ult.regular_mismatch                                    # 90000 vs the history's 80000
    s.close()


def test_an_old_record_is_stale(store, db_path):
    s, keys = _chosen(db_path, "2026-09-20T01:00", [("2025-01-01", 0, 90000)])
    assert current_prices(s, [1], AS_OF, {1: 90000}, option_keys=keys)[1].stale
    s.close()
