"""Read-only (network): ITAD products, aliases and TW/US histories of the 6 bundles and all their content apps."""
import json, time
from datetime import datetime, timezone
from pathlib import Path
from steamsage.cli import Context
from steamsage.commands import itad_source
from steamsage.config import load_config, load_secrets
OUT = Path(__file__).parent / "out"
s1 = json.loads((OUT / "s1.json").read_text(encoding="utf-8"))
ctx = Context(load_config(Path("steamsage.toml"))[0], load_secrets(), None, None)
itad = itad_source(ctx)
t0 = time.perf_counter()
bids = [int(b) for b in s1["multi"]]
payload = itad._post("/lookup/id/shop/61/v1", [f"bundle/{b}" for b in bids]) or {}
bprod = {b: payload.get(f"bundle/{b}") for b in bids}
apps = sorted({it["app_id"] for b in s1["multi"].values() for it in b["items"]})
aprod = itad.lookup_steam(apps)
ids = sorted({g for g in list(bprod.values()) + list(aprod.values()) if g})
aliases = itad.reverse_lookup([g for g in bprod.values() if g])
since = datetime(2010, 1, 1, tzinfo=timezone.utc)
hist = {}
for region in ("TW", "US"):
    for g in ids:
        h = itad.history(g, region, since)
        hist[f"{region}:{g}"] = [[e.observed_at.isoformat(), e.price_cents, e.regular_cents, e.cut_pct, e.currency] for e in h]
summ = itad.price_summaries([g for g in bprod.values() if g], "TW")
out = {"bprod": bprod, "aprod": aprod, "aliases": aliases, "hist": hist,
       "summ": {g: repr(v) for g, v in summ.items()}, "seconds": round(time.perf_counter() - t0, 1)}
(OUT / "s4.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print("seconds", out["seconds"])
for b, g in bprod.items():
    h = hist.get(f"TW:{g}") or []; hu = hist.get(f"US:{g}") or []
    print(b, g, "aliases", aliases.get(g), "TW entries", len(h), h[0][0][:10] if h else None, "US", len(hu), hu[0][0][:10] if hu else None)
    print("   ", out["summ"].get(g))
print("apps without ITAD:", [a for a, g in aprod.items() if not g])
