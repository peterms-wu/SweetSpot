"""Time helpers. All stored times are UTC, fixed-width ISO strings so they sort lexically."""

import calendar
import re
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

_DB_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_STEAM_DATE_FORMATS = ("%d %b, %Y", "%b %d, %Y", "%Y-%m-%d", "%d %B, %Y", "%B %d, %Y")
_ZH_DATE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")


def now_utc() -> datetime:
    return datetime.now(UTC)


def elapsed_clock(start: datetime) -> Callable[[], datetime]:
    """`start` plus the monotonic time since this call: the moment within a run that began at `start`. A run that is
    given a fixed `now` (tests, a replay) keeps its times reproducible apart from the elapsed seconds."""
    origin = time.monotonic()
    return lambda: start + timedelta(seconds=time.monotonic() - origin)


def _require_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"naive datetime is not allowed: {dt!r}")
    return dt.astimezone(UTC)


def parse_iso(text: str) -> datetime:
    """Parse an ISO-8601 timestamp with an explicit offset and return it in UTC."""
    return _require_aware(datetime.fromisoformat(text.replace("Z", "+00:00")))


def to_db(dt: datetime) -> str:
    return _require_aware(dt).strftime(_DB_FORMAT)


def from_db(text: str) -> datetime:
    return datetime.strptime(text, _DB_FORMAT).replace(tzinfo=UTC)


def itad_since(dt: datetime) -> str:
    """ITAD rejects fractional seconds (HTTP 400), so format to whole seconds in UTC."""
    return _require_aware(dt).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_steam_date(text: str | None) -> date | None:
    """Parse a Steam store release date; return None for unparseable text such as 'Coming soon'."""
    if not text:
        return None
    text = text.strip()
    match = _ZH_DATE.search(text)
    if match:
        year, month, day = map(int, match.groups())
        return date(year, month, day)
    for fmt in _STEAM_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def add_months(dt: datetime, months: int) -> datetime:
    """Add calendar months, clamping to the last day when the target month is shorter."""
    month_index = dt.month - 1 + months
    year, month = dt.year + month_index // 12, month_index % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)
