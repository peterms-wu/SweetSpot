"""Offline: current bundle price vs buying separately (Steam now) vs sum of sweet prices."""
import gzip, json
from pathlib import Path
OUT = Path(__file__).parent / "out"
s1 = json.loads((OUT / "s1.json").read_text(encoding="utf-8"))
s2 = json.loads((OUT / "s2.json").read_text(encoding="utf-8"))
dec = {d["app_id"]: d for d in json.load(gzip.open("data/forecasts/20260927T023321Z.json.gz"))["decisions"]}
bopt = {it["id"]: it["best_purchase_option"] for it in s2["bundles"]["response"]["store_items"]}
apps = {it["appid"]: it for it in s2["apps"] if it.get("appid")}
def best(a):
    it = apps.get(a) or {}
    o = it.get("best_purchase_option") or {}
    return o, it.get("name"), it.get("type"), it.get("is_free")
res = {}
for bid, b in s1["multi"].items():
    o = bopt[int(bid)]
    fin, before, pct = int(o["final_price_in_cents"]), int(o.get("price_before_bundle_discount") or o["final_price_in_cents"]), o.get("bundle_discount_pct", 0)
    print(f"\n== bundle/{bid} {b['name']}  final NT${fin/100:.0f}  before-bundle-discount NT${before/100:.0f}  bundle -{pct}%  games {o.get('included_game_count')}")
    sep = 0; wl_now = 0; wl_sweet = 0; wl_reg = 0; rows = []
    for it in b["items"]:
        po, nm, ty, free = best(it["app_id"])
        f = int(po["final_price_in_cents"]) if po.get("final_price_in_cents") else None
        orig = int(po.get("original_price_in_cents") or f or 0) if f is not None else None
        sep += f or 0
        d = dec.get(it["app_id"])
        tag = "WL" if it["wishlist"] else ("WL-DLC" if it["parent_in_wishlist"] else ("DLC/other" if ty and ty != 0 else "other"))
        if d:
            wl_now += d["current"]["price_cents"]; wl_reg += d["regular_cents"]
            wl_sweet += d["sweet_cents"] if d.get("sweet_cents") is not None else 0
        rows.append((it["app_id"], tag, nm or it["name"], f, orig, po.get("discount_pct"), po.get("packageid"), d and d.get("sweet_cents"), d and d.get("sweet_point", {}) and d["sweet_point"].get("label"), d and d["current"]["price_cents"], d and d.get("group")))
        print(f"   {it['app_id']:>8} {tag:9} {(nm or it['name'] or '')[:28]:28} now {f and f/100}  orig {orig and orig/100}  -{po.get('discount_pct') or 0}%  sub {po.get('packageid')}  sweet {d and d.get('sweet_cents') and d['sweet_cents']/100} @ {d and d.get('sweet_point') and d['sweet_point'].get('label')}  group {d and d.get('group')}  cur(dec) {d and d['current']['price_cents']/100}")
    print(f"   sum separate(all contents)={sep/100:.0f}  wishlist-only now={wl_now/100:.0f}  wishlist regular={wl_reg/100:.0f}  wishlist sweet sum={wl_sweet/100:.0f}")
    res[bid] = {"final": fin, "before": before, "pct": pct, "sep_all": sep, "wl_now": wl_now, "wl_reg": wl_reg, "wl_sweet": wl_sweet, "rows": rows}
(OUT / "s3.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
