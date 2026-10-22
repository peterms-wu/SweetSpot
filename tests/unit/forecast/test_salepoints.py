"""research R2: future seasonal sale points (tasks T007)."""

from datetime import timedelta

from sweetspot.forecast.salepoints import future_sale_points, sale_points
from sweetspot.store.query import PriceStore
from sweetspot.timeutil import add_months, now_utc
from tests.forecast_builders import BASIC_CALENDAR, GameSpec, Sale, build_db, dt

OLD_CALENDAR = [  # 2019-2020: no spring sale yet
    Sale("summer", 2019, "2019-06-25T17:00", "2019-07-09T17:00"),
    Sale("autumn", 2019, "2019-11-26T18:00", "2019-12-03T18:00"),
    Sale("winter", 2019, "2019-12-19T18:00", "2020-01-02T18:00"),
    Sale("summer", 2020, "2020-06-25T17:00", "2020-07-09T17:00"),
    Sale("autumn", 2020, "2020-11-25T18:00", "2020-12-01T18:00"),
    Sale("winter", 2020, "2020-12-22T18:00", "2021-01-05T18:00"),
]


def store_with(db_path, calendar):
    build_db(db_path, [GameSpec(1, tw=[("2024-12-11", 0)])], calendar=calendar)
    return PriceStore.open(db_path)


def test_backtest_points_are_estimated_from_past_sales_only(db_path):
    # the actual 2025 summer sale is on an unusual date; a backtest at 2025-06-01 must not see it
    calendar = [s for s in BASIC_CALENDAR if (s.season, s.year) != ("summer", 2025)]
    calendar.append(Sale("summer", 2025, "2025-07-03T17:00", "2025-07-17T17:00"))
    store = store_with(db_path, calendar)
    try:
        points = future_sale_points(store, dt("2025-06-01"))
    finally:
        store.close()
    first = points[0]
    assert (first.index, first.season, first.year, first.label) == (1, "summer", 2025, "2025 夏特")
    assert first.status == "estimated" and first.basis["reference_year"] == 2024
    assert first.start == dt("2025-06-26T17:00")        # 2024-06-27 moved to the same weekday in 2025
    assert all(p.status == "estimated" for p in points)


def test_points_are_ordered_indexed_and_within_60_months():
    as_of = dt("2025-06-01")
    events = [e for e in _events(BASIC_CALENDAR) if e.start <= as_of]
    points = sale_points(events, as_of)
    assert [p.index for p in points] == list(range(1, len(points) + 1))
    assert all(a.start < b.start for a, b in zip(points, points[1:]))
    assert points[-1].end <= add_months(as_of, 60)
    assert len(points) == 20                            # four seasons a year for five years


def test_ongoing_sale_is_not_a_point():
    as_of = dt("2025-06-30")                            # inside the 2025 summer sale
    events = [e for e in _events(BASIC_CALENDAR) if e.start <= as_of]
    points = sale_points(events, as_of)
    assert (points[0].season, points[0].year) == ("autumn", 2025)
    assert all((p.season, p.year) != ("summer", 2025) for p in points)


def test_estimate_already_due_but_not_started_is_kept():
    calendar = [s for s in BASIC_CALENDAR if (s.season, s.year) != ("summer", 2025)]
    as_of = dt("2025-06-27")                            # estimate says the sale began 06-26; it has not
    events = [e for e in _events(calendar) if e.start <= as_of]
    first = sale_points(events, as_of)[0]
    assert (first.season, first.year, first.status) == ("summer", 2025, "estimated")


def test_only_seasons_held_in_the_last_18_months():
    events = _events(OLD_CALENDAR)
    points = sale_points([e for e in events if e.start <= dt("2021-06-01")], dt("2021-06-01"))
    assert "spring" not in {p.season for p in points}
    later = sale_points([e for e in _events(BASIC_CALENDAR) if e.start <= dt("2024-06-01")], dt("2024-06-01"))
    assert ("spring", 2025) in {(p.season, p.year) for p in later}


def test_live_points_use_announcements_then_estimates(db_path):
    now = now_utc()
    soon = now + timedelta(days=10)
    year = soon.year
    calendar = [
        Sale("summer", year - 1, _iso(soon - timedelta(days=365)), _iso(soon - timedelta(days=358))),
        Sale("autumn", year - 1, _iso(soon - timedelta(days=300)), _iso(soon - timedelta(days=293))),
        Sale("summer", year, _iso(soon), _iso(soon + timedelta(days=7))),
    ]
    store = store_with(db_path, calendar)
    try:
        points = future_sale_points(store, now)
    finally:
        store.close()
    announced = [p for p in points if p.status == "announced"]
    assert [(p.season, p.year) for p in announced] == [("summer", year)]
    assert announced[0].basis is None
    assert all(p.basis for p in points if p.status == "estimated")


def _iso(value) -> str:
    return value.strftime("%Y-%m-%dT%H:%M")


def _events(sales):
    from sweetspot.calendar import SaleEvent

    return [SaleEvent(name="x", name_zh="x", kind=s.kind, season=s.season, year=s.year, start=dt(s.start),
                      end=dt(s.end), status="ended", source="https://example.test") for s in sales]
