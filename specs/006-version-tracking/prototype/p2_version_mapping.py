"""P2: map each wishlist app's default package to an ITAD game and verify it with the extended rule (research R2).

Extended rule (spec FR-005): every alias must be app/N (or an alias app of N), or a sub whose contents are N plus
zero or more DLC whose parent is N. Prices come from the app's own purchase options in the same GetItems call
(a package item's best_purchase_option can be a bundle that contains it, e.g. Eternights): a sub that is currently
sold must have the default option's price; a sub that is not sold or not public only warns; bundle/... rejects.
Also: ITAD current Steam price of the version game (tracking status, FR-009). Read-only; writes out/p2.json.
"""
import json
import sqlite3
import time
from pathlib import Path

import httpx

from steamsage.config import load_secrets

OUT = Path(__file__).parent / "out"
H = {"ITAD-API-Key": load_secrets().itad_api_key.reveal()}
ITAD = "https://api.isthereanydeal.com"
CTX = {"language": "tchinese", "country_code": "TW", "steam_realm": 1}
p1b = {r["app_id"]: r for r in json.loads((OUT / "p1b.json").read_text(encoding="utf-8"))}
conn = sqlite3.connect("file:data/steamsage.db?mode=ro", uri=True)
own = {a: e for a, e in conn.execute(
    "SELECT app_id, external_id FROM source_mappings m WHERE source='itad' AND checked_at = "
    "(SELECT MAX(checked_at) FROM source_mappings m2 WHERE m2.app_id=m.app_id AND m2.source='itad')")}


def get_items(ids, key):
    out = {}
    for s in range(0, len(ids), 50):
        req = {"ids": [{key: i} for i in ids[s:s + 50]], "context": CTX, "data_request": {"include_basic_info": True}}
        r = httpx.get("https://api.steampowered.com/IStoreBrowseService/GetItems/v1/",
                      params={"input_json": json.dumps(req)}, timeout=60).json()
        for it in r["response"].get("store_items", []):
            out[it.get("appid") if key == "appid" else it.get("id")] = it
    return out


t0 = time.perf_counter()
apps = [a for a, r in p1b.items() if r["result"] == "unique"]
default = {a: p1b[a]["matches"][0] for a in apps}
ids = httpx.post(f"{ITAD}/lookup/id/shop/61/v1", json=[f"sub/{default[a]}" for a in apps], headers=H, timeout=60).json()
version = {a: ids.get(f"sub/{default[a]}") for a in apps}
games = sorted({g for g in version.values() if g})
aliases = httpx.post(f"{ITAD}/lookup/shop/61/id/v1", json=games, headers=H, timeout=60).json()
subs = sorted({int(x[4:]) for g in games for x in aliases.get(g) or [] if x.startswith("sub/")})
packages = get_items(subs, "packageid")
extra_apps = sorted({x for p in packages.values() for x in p.get("included_appids") or []} - set(apps))
app_items = get_items(extra_apps, "appid")
prices = httpx.post(f"{ITAD}/games/prices/v3", json=games, params={"country": "TW", "shops": 61, "deals": "false",
                    "vouchers": "false"}, headers=H, timeout=60).json()
steam_deals = {g["id"]: [d for d in g.get("deals") or [] if d["shop"]["id"] == 61] for g in prices}
elapsed = time.perf_counter() - t0

def app_options(ids):
    out = {}
    for s in range(0, len(ids), 50):
        req = {"ids": [{"appid": i} for i in ids[s:s + 50]], "context": CTX,
               "data_request": {"include_all_purchase_options": True}}
        r = httpx.get("https://api.steampowered.com/IStoreBrowseService/GetItems/v1/",
                      params={"input_json": json.dumps(req)}, timeout=60).json()
        for it in r["response"].get("store_items", []):
            out[it.get("appid")] = {o["packageid"]: (int(o.get("original_price_in_cents") or o["final_price_in_cents"]),
                                                     int(o["final_price_in_cents"]))
                                    for o in it.get("purchase_options", []) if o.get("packageid")}
    return out


options = app_options(apps)


def verify(app, game):
    warnings = []
    for alias in aliases.get(game) or []:
        kind, _, raw = alias.partition("/")
        if kind == "bundle":
            return "rejected", f"bundle:{raw}", warnings
        if kind == "app":
            if int(raw) != app:
                return "rejected", f"other-app:{raw}", warnings   # prototype: canonical-alias check skipped
            continue
        pkg = packages.get(int(raw))
        if not pkg or pkg.get("success") != 1:
            warnings.append(f"sub/{raw} 無法公開查詢")
            continue
        contents = pkg.get("included_appids") or []
        if app not in contents:
            return "rejected", f"sub-without-app:{raw}", warnings
        others = [x for x in contents if x != app]
        not_dlc = [x for x in others if (app_items.get(x) or {}).get("type") != 4
                   or ((app_items.get(x) or {}).get("related_items") or {}).get("parent_appid") != app]
        if not_dlc:
            return "rejected", f"other-games:{not_dlc}", warnings
        sold = options[app].get(int(raw))
        if sold is None:
            warnings.append(f"sub/{raw} 目前不在這款遊戲的購買選項中")
        elif sold != options[app][default[app]]:
            return "rejected", f"price:{raw}:{sold}!={options[app][default[app]]}", warnings
    return "verified", None, warnings


rows, summary = [], {}
for a in apps:
    g = version[a]
    if g is None:
        kind, verdict = "no-itad-game", None
    else:
        verdict = verify(a, g)
        kind = ("same-as-own" if g == own.get(a) else "different") + "/" + verdict[0]
    deals = steam_deals.get(g, []) if g else []
    row = {"app_id": a, "name": p1b[a]["name"], "package": default[a], "version_game": g, "own_game": own.get(a),
           "kind": kind, "verdict": verdict, "aliases": aliases.get(g), "itad_steam_deals": len(deals)}
    rows.append(row)
    summary[kind] = summary.get(kind, 0) + 1
    if not kind.startswith("same-as-own/verified") or len(deals) != 1:
        print(row)
print(summary)
print("ITAD Steam deals per version game:", {n: sum(1 for r in rows if r["itad_steam_deals"] == n) for n in (0, 1, 2, 3)})
print(f"elapsed {elapsed:.1f}s (lookup, aliases, {len(subs)} packages, {len(extra_apps)} extra apps, prices)")
(OUT / "p2.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
