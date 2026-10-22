"""After 009 (proposal for the user's [purchase_options]), read-only: what each choosable edition would give.

For every edition with a config line, the decision if it were chosen, next to the default version's decision. Choices
of different games are independent (SC-002), so one run per "k-th edition of each game". Writes out/t060.json.
"""
import json
from collections import defaultdict
from pathlib import Path

from steamsage.config import load_config
from steamsage.decision.contract import batch_to_dict
from steamsage.decision.engine import run_decisions
from steamsage.forecast.models import current_model
from steamsage.store.query import PriceStore
from steamsage.timeutil import now_utc

OUT = Path(__file__).parent / "out"
prefs = load_config(Path("steamsage.toml"))[0].preferences
store = PriceStore.open(Path("data/steamsage.db"))
as_of = now_utc()
apps = store.wishlist_apps()


def decide(choices):
    data = batch_to_dict(run_decisions(store, apps, as_of, current_model(), prefs, now=as_of, choices=choices))
    return {d["app_id"]: d for d in data["decisions"]}


base = decide({})
editions = defaultdict(list)
for app, d in base.items():
    for e in d["editions"] or []:
        if e["config_line"]:
            editions[app].append(e)
rows = []
for k in range(max(len(v) for v in editions.values())):
    round_ = {a: (v[k]["kind"], v[k]["id"]) for a, v in editions.items() if len(v) > k}
    got = decide(round_)
    for app, (kind, option_id) in round_.items():
        e = next(x for x in editions[app] if (x["kind"], x["id"]) == (kind, option_id))
        b, c = base[app], got[app]
        rows.append({"app_id": app, "name": b["name"], "edition": e["name"], "config": e["config_line"],
                     "regular": [b["regular_twd"], c["regular_twd"]], "price": [(b["current"] or {}).get("price_twd"),
                                                                                 (c["current"] or {}).get("price_twd")],
                     "group": [b["group"], c["group"]], "sweet": [b["sweet_twd"], c["sweet_twd"]],
                     "pct": [b["sweet_pct"], c["sweet_pct"]],
                     "point": [(b["sweet_point"] or {}).get("label"), (c["sweet_point"] or {}).get("label")],
                     "prob": [b["sweet_probability"], c["sweet_probability"]],
                     "low": e["low_twd"], "history_start": e["history_start"], "confidence": c["confidence"]})
rows.sort(key=lambda r: (r["name"], r["regular"][1] or 0))
(OUT / "t060.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
for r in rows:
    extra = (r["sweet"][1] - r["sweet"][0]) if None not in r["sweet"] else None
    print(f"{r['name'][:18]:18} | {r['edition'][:26]:26} | 原價 {r['regular'][0]}→{r['regular'][1]} | "
          f"{r['group'][0]}→{r['group'][1]} | 甜蜜價 {r['sweet'][0]}→{r['sweet'][1]} (+{extra}) | "
          f"{r['point'][0]}→{r['point'][1]} | {r['confidence']}")
store.close()
