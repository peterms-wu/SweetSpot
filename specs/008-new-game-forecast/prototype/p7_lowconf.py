"""008 plan R0.1 (tuning split, cutoff 2026-09-25): who are the low-confidence games (no own TW seasonal record),
and which base predicts their next sales best?

Bases for a game without own TW records at as_of (everything from data before as_of):
  B0  current: population per-sale share, 1 - (1 - s)^k
  B1  the game's own US seasonal records used as its record (seasonal-record 1.0.0 run on them); B0 when none
  B2  "first record" share: over the population, the share of games whose FIRST TW record reached d, for the next
      sale; later sales use the population per-sale share: 1 - (1 - s1)(1 - s)^(k-1)
  B2n like B2, first records only from games released at most 365 days before that sale (really new games)
  B3  B1 when the game has US records, else B2n
Scored on the tuning units of those games (002 scoring and finished-only), game-weighted Brier as in 002.
"""

import sys
import time
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

import numpy as np
from ulib import load

ROOT = Path(r"〈專案資料夾〉")
sys.path.insert(0, str(ROOT / "src"))
from steamsage.forecast.backtest.dataset import build_dataset  # noqa: E402
from steamsage.forecast.contract import LEVELS  # noqa: E402
from steamsage.forecast.engine import all_apps, is_paid_at, load_games  # noqa: E402
from steamsage.forecast.evidence import GameEvidence, population_view  # noqa: E402
from steamsage.forecast.models import current_model  # noqa: E402
from steamsage.store.query import PriceStore  # noqa: E402

t0 = time.monotonic()
data = load()
u = data["units"]
cases, per_as_of, schedule = data["cases"], data["per_as_of"], data["schedule"]
cutoff = data["cutoff"]
store = PriceStore.open(ROOT / "data" / "steamsage.db", ROOT / "data" / "steam_sales.toml")
games = load_games(store, all_apps(store), cutoff)
events = store.calendar_events()
rd = build_dataset(store, games, events, cutoff=cutoff, regions=("TW",), split="tuning").regions["TW"]
assert rd.dataset_id == data["dataset_id"]
release = {}
for a in rd.population_apps:
    f = store.facts(a, cutoff).release_date.value
    release[a] = f
store.close()
print(f"load {time.monotonic() - t0:.0f}s; population {len(rd.population_apps)}, release known "
      f"{sum(v is not None for v in release.values())}")

model = current_model()
L = np.array(LEVELS)
curves = {}          # (ti, app) -> {base: np.array[k][j]}
info = {}            # (ti, app) -> characteristics
for ti, as_of in enumerate(schedule):
    low = [a for (a, t), c in cases.items() if t == as_of and not isinstance(c, str) and c["conf"] == "low"]
    if not low:
        continue
    pool = [a for a in rd.population_apps if games[a].series["TW"].first_start <= as_of and is_paid_at(games[a], as_of)]
    pv = population_view((games[a] for a in pool), as_of, "TW")
    model.prepare(pv)
    points = per_as_of[as_of]["points"]
    total, at_least = model._freq._pool
    s_all = np.array([at_least[d] / total for d in LEVELS])
    firsts, firsts_new = [], []
    for a, hist in pv.sale_history.items():
        tw = hist.get("TW", ())
        if not tw:
            continue
        o = tw[0]
        firsts.append(o.max_cut)
        r = release.get(a)
        if r is not None and o.start.date() - r <= timedelta(days=365):
            firsts_new.append(o.max_cut)
    s1 = np.array([np.mean(np.array(firsts) >= d) for d in LEVELS])
    s1n = np.array([np.mean(np.array(firsts_new) >= d) for d in LEVELS]) if firsts_new else s1
    K = len(points)
    kk = np.arange(1, K + 1)[:, None]
    b2 = 1 - (1 - s1[None, :]) * (1 - s_all[None, :]) ** (kk - 1)
    b2n = 1 - (1 - s1n[None, :]) * (1 - s_all[None, :]) ** (kk - 1)
    for a in low:
        g = games[a]
        us = tuple(o for o in g.outcomes.get("US", ()) if o.end <= as_of)
        b1 = None
        if us:
            ev = GameEvidence(app_id=a, as_of=as_of, target_region="TW",
                              series={r: g.series[r].truncate(as_of) for r in ("TW", "US") if r in g.series},
                              sale_history={"TW": us, "US": us})
            b1 = np.array(model.predict(ev, points, LEVELS).probabilities)
        b0 = np.array(cases[(a, as_of)]["curve"])
        curves[(ti, a)] = {"B0": b0, "B1": b1 if b1 is not None else b0, "B2": b2, "B2n": b2n,
                           "B3": b1 if b1 is not None else b2n}
        tw = g.series["TW"]
        r = release.get(a)
        disc_before = any(s.cut > 0 and s.start < as_of for s in tw.states)
        info[(ti, a)] = {"us": len(us), "age": None if r is None else (as_of.date() - r).days,
                         "track": (as_of - tw.first_start).days, "disc": disc_before}
    print(f"{as_of:%Y-%m} low {len(low)}; firsts {len(firsts)} new {len(firsts_new)}; "
          f"s1(50) {s1[9]:.2f} s1n(50) {s1n[9]:.2f} s(50) {s_all[9]:.2f}", flush=True)

# ---- characteristics of low-confidence cases ----
def cat(i):
    if i["us"] > 0:
        return "A 美國區有紀錄（台灣區追蹤起點晚）"
    if i["age"] is None:
        return "D 發行日未知"
    if i["age"] < 0:
        return "B0 尚未發行（預購）"
    if i["age"] <= 365:
        return "B 發行 1 年內"
    return "C 發行超過 1 年、兩區都沒有紀錄"


print(f"\n## 低信心的（遊戲、分析時點）：{len(info)} 個，{len({a for _, a in info})} 款\n")
cats = defaultdict(list)
for key, i in info.items():
    cats[cat(i)].append(key)
print("| 類別 | 個數 | 款數 | 分析時點前有過折扣 |\n|---|---|---|---|")
for c in sorted(cats):
    ks = cats[c]
    print(f"| {c} | {len(ks)} | {len({a for _, a in ks})} | {np.mean([info[k]['disc'] for k in ks]):.0%} |")

# ---- scoring on the low units ----
sel = u["conf"] == 1
idx = np.nonzero(sel)[0]
keys = list(zip(u["t"][idx].tolist(), u["app"][idx].tolist()))
bases = ("B0", "B1", "B2", "B2n", "B3")
P = {b: np.array([curves[k][b][kk, jj] for k, kk, jj in zip(keys, u["k"][idx], u["j"][idx])]) for b in bases}
catv = np.array([cat(info[k]) for k in keys])
appv = u["app"][idx]


def gw_brier(p, y, apps):
    a, inv = np.unique(apps, return_inverse=True)
    return (np.bincount(inv, weights=(p - y) ** 2) / np.bincount(inv)).mean()


for key, title in (("off", "002 計分"), ("fin", "只計已結束")):
    yv = u[key][idx]
    ok = yv >= 0
    print(f"\n## 低信心單位，{title}\n")
    print("| 類別 | 單位數 | 實際 | " + " | ".join(f"{b} 預測／Brier" for b in bases) + " |")
    print("|---|---|---|" + "---|" * len(bases))
    for c in ["全部"] + sorted(cats):
        m = ok & ((catv == c) if c != "全部" else True)
        if not m.any():
            continue
        y = yv[m].astype(float)
        cells = [f"{P[b][m].mean():.3f}／{gw_brier(P[b][m], y, appv[m]):.4f}" for b in bases]
        print(f"| {c} | {m.sum():,} | {y.mean():.3f} | " + " | ".join(cells) + " |")
print(f"\ntotal {time.monotonic() - t0:.0f}s")
