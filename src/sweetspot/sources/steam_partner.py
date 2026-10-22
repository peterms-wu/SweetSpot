"""Official seasonal sales page on the Steamworks documentation site (feature 012; research R0.2, R1).

The page's "Dates" section lists the next few seasonal sales, one line each, e.g. "Autumn Sale 2026 | 1 October, 2026 -
8 October, 2026". Three date spellings have been used since 2024 and not-yet-dated sales read "TBD". Only that section
is read; anything unrecognised is reported line by line and never guessed.
"""

import hashlib
import html
import re
from collections.abc import Callable
from datetime import date, datetime

from sweetspot.calendar import MAX_SEASONAL_DAYS, SEASONS
from sweetspot.sources import OfficialSale, ParsedSales, RejectedLine, SeasonalSalesPage
from sweetspot.sources.errors import SourceError
from sweetspot.sources.http import RateLimitedClient
from sweetspot.timeutil import now_utc

OFFICIAL_URL = "https://partner.steamgames.com/doc/marketing/discounts/seasonalsales"

MONTHS = {m: i for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
     "december"), 1)}
PENDING = {"tbd", "tba", "coming soon"}
MAX_SKIPPED_LINES = 3            # lines allowed between the "Dates" heading and its first date line

_HEADING = re.compile(r"(?i)\bsale\s+\d{4}\s*\|")
_TITLE = re.compile(r"^([A-Za-z]+)\s+Sale\s+(\d{4})\s*\|\s*(.*?)$")
_RANGE = re.compile(r"^(.+?)\s*[-–—]\s*(.+)$")
_DAY_FIRST = re.compile(r"^(\d{1,2})\s+([A-Za-z]+),?\s+(\d{4})$")       # 1 October, 2026 (2026)
_MONTH_FIRST = re.compile(r"^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$")     # June 27, 2024 (2024-25)
_NO_YEAR = re.compile(r"^([A-Za-z]+)\s+(\d{1,2})$")                     # March 14 - March 21, 2024 (2024-03)


def _text_lines(page: str) -> list[str]:
    body = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", page)
    body = re.sub(r"(?i)<br\s*/?>|</?(h\d|p|div|li|ul|ol|table|tr)\b[^>]*>", "\n", body)
    body = html.unescape(re.sub(r"<[^>]+>", "", body))
    return [line for line in (re.sub(r"\s+", " ", raw).strip() for raw in body.splitlines()) if line]


def _month(name: str) -> int:
    number = MONTHS.get(name.lower())
    if number is None:
        raise ValueError(f"date format: unknown month {name!r}")
    return number


def _date(text: str, year: int | None = None) -> date:
    if m := _DAY_FIRST.match(text):
        return date(int(m.group(3)), _month(m.group(2)), int(m.group(1)))
    if m := _MONTH_FIRST.match(text):
        return date(int(m.group(3)), _month(m.group(1)), int(m.group(2)))
    if year is not None and (m := _NO_YEAR.match(text)):
        return date(year, _month(m.group(1)), int(m.group(2)))
    raise ValueError(f"date format: {text!r}")


def _dates(text: str) -> tuple[date, date]:
    r = _RANGE.match(text)
    if not r:
        raise ValueError(f"date format: {text!r}")
    end = _date(r.group(2))
    start = _date(r.group(1), end.year)
    if start > end and _NO_YEAR.match(r.group(1)):
        start = start.replace(year=start.year - 1)            # "December 19 - January 2, 2025"
    return start, end


def _line(line: str) -> OfficialSale | str | RejectedLine:
    """An accepted sale, the line itself when it is listed without dates, or a rejection."""
    m = _TITLE.match(line)
    if not m:
        return RejectedLine(line, "format")
    season, year, rest = m.group(1).lower(), int(m.group(2)), m.group(3)
    if season not in SEASONS:
        return RejectedLine(line, f"unknown season {m.group(1)!r}")
    if rest.lower() in PENDING:
        return line
    try:
        start, end = _dates(rest)
    except ValueError as exc:
        return RejectedLine(line, str(exc))
    if not start < end or not 1 <= (end - start).days <= MAX_SEASONAL_DAYS:
        return RejectedLine(line, f"length {(end - start).days} days (must be 1 to {MAX_SEASONAL_DAYS})")
    if start.year != year:
        return RejectedLine(line, f"title year {year} is not the start year {start.year}")
    return OfficialSale(season, year, start, end)


def parse_seasonal_sales(page: str) -> ParsedSales:
    lines = _text_lines(page)
    try:
        begin = lines.index("Dates")
    except ValueError:
        return ParsedSales(found_dates_section=False)
    accepted: list[tuple[str, OfficialSale]] = []
    pending: list[str] = []
    rejected: list[RejectedLine] = []
    skipped = 0
    for line in lines[begin + 1:]:
        if not _HEADING.search(line):
            if accepted or pending or rejected or skipped >= MAX_SKIPPED_LINES:
                break
            skipped += 1
            continue
        result = _line(line)
        if isinstance(result, OfficialSale):
            accepted.append((line, result))
        elif isinstance(result, str):
            pending.append(result)
        else:
            rejected.append(result)
    by_key: dict[tuple[int, str], list[tuple[str, OfficialSale]]] = {}
    for line, sale in accepted:
        by_key.setdefault((sale.year, sale.season), []).append((line, sale))
    sales = []
    for items in by_key.values():
        if len({sale for _, sale in items}) == 1:
            sales.append(items[0][1])
        else:
            rejected += [RejectedLine(line, "the same sale is listed with different dates") for line, _ in items]
    found = bool(accepted or pending or rejected)
    return ParsedSales(found_dates_section=found, sales=sorted(sales, key=lambda s: s.start_date),
                       pending=pending, rejected=rejected)


class SteamPartnerDocs:
    """SeasonalSalesSource over the public Steamworks documentation page (one GET, no retries; research R1)."""

    url = OFFICIAL_URL

    def __init__(self, http: RateLimitedClient, clock: Callable[[], datetime] = now_utc):
        self.http = http
        self._clock = clock

    def seasonal_sales_page(self) -> SeasonalSalesPage:
        response = self.http.get(OFFICIAL_URL)
        if response.status_code != 200:
            raise SourceError(f"{self.http.name}: HTTP {response.status_code} for {OFFICIAL_URL}")
        kind = response.headers.get("content-type", "")
        if not kind.lower().startswith("text/html"):
            raise SourceError(f"{self.http.name}: expected text/html, got {kind or 'no content type'}")
        content = response.content
        parsed = parse_seasonal_sales(response.text)
        return SeasonalSalesPage(url=OFFICIAL_URL, fetched_at=self._clock(), http_status=response.status_code,
                                 bytes=len(content), sha256=hashlib.sha256(content).hexdigest(),
                                 found_dates_section=parsed.found_dates_section, sales=parsed.sales,
                                 pending=parsed.pending, rejected=parsed.rejected)
