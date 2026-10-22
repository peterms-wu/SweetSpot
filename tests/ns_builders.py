"""Synthetic price series for feature 007 tests (tasks T002). Times are UTC; a bare date means 00:00 UTC."""

from datetime import timedelta

from sweetspot.forecast.evidence import GameData
from sweetspot.forecast.series import PriceSeries, PriceState
from tests.forecast_builders import dt

REGULAR = 50000


def series(steps, region: str = "TW", known_until: str | None = None, regular: int = REGULAR) -> PriceSeries:
    """`steps` = [(time, cut), …]; the first row is the tracking start. known_until defaults to the last row + 1 day."""
    states = tuple(PriceState(dt(t), cut, i == 0, regular) for i, (t, cut) in enumerate(steps))
    until = dt(known_until) if known_until else states[-1].start + timedelta(days=1)
    return PriceSeries(region, states, until)


def windows(*pairs):
    """Seasonal sale periods [(start, end), …] as datetimes."""
    return [(dt(a), dt(b)) for a, b in pairs]


def game(app_id: int, tw, us=None, *, tw_until: str | None = None, us_until: str | None = None) -> GameData:
    data = {"TW": series(tw, "TW", tw_until)}
    if us:
        data["US"] = series(us, "US", us_until)
    return GameData(app_id, data, {r: () for r in data})


def promo_steps(first: str, starts, *, days: int = 7, cut: int = 50):
    """A tracking start at `first` (no discount) then a `cut` promotion of `days` days at each start."""
    rows = [(first, 0)]
    for s in starts:
        rows += [(s, cut), ((dt(s) + timedelta(days=days)).isoformat(), 0)]
    return rows


# Seasonal sales used by most tests (TOL = 1 day before each start counts as seasonal).
SEASONS = windows(("2025-03-13T17:00", "2025-03-20T17:00"), ("2025-06-26T17:00", "2025-07-10T17:00"),
                  ("2025-09-29T17:00", "2025-10-06T17:00"), ("2025-12-18T18:00", "2026-01-05T18:00"),
                  ("2026-03-19T17:00", "2026-03-26T17:00"), ("2026-06-25T17:00", "2026-07-09T17:00"))
