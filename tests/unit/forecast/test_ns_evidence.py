"""What the non-seasonal model sees (feature 007 data-model; tasks T004)."""

from datetime import timedelta

import pytest

from sweetspot.forecast.nonseasonal.events import SeasonalWindows, window_fraction
from sweetspot.forecast.nonseasonal.evidence import (ClockSamples, basis, clock_state, game_evidence_ns,
                                                     population_share, prepare_games)
from tests.forecast_builders import dt
from tests.ns_builders import SEASONS, game, promo_steps

W = SeasonalWindows(SEASONS)
DAY = timedelta(days=1)


def test_evidence_only_sees_the_past():
    g = prepare_games({1: game(1, promo_steps("2025-01-01", ["2025-02-01", "2025-04-01", "2025-05-01"]),
                               tw_until="2025-09-01")}, W)[1]
    ev = game_evidence_ns(g, dt("2025-04-15"), "TW", W, ahead=())
    assert [a.at for a in ev.arrivals] == [dt("2025-02-01"), dt("2025-04-01")]
    assert ev.known_until == dt("2025-04-15")
    assert ev.history_start == dt("2025-01-01") and ev.history_source == "TW"
    assert not ev.discounted_now
    assert game_evidence_ns(g, dt("2025-04-03"), "TW", W, ahead=()).discounted_now


def test_us_fills_only_the_time_before_tw_tracking():
    tw = promo_steps("2025-01-01", ["2025-02-01"])
    us = promo_steps("2024-01-01", ["2024-04-01", "2024-08-01", "2025-02-01"])
    g = prepare_games({1: game(1, tw, us, tw_until="2025-09-01", us_until="2025-09-01")}, W)[1]
    ev = game_evidence_ns(g, dt("2025-03-01"), "TW+US", W, ahead=())
    assert [a.at for a in ev.arrivals] == [dt("2024-04-01"), dt("2024-08-01"), dt("2025-02-01")]
    assert ev.history_start == dt("2024-01-01") and ev.history_source == "TW+US"
    tw_only = game_evidence_ns(g, dt("2025-03-01"), "TW", W, ahead=())
    assert [a.at for a in tw_only.arrivals] == [dt("2025-02-01")]


def test_basis_fields():
    starts = ["2025-01-10", "2025-02-20", "2025-04-10", "2025-05-15"]
    rows = [("2024-12-01", 0), ("2025-01-10", 50), ("2025-01-17", 0), ("2025-02-20", 40), ("2025-02-27", 0),
            ("2025-04-10", 40), ("2025-04-17", 0), ("2025-05-15", 50), ("2025-05-22", 0)]
    g = prepare_games({1: game(1, rows, tw_until="2025-09-01")}, W)[1]
    b = basis(game_evidence_ns(g, dt("2025-06-01"), "TW", W, ahead=()))
    assert b.promos_365d == 4
    gaps = [(dt(b_) - dt(a)).days for a, b_ in zip(starts, starts[1:])]      # 41, 49, 35
    assert b.interval_days == sorted(gaps)[1]
    assert b.common_depth == 50                     # 2 × 50 and 2 × 40: the deeper wins a tie
    assert (b.last_start, b.last_depth, b.days_since) == (dt("2025-05-15"), 50, 17)
    assert b.history_days == (dt("2025-06-01") - dt("2024-12-01")).days
    assert not b.in_promo_now
    one = basis(game_evidence_ns(g, dt("2025-01-20"), "TW", W, ahead=()))
    assert one.promos_365d == 1 and one.interval_days is None
    running = basis(game_evidence_ns(g, dt("2025-05-18"), "TW", W, ahead=()))
    assert running.in_promo_now


def test_clock_state_groups():
    t = dt("2025-12-01")
    assert clock_state([], t) == (0, 4)
    assert clock_state([t - 10 * DAY], t) == (1, 4)
    starts = [t - 130 * DAY, t - 90 * DAY, t - 50 * DAY, t - 10 * DAY]      # every 40 days, 10 days since the last
    assert clock_state(starts, t) == (2, 0)                                   # 10 / 40 < 0.5
    assert clock_state(starts, t + 20 * DAY) == (2, 1)                        # 30 / 40
    assert clock_state(starts, t + 40 * DAY) == (2, 2)                        # 50 / 40
    assert clock_state(starts, t + 60 * DAY) == (2, 3)                        # 70 / 40
    assert clock_state([t - 400 * DAY] + starts, t)[0] == 2                   # older than 365 days: not counted


def test_clock_samples_use_the_past_for_features_and_the_window_for_outcomes():
    rows = promo_steps("2025-01-01", ["2025-02-15", "2025-04-15", "2025-08-01"])
    g = prepare_games({1: game(1, rows, tw_until="2026-01-01")}, W)
    samples = ClockSamples(g, "TW", W)
    first = samples.rows[0]
    assert first.t == dt("2025-01-31")                                   # tracking start + 30 days
    assert (first.kgroup, first.discounted) == (0, False)                 # the 02-15 start is later
    assert first.outcomes[30][1] is True                                  # 02-15 lies in (t, t + 30]
    assert all(r.t - dt("2025-01-31") == (r.t - first.t) for r in samples.rows)
    assert all((r.t - first.t).days % 14 == 0 for r in samples.rows)
    later = next(r for r in samples.rows if r.t > dt("2025-04-20"))
    assert later.kgroup == 1                                              # 2 starts in the past year
    for r in samples.rows:
        for h, (seasonal, hit) in r.outcomes.items():
            assert r.t + h * DAY <= dt("2026-01-01")
            assert seasonal == W.overlaps(r.t, r.t + h * DAY)


def test_clock_table_only_uses_samples_finished_before_as_of():
    rows = promo_steps("2024-01-01", ["2024-03-01", "2024-06-01", "2024-09-01", "2025-02-01", "2025-05-01"])
    g = prepare_games({1: game(1, rows, tw_until="2026-01-01")}, W)
    samples = ClockSamples(g, "TW", W)
    as_of = dt("2025-08-01")
    table = samples.table(as_of, {1})
    expected = {h: sum(1 for r in samples.rows if h in r.outcomes and as_of - 365 * DAY <= r.t
                       and r.t + (h + 1) * DAY <= as_of) for h in (30, 60, 90)}
    assert {h: table.total(h) for h in (30, 60, 90)} == expected
    assert samples.table(as_of, set()).total(30) == 0


def test_population_share_excludes_short_histories():
    long_ = promo_steps("2024-06-01", ["2024-08-01", "2024-11-01", "2025-02-01"])
    short = promo_steps("2025-04-01", ["2025-04-10"])
    gs = prepare_games({1: game(1, long_, tw_until="2025-09-01"), 2: game(2, short, tw_until="2025-09-01")}, W)
    as_of = dt("2025-05-01")
    share = population_share(gs, [1, 2], as_of)
    lo = as_of - 365 * DAY
    times = [dt("2024-08-01"), dt("2024-11-01"), dt("2025-02-01")]
    assert share[(30, 50)] == pytest.approx(window_fraction(times, dt("2024-06-01"), as_of, 30))
    assert share[(30, 55)] == 0.0
    assert lo < dt("2024-06-01")
