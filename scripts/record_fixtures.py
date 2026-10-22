"""Record real API responses into tests/fixtures/ (run manually; not part of the test suite).

Usage: uv run python scripts/record_fixtures.py steam|itad|reference

API keys are read from the environment only and are scrubbed from anything written to disk.
The wishlist comes from your own sweetspot.toml; what is written keeps only a few games, with a fictional order
and dates and no game Steam marks as adult or frequent sexual content, and the publisher catalog gets fictional
titles and app ids (feature 014 FR-008a): the fixtures are published.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
UA = {"User-Agent": "SweetSpot/0.1.0 (personal, non-commercial; fixture recorder)"}
SAMPLE_APPS = [620, 413150, 1145360]
WISHLIST_KEEP = 5                      # wishlist games kept in the fixture (014 FR-008)
NSFW = {3, 4}                          # Steam content descriptors: adult only / frequent sexual content
PUBLISHER = "Devolver Digital"         # a catalog that pages (> 100 games); its titles are replaced anyway
FICTIONAL_APP = 9_000_007              # catalog app ids: 9000007 + 10 k, never a multiple of 10 like real ones


def _secrets() -> list[str]:
    values = [os.environ.get(n, "") for n in ("ITAD_API_KEY", "STEAM_WEB_API_KEY")]
    if sys.platform == "win32":
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            for name in ("ITAD_API_KEY", "STEAM_WEB_API_KEY"):
                try:
                    values.append(winreg.QueryValueEx(key, name)[0])
                except OSError:
                    pass
    return [v for v in values if v]


def own_steamid() -> str:
    """From your own settings file; nothing personal is written in this script (014)."""
    sys.path.insert(0, str(ROOT / "src"))
    from sweetspot.config import load_config

    return load_config(ROOT / "sweetspot.toml")[0].steamid


def content_descriptors(client: httpx.Client, app_ids: list[int]) -> dict[int, set[int]]:
    """Steam content descriptor ids per app (public GetItems, 100 per request)."""
    found: dict[int, set[int]] = {}
    for start in range(0, len(app_ids), 100):
        body = {"ids": [{"appid": a} for a in app_ids[start:start + 100]],
                "context": {"language": "tchinese", "country_code": "TW"}, "data_request": {"include_basic_info": True}}
        response = client.get("https://api.steampowered.com/IStoreBrowseService/GetItems/v1/",
                              params={"input_json": json.dumps(body)})
        response.raise_for_status()
        for item in response.json().get("response", {}).get("store_items", []):
            found[int(item.get("appid") or item.get("id"))] = set(item.get("content_descriptorids") or [])
        time.sleep(1.5)
    return found


def anonymize_wishlist(payload: dict, *, keep: int, nsfw: set[int]) -> dict:
    """The first `keep` games that are not in `nsfw`, ranked 1..keep, with fictional dates a day apart."""
    items = (payload.get("response") or {}).get("items")
    if not isinstance(items, list):
        return payload
    kept = [i for i in items if i.get("appid") not in nsfw][:keep]
    return {"response": {"items": [{"appid": i["appid"], "priority": n, "date_added": 1700000000 + 86400 * n}
                                   for n, i in enumerate(kept, 1)]}}


_ROW = re.compile(r'data-ds-appid="(\d+)"')


def fictional_catalog(payload: dict, *, offset: int) -> dict:
    """The same number of app rows, each with a fictional id and title; total_count and start unchanged."""
    rows = []
    for n, _ in enumerate(_ROW.findall(payload.get("results_html") or ""), offset + 1):
        app = FICTIONAL_APP + 10 * (n - 1)
        rows.append(f'<a href="https://store.steampowered.com/app/{app}/Example_{n:03d}/" data-ds-appid="{app}" '
                    f'data-ds-itemkey="App_{app}" class="search_result_row"><div class="search_name ellipsis">'
                    f'<span class="title">範例作品 {n:03d}</span></div></a>')
    return {**payload, "results_html": "\n".join(rows)}


def save_data(relpath: str, data: dict) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=1)
    for secret in _secrets():
        if secret in text:
            raise SystemExit(f"refusing to write {relpath}: it contains an API key")
    path = FIXTURES / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"-> tests/fixtures/{relpath}")


def record_wishlist(client: httpx.Client, *, steamid: str) -> None:
    payload = client.get("https://api.steampowered.com/IWishlistService/GetWishlist/v1/",
                         params={"steamid": steamid}).json()
    ids = [i["appid"] for i in (payload.get("response") or {}).get("items") or []]
    nsfw = {a for a, d in content_descriptors(client, ids).items() if d & NSFW}
    save_data("steam/wishlist_ok.json", anonymize_wishlist(payload, keep=WISHLIST_KEEP, nsfw=nsfw))


def save(relpath: str, response: httpx.Response) -> None:
    text = response.text
    for secret in _secrets():
        if secret in text:
            raise SystemExit(f"refusing to write {relpath}: response contains an API key")
    path = FIXTURES / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(response.json(), ensure_ascii=False, indent=1), encoding="utf-8")
    except ValueError:
        path.write_text(text, encoding="utf-8")
    print(f"{response.status_code} -> {path.relative_to(ROOT)}")
    time.sleep(1.5)


def record_steam(client: httpx.Client) -> None:
    record_wishlist(client, steamid=own_steamid())
    save("steam/appdetails_prices.json",
         client.get("https://store.steampowered.com/api/appdetails",
                    params={"appids": ",".join(map(str, SAMPLE_APPS)), "cc": "tw", "filters": "price_overview"}))
    for app in (620, 323180):
        save(f"steam/appdetails_{app}.json",
             client.get("https://store.steampowered.com/api/appdetails",
                        params={"appids": app, "cc": "tw", "l": "tchinese"}))
    save("steam/appdetails_missing.json",
         client.get("https://store.steampowered.com/api/appdetails", params={"appids": 1, "cc": "tw"}))
    items = {"ids": [{"appid": a} for a in SAMPLE_APPS],
             "context": {"language": "tchinese", "country_code": "TW", "steam_realm": 1},
             "data_request": {"include_basic_info": True, "include_release": True, "include_reviews": True,
                              "include_tag_count": 20}}
    save("steam/getitems.json",
         client.get("https://api.steampowered.com/IStoreBrowseService/GetItems/v1/",
                    params={"input_json": json.dumps(items)}))
    save("steam/appreviews_620.json",
         client.get("https://store.steampowered.com/appreviews/620",
                    params={"json": 1, "num_per_page": 0, "language": "all", "purchase_type": "all"}))
    save("steam/packagedetails_7877.json",
         client.get("https://store.steampowered.com/api/packagedetails", params={"packageids": 7877, "cc": "tw"}))


def _itad_key() -> str:
    key = os.environ.get("ITAD_API_KEY")
    if not key and sys.platform == "win32":
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as reg:
            key = winreg.QueryValueEx(reg, "ITAD_API_KEY")[0]
    if not key:
        raise SystemExit("ITAD_API_KEY is not set")
    return key


def record_itad(client: httpx.Client) -> None:
    base = "https://api.isthereanydeal.com"
    client.headers["ITAD-API-Key"] = _itad_key()
    apps = [620, 413150, 1145360, 220]
    lookup = client.post(f"{base}/lookup/id/shop/61/v1", json=[f"app/{a}" for a in apps])
    save("itad/lookup.json", lookup)
    ids = {int(k.split("/")[1]): v for k, v in lookup.json().items() if v}
    reverse = client.post(f"{base}/lookup/shop/61/id/v1", json=list(ids.values()))
    save("itad/reverse_lookup.json", reverse)
    for app in (620, 220):
        for country in ("TW", "US"):
            save(f"itad/history_{app}_{country}.json",
                 client.get(f"{base}/games/history/v2", params={"id": ids[app], "country": country, "shops": 61,
                                                                 "since": "2010-01-01T00:00:00Z"}))
    save("itad/prices_tw.json",
         client.post(f"{base}/games/prices/v3", params={"country": "TW", "shops": 61, "deals": "false",
                                                         "vouchers": "false"}, json=list(ids.values())))
    del client.headers["ITAD-API-Key"]
    subs = {int(s.split("/")[1]) for s in reverse.json().get(ids[220], []) if s.startswith("sub/")}
    for sub in sorted(subs):
        save(f"steam/packagedetails_{sub}.json",
             client.get("https://store.steampowered.com/api/packagedetails", params={"packageids": sub, "cc": "tw"}))
    for app in (220, 659):
        save(f"steam/appdetails_{app}.json",
             client.get("https://store.steampowered.com/api/appdetails", params={"appids": app, "cc": "tw",
                                                                                   "l": "tchinese"}))


def _steam_key() -> str:
    key = os.environ.get("STEAM_WEB_API_KEY")
    if not key and sys.platform == "win32":
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as reg:
            key = winreg.QueryValueEx(reg, "STEAM_WEB_API_KEY")[0]
    if not key:
        raise SystemExit("STEAM_WEB_API_KEY is not set")
    return key


def record_reference(client: httpx.Client) -> None:
    search = "https://store.steampowered.com/search/results/"
    for start in (0, 50, 100):
        page = client.get(search, params={"publisher": PUBLISHER, "category1": 998, "count": 50, "start": start,
                                          "infinite": 1, "cc": "tw", "l": "english"}).json()
        save_data(f"steam/search_publisher_{start}.json", fictional_catalog(page, offset=start))
        time.sleep(1.5)
    response = client.get("https://api.steampowered.com/IStoreService/GetAppList/v1/",
                          params={"key": _steam_key(), "include_games": "true", "include_dlc": "false",
                                  "max_results": 5})
    save("steam/applist_page1.json", response)
    last = response.json()["response"].get("last_appid")
    save("steam/applist_page2.json",
         client.get("https://api.steampowered.com/IStoreService/GetAppList/v1/",
                    params={"key": _steam_key(), "include_games": "true", "include_dlc": "false",
                            "max_results": 5, "last_appid": last}))


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else "steam"
    with httpx.Client(headers=UA, timeout=30) as client:
        if target == "steam":
            record_steam(client)
        elif target == "itad":
            record_itad(client)
        elif target == "reference":
            record_reference(client)
        else:
            raise SystemExit(f"unknown target {target}")


if __name__ == "__main__":
    main()
