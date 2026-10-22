"""P4: backtest dataset impact (spec FR-016/FR-017, research R6). Read-only; writes out/p4.json.

1. Rebuild the TW dataset at the 002 cutoff and confirm its id (d547c29d...).
2. ITAD current prices for every mapped game: which ones ITAD no longer tracks on Steam (0 Steam deals).
3. For those in the dataset: is the app still sold on Steam, and how many seasonal sales fall between the series'
   last observation and the cutoff (sales that the dataset treats as known but are really unknown).
4. Series whose regular price flips back to an earlier value (possibly two products mixed).
"""
import json
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from steamsage.config import load_secrets
from steamsage.forecast.backtest.dataset import build_dataset
from steamsage.forecast.backtest.split import part
from steamsage.forecast.engine import all_apps, load_games
from steamsage.store.query import PriceStore

OUT = Path(__file__).parent / "out"
CUTOFF = datetime(2026, 9, 25, tzinfo=UTC)
H = {"ITAD-API-Key": load_secrets().itad_api_key.reveal()}

t0 = time.perf_counter()
store = PriceStore.open(Path("data/steamsage.db"))
games = load_games(store, all_apps(store), CUTOFF)
events = store.calendar_events()
dataset = build_dataset(store, games, events, cutoff=CUTOFF, regions=("TW",))
tw = dataset.regions["TW"]
print(f"dataset TW id {tw.dataset_id[:8]}..., {len(tw.apps)} apps, {len(tw.schedule)} points "
      f"({time.perf_counter() - t0:.0f}s)")

conn = sqlite3.connect("file:data/steamsage.db?mode=ro", uri=True)
ext = {a: e for a, e in conn.execute("SELECT app_id, external_id FROM source_mappings WHERE source='itad' "
                                     "AND external_id IS NOT NULL GROUP BY app_id")}
ids = sorted({ext[a] for a in tw.apps if a in ext})
deals = {}
t1 = time.perf_counter()
for s in range(0, len(ids), 200):
    r = httpx.post("https://api.isthereanydeal.com/games/prices/v3", json=ids[s:s + 200], headers=H, timeout=120,
                   params={"country": "TW", "shops": 61, "deals": "false", "vouchers": "false"})
    for g in r.json():
        deals[g["id"]] = sum(1 for d in g.get("deals") or [] if d["shop"]["id"] == 61)
print(f"ITAD prices for {len(ids)} games: {time.perf_counter() - t1:.0f}s")
stopped = [a for a in tw.apps if deals.get(ext.get(a), 0) == 0]
multi = [a for a in tw.apps if deals.get(ext.get(a), 0) > 1]

sold = {}
for s in range(0, len(stopped), 50):
    req = {"ids": [{"appid": a} for a in stopped[s:s + 50]],
           "context": {"language": "english", "country_code": "TW", "steam_realm": 1},
           "data_request": {"include_basic_info": True}}
    r = httpx.get("https://api.steampowered.com/IStoreBrowseService/GetItems/v1/",
                  params={"input_json": json.dumps(req)}, timeout=60).json()
    for it in r["response"].get("store_items", []):
        sold[it.get("appid")] = bool(it.get("best_purchase_option"))

seasonal = sorted((e for e in events if e.kind == "seasonal"), key=lambda e: e.start)
rows = []
for a in stopped:
    series = games[a].series["TW"]
    last = series.states[-1].start
    hidden = [e for e in seasonal if last < e.start <= CUTOFF]
    rows.append({"app_id": a, "name": store.facts(a, CUTOFF).name.value, "split": part(a), "still_sold": sold.get(a),
                 "last_observation": last.date().isoformat(), "last_cut": series.states[-1].cut,
                 "sales_after_last": len(hidden)})
rows.sort(key=lambda r: -r["sales_after_last"])
flip = []
for a in tw.apps:
    regs = [s.regular_cents for s in games[a].series["TW"].states if s.regular_cents is not None]
    changes = [regs[0]] + [regs[i] for i in range(1, len(regs)) if regs[i] != regs[i - 1]] if regs else []
    if any(changes[i] in changes[:i - 1] for i in range(2, len(changes))):
        flip.append({"app_id": a, "split": part(a), "regulars": sorted(set(changes))})

print(f"ITAD 0 Steam deals: {len(stopped)} apps; >1 Steam deals: {len(multi)}")
print("  still sold on Steam:", sum(1 for r in rows if r["still_sold"]), "| not sold:", sum(1 for r in rows if not r["still_sold"]))
print("  with >=1 seasonal sale after the last observation:", sum(1 for r in rows if r["sales_after_last"]),
      "| by split:", {s: sum(1 for r in rows if r["sales_after_last"] and r["split"] == s) for s in ("tuning", "validation")})
print("  still sold AND last state is a discount:", [r for r in rows if r["still_sold"] and r["last_cut"]])
for r in rows[:12]:
    print("   ", r)
print(f"regular-price flips: {len(flip)}", {s: sum(1 for f in flip if f["split"] == s) for s in ("tuning", "validation")})
(OUT / "p4.json").write_text(json.dumps({"dataset_id": tw.dataset_id, "stopped": rows, "multi_deals": multi,
                                         "flips": flip}, ensure_ascii=False, indent=1), encoding="utf-8")
