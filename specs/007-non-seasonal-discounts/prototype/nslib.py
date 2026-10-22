"""Shared prototype helpers (feature 007 plan): non-seasonal arrivals, candidate models, scoring units.

Definitions (spec FR-001, clarify 2026-09-26):
- non-seasonal arrival of level d: a price change outside every seasonal sale window (with TOL before the start)
  where the cut goes from < d to >= d; tracking starts are never arrivals.
- non-seasonal promotion (report basis only): a discount episode that overlaps no seasonal sale.
"""
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import UTC, datetime, timedelta

LEVELS = tuple(range(5, 100, 5))
HORIZONS = (30, 60, 90)
TOL = timedelta(days=1)
CUTOFF = datetime(2026, 9, 25, tzinfo=UTC)
DAY = 86400.0


class Windows:
    def __init__(self, seasonal):
        self.w = sorted(seasonal)
        self.starts = [s - TOL for s, _ in self.w]

    def inside(self, t):
        i = bisect_right(self.starts, t) - 1
        return i >= 0 and t < self.w[i][1]

    def overlaps(self, a, b):
        return any(s - TOL < b and a < e for s, e in self.w)


def arrivals(series, win):
    """[(t, prev_cut, cut)] non-seasonal upward changes."""
    out, st = [], series.states
    for i in range(1, len(st)):
        s = st[i]
        if s.is_tracking_start or s.cut <= st[i - 1].cut:
            continue
        if not win.inside(s.start):
            out.append((s.start, st[i - 1].cut, s.cut))
    return out


def promos(series, win):
    """Non-seasonal promotion starts [(t, deepest non-seasonal cut of that episode)] (0 -> >0 outside seasonal)."""
    out, st = [], series.states
    i = 1
    while i < len(st):
        if st[i].cut > 0 and st[i - 1].cut == 0 and not st[i].is_tracking_start and not win.inside(st[i].start):
            best, j = 0, i
            while j < len(st) and st[j].cut > 0:
                if not win.inside(st[j].start):
                    best = max(best, st[j].cut)
                j += 1
            out.append((st[i].start, best))
            i = j
        else:
            i += 1
    return out


def arrived(arrs, lo, hi):
    """Levels with an arrival in (lo, hi]."""
    got = set()
    for t, p, c in arrs:
        if lo < t <= hi:
            got.update(d for d in LEVELS if p < d <= c)
    return got


def window_fraction(times, lo, hi, h):
    """Share of start points t in [lo, hi - h] whose window (t, t+h] contains one of `times` (continuous)."""
    end = hi - timedelta(days=h)
    if end <= lo:
        return None
    total = (end - lo).total_seconds()
    covered, cur_a, cur_b = 0.0, None, None
    for a in times:
        s, e = max(a - timedelta(days=h), lo), min(a, end)
        if e <= s:
            continue
        if cur_b is not None and s <= cur_b:
            cur_b = max(cur_b, e)
        else:
            if cur_b is not None:
                covered += (cur_b - cur_a).total_seconds()
            cur_a, cur_b = s, e
    if cur_b is not None:
        covered += (cur_b - cur_a).total_seconds()
    return covered / total


def own_fraction(arrs, lo, hi, h, d):
    times = sorted(t for t, p, c in arrs if p < d <= c and lo < t <= hi)
    return window_fraction(times, lo, hi, h)


class GameNS:
    """Per-game non-seasonal data for one region, precomputed once."""

    def __init__(self, series, win):
        self.series = series
        self.arrs = arrivals(series, win)
        self.promos = promos(series, win)
        self.first = series.states[0].start if series.states else None
        self.known = series.known_until


def history_view(tw: GameNS, us: GameNS | None, mode: str, as_of):
    """(arrivals, promos, history start) visible at as_of. TW+US fills the period before TW tracking with US."""
    arrs = [a for a in tw.arrs if a[0] <= as_of]
    prom = [p for p in tw.promos if p[0] <= as_of]
    start = tw.first
    if mode == "TW+US" and us is not None and us.first is not None and us.first < tw.first:
        arrs = [a for a in us.arrs if a[0] < tw.first] + arrs
        prom = [p for p in us.promos if p[0] < tw.first] + prom
        start = us.first
    return arrs, prom, start
