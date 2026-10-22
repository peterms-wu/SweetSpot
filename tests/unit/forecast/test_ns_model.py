"""Model `non-seasonal` 1.0.0 (feature 007 research R1; tasks T005)."""

import random
from datetime import timedelta

import pytest

from sweetspot.forecast.nonseasonal import DEFAULT_PARAMS, HORIZONS, build_ns_model
from sweetspot.forecast.nonseasonal.events import SeasonalWindows
from sweetspot.forecast.nonseasonal.evidence import (ClockTable, NSPopulation, game_evidence_ns, population_share,
                                                     prepare_games)
from sweetspot.forecast.nonseasonal.model import NonSeasonal
from tests.forecast_builders import dt
from tests.ns_builders import SEASONS, game, promo_steps

W = SeasonalWindows(SEASONS)
DAY = timedelta(days=1)
LEVELS = tuple(range(5, 100, 5))
AS_OF = dt("2025-12-01")


def flat_share(value=0.2):
    return {(h, d): value for h in HORIZONS for d in LEVELS}


def evidence_for(rows, as_of=AS_OF, mode="TW", **kw):
    g = prepare_games({1: game(1, rows, tw_until="2026-06-01", **kw)}, W)[1]
    return game_evidence_ns(g, as_of, mode, W, ahead=())


def test_parameters():
    m = build_ns_model("non-seasonal")
    assert dict(m.params) == dict(DEFAULT_PARAMS) == {"smoothing": 2, "history": "TW+US", "clock": True}
    m = NonSeasonal.from_params({"smoothing": "5", "history": "TW", "clock": "false"})
    assert dict(m.params) == {"smoothing": 5, "history": "TW", "clock": False}
    for bad in ({"smoothing": "0"}, {"smoothing": "x"}, {"history": "US"}, {"clock": "maybe"}, {"other": 1}):
        with pytest.raises(ValueError):
            NonSeasonal.from_params(bad)
    assert set(m.confidence_levels()) == {"normal", "low"}


def test_own_share_is_smoothed_toward_the_population():
    rows = promo_steps("2024-12-01", ["2025-01-15", "2025-03-01", "2025-05-01", "2025-07-15", "2025-09-01",
                                      "2025-11-01"])
    ev = evidence_for(rows)
    m = NonSeasonal(smoothing=2, history="TW", clock=False)
    m.prepare(NSPopulation(AS_OF, flat_share(0.2), None))
    out = m.predict(ev)
    from sweetspot.forecast.nonseasonal.events import window_fraction
    start = AS_OF - 365 * DAY
    times = [a.at for a in ev.arrivals if a.to_cut >= 50 and a.at > start]
    f = window_fraction(times, start, AS_OF, 30)
    w = 365 / 30.44 - 30 / 30.44
    assert out.probabilities[0][LEVELS.index(50)] == pytest.approx((w * f + 2 * 0.2) / (w + 2))
    assert out.probabilities[0][LEVELS.index(55)] == pytest.approx(2 * 0.2 / (w + 2))    # never reached -55%
    assert out.confidence == "normal" and out.sources == ("own", "own", "own")


def test_short_history_uses_the_population_share():
    ev = evidence_for(promo_steps("2025-09-15", ["2025-10-01"]))            # 77 days before as_of
    m = NonSeasonal(smoothing=2, history="TW", clock=False)
    m.prepare(NSPopulation(AS_OF, flat_share(0.3), None))
    out = m.predict(ev)
    assert out.sources == ("own", "population", "population")               # 77 >= 30 + 30, < 60 + 30
    assert out.probabilities[1] == pytest.approx((0.3,) * 19)
    assert out.confidence == "low"


def test_clock_ratio_with_layered_smoothing():
    # cells: (h, k, phase, now, seasonal); by_now: (h, k, now, seasonal); by_k: (h, k) → (samples, hits)
    table = ClockTable(cells={(30, 0, 4, False, False): (10, 9)}, by_now={(30, 0, False, False): (100, 30)},
                       by_k={(30, 0): (1000, 200)})
    marg = 0.2
    base = (30 + 20 * marg) / (100 + 20)
    cell = (9 + 20 * base) / (10 + 20)
    assert table.ratio(30, 0, 4, False, False) == pytest.approx(cell / marg)
    assert table.ratio(60, 0, 4, False, False) == 1.0                         # no samples: no adjustment
    ev = evidence_for([("2024-12-01", 0)])                                   # no promotions: k = 0, phase 4
    m = NonSeasonal(smoothing=2, history="TW", clock=True)
    m.prepare(NSPopulation(AS_OF, flat_share(0.1), table))
    out = m.predict(ev)
    no_clock = NonSeasonal(smoothing=2, history="TW", clock=False)
    no_clock.prepare(NSPopulation(AS_OF, flat_share(0.1), table))
    base_out = no_clock.predict(ev)
    assert out.probabilities[0][0] == pytest.approx(base_out.probabilities[0][0] * cell / marg)
    assert out.factors["clock_ratio"][0] == pytest.approx(cell / marg)


def test_cap_and_cumulative_maximum_over_horizons():
    table = ClockTable(cells={(30, 0, 4, False, False): (1000, 1000)}, by_now={}, by_k={(30, 0): (1000, 100)})
    m = NonSeasonal(smoothing=2, history="TW", clock=True)
    m.prepare(NSPopulation(AS_OF, flat_share(1.0), table))
    out = m.predict(evidence_for([("2024-12-01", 0)]))
    assert max(max(row) for row in out.probabilities) == 0.99
    for d in range(len(LEVELS)):
        assert out.probabilities[0][d] <= out.probabilities[1][d] <= out.probabilities[2][d]


def test_monotone_on_random_paths():
    rng = random.Random(7)
    games = {}
    for app in range(1, 41):
        t, rows = dt("2024-06-01"), [("2024-06-01", 0)]
        while t < dt("2026-01-01"):
            t += timedelta(days=rng.randint(10, 80))
            cut = rng.choice([10, 20, 35, 50, 60, 75, 90])
            rows += [(t.isoformat(), cut)]
            if rng.random() < 0.3:
                rows += [((t + timedelta(days=2)).isoformat(), min(cut + 15, 95))]
            t += timedelta(days=rng.randint(3, 14))
            rows += [(t.isoformat(), 0)]
        games[app] = game(app, rows, tw_until="2026-06-01")
    gs = prepare_games(games, W)
    for as_of in (dt("2025-03-01"), dt("2025-09-01"), dt("2026-01-01")):
        m = NonSeasonal(smoothing=2, history="TW", clock=False)
        m.prepare(NSPopulation(as_of, population_share(gs, list(gs), as_of), None))
        for app, g in gs.items():
            out = m.predict(game_evidence_ns(g, as_of, "TW", W, ahead=()))
            for i, row in enumerate(out.probabilities):
                assert all(0 <= p <= 0.99 for p in row)
                assert all(a >= b for a, b in zip(row, row[1:]))
                if i:
                    assert all(a >= b for a, b in zip(row, out.probabilities[i - 1]))
