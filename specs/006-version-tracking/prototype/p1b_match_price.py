"""P1b: default purchase option = the package option whose price equals appdetails price_overview (research R1).

Both calls are batched: appdetails filters=price_overview (the daily current-price call, 50 per request) and
GetItems include_all_purchase_options (50 per request). Also checks GetItems package_groups 'default'.
"""
import json
import sqlite3
import time
from pathlib import Path

import httpx

OUT = Path(__file__).parent / "out"
conn = sqlite3.connect("file:data/steamsage.db?mode=ro", uri=True)
apps = [r[0] for r in conn.execute("SELECT app_id FROM wishlist_membership WHERE state='in_wishlist' ORDER BY app_id")]

t0 = time.perf_counter()
overview = {}
for start in range(0, len(apps), 50):
    batch = apps[start:start + 50]
    p = httpx.get("https://store.steampowered.com/api/appdetails",
                  params={"appids": ",".join(map(str, batch)), "cc": "tw", "filters": "price_overview"}, timeout=60).json()
    for a in batch:
        d = (p.get(str(a)) or {}).get("data")
        overview[a] = d.get("price_overview") if isinstance(d, dict) else None
t1 = time.perf_counter()
items = {}
for start in range(0, len(apps), 50):
    req = {"ids": [{"appid": a} for a in apps[start:start + 50]],
           "context": {"language": "tchinese", "country_code": "TW", "steam_realm": 1},
           "data_request": {"include_basic_info": True, "include_all_purchase_options": True}}
    r = httpx.get("https://api.steampowered.com/IStoreBrowseService/GetItems/v1/",
                  params={"input_json": json.dumps(req)}, timeout=60).json()
    for it in r["response"].get("store_items", []):
        items[it.get("appid") or it.get("id")] = it
t2 = time.perf_counter()

def price(o):
    final = int(o.get("final_price_in_cents") or 0)
    return int(o.get("original_price_in_cents") or final), final

stats = {"unique": 0, "none": 0, "multiple": 0, "no_overview": 0}
rows = []
for a in apps:
    it, po = items.get(a) or {}, overview.get(a)
    groups = it.get("package_groups") or []
    default_first = next((g["subs"][0]["packageid"] for g in groups if g.get("name") == "default" and g.get("subs")), None)
    if not po:
        stats["no_overview"] += 1
        rows.append({"app_id": a, "name": it.get("name"), "result": "no_overview"}); continue
    target = (po["initial"], po["final"])
    matches = [o["packageid"] for o in it.get("purchase_options", []) if o.get("packageid") and price(o) == target]
    kind = "unique" if len(matches) == 1 else ("none" if not matches else "multiple")
    stats[kind] += 1
    row = {"app_id": a, "name": it.get("name"), "result": kind, "matches": matches, "default_first": default_first,
           "agrees_with_default_group": default_first in matches if default_first else None}
    rows.append(row)
    if kind != "unique" or row["agrees_with_default_group"] is False:
        print(row, target, [(o.get("packageid"), o.get("bundleid"), price(o), o.get("purchase_option_name")) for o in it.get("purchase_options", [])][:5])
print(stats)
print("default group present:", sum(1 for r in rows if r.get("default_first")), "/", len(rows))
print(f"appdetails price_overview: {t1 - t0:.1f}s, GetItems: {t2 - t1:.1f}s")
(OUT / "p1b.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
