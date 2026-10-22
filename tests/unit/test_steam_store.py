import json
from datetime import UTC, date, datetime

import pytest

from sweetspot.sources import PriceQuote, WishlistFetchError
from sweetspot.sources import steam_store as ss
from sweetspot.sources import steam_webapi as sw
from tests.conftest import FIXTURES

STEAM = FIXTURES / "steam"


def load(name):
    return json.loads((STEAM / name).read_text(encoding="utf-8"))


def test_full_details_matched_by_steam_appid_not_outer_key():
    raw = load("appdetails_620.json")
    assert list(raw) != ["620"]  # the recorded quirk: outer key differs from the requested app
    details = ss.parse_app_details(raw, 620)
    assert details.app_id == 620 and details.type == "game" and details.name == "Portal 2"
    assert details.release_date == date(2011, 4, 18)
    assert details.publishers == ["Valve"] and details.developers == ["Valve"]
    assert 7877 in details.package_ids
    assert details.quote == PriceQuote("TWD", 18800, 18800, 0)
    assert details.is_free is False and details.coming_soon is False
    assert details.parent_app_id is None


def test_soundtrack_has_parent_app():
    details = ss.parse_app_details(load("appdetails_323180.json"), 323180)
    assert details.type == "music" and details.parent_app_id == 620


def test_missing_app_returns_none():
    assert ss.parse_app_details(load("appdetails_missing.json"), 1) is None


def test_price_batch_in_cents():
    lookups = ss.parse_price_batch(load("appdetails_prices.json"), [620, 413150, 1145360])
    assert lookups[620].found and lookups[620].quote == PriceQuote("TWD", 18800, 18800, 0)
    assert lookups[413150].quote.initial_cents == 39800


def test_price_batch_success_without_price_and_missing_apps():
    raw = {"10": {"success": True, "data": []}, "11": {"success": False}}
    lookups = ss.parse_price_batch(raw, [10, 11, 12])
    assert lookups[10].found and lookups[10].quote is None
    assert not lookups[11].found and not lookups[12].found


@pytest.mark.parametrize(
    "genres,expected",
    [
        ([{"id": "23", "description": "獨立"}], True),
        ([{"id": "99", "description": "Indie"}], True),
        ([{"id": "1", "description": "動作"}], False),
        ([], None),
        (None, None),
    ],
)
def test_indie_detection(genres, expected):
    assert ss.is_indie(genres) is expected


@pytest.mark.parametrize(
    "type_,parent,expected",
    [("game", None, "game"), ("dlc", 620, "dlc"), ("music", 620, "dlc"), ("demo", 620, "other"),
     ("video", None, "other"), (None, None, None)],
)
def test_product_type_mapping(type_, parent, expected):
    assert ss.product_type(type_, parent) == expected


def test_review_summary():
    summary = ss.parse_review_summary(load("appreviews_620.json"))
    assert summary.total_reviews == 467117 and summary.total_positive == 461064


def test_package_details():
    pkg = ss.parse_package_details(load("packagedetails_7877.json"), 7877)
    assert pkg.app_ids == [620] and pkg.quote == PriceQuote("TWD", 18800, 18800, 0)


def test_getitems_summary():
    items = sw.parse_items(load("getitems.json"))
    assert items[620].review_count_filtered == 390695 and items[620].percent_positive == 98
    assert items[620].tag_ids


def test_wishlist_parse():
    """The fixture keeps 5 games with a fictional order and dates (014 FR-008; scripts/record_fixtures.py)."""
    entries = sw.parse_wishlist(load("wishlist_ok.json"))
    assert len(entries) == 5
    first = entries[0]
    assert first.app_id == 239140 and first.priority == 1
    assert first.date_added == datetime.fromtimestamp(1700086400, UTC)
    assert [e.priority for e in entries] == [1, 2, 3, 4, 5]


@pytest.mark.parametrize(
    "payload,reason",
    [({"response": {}}, "private"), ({}, "malformed"), ({"response": {"items": "x"}}, "malformed"),
     ({"response": {"items": [{"priority": 1}]}}, "malformed")],
)
def test_wishlist_parse_rejections(payload, reason):
    with pytest.raises(WishlistFetchError) as info:
        sw.parse_wishlist(payload)
    assert info.value.reason == reason


def test_wishlist_explicit_empty():
    assert sw.parse_wishlist({"response": {"items": []}}) == []


def test_catalog_pages_parse_app_ids_and_totals():
    """A publisher catalog of 144 games over 3 pages, titles and ids fictional (014 FR-008a)."""
    pages = [ss.parse_catalog_page(load(f"search_publisher_{start}.json"), start) for start in (0, 50, 100)]
    assert [p.total_count for p in pages] == [144, 144, 144]
    assert [p.start for p in pages] == [0, 50, 100]
    assert [len(p.app_ids) for p in pages] == [50, 50, 44]
    assert pages[0].app_ids[0] == 9000007 and pages[2].app_ids[-1] == 9000007 + 10 * 143
    assert len(set().union(*(p.app_ids for p in pages))) == 144


def test_catalog_page_rejects_failed_response():
    with pytest.raises(ss.SourceError):
        ss.parse_catalog_page({"success": 2}, 0)


def test_app_list_pages():
    first = sw.parse_app_list(load("applist_page1.json"))
    second = sw.parse_app_list(load("applist_page2.json"))
    assert first.apps[0][:2] == (10, "Counter-Strike") and first.have_more
    assert first.last_appid == first.apps[-1][0] and second.apps[0][0] > first.last_appid


def test_getitems_release_and_type():
    items = sw.parse_items(load("getitems.json"))
    assert items[620].app_type == 0 and items[620].release_date == date(2011, 4, 19)


def test_catalog_rows_include_packages_but_ids_are_single_apps():
    page = ss.parse_catalog_page(load("search_dev_larian_0.json"), 0)
    assert page.total_count == 9 and page.rows == 9
    assert len(page.app_ids) == 8          # the package row lists several app ids and is not a single app
    assert all(isinstance(a, int) for a in page.app_ids)


def test_empty_catalog_page():
    page = ss.parse_catalog_page(load("search_dev_empty_0.json"), 0)
    assert page.total_count == 0 and page.rows == 0 and page.app_ids == [] and page.start == -1


def test_package_items_replace_packagedetails():
    packages = sw.parse_package_items(load("getitems_packages.json"))
    assert packages[7877] == ss.PackageDetails(7877, [620], PriceQuote("TWD", 18800, 18800, 0))
    assert packages[36].app_ids == [220]
    assert packages[1187613] is None and packages[1187615] is None      # not public: same as success:false
    assert packages[17798].app_ids == [219780, 214170, 219760]           # a multi-game package
    # same contents and price as the store's packagedetails for the same package
    assert packages[7877] == ss.parse_package_details(load("packagedetails_7877.json"), 7877)


def test_getitems_regular_price():
    items = sw.parse_items(load("getitems.json"))
    assert items[620].regular_price_cents == 18800
