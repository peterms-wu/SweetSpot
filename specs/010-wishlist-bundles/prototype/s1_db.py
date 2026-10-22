"""Read-only: latest purchase_options bundles with other games; wishlist apps inside."""
import json, sqlite3
from pathlib import Path
OUT = Path(__file__).parent / "out"; OUT.mkdir(exist_ok=True)
c = sqlite3.connect("file:data/steamsage.db?mode=ro", uri=True)
wl = {a for (a,) in c.execute("SELECT app_id FROM wishlist_membership WHERE state='in_wishlist'")}
last = c.execute("SELECT MAX(checked_at) FROM purchase_options").fetchone()[0]
rows = c.execute("SELECT app_id, option_id, name, original_cents, final_cents, contents_json, role FROM purchase_options "
                 "WHERE checked_at=? AND kind='bundle'", (last,)).fetchall()
by = {}
for app, bid, name, o, f, cj, role in rows:
    b = by.setdefault(bid, {"name": name, "original": o, "final": f, "contents": json.loads(cj or "[]"), "seen_from": [], "roles": set()})
    b["seen_from"].append(app); b["roles"].add(role)
def name_of(a):
    r = c.execute("SELECT value_json FROM product_facts WHERE app_id=? AND field='name' ORDER BY retrieved_at DESC LIMIT 1", (a,)).fetchone()
    if r: return json.loads(r[0])
    r = c.execute("SELECT name FROM steam_app_list WHERE app_id=?", (a,)).fetchone()
    return r[0] if r else None
other = {k: v for k, v in by.items() if "other-games" in v["roles"]}
print("bundles total", len(by), "other-games", len(other), "wishlist apps", len(wl), "checked", last)
multi = {}
dist = {}
for bid, b in other.items():
    ids = [x["app_id"] for x in b["contents"]]
    w = [a for a in ids if a in wl]
    dist[len(w)] = dist.get(len(w), 0) + 1
    if len(w) >= 2:
        multi[bid] = {**{k: v for k, v in b.items() if k != "roles"},
                      "items": [{"app_id": x["app_id"], "type": x["type"], "parent": x["parent_app_id"], "wishlist": x["app_id"] in wl,
                                 "parent_in_wishlist": x["parent_app_id"] in wl, "name": name_of(x["app_id"])} for x in b["contents"]]}
print("distribution of wishlist apps per other-games bundle:", sorted(dist.items()))
for bid, b in multi.items():
    print(f"\nbundle/{bid} {b['name']} NT${b['original']//100}->{b['final']//100} seen from {b['seen_from']}")
    for it in b["items"]:
        print("   ", it)
(OUT / "s1.json").write_text(json.dumps({"wishlist": sorted(wl), "multi": multi}, ensure_ascii=False, indent=1), encoding="utf-8")
