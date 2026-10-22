"""Steam Web API (api.steampowered.com): wishlist, batched store items, full app list."""

import json
from datetime import UTC, datetime
from typing import Any

from sweetspot.sources import (AppKind, AppListPage, BundleContents, ContentPrice, ItemSummary, PackageDetails,
                               PriceQuote, PurchaseOption, VersionPackage, WishlistEntry, WishlistFetchError)
from sweetspot.sources.http import RateLimited, RateLimitedClient, SourceDisabled, SourceError

BASE = "https://api.steampowered.com"
ITEMS_BATCH = 50


def parse_wishlist(payload: Any) -> list[WishlistEntry]:
    """A missing 'items' key means private/unavailable; an explicit empty list is a real empty wishlist."""
    if not isinstance(payload, dict) or not isinstance(payload.get("response"), dict):
        raise WishlistFetchError("malformed", "wishlist response has no 'response' object")
    response = payload["response"]
    if "items" not in response:
        raise WishlistFetchError("private", "wishlist is private or unavailable")
    items = response["items"]
    if not isinstance(items, list):
        raise WishlistFetchError("malformed", "wishlist 'items' is not a list")
    entries = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("appid"), int):
            raise WishlistFetchError("malformed", f"wishlist item without appid: {item!r}")
        added = item.get("date_added")
        entries.append(WishlistEntry(
            app_id=item["appid"],
            priority=item.get("priority"),
            date_added=datetime.fromtimestamp(added, UTC) if isinstance(added, int) and added > 0 else None,
        ))
    return entries


def parse_items(payload: Any) -> dict[int, ItemSummary]:
    result = {}
    for item in (payload.get("response") or {}).get("store_items") or []:
        app_id = item.get("appid")
        if item.get("success") != 1 or not isinstance(app_id, int):
            continue
        reviews = (item.get("reviews") or {}).get("summary_filtered") or {}
        release = item.get("release") or {}
        stamp = release.get("steam_release_date")
        option = item.get("best_purchase_option") or {}
        regular = option.get("original_price_in_cents") or option.get("final_price_in_cents")
        result[app_id] = ItemSummary(
            app_id=app_id,
            name=item.get("name"),
            # GetItems omits the summary when a game has no reviews at all.
            review_count_filtered=reviews.get("review_count", 0) if item.get("reviews") is not None else None,
            percent_positive=reviews.get("percent_positive"),
            tag_ids=[int(t) for t in item.get("tagids") or []],
            app_type=item.get("type") if isinstance(item.get("type"), int) else None,
            is_free=item.get("is_free"),
            release_date=datetime.fromtimestamp(stamp, UTC).date() if isinstance(stamp, int) and stamp > 0 else None,
            coming_soon=release.get("is_coming_soon"),
            regular_price_cents=int(regular) if regular is not None else None,
        )
    return result


def parse_package_items(payload: Any) -> dict[int, PackageDetails | None]:
    """GetItems for package ids: contents and TW price. Unknown or non-public packages come back with
    success != 1 and map to None, like store packagedetails' success:false."""
    result: dict[int, PackageDetails | None] = {}
    for item in (payload.get("response") or {}).get("store_items") or []:
        package_id = item.get("id")
        if not isinstance(package_id, int):
            continue
        if item.get("success") != 1:
            result[package_id] = None
            continue
        option = item.get("best_purchase_option") or {}
        final = option.get("final_price_in_cents")
        quote = None
        if final is not None:
            original = option.get("original_price_in_cents") or final
            quote = PriceQuote("TWD", int(original), int(final), int(option.get("discount_pct") or 0))
        result[package_id] = PackageDetails(package_id, [int(a) for a in item.get("included_appids") or []], quote)
    return result


def _store_items(payload: Any) -> list[dict]:
    return [i for i in ((payload or {}).get("response") or {}).get("store_items") or [] if isinstance(i, dict)]


def parse_purchase_options(payload: Any) -> dict[int, list[PurchaseOption]]:
    """GetItems include_all_purchase_options for apps (feature 006): every package and bundle, in store order."""
    result: dict[int, list[PurchaseOption]] = {}
    for item in _store_items(payload):
        app_id = item.get("appid")
        if item.get("success") != 1 or not isinstance(app_id, int):
            continue
        options = []
        for option in item.get("purchase_options") or []:
            final = option.get("final_price_in_cents")
            if final is None:
                continue
            original = option.get("original_price_in_cents") or final
            package, bundle = option.get("packageid"), option.get("bundleid")
            before = option.get("price_before_bundle_discount") if bundle else None
            discount = option.get("bundle_discount_pct") if bundle else None
            options.append(PurchaseOption(int(package) if package else None, int(bundle) if bundle else None,
                                          option.get("purchase_option_name"), int(original), int(final),
                                          int(discount) if isinstance(discount, int) else None,
                                          int(before) if before is not None else None))
        result[app_id] = options
    return result


def parse_version_packages(payload: Any) -> dict[int, VersionPackage]:
    """GetItems for package ids: contents; packages the store does not describe are not public."""
    result: dict[int, VersionPackage] = {}
    for item in _store_items(payload):
        package_id = item.get("id")
        if not isinstance(package_id, int):
            continue
        public = item.get("success") == 1
        result[package_id] = VersionPackage(package_id, public,
                                            [int(a) for a in item.get("included_appids") or []] if public else [],
                                            item.get("name"))
    return result


def parse_bundle_contents(payload: Any) -> dict[int, BundleContents]:
    """GetItems for bundle ids (feature 009): the apps of each bundle; a bundle the store does not describe has
    unknown contents."""
    result: dict[int, BundleContents] = {}
    for item in _store_items(payload):
        bundle_id = item.get("id")
        if not isinstance(bundle_id, int):
            continue
        found = item.get("success") == 1
        result[bundle_id] = BundleContents(bundle_id, found,
                                           [int(a) for a in item.get("included_appids") or []] if found else [],
                                           item.get("name") if found else None)
    return result


def parse_content_prices(payload: Any) -> dict[int, ContentPrice]:
    """GetItems for apps (feature 010): the best purchase option's price and the name; apps the store does not
    describe are left out (unknown)."""
    result: dict[int, ContentPrice] = {}
    for item in _store_items(payload):
        app_id = item.get("appid")
        if item.get("success") != 1 or not isinstance(app_id, int):
            continue
        final = (item.get("best_purchase_option") or {}).get("final_price_in_cents")
        result[app_id] = ContentPrice(app_id, int(final) if final is not None else None, item.get("name") or None)
    return result


def parse_app_kinds(payload: Any) -> dict[int, AppKind]:
    result: dict[int, AppKind] = {}
    for item in _store_items(payload):
        app_id = item.get("appid")
        if item.get("success") != 1 or not isinstance(app_id, int):
            continue
        parent = (item.get("related_items") or {}).get("parent_appid")
        result[app_id] = AppKind(app_id, item.get("type") if isinstance(item.get("type"), int) else None,
                                 int(parent) if parent else None)
    return result


def parse_app_list(payload: Any) -> AppListPage:
    response = (payload or {}).get("response") or {}
    apps = [(int(a["appid"]), a.get("name") or "", a.get("last_modified"))
            for a in response.get("apps") or [] if isinstance(a.get("appid"), int)]
    return AppListPage(apps=apps, have_more=bool(response.get("have_more_results")),
                       last_appid=response.get("last_appid"))


class SteamWebApi:
    def __init__(self, http: RateLimitedClient, api_key: str | None = None):
        self.http = http
        self.api_key = api_key

    def get_wishlist(self, steamid: str) -> list[WishlistEntry]:
        try:
            response = self.http.get(f"{BASE}/IWishlistService/GetWishlist/v1/", params={"steamid": steamid})
        except RateLimited as exc:
            raise WishlistFetchError("rate-limited", str(exc)) from None
        except SourceDisabled as exc:
            raise WishlistFetchError("private", str(exc)) from None
        except SourceError as exc:
            reason = "rate-limited" if "429" in str(exc) else "network"
            raise WishlistFetchError(reason, str(exc)) from None
        if response.status_code != 200:
            raise WishlistFetchError("network", f"HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError:
            raise WishlistFetchError("malformed", "wishlist response is not JSON") from None
        return parse_wishlist(payload)

    def get_items(self, app_ids: list[int]) -> dict[int, ItemSummary]:
        result: dict[int, ItemSummary] = {}
        for start in range(0, len(app_ids), ITEMS_BATCH):
            request = {
                "ids": [{"appid": a} for a in app_ids[start:start + ITEMS_BATCH]],
                "context": {"language": "tchinese", "country_code": "TW", "steam_realm": 1},
                "data_request": {"include_basic_info": True, "include_release": True, "include_reviews": True,
                                 "include_tag_count": 20},
            }
            response = self.http.get(f"{BASE}/IStoreBrowseService/GetItems/v1/",
                                     params={"input_json": json.dumps(request)})
            if response.status_code == 200:
                result.update(parse_items(response.json()))
        return result

    def package_details_batch(self, package_ids: list[int]) -> dict[int, PackageDetails | None]:
        """Package contents and prices, 50 per request (replaces one store packagedetails call per package)."""
        result: dict[int, PackageDetails | None] = {}
        for start in range(0, len(package_ids), ITEMS_BATCH):
            batch = package_ids[start:start + ITEMS_BATCH]
            request = {"ids": [{"packageid": p} for p in batch],
                       "context": {"language": "tchinese", "country_code": "TW", "steam_realm": 1},
                       "data_request": {"include_basic_info": True}}
            response = self.http.get(f"{BASE}/IStoreBrowseService/GetItems/v1/",
                                     params={"input_json": json.dumps(request)})
            if response.status_code != 200:
                raise SourceError(f"steam-webapi: GetItems (packages) HTTP {response.status_code}")
            result.update(parse_package_items(response.json()))
        return result

    # --- feature 006: VersionSource ------------------------------------------------------------------------

    def _get_items(self, ids: list[dict], data_request: dict, what: str) -> list[dict]:
        request = {"ids": ids, "context": {"language": "tchinese", "country_code": "TW", "steam_realm": 1},
                   "data_request": data_request}
        response = self.http.get(f"{BASE}/IStoreBrowseService/GetItems/v1/", params={"input_json": json.dumps(request)})
        if response.status_code != 200:
            raise SourceError(f"steam-webapi: GetItems ({what}) HTTP {response.status_code}")
        return response.json()

    def purchase_options(self, app_ids: list[int]) -> dict[int, list[PurchaseOption]]:
        result: dict[int, list[PurchaseOption]] = {}
        for start in range(0, len(app_ids), ITEMS_BATCH):
            payload = self._get_items([{"appid": a} for a in app_ids[start:start + ITEMS_BATCH]],
                                      {"include_all_purchase_options": True}, "purchase options")
            result.update(parse_purchase_options(payload))
        return result

    def version_packages(self, package_ids: list[int]) -> dict[int, VersionPackage]:
        result: dict[int, VersionPackage] = {}
        for start in range(0, len(package_ids), ITEMS_BATCH):
            payload = self._get_items([{"packageid": p} for p in package_ids[start:start + ITEMS_BATCH]],
                                      {"include_basic_info": False}, "packages")
            result.update(parse_version_packages(payload))
        return result

    def bundle_contents(self, bundle_ids: list[int]) -> dict[int, BundleContents]:
        """Implements BundleSource (feature 009)."""
        result: dict[int, BundleContents] = {}
        for start in range(0, len(bundle_ids), ITEMS_BATCH):
            payload = self._get_items([{"bundleid": b} for b in bundle_ids[start:start + ITEMS_BATCH]],
                                      {"include_basic_info": False}, "bundles")
            result.update(parse_bundle_contents(payload))
        return result

    def content_prices(self, app_ids: list[int]) -> dict[int, ContentPrice]:
        """Implements ContentPriceSource (feature 010)."""
        result: dict[int, ContentPrice] = {}
        for start in range(0, len(app_ids), ITEMS_BATCH):
            payload = self._get_items([{"appid": a} for a in app_ids[start:start + ITEMS_BATCH]],
                                      {"include_basic_info": True}, "content prices")
            result.update(parse_content_prices(payload))
        return result

    def app_kinds(self, app_ids: list[int]) -> dict[int, AppKind]:
        result: dict[int, AppKind] = {}
        for start in range(0, len(app_ids), ITEMS_BATCH):
            payload = self._get_items([{"appid": a} for a in app_ids[start:start + ITEMS_BATCH]],
                                      {"include_basic_info": False}, "app kinds")
            result.update(parse_app_kinds(payload))
        return result

    def app_list(self, last_appid: int | None, max_results: int) -> AppListPage:
        """Full store app list (games only). Requires a Steam Web API key (research R3)."""
        if not self.api_key:
            raise SourceDisabled("steam-webapi: STEAM_WEB_API_KEY is not set")
        params: dict[str, Any] = {"key": self.api_key, "include_games": "true", "include_dlc": "false",
                                  "include_software": "false", "include_videos": "false",
                                  "include_hardware": "false", "max_results": max_results}
        if last_appid:
            params["last_appid"] = last_appid
        response = self.http.get(f"{BASE}/IStoreService/GetAppList/v1/", params=params)
        if response.status_code != 200:
            raise SourceError(f"steam-webapi: GetAppList HTTP {response.status_code}")
        return parse_app_list(response.json())
