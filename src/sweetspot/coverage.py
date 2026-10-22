"""Per-game data coverage (FR-021, FR-022; data-model §9). Read-only; computed on demand."""

import csv
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from sweetspot.store.query import product_clause
from sweetspot.timeutil import from_db

GAP = timedelta(days=90)
HISTORY_SOURCES = ("itad-history", "legacy-itad")
NOTE = ("long_unchanged 只是提示：ITAD 只在價格變動時記錄，長期沒有紀錄通常代表價格沒變；"
        "data_gaps 才是本工具自行記錄的現價中斷。")


@dataclass(frozen=True)
class Span:
    start: datetime
    end: datetime


@dataclass
class Coverage:
    app_id: int
    history_state: str                        # available | none | not-fetched
    tw_earliest: datetime | None = None
    tw_latest: datetime | None = None
    aux_available: bool = False
    aux_earliest: datetime | None = None
    aux_latest: datetime | None = None
    current_price_latest: datetime | None = None
    paid_sale_count: int | None = None        # None = unknown (no history), not zero
    free_promo_count: int | None = None
    data_gaps: list[Span] = field(default_factory=list)
    long_unchanged: list[Span] = field(default_factory=list)
    mapping_state: str | None = None
    mapping_reason: str | None = None
    note: str = NOTE


def _gaps(times: list[datetime], until: datetime | None) -> list[Span]:
    points = sorted(times) + ([until] if until is not None and times else [])
    return [Span(a, b) for a, b in zip(points, points[1:]) if b - a > GAP]


def _history_rows(conn: sqlite3.Connection, app_id: int, region: str, key: str | None = None) -> list[tuple]:
    """One row per observed time (the same change may come from ITAD and the legacy import); `key` limits the rows
    to one ITAD product (feature 006)."""
    clause, params = product_clause(conn, app_id, key)
    rows = conn.execute(
        f"SELECT observed_at, MIN(cut_pct), MIN(price_cents), MIN(regular_cents) FROM price_observations "
        f"WHERE app_id = ? AND region = ? AND anomaly IS NULL AND source IN {HISTORY_SOURCES}{clause} "
        f"GROUP BY observed_at ORDER BY observed_at", (app_id, region, *params)).fetchall()
    return [(from_db(t), cut, price, regular) for t, cut, price, regular in rows]


def _count_events(rows: list[tuple]) -> tuple[int, int]:
    """(paid sales, free giveaways): count each period once, when it starts."""
    paid = free = 0
    previous = "full"
    for _, cut, price, regular in rows:
        state = "free" if price == 0 and regular else ("paid-sale" if cut and price else "full")
        if state != previous:
            paid += state == "paid-sale"
            free += state == "free"
        previous = state
    return paid, free


def coverage(conn: sqlite3.Connection, app_id: int, now: datetime, aux_region: str = "US",
             key: str | None = None) -> Coverage:
    tw = _history_rows(conn, app_id, "TW", key)
    aux = _history_rows(conn, app_id, aux_region, key)
    fetched = conn.execute("SELECT COUNT(*) FROM history_fetches WHERE app_id = ? AND region = 'TW' "
                           "AND source = 'itad'", (app_id,)).fetchone()[0]     # an edition's fetch is not the app's
    state = "available" if tw else ("none" if fetched else "not-fetched")
    current = [from_db(t) for (t,) in conn.execute(
        "SELECT observed_at FROM price_observations WHERE app_id = ? AND source = 'steam-current' "
        "AND anomaly IS NULL ORDER BY observed_at", (app_id,))]
    mapping = conn.execute(
        "SELECT verification, reason_code FROM source_mappings WHERE app_id = ? AND source = 'itad' "
        "ORDER BY checked_at DESC, mapping_id DESC LIMIT 1", (app_id,)).fetchone()
    result = Coverage(app_id=app_id, history_state=state, mapping_state=mapping[0] if mapping else None,
                      mapping_reason=mapping[1] if mapping else None)
    if tw:
        result.tw_earliest, result.tw_latest = tw[0][0], tw[-1][0]
        result.paid_sale_count, result.free_promo_count = _count_events(tw)
        result.long_unchanged = _gaps([t for t, *_ in tw], now)
    if aux:
        result.aux_available, result.aux_earliest, result.aux_latest = True, aux[0][0], aux[-1][0]
    if current:
        result.current_price_latest = current[-1]
        result.data_gaps = _gaps(current, now)
    return result


# --- CSV ----------------------------------------------------------------------------------------

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
CSV_FIELDS = ["app_id", "name", "history_state", "tw_earliest", "tw_latest", "aux_available", "aux_earliest",
              "current_price_latest", "paid_sale_count", "free_promo_count", "data_gaps", "long_unchanged",
              "mapping_state", "mapping_reason"]


def csv_cell(value) -> str:
    """Spreadsheet-safe cell: text that a spreadsheet would treat as a formula is prefixed with ' (constitution IX)."""
    if value is None:
        return ""
    text = str(value)
    return "'" + text if text.startswith(_FORMULA_START) else text


def _spans(spans: list[Span]) -> str:
    return "; ".join(f"{s.start.date()}~{s.end.date()}" for s in spans)


def write_csv(path: Path, rows: list[Coverage], names: dict[int, str]) -> None:
    with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for c in rows:
            values = {
                "app_id": c.app_id, "name": names.get(c.app_id), "history_state": c.history_state,
                "tw_earliest": c.tw_earliest and c.tw_earliest.date(), "tw_latest": c.tw_latest and c.tw_latest.date(),
                "aux_available": c.aux_available, "aux_earliest": c.aux_earliest and c.aux_earliest.date(),
                "current_price_latest": c.current_price_latest and c.current_price_latest.date(),
                "paid_sale_count": c.paid_sale_count, "free_promo_count": c.free_promo_count,
                "data_gaps": _spans(c.data_gaps), "long_unchanged": _spans(c.long_unchanged),
                "mapping_state": c.mapping_state, "mapping_reason": c.mapping_reason,
            }
            writer.writerow({k: csv_cell(v) for k, v in values.items()})
