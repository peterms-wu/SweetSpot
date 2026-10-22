"""Feature 012: comparing the official page with the calendar file, merging, fetch records and write-back
(research R3, R5; contracts/calendar-sync.md)."""

import json
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from sweetspot import calendar, calendar_sync
from sweetspot.sources import OfficialSale, RejectedLine, SeasonalSalesPage
from sweetspot.sources.errors import RateLimited, SourceDisabled, SourceError
from sweetspot.store.writer import StoreWriter

PT = ZoneInfo("America/Los_Angeles")
OFFICIAL = "https://partner.steamgames.com/doc/marketing/discounts/seasonalsales"
NOW = datetime(2026, 9, 27, 12, tzinfo=UTC)


def utc(day: str) -> datetime:
    return datetime.combine(date.fromisoformat(day), time(10), PT).astimezone(UTC)


def event(season, year, start, end, *, kind="seasonal", name=None, name_zh=None, source="https://example.test/a"):
    return calendar.SaleEvent(name=name or f"Steam {season.title()} Sale", name_zh=name_zh or calendar.SEASON_ZH[season],
                              kind=kind, season=season if kind == "seasonal" else None, year=year, start=utc(start),
                              end=utc(end), status="ended" if utc(end) <= NOW else "announced", source=source)


FILE = [
    event("summer", 2026, "2026-06-25", "2026-07-09"),
    event("autumn", 2026, "2026-10-01", "2026-10-08"),
    event("winter", 2026, "2026-12-17", "2027-01-04", name="Steam Winter Sale", name_zh="冬季特賣"),
    event("spring", 2027, "2027-03-18", "2027-03-25"),
    event("summer", 2027, "2027-06-24", "2027-07-08"),
]


def official(season, year, start, end):
    return calendar.official_event(season, year, utc(start), utc(end), source=OFFICIAL, now=NOW, file_events=FILE)


TODAY = [official("autumn", 2026, "2026-10-01", "2026-10-08"), official("winter", 2026, "2026-12-17", "2027-01-04"),
         official("spring", 2027, "2027-03-18", "2027-03-25"), official("summer", 2027, "2027-06-24", "2027-07-08")]


# --- pure functions (T009) -------------------------------------------------------------------------------------------

def test_official_event():
    e = official("autumn", 2027, "2027-09-30", "2027-10-07")
    assert (e.kind, e.season, e.year, e.status, e.confidence, e.source) == (
        "seasonal", "autumn", 2027, "announced", "official", OFFICIAL)
    assert e.start == datetime(2027, 9, 30, 17, tzinfo=UTC) and e.end == datetime(2027, 10, 7, 17, tzinfo=UTC)
    assert (e.name, e.name_zh) == ("Steam Autumn Sale", "秋季特賣")      # the latest file entry of the season
    assert official("summer", 2026, "2026-06-25", "2026-07-09").status == "ended"


def test_official_event_names_without_a_file_entry():
    e = calendar.official_event("spring", 2028, utc("2028-03-16"), utc("2028-03-23"), source=OFFICIAL, now=NOW,
                                file_events=[])
    assert (e.name, e.name_zh) == ("Steam Spring Sale", "春季特賣")


def test_compare_all_same():
    diff = calendar.compare_official(FILE, TODAY, now=NOW)
    assert [calendar.label(e) for e in diff.same] == ["2026 秋特", "2026 冬特", "2027 春特", "2027 夏特"]
    assert diff.new == [] and diff.conflicts == [] and diff.missing == []


def test_compare_new_conflict_missing():
    page = [TODAY[0], official("winter", 2026, "2026-12-18", "2027-01-04"), TODAY[3],
            official("autumn", 2027, "2027-09-30", "2027-10-07")]
    diff = calendar.compare_official(FILE, page, now=NOW)
    assert [calendar.label(e) for e in diff.same] == ["2026 秋特", "2027 夏特"]
    assert [calendar.label(e) for e in diff.new] == ["2027 秋特"]
    assert [(calendar.label(f), o.start) for f, o in diff.conflicts] == [("2026 冬特", utc("2026-12-18"))]
    assert [calendar.label(e) for e in diff.missing] == ["2027 春特"]          # not ended, within the page's range


def test_missing_ignores_ended_and_later_sales():
    later = FILE + [event("autumn", 2027, "2027-09-30", "2027-10-07")]      # the file already has one beyond the page
    diff = calendar.compare_official(later, TODAY, now=NOW)
    assert diff.missing == []
    only_summer = calendar.compare_official(FILE, [TODAY[3]], now=datetime(2026, 10, 10, tzinfo=UTC))
    assert [calendar.label(e) for e in only_summer.missing] == ["2026 冬特", "2027 春特"]   # 2026 秋特 has ended


def test_themed_sales_are_not_compared():
    themed = FILE + [event("summer", 2027, "2027-03-08", "2027-03-15", kind="themed", name_zh="節奏遊戲節")]
    assert calendar.compare_official(themed, TODAY, now=NOW).missing == []


def test_compare_with_an_empty_page():
    diff = calendar.compare_official(FILE, [], now=NOW)
    assert diff.same == diff.new == diff.conflicts == diff.missing == []


def test_effective_events_adds_only_what_the_file_lacks():
    adopted = [official("winter", 2026, "2026-12-18", "2027-01-04"), official("autumn", 2027, "2027-09-30", "2027-10-07")]
    merged = calendar.effective_events(FILE, adopted)
    assert [calendar.label(e) for e in merged] == ["2026 夏特", "2026 秋特", "2026 冬特", "2027 春特", "2027 夏特", "2027 秋特"]
    winter = next(e for e in merged if calendar.label(e) == "2026 冬特")
    assert winter.start == utc("2026-12-17") and winter.source != OFFICIAL        # the file wins a conflict
    assert merged[-1].source == OFFICIAL
    assert calendar.effective_events(FILE, []) == FILE


def test_read_defaults(tmp_path):
    path = tmp_path / "steam_sales.toml"
    path.write_text('schema_version = 1\ndefault_time = "09:00"\ndefault_tz = "UTC"\n', encoding="utf-8")
    assert calendar.read_defaults(path) == (time(9), ZoneInfo("UTC"))
    path.write_text("schema_version = 1\n", encoding="utf-8")
    assert calendar.read_defaults(path) == (time(10), ZoneInfo("America/Los_Angeles"))


def test_day_to_utc():
    assert calendar.day_to_utc(date(2026, 12, 17), time(10), PT) == datetime(2026, 12, 17, 18, tzinfo=UTC)   # PST
    assert calendar.day_to_utc(date(2026, 10, 1), time(10), PT) == datetime(2026, 10, 1, 17, tzinfo=UTC)     # PDT


@pytest.mark.parametrize("label, expected", [("2026 冬特", ("winter", 2026)), ("2027 春特", ("spring", 2027))])
def test_labels_stay_the_same(label, expected):
    season, year = expected
    assert calendar.label(official(season, year, "2026-12-17", "2027-01-04")) == label


# --- fetch records and adopted sales (T011) --------------------------------------------------------------------------

DEFAULTS = {"default_time": time(10), "tz": PT}


def page(*sales, pending=(), rejected=(), found=True, at=NOW):
    return SeasonalSalesPage(url=OFFICIAL, fetched_at=at, http_status=200, bytes=3576, sha256="ab" * 32,
                             found_dates_section=found, sales=list(sales), pending=list(pending),
                             rejected=list(rejected))


def sale(season, year, start, end):
    return OfficialSale(season, year, date.fromisoformat(start), date.fromisoformat(end))


AUTUMN_27 = sale("autumn", 2027, "2027-09-30", "2027-10-07")
WINTER_26 = sale("winter", 2026, "2026-12-17", "2027-01-04")


@pytest.fixture
def writer(db_path):
    w = StoreWriter.open(db_path)
    yield w
    w.close()


def fetches(w):
    return w.conn.execute("SELECT status, reason, http_status, accepted, pending, rejected_json, run_id "
                          "FROM calendar_fetches ORDER BY fetch_id").fetchall()


def test_record_successful_fetch(writer):
    calendar_sync.record_fetch(writer, page(WINTER_26, AUTUMN_27, pending=["Spring Sale 2028 | TBD"]), now=NOW,
                               run_id="r1", **DEFAULTS)
    assert fetches(writer) == [("ok", None, 200, 2, 1, "[]", "r1")]
    rows = writer.conn.execute("SELECT season, year, starts_at, ends_at FROM sale_sightings ORDER BY year").fetchall()
    assert rows == [("winter", 2026, "2026-12-17T18:00:00.000000Z", "2027-01-04T18:00:00.000000Z"),
                    ("autumn", 2027, "2027-09-30T17:00:00.000000Z", "2027-10-07T17:00:00.000000Z")]


@pytest.mark.parametrize("result, status", [
    (page(found=False), "no_dates"),
    (page(rejected=[RejectedLine("Holiday Sale 2026 | x", "unknown season 'Holiday'")]), "no_dates"),
    (SourceDisabled("steam-partner: HTTP 403"), "denied"),
    (RateLimited("steam-partner: asked to wait 7200s"), "rate_limited"),
    (SourceError("steam-partner: network error"), "failed"),
])
def test_record_unsuccessful_fetch(writer, result, status):
    calendar_sync.record_fetch(writer, result, now=NOW, **DEFAULTS)
    (row,) = fetches(writer)
    assert row[0] == status
    assert writer.conn.execute("SELECT COUNT(*) FROM sale_sightings").fetchone()[0] == 0
    if isinstance(result, Exception):
        assert row[1] == str(result) and row[2] is None


def test_only_tbd_lines_is_still_a_successful_read(writer):
    calendar_sync.record_fetch(writer, page(pending=["Spring Sale 2027 | TBD"]), now=NOW, **DEFAULTS)
    assert fetches(writer)[0][0] == "ok"


def test_rejected_lines_are_capped(writer):
    lines = [RejectedLine("x" * 300, "format")] * 25
    calendar_sync.record_fetch(writer, page(WINTER_26, rejected=lines), now=NOW, **DEFAULTS)
    stored = json.loads(fetches(writer)[0][5])
    assert len(stored) == 20 and all(len(r["line"]) == 200 for r in stored)


def at(day):
    return datetime.fromisoformat(day).replace(tzinfo=UTC)


def test_adopted_sales_use_the_latest_sighting(writer):
    moved = sale("autumn", 2027, "2027-10-07", "2027-10-14")
    calendar_sync.record_fetch(writer, page(WINTER_26, AUTUMN_27, at=at("2027-03-01")), now=at("2027-03-01"), **DEFAULTS)
    calendar_sync.record_fetch(writer, SourceError("x"), now=at("2027-03-02"), **DEFAULTS)
    calendar_sync.record_fetch(writer, page(moved, at=at("2027-03-03")), now=at("2027-03-03"), **DEFAULTS)  # winter gone
    adopted = calendar_sync.adopted_sales(writer.conn, file_events=FILE, now=at("2027-03-04"))
    assert [(calendar.label(e), e.start) for e in adopted] == [("2026 冬特", utc("2026-12-17")),
                                                               ("2027 秋特", utc("2027-10-07"))]
    assert all(e.source == OFFICIAL and e.confidence == "official" for e in adopted)
    assert adopted[0].status == "ended" and adopted[1].status == "announced"
    listed = calendar_sync.listed_now(writer.conn, file_events=FILE, now=at("2027-03-04"))
    assert [calendar.label(e) for e in listed] == ["2027 秋特"]
    assert calendar_sync.last_success(writer.conn) == at("2027-03-03")
    assert calendar_sync.latest_fetch(writer.conn)["status"] == "ok"


def test_sighting_times(writer):
    moved = sale("autumn", 2027, "2027-10-07", "2027-10-14")
    for day, sales in (("2027-03-01", [AUTUMN_27]), ("2027-03-02", [AUTUMN_27]), ("2027-03-03", [moved])):
        calendar_sync.record_fetch(writer, page(*sales, at=at(day)), now=at(day), **DEFAULTS)
    times = calendar_sync.sighting_times(writer.conn, "autumn", 2027)
    assert times == [(utc("2027-09-30"), utc("2027-10-07"), at("2027-03-01"), at("2027-03-02")),
                     (utc("2027-10-07"), utc("2027-10-14"), at("2027-03-03"), at("2027-03-03"))]


def test_nothing_recorded(writer):
    assert calendar_sync.adopted_sales(writer.conn, file_events=FILE, now=NOW) == []
    assert calendar_sync.listed_now(writer.conn, file_events=FILE, now=NOW) == []
    assert calendar_sync.last_success(writer.conn) is None and calendar_sync.latest_fetch(writer.conn) is None


CALENDAR_FILE = ('schema_version = 1\ndefault_time = "10:00"\ndefault_tz = "America/Los_Angeles"\n\n'
                 '[[sale]]\nname = "Steam Winter Sale"\nname_zh = "冬季特賣"\nkind = "seasonal"\nseason = "winter"\n'
                 'year = 2026\nstart = "2026-12-17"\nend = "2027-01-04"\nstatus = "announced"\n'
                 'source = "https://example.test/w"\n')


def test_load_effective(writer, tmp_path):
    path = tmp_path / "steam_sales.toml"
    path.write_text(CALENDAR_FILE, encoding="utf-8")
    calendar_sync.record_fetch(writer, page(WINTER_26, AUTUMN_27), now=NOW, **DEFAULTS)
    merged = calendar_sync.load_effective(writer.conn, path, now=NOW)
    assert [(calendar.label(e), e.source) for e in merged] == [("2026 冬特", "https://example.test/w"),
                                                               ("2027 秋特", OFFICIAL)]
    path.write_text("not toml [", encoding="utf-8")
    with pytest.raises(calendar.CalendarError):
        calendar_sync.load_effective(writer.conn, path, now=NOW)       # FR-009: never the database alone


# --- write-back (T036; research R5; contracts/calendar-sync.md §4-§5) -------------------------------------------------

SYNC_FILE = """# test calendar
schema_version = 1
default_time = "10:00"
default_tz = "America/Los_Angeles"

[[sale]]
name = "Steam Summer Sale"
name_zh = "夏季特賣"
kind = "seasonal"
season = "summer"
year = 2026
start = "2026-06-25"
end = "2026-07-09"
status = "ended"
source = "https://example.test/summer"
confidence = "official"
note = "Summer \\"quoted\\" note."

[[sale]]
name = "Steam Winter Sale"
name_zh = "冬季特賣"
kind = "seasonal"
season = "winter"
year = 2026
start = "2026-12-17"
end = "2027-01-04"
status = "announced"
source = "https://example.test/winter"
confidence = "official"
"""

AUTUMN_26 = sale("autumn", 2026, "2026-10-01", "2026-10-08")
WINTER_MOVED = sale("winter", 2026, "2026-12-18", "2027-01-04")
AUTUMN_BLOCK = """[[sale]]
name = "Steam Autumn Sale"
name_zh = "秋季特賣"
kind = "seasonal"
season = "autumn"
year = 2026
start = "2026-10-01"
end = "2026-10-08"
status = "announced"
source = "https://partner.steamgames.com/doc/marketing/discounts/seasonalsales"
confidence = "official"
note = "Listed on the official seasonal sales page; first seen 2026-09-27 (written by sweetspot calendar --sync on 2026-09-27)."

"""


@pytest.fixture
def synced(writer, tmp_path):
    path = tmp_path / "steam_sales.toml"
    path.write_bytes(SYNC_FILE.encode("utf-8"))
    calendar_sync.record_fetch(writer, page(AUTUMN_26, WINTER_MOVED), now=NOW, **DEFAULTS)
    return writer, path


def test_sync_plan_lists_additions_and_reschedules(synced):
    writer, path = synced
    plan = calendar_sync.sync_plan(writer.conn, path, now=NOW)
    assert [(calendar.label(a.event), a.first_seen) for a in plan.add] == [("2026 秋特", NOW)]
    assert [(calendar.label(r.file_event), r.official.start, r.seen) for r in plan.reschedule] == [
        ("2026 冬特", utc("2026-12-18"), NOW)]
    assert plan.based_on_fetch == NOW
    assert calendar_sync.sync_summary(plan, written=False) == {
        "written": False, "based_on_fetch": NOW.isoformat(),
        "add": [{"label": "2026 秋特", "start": "2026-10-01", "end": "2026-10-08", "first_seen": "2026-09-27"}],
        "reschedule": [{"label": "2026 冬特", "file": ["2026-12-17", "2027-01-04"],
                        "official": ["2026-12-18", "2027-01-04"]}]}


def test_write_inserts_and_reschedules_leaving_everything_else(synced):
    writer, path = synced
    result = calendar_sync.write_sync(path, calendar_sync.sync_plan(writer.conn, path, now=NOW), now=NOW)
    assert result == {"written": True}
    text = path.read_bytes().decode("utf-8")
    winter_at = SYNC_FILE.index("[[sale]]\nname = \"Steam Winter Sale\"")
    assert text.startswith(SYNC_FILE[:winter_at] + AUTUMN_BLOCK)                   # before: byte for byte
    winter = text[len(SYNC_FILE[:winter_at] + AUTUMN_BLOCK):]
    assert winter == SYNC_FILE[winter_at:].replace('start = "2026-12-17"', 'start = "2026-12-18"').replace(
        'source = "https://example.test/winter"', f'source = "{OFFICIAL}"') + (
        'note = "Rescheduled per the official seasonal sales page (seen 2026-09-27); previously 2026-12-17 to '
        '2027-01-04 from https://example.test/winter."\n')
    calendar.load_calendar(path, now=NOW)                                          # valid
    again = calendar_sync.sync_plan(writer.conn, path, now=NOW)
    assert again.add == [] and again.reschedule == []


def test_reschedule_appends_to_an_existing_note(writer, tmp_path):
    path = tmp_path / "steam_sales.toml"
    path.write_bytes(SYNC_FILE.encode("utf-8"))
    calendar_sync.record_fetch(writer, page(sale("summer", 2026, "2026-06-26", "2026-07-10")), now=NOW, **DEFAULTS)
    calendar_sync.write_sync(path, calendar_sync.sync_plan(writer.conn, path, now=NOW), now=NOW)
    text = path.read_text(encoding="utf-8")
    assert ('note = "Summer \\"quoted\\" note. Rescheduled per the official seasonal sales page (seen 2026-09-27); '
            'previously 2026-06-25 to 2026-07-09 from https://example.test/summer."') in text
    assert 'start = "2026-06-26"' in text and 'end = "2026-07-10"' in text


def test_no_difference_leaves_the_file_alone(writer, tmp_path):
    path = tmp_path / "steam_sales.toml"
    path.write_bytes(SYNC_FILE.encode("utf-8"))
    calendar_sync.record_fetch(writer, page(WINTER_26), now=NOW, **DEFAULTS)
    stamp = path.stat().st_mtime_ns
    plan = calendar_sync.sync_plan(writer.conn, path, now=NOW)
    assert plan.add == [] and plan.reschedule == []
    assert calendar_sync.write_sync(path, plan, now=NOW) == {"written": False}
    assert path.stat().st_mtime_ns == stamp


def test_invalid_result_keeps_the_original(synced, monkeypatch):
    writer, path = synced
    plan = calendar_sync.sync_plan(writer.conn, path, now=NOW)
    before = path.read_bytes()

    def broken(p, *, now):
        raise calendar.CalendarError("broken on purpose")

    monkeypatch.setattr(calendar, "load_calendar", broken)
    result = calendar_sync.write_sync(path, plan, now=NOW)
    assert result == {"written": False, "error": "broken on purpose"}
    assert path.read_bytes() == before
    assert list(path.parent.glob("*.tmp")) == []


def test_crlf_files_keep_crlf(synced):
    writer, path = synced
    path.write_bytes(SYNC_FILE.replace("\n", "\r\n").encode("utf-8"))
    calendar_sync.write_sync(path, calendar_sync.sync_plan(writer.conn, path, now=NOW), now=NOW)
    raw = path.read_bytes()
    assert b"\n" not in raw.replace(b"\r\n", b"") and raw.count(b"[[sale]]") == 3


def test_write_back_on_the_real_calendar_file(writer, tmp_path):
    """The real file (151 entries, long notes): only the rescheduled block's lines and the new block change."""
    import difflib
    from pathlib import Path

    real = Path(__file__).parents[2] / "data" / "steam_sales.toml"
    path = tmp_path / "steam_sales.toml"
    path.write_bytes(real.read_bytes())
    calendar_sync.record_fetch(writer, page(WINTER_MOVED, AUTUMN_27), now=NOW, **DEFAULTS)
    assert calendar_sync.write_sync(path, calendar_sync.sync_plan(writer.conn, path, now=NOW), now=NOW) == \
        {"written": True}
    before = real.read_bytes().decode("utf-8").splitlines(keepends=True)
    after = path.read_bytes().decode("utf-8").splitlines(keepends=True)
    changed = [line for line in difflib.unified_diff(before, after, n=0)
               if line[:1] in "+-" and not line.startswith(("+++", "---"))]
    removed = [line for line in changed if line.startswith("-")]
    added = [line for line in changed if line.startswith("+")]
    # the file's 2026 winter already cites the official page, so only its start and note change
    assert [line.split(" =")[0] for line in removed] == ["-start", "-note"]
    assert len(added) == 2 + 13                     # the two changed winter lines, the new block (12) and a blank line
    events = calendar.load_calendar(path, now=NOW)
    assert len(events) == 152
    labels = [calendar.label(e) for e in events]
    assert labels.index("2027 夏特") < labels.index("2027 秋特")


def test_new_sale_after_every_block_is_appended(writer, tmp_path):
    path = tmp_path / "steam_sales.toml"
    path.write_bytes(SYNC_FILE.encode("utf-8"))
    calendar_sync.record_fetch(writer, page(sale("spring", 2027, "2027-03-18", "2027-03-25")), now=NOW, **DEFAULTS)
    calendar_sync.write_sync(path, calendar_sync.sync_plan(writer.conn, path, now=NOW), now=NOW)
    text = path.read_text(encoding="utf-8")
    assert text.startswith(SYNC_FILE + "\n[[sale]]\nname = \"Steam Spring Sale\"")
    assert [calendar.label(e) for e in calendar.load_calendar(path, now=NOW)][-1] == "2027 春特"
