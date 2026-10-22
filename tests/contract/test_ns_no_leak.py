"""Non-seasonal forecasts never see anything after as_of (feature 007 spec FR-011, SC-002; tasks T006).

Everything after as_of is tampered with (prices in both regions, "known until", the calendar), and the forecast at
as_of must not change. Three deliberately peeking variants prove that the test can catch each kind of leak.
"""

from datetime import timedelta

import pytest

from sweetspot.calendar import SaleEvent
from sweetspot.forecast.nonseasonal import events as ns_events
from sweetspot.forecast.nonseasonal import evidence as ns_evidence
from sweetspot.forecast.nonseasonal.evidence import NSFrame
from sweetspot.forecast.nonseasonal.model import NonSeasonal
from tests.forecast_builders import dt
from tests.ns_builders import game

AS_OF = dt("2025-08-01")
DAY = timedelta(days=1)


def sale(season, year, start, end):
    return SaleEvent(f"{season} sale", "特賣", "seasonal", season, year, dt(start), dt(end), "ended", "https://x.test")


CALENDAR = [sale("winter", 2023, "2023-12-21T18:00", "2024-01-04T18:00"),
            sale("spring", 2024, "2024-03-14T17:00", "2024-03-21T17:00"),
            sale("summer", 2024, "2024-06-27T17:00", "2024-07-11T17:00"),
            sale("autumn", 2024, "2024-11-27T18:00", "2024-12-04T18:00"),
            sale("winter", 2024, "2024-12-19T18:00", "2025-01-02T18:00"),
            sale("spring", 2025, "2025-03-13T17:00", "2025-03-20T17:00"),
            sale("summer", 2025, "2025-06-26T17:00", "2025-07-10T17:00"),
            sale("autumn", 2025, "2025-09-29T17:00", "2025-10-06T17:00"),
            sale("winter", 2025, "2025-12-18T18:00", "2026-01-05T18:00")]


def rows(first, starts, cut=50, days=7):
    out = [(first, 0)]
    for s in starts:
        out += [(s, cut), ((dt(s) + days * DAY).isoformat(), 0)]
    return out


BEFORE = {
    1: rows("2024-01-10", ["2024-02-10", "2024-04-15", "2024-05-25", "2024-08-20", "2024-10-01", "2025-01-20",
                           "2025-02-25", "2025-04-10", "2025-05-20"]),
    2: rows("2024-02-01", ["2024-09-10", "2025-04-20"], cut=30),
    3: rows("2024-05-01", ["2024-06-01", "2024-10-15", "2025-02-01", "2025-05-01"], cut=75),
    # an arrival 6 hours before as_of: a surprise sale starting 12 hours after as_of must not make it seasonal
    4: rows("2024-03-01", ["2024-09-01", "2025-01-15", "2025-05-05"]) + [("2025-07-31T18:00", 40)],
}
AFTER = {1: rows("2025-08-01T06:00", ["2025-08-20", "2025-10-15"])[1:], 2: [("2025-08-05", 90)],
         3: rows("2025-08-01T06:00", ["2025-08-10"])[1:], 4: [("2025-08-03", 0), ("2025-08-25", 60)]}
US = rows("2022-01-01", ["2022-03-01", "2022-06-01", "2022-10-01", "2023-02-01", "2023-06-10", "2023-09-01"])


def build(tamper: bool):
    games = {}
    for app, before in BEFORE.items():
        after = [(t, min(c + 45, 95) if c else 0) for t, c in AFTER[app]] + [("2026-02-01", 95)] if tamper \
            else AFTER[app]
        us_after = [("2025-09-01", 80)] if tamper else []
        games[app] = game(app, before + after, US + us_after, tw_until="2026-09-01" if tamper else "2026-09-24",
                          us_until="2026-08-01" if tamper else "2026-09-24")
    calendar = [e for e in CALENDAR if not tamper or e.start <= AS_OF]
    if tamper:
        calendar.append(sale("autumn", 2025, "2025-08-01T12:00", "2025-08-08T12:00"))     # a "surprise" date
    return games, calendar


def predictions(tamper: bool, params=None):
    games, calendar = build(tamper)
    model = NonSeasonal.from_params(params or {})
    frame = NSFrame(games, calendar, model.history, population=list(games))
    model.prepare(frame.population_at(AS_OF, list(games)))
    return {app: model.predict(frame.evidence(app, AS_OF)) for app in games}


PARAMS = [{}, {"history": "TW"}, {"clock": "false"}, {"smoothing": "5"}]


@pytest.mark.parametrize("params", PARAMS)
def test_tampering_after_as_of_changes_nothing(params):
    a, b = predictions(False, params), predictions(True, params)
    assert a == b
    assert any(max(max(r) for r in out.probabilities) > 0 for out in a.values())


def _differs():
    return predictions(False) != predictions(True)


def test_catches_clock_samples_that_end_after_as_of(monkeypatch):
    monkeypatch.setattr(ns_evidence, "sample_usable", lambda t, h, as_of: t >= as_of - 365 * DAY)
    assert _differs()


def test_catches_a_later_sale_reclassifying_a_past_arrival(monkeypatch):
    monkeypatch.setattr(ns_events, "known_at", lambda window_start, as_of: True)
    assert _differs()


def test_catches_the_real_calendar_instead_of_estimates(monkeypatch):
    def peek(frame, as_of):
        return tuple((e.start, e.end) for e in frame.events if e.kind == "seasonal" and e.end > as_of)
    monkeypatch.setattr(NSFrame, "ahead", peek)
    assert _differs()
