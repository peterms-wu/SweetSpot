"""P1 (plan, read-only): every purchase option of every wishlist app, classified as in research R1.

Classes: D = Steam default option (latest app_versions row); P+ = another package whose ITAD product passes the 006
rule (verify_version with the option itself as the price reference); P- = a package that fails it; BO = a bundle
with only the app and its own DLC; BG = a bundle with other games; B! = a bundle without the app.
For D, P+, P- and BO: the ITAD product, its aliases, the TW and US history (entries, start, discounts, lowest price).
Timings per step (the daily cost, research R8). Writes out/p1.json. Uses the network, never writes the database.
"""
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from steamsage.cli import Context
from steamsage.commands import itad_source, steam_sources
from steamsage.config import load_config, load_secrets
from steamsage.pipeline.verify import verify_version

OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)
DLC = 4
conn = sqlite3.connect("file:data/steamsage.db?mode=ro", uri=True)
ctx = Context(load_config(Path("steamsage.toml"))[0], load_secrets(), None, None)
webapi, _ = steam_sources(ctx)
itad = itad_source(ctx)
T = {}


def timed(name, fn):
    t0 = time.perf_counter()
    out = fn()
    T[name] = round(time.perf_counter() - t0, 1)
    return out


def items(ids, request):
    out = []
    for s in range(0, len(ids), 50):
        payload = webapi._get_items(ids[s:s + 50], request, "p1")
        out += ((payload or {}).get("response") or {}).get("store_items") or []
    return out


apps = [a for (a,) in conn.execute("SELECT app_id FROM wishlist_membership WHERE state='in_wishlist' ORDER BY app_id")]
names = {a: json.loads(conn.execute("SELECT value_json FROM product_facts WHERE app_id=? AND field='name' ORDER BY "
                                    "retrieved_at DESC, fact_id DESC LIMIT 1", (a,)).fetchone()[0]) for a in apps}
cur = conn.execute("SELECT * FROM app_versions v WHERE checked_at=(SELECT MAX(checked_at) FROM app_versions w "
                   "WHERE w.app_id=v.app_id)")
cols = [d[0] for d in cur.description]
versions = {r["app_id"]: r for r in (dict(zip(cols, x)) for x in cur)}

options = timed("steam_purchase_options", lambda: webapi.purchase_options(apps))
bundles = sorted({o.bundle_id for os_ in options.values() for o in os_ if o.bundle_id})
bundle_items = timed("steam_bundle_contents", lambda: items([{"bundleid": b} for b in bundles],
                                                           {"include_basic_info": True}))
contents = {it["id"]: it.get("included_appids") or [] for it in bundle_items if it.get("success") == 1}
others = sorted({a for c in contents.values() for a in c} - set(apps))
kinds = timed("steam_bundle_app_kinds", lambda: webapi.app_kinds(others))


def bundle_class(app, bundle_id):
    c = contents.get(bundle_id)
    if c is None:
        return "B?"
    if app not in c:
        return "B!"
    extra = [a for a in c if a != app and not (kinds.get(a) and kinds[a].type == DLC and kinds[a].parent_app_id == app)]
    return "BO" if not extra else "BG"


rows = []
for a in apps:
    v = versions.get(a)
    for o in options.get(a) or []:
        is_default = bool(v and o.package_id and v["package_id"] == o.package_id)
        cls = "D" if is_default else ("P?" if o.package_id else bundle_class(a, o.bundle_id))
        rows.append({"app_id": a, "name": names[a], "package_id": o.package_id, "bundle_id": o.bundle_id,
                     "option_name": o.name, "original_cents": o.original_cents, "final_cents": o.final_cents,
                     "cls": cls, "bundle_apps": contents.get(o.bundle_id)})

need = [r for r in rows if r["cls"] in ("D", "P?", "BO")]
subs = sorted({r["package_id"] for r in need if r["package_id"]})
bos = sorted({r["bundle_id"] for r in need if r["bundle_id"]})


def lookup():
    out = {("sub", p): g for p, g in itad.lookup_packages(subs).items()}
    payload = itad._post("/lookup/id/shop/61/v1", [f"bundle/{b}" for b in bos]) or {}
    out.update({("bundle", b): payload.get(f"bundle/{b}") for b in bos})
    return out


products = timed("itad_lookup", lookup)
games = sorted({g for g in products.values() if g})
aliases = timed("itad_reverse_lookup", lambda: itad.reverse_lookup(games))
alias_subs = sorted({int(x[4:]) for g in games for x in aliases.get(g) or [] if x.startswith("sub/")})
packages = timed("steam_alias_packages", lambda: webapi.version_packages(alias_subs))
extra = sorted({x for p in packages.values() for x in p.app_ids} - set(apps))
pkg_kinds = timed("steam_alias_app_kinds", lambda: webapi.app_kinds(extra))
summaries = timed("itad_price_summaries", lambda: itad.price_summaries(games, "TW"))

for r in need:
    g = products.get(("sub", r["package_id"]) if r["package_id"] else ("bundle", r["bundle_id"]))
    r["itad_id"], r["aliases"] = g, aliases.get(g)
    r["steam_deals"] = summaries[g].steam_deals if g in summaries else None
    if g is None:
        r["verdict"] = ["no-itad", None, None, []]
        continue
    opts = {x.package_id: (x.original_cents, x.final_cents) for x in options[r["app_id"]] if x.package_id}
    ref = r["package_id"] if r["package_id"] else -1
    if r["bundle_id"]:
        # research R2 candidate: the bundle's own alias counts as the option itself (contents checked above)
        alias_list = [x for x in aliases.get(g) or [] if x != f"bundle/{r['bundle_id']}"]
    else:
        alias_list = aliases.get(g) or []
    res = verify_version(r["app_id"], alias_list or [f"app/{r['app_id']}"], default_package=ref, options=opts,
                         packages=packages, kinds=pkg_kinds, metadata=None)
    r["verdict"] = [res.verification, res.reason_code, res.reason_detail, res.warnings]
    if r["cls"] == "P?":
        r["cls"] = "P+" if res.verification == "verified" else "P-"

editions = [r for r in need if r["cls"] in ("P+", "P-", "BO")]
since = datetime(2010, 1, 1, tzinfo=timezone.utc)
hist = {}
for region in ("TW", "US"):
    ids = sorted({r["itad_id"] for r in editions if r["itad_id"]})
    hist[region] = timed(f"itad_history_{region}_editions", lambda: {g: itad.history(g, region, since) for g in ids})
for r in editions:
    for region in ("TW", "US"):
        h = hist[region].get(r["itad_id"]) or []
        prices = [(e.price_cents, e.observed_at) for e in h if e.price_cents is not None]
        low = min(prices) if prices else None
        r[region] = {"entries": len(h), "start": h[0].observed_at.isoformat() if h else None,
                     "discounts": sum(1 for e in h if e.cut_pct), "max_cut": max([e.cut_pct or 0 for e in h] or [0]),
                     "low_cents": low[0] if low and region == "TW" else None,
                     "low_at": low[1].isoformat() if low and region == "TW" else None,
                     "regulars": sorted({e.regular_cents for e in h if e.regular_cents is not None})}

counts = {}
for r in rows:
    counts[r["cls"]] = counts.get(r["cls"], 0) + 1
apps_with = lambda cs: len({r["app_id"] for r in rows if r["cls"] in cs})  # noqa: E731
listable = [r for r in rows if r["cls"] in ("P+", "BO") and r["verdict"][0] == "verified"]
summary = {"apps": len(apps), "apps_with_options": sum(1 for a in apps if options.get(a)), "options": len(rows),
           "classes": counts, "apps_P+": apps_with({"P+"}), "apps_BO": apps_with({"BO"}),
           "apps_editions": apps_with({"P+", "P-", "BO"}), "listable": len(listable),
           "apps_listable": len({r["app_id"] for r in listable}), "bundles": len(bundles), "seconds": T}
(OUT / "p1.json").write_text(json.dumps({"summary": summary, "rows": rows, "names": names},
                                        ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=1))
for r in editions:
    print(f"{r['cls']:3} {r['name'][:20]:20} {(r['option_name'] or '')[:34]:34} NT${r['original_cents'] // 100:>5}"
          f" {r['verdict'][:3]} TW {r['TW']['entries']:>3} from {str(r['TW']['start'])[:10]} low "
          f"{(r['TW']['low_cents'] or 0) // 100} US from {str(r['US']['start'])[:10]}")
