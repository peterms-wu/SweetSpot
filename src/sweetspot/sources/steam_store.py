"""Steam store endpoints (store.steampowered.com): current prices, app/package details, reviews."""

import re
from typing import Any

from sweetspot.products import is_indie, product_type  # noqa: F401  (re-exported)
from sweetspot.sources import (AppDetails, AppKind, BundleContents, CatalogPage, ContentPrice, ItemSummary,
                               PackageDetails, PriceLookup, PriceQuote, PurchaseOption, ReviewSummary, VersionPackage)
from sweetspot.sources.errors import SourceError
from sweetspot.sources.http import RateLimitedClient
from sweetspot.sources.steam_webapi import SteamWebApi
from sweetspot.timeutil import parse_steam_date

BASE = "https://store.steampowered.com"
PRICE_BATCH = 50


def _quote(price: Any) -> PriceQuote | None:
    if not isinstance(price, dict) or not {"currency", "initial", "final"} <= price.keys():
        return None
    return PriceQuote(currency=price["currency"], initial_cents=int(price["initial"]),
                      final_cents=int(price["final"]), discount_pct=int(price.get("discount_percent") or 0))


def parse_price_batch(payload: dict, app_ids: list[int]) -> dict[int, PriceLookup]:
    result = {}
    for app_id in app_ids:
        entry = payload.get(str(app_id)) or {}
        if not entry.get("success"):
            result[app_id] = PriceLookup(app_id, False, None)
            continue
        data = entry.get("data")
        result[app_id] = PriceLookup(app_id, True, _quote(data.get("price_overview")) if isinstance(data, dict)
                                     else None)
    return result


def parse_app_details(payload: dict, app_id: int) -> AppDetails | None:
    """Pick the entry whose data.steam_appid is the requested app; the outer key is unreliable."""
    for entry in payload.values():
        if not isinstance(entry, dict) or not entry.get("success"):
            continue
        data = entry.get("data") or {}
        if data.get("steam_appid") != app_id:
            continue
        fullgame = data.get("fullgame") or {}
        parent = int(fullgame["appid"]) if str(fullgame.get("appid", "")).isdigit() else None
        release = data.get("release_date") or {}
        return AppDetails(
            app_id=app_id,
            name=data.get("name"),
            type=data.get("type"),
            is_free=data.get("is_free"),
            coming_soon=release.get("coming_soon"),
            release_date=parse_steam_date(release.get("date")),
            publishers=[p for p in data.get("publishers") or [] if p],
            developers=[d for d in data.get("developers") or [] if d],
            genres=[{"id": str(g.get("id")), "description": g.get("description")} for g in data.get("genres") or []],
            parent_app_id=parent,
            package_ids=[int(p) for p in data.get("packages") or []],
            quote=_quote(data.get("price_overview")),
        )
    return None


def parse_canonical_app_id(payload: dict) -> int | None:
    """The steam_appid Steam actually returns for a requested app (aliases resolve to their main app)."""
    for entry in payload.values():
        if isinstance(entry, dict) and entry.get("success"):
            app_id = (entry.get("data") or {}).get("steam_appid")
            if isinstance(app_id, int):
                return app_id
    return None


def parse_review_summary(payload: dict) -> ReviewSummary | None:
    summary = payload.get("query_summary") if payload.get("success") in (1, True) else None
    if not summary or "total_reviews" not in summary:
        return None
    return ReviewSummary(total_reviews=int(summary["total_reviews"]),
                         total_positive=int(summary.get("total_positive") or 0))


def parse_package_details(payload: dict, package_id: int) -> PackageDetails | None:
    entry = payload.get(str(package_id)) or {}
    if not entry.get("success"):
        return None
    data = entry.get("data") or {}
    return PackageDetails(package_id=package_id, app_ids=[int(a["id"]) for a in data.get("apps") or []],
                          quote=_quote(data.get("price")))


_SEARCH_APPID = re.compile(r'data-ds-appid="(\d+)"')   # single-app results only; packages list several ids
_SEARCH_ROW = re.compile(r'class="search_result_row')


def parse_catalog_page(payload: dict, start: int) -> CatalogPage:
    """Store search page. total_count also counts package/bundle rows (no single app id); an empty result
    comes back as total_count 0 with start -1."""
    if not payload.get("success") or not isinstance(payload.get("total_count"), int):
        raise SourceError("steam-store: search response is not a valid result page")
    html = payload.get("results_html") or ""
    ids = [int(a) for a in _SEARCH_APPID.findall(html)]
    return CatalogPage(app_ids=list(dict.fromkeys(ids)), total_count=payload["total_count"],
                       start=int(payload.get("start", start)), rows=len(_SEARCH_ROW.findall(html)))


class SteamStore:
    """Implements CurrentPriceSource and MetadataSource for the Taiwan store."""

    def __init__(self, http: RateLimitedClient, webapi: SteamWebApi):
        self.http = http
        self.webapi = webapi

    def _get_json(self, path: str, params: dict) -> Any:
        response = self.http.get(f"{BASE}{path}", params=params)
        if response.status_code != 200:
            return None
        try:
            return response.json()
        except ValueError:
            return None

    def current_prices(self, app_ids: list[int]) -> dict[int, PriceLookup]:
        result: dict[int, PriceLookup] = {}
        for start in range(0, len(app_ids), PRICE_BATCH):
            batch = app_ids[start:start + PRICE_BATCH]
            payload = self._get_json("/api/appdetails", {"appids": ",".join(map(str, batch)), "cc": "tw",
                                                         "filters": "price_overview"})
            if isinstance(payload, dict):
                result.update(parse_price_batch(payload, batch))
        return result

    def app_details(self, app_id: int) -> AppDetails | None:
        payload = self._get_json("/api/appdetails", {"appids": app_id, "cc": "tw", "l": "tchinese"})
        return parse_app_details(payload, app_id) if isinstance(payload, dict) else None

    def canonical_app_id(self, app_id: int) -> int | None:
        payload = self._get_json("/api/appdetails", {"appids": app_id, "cc": "tw", "filters": "basic"})
        return parse_canonical_app_id(payload) if isinstance(payload, dict) else None

    def item_summaries(self, app_ids: list[int]) -> dict[int, ItemSummary]:
        return self.webapi.get_items(app_ids)

    def review_summary(self, app_id: int) -> ReviewSummary | None:
        payload = self._get_json(f"/appreviews/{app_id}", {"json": 1, "num_per_page": 0, "language": "all",
                                                           "purchase_type": "all"})
        return parse_review_summary(payload) if isinstance(payload, dict) else None

    def search_catalog(self, kind: str, name: str, start: int) -> CatalogPage:
        """One page (50) of games by publisher or developer. robots.txt allows /search/ (research R4)."""
        if kind not in ("publisher", "developer"):
            raise ValueError(kind)
        payload = self._get_json("/search/results/", {kind: name, "category1": 998, "count": 50, "start": start,
                                                      "infinite": 1, "cc": "tw", "l": "english"})
        if not isinstance(payload, dict):
            raise SourceError(f"steam-store: search failed for {kind} {name!r}")
        return parse_catalog_page(payload, start)

    def package_details_batch(self, package_ids: list[int]) -> dict[int, PackageDetails | None]:
        return self.webapi.package_details_batch(package_ids)

    # feature 006: VersionSource, answered by the batched Web API
    def purchase_options(self, app_ids: list[int]) -> dict[int, list[PurchaseOption]]:
        return self.webapi.purchase_options(app_ids)

    def version_packages(self, package_ids: list[int]) -> dict[int, VersionPackage]:
        return self.webapi.version_packages(package_ids)

    def app_kinds(self, app_ids: list[int]) -> dict[int, AppKind]:
        return self.webapi.app_kinds(app_ids)

    def bundle_contents(self, bundle_ids: list[int]) -> dict[int, BundleContents]:
        return self.webapi.bundle_contents(bundle_ids)

    # feature 010: ContentPriceSource
    def content_prices(self, app_ids: list[int]) -> dict[int, ContentPrice]:
        return self.webapi.content_prices(app_ids)

    def package_details(self, package_id: int) -> PackageDetails | None:
        payload = self._get_json("/api/packagedetails", {"packageids": package_id, "cc": "tw"})
        return parse_package_details(payload, package_id) if isinstance(payload, dict) else None
