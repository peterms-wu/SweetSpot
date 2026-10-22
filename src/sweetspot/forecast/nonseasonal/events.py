"""Non-seasonal arrivals and promotions (feature 007 spec FR-001, clarify 2026-09-26).

- A non-seasonal arrival of level d: a price change, not the tracking start, where the cut goes from < d to >= d
  outside every seasonal sale window [start − TOL, end). It is the event the model forecasts and the backtest scores.
- A non-seasonal promotion: a discount episode (from no discount back to no discount) that overlaps no seasonal
  window. Only the report's basis (count, interval, depth) uses it.

Which windows count depends on when you look: at as_of only sales that had started by then are known, so a change
just before a sale that starts after as_of is still non-seasonal at as_of (research R1, "資料的時點").
"""

from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sweetspot.forecast.nonseasonal import TOL
from sweetspot.forecast.series import PriceSeries


def known_at(window_start: datetime, as_of: datetime) -> bool:
    """A sale window counts at as_of only once the sale has started. A module attribute so the leak test can
    swap in a peeking version."""
    return window_start <= as_of


class SeasonalWindows:
    """Seasonal sale periods, each extended by TOL before its start."""

    def __init__(self, windows: Iterable[tuple[datetime, datetime]]):
        self.windows = tuple(sorted(windows))
        self._starts = [s - TOL for s, _ in self.windows]

    @classmethod
    def from_events(cls, events) -> "SeasonalWindows":
        return cls((e.start, e.end) for e in events if e.kind == "seasonal")

    def window_start(self, t: datetime) -> datetime | None:
        """The start of the sale whose window contains t, or None."""
        i = bisect_right(self._starts, t) - 1          # seasonal sales never overlap each other
        if i >= 0 and t < self.windows[i][1]:
            return self.windows[i][0]
        return None

    def overlaps(self, a: datetime, b: datetime, started_by: datetime | None = None) -> bool:
        """Does any window [start − TOL, end) intersect the period from a to b? With started_by, only sales that had
    started by then."""
        i = bisect_left(self._starts, b) - 1           # the last window starting (minus TOL) before b
        while i >= 0:
            s, e = self.windows[i]
            if e <= a:                                  # sorted and disjoint: every earlier one ends even sooner
                return False
            if started_by is None or known_at(s, started_by):
                return True
            i -= 1
        return False


@dataclass(frozen=True)
class Arrival:
    at: datetime
    from_cut: int
    to_cut: int
    window_start: datetime | None        # the seasonal sale this change falls in, if any

    def reaches(self, d: int) -> bool:
        return self.from_cut < d <= self.to_cut

    def seasonal(self, as_of: datetime | None = None) -> bool:
        """Inside a seasonal window known at as_of (None: the whole calendar, for scoring)."""
        if self.window_start is None:
            return False
        return as_of is None or known_at(self.window_start, as_of)


@dataclass(frozen=True)
class Promo:
    start: datetime
    end: datetime | None                 # None: still running at as_of
    depth: int


def arrivals(series: PriceSeries, windows: SeasonalWindows) -> tuple[Arrival, ...]:
    """Every upward change of the series (seasonal ones included, annotated with their window)."""
    st = series.states
    return tuple(Arrival(st[i].start, st[i - 1].cut, st[i].cut, windows.window_start(st[i].start))
                 for i in range(1, len(st)) if not st[i].is_tracking_start and st[i].cut > st[i - 1].cut)


def nonseasonal(items: Sequence[Arrival], as_of: datetime) -> list[Arrival]:
    """The non-seasonal arrivals visible at as_of."""
    return [a for a in items if a.at <= as_of and not a.seasonal(as_of)]


def arrived_levels(items: Sequence[Arrival], lo: datetime, hi: datetime, levels: Sequence[int]) -> set[int]:
    """Levels with a non-seasonal arrival in (lo, hi], judged with the whole calendar (scoring)."""
    got: set[int] = set()
    for a in items:
        if lo < a.at <= hi and not a.seasonal():
            got.update(d for d in levels if a.reaches(d))
    return got


def promos(series: PriceSeries, windows: SeasonalWindows, as_of: datetime) -> tuple[Promo, ...]:
    """Non-seasonal promotions visible at as_of: episodes that started after the tracking start and overlap no
    seasonal window known at as_of. A running episode is judged up to what is known."""
    st = [s for s in series.states if s.start <= as_of]
    known = as_of if series.known_until is None else min(series.known_until, as_of)
    out = []
    i = 1
    while i < len(st):
        if st[i].cut > 0 and st[i - 1].cut == 0 and not st[i].is_tracking_start:
            j, depth = i, 0
            while j < len(st) and st[j].cut > 0:
                depth = max(depth, st[j].cut)
                j += 1
            end = st[j].start if j < len(st) else None
            if not windows.overlaps(st[i].start, end or known, started_by=as_of):
                out.append(Promo(st[i].start, end, depth))
            i = j
        else:
            i += 1
    return tuple(out)


def window_fraction(times: Sequence[datetime], lo: datetime, hi: datetime, h: int) -> float | None:
    """Share of start points t in [lo, hi − h] whose window (t, t + h] contains one of `times` (exact, continuous).
    None when there is no such start point."""
    end = hi - timedelta(days=h)
    if end <= lo:
        return None
    span = timedelta(days=h)
    covered = timedelta(0)
    cur_a = cur_b = None
    for a in sorted(times):
        s, e = max(a - span, lo), min(a, end)
        if e <= s:
            continue
        if cur_b is not None and s <= cur_b:
            cur_b = max(cur_b, e)
            continue
        if cur_b is not None:
            covered += cur_b - cur_a
        cur_a, cur_b = s, e
    if cur_b is not None:
        covered += cur_b - cur_a
    return covered / (end - lo)
