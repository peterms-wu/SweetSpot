"""How often the auxiliary region's discounts match Taiwan's (FR-007b, SC-010; data-model §8).

Feature 002 uses this to decide whether aux-region discount history may stand in for Taiwan's
(constitution IX: only after verification). Two measures over the overlap period:
- days_same_cut: days on which both regions were in the same discount state (sampled at 23:59:59 UTC).
- sales_matched: Taiwan sale starts that the aux region shows with the same discount within ±1 day.
The overlap starts at Taiwan's first real change — the tracking-start snapshot is not a change.
"""

import bisect
import sqlite3
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from sweetspot.store.query import product_clause
from sweetspot.store.writer import StoreWriter
from sweetspot.timeutil import from_db, to_db

HISTORY_SOURCES = ("itad-history", "legacy-itad")
MATCH_WINDOW = timedelta(days=1)


@dataclass(frozen=True)
class Consistency:
    scope: str
    aux_region: str
    overlap_start: datetime | None
    overlap_end: datetime | None
    days_compared: int
    days_same_cut: int
    sales_tw: int
    sales_matched: int


def _series(conn: sqlite3.Connection, app_id: int, region: str,
            key: str | None = None) -> list[tuple[datetime, int, bool]]:
    clause, params = product_clause(conn, app_id, key)
    rows = conn.execute(
        f"SELECT observed_at, MIN(cut_pct), MAX(is_tracking_start) FROM price_observations WHERE app_id = ? "
        f"AND region = ? AND anomaly IS NULL AND source IN {HISTORY_SOURCES} AND cut_pct IS NOT NULL{clause} "
        f"GROUP BY observed_at ORDER BY observed_at", (app_id, region, *params)).fetchall()
    return [(from_db(t), cut, bool(start)) for t, cut, start in rows]


def _state_at(series: list[tuple[datetime, int, bool]], times: list[datetime], moment: datetime) -> int | None:
    index = bisect.bisect_right(times, moment) - 1
    return series[index][1] if index >= 0 else None


def compute(conn: sqlite3.Connection, app_id: int, aux_region: str, *, now: datetime,
            key: str | None = None) -> Consistency | None:
    """`key` limits both regions to one ITAD product (feature 006); None reads every row, as before."""
    tw, aux = _series(conn, app_id, "TW", key), _series(conn, app_id, aux_region, key)
    changes = [row for row in tw if not row[2]]
    if not changes or not aux:
        return None
    start = max(changes[0][0], aux[0][0])
    tw_times, aux_times = [r[0] for r in tw], [r[0] for r in aux]

    compared = same = 0
    day = start.date()
    while (moment := datetime.combine(day, time(23, 59, 59), start.tzinfo)) <= now:
        compared += 1
        same += _state_at(tw, tw_times, moment) == _state_at(aux, aux_times, moment)
        day += timedelta(days=1)

    sales = matched = 0
    previous = None
    for when, cut, _ in tw:
        if cut and not previous and when >= start:
            sales += 1
            lo = bisect.bisect_left(aux_times, when - MATCH_WINDOW)
            hi = bisect.bisect_right(aux_times, when + MATCH_WINDOW)
            matched += any(aux[i][1] == cut for i in range(lo, hi))
        previous = cut
    return Consistency(str(app_id), aux_region, start, now, compared, same, sales, matched)


def refresh(writer: StoreWriter, app_ids: list[int], aux_region: str, *, now: datetime,
            keys: dict[int, str | None] | None = None) -> list[Consistency]:
    """Store per-app rows for `app_ids` and an 'ALL' row over every app that has both regions. `keys` picks the
    ITAD product per app (feature 006); apps without a key read every row."""
    both = [a for (a,) in writer.conn.execute(
        f"SELECT app_id FROM price_observations WHERE source IN {HISTORY_SOURCES} AND region IN ('TW', ?) "
        f"GROUP BY app_id HAVING COUNT(DISTINCT region) = 2", (aux_region,))]
    results = {a: compute(writer.conn, a, aux_region, now=now, key=(keys or {}).get(a))
               for a in set(both) | set(app_ids)}
    rows = [results[a] for a in app_ids if results.get(a)]
    found = [r for r in results.values() if r]
    rows.append(Consistency(
        "ALL", aux_region, min((r.overlap_start for r in found), default=None), now if found else None,
        sum(r.days_compared for r in found), sum(r.days_same_cut for r in found),
        sum(r.sales_tw for r in found), sum(r.sales_matched for r in found)))
    with writer.transaction():
        writer.conn.executemany(
            "INSERT INTO region_consistency (scope, aux_region, overlap_start, overlap_end, days_compared, "
            "days_same_cut, sales_tw, sales_matched, computed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(r.scope, r.aux_region, r.overlap_start and to_db(r.overlap_start),
              r.overlap_end and to_db(r.overlap_end), r.days_compared, r.days_same_cut, r.sales_tw,
              r.sales_matched, to_db(now)) for r in rows])
    return rows
