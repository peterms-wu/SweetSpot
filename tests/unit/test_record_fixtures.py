"""014 T018: what the fixture recorder writes never brings back the wishlist order, dates or NSFW games, nor the
publisher catalog titles (FR-008a; research R9, R10). Network and files are fakes."""

import importlib.util
import json
import re
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("record_fixtures", ROOT / "scripts" / "record_fixtures.py")
rf = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rf)

_SCAN = importlib.util.spec_from_file_location("scan_personal", ROOT / "scripts" / "scan_personal.py")
scan_personal = importlib.util.module_from_spec(_SCAN)
_SCAN.loader.exec_module(scan_personal)

WISHLIST = {"response": {"items": [{"appid": a, "priority": 50 - i, "date_added": 1770000000 + 977 * i}
                                   for i, a in enumerate([10, 20, 30, 40, 50, 60, 70, 80])]}}
CATALOG_ROW = ('<a href="https://store.steampowered.com/app/{id}/Some_Real_Title/?snr=1" data-ds-appid="{id}" '
               'data-ds-itemkey="App_{id}" onmouseover="GameHover( this, event, \'global_hover\', '
               '{{&quot;type&quot;:&quot;app&quot;,&quot;id&quot;:{id},&quot;public&quot;:1}} );" '
               'class="search_result_row"><div class="search_capsule"><img src="https://shared.akamai.steamstatic.com/'
               'store_item_assets/steam/apps/{id}/capsule_sm_120.jpg?t=1"></div>'
               '<span class="title">Real Title {id}</span></a>')


def catalog(ids, total=3):
    return {"success": 1, "results_html": "\n".join(CATALOG_ROW.format(id=i) for i in ids), "total_count": total,
            "start": 0}


def test_wishlist_is_cut_and_its_order_and_dates_are_fictional():
    out = rf.anonymize_wishlist(WISHLIST, keep=3, nsfw={30})
    items = out["response"]["items"]
    assert [i["appid"] for i in items] == [10, 20, 40]                 # 30 left out, only 3 kept
    assert [i["priority"] for i in items] == [1, 2, 3]
    real_dates = {i["date_added"] for i in WISHLIST["response"]["items"]}
    assert not {i["date_added"] for i in items} & real_dates
    assert len({i["date_added"] for i in items}) == 3


def test_a_private_or_odd_answer_is_kept_as_it_is():
    assert rf.anonymize_wishlist({"response": {}}, keep=3, nsfw=set()) == {"response": {}}


def test_catalog_titles_ids_links_and_images_become_fictional():
    real_ids = [3883290, 1066630, 1149550]
    out = rf.fictional_catalog(catalog(real_ids), offset=0)
    html = out["results_html"]
    for real in real_ids:
        assert str(real) not in html
    assert "Real Title" not in html and "Some_Real_Title" not in html
    ids = [int(x) for x in re.findall(r'data-ds-appid="(\d+)"', html)]
    assert len(ids) == 3 and all(i % 10 != 0 for i in ids)            # never a real app id (multiples of 10)
    assert re.findall(r'<span class="title">([^<]+)</span>', html) == ["範例作品 001", "範例作品 002", "範例作品 003"]
    assert out["total_count"] == 3


def test_catalog_numbering_continues_across_pages():
    second = rf.fictional_catalog(catalog([1, 2], total=4), offset=2)["results_html"]
    assert "範例作品 003" in second and "範例作品 004" in second
    first = rf.fictional_catalog(catalog([5, 6], total=4), offset=0)["results_html"]
    assert set(re.findall(r'data-ds-appid="(\d+)"', first)).isdisjoint(re.findall(r'data-ds-appid="(\d+)"', second))


def test_the_catalog_still_parses():
    from sweetspot.sources import steam_store as ss

    page = ss.parse_catalog_page(rf.fictional_catalog(catalog([3883290, 1066630, 1149550]), offset=0), 0)
    assert len(page.app_ids) == 3 and page.total_count == 3


def test_recording_writes_only_the_anonymized_wishlist(tmp_path, monkeypatch):
    def handler(request):
        if "GetWishlist" in request.url.path:
            return httpx.Response(200, json=WISHLIST)
        if "GetItems" in request.url.path:
            ids = [i["appid"] for i in json.loads(request.url.params["input_json"])["ids"]]
            return httpx.Response(200, json={"response": {"store_items": [
                {"appid": a, "success": 1, "content_descriptorids": [3] if a == 20 else [1, 5]} for a in ids]}})
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(rf, "FIXTURES", tmp_path)
    monkeypatch.setattr(rf.time, "sleep", lambda s: None)
    monkeypatch.setattr(rf, "_secrets", lambda: [])
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        rf.record_wishlist(client, steamid="76561197960265728")
    saved = json.loads((tmp_path / "steam" / "wishlist_ok.json").read_text(encoding="utf-8"))
    items = saved["response"]["items"]
    assert 20 not in [i["appid"] for i in items] and len(items) == rf.WISHLIST_KEEP
    text = (tmp_path / "steam" / "wishlist_ok.json").read_text(encoding="utf-8")
    result = scan_personal.scan([("tests/fixtures/steam/wishlist_ok.json", text)], owners=set())
    assert result.unallowed == []


def test_the_recorder_holds_no_steamid():
    text = (ROOT / "scripts" / "record_fixtures.py").read_text(encoding="utf-8")
    assert not re.search(r"7656119\d{10}", text)
