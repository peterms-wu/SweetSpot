"""Feature 012: the official seasonal sales page source and parser (research R0.2, R1)."""

from datetime import date

import httpx
import pytest

from sweetspot.sources import OfficialSale
from sweetspot.sources.errors import RateLimited, ResponseTooLarge, SourceDisabled, SourceError
from sweetspot.sources.http import RateLimitedClient
from sweetspot.sources.steam_partner import OFFICIAL_URL, SteamPartnerDocs, parse_seasonal_sales
from tests.conftest import partner_page

DATES_LINE = '<h2 class="bb_subsection"><a name="1"></a><strong>{title}</strong> | {dates}</h2>'
FAQ = '<h2 class="bb_section"><a name="3"></a>Frequently'


def page_with(*lines: tuple[str, str]) -> str:
    """The 2026-09-27 page with its four date lines replaced by `lines`."""
    base = partner_page()
    start = base.index('<h2 class="bb_subsection">')
    end = base.index(FAQ)
    body = " ".join(DATES_LINE.format(title=t, dates=d) for t, d in lines)
    return base[:start] + body + base[end:]


def test_parses_todays_page():
    parsed = parse_seasonal_sales(partner_page())
    assert parsed.found_dates_section is True
    assert parsed.sales == [
        OfficialSale("autumn", 2026, date(2026, 10, 1), date(2026, 10, 8)),
        OfficialSale("winter", 2026, date(2026, 12, 17), date(2027, 1, 4)),
        OfficialSale("spring", 2027, date(2027, 3, 18), date(2027, 3, 25)),
        OfficialSale("summer", 2027, date(2027, 6, 24), date(2027, 7, 8)),
    ]
    assert parsed.pending == [] and parsed.rejected == []


def test_month_first_dates_and_tbd():
    parsed = parse_seasonal_sales(partner_page("seasonalsales-2025-05-17.html"))
    assert parsed.sales == [
        OfficialSale("summer", 2025, date(2025, 6, 26), date(2025, 7, 10)),
        OfficialSale("autumn", 2025, date(2025, 9, 29), date(2025, 10, 6)),
        OfficialSale("winter", 2025, date(2025, 12, 18), date(2026, 1, 5)),
    ]
    assert parsed.pending == ["Spring Sale 2026 | TBD"]
    assert parsed.rejected == []


def test_year_written_once():
    parsed = parse_seasonal_sales(partner_page("seasonalsales-2024-03-20.html"))
    assert [(s.season, s.start_date, s.end_date) for s in parsed.sales] == [
        ("spring", date(2024, 3, 14), date(2024, 3, 21)),
        ("summer", date(2024, 6, 27), date(2024, 7, 11)),
        ("autumn", date(2024, 11, 27), date(2024, 12, 4)),
        ("winter", date(2024, 12, 19), date(2025, 1, 2)),
    ]
    assert parsed.rejected == []


def test_year_written_once_across_new_year():
    parsed = parse_seasonal_sales(page_with(("Winter Sale 2024", "December 19 - January 2, 2025")))
    assert parsed.sales == [OfficialSale("winter", 2024, date(2024, 12, 19), date(2025, 1, 2))]


def test_en_dash_without_commas():
    parsed = parse_seasonal_sales(page_with(("Autumn Sale 2026", "1 October 2026 – 8 October 2026")))
    assert parsed.sales == [OfficialSale("autumn", 2026, date(2026, 10, 1), date(2026, 10, 8))]


@pytest.mark.parametrize(("title", "dates", "reason"), [
    ("Holiday Sale 2026", "17 December, 2026 - 4 January, 2027", "unknown season"),
    ("Autumn Sale 2026", "early October", "date format"),
    ("Autumn Sale 2026", "1 Octember, 2026 - 8 October, 2026", "date format"),
    ("Autumn Sale 2026", "1 October, 2026 - 1 October, 2026", "length"),
    ("Summer Sale 2026", "1 June, 2026 - 15 July, 2026", "length"),
    ("Autumn Sale 2027", "1 October, 2026 - 8 October, 2026", "title year"),
])
def test_rejected_lines(title, dates, reason):
    parsed = parse_seasonal_sales(page_with((title, dates), ("Spring Sale 2027", "18 March, 2027 - 25 March, 2027")))
    assert [s.season for s in parsed.sales] == ["spring"]
    assert len(parsed.rejected) == 1
    assert parsed.rejected[0].line == f"{title} | {dates}"
    assert reason in parsed.rejected[0].reason


def test_same_sale_twice():
    same = parse_seasonal_sales(page_with(("Autumn Sale 2026", "1 October, 2026 - 8 October, 2026"),
                                          ("Autumn Sale 2026", "1 October, 2026 - 8 October, 2026")))
    assert len(same.sales) == 1 and same.rejected == []
    different = parse_seasonal_sales(page_with(("Autumn Sale 2026", "1 October, 2026 - 8 October, 2026"),
                                               ("Autumn Sale 2026", "2 October, 2026 - 9 October, 2026")))
    assert different.sales == []
    assert len(different.rejected) == 2 and all("different dates" in r.reason for r in different.rejected)


@pytest.mark.parametrize("text", ["", "<html><body><p>Seasonal sales</p></body></html>",
                                  partner_page(edit=('<a name="2"></a>Dates', '<a name="2"></a>Schedule'))])
def test_no_dates_section(text):
    parsed = parse_seasonal_sales(text)
    assert parsed.found_dates_section is False
    assert parsed.sales == [] and parsed.pending == [] and parsed.rejected == []


def test_reads_only_the_dates_section():
    text = partner_page(edit=(FAQ, FAQ + "</h2><p>Summer Sale 2030 | 1 July, 2030 - 8 July, 2030</p><h2>"))
    assert [s.year for s in parse_seasonal_sales(text).sales] == [2026, 2026, 2027, 2027]


def test_entities_and_whitespace():
    text = page_with(("Autumn  Sale&nbsp;2026", "1&nbsp;October,  2026 &#8211; 8 October, 2026"))
    assert parse_seasonal_sales(text).sales == [OfficialSale("autumn", 2026, date(2026, 10, 1), date(2026, 10, 8))]


# --- client ---------------------------------------------------------------------------------------------------------

class Recorder:
    def __init__(self, response=None, exc=None):
        self.response, self.exc, self.calls = response, exc, 0

    def __call__(self, request):
        self.calls += 1
        assert str(request.url) == OFFICIAL_URL
        if self.exc:
            raise self.exc
        return self.response


def docs(handler, sleeps=None):
    http = RateLimitedClient("steam-partner", min_interval=2.0, max_retries=0, max_retry_wait=0,
                             max_bytes=2 * 1024 * 1024, transport=httpx.MockTransport(handler),
                             sleep=(sleeps.append if sleeps is not None else lambda s: None))
    return SteamPartnerDocs(http), http


HTML = {"content-type": "text/html; charset=UTF-8"}


def test_fetches_and_parses():
    text = partner_page()
    source, http = docs(Recorder(httpx.Response(200, headers=HTML, text=text)))
    page = source.seasonal_sales_page()
    assert page.url == OFFICIAL_URL and page.http_status == 200
    assert page.bytes == len(text.encode("utf-8")) and len(page.sha256) == 64
    assert page.found_dates_section and len(page.sales) == 4
    assert http.requests_sent == 1


def test_denied_disables_the_source():
    handler = Recorder(httpx.Response(403, headers=HTML))
    source, http = docs(handler)
    with pytest.raises(SourceDisabled):
        source.seasonal_sales_page()
    assert http.disabled and handler.calls == 1


def test_rate_limited_gives_up_without_waiting():
    handler = Recorder(httpx.Response(429, headers={"Retry-After": "3600"}))
    sleeps = []
    source, _ = docs(handler, sleeps)
    with pytest.raises(RateLimited, match="3600"):
        source.seasonal_sales_page()
    assert handler.calls == 1 and sleeps == []


@pytest.mark.parametrize("headers", [{}, {"Retry-After": "0"}, {"Retry-After": "soon"}])
def test_rate_limited_without_a_wait_is_still_rate_limited(headers):
    """014 T076 (012 FR-002, data-model `rate_limited` = 429): a 429 with no usable Retry-After was a plain
    SourceError, so the notice said 'fetch failed' and not 'rate limited'."""
    handler = Recorder(httpx.Response(429, headers={**HTML, **headers}))
    sleeps = []
    source, _ = docs(handler, sleeps)
    with pytest.raises(RateLimited, match="429"):
        source.seasonal_sales_page()
    assert handler.calls == 1 and sleeps == []


@pytest.mark.parametrize("status", [500, 404, 301])
def test_other_statuses_fail_once(status):
    handler = Recorder(httpx.Response(status, headers=HTML))
    source, _ = docs(handler)
    with pytest.raises(SourceError):
        source.seasonal_sales_page()
    assert handler.calls == 1


def test_not_html_fails():
    source, _ = docs(Recorder(httpx.Response(200, json={"dates": []})))
    with pytest.raises(SourceError, match="text/html"):
        source.seasonal_sales_page()


def test_timeout_fails_once():
    handler = Recorder(exc=httpx.ReadTimeout("timed out"))
    source, _ = docs(handler)
    with pytest.raises(SourceError):
        source.seasonal_sales_page()
    assert handler.calls == 1


def test_too_large_fails():
    source, _ = docs(Recorder(httpx.Response(200, headers=HTML, content=b"x" * (2 * 1024 * 1024 + 1))))
    with pytest.raises(ResponseTooLarge):
        source.seasonal_sales_page()
