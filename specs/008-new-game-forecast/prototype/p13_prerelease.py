"""008 plan R0.6: do pre-release seasonal records hurt games with few records? (tuning, finished-only, 1.0.0)"""
import sys
from pathlib import Path
import numpy as np
from ulib import load
sys.path.insert(0, r"〈專案資料夾〉\src")
from steamsage.forecast.engine import all_apps, load_games
from steamsage.store.query import PriceStore
ROOT = Path(r"〈專案資料夾〉")
data = load(); u = data["units"]; sched = data["schedule"]
store = PriceStore.open(ROOT / "data" / "steamsage.db", ROOT / "data" / "steam_sales.toml")
games = load_games(store, all_apps(store), data["cutoff"], regions=("TW",))
rel = {a: store.facts(a, data["cutoff"]).release_date.value for a in set(u["app"].tolist())}
store.close()
pre_n = {}
for t, a in set(zip(u["t"].tolist(), u["app"].tolist())):
    own = [o for o in games[a].outcomes.get("TW", ()) if o.end <= sched[t]]
    r = rel.get(a)
    pre_n[(t, a)] = sum(1 for o in own if r is not None and o.start.date() < r)
pre = np.array([pre_n[(t, a)] for t, a in zip(u["t"].tolist(), u["app"].tolist())])
ok = (u["fin"] >= 0) & (u["conf"] == 0)
y = u["fin"].astype(float)
for s in (1, 2, 3):
    for name, m in (("含發售前紀錄", pre > 0), ("沒有", pre == 0)):
        mm = ok & (u["sales"] == s) & m & (u["seen"] == 1)
        if mm.any():
            print(f"本身 {s} 場、{name}、見過的等級：單位 {mm.sum():,}、款 {len(set(u['app'][mm].tolist()))}、"
                  f"預測 {u['p'][mm].mean():.3f} → 實際 {y[mm].mean():.3f}、Brier {((u['p'][mm]-y[mm])**2).mean():.4f}")
