"""P4: one live fetch through the project's RateLimitedClient (timing, headers, parse), plus one fetch of the
2026 autumn sale's own page to check the start time of day (FR-004). 2 requests in total.

Usage: uv run python specs/012-sale-calendar-sync/prototype/p4_fetch.py
"""

import re
import time
from datetime import UTC, datetime
from pathlib import Path

from steamsage import calendar
from steamsage.sources.http import RateLimitedClient

from p1_parse import ROOT, SOURCE, _text_lines, compare, parse

EVENT_PAGE = "https://partner.steamgames.com/doc/marketing/upcoming_events/2026_autumn_sale"


def main() -> None:
    client = RateLimitedClient("steam-partner-docs", min_interval=2.0, max_retries=0)
    try:
        started = time.monotonic()
        response = client.get(SOURCE)
        seconds = time.monotonic() - started
        headers = {k: response.headers.get(k) for k in ("content-type", "cache-control", "etag", "last-modified",
                                                         "content-encoding", "content-length")}
        print(f"GET {SOURCE}: {response.status_code}, {len(response.content)} bytes, {seconds:.2f} s")
        print(f"    headers: {headers}")
        started = time.monotonic()
        parsed, rejected, found = parse(response.text)
        now = datetime.now(UTC)
        diff = compare(parsed, calendar.load_calendar(ROOT / "data" / "steam_sales.toml", now=now), now)
        print(f"    parse {1000 * (time.monotonic() - started):.0f} ms: section={found} parsed={len(parsed)} "
              f"rejected={[r.reason for r in rejected]} {({k: len(v) for k, v in diff.items()})}")
        response = client.get(EVENT_PAGE)
        print(f"GET {EVENT_PAGE}: {response.status_code}")
        for line in _text_lines(response.text):
            if re.search(r"(?i)\b(\d{1,2}(:\d\d)?\s*(am|pm)|pacific|PT\b|PDT|PST|UTC)", line) and len(line) < 400:
                print(f"    {line}")
        out = Path(__file__).parent / "out"
        out.mkdir(exist_ok=True)
        (out / "2026_autumn_sale.html").write_text(response.text, encoding="utf-8")
        print(f"requests sent: {client.requests_sent}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
