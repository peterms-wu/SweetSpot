"""P1: parse the official seasonal sales page and compare it with data/steam_sales.toml (read-only).

Usage: uv run python specs/012-sale-calendar-sync/prototype/p1_parse.py [page.html ...]
Default page: out/seasonalsales-2026-09-27.html (saved 2026-09-27). Also runs the synthetic variants (V1-V8).
"""

import html
import re
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from steamsage import calendar

HERE = Path(__file__).parent
ROOT = HERE.parents[2]
SOURCE = "https://partner.steamgames.com/doc/marketing/discounts/seasonalsales"
SEASON_WORDS = {"spring": "spring", "summer": "summer", "autumn": "autumn", "winter": "winter"}
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
     "december"], 1)}
TITLE = re.compile(r"^\s*([A-Za-z]+)\s+Sale\s+(\d{4})\s*\|\s*(.*?)\s*$")
# Both orders occur on the page: "1 October, 2026" (2026) and "June 27, 2024" (2024-25).
DAY_FIRST = re.compile(r"^(\d{1,2})\s+([A-Za-z]+),?\s+(\d{4})$")
MONTH_FIRST = re.compile(r"^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$")
RANGE = re.compile(r"^(.+?)\s*[-–—]\s*(.+)$")
HEADING = re.compile(r"(?i)\bsale\s+\d{4}\s*\|")
PENDING = {"tbd", "tba", "coming soon"}


@dataclass(frozen=True)
class Parsed:
    season: str
    year: int
    start: date
    end: date


@dataclass(frozen=True)
class Rejected:
    line: str
    reason: str


def _text_lines(page: str) -> list[str]:
    body = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", page)
    body = re.sub(r"(?i)<br\s*/?>|</?(h\d|p|div|li)\b[^>]*>", "\n", body)
    body = html.unescape(re.sub(r"<[^>]+>", "", body))
    return [re.sub(r"\s+", " ", l).strip() for l in body.splitlines() if l.strip()]


def _date(text: str) -> date:
    if m := DAY_FIRST.match(text):
        day, month, year = m.groups()
    elif m := MONTH_FIRST.match(text):
        month, day, year = m.groups()
    else:
        raise ValueError(f"date format {text!r}")
    number = MONTHS.get(month.lower())
    if number is None:
        raise ValueError(f"unknown month {month!r}")
    return date(int(year), number, int(day))


def parse(page: str) -> tuple[list[Parsed], list[Rejected], bool]:
    """(accepted, rejected, dates_section_found). Only lines inside the 'Dates' section are read."""
    lines = _text_lines(page)
    try:
        begin = lines.index("Dates")
    except ValueError:
        return [], [], False
    accepted, rejected = [], []
    for line in lines[begin + 1:]:
        if not HEADING.search(line):
            if accepted or rejected:
                break                     # the section ends at the first non-date line after the dates
            continue
        m = TITLE.match(line)
        if not m:
            rejected.append(Rejected(line, "format"))
            continue
        season = SEASON_WORDS.get(m.group(1).lower())
        if season is None:
            rejected.append(Rejected(line, f"unknown season {m.group(1)!r}"))
            continue
        if m.group(3).lower() in PENDING:
            rejected.append(Rejected(line, "tbd"))      # listed without dates: not an error
            continue
        r = RANGE.match(m.group(3))
        try:
            if not r:
                raise ValueError(f"range format {m.group(3)!r}")
            end = _date(r.group(2))
            first = r.group(1)
            if not re.search(r"\d{4}$", first):   # "March 14 - March 21, 2024" (2024-03): year written once
                first = f"{first}, {end.year}"
            start = _date(first)
            if start > end and start.replace(year=start.year - 1) < end:
                start = start.replace(year=start.year - 1)   # "December 19 - January 2, 2025"
        except ValueError as exc:
            rejected.append(Rejected(line, str(exc)))
            continue
        year = int(m.group(2))
        if not start < end or not 1 <= (end - start).days <= calendar.MAX_SEASONAL_DAYS:
            rejected.append(Rejected(line, "length"))
            continue
        if start.year != year:
            rejected.append(Rejected(line, "title year != start year"))
            continue
        accepted.append(Parsed(season, year, start, end))
    # duplicates: same season/year twice with different dates -> reject both
    by_key: dict = {}
    for p in accepted:
        by_key.setdefault((p.year, p.season), set()).add(p)
    out = []
    for key, items in by_key.items():
        if len(items) == 1:
            out.append(next(iter(items)))
        else:
            rejected.append(Rejected(f"{key}", "duplicate with different dates"))
    return sorted(out, key=lambda p: p.start), rejected, True


def to_utc(day: date) -> datetime:
    return datetime.combine(day, time(10, 0), ZoneInfo("America/Los_Angeles")).astimezone(UTC)


def compare(parsed: list[Parsed], events: list[calendar.SaleEvent], now: datetime) -> dict[str, list]:
    toml = {(e.year, e.season): e for e in events if e.kind == "seasonal"}
    out = {"same": [], "new": [], "conflict": [], "missing": []}
    seen = set()
    for p in parsed:
        key = (p.year, p.season)
        seen.add(key)
        e = toml.get(key)
        if e is None:
            out["new"].append(p)
        elif (e.start, e.end) == (to_utc(p.start), to_utc(p.end)):
            out["same"].append(p)
        else:
            out["conflict"].append((p, e))
    if parsed:
        last = max(p.start for p in parsed)
        for key, e in toml.items():
            # not ended, not listed, and within the page's horizon (not later than its last listed sale)
            if key not in seen and e.end > now and to_utc(last) >= e.start:
                out["missing"].append(e)
    return out


def show(name: str, page: str, events, now) -> dict:
    parsed, rejected, found = parse(page)
    diff = compare(parsed, events, now)
    counts = {k: len(v) for k, v in diff.items()}
    print(f"{name}: section={'yes' if found else 'NO'} parsed={len(parsed)} rejected={len(rejected)} {counts}")
    for r in rejected:
        print(f"    rejected: {r.reason}: {r.line[:90]}")
    for p, e in diff["conflict"]:
        print(f"    conflict {p.year} {p.season}: page {p.start}..{p.end} vs toml {e.start:%Y-%m-%d}..{e.end:%Y-%m-%d}")
    for p in diff["new"]:
        print(f"    new {p.year} {p.season}: {p.start}..{p.end}")
    for e in diff["missing"]:
        print(f"    missing {calendar.label(e)}")
    return counts


def variants(base: str) -> dict[str, str]:
    add = ('<h2 class="bb_subsection"><a name="1"></a><strong>Autumn Sale 2027</strong> | 30 September, 2027 - 7 October,'
           ' 2027</h2>')
    anchor = '<h2 class="bb_section"><a name="3"></a>Frequently'
    return {
        "V1 new 2027 autumn": base.replace(anchor, add + anchor),
        "V2 winter moved +1 day": base.replace("17 December, 2026", "18 December, 2026"),
        "V3 renamed season": base.replace("<strong>Winter Sale 2026</strong>", "<strong>Holiday Sale 2026</strong>"),
        "V4 date format changed": base.replace("1 October, 2026 - 8 October, 2026", "October 1 - October 8, 2026"),
        "V5 no Dates section": base.replace("<a name=\"2\"></a>Dates", "<a name=\"2\"></a>Schedule"),
        "V6 empty page": "",
        "V7 spring removed early": re.sub(r"<h2 class=\"bb_subsection\"><a name=\"1\"></a><strong>Spring Sale 2027.*?</h2>",
                                          "", base),
        "V8 en dash, no comma": base.replace("1 October, 2026 - 8 October, 2026", "1 October 2026 – 8 October 2026"),
    }


def main() -> None:
    now = datetime(2026, 9, 27, 12, tzinfo=UTC)
    events = calendar.load_calendar(ROOT / "data" / "steam_sales.toml", now=now)
    pages = [Path(p) for p in sys.argv[1:]] or [HERE / "out" / "seasonalsales-2026-09-27.html"]
    for path in pages:
        base = path.read_text(encoding="utf-8")
        show(path.name, base, events, now)
    for name, page in variants(base).items():
        show(name, page, events, now)


if __name__ == "__main__":
    main()
