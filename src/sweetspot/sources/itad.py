"""IsThereAnyDeal API client (research R1). Steam is shop 61. Prices are kept unmodified (ITAD terms)."""

from datetime import datetime
from typing import Any

from sweetspot.sources import HistoryEntry, ItadPrice, PriceQuote
from sweetspot.sources.http import RateLimitedClient
from sweetspot.timeutil import itad_since, parse_iso

BASE = "https://api.isthereanydeal.com"
STEAM_SHOP = 61
BATCH = 200
MIN_INTERVAL = 0.4          # request spacing
WINDOW_LIMIT = 750          # of the documented 1000 per 5 minutes, leaving headroom
# Accounts without a verified email get a much smaller quota (observed: ~100 requests, then 429 with
# Retry-After ~250s). Waiting out one 5-minute window is acceptable for a daily run (FR-023).
MAX_RETRY_WAIT = 330


def _cents(money: Any) -> tuple[str | None, int | None]:
    if not isinstance(money, dict):
        return None, None
    amount = money.get("amountInt")
    return money.get("currency"), int(amount) if isinstance(amount, int) else None


def parse_history(payload: Any) -> list[HistoryEntry]:
    entries = []
    for row in payload if isinstance(payload, list) else []:
        if (row.get("shop") or {}).get("id") != STEAM_SHOP or not row.get("timestamp"):
            continue
        deal = row.get("deal") or {}
        currency, price = _cents(deal.get("price"))
        regular_currency, regular = _cents(deal.get("regular"))
        entries.append(HistoryEntry(
            observed_at=parse_iso(row["timestamp"]),
            raw_timestamp=row["timestamp"],
            currency=currency if currency == regular_currency else f"{currency}/{regular_currency}",
            price_cents=price,
            regular_cents=regular,
            cut_pct=deal.get("cut") if isinstance(deal.get("cut"), int) else None,
        ))
    return sorted(entries, key=lambda e: e.observed_at)


def parse_prices(payload: Any) -> dict[str, PriceQuote | None]:
    result: dict[str, PriceQuote | None] = {}
    for game in payload if isinstance(payload, list) else []:
        deals = [d for d in game.get("deals") or [] if (d.get("shop") or {}).get("id") == STEAM_SHOP]
        quote = None
        if len(deals) == 1:
            currency, price = _cents(deals[0].get("price"))
            _, regular = _cents(deals[0].get("regular"))
            if currency and price is not None and regular is not None:
                quote = PriceQuote(currency, regular, price, int(deals[0].get("cut") or 0))
        result[game.get("id")] = quote
    return result


def parse_price_summaries(payload: Any, requested: list[str]) -> dict[str, ItadPrice]:
    """Steam price count and (single) quote per requested product. ITAD leaves out products it has no price for,
    so a requested id missing from a valid response has 0 Steam prices; no valid response means unknown."""
    if not isinstance(payload, list):
        return {}
    quotes = parse_prices(payload)
    counts = {game.get("id"): sum(1 for d in game.get("deals") or [] if (d.get("shop") or {}).get("id") == STEAM_SHOP)
              for game in payload}
    return {i: ItadPrice(quotes.get(i), counts.get(i, 0)) for i in requested}


class ItadClient:
    """Implements HistorySource."""

    def __init__(self, http: RateLimitedClient, api_key: str):
        self.http = http
        self._headers = {"ITAD-API-Key": api_key}

    def _post(self, path: str, body: list, params: dict | None = None) -> Any:
        response = self.http.post(f"{BASE}{path}", json=body, params=params, headers=self._headers)
        return response.json() if response.status_code == 200 else None

    def lookup_steam(self, app_ids: list[int]) -> dict[int, str | None]:
        result: dict[int, str | None] = {}
        for start in range(0, len(app_ids), BATCH):
            batch = app_ids[start:start + BATCH]
            payload = self._post(f"/lookup/id/shop/{STEAM_SHOP}/v1", [f"app/{a}" for a in batch]) or {}
            result.update({a: payload.get(f"app/{a}") for a in batch})
        return result

    def lookup_packages(self, package_ids: list[int]) -> dict[int, str | None]:
        """ITAD product of each Steam package (feature 006)."""
        result: dict[int, str | None] = {}
        for start in range(0, len(package_ids), BATCH):
            batch = package_ids[start:start + BATCH]
            payload = self._post(f"/lookup/id/shop/{STEAM_SHOP}/v1", [f"sub/{p}" for p in batch]) or {}
            result.update({p: payload.get(f"sub/{p}") for p in batch})
        return result

    def lookup_ids(self, ids: list[tuple[str, int]]) -> dict[tuple[str, int], str | None]:
        """Implements OptionLookupSource (feature 009): `("sub", N)` and `("bundle", N)` in the same request."""
        result: dict[tuple[str, int], str | None] = {}
        for start in range(0, len(ids), BATCH):
            batch = ids[start:start + BATCH]
            payload = self._post(f"/lookup/id/shop/{STEAM_SHOP}/v1", [f"{kind}/{n}" for kind, n in batch]) or {}
            result.update({(kind, n): payload.get(f"{kind}/{n}") for kind, n in batch})
        return result

    def reverse_lookup(self, external_ids: list[str]) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for start in range(0, len(external_ids), BATCH):
            payload = self._post(f"/lookup/shop/{STEAM_SHOP}/id/v1", external_ids[start:start + BATCH]) or {}
            result.update({k: list(v or []) for k, v in payload.items()})
        return result

    def history(self, external_id: str, country: str, since: datetime) -> list[HistoryEntry]:
        response = self.http.get(f"{BASE}/games/history/v2", headers=self._headers, params={
            "id": external_id, "country": country, "shops": STEAM_SHOP, "since": itad_since(since)})
        return parse_history(response.json()) if response.status_code == 200 else []

    def current_prices(self, external_ids: list[str], country: str) -> dict[str, PriceQuote | None]:
        result: dict[str, PriceQuote | None] = {}
        for start in range(0, len(external_ids), BATCH):
            payload = self._post("/games/prices/v3", external_ids[start:start + BATCH],
                                 params={"country": country, "shops": STEAM_SHOP, "deals": "false",
                                         "vouchers": "false"})
            result.update(parse_prices(payload))
        return result

    def price_summaries(self, external_ids: list[str], country: str) -> dict[str, ItadPrice]:
        """Implements ItadPriceSource (feature 006): one request per 200 products, like current_prices."""
        result: dict[str, ItadPrice] = {}
        for start in range(0, len(external_ids), BATCH):
            batch = external_ids[start:start + BATCH]
            payload = self._post("/games/prices/v3", batch,
                                 params={"country": country, "shops": STEAM_SHOP, "deals": "false",
                                         "vouchers": "false"})
            result.update(parse_price_summaries(payload, batch))
        return result
