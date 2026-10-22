"""research R3 / data-model ScoringUnit (tasks T020)."""

from sweetspot.calendar import SaleEvent
from sweetspot.forecast.backtest.scoring import (actual_sales, horizon_group, score_case, unit_outcome,
                                                 window_points)
from sweetspot.forecast.salepoints import SalePoint
from sweetspot.forecast.series import build_series
from sweetspot.store.query import Observation
from tests.forecast_builders import dt


def event(season, year, start, end, kind="seasonal") -> SaleEvent:
    return SaleEvent(name="x", name_zh="x", kind=kind, season=season, year=year, start=dt(start), end=dt(end),
                     status="ended", source="https://example.test")


def point(i, season, year, start, end) -> SalePoint:
    return SalePoint(index=i, season=season, year=year, label=f"{year} {season}", start=dt(start), end=dt(end),
                     status="estimated", basis={})


def series(rows, known_until="2026-09-24"):
    obs = [Observation(app_id=1, region="TW", source="itad-history", observed_at=dt(w), retrieved_at=dt("2026-09-24"),
                       regular_cents=50000, price_cents=None, cut_pct=c, is_tracking_start=(i == 0))
           for i, (w, c) in enumerate(rows)]
    return build_series(obs, "TW", dt(known_until))


SUMMER = event("summer", 2025, "2025-06-26T17:00", "2025-07-10T17:00")
AUTUMN = event("autumn", 2025, "2025-09-29T17:00", "2025-10-06T17:00")
ACTUAL = actual_sales([SUMMER, AUTUMN, event(None, 2025, "2025-08-01", "2025-08-05", kind="themed")])


def test_actual_sales_are_keyed_by_season_and_year():
    assert set(ACTUAL) == {("summer", 2025), ("autumn", 2025)}


def test_unit_outcomes():
    ku = dt("2025-12-01")
    end = dt("2025-07-10")
    assert unit_outcome(dt("2025-07-01"), SUMMER, ku, end) == "occurred"
    assert unit_outcome(None, SUMMER, ku, end) == "not-occurred"
    assert unit_outcome(dt("2025-07-10T17:00"), SUMMER, ku, end) == "not-occurred"      # end is exclusive
    assert unit_outcome(None, AUTUMN, dt("2025-10-01"), end) == "censored"
    assert unit_outcome(dt("2025-09-30"), AUTUMN, dt("2025-10-01"), end) == "occurred"   # happened before data ended
    assert unit_outcome(None, None, ku, dt("2025-11-01")) == "not-held"     # would have ended before the data did


def test_missing_sale_beyond_the_data_is_censored_not_unheld():
    """A point past the end of the calendar/data is unknown, not 'never held' (found in the US backtest)."""
    ku = dt("2025-12-01")
    assert unit_outcome(None, None, ku, dt("2027-07-01")) == "censored"
    assert unit_outcome(dt("2025-11-15"), None, ku, dt("2027-07-01")) == "occurred"   # the sale is still ahead


def test_scoring_uses_actual_end_not_the_estimate():
    s = series([("2025-01-01", 0), ("2025-07-15", 50), ("2025-07-20", 0)])
    late_summer = event("summer", 2025, "2025-07-03T17:00", "2025-07-17T17:00")
    estimated = point(1, "summer", 2025, "2025-06-26T17:00", "2025-07-10T17:00")
    outcomes = score_case(s, dt("2025-06-01"), [estimated], [50], actual_sales([late_summer]))
    assert outcomes == [["occurred"]]


def test_discount_running_at_as_of_is_not_an_event():
    s = series([("2025-01-01", 0), ("2025-06-26T17:00", 50), ("2025-07-10T17:00", 0)])
    outcomes = score_case(s, dt("2025-07-01"), [point(1, "autumn", 2025, "2025-09-29", "2025-10-06")], [50], ACTUAL)
    assert outcomes == [["not-occurred"]]


def test_new_event_in_the_rest_of_a_running_sale_counts_for_the_next_point():
    s = series([("2025-01-01", 0), ("2025-06-26T17:00", 30), ("2025-07-05", 60), ("2025-07-10T17:00", 0)])
    outcomes = score_case(s, dt("2025-07-01"), [point(1, "autumn", 2025, "2025-09-29", "2025-10-06")], [30, 60],
                          ACTUAL)
    assert outcomes == [["not-occurred", "occurred"]]


def test_cumulative_outcomes_and_not_held():
    s = series([("2025-01-01", 0), ("2025-10-01", 50)])
    pts = [point(1, "summer", 2025, "2025-06-26T17:00", "2025-07-10T17:00"),
           point(2, "spring", 2025, "2025-08-01", "2025-08-08"),                     # never held
           point(3, "autumn", 2025, "2025-09-29T17:00", "2025-10-06T17:00")]
    assert score_case(s, dt("2025-06-01"), pts, [50], ACTUAL) == [["not-occurred"], ["not-held"], ["occurred"]]


def test_censoring_is_per_game():
    early = series([("2025-01-01", 0)], known_until="2025-10-01")
    late = series([("2025-01-01", 0)], known_until="2025-12-01")
    pts = [point(1, "autumn", 2025, "2025-09-29T17:00", "2025-10-06T17:00")]
    assert score_case(early, dt("2025-06-01"), pts, [50], ACTUAL) == [["censored"]]
    assert score_case(late, dt("2025-06-01"), pts, [50], ACTUAL) == [["not-occurred"]]


def test_windows_use_the_estimated_end():
    as_of = dt("2025-06-01")
    pts = [point(1, "summer", 2025, "2025-06-26", "2025-07-10"),
           point(2, "summer", 2026, "2026-05-20", "2026-06-01"),       # exactly 12 months: inside TW
           point(3, "autumn", 2026, "2026-06-01", "2026-06-02"),        # just past 12 months: US
           point(4, "summer", 2030, "2030-05-20", "2030-06-01"),        # exactly 60 months: inside US
           point(5, "autumn", 2030, "2030-06-01", "2030-06-02")]
    assert [p.index for p in window_points(pts, as_of, "TW")] == [1, 2]
    assert [p.index for p in window_points(pts, as_of, "US")] == [3, 4]


def test_horizon_groups():
    as_of = dt("2025-06-01")
    assert horizon_group("TW", as_of, dt("2025-08-31")) == "0-3m"
    assert horizon_group("TW", as_of, dt("2025-11-30")) == "3-6m"
    assert horizon_group("TW", as_of, dt("2026-05-30")) == "6-12m"
    assert horizon_group("US", as_of, dt("2027-05-30")) == "12-24m"
    assert horizon_group("US", as_of, dt("2028-05-30")) == "24-36m"
    assert horizon_group("US", as_of, dt("2030-05-30")) == "36-60m"
