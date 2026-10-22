"""Price-state series and seasonal-sale outcomes (research R1, R3).

An ITAD history row is a price *state* that starts at observed_at and holds until the next row. The first row
of a series is the tracking start: the state already in effect, not a price change.
"""

from bisect import bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from sweetspot.calendar import SaleEvent, label
from sweetspot.store.query import SERIES_SOURCES, Observation


@dataclass(frozen=True)
class PriceState:
    start: datetime
    cut: int
    is_tracking_start: bool
    regular_cents: int | None = None


@dataclass(frozen=True)
class PriceSeries:
    region: str
    states: tuple[PriceState, ...]
    known_until: datetime | None      # history confirmed up to here; later changes are unknown, not absent

    @property
    def first_start(self) -> datetime | None:
        return self.states[0].start if self.states else None

    def _index_at(self, moment: datetime) -> int:
        """Index of the state in effect at `moment` (-1 if the series has not started)."""
        return bisect_right([s.start for s in self.states], moment) - 1

    def state_at(self, moment: datetime) -> PriceState | None:
        i = self._index_at(moment)
        return self.states[i] if i >= 0 else None

    def truncate(self, as_of: datetime) -> "PriceSeries":
        known = as_of if self.known_until is None else min(self.known_until, as_of)
        return PriceSeries(self.region, tuple(s for s in self.states if s.start <= as_of), known)

    def events_after(self, as_of: datetime) -> list[PriceState]:
        """Price changes that take effect after as_of (tracking starts are never changes)."""
        return [s for s in self.states if s.start > as_of and not s.is_tracking_start]

    def first_crossings(self, as_of: datetime, levels: Iterable[int]) -> dict[int, datetime | None]:
        """For each level d, the first time after as_of that the cut moves from < d to >= d (research R3).

        A discount already running at as_of is not a new event; neither is a new row with the same cut
        (for example a regular-price change during a sale)."""
        firsts: dict[int, datetime | None] = {d: None for d in levels}
        pending = sorted(firsts)
        start = self._index_at(as_of) + 1
        for i in range(max(start, 1), len(self.states)):
            state = self.states[i]
            if state.is_tracking_start:
                continue
            previous = self.states[i - 1].cut
            if state.cut <= previous:
                continue
            still = []
            for d in pending:
                if previous < d <= state.cut:
                    firsts[d] = state.start
                else:
                    still.append(d)
            pending = still
            if not pending:
                break
        return firsts


def build_series(rows: Sequence[Observation], region: str, known_until: datetime | None) -> PriceSeries:
    """Merge ITAD sources into one series: one state per observed_at (itad-history wins a tie), rows without a
    cut dropped, steam-current snapshots ignored. The caller passes one product's rows: its default history, or an
    edition's (feature 009)."""
    ordered = sorted((o for o in rows if o.source in SERIES_SOURCES and o.cut_pct is not None),
                     key=lambda o: (o.observed_at, o.source))
    states: list[PriceState] = []
    for o in ordered:
        if states and states[-1].start == o.observed_at:
            continue
        states.append(PriceState(o.observed_at, o.cut_pct, not states, o.regular_cents))
    return PriceSeries(region, tuple(states), known_until)


@dataclass(frozen=True)
class SaleOutcome:
    """The deepest cut a product reached during one ended seasonal sale, in one region."""

    season: str
    year: int
    label: str
    region: str
    start: datetime
    end: datetime
    max_cut: int

    @property
    def sale_key(self) -> tuple[str, int]:
        return (self.season, self.year)


def sale_outcomes(series: PriceSeries, sales: Iterable[SaleEvent]) -> tuple[SaleOutcome, ...]:
    """Max cut per seasonal sale fully covered by the series: it started on or before the sale start and the
    history is known through the sale end (research R1). Uncovered sales yield nothing, never 0%."""
    if not series.states or series.known_until is None:
        return ()
    starts = [s.start for s in series.states]
    out = []
    for sale in sorted((s for s in sales if s.kind == "seasonal"), key=lambda s: s.start):
        if series.states[0].start > sale.start or sale.end > series.known_until:
            continue
        i = bisect_right(starts, sale.start) - 1
        best = series.states[i].cut
        for state in series.states[i + 1:]:
            if state.start >= sale.end:
                break
            best = max(best, state.cut)
        out.append(SaleOutcome(sale.season, sale.year, label(sale), series.region, sale.start, sale.end, best))
    return tuple(out)
