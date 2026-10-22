"""SC-002 on the same data (tasks T028): decisions with version keys vs with every app forced to its own product.

Only games whose version differs from their own product may differ. Read-only; prints the differences.
"""
import sys
from datetime import UTC, datetime
from pathlib import Path

from steamsage.config import load_config
from steamsage.decision.contract import batch_to_dict
from steamsage.decision.engine import run_decisions
from steamsage.forecast.models import current_model
from steamsage.store.query import HistoryKey, PriceStore

config, _ = load_config(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("steamsage.toml"))
store = PriceStore.open(config.db_path)
as_of = datetime.now(UTC)
apps = store.wishlist_apps()
FIELDS = ("group", "confidence", "sweet_twd", "sweet_pct", "p_min_pct", "tags", "reasons")


def decide():
    data = batch_to_dict(run_decisions(store, apps, as_of, current_model(), config.preferences, now=as_of))
    return {d["app_id"]: d for d in data["decisions"]}


normal = decide()
real = PriceStore.history_keys


def own_only(self, app_ids, at):
    own = self.own_keys(app_ids)
    return {a: HistoryKey(own[a], "own", "no-record") for a in app_ids}


PriceStore.history_keys = own_only
forced = decide()
PriceStore.history_keys = real

differ = []
for app, d in normal.items():
    o = forced[app]
    fields = [f for f in FIELDS if d.get(f) != o.get(f)]
    if (d.get("sweet_point") or {}).get("label") != (o.get("sweet_point") or {}).get("label"):
        fields.append("sweet_point")
    if d.get("status_reason") != o.get("status_reason"):
        fields.append("status_reason")
    if fields:
        differ.append((app, d["name"], fields))
print(f"{len(normal)} games; {len(differ)} differ")
for row in differ:
    print("  ", row)

if "--detail" in sys.argv:
    for app, name, fields in differ[:3] + [r for r in differ if r[0] == 881020]:
        a, b = normal[app], forced[app]
        print("==", app, name)
        for x, y in zip(a.get("reasons", []), b.get("reasons", [])):
            if x != y:
                print("   version:", x)
                print("   own    :", y)
        print("   sweet", a.get("sweet_twd"), b.get("sweet_twd"), "p_min", a.get("p_min_pct"), b.get("p_min_pct"))

# Classify: which differences come only from the population line ("參考資料集中…（N 場…）")?
population_only, substantive = [], []
for app, name, fields in differ:
    if app in (239140, 9500003):
        continue
    a, b = normal[app], forced[app]
    lines = [(x, y) for x, y in zip(a.get("reasons", []), b.get("reasons", [])) if x != y]
    if fields == ["reasons"] and all("參考資料集中" in x and "參考資料集中" in y for x, y in lines):
        population_only.append(app)
    else:
        substantive.append((app, name, fields))
print(f"population line only: {len(population_only)}; other differences: {substantive}")
