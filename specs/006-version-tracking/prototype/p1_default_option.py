"""P1: which package is the Steam default purchase option, and can one batched call tell? (research R1)

Compares, for every wishlist app:
  A. GetItems best_purchase_option.packageid (batched, 50 per request)
  B. store appdetails: first sub of the 'default' package group (one request per app, saved by the earlier probe)
  C. appdetails price_overview (initial/final) vs A's prices
Read-only; writes prototype/out/p1.json.
"""
import json
import sqlite3
import sys
import time
from pathlib import Path

import httpx

OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)
probe = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["res"]   # appdetails probe (default group subs)

conn = sqlite3.connect("file:data/steamsage.db?mode=ro", uri=True)
apps = [r[0] for r in conn.execute("SELECT app_id FROM wishlist_membership WHERE state='in_wishlist' ORDER BY app_id")]

t0 = time.perf_counter()
items = {}
for start in range(0, len(apps), 50):
    req = {"ids": [{"appid": a} for a in apps[start:start + 50]],
           "context": {"language": "tchinese", "country_code": "TW", "steam_realm": 1},
           "data_request": {"include_basic_info": True, "include_all_purchase_options": True}}
    r = httpx.get("https://api.steampowered.com/IStoreBrowseService/GetItems/v1/",
                  params={"input_json": json.dumps(req)}, timeout=60)
    for it in r.json()["response"].get("store_items", []):
        items[it.get("appid") or it.get("id")] = it
elapsed = time.perf_counter() - t0

rows, agree, differ, missing = [], 0, [], []
for a in apps:
    it = items.get(a) or {}
    best = it.get("best_purchase_option") or {}
    a_pkg = best.get("packageid")
    p = probe.get(str(a))
    b_pkg = p[2][0] if p and p[2] else None
    single = [o for o in it.get("purchase_options", []) if o.get("packageid") and o.get("included_game_count") == 1]
    row = {"app_id": a, "name": it.get("name"), "best_package": a_pkg, "best_bundle": best.get("bundleid"),
           "best_games": best.get("included_game_count"), "default_group_first": b_pkg,
           "n_single_game_packages": len(single), "appdetails_initial": p[3] if p else None,
           "best_original": int(best.get("original_price_in_cents") or best.get("final_price_in_cents") or 0) or None}
    rows.append(row)
    if a_pkg is None and b_pkg is None:
        missing.append(row)
    elif a_pkg == b_pkg:
        agree += 1
    else:
        differ.append(row)

print(f"GetItems for {len(apps)} apps: {elapsed:.1f}s")
print(f"best_purchase_option == default group first sub: {agree}; differ: {len(differ)}; neither: {len(missing)}")
for r in differ + missing:
    print("  ", r)
(OUT / "p1.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
