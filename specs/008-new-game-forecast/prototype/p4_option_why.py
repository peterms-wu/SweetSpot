"""008 first step, diagnosis 2: why is the chosen 3.1.0 option (c=20, raw) 96.6% -> 84.9% when units are ~calibrated?

1. match every evaluable chosen option to its scoring unit (same app, as_of, sale point, level) and compare
2. break the chosen options down by the game's state at as_of and by the target vs the record depth M
"""

import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from ulib import load

ROOT = Path(r"〈專案資料夾〉")
sys.path.insert(0, str(ROOT / "src"))
from steamsage.config import Preferences  # noqa: E402
from steamsage.decision.rule import decide  # noqa: E402
from steamsage.forecast.contract import LEVELS  # noqa: E402
from steamsage.forecast.engine import all_apps, load_games  # noqa: E402
from steamsage.store.query import PriceStore  # noqa: E402
from steamsage.forecast.backtest.scoring import actual_sales  # noqa: E402

data = load()
u = data["units"]
cases, per_as_of, schedule = data["cases"], data["per_as_of"], data["schedule"]
store = PriceStore.open(ROOT / "data" / "steamsage.db", ROOT / "data" / "steam_sales.toml")
games = load_games(store, all_apps(store), data["cutoff"], regions=("TW",))
actual = actual_sales(store.calendar_events())
store.close()
tix = {t: i for i, t in enumerate(schedule)}
unit = {(int(t), int(a), int(k), int(j)): (p, int(f), int(o)) for t, a, k, j, p, f, o in
        zip(u["t"], u["app"], u["k"], u["j"], u["p"], u["fin"], u["off"])}
prefs = Preferences(wait_cost_twd=20)
rows = []
for (app, as_of), case in cases.items():
    info = per_as_of[as_of]
    d = decide(probabilities=case["curve"], points=info["points"], as_of=as_of, confidence=case["conf"],
               evidence_max_cut=case["max_cut"], regular_cents=case["regular"],
               current_price_cents=case["regular"] * (100 - case["cut"]) // 100, regular_mismatch=False,
               no_history=info["no_history"], preferences=prefs, rule="3.1.0")
    if d.group == "now" or d.expected is None or d.expected.target_pct is None or d.basis != "own" \
            or d.confidence != "normal":
        continue
    pts = info["points"]
    end = pts[d.deadline_index - 1].end
    series = games[app].series["TW"]
    if series.known_until is None or series.known_until < end:
        continue
    pct = d.expected.target_pct
    first = series.first_crossings(as_of, [pct])[pct]
    hit = first is not None and first <= end
    un = unit.get((tix[as_of], app, d.deadline_index - 1, LEVELS.index(pct)))
    act = actual.get(pts[d.deadline_index - 1].sale_key)
    hit_act = None if act is None or series.known_until < act.end else (first is not None and first < act.end)
    rows.append({"hit_act": hit_act, "act_end": act.end if act else None, "p": d.expected.reach_probability, "hit": hit, "unit": un, "cut": case["cut"], "M": case["max_cut"],
                 "pct": pct, "K": d.deadline_index, "sales": case["sales"], "as_of": as_of, "app": app,
                 "first": first, "end": end, "status": pts[d.deadline_index - 1].status})

p = np.array([r["p"] for r in rows])
y = np.array([r["hit"] for r in rows], float)
print(f"一般信心、本身曲線的可評估等待決策 {len(rows):,}：{p.mean():.1%} → {y.mean():.1%}\n")
matched = [r for r in rows if r["unit"] is not None and r["unit"][1] >= 0]
print(f"對到已結束計分單位的 {len(matched):,}：選項預測 {np.mean([r['p'] for r in matched]):.1%}、"
      f"單位預測 {np.mean([r['unit'][0] for r in matched]):.1%}；選項實際 {np.mean([r['hit'] for r in matched]):.1%}、"
      f"單位實際 {np.mean([r['unit'][1] for r in matched]):.1%}；結果不同 {sum(r['hit'] != r['unit'][1] for r in matched)}\n")


def show(title, groups):
    print(f"| {title} | 決策數 | 預測 → 實際 |\n|---|---|---|")
    for name, sel in groups:
        m = np.array([sel(r) for r in rows])
        if m.any():
            print(f"| {name} | {m.sum():,} | {p[m].mean():.1%} → {y[m].mean():.1%} |")
    print()


show("分析時點的狀態", [("正在打折（現價有折扣）", lambda r: r["cut"] > 0), ("沒有打折", lambda r: r["cut"] == 0)])
show("目標和過去最深 M", [("目標 = M", lambda r: r["pct"] == r["M"]), ("目標 = M − 5", lambda r: r["pct"] == r["M"] - 5),
                     ("目標 ≤ M − 10", lambda r: r["pct"] <= r["M"] - 10), ("目標 > M", lambda r: r["pct"] > r["M"])])
show("最晚等到的那一場", [("已公布", lambda r: r["status"] == "announced"), ("估計", lambda r: r["status"] != "announced")])
by_t = defaultdict(list)
for r in rows:
    by_t[r["as_of"]].append(r)
print("| 分析時點 | 決策數 | 預測 → 實際 |\n|---|---|---|")
for t in schedule:
    rs = by_t.get(t)
    if rs:
        print(f"| {t:%Y-%m} | {len(rs):,} | {np.mean([r['p'] for r in rs]):.1%} → {np.mean([r['hit'] for r in rs]):.1%} |")
misses = [r for r in rows if not r["hit"] and r["p"] > 0.99]
print(f"\n預測 > 99% 卻沒達到：{len(misses):,}；其中正在打折 {sum(r['cut'] > 0 for r in misses):,}、"
      f"目標 = M {sum(r['pct'] == r['M'] for r in misses):,}、本身 1 場 {sum(r['sales'] == 1 for r in misses):,}")
for r in misses[:12]:
    s = games[r["app"]].series["TW"]
    cuts = [(st.start.strftime("%m-%d"), st.cut) for st in s.states if r["as_of"] <= st.start <= r["end"]]
    print(f"  app {r['app']} {r['as_of']:%Y-%m} cut {r['cut']} M {r['M']} target {r['pct']} K {r['K']} "
          f"sales {r['sales']} end {r['end']:%Y-%m-%d} changes {cuts[:6]}")

print("\n## 以實際的特賣結束日計分\n")
ra = [r for r in rows if r["hit_act"] is not None]
print(f"可評估 {len(ra):,}：{np.mean([r['p'] for r in ra]):.1%} → 估計結束日 {np.mean([r['hit'] for r in ra]):.1%}、"
      f"實際結束日 {np.mean([r['hit_act'] for r in ra]):.1%}\n")
print("| 分析時點 | 最晚那一場（多數） | 估計結束 | 實際結束 | 決策數 | 預測 | 實際（估計日） | 實際（實際日） |\n"
      "|---|---|---|---|---|---|---|---|")
from collections import Counter
for t in schedule:
    rs = [r for r in ra if r["as_of"] == t]
    if not rs:
        continue
    (end, aend), _ = Counter((r["end"], r["act_end"]) for r in rs).most_common(1)[0]
    print(f"| {t:%Y-%m} | K={Counter(r['K'] for r in rs).most_common(1)[0][0]} | {end:%Y-%m-%d} | {aend:%Y-%m-%d} | {len(rs):,} | "
          f"{np.mean([r['p'] for r in rs]):.1%} | {np.mean([r['hit'] for r in rs]):.1%} | {np.mean([r['hit_act'] for r in rs]):.1%} |")
for name, sel in (("目標 = M", lambda r: r["pct"] == r["M"]), ("目標 < M", lambda r: r["pct"] < r["M"]), ("目標 > M", lambda r: r["pct"] > r["M"]),
                  ("本身 1 場", lambda r: r["sales"] == 1), ("本身 2–5 場", lambda r: 2 <= r["sales"] <= 5), ("本身 6+ 場", lambda r: r["sales"] >= 6),
                  ("正在打折", lambda r: r["cut"] > 0)):
    rs = [r for r in ra if sel(r)]
    print(f"{name}: {len(rs):,} {np.mean([r['p'] for r in rs]):.1%} → {np.mean([r['hit_act'] for r in rs]):.1%}")
