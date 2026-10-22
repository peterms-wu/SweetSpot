"""Read-only (network): raw Steam GetItems for the 6 bundles and the default options of their content apps."""
import json
from pathlib import Path
from steamsage.cli import Context
from steamsage.commands import steam_sources
from steamsage.config import load_config, load_secrets
OUT = Path(__file__).parent / "out"
s1 = json.loads((OUT / "s1.json").read_text(encoding="utf-8"))
ctx = Context(load_config(Path("steamsage.toml"))[0], load_secrets(), None, None)
webapi, _ = steam_sources(ctx)
bids = [int(b) for b in s1["multi"]]
raw_b = webapi._get_items([{"bundleid": b} for b in bids], {"include_basic_info": True, "include_all_purchase_options": True}, "b")
apps = sorted({it["app_id"] for b in s1["multi"].values() for it in b["items"]})
raw_a = []
for s in range(0, len(apps), 50):
    raw_a += (webapi._get_items([{"appid": a} for a in apps[s:s+50]], {"include_basic_info": True, "include_all_purchase_options": True}, "a").get("response") or {}).get("store_items") or []
(OUT / "s2.json").write_text(json.dumps({"bundles": raw_b, "apps": raw_a}, ensure_ascii=False, indent=1), encoding="utf-8")
it = raw_b["response"]["store_items"][0]
print(json.dumps({k: v for k, v in it.items() if k not in ("assets", "basic_info")}, ensure_ascii=False, indent=1)[:4000])
