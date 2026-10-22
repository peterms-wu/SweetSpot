"""Steam sale calendar: load and validate the sourced file, map times to sales, estimate unannounced
seasonal sales, and flag gaps (FR-030..033; contracts/sales-calendar.md; research R9). Feature 012 adds the pure
comparison with the official seasonal sales page and the merge of adopted official sales (research R3)."""

import json
import tomllib
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sweetspot.store.writer import StoreWriter
from sweetspot.timeutil import add_months, from_db, parse_iso, to_db

SEASONS = ("spring", "summer", "autumn", "winter")
SEASON_ZH = {"spring": "春季特賣", "summer": "夏季特賣", "autumn": "秋季特賣", "winter": "冬季特賣"}
SEASON_SHORT = {"spring": "春特", "summer": "夏特", "autumn": "秋特", "winter": "冬特"}
# Typical month of each season, used only to decide which occurrence is "next" for coverage alerts.
SEASON_MONTH = {"spring": 3, "summer": 6, "autumn": 10, "winter": 12}
KINDS = ("seasonal", "themed")
CONFIDENCES = ("official", "secondary")
MAX_SEASONAL_DAYS = 30


class CalendarError(Exception):
    pass


@dataclass(frozen=True)
class SaleEvent:
    name: str
    name_zh: str
    kind: str
    season: str | None
    year: int
    start: datetime          # UTC, inclusive
    end: datetime            # UTC, exclusive: prices return to normal at `end`
    status: str              # ended | announced | estimated
    source: str              # URL, or a description of the estimate basis
    confidence: str = "official"
    basis: dict | None = field(default=None, compare=False)


def label(event: SaleEvent) -> str:
    """'2027 春特' for seasonal sales; '<year> <中文名稱>' for themed ones. Winter uses its start year."""
    if event.kind == "seasonal" and event.season:
        return f"{event.year} {SEASON_SHORT[event.season]}"
    return f"{event.year} {event.name_zh}"


# --- loading ------------------------------------------------------------------------------------

def day_to_utc(day: date, default_time: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, default_time, tz).astimezone(ZoneInfo("UTC"))


def _to_utc(value: str, default_time: time, tz: ZoneInfo) -> datetime:
    if "T" in value:
        return parse_iso(value)
    return day_to_utc(date.fromisoformat(value), default_time, tz)


def _defaults(data: dict) -> tuple[time, ZoneInfo]:
    return time.fromisoformat(data.get("default_time", "10:00")), ZoneInfo(data.get("default_tz", "America/Los_Angeles"))


def read_defaults(path: Path) -> tuple[time, ZoneInfo]:
    """The file's default time of day and time zone for date-only entries (feature 012: official dates use them too)."""
    try:
        return _defaults(tomllib.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise CalendarError(f"無法讀取行事曆 {path}：{exc}") from exc


def _validate(entry: dict, where: str, start: datetime, end: datetime, now: datetime) -> None:
    def fail(message: str) -> None:
        raise CalendarError(f"{where}：{message}")

    if entry.get("kind") not in KINDS:
        fail(f"kind 必須是 {KINDS}")
    if entry["kind"] == "seasonal" and entry.get("season") not in SEASONS:
        fail(f"季節特賣的 season 必須是 {SEASONS}")
    if entry.get("confidence", "official") not in CONFIDENCES:
        fail(f"confidence 必須是 {CONFIDENCES}")
    source = str(entry.get("source", ""))
    if "steamdb" in source.lower():
        fail("source 不可使用 steamdb（憲章 VIII）")
    if not source.startswith("https://"):
        fail("source 必須是 https 網址")
    if start >= end:
        fail("start 必須早於 end")
    if entry["kind"] == "seasonal" and not 1 <= (end - start).days <= MAX_SEASONAL_DAYS:
        fail(f"季節特賣天數必須在 1 到 {MAX_SEASONAL_DAYS} 天之間")
    if entry.get("status") not in ("ended", "announced"):
        fail("status 必須是 ended 或 announced")
    if entry["status"] == "ended" and end > now:
        fail("status 為 ended，但 end 還沒到")


def load_calendar(path: Path, *, now: datetime) -> list[SaleEvent]:
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise CalendarError(f"無法讀取行事曆 {path}：{exc}") from exc
    default_time, tz = _defaults(data)
    events, seen = [], set()
    for index, entry in enumerate(data.get("sale", []), 1):
        where = f"第 {index} 筆（{entry.get('year')} {entry.get('name')}）"
        try:
            start = _to_utc(str(entry["start"]), default_time, tz)
            end = _to_utc(str(entry["end"]), default_time, tz)
        except (KeyError, ValueError) as exc:
            raise CalendarError(f"{where}：日期格式錯誤（{exc}）") from exc
        _validate(entry, where, start, end, now)
        if entry["kind"] == "seasonal":
            key = (int(entry["year"]), entry["season"])
            if key in seen:
                raise CalendarError(f"{where}：{key[0]} 年的 {SEASON_ZH[key[1]]}重複")
            seen.add(key)
        events.append(SaleEvent(
            name=entry["name"], name_zh=entry.get("name_zh", entry["name"]), kind=entry["kind"],
            season=entry.get("season"), year=int(entry["year"]), start=start, end=end,
            status="ended" if end <= now else "announced", source=entry["source"],
            confidence=entry.get("confidence", "official"),
        ))
    return sorted(events, key=lambda e: e.start)


# --- official seasonal sales page (feature 012) ------------------------------------------------------------------

@dataclass(frozen=True)
class CalendarDiff:
    """The official page's sales against the file (research R3). `conflicts`: (file event, official event); the
    forecast keeps the file's dates. `missing`: file sales not ended, within the page's range, not listed."""
    same: list[SaleEvent]
    new: list[SaleEvent]
    conflicts: list[tuple[SaleEvent, SaleEvent]]
    missing: list[SaleEvent]


def _key(event: SaleEvent) -> tuple[int, str | None]:
    return event.year, event.season


PACIFIC = ZoneInfo("America/Los_Angeles")


def pacific_days(start: datetime, end: datetime) -> str:
    """'3/18–3/25': the Pacific start date and the day prices return, as on the official page and in the file. Used
    in every calendar text (alerts, report notices, the comparison line) so they all match the page."""
    s, e = start.astimezone(PACIFIC), end.astimezone(PACIFIC)
    return f"{s.month}/{s.day}–{e.month}/{e.day}"


def official_event(season: str, year: int, start: datetime, end: datetime, *, source: str, now: datetime,
                   file_events: list[SaleEvent]) -> SaleEvent:
    """A seasonal sale from the official page, named like the file's latest sale of the same season."""
    same_season = [e for e in file_events if e.kind == "seasonal" and e.season == season]
    ref = max(same_season, key=lambda e: e.year, default=None)
    return SaleEvent(name=ref.name if ref else f"Steam {season.title()} Sale",
                     name_zh=ref.name_zh if ref else SEASON_ZH[season], kind="seasonal", season=season, year=year,
                     start=start, end=end, status="ended" if end <= now else "announced", source=source,
                     confidence="official")


def compare_official(file_events: list[SaleEvent], official: list[SaleEvent], *, now: datetime) -> CalendarDiff:
    in_file = {_key(e): e for e in file_events if e.kind == "seasonal"}
    same, new, conflicts = [], [], []
    for o in sorted(official, key=lambda e: e.start):
        f = in_file.get(_key(o))
        if f is None:
            new.append(o)
        elif (f.start, f.end) == (o.start, o.end):
            same.append(o)
        else:
            conflicts.append((f, o))
    missing = []
    if official:
        listed = {_key(o) for o in official}
        last = max(o.start for o in official)
        missing = [f for key, f in sorted(in_file.items(), key=lambda kv: kv[1].start)
                   if key not in listed and f.end > now and f.start <= last]
    return CalendarDiff(same, new, conflicts, missing)


def effective_events(file_events: list[SaleEvent], adopted: list[SaleEvent]) -> list[SaleEvent]:
    """The file's sales plus adopted official sales for seasons and years the file does not have. The file always
    wins (clarify Q2): a conflicting official date is reported, never used."""
    in_file = {_key(e) for e in file_events if e.kind == "seasonal"}
    extra = [a for a in adopted if _key(a) not in in_file]
    return sorted(list(file_events) + extra, key=lambda e: e.start)


# --- mapping ------------------------------------------------------------------------------------

def sales_at(events: list[SaleEvent], moment: datetime) -> list[SaleEvent]:
    """Sales in effect at `moment` ([start, end)); empty means outside any known sale (FR-031)."""
    return [e for e in events if e.start <= moment < e.end]


def sales_overlapping(events: list[SaleEvent], start: datetime, end: datetime) -> list[SaleEvent]:
    return [e for e in events if e.start < end and start < e.end]


# --- estimates ----------------------------------------------------------------------------------

def estimate_sale(events: list[SaleEvent], season: str, year: int) -> SaleEvent | None:
    """Last year's same-season sale moved to `year`, aligned to the same weekday (±3 days), same length.

    Only the most recent year is used so schedule changes (autumn moved to late September in 2025) take
    effect immediately instead of being averaged away (research R9).
    """
    refs = [e for e in events if e.kind == "seasonal" and e.season == season and e.year < year
            and e.status != "estimated"]
    if not refs:
        return None
    ref = max(refs, key=lambda e: e.year)
    tz = ZoneInfo("America/Los_Angeles")
    ref_start, ref_end = ref.start.astimezone(tz), ref.end.astimezone(tz)
    day = ref_start.date()
    try:
        candidate = day.replace(year=day.year + (year - ref.year))
    except ValueError:  # 29 February
        candidate = date(day.year + (year - ref.year), 2, 28)
    delta = (ref_start.weekday() - candidate.weekday()) % 7
    candidate += timedelta(days=delta - 7 if delta > 3 else delta)
    length = (ref_end.date() - ref_start.date()).days
    start = datetime.combine(candidate, ref_start.time(), tz)
    end = datetime.combine(candidate + timedelta(days=length), ref_end.time(), tz)
    utc = ZoneInfo("UTC")
    basis = {"method": "same-season-last-year-weekday-aligned", "reference_year": ref.year,
             "reference_start": ref.start.isoformat(), "reference_end": ref.end.isoformat(),
             "reference_source": ref.source}
    return SaleEvent(name=ref.name, name_zh=ref.name_zh, kind="seasonal", season=season, year=year,
                     start=start.astimezone(utc), end=end.astimezone(utc), status="estimated",
                     source=f"預估：依 {label(ref)} 對齊星期幾", confidence="estimated", basis=basis)


def _estimate_row_to_event(row: tuple) -> SaleEvent:
    season, year, est_start, est_end, basis_json = row
    basis = json.loads(basis_json)
    return SaleEvent(name=f"Steam {season.title()} Sale", name_zh=SEASON_ZH[season], kind="seasonal",
                     season=season, year=year, start=from_db(est_start), end=from_db(est_end), status="estimated",
                     source=f"預估：依 {basis.get('reference_year')} {SEASON_SHORT[season]} 對齊星期幾",
                     confidence="estimated", basis=basis)


def current_estimates(writer_or_conn) -> list[SaleEvent]:
    conn = getattr(writer_or_conn, "conn", writer_or_conn)
    rows = conn.execute("SELECT season, year, est_start, est_end, basis_json FROM sale_estimates "
                        "WHERE superseded_at IS NULL ORDER BY est_start")
    return [_estimate_row_to_event(r) for r in rows]


def refresh_estimates(writer: StoreWriter, events: list[SaleEvent], *, now: datetime,
                      horizon_months: int = 24) -> list[SaleEvent]:
    """Store estimates for unannounced seasonal sales within the horizon; supersede estimates that
    are now announced (the old rows are kept for later accuracy checks). Returns new estimates."""
    known = {(e.year, e.season) for e in events if e.kind == "seasonal"}
    stamp = to_db(now)
    created = []
    with writer.transaction():
        for estimate_id, season, year in writer.conn.execute(
                "SELECT estimate_id, season, year FROM sale_estimates WHERE superseded_at IS NULL").fetchall():
            if (year, season) in known:
                writer.conn.execute("UPDATE sale_estimates SET superseded_at = ? WHERE estimate_id = ?",
                                    (stamp, estimate_id))
        open_estimates = {(s, y) for _, s, y in writer.conn.execute(
            "SELECT estimate_id, season, year FROM sale_estimates WHERE superseded_at IS NULL")}
        horizon = add_months(now, horizon_months)
        for year in range(now.year, horizon.year + 1):
            for season in SEASONS:
                if (year, season) in known or (season, year) in open_estimates:
                    continue
                estimate = estimate_sale(events, season, year)
                if estimate is None or estimate.end <= now or estimate.start > horizon:
                    continue
                writer.conn.execute(
                    "INSERT INTO sale_estimates (season, year, est_start, est_end, basis_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (season, year, to_db(estimate.start), to_db(estimate.end),
                     json.dumps(estimate.basis, ensure_ascii=False), stamp),
                )
                created.append(estimate)
    return created


# --- alerts -------------------------------------------------------------------------------------

def coverage_alerts(events: list[SaleEvent], estimates: list[SaleEvent], *, now: datetime) -> list[str]:
    """FR-033(a): a seasonal sale expected within 12 months with neither an announcement nor an estimate."""
    covered = {(e.year, e.season) for e in events + estimates if e.kind == "seasonal"}
    alerts = []
    for season in SEASONS:
        year = now.year if date(now.year, SEASON_MONTH[season], 15) > now.date() else now.year + 1
        if (year, season) not in covered:
            alerts.append(f"{year} {SEASON_ZH[season]}尚無官方公告，也無法預估；請更新 data/steam_sales.toml")
    return alerts


@dataclass(frozen=True)
class MissedSale:
    day: date                # Pacific date on which many games started a discount
    publishers: int          # distinct publishers starting a discount that day
    apps: int


def _publisher_groups(conn) -> dict[int, str]:
    """Latest known first publisher per app; apps without one count as their own group."""
    groups: dict[int, str] = {}
    for app_id, value in conn.execute(
            "SELECT app_id, value_json FROM product_facts WHERE field = 'publishers' ORDER BY retrieved_at"):
        names = json.loads(value) if value else None
        if names:
            groups[app_id] = str(names[0]).casefold()
    return groups


def detect_missed_sales(writer_or_conn, events: list[SaleEvent], *, since: datetime, now: datetime,
                        min_publishers: int = 20, ratio: float = 0.3) -> list[MissedSale]:
    """FR-033(b): days on which many *publishers* start discounting outside every known sale (±1 day).

    Counting publishers rather than games keeps one publisher's own sale (often 100+ games) from looking
    like a store-wide event. Threshold: `ratio` of the typical publisher count on known seasonal-sale start
    days in the data, but never below `min_publishers` (observed 2025-26: 80-104 on real sale starts,
    at most 16 on other days).
    """
    conn = getattr(writer_or_conn, "conn", writer_or_conn)
    tz = ZoneInfo("America/Los_Angeles")
    groups = _publisher_groups(conn)
    publishers: dict[date, set[str]] = {}
    apps: Counter = Counter()
    previous: dict[tuple[int, str], int | None] = {}
    seen: set[tuple[date, int]] = set()
    for app_id, source, observed_at, cut in conn.execute(
            "SELECT app_id, source, observed_at, cut_pct FROM price_observations WHERE region = 'TW' "
            "AND source IN ('itad-history', 'legacy-itad') AND anomaly IS NULL AND observed_at >= ? "
            "AND observed_at <= ? ORDER BY app_id, source, observed_at", (to_db(since), to_db(now))):
        key = (app_id, source)
        if cut and previous.get(key) == 0:
            day = from_db(observed_at).astimezone(tz).date()
            if (day, app_id) not in seen:
                seen.add((day, app_id))
                publishers.setdefault(day, set()).add(groups.get(app_id, f"app:{app_id}"))
                apps[day] += 1
        previous[key] = cut

    # Only sales inside the data's coverage count: earlier sales have no observations (0 publishers) and
    # would drag the typical size, and with it the threshold, down to the floor.
    data_start = min(publishers, default=None)
    seasonal_starts = [len(publishers.get(e.start.astimezone(tz).date(), ())) for e in events
                       if e.kind == "seasonal" and since <= e.start <= now and data_start is not None
                       and e.start.astimezone(tz).date() >= data_start]
    typical = sorted(seasonal_starts)[len(seasonal_starts) // 2] if seasonal_starts else 0
    threshold = max(min_publishers, ratio * typical)
    covered_days: set[date] = set()
    for e in events:
        day = e.start.astimezone(tz).date() - timedelta(days=1)
        while day <= e.end.astimezone(tz).date() + timedelta(days=1):
            covered_days.add(day)
            day += timedelta(days=1)
    return [MissedSale(day, len(pubs), apps[day]) for day, pubs in sorted(publishers.items())
            if len(pubs) >= threshold and day not in covered_days]

