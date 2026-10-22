"""feature 006 (research R4): ITAD current prices with the number of Steam prices per product."""

import json

from sweetspot import sources
from sweetspot.sources import itad
from tests.conftest import FIXTURES

ESSENTIALS = "0197ad38-0c21-73fa-bb69-9c7b41676553"
PASSION = "018d937f-69a7-7354-bfff-7fcc53f11a27"
OLD_DYING_LIGHT = "018d937e-f022-7110-a507-755f61a998cc"


def payload():
    return json.loads((FIXTURES / "itad" / "prices_versions.json").read_text(encoding="utf-8"))


def test_summaries_count_steam_prices_and_keep_the_quote_only_when_single():
    got = itad.parse_price_summaries(payload(), [ESSENTIALS, PASSION, OLD_DYING_LIGHT])
    assert got[ESSENTIALS] == sources.ItadPrice(sources.PriceQuote("TWD", 67000, 13400, 80), 1)
    assert got[PASSION].steam_deals == 2 and got[PASSION].quote is None     # a package and a bundle
    assert got[OLD_DYING_LIGHT] == sources.ItadPrice(None, 0)               # ITAD no longer tracks it on Steam


def test_summaries_agree_with_current_prices():
    quotes = itad.parse_prices(payload())
    got = itad.parse_price_summaries(payload(), list(quotes))
    assert {k: v.quote for k, v in got.items()} == quotes


def test_missing_payload_means_unknown_not_zero():
    assert itad.parse_price_summaries(None, [ESSENTIALS]) == {}


# --- feature 009: ITAD products of packages and bundles in one request ---------------------------------------

def test_lookup_ids_asks_for_subs_and_bundles_together():
    import httpx

    from sweetspot.sources.http import RateLimitedClient
    lookup = json.loads((FIXTURES / "itad" / "lookup_options.json").read_text(encoding="utf-8"))
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={k: lookup.get(k) for k in json.loads(request.content)})

    http = RateLimitedClient("t", min_interval=0, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    got = itad.ItadClient(http, "key").lookup_ids([("sub", 349020), ("bundle", 32470), ("bundle", 77855)])
    assert bodies == [["sub/349020", "bundle/32470", "bundle/77855"]]
    assert got == {("sub", 349020): lookup["sub/349020"], ("bundle", 32470): lookup["bundle/32470"],
                   ("bundle", 77855): None}
