"""008 first step, side by side (tuning split, cutoff 2026-09-25):

variants of the seasonal curves
  raw       seasonal-record 1.0.0
  iso       past-only isotonic map of p, one map (p2_iso.py)
  iso_conf  past-only isotonic map of p, one map per confidence level
  shrinkA   structural probe: seen-level per-sale share shrunk toward the population share with weight A sales

per variant: unit Brier (two scorings), rule 2.1.0 decision changes, net benefit vs raw 2.1.0 (monthly
re-evaluation, production net_comparison), and the chosen 3.1.0 option's "reached by the deadline" scored at the
ACTUAL end of the deadline sale (005 R0.2 used the estimated end).
"""

import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from ulib import apply, load, make_maps

ROOT = Path(r"〈專案資料夾〉")
sys.path.insert(0, str(ROOT / "src"))
from steamsage.config import Preferences  # noqa: E402
from steamsage.decision.backtest import _Compact, case_rows, follow_advice, follow_advice_monthly  # noqa: E402
from steamsage.decision.compare_rule import net_comparison  # noqa: E402
from steamsage.decision.rule import decide  # noqa: E402
from steamsage.forecast.backtest.scoring import actual_sales  # noqa: E402
from steamsage.forecast.engine import all_apps, load_games  # noqa: E402
from steamsage.store.query import PriceStore  # noqa: E402

t_start = time.monotonic()
raw = load()
store = PriceStore.open(ROOT / "data" / "steamsage.db", ROOT / "data" / "steam_sales.toml")
games = load_games(store, all_apps(store), raw["cutoff"], regions=("TW",))
actual = actual_sales(store.calendar_events())
store.close()
schedule = raw["schedule"]
maps = make_maps(raw)
VARIANTS = {"raw": (raw, None), "iso": (raw, "iso"), "iso_conf": (raw, "iso_conf")}
for a in ("0.5", "1", "2"):
    VARIANTS[f"shrink{a}"] = (load(f"cache_shrink{a}.pkl"), None)
P21, P31 = Preferences(), Preferences(wait_cost_twd=20)


def mapped(curve, m):
    if m is None or curve is None:
        return curve
    return tuple(tuple(float(v) for v in row) for row in np.interp(np.array(curve), m[0], m[1]))


def unit_probs(data, mp):
    u = data["units"]
    if mp is None:
        return u["p"]
    q = u["p"].copy()
    for ti, t in enumerate(schedule):
        for ci, c in enumerate(("normal", "low")):
            m = (u["t"] == ti) & (u["conf"] == ci)
            q[m] = apply(maps[mp][t][c], u["p"][m])
    return q


def decisions(data, mp, rule, prefs):
    out = {}
    for (app, as_of), case in data["cases"].items():
        info = data["per_as_of"][as_of]
        curve, nh = case["curve"], info["no_history"]
        if mp:
            curve, nh = mapped(curve, maps[mp][as_of][case["conf"]]), mapped(nh, maps[mp][as_of]["low"])
        out[(app, as_of)] = decide(probabilities=curve, points=info["points"], as_of=as_of, confidence=case["conf"],
                                   evidence_max_cut=case["max_cut"], regular_cents=case["regular"],
                                   current_price_cents=case["regular"] * (100 - case["cut"]) // 100,
                                   regular_mismatch=False, no_history=nh, preferences=prefs, rule=rule)
    return out


def result(decs, cost):
    by_app = defaultdict(dict)
    for (app, as_of), d in decs.items():
        by_app[app][as_of] = _Compact(d.group, d.sweet_pct)
    scores = {}
    for (app, as_of), d in decs.items():
        series = games[app].series["TW"]
        st = series.state_at(as_of)
        now = st.regular_cents * (100 - st.cut) // 100
        scores[("fixed", app, as_of)] = follow_advice(series, as_of, d, now_price_cents=now)
        scores[("monthly", app, as_of)] = follow_advice_monthly(series, as_of, schedule, by_app[app],
                                                                now_price_cents=now)
    return {"cases": case_rows(scores), "preferences": {"wait_cost_twd": cost},
            "dataset": {"dataset_id": raw["dataset_id"], "split": {"name": "tuning"}},
            "model": {"name": "x", "version": "x", "params": {}}, "rule": {"name": "sweet-price", "version": "x"}}


def options(data, decs):
    """Chosen 3.1.0 options, scored at the actual end of the deadline sale."""
    rows = []
    for (app, as_of), d in decs.items():
        if d.group == "now" or d.expected is None or d.expected.target_pct is None:
            continue
        point = data["per_as_of"][as_of]["points"][d.deadline_index - 1]
        act = actual.get(point.sale_key)
        series = games[app].series["TW"]
        if act is None or series.known_until is None or series.known_until < act.end:
            continue
        pct = d.expected.target_pct
        first = series.first_crossings(as_of, [pct])[pct]
        rows.append((d.expected.reach_probability, first is not None and first < act.end,
                     d.confidence == "normal" and d.basis == "own", data["cases"][(app, as_of)]["sales"]))
    return rows


def pct(rows, sel=lambda r: True):
    rs = [r for r in rows if sel(r)]
    return f"{np.mean([r[0] for r in rs]):.1%} → {np.mean([r[1] for r in rs]):.1%}（{len(rs):,}）" if rs else "—"


base = None
lines_u, lines_d, lines_n, lines_o = [], [], [], []
d21_raw = None
for name, (data, mp) in VARIANTS.items():
    t1 = time.monotonic()
    u = data["units"]
    q = unit_probs(data, mp)
    cells = []
    for key in ("off", "fin"):
        ok = u[key] >= 0
        y = u[key].astype(float)
        e = (q - y) ** 2
        hi = ok & (q >= 0.7)
        cells += [f"{e[ok].mean():.4f}", f"{e[ok & (u['conf'] == 0)].mean():.4f}",
                  f"{(q[hi].mean() - y[hi].mean()) * 100:+.1f}"]
    lines_u.append(f"| {name} | " + " | ".join(cells) + " |")
    d21, d31 = decisions(data, mp, "2.1.0", P21), decisions(data, mp, "3.1.0", P31)
    if name == "raw":
        d21_raw = d21
        base = result(d21, 20)
    g = Counter(d.group for d in d21.values())
    ch = sum(d21[k].group != d21_raw[k].group for k in d21)
    sp = sum(d21[k].sweet_pct != d21_raw[k].sweet_pct for k in d21)
    lines_d.append(f"| {name} | {ch:,}（{ch / len(d21):.1%}） | {sp:,}（{sp / len(d21):.1%}） | "
                   f"{g['now']:,} / {g['soon']:,} / {g['wait']:,} / {g['low']:,} |")
    r21, r31 = result(d21, 20), result(d31, 20)
    for rule, r in (("2.1.0", r21), ("3.1.0", r31)):
        if name == "raw" and rule == "2.1.0":
            continue
        cells = []
        for c in (0, 20):
            nc = net_comparison(dict(base, preferences={"wait_cost_twd": c}), dict(r, preferences={"wait_cost_twd": c}),
                                default_cost=-1)["modes"]["monthly"]
            cells.append(f"{nc['diff']:+.1f} [{nc['ci'][0]:+.1f}, {nc['ci'][1]:+.1f}]")
        lines_n.append(f"| {rule} {name} | {nc['b']['saving']:.1f} | {nc['b']['wait_days']:.1f} | " + " | ".join(cells)
                       + " |")
    ro = options(data, d31)
    lines_o.append(f"| {name} | {pct(ro)} | {pct(ro, lambda r: r[2])} | {pct(ro, lambda r: not r[2])} | "
                   f"{pct(ro, lambda r: r[2] and r[3] == 1)} |")
    print(f"{name}: {time.monotonic() - t1:.0f}s", flush=True)

print("\n## 單位層級 Brier（調參組）\n")
print("| 版本 | 002 框架 | 　一般信心 | 　預測 ≥ 0.7 高估 | 只計已結束 | 　一般信心 | 　預測 ≥ 0.7 高估 |\n|---|---|---|---|---|---|---|")
print("\n".join(lines_u))
print("\n## 規則 2.1.0 的決策（和原始相比）\n")
print("| 版本 | 分組改變 | 甜蜜價改變 | 現在買 / 即將 / 繼續等 / 低信心 |\n|---|---|---|---|")
print("\n".join(lines_d))
print("\n## 淨效益：和原始曲線的 2.1.0 成對比較（每月重新評估，依遊戲重抽樣 2,000 次）\n")
print(f"基準 2.1.0 原始：見 p2_iso.md（多省 NT$210.6、多等 40.6 天）\n")
print("| 候選 | 多省（NT$） | 多等（天） | 差距 c = 0 | 差距 c = 20 |\n|---|---|---|---|---|")
print("\n".join(lines_n))
print("\n## 3.1.0（c = 20）選中選項「到期前達到」，以實際結束日計分：預測 → 實際（決策數）\n")
print("| 版本 | 全部 | 一般信心、本身曲線 | 低信心或沒有本身歷史 | 一般信心、本身 1 場 |\n|---|---|---|---|---|")
print("\n".join(lines_o))
print(f"\ntotal {time.monotonic() - t_start:.0f}s")
