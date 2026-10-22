"""Which sale and which official record a comparison looks at (feature 013 research R3, FR-001–FR-003)."""

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sweetspot.calendar import SEASONS, SaleEvent
from sweetspot.decision import records
from sweetspot.timeutil import parse_iso

SETTLE = timedelta(days=3)          # price histories fill in within days after a sale ends (HANDOFF, FR-002)
DAY_SHARE = timedelta(hours=12)     # a Taipei day counts as a sale day when the sale covers at least half of it


class TargetError(ValueError):
    """The comparison cannot run; nothing is written."""


@dataclass(frozen=True)
class ReviewTarget:
    sale: SaleEvent
    record_path: Path
    record: dict[str, Any]
    as_of: datetime
    during: tuple[tuple[Path, dict[str, Any]], ...]   # official records made during the sale, by as_of (FR-010a)
    missing_days: tuple[str, ...]                     # Taipei sale days without any official record
    today: datetime
    forced: bool
    skipped_records: tuple[str, ...]
    hours_before_start: float


def parse_sale(text: str) -> tuple[str, int]:
    m = re.fullmatch(r"([a-z]+)-(\d{4})", text or "")
    if not m or m.group(1) not in SEASONS:
        raise TargetError(f"特賣的寫法是 <季節>-<年份>，例如 autumn-2026（季節：{'、'.join(SEASONS)}）：{text!r}")
    return m.group(1), int(m.group(2))


def _pick_sale(events: list[SaleEvent], sale: str | None, today: datetime) -> SaleEvent:
    seasonal = [e for e in events if e.kind == "seasonal"]
    if sale is None:
        ended = [e for e in seasonal if e.end <= today]
        if not ended:
            raise TargetError("行事曆中沒有已結束的季節特賣")
        return max(ended, key=lambda e: e.end)
    season, year = parse_sale(sale)
    for e in seasonal:
        if (e.season, e.year) == (season, year):
            return e
    raise TargetError(f"行事曆中找不到季節特賣 {sale}")


def _taipei_day(moment: datetime) -> date:
    return (moment + records.TAIPEI).date()


def sale_days(sale: SaleEvent) -> list[date]:
    """Taipei days the sale covers for at least half the day: the days a daily record should exist."""
    out = []
    day = _taipei_day(sale.start)
    while True:
        lo = datetime.combine(day, datetime.min.time(), sale.start.tzinfo) - records.TAIPEI
        hi = lo + timedelta(days=1)
        if lo >= sale.end:
            return out
        if min(hi, sale.end) - max(lo, sale.start) >= DAY_SHARE:
            out.append(day)
        day += timedelta(days=1)


def _load_all(directory: Path) -> tuple[list[tuple[Path, dict]], list[str]]:
    loaded, skipped = [], []
    for path in records.list_records(directory):
        try:
            loaded.append((path, records.load_record(path)))
        except records.RecordError:
            skipped.append(path.name)
    return loaded, skipped


def _as_of(data: dict) -> datetime | None:
    try:
        return parse_iso(data["as_of"])
    except (KeyError, TypeError, ValueError):
        return None


def select_target(events: list[SaleEvent], forecasts_dir: Path, *, sale: str | None = None, record: str | None = None,
                  today: datetime, force: bool = False) -> ReviewTarget:
    event = _pick_sale(events, sale, today)
    if event.end > today:
        raise TargetError(f"{event.name_zh} {event.year} 還沒結束（結束於 {event.end:%Y-%m-%d %H:%M} UTC）")
    forced = False
    if today < event.end + SETTLE:
        if not force:
            raise TargetError(f"特賣結束不到 3 天（{event.end:%Y-%m-%d}），價格歷史可能還沒補齊；確定要執行請加 --force")
        forced = True

    loaded, skipped = _load_all(Path(forecasts_dir))
    if record is not None:
        name = Path(record).name
        chosen = next(((p, d) for p, d in loaded if p.name == name), None)
        if chosen is None:
            raise TargetError(f"找不到可讀的紀錄 {record}")
        as_of = _as_of(chosen[1])
        if as_of is None or as_of >= event.end:
            raise TargetError(f"紀錄 {name} 的分析時點不在特賣結束以前，無法當作預測")
    else:
        before = [(a, p, d) for p, d in loaded if d.get("official") and (a := _as_of(d)) and a < event.start]
        if not before:
            raise TargetError(f"找不到 {event.name_zh} {event.year} 開賣前的正式紀錄")
        as_of, path, data = max(before, key=lambda x: x[0])
        chosen = (path, data)

    during = sorted(((a, p, d) for p, d in loaded
                     if d.get("official") and (a := _as_of(d)) and event.start <= a < event.end), key=lambda x: x[0])
    seen = {_taipei_day(a) for a, _, _ in during}
    missing = tuple(day.isoformat() for day in sale_days(event) if day not in seen)
    hours = round((event.start - as_of).total_seconds() / 3600, 1)
    return ReviewTarget(sale=event, record_path=chosen[0], record=chosen[1], as_of=as_of,
                        during=tuple((p, d) for _, p, d in during), missing_days=missing, today=today, forced=forced,
                        skipped_records=tuple(skipped), hours_before_start=hours)
