"""feature 013 (research R1, R2, FR-004–FR-006): the price series a record followed and what the sale did to it."""

import pytest

from sweetspot.calendar import SaleEvent
from sweetspot.review.actual import sale_actual, tracked_series
from sweetspot.store.query import PriceStore
from tests.forecast_builders import dt
from tests.review_builders import AS_OF, TODAY, default_decisions, review_db

SALE = SaleEvent("Steam Autumn Sale", "秋季特賣", "seasonal", "autumn", 2026, dt("2026-10-01T17:00"),
                 dt("2026-10-08T17:00"), "ended", "test")
LOW = list(range(5, 65, 5))       # 5..60
HIGH = list(range(65, 100, 5))    # 65..95


@pytest.fixture
def store(db_path):
    review_db(db_path)
    s = PriceStore.open(db_path)
    yield s
    s.close()


def decisions():
    return {d["app_id"]: d for d in default_decisions()}


# --- which product is read (T005) ------------------------------------------------------------------------

def test_the_default_version_reads_its_own_history(store):
    t = tracked_series(store, decisions()[1], SALE, TODAY)
    assert t.reason is None and t.basis == "default" and t.itad_id == "itad-1"
    assert [s.cut for s in t.series.states] == [0, 60, 0]
    assert t.option == {"kind": "sub", "id": 1001, "name": "Game 1"}
    assert t.known_until == dt("2026-10-09T17:00")


def test_a_user_edition_reads_the_edition_history(store):
    t = tracked_series(store, decisions()[4], SALE, TODAY)
    assert t.reason is None and t.basis == "user" and t.itad_id == "itad-ed4"
    assert max(s.cut for s in t.series.states) == 75            # the app's own history never left 0%


def test_known_until_is_capped_at_today(store):
    t = tracked_series(store, decisions()[3], SALE, dt("2026-10-12"))
    assert t.known_until == dt("2026-10-12")
    assert [s.cut for s in t.series.states] == [0, 50, 0]       # the 10/20 promotion is after today


# --- what the sale did (T007) ---------------------------------------------------------------------------

def test_a_discount_that_starts_with_the_sale(store):
    t = tracked_series(store, decisions()[1], SALE, TODAY)
    a = sale_actual(t, SALE, AS_OF)
    assert (a.max_cut, a.min_cents, a.running_cut_at_as_of) == (60, 20000, 0)
    assert all(a.sale_max(d) and a.crossing(d) for d in LOW)
    assert not any(a.sale_max(d) or a.crossing(d) for d in HIGH)
    assert not a.regular_changed


def test_a_discount_already_running_at_as_of(store):
    """D1: the sale's deepest cut counts it; the backtest's first crossing after as_of does not."""
    t = tracked_series(store, decisions()[2], SALE, TODAY)
    a = sale_actual(t, SALE, AS_OF)
    assert (a.max_cut, a.min_cents, a.running_cut_at_as_of) == (40, 30000, 40)
    assert [d for d in range(5, 100, 5) if a.sale_max(d)] == list(range(5, 45, 5))
    assert not any(a.crossing(d) for d in range(5, 100, 5))


def test_the_lowest_price_counts_the_state_in_effect_at_the_start(db_path):
    review_db(db_path, history={1: [("2026-01-01", 0), ("2026-09-20", 70), ("2026-10-03", 50),
                                    ("2026-10-08T17:00", 0)]})
    s = PriceStore.open(db_path)
    try:
        a = sale_actual(tracked_series(s, decisions()[1], SALE, TODAY), SALE, AS_OF)
    finally:
        s.close()
    assert (a.max_cut, a.min_cents, a.running_cut_at_as_of) == (70, 15000, 70)


def test_a_regular_price_change_in_the_sale_is_flagged(db_path):
    review_db(db_path, history={1: [("2026-01-01", 0), ("2026-10-01T17:00", 60), ("2026-10-04", 60, 60000),
                                    ("2026-10-08T17:00", 0, 60000)]})
    s = PriceStore.open(db_path)
    try:
        a = sale_actual(tracked_series(s, decisions()[1], SALE, TODAY), SALE, AS_OF)
    finally:
        s.close()
    assert a.regular_changed and a.max_cut == 60 and a.min_cents == 20000


# --- US2: what cannot be compared (T016) ------------------------------------------------------------------

def _tracked(db_path, app, decision=None, **db):
    review_db(db_path, **db)
    s = PriceStore.open(db_path)
    try:
        return tracked_series(s, decision or decisions()[app], SALE, TODAY)
    finally:
        s.close()


def test_history_that_stops_before_the_sale_ends(db_path):
    assert _tracked(db_path, 5).reason == "價格歷史只到 2026-10-05"


def test_no_series_at_all(db_path):
    d = dict(decisions()[1], version={"itad_id": "itad-other", "source": "steam-default", "option": None})
    assert _tracked(db_path, 1, d).reason == "沒有價格序列"


def test_a_series_that_starts_after_the_sale_starts(db_path):
    t = _tracked(db_path, 1, history={1: [("2026-10-03", 50), ("2026-10-08T17:00", 0)]})
    assert t.reason == "價格序列從 2026-10-03 才開始，沒有涵蓋特賣開始"


def test_a_user_edition_without_its_own_history(db_path):
    d = dict(decisions()[4], version={"itad_id": "itad-none", "source": "user", "option": {"kind": "sub", "id": 9}})
    assert _tracked(db_path, 4, d).reason == "指定的版本沒有自己的價格歷史"


def test_a_record_without_a_tracked_product(db_path):
    d = dict(decisions()[1], version={"itad_id": None, "source": "steam-default"})
    assert _tracked(db_path, 1, d).reason == "紀錄沒有追蹤的 ITAD 商品"


def test_unknown_games_stay_out_of_every_denominator(store):
    from sweetspot.review.score import decision_summary, review_game, seasonal_summary
    from tests.review_builders import forecast_game, pre_sale_record

    ds = decisions()
    rows = []
    for app in (1, 2):
        t = tracked_series(store, ds[app], SALE, TODAY)
        rows.append(review_game(ds[app], forecast_game(app), t, sale_actual(t, SALE, AS_OF), SALE))
    before = (seasonal_summary(rows, 1), decision_summary(rows, pre_sale_record(), 1))
    unknown = review_game(ds[5], forecast_game(5), tracked_series(store, ds[5], SALE, TODAY), None, SALE)
    assert unknown["status"] == "no-actual" and unknown["reason"] == "價格歷史只到 2026-10-05"
    assert unknown["decision"]["hit"] is None
    assert (seasonal_summary(rows + [unknown], 1), decision_summary(rows + [unknown], pre_sale_record(), 1)) == before


# --- US2: the tracked option's daily rows (T017, D2) --------------------------------------------------------

def _steps(option, cut, days=range(7)):
    from sweetspot.store.query import OptionRecord
    from tests.review_builders import daily_rows

    return [OptionRecord(app_id=6, checked_at=dt(t), kind=r["kind"], option_id=r["option_id"], name=r["name"],
                         original_cents=r["original_cents"], final_cents=r["final_cents"], position=0,
                         is_default=True, role="default", external_id=None, verification=None, verified_at=None,
                         reason_code=None, reason_detail=None, itad_steam_deals=None)
            for t, r in daily_rows(option, cut, days)]


def test_deeper_daily_rows_correct_the_history(store):
    from sweetspot.review.actual import cross_check
    from tests.review_builders import F_OPTION

    t = tracked_series(store, decisions()[6], SALE, TODAY)
    a = cross_check(sale_actual(t, SALE, AS_OF), _steps(F_OPTION, 33))
    assert (a.max_cut, a.history_max_cut, a.min_cents, a.daily_max_cut, a.daily_min_cents) == (33, 0, 33500, 33, 33500)
    assert a.corrected and not a.noted
    assert [d for d in range(5, 100, 5) if a.sale_max(d)] == [5, 10, 15, 20, 25, 30]
    assert [d for d in range(5, 100, 5) if a.crossing(d)] == [5, 10, 15, 20, 25, 30]
    assert a.crossings[30] == dt("2026-10-01T18:30")          # the first daily row that showed it


def test_a_deeper_history_is_only_noted(store):
    from sweetspot.review.actual import cross_check

    t = tracked_series(store, decisions()[1], SALE, TODAY)
    a = cross_check(sale_actual(t, SALE, AS_OF), _steps({"kind": "sub", "id": 1001, "name": "Game 1"}, 50))
    assert (a.max_cut, a.min_cents, a.daily_max_cut) == (60, 20000, 50)
    assert a.noted and not a.corrected


def test_the_first_day_lag_is_not_a_mismatch(store):
    """10/2 02:30 Taipei: Steam had switched, ITAD had not (or the other way); only the whole sale is compared."""
    from sweetspot.review.actual import cross_check

    option = {"kind": "sub", "id": 1001, "name": "Game 1"}
    steps = _steps(option, 0, days=[0]) + _steps(option, 60, days=range(1, 7))
    a = cross_check(sale_actual(tracked_series(store, decisions()[1], SALE, TODAY), SALE, AS_OF), steps)
    assert (a.max_cut, a.daily_max_cut, a.corrected, a.noted) == (60, 60, False, False)


def test_no_daily_rows_change_nothing(store):
    from sweetspot.review.actual import cross_check

    base = sale_actual(tracked_series(store, decisions()[1], SALE, TODAY), SALE, AS_OF)
    assert cross_check(base, []) == base and base.daily_max_cut is None


# --- US2: versions (T018) -----------------------------------------------------------------------------------

def test_the_records_version_is_read_even_after_steam_changes_it(db_path):
    from tests.forecast_builders import add_version

    review_db(db_path)
    add_version(db_path, 1, "2026-10-05", external_id="itad-new")
    s = PriceStore.open(db_path)
    try:
        t = tracked_series(s, decisions()[1], SALE, TODAY)
    finally:
        s.close()
    assert t.itad_id == "itad-1" and t.version_changed and [x.cut for x in t.series.states] == [0, 60, 0]
    assert not tracked_series_unchanged(db_path)


def tracked_series_unchanged(db_path):
    s = PriceStore.open(db_path)
    try:
        return tracked_series(s, decisions()[2], SALE, TODAY).version_changed
    finally:
        s.close()


def test_the_daily_rows_of_a_user_edition_are_the_editions(db_path):
    from tests.review_builders import D_OPTION, F_OPTION, daily_rows

    review_db(db_path, daily={4: daily_rows(D_OPTION, 75) + daily_rows(dict(F_OPTION, id=4001 + 1), 10)})
    s = PriceStore.open(db_path)
    try:
        t = tracked_series(s, decisions()[4], SALE, TODAY)
        steps = s.option_steps(4, t.option["kind"], t.option["id"], SALE.start, SALE.end)
    finally:
        s.close()
    assert t.option == D_OPTION and {r.option_id for r in steps} == {4001} and len(steps) == 7
