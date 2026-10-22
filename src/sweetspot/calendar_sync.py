"""Official seasonal sales: fetch records, adopted sales, alerts and write-back to the calendar file (feature 012;
research R2-R5; contracts/calendar-sync.md). The pure comparison and merge live in calendar.py."""

import json
import os
import re
import time as time_module
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sweetspot import calendar
from sweetspot.calendar import SaleEvent
from sweetspot.sources import SeasonalSalesPage, SeasonalSalesSource
from sweetspot.sources.errors import RateLimited, SourceDisabled, SourceError
from sweetspot.store.writer import StoreWriter
from sweetspot.timeutil import from_db, to_db

MAX_REJECTED = 20
MAX_LINE = 200


# --- fetch records ----------------------------------------------------------------------------------------------------

def _status(result: SeasonalSalesPage | SourceError) -> str:
    if isinstance(result, SourceDisabled):
        return "denied"
    if isinstance(result, RateLimited):
        return "rate_limited"
    if isinstance(result, SourceError):
        return "failed"
    return "ok" if result.found_dates_section and (result.sales or result.pending) else "no_dates"


def record_fetch(writer: StoreWriter, result: SeasonalSalesPage | SourceError, *, now: datetime, default_time: time,
                 tz: ZoneInfo, url: str | None = None, run_id: str | None = None) -> int:
    """One calendar_fetches row, plus one sale_sightings row per listed sale of a successful read (one transaction).
    Dates become UTC with the calendar file's default time of day, like the file's own date-only entries."""
    status = _status(result)
    page = result if isinstance(result, SeasonalSalesPage) else None
    rejected = [{"line": r.line[:MAX_LINE], "reason": r.reason[:MAX_LINE]} for r in (page.rejected if page else [])]
    with writer.transaction():
        cur = writer.conn.execute(
            "INSERT INTO calendar_fetches (fetched_at, url, status, reason, http_status, bytes, page_sha256, accepted, "
            "pending, rejected_json, run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (to_db(now), page.url if page else (url or ""), status, None if page else str(result)[:500],
             page.http_status if page else None, page.bytes if page else None, page.sha256 if page else None,
             len(page.sales) if page else 0, len(page.pending) if page else 0,
             json.dumps(rejected[:MAX_REJECTED], ensure_ascii=False), run_id))
        fetch_id = cur.lastrowid
        if status == "ok":
            writer.conn.executemany(
                "INSERT INTO sale_sightings (fetch_id, season, year, starts_at, ends_at) VALUES (?, ?, ?, ?, ?)",
                [(fetch_id, s.season, s.year, to_db(calendar.day_to_utc(s.start_date, default_time, tz)),
                  to_db(calendar.day_to_utc(s.end_date, default_time, tz))) for s in page.sales])
    return fetch_id


def _conn(writer_or_conn):
    return getattr(writer_or_conn, "conn", writer_or_conn)


def latest_fetch(conn) -> dict | None:
    row = _conn(conn).execute(
        "SELECT fetch_id, fetched_at, url, status, reason, http_status, accepted, pending, rejected_json "
        "FROM calendar_fetches ORDER BY fetched_at DESC, fetch_id DESC LIMIT 1").fetchone()
    if row is None:
        return None
    keys = ("fetch_id", "fetched_at", "url", "status", "reason", "http_status", "accepted", "pending", "rejected")
    out = dict(zip(keys, row))
    out["fetched_at"] = from_db(out["fetched_at"])
    out["rejected"] = json.loads(out["rejected"])
    return out


def last_success(conn) -> datetime | None:
    row = _conn(conn).execute("SELECT MAX(fetched_at) FROM calendar_fetches WHERE status = 'ok'").fetchone()
    return from_db(row[0]) if row and row[0] else None


def _sightings(conn, where: str = "", params: tuple = ()) -> list[tuple]:
    return _conn(conn).execute(
        "SELECT s.season, s.year, s.starts_at, s.ends_at, f.url, f.fetched_at, f.fetch_id FROM sale_sightings s "
        f"JOIN calendar_fetches f USING (fetch_id) WHERE f.status = 'ok' {where} "
        "ORDER BY f.fetched_at, f.fetch_id", params).fetchall()


def _event(row: tuple, *, file_events: list[SaleEvent], now: datetime) -> SaleEvent:
    season, year, starts_at, ends_at, url = row[:5]
    return calendar.official_event(season, year, from_db(starts_at), from_db(ends_at), source=url, now=now,
                                   file_events=file_events)


def adopted_sales(conn, *, file_events: list[SaleEvent], now: datetime) -> list[SaleEvent]:
    """Every seasonal sale ever listed, with the dates of its most recent sighting (research R3): a sale that left
    the page (ended, or removed early) is kept."""
    latest: dict[tuple[int, str], tuple] = {}
    for row in _sightings(conn):
        latest[(row[1], row[0])] = row
    return sorted((_event(r, file_events=file_events, now=now) for r in latest.values()), key=lambda e: e.start)


def listed_now(conn, *, file_events: list[SaleEvent], now: datetime) -> list[SaleEvent]:
    """The sales listed by the most recent successful read."""
    row = _conn(conn).execute("SELECT fetch_id FROM calendar_fetches WHERE status = 'ok' "
                              "ORDER BY fetched_at DESC, fetch_id DESC LIMIT 1").fetchone()
    if row is None:
        return []
    rows = _sightings(conn, "AND f.fetch_id = ?", (row[0],))
    return sorted((_event(r, file_events=file_events, now=now) for r in rows), key=lambda e: e.start)


def sighting_times(conn, season: str, year: int) -> list[tuple[datetime, datetime, datetime, datetime]]:
    """(start, end, first seen, last seen) for each distinct pair of dates, oldest first."""
    rows = _conn(conn).execute(
        "SELECT s.starts_at, s.ends_at, MIN(f.fetched_at), MAX(f.fetched_at) FROM sale_sightings s "
        "JOIN calendar_fetches f USING (fetch_id) WHERE f.status = 'ok' AND s.season = ? AND s.year = ? "
        "GROUP BY s.starts_at, s.ends_at ORDER BY MIN(f.fetched_at)", (season, year)).fetchall()
    return [tuple(from_db(v) for v in r) for r in rows]


def fetch(writer: StoreWriter, source: SeasonalSalesSource, *, now: datetime, default_time: time, tz: ZoneInfo,
          run_id: str | None = None) -> dict:
    """Read the official page once and record the result. Never raises for a source failure (constitution III)."""
    started = time_module.monotonic()
    try:
        result: SeasonalSalesPage | SourceError = source.seasonal_sales_page()
    except SourceError as exc:
        result = exc
    fetch_id = record_fetch(writer, result, now=now, default_time=default_time, tz=tz,
                            url=getattr(source, "url", None), run_id=run_id)
    return {"fetch_id": fetch_id, "status": _status(result), "seconds": round(time_module.monotonic() - started, 2)}


# --- alerts and summary (contracts/calendar-sync.md §2-§3) -------------------------------------------------------

STALE_DAYS = 7
TAIPEI_OFFSET = timedelta(hours=8)
SYNC_HINT = "執行 sweetspot calendar --sync --write 寫入 data/steam_sales.toml"


def pacific_days(event: SaleEvent) -> str:
    return calendar.pacific_days(event.start, event.end)


@dataclass
class OfficialState:
    summary: dict
    alerts: list[str] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)       # the alerts the user must act on (plan D1)


def official_state(conn, file_events: list[SaleEvent], *, now: datetime, fetched: dict | None = None) -> OfficialState:
    """Compare the latest successful read with the file; alerts for this run's fetch result and the calendar state."""
    listed = listed_now(conn, file_events=file_events, now=now)
    adopted = adopted_sales(conn, file_events=file_events, now=now)
    diff = calendar.compare_official(file_events, listed, now=now)
    in_file = {(e.year, e.season) for e in file_events if e.kind == "seasonal"}
    not_in_file = [a for a in adopted if (a.year, a.season) not in in_file]
    latest = latest_fetch(conn)
    success = last_success(conn)
    alerts: list[str] = []
    notices: list[str] = []
    if fetched is not None and latest is not None:
        alerts += _fetch_alerts(latest)
        if latest["status"] == "no_dates":
            notices += alerts[-1:]
        if latest["rejected"]:
            lines = "；".join(f"{r['line']}（{_reason_zh(r['reason'])}）" for r in latest["rejected"])
            alerts.append(f"官方特賣頁面有 {len(latest['rejected'])} 行無法解析，已略過：{lines}")
            notices.append(alerts[-1])
    if diff.conflicts:
        items = "；".join(f"{calendar.label(f)}是 {pacific_days(o)}，data/steam_sales.toml 是 {pacific_days(f)}"
                         for f, o in diff.conflicts)
        alerts.append(f"官方特賣頁面的 {items}；預測沿用檔案的日期。確認後執行 sweetspot calendar --sync --write")
        notices.append(alerts[-1])
    if fetched is not None and latest is not None and latest["status"] == "ok":
        alerts += _moved_alerts(conn, not_in_file, seen_at=latest["fetched_at"])
    if not_in_file:
        items = "、".join(f"{calendar.label(e)}（太平洋時間 {pacific_days(e)}）" for e in not_in_file)
        alerts.append(f"官方特賣頁面公告了 {items}，已用於預測；{SYNC_HINT}")
    if diff.missing:
        items = "、".join(calendar.label(e) for e in diff.missing)
        alerts.append(f"官方特賣頁面不再列出 {items}（可能取消或改名）；行事曆保留原本的日期")
    stale = _stale_alert(conn, success, now=now)
    if stale:
        alerts.append(stale)
        notices.append(stale)
    summary = {
        "status": fetched["status"] if fetched else "not_fetched",
        "listed": len(listed), "pending": latest["pending"] if latest and latest["status"] == "ok" else 0,
        "rejected": len(latest["rejected"]) if latest else 0,
        "same": len(diff.same), "new": len(diff.new), "conflict": len(diff.conflicts), "missing": len(diff.missing),
        "not_in_file": len(not_in_file), "last_success": success.isoformat() if success else None,
        "seconds": fetched["seconds"] if fetched else 0.0,
    }
    return OfficialState(summary, alerts, notices)


def calendar_notices(conn, file_events: list[SaleEvent], *, now: datetime) -> list[str]:
    """Plan D1 (FR-021): the alerts the user must act on, for the report banner and the extension popup: a date
    that differs from the file, a page format change, and no successful read for STALE_DAYS or more."""
    latest = latest_fetch(conn)
    fetched = {"status": latest["status"], "seconds": 0.0} if latest else None
    return official_state(conn, file_events, now=now, fetched=fetched).notices


def _moved_alerts(conn, not_in_file: list[SaleEvent], *, seen_at: datetime) -> list[str]:
    """A sale not yet in the file whose official dates changed in this read (reported once, when first seen)."""
    out = []
    for sale in not_in_file:
        times = sighting_times(conn, sale.season, sale.year)
        if len(times) >= 2 and times[-1][2] == seen_at:
            (old_start, old_end, _, _), (new_start, new_end, _, _) = times[-2], times[-1]
            out.append(f"官方特賣頁面把 {calendar.label(sale)}從 {calendar.pacific_days(old_start, old_end)} 改成 "
                       f"{calendar.pacific_days(new_start, new_end)}（尚未寫入檔案，已改用新日期）")
    return out


REASONS_ZH = (("unknown season", "未知的季節"), ("date format", "日期格式無法辨識"), ("length", "天數不合理"),
              ("title year", "標題年份和開始日期不符"), ("different dates", "同一場列出不同的日期"), ("format", "格式無法辨識"))


def _reason_zh(reason: str) -> str:
    return next((zh for key, zh in REASONS_ZH if key in reason), reason)


def _taipei(moment: datetime) -> str:
    return (moment + TAIPEI_OFFSET).strftime("%Y-%m-%d %H:%M")


def _stale_alert(conn, success: datetime | None, *, now: datetime) -> str | None:
    """FR-014: no successful read for STALE_DAYS or more (counted from the first attempt when none ever succeeded)."""
    if success is not None:
        days = (now - success).days
        return (f"官方特賣頁面已 {days} 天沒有成功讀取（最後一次 {_taipei(success)} 台北）"
                if days >= STALE_DAYS else None)
    row = _conn(conn).execute("SELECT MIN(fetched_at) FROM calendar_fetches").fetchone()
    if not row or not row[0]:
        return None
    days = (now - from_db(row[0])).days
    return f"官方特賣頁面已 {days} 天沒有成功讀取（從未成功）" if days >= STALE_DAYS else None


def _fetch_alerts(latest: dict) -> list[str]:
    status, reason = latest["status"], latest["reason"]
    keep = "特賣日期沿用既有紀錄"
    if status == "denied":
        code = re.search(r"HTTP (\d{3})", reason or "")
        return [f"官方特賣頁面拒絕存取（HTTP {code.group(1) if code else '401/403'}），本次停止，不重試；{keep}"]
    if status == "rate_limited":
        wait = re.search(r"(\d+)s", reason or "")
        return [f"官方特賣頁面要求等待 {wait.group(1) if wait else '?'} 秒（HTTP 429），本次略過；{keep}"]
    if status == "failed":
        return [f"官方特賣頁面抓取失敗（{reason}），{keep}"]
    if status == "no_dates":
        return [f"官方特賣頁面格式改變，找不到任何季節特賣日期；{keep}"]
    return []


# --- write-back to the calendar file (research R5; contracts/calendar-sync.md §4-§5) -----------------------------

@dataclass(frozen=True)
class SyncAdd:
    event: SaleEvent
    first_seen: datetime | None


@dataclass(frozen=True)
class SyncReschedule:
    file_event: SaleEvent
    official: SaleEvent
    seen: datetime | None


@dataclass(frozen=True)
class SyncPlan:
    add: list[SyncAdd]
    reschedule: list[SyncReschedule]
    based_on_fetch: datetime | None


def _first_seen(conn, event: SaleEvent) -> datetime | None:
    return next((first for start, end, first, _ in sighting_times(conn, event.season, event.year)
                 if (start, end) == (event.start, event.end)), None)


def sync_plan(conn, path: Path, *, now: datetime) -> SyncPlan:
    """What `calendar --sync` would write: adopted sales the file lacks, and the file's sales whose dates differ from
    the latest successful read. Based on the database only (no network)."""
    file_events = calendar.load_calendar(path, now=now)
    in_file = {(e.year, e.season) for e in file_events if e.kind == "seasonal"}
    adds = [SyncAdd(a, _first_seen(conn, a)) for a in adopted_sales(conn, file_events=file_events, now=now)
            if (a.year, a.season) not in in_file]
    diff = calendar.compare_official(file_events, listed_now(conn, file_events=file_events, now=now), now=now)
    moves = [SyncReschedule(f, o, _first_seen(conn, o)) for f, o in diff.conflicts]
    return SyncPlan(adds, moves, last_success(conn))


def _pacific_date(moment: datetime, tz: ZoneInfo) -> str:
    return moment.astimezone(tz).date().isoformat()


def sync_summary(plan: SyncPlan, *, written: bool, error: str | None = None) -> dict:
    tz = calendar.PACIFIC
    out = {
        "written": written, "based_on_fetch": plan.based_on_fetch.isoformat() if plan.based_on_fetch else None,
        "add": [{"label": calendar.label(a.event), "start": _pacific_date(a.event.start, tz),
                 "end": _pacific_date(a.event.end, tz),
                 "first_seen": a.first_seen.date().isoformat() if a.first_seen else None} for a in plan.add],
        "reschedule": [{"label": calendar.label(r.file_event),
                        "file": [_pacific_date(r.file_event.start, tz), _pacific_date(r.file_event.end, tz)],
                        "official": [_pacific_date(r.official.start, tz), _pacific_date(r.official.end, tz)]}
                       for r in plan.reschedule],
    }
    if error:
        out["error"] = error
    return out


def _toml_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


_BLOCK = re.compile(r"(?m)^\[\[sale\]\][ \t]*\r?$")
_NOTE = re.compile(r'(?m)^note[ \t]*=[ \t]*"((?:[^"\\\r\n]|\\.)*)"[ \t]*(\r?)$')


def _blocks(text: str) -> list[tuple[int, int]]:
    starts = [m.start() for m in _BLOCK.finditer(text)]
    return list(zip(starts, starts[1:] + [len(text)]))


def _block_key(block: str) -> tuple[int, str | None, str]:
    entry = tomllib.loads(block.replace("\r\n", "\n"))["sale"][0]
    return int(entry["year"]), entry.get("season"), str(entry["start"])


def _set_value(block: str, key: str, value: str) -> str:
    pattern = re.compile(rf'(?m)^{key}[ \t]*=[ \t]*"[^"\r\n]*"')
    assert pattern.search(block), key
    return pattern.sub(lambda m: f"{key} = {_toml_string(value)}", block, count=1)


def _add_note(block: str, sentence: str, nl: str) -> str:
    """Append the sentence to the block's one-line note, or add a note line at the end of the block."""
    m = _NOTE.search(block)
    if m:
        return block[:m.start(1)] + m.group(1) + " " + _toml_string(sentence)[1:-1] + block[m.end(1):]
    body = block.rstrip("\r\n")
    return body + nl + f"note = {_toml_string(sentence)}" + block[len(body):]


def _new_block(add: SyncAdd, *, tz: ZoneInfo, now: datetime, nl: str) -> str:
    e = add.event
    first = f"first seen {add.first_seen.date().isoformat()}" if add.first_seen else "first seen date unknown"
    fields = [("name", e.name), ("name_zh", e.name_zh), ("kind", "seasonal"), ("season", e.season), ("year", e.year),
              ("start", _pacific_date(e.start, tz)), ("end", _pacific_date(e.end, tz)),
              ("status", "ended" if e.end <= now else "announced"), ("source", e.source), ("confidence", "official"),
              ("note", f"Listed on the official seasonal sales page; {first} "
                       f"(written by sweetspot calendar --sync on {now.date().isoformat()}).")]
    lines = ["[[sale]]"] + [f"{k} = {v if isinstance(v, int) else _toml_string(str(v))}" for k, v in fields]
    return nl.join(lines) + nl


def write_sync(path: Path, plan: SyncPlan, *, now: datetime) -> dict:
    """Apply the plan by editing the text: every other byte of the file stays as it was; the result must load
    (load_calendar) before it replaces the file (FR-017)."""
    if not plan.add and not plan.reschedule:
        return {"written": False}
    raw = Path(path).read_bytes().decode("utf-8")
    nl = "\r\n" if "\r\n" in raw else "\n"
    default_time, tz = calendar.read_defaults(path)
    text = raw
    for move in plan.reschedule:
        for start, end in _blocks(text):
            block = text[start:end]
            year, season, _ = _block_key(block)
            if (year, season) != (move.file_event.year, move.file_event.season):
                continue
            seen = move.seen.date().isoformat() if move.seen else "unknown"
            sentence = (f"Rescheduled per the official seasonal sales page (seen {seen}); previously "
                        f"{_pacific_date(move.file_event.start, tz)} to {_pacific_date(move.file_event.end, tz)} "
                        f"from {move.file_event.source}.")
            block = _set_value(block, "start", _pacific_date(move.official.start, tz))
            block = _set_value(block, "end", _pacific_date(move.official.end, tz))
            block = _set_value(block, "source", move.official.source)
            text = text[:start] + _add_note(block, sentence, nl) + text[end:]
            break
    for add in sorted(plan.add, key=lambda a: a.event.start):
        block = _new_block(add, tz=tz, now=now, nl=nl)
        later = [s for s, e in _blocks(text)
                 if calendar._to_utc(_block_key(text[s:e])[2], default_time, tz) > add.event.start]
        if later:
            text = text[:later[0]] + block + nl + text[later[0]:]
        else:
            text = text + ("" if text.endswith(nl) else nl) + nl + block
    tmp = Path(path).with_name(Path(path).name + ".tmp")
    tmp.write_bytes(text.encode("utf-8"))
    try:
        calendar.load_calendar(tmp, now=now)
    except calendar.CalendarError as exc:
        tmp.unlink(missing_ok=True)
        return {"written": False, "error": str(exc)}
    os.replace(tmp, path)
    return {"written": True}


def load_effective(conn, path: Path, *, now: datetime) -> list[SaleEvent]:
    """The calendar the forecast uses: the file plus adopted official sales the file lacks. A file that cannot be
    read raises CalendarError; the database's sales are never used alone (FR-009)."""
    file_events = calendar.load_calendar(path, now=now)
    return calendar.effective_events(file_events, adopted_sales(conn, file_events=file_events, now=now))
