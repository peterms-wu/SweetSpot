"""What the non-seasonal model sees at an analysis time (feature 007 data-model; research R1, R7).

The framework loads everything up to the data cutoff once and cuts it at each as_of here; the model only gets
NSEvidence and NSPopulation, never the store (constitution IV). Clock samples do not depend on as_of: a sample at t
uses data up to t for its state and (t, t + h] for its outcome, so all of them are built once and each as_of only
adds up the ones that finished at least TOL before it (sample_usable).
"""

import statistics
from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sweetspot.calendar import SaleEvent
from sweetspot.forecast.contract import LEVELS
from sweetspot.forecast.evidence import GameData
from sweetspot.forecast.nonseasonal import CLOCK_SMOOTHING, CLOCK_STEP_DAYS, HORIZONS, LOOKBACK_DAYS, TOL
from sweetspot.forecast.nonseasonal.events import (Arrival, Promo, SeasonalWindows, arrivals, nonseasonal, promos,
                                                   window_fraction)
from sweetspot.forecast.salepoints import sale_points
from sweetspot.forecast.series import PriceSeries

HISTORIES = ("TW", "TW+US")
LOOKBACK = timedelta(days=LOOKBACK_DAYS)
MIN_EXTRA_DAYS = 30          # own history must cover h + 30 days to be used for horizon h (research R1)


@dataclass(frozen=True)
class GameNS:
    """One game's series and upward changes, loaded up to the data cutoff."""

    app_id: int
    tw: PriceSeries
    us: PriceSeries | None
    tw_arrivals: tuple[Arrival, ...]
    us_arrivals: tuple[Arrival, ...]


def prepare_games(games: Mapping[int, GameData], windows: SeasonalWindows) -> dict[int, GameNS]:
    out = {}
    for app, g in games.items():
        tw = g.series.get("TW")
        if tw is None or not tw.states:
            continue
        us = g.series.get("US")
        us = us if us is not None and us.states else None
        out[app] = GameNS(app, tw, us, arrivals(tw, windows), arrivals(us, windows) if us else ())
    return out


def _us_fills(g: GameNS, mode: str) -> bool:
    return mode == "TW+US" and g.us is not None and g.us.first_start < g.tw.first_start


def _view(g: GameNS, as_of: datetime, mode: str) -> tuple[list[Arrival], datetime, str]:
    """Non-seasonal arrivals visible at as_of, the history start and its source (research R1 `history`)."""
    tw = nonseasonal(g.tw_arrivals, as_of)
    if _us_fills(g, mode):
        us = [a for a in nonseasonal(g.us_arrivals, as_of) if a.at < g.tw.first_start]
        return us + tw, g.us.first_start, "TW+US"
    return tw, g.tw.first_start, "TW"


@dataclass(frozen=True)
class NSEvidence:
    app_id: int
    as_of: datetime
    arrivals: tuple[Arrival, ...]                 # non-seasonal, visible at as_of, oldest first
    history_start: datetime
    history_source: str                           # TW | TW+US
    known_until: datetime                         # TW history known up to here (<= as_of)
    discounted_now: bool
    seasonal_ahead: tuple[tuple[datetime, datetime], ...]    # known or estimated sales not yet over
    promos: tuple[Promo, ...]                     # for the basis only


def game_evidence_ns(g: GameNS, as_of: datetime, mode: str, windows: SeasonalWindows,
                     ahead: Iterable[tuple[datetime, datetime]]) -> NSEvidence:
    items, start, source = _view(g, as_of, mode)
    known = as_of if g.tw.known_until is None else min(g.tw.known_until, as_of)
    state = g.tw.state_at(as_of)
    found = list(promos(g.tw, windows, as_of))
    if source == "TW+US":
        found = [p for p in promos(g.us, windows, as_of) if p.start < g.tw.first_start] + found
    return NSEvidence(g.app_id, as_of, tuple(items), start, source, known, bool(state and state.cut > 0),
                      tuple(ahead), tuple(found))


@dataclass(frozen=True)
class NSBasis:
    """The facts behind a forecast (spec FR-006; contracts/ns-model-api.md wording)."""

    history_start: datetime
    history_source: str
    history_days: int
    promos_365d: int
    interval_days: int | None       # median gap between promotion starts in the past year (2+ promotions)
    common_depth: int | None        # most common depth in the past year; a tie goes to the deeper one
    last_start: datetime | None
    last_depth: int | None
    days_since: int | None
    in_promo_now: bool


def basis(ev: NSEvidence) -> NSBasis:
    year = [p for p in ev.promos if ev.as_of - LOOKBACK < p.start <= ev.as_of]
    gaps = [(b.start - a.start).days for a, b in zip(year, year[1:])]
    interval = int(statistics.median(gaps) + 0.5) if gaps else None
    counts = Counter(p.depth for p in year)
    common = max(counts, key=lambda d: (counts[d], d)) if counts else None
    last = ev.promos[-1] if ev.promos else None
    return NSBasis(ev.history_start, ev.history_source, (ev.as_of - ev.history_start).days, len(year), interval,
                   common, last.start if last else None, last.depth if last else None,
                   (ev.as_of - last.start).days if last else None, bool(last and last.end is None))


# --- the clock ---------------------------------------------------------------------------------------------

def kgroup(n: int) -> int:
    return 0 if n == 0 else 1 if n <= 2 else 2 if n <= 4 else 3


def clock_state(starts: Sequence[datetime], t: datetime) -> tuple[int, int]:
    """(promotion-count group, phase) at t from non-seasonal promotion starts: count in the past 365 days
    (0 / 1-2 / 3-4 / 5+); phase = days since the last start ÷ the median gap (<0.5 / 0.5-1 / 1-1.5 / ≥1.5), or 4
    with fewer than 3 starts."""
    year = [s for s in starts if t - LOOKBACK < s <= t]
    phase = 4
    if len(year) >= 3:
        med = statistics.median((b - a).days for a, b in zip(year, year[1:]))
        r = (t - year[-1]).days / med if med else 9
        phase = 0 if r < 0.5 else 1 if r < 1 else 2 if r < 1.5 else 3
    return kgroup(len(year)), phase


def sample_usable(t: datetime, h: int, as_of: datetime) -> bool:
    """A clock sample counts at as_of when it lies within the lookback and its window ended TOL before as_of. A
    module attribute so the leak test can swap in a peeking version."""
    return as_of - LOOKBACK <= t and t + timedelta(days=h) + TOL <= as_of


@dataclass(frozen=True)
class SampleRow:
    app_id: int
    t: datetime
    kgroup: int
    phase: int
    discounted: bool
    outcomes: Mapping[int, tuple[bool, bool]]     # h -> (seasonal sale inside (t, t+h], any non-seasonal arrival)


@dataclass(frozen=True)
class ClockTable:
    """(samples, hits) by (h, k, phase, discounted, seasonal), by (h, k, discounted, seasonal) and by (h, k)."""

    cells: Mapping[tuple, tuple[int, int]]
    by_now: Mapping[tuple, tuple[int, int]]
    by_k: Mapping[tuple, tuple[int, int]]

    def ratio(self, h: int, k: int, phase: int, discounted: bool, seasonal: bool) -> float:
        n0, r0 = self.by_k.get((h, k), (0, 0))
        marg = r0 / n0 if n0 else 0.0
        if not marg:
            return 1.0
        n1, r1 = self.by_now.get((h, k, discounted, seasonal), (0, 0))
        base = (r1 + CLOCK_SMOOTHING * marg) / (n1 + CLOCK_SMOOTHING)
        n2, r2 = self.cells.get((h, k, phase, discounted, seasonal), (0, 0))
        return (r2 + CLOCK_SMOOTHING * base) / (n2 + CLOCK_SMOOTHING) / marg

    def total(self, h: int) -> int:
        return sum(n for (hh, _), (n, _) in self.by_k.items() if hh == h)


class ClockSamples:
    """Every game every CLOCK_STEP_DAYS from 30 days after its TW tracking start (research R1 `clock`)."""

    def __init__(self, games: Mapping[int, GameNS], mode: str, windows: SeasonalWindows,
                 since: datetime | None = None):
        rows = []
        step, first_gap = timedelta(days=CLOCK_STEP_DAYS), timedelta(days=MIN_EXTRA_DAYS)
        shortest = timedelta(days=min(HORIZONS))
        for app in sorted(games):
            g = games[app]
            known = g.tw.known_until
            if known is None:
                continue
            items = [a for a in g.tw_arrivals if not a.seasonal()]
            if _us_fills(g, mode):
                items = [a for a in g.us_arrivals if not a.seasonal() and a.at < g.tw.first_start] + items
            starts = [a.at for a in items if a.from_cut == 0]
            tw_times = [a.at for a in g.tw_arrivals if not a.seasonal()]
            t = g.tw.first_start + first_gap
            while t + shortest <= known:
                if since is None or t >= since:
                    upto = starts[:bisect_right(starts, t)]
                    k, phase = clock_state(upto, t)
                    state = g.tw.state_at(t)
                    outcomes = {}
                    for h in HORIZONS:
                        end = t + timedelta(days=h)
                        if end > known:
                            break
                        hit = bisect_right(tw_times, end) > bisect_right(tw_times, t)
                        outcomes[h] = (windows.overlaps(t, end), hit)
                    rows.append(SampleRow(app, t, k, phase, bool(state and state.cut > 0), outcomes))
                t += step
        rows.sort(key=lambda r: (r.t, r.app_id))
        self.rows = rows
        self._times = [r.t for r in rows]

    def table(self, as_of: datetime, apps: set[int]) -> ClockTable:
        cells: dict = {}
        by_now: dict = {}
        by_k: dict = {}
        lo = bisect_left(self._times, as_of - LOOKBACK)
        hi = bisect_right(self._times, as_of)
        for r in self.rows[lo:hi]:
            if r.app_id not in apps:
                continue
            for h, (seasonal, hit) in r.outcomes.items():
                if not sample_usable(r.t, h, as_of):
                    continue
                for table, key in ((cells, (h, r.kgroup, r.phase, r.discounted, seasonal)),
                                   (by_now, (h, r.kgroup, r.discounted, seasonal)), (by_k, (h, r.kgroup))):
                    n, x = table.get(key, (0, 0))
                    table[key] = (n + 1, x + hit)
        return ClockTable(cells, by_now, by_k)


# --- the population ----------------------------------------------------------------------------------------

def population_share(games: Mapping[int, GameNS], apps: Iterable[int], as_of: datetime) -> dict[tuple[int, int], float]:
    """b(h, d): the mean over games of their own share of past windows with an arrival of d (TW only; games whose
    history covers h + 30 days). Missing levels are 0."""
    sums: Counter = Counter()
    counts: Counter = Counter()
    for app in apps:
        g = games.get(app)
        if g is None:
            continue
        start = max(g.tw.first_start, as_of - LOOKBACK)
        hi = as_of if g.tw.known_until is None else min(g.tw.known_until, as_of)
        items = [a for a in nonseasonal(g.tw_arrivals, as_of) if start < a.at <= hi]
        for h in HORIZONS:
            if (hi - start).days < h + MIN_EXTRA_DAYS:
                continue
            for d in LEVELS:
                f = window_fraction([a.at for a in items if a.reaches(d)], start, hi, h)
                if f is not None:
                    sums[(h, d)] += f
                    counts[(h, d)] += 1
    return {(h, d): sums[(h, d)] / counts[(h, d)] if counts[(h, d)] else 0.0 for h in HORIZONS for d in LEVELS}


@dataclass(frozen=True)
class NSPopulation:
    as_of: datetime
    share: Mapping[tuple[int, int], float]
    clock: ClockTable | None


class NSFrame:
    """Everything loaded up to the data cutoff, cut at any as_of (backtest), or at the present (live = True: the
    events are store.sales(now), announced future sales included)."""

    def __init__(self, games: Mapping[int, GameData], events: Sequence[SaleEvent], mode: str, *,
                 population: Sequence[int], clock: bool = True, since: datetime | None = None, live: bool = False,
                 share_cache: dict | None = None):
        if mode not in HISTORIES:
            raise ValueError(f"history 必須是 {', '.join(HISTORIES)} 之一：{mode!r}")
        self.events = list(events)
        self.mode = mode
        self.live = live
        self.windows = SeasonalWindows.from_events(self.events)
        self.games = prepare_games(games, self.windows)
        pool = {a: self.games[a] for a in population if a in self.games}
        self.samples = ClockSamples(pool, mode, self.windows, since) if clock else None
        self._ahead: dict[datetime, tuple] = {}
        self._shares = share_cache if share_cache is not None else {}     # b(h, d) does not depend on `history`

    def ahead(self, as_of: datetime) -> tuple[tuple[datetime, datetime], ...]:
        """Seasonal sales not over at as_of: running ones and the known or estimated future points."""
        known = self.events if self.live else [e for e in self.events if e.start <= as_of]
        points = sale_points(known, as_of)
        running = [(e.start, e.end) for e in known if e.kind == "seasonal" and e.start <= as_of < e.end]
        return tuple(running + [(p.start, p.end) for p in points])

    def _ahead_at(self, as_of: datetime):
        if as_of not in self._ahead:
            self._ahead[as_of] = self.ahead(as_of)
        return self._ahead[as_of]

    def population_at(self, as_of: datetime, apps: Sequence[int]) -> NSPopulation:
        key = (as_of, tuple(sorted(apps)))
        if key not in self._shares:
            self._shares[key] = population_share(self.games, apps, as_of)
        return NSPopulation(as_of, self._shares[key], self.samples.table(as_of, set(apps)) if self.samples else None)

    def evidence(self, app: int, as_of: datetime) -> NSEvidence:
        return game_evidence_ns(self.games[app], as_of, self.mode, self.windows, self._ahead_at(as_of))


__all__ = ["ClockSamples", "ClockTable", "GameNS", "HISTORIES", "NSBasis", "NSEvidence", "NSFrame", "NSPopulation",
           "SampleRow", "basis", "clock_state", "game_evidence_ns", "population_share", "prepare_games",
           "sample_usable"]
