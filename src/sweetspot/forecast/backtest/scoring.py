"""Scoring units and outcomes (research R3; data-model ScoringUnit).

A unit is game × as_of × level × sale point. Points are matched to the real sale by (season, year) and judged
at the *actual* end; windows and horizon groups use the *estimated* end known at as_of.
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime

from sweetspot.calendar import SaleEvent
from sweetspot.forecast.salepoints import SalePoint
from sweetspot.forecast.series import PriceSeries
from sweetspot.timeutil import add_months

# framework settings (docs/model/model-definition.md): evaluated window per region, in months after as_of
WINDOWS = {"TW": (0, 12), "US": (12, 60)}
HORIZON_GROUPS = {"TW": ((3, "0-3m"), (6, "3-6m"), (12, "6-12m")),
                  "US": ((24, "12-24m"), (36, "24-36m"), (60, "36-60m"))}
OUTCOMES = ("occurred", "not-occurred", "censored", "not-held")


def window_points(points: Sequence[SalePoint], as_of: datetime, region: str) -> tuple[SalePoint, ...]:
    lo, hi = WINDOWS[region]
    after, until = add_months(as_of, lo), add_months(as_of, hi)
    return tuple(p for p in points if after < p.end <= until)


def horizon_group(region: str, as_of: datetime, end: datetime) -> str:
    groups = HORIZON_GROUPS[region]
    for months, name in groups:
        if end <= add_months(as_of, months):
            return name
    return groups[-1][1]


def actual_sales(events: Iterable[SaleEvent]) -> dict[tuple[str, int], SaleEvent]:
    return {(e.season, e.year): e for e in events if e.kind == "seasonal" and e.season}


def unit_outcome(first: datetime | None, actual: SaleEvent | None, known_until: datetime | None,
                 estimated_end: datetime) -> str:
    if actual is None:
        # Not in the calendar. Before the data ends that means it was not held; after, it is still unknown.
        if known_until is not None and estimated_end <= known_until:
            return "not-held"
        if first is not None and known_until is not None and first <= known_until:
            return "occurred"            # the sale, if held, is still ahead of the event
        return "censored"
    if first is not None and first < actual.end:
        return "occurred"
    if known_until is None or actual.end > known_until:
        return "censored"
    return "not-occurred"


def score_case(series: PriceSeries, as_of: datetime, points: Sequence[SalePoint], levels: Sequence[int],
               actual: Mapping[tuple[str, int], SaleEvent], firsts: Mapping[int, datetime | None] | None = None
               ) -> list[list[str]]:
    """Outcomes [point][level] for one game at one as_of. `series` is the full series up to the data cutoff."""
    firsts = firsts if firsts is not None else series.first_crossings(as_of, levels)
    return [[unit_outcome(firsts[d], actual.get(p.sale_key), series.known_until, p.end) for d in levels]
            for p in points]


def finished_outcomes(series: PriceSeries, points: Sequence[SalePoint], levels: Sequence[int],
                      actual: Mapping[tuple[str, int], SaleEvent], firsts: Mapping[int, datetime | None]
                      ) -> list[list[int] | None]:
    """Feature 008 FR-011: per point, None unless its actual sale ended inside the known history; then 1 when the
    level was first reached before the actual end, else 0 (both outcomes judged the same way)."""
    out = []
    for p in points:
        event = actual.get(p.sale_key)
        if event is None or series.known_until is None or series.known_until < event.end:
            out.append(None)
            continue
        out.append([int(firsts[d] is not None and firsts[d] < event.end) for d in levels])
    return out
