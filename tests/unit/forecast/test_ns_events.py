"""Non-seasonal arrivals and promotions (feature 007 spec FR-001; tasks T003)."""

from datetime import timedelta

import pytest

from sweetspot.forecast.nonseasonal.events import (SeasonalWindows, arrivals, arrived_levels, nonseasonal, promos,
                                                   window_fraction)
from tests.forecast_builders import dt
from tests.ns_builders import SEASONS, series

W = SeasonalWindows(SEASONS)
SUMMER = dt("2025-06-26T17:00")
LEVELS = tuple(range(5, 100, 5))


def test_tracking_start_is_never_an_arrival():
    s = series([("2025-01-01", 50), ("2025-01-10", 0), ("2025-02-01", 40)])
    got = arrivals(s, W)
    assert [(a.at, a.from_cut, a.to_cut) for a in got] == [(dt("2025-02-01"), 0, 40)]


def test_one_day_tolerance_before_a_seasonal_start():
    s = series([("2025-06-01", 0), ("2025-06-25T18:00", 30), ("2025-06-25T19:00", 0)])
    assert W.window_start(dt("2025-06-25T18:00")) == SUMMER         # 23 hours before: seasonal
    assert W.window_start(dt("2025-06-25T16:00")) is None            # 25 hours before: not
    assert W.window_start(dt("2025-07-10T16:59")) == SUMMER
    assert W.window_start(dt("2025-07-10T17:00")) is None            # the end is exclusive
    assert [a.window_start for a in arrivals(s, W)] == [SUMMER]


def test_promotion_running_into_a_seasonal_sale():
    rows = [("2025-06-01", 0), ("2025-06-20", 50), ("2025-06-28", 75), ("2025-07-12", 0)]
    s = series(rows, known_until="2025-08-01")
    arr = arrivals(s, W)
    ns = nonseasonal(arr, dt("2025-08-01"))
    assert [(a.at, a.to_cut) for a in ns] == [(dt("2025-06-20"), 50)]            # -75% inside the sale is seasonal
    assert arrived_levels(arr, dt("2025-06-01"), dt("2025-08-01"), LEVELS) == set(range(5, 55, 5))
    assert promos(s, W, dt("2025-08-01")) == ()                                  # it overlaps: not a promotion


def test_deepening_counts_only_the_new_levels():
    s = series([("2025-04-01", 0), ("2025-04-10", 50), ("2025-04-14", 60), ("2025-04-20", 0)])
    arr = arrivals(s, W)
    assert arrived_levels(arr, dt("2025-04-12"), dt("2025-05-01"), LEVELS) == {55, 60}
    assert arrived_levels(arr, dt("2025-04-01"), dt("2025-05-01"), LEVELS) == set(range(5, 65, 5))


def test_a_later_sale_does_not_reclassify_the_past():
    s = series([("2025-06-01", 0), ("2025-06-25T20:00", 40), ("2025-07-12", 0)])
    arr = arrivals(s, W)
    before = dt("2025-06-25T21:00")                  # the summer sale has not started yet
    assert [a.at for a in nonseasonal(arr, before)] == [dt("2025-06-25T20:00")]
    assert nonseasonal(arr, dt("2025-06-27")) == []


def test_promotions_for_the_basis():
    rows = [("2025-01-10", 0), ("2025-02-01", 30), ("2025-02-03", 50), ("2025-02-10", 0),
            ("2025-04-01", 50), ("2025-04-08", 0), ("2025-06-20", 50), ("2025-07-12", 0),
            ("2025-08-01", 40)]
    s = series(rows, known_until="2025-08-05")
    got = promos(s, W, dt("2025-08-05"))
    assert [(p.start, p.end, p.depth) for p in got] == [
        (dt("2025-02-01"), dt("2025-02-10"), 50), (dt("2025-04-01"), dt("2025-04-08"), 50),
        (dt("2025-08-01"), None, 40)]
    # truncated at an earlier as_of: only what was visible then
    assert [p.start for p in promos(s, W, dt("2025-03-01"))] == [dt("2025-02-01")]


def test_window_fraction_matches_hand_computation():
    t0 = dt("2025-01-01")
    day = timedelta(days=1)
    lo, hi = t0, t0 + 100 * day
    assert window_fraction([t0 + 50 * day], lo, hi, 30) == pytest.approx(30 / 70)
    assert window_fraction([t0 + 50 * day, t0 + 60 * day], lo, hi, 30) == pytest.approx(40 / 70)
    assert window_fraction([t0 + 10 * day], lo, hi, 30) == pytest.approx(10 / 70)
    assert window_fraction([t0 + 95 * day], lo, hi, 30) == pytest.approx(5 / 70)
    assert window_fraction([], lo, hi, 30) == 0.0
    assert window_fraction([t0 + 10 * day], lo, t0 + 30 * day, 30) is None


def test_overlaps_respects_started_by():
    a, b = dt("2025-06-20"), dt("2025-06-30")
    assert W.overlaps(a, b)
    assert not W.overlaps(a, b, started_by=dt("2025-06-25"))
    assert W.overlaps(a, b, started_by=dt("2025-06-27"))
    assert not W.overlaps(dt("2025-05-01"), dt("2025-06-25T16:00"))
    assert W.overlaps(dt("2025-05-01"), dt("2025-06-25T18:00"))            # tolerance
