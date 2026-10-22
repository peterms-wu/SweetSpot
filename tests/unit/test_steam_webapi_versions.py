"""feature 006 (research R1, R2): purchase options, package contents and DLC parents from GetItems."""

import json
from urllib.parse import parse_qs

import httpx

from sweetspot import sources
from sweetspot.sources import steam_webapi
from sweetspot.sources.http import RateLimitedClient
from tests.conftest import FIXTURES


def raw(name):
    return json.loads((FIXTURES / "steam" / name).read_text(encoding="utf-8"))


def test_purchase_options_keep_packages_and_bundles_apart():
    got = steam_webapi.parse_purchase_options(raw("getitems_purchase_options.json"))
    dying = got[239140]
    assert dying[0] == sources.PurchaseOption(1345940, None, "Dying Light Essentials Edition", 67000, 13400)
    assert dying[2].package_id is None and dying[2].bundle_id == 49425
    eternights = got[1402110]
    package = next(o for o in eternights if o.package_id == 492077)
    assert (package.original_cents, package.final_cents) == (79000, 79000)   # no discount: original = final


def test_bundle_options_carry_the_bundle_discount_and_the_price_before_it():
    """feature 010 (research R2): the same request already returns them; packages and older rows have none."""
    got = steam_webapi.parse_purchase_options(raw("getitems_purchase_options.json"))
    e33 = got[1903340]
    bundle = next(o for o in e33 if o.bundle_id == 74895)
    assert (bundle.final_cents, bundle.bundle_discount_pct, bundle.before_bundle_cents) == (115000, 10, 147600)
    package = next(o for o in e33 if o.package_id == 685434)
    assert (package.bundle_discount_pct, package.before_bundle_cents) == (None, None)
    old_bundle = next(o for o in got[239140] if o.bundle_id == 49425)      # recorded without the two fields
    assert (old_bundle.bundle_discount_pct, old_bundle.before_bundle_cents) == (None, None)
    assert sources.PurchaseOption(1, None, "x", 1, 1).bundle_discount_pct is None     # defaults keep old callers


def test_version_packages_contents_and_public_flag():
    got = steam_webapi.parse_version_packages(raw("getitems_version_packages.json"))
    essentials = got[1345940]
    assert essentials.public and essentials.app_ids[0] == 239140 and len(essentials.app_ids) == 11
    assert got[1345941] == sources.VersionPackage(1345941, False, [], "Dying Light Essentials Edition")
    assert got[9900011].app_ids == [9500003]


def test_app_kinds_mark_dlc_and_parent():
    got = steam_webapi.parse_app_kinds(raw("getitems_dlc_apps.json"))
    assert got[302101] == sources.AppKind(302101, 4, 239140)
    game = got[534380]
    assert game.type == 0 and game.parent_app_id is None


def test_client_batches_fifty_ids_per_request():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(parse_qs(request.url.query.decode())["input_json"][0])
        seen.append(body)
        return httpx.Response(200, json={"response": {"store_items": []}})

    http = RateLimitedClient("t", min_interval=0, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    api = steam_webapi.SteamWebApi(http)
    api.purchase_options(list(range(1, 121)))
    assert [len(b["ids"]) for b in seen] == [50, 50, 20]
    assert seen[0]["data_request"] == {"include_all_purchase_options": True}
    assert seen[0]["context"]["country_code"] == "TW"


# --- feature 009: bundle contents (research R1) --------------------------------------------------------------

def test_bundle_contents_parse_apps_and_unknown_bundles():
    got = steam_webapi.parse_bundle_contents(raw("getitems_bundles.json"))
    assert got[32470] == sources.BundleContents(32470, True, [1091500, 2138330], "《電馭叛客 2077：終極版》")
    assert got[77855].app_ids == [1868140, 2527500]
    assert got[1] == sources.BundleContents(1, False, [], None)          # not described: unknown, not empty


def test_bundle_contents_batch_fifty_and_raise_on_http_errors():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(parse_qs(request.url.query.decode())["input_json"][0])
        seen.append(body)
        return httpx.Response(200, json={"response": {"store_items": []}})

    http = RateLimitedClient("t", min_interval=0, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    steam_webapi.SteamWebApi(http).bundle_contents(list(range(1, 61)))
    assert [len(b["ids"]) for b in seen] == [50, 10] and seen[0]["ids"][0] == {"bundleid": 1}

    failing = RateLimitedClient("t", min_interval=0, sleep=lambda s: None,
                                transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    import pytest
    from sweetspot.sources.errors import SourceError
    with pytest.raises(SourceError):
        steam_webapi.SteamWebApi(failing).bundle_contents([32470])


# --- feature 010: content prices of wishlist bundles (research R6) --------------------------------------------

def test_content_prices_read_the_best_purchase_option_and_name():
    got = steam_webapi.parse_content_prices(raw("getitems_content_prices.json"))
    assert got[457680] == sources.ContentPrice(457680, 30000, "OPUS：地球計畫")
    assert got[999001] == sources.ContentPrice(999001, None, None)          # on the store, no price: unknown
    assert 999002 not in got                                                # not described


def test_content_prices_batch_fifty_with_basic_info():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(parse_qs(request.url.query.decode())["input_json"][0]))
        return httpx.Response(200, json={"response": {"store_items": []}})

    http = RateLimitedClient("t", min_interval=0, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    steam_webapi.SteamWebApi(http).content_prices(list(range(1, 61)))
    assert [len(b["ids"]) for b in seen] == [50, 10] and seen[0]["data_request"] == {"include_basic_info": True}
