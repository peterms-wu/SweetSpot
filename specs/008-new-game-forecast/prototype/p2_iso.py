"""008 first step, parts 2 and 3 (tuning split, cutoff 2026-09-25):

2. option-level calibration of rule 3.1.0 (c = 20): the chosen option's "reached by the deadline" vs what happened
3. the simplest post-hoc calibration: isotonic regression of p, refitted at every as_of on finished-sale units that
   were already known then (sale ended before as_of); variants: one map for all, one map per confidence level.
   Effects on Brier/calibration, on rule 2.1.0 decisions, and on 3.1.0 (c = 20) vs 2.1.0 net benefit.

Decisions use the production decide(); scoring uses the production follow_advice_monthly / follow_advice and the
production net_comparison (paired by game, 2,000 resamples, seed from the dataset id). The raw runs are checked case
by case against the production backtest-rule results of the same dataset.
"""

import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from ulib import OUT, bins, load, summary

ROOT = Path(r"〈專案資料夾〉")
sys.path.insert(0, str(ROOT / "src"))

from steamsage.config import Preferences  # noqa: E402
from steamsage.decision.backtest import (_Compact, case_rows, follow_advice, follow_advice_monthly)  # noqa: E402
from steamsage.decision.compare_rule import net_comparison  # noqa: E402
from steamsage.decision.rule import decide  # noqa: E402
from steamsage.forecast.engine import all_apps, load_games  # noqa: E402
from steamsage.store.query import PriceStore  # noqa: E402

PROD = {"2.1.0": sorted(ROOT.glob("data/backtests/*sweet-price-2.1.0_seasonal-record-1.0.0_b5c69b_TW_858b3147.json"))[-1],
        "3.1.0": sorted(ROOT.glob("data/backtests/*sweet-price-3.1.0-c20_seasonal-record-1.0.0_b5c69b_TW_858b3147.json"))[-1]}
MIN_FIT = 5000
t_start = time.monotonic()
data = load()
u = data["units"]
cases, per_as_of, schedule = data["cases"], data["per_as_of"], data["schedule"]
store = PriceStore.open(ROOT / "data" / "steamsage.db", ROOT / "data" / "steam_sales.toml")
games = load_games(store, all_apps(store), data["cutoff"], regions=("TW",))
store.close()
print(f"loaded {time.monotonic() - t_start:.0f}s")


# ---- isotonic maps ------------------------------------------------------------------------------------------
def pav(x, y, w):
    """Weighted pool-adjacent-violators on points sorted by x; returns fitted non-decreasing values."""
    vals, wts, cnt = [], [], []
    for yi, wi in zip(y, w):
        vals.append(yi); wts.append(wi); cnt.append(1)
        while len(vals) > 1 and vals[-2] > vals[-1]:
            v = (vals[-2] * wts[-2] + vals[-1] * wts[-1]) / (wts[-2] + wts[-1])
            wsum, c = wts[-2] + wts[-1], cnt[-2] + cnt[-1]
            vals[-2:], wts[-2:], cnt[-2:] = [v], [wsum], [c]
    out = []
    for v, c in zip(vals, cnt):
        out.extend([v] * c)
    return np.array(out)


def fit(p, y, nbins=200):
    if len(p) < MIN_FIT:
        return None
    b = np.minimum((p * nbins).astype(int), nbins - 1)
    w = np.bincount(b, minlength=nbins).astype(float)
    sp = np.bincount(b, weights=p, minlength=nbins)
    sy = np.bincount(b, weights=y, minlength=nbins)
    keep = w > 0
    x, yy, ww = sp[keep] / w[keep], sy[keep] / w[keep], w[keep]
    return x, pav(x, yy, ww)


def apply(m, p):
    if m is None:
        return p
    return np.interp(p, m[0], m[1])


ends = u["end"]
maps = {"global": {}, "by_conf": {}}
for ti, t in enumerate(schedule):
    train = (u["t"] < ti) & (u["fin"] >= 0) & (ends > 0) & (ends <= t.timestamp())
    maps["global"][t] = {"normal": fit(u["p"][train], u["fin"][train].astype(float))}
    maps["global"][t]["low"] = maps["global"][t]["normal"]
    maps["by_conf"][t] = {c: fit(u["p"][train & (u["conf"] == i)], u["fin"][train & (u["conf"] == i)].astype(float))
                          for i, c in enumerate(("normal", "low"))}
fitted = sum(maps["global"][t]["normal"] is not None for t in schedule)
print(f"maps fitted at {fitted}/{len(schedule)} as_of (min {MIN_FIT} known finished units)")
last = maps["global"][schedule[-1]]["normal"]
probe = np.array([0.02, 0.1, 0.2, 0.3, 0.5, 0.7, 0.8, 0.9, 0.95, 0.99, 1.0])
print("last global map:", " ".join(f"{a:.2f}->{b:.3f}" for a, b in zip(probe, apply(last, probe))))
lowm = maps["by_conf"][schedule[-1]]["low"]
print("last low map:   ", " ".join(f"{a:.2f}->{b:.3f}" for a, b in zip(probe, apply(lowm, probe))))

# ---- part 3a: unit-level Brier / calibration ----------------------------------------------------------------
t_idx = u["t"]
conf = u["conf"]
cal = {}
for name, mp in maps.items():
    q = u["p"].copy()
    for ti, t in enumerate(schedule):
        for ci, c in enumerate(("normal", "low")):
            m = (t_idx == ti) & (conf == ci)
            q[m] = apply(mp[t][c], u["p"][m])
    cal[name] = q
report = {}
lines = ["## 3a. 單位層級（調參組）\n",
         "| 計分 | 版本 | 單位數 | 預測 → 實際 | Brier | 預測 ≥ 0.7 的高估 | 一般信心 Brier | 低信心 Brier |",
         "|---|---|---|---|---|---|---|---|"]
for key, title in (("off", "002 框架"), ("fin", "只計已結束")):
    ok = u[key] >= 0
    y = u[key].astype(float)
    for name, q in (("原始", u["p"]), ("保序：單一", cal["global"]), ("保序：依信心", cal["by_conf"])):
        s = summary(q[ok], y[ok])
        bn = ((q - y) ** 2)[ok & (conf == 0)].mean()
        bl = ((q - y) ** 2)[ok & (conf == 1)].mean()
        lines.append(f"| {title} | {name} | {s['n']:,} | {s['pred']:.3f} → {s['act']:.3f} | {s['brier']:.4f} | "
                     f"{s['hi_gap'] * 100:+.1f} | {bn:.4f} | {bl:.4f} |")
    # only as_of with a fitted map (the calibration can act there)
    for name, q in (("原始（有校準表的時點）", u["p"]), ("保序：單一（有校準表的時點）", cal["global"])):
        has = np.isin(t_idx, [ti for ti, t in enumerate(schedule) if maps["global"][t]["normal"] is not None])
        s = summary(q[ok & has], y[ok & has])
        lines.append(f"| {title} | {name} | {s['n']:,} | {s['pred']:.3f} → {s['act']:.3f} | {s['brier']:.4f} | "
                     f"{s['hi_gap'] * 100:+.1f} | — | — |")
lines.append("\n校準表（只計已結束）：原始 → 保序單一 → 保序依信心\n")
lines.append("| 預測機率（原始分組） | 單位數 | 原始 | 保序：單一 | 保序：依信心 |\n|---|---|---|---|---|")
ok = u["fin"] >= 0
y = u["fin"].astype(float)
for lo, n, pm, am in bins(u["p"][ok], y[ok]):
    m = ok & (np.minimum((u["p"] / 0.1).astype(int), 9) == int(round(lo * 10)))
    lines.append(f"| {lo:.1f}–{lo + 0.1:.1f} | {n:,} | {pm:.3f} → {am:.3f} | {cal['global'][m].mean():.3f} → {am:.3f} | "
                 f"{cal['by_conf'][m].mean():.3f} → {am:.3f} |")
print("\n".join(lines))


# ---- decisions ----------------------------------------------------------------------------------------------
def mapped_curve(curve, m):
    if m is None:
        return curve
    arr = np.interp(np.array(curve), m[0], m[1])
    return tuple(tuple(float(v) for v in row) for row in arr)


def run(rule, prefs, variant):
    out = {}
    for (app, as_of), case in cases.items():
        if isinstance(case, str):
            out[(app, as_of)] = case
            continue
        info = per_as_of[as_of]
        curve, nh = case["curve"], info["no_history"]
        if variant:
            mp = maps[variant][as_of]
            curve = mapped_curve(curve, mp[case["conf"]])
            nh = mapped_curve(nh, mp["low"]) if nh else None
        try:
            out[(app, as_of)] = decide(probabilities=curve, points=info["points"], as_of=as_of,
                                       confidence=case["conf"], evidence_max_cut=case["max_cut"],
                                       regular_cents=case["regular"],
                                       current_price_cents=case["regular"] * (100 - case["cut"]) // 100,
                                       regular_mismatch=False, no_history=nh, preferences=prefs, rule=rule)
        except Exception as exc:  # noqa: BLE001
            out[(app, as_of)] = f"{type(exc).__name__}: {exc}"
    return out


def score(decs):
    by_app = defaultdict(dict)
    for (app, as_of), d in decs.items():
        if not isinstance(d, str):
            by_app[app][as_of] = _Compact(d.group, d.sweet_pct)
    scores = {}
    for (app, as_of), d in decs.items():
        if isinstance(d, str):
            continue
        series = games[app].series["TW"]
        st = series.state_at(as_of)
        now_price = st.regular_cents * (100 - st.cut) // 100
        scores[("fixed", app, as_of)] = follow_advice(series, as_of, d, now_price_cents=now_price)
        scores[("monthly", app, as_of)] = follow_advice_monthly(series, as_of, schedule, by_app[app],
                                                                now_price_cents=now_price)
    return scores


def as_result(scores, rule, cost):
    return {"cases": case_rows(scores), "preferences": {"wait_cost_twd": cost} if cost is not None else {},
            "dataset": {"dataset_id": data["dataset_id"], "split": {"name": "tuning"}},
            "model": {"name": "seasonal-record", "version": "1.0.0", "params": {}},
            "rule": {"name": "sweet-price", "version": rule}}


def option_calibration(decs):
    rows = []
    for (app, as_of), d in decs.items():
        if isinstance(d, str) or d.group == "now" or d.expected is None or d.expected.target_pct is None:
            continue
        points = per_as_of[as_of]["points"]
        end = points[d.deadline_index - 1].end
        series = games[app].series["TW"]
        if series.known_until is None or series.known_until < end:
            continue
        first = series.first_crossings(as_of, [d.expected.target_pct])[d.expected.target_pct]
        case = cases[(app, as_of)]
        seen = case["max_cut"] is not None and d.confidence == "normal" and d.basis == "own" \
            and d.expected.target_pct <= case["max_cut"]
        rows.append((d.expected.reach_probability, first is not None and first <= end, d.confidence, d.basis, seen,
                     case["sales"], d.deadline_index, app, as_of))
    return rows


def opt_table(rows, title):
    p = np.array([r[0] for r in rows])
    y = np.array([r[1] for r in rows], float)
    out = [f"### {title}：選中選項「到期前達到」（{len(rows):,} 個可評估的等待決策）\n",
           "| 分組 | 決策數 | 預測 → 實際 |\n|---|---|---|",
           f"| 全部 | {len(rows):,} | {p.mean():.1%} → {y.mean():.1%} |"]
    groups = [("一般信心、本身曲線", lambda r: r[2] == "normal" and r[3] == "own"),
              ("低信心或沒有本身歷史的曲線", lambda r: not (r[2] == "normal" and r[3] == "own")),
              ("目標是見過的等級", lambda r: r[4]),
              ("目標比過去更深", lambda r: r[2] == "normal" and r[3] == "own" and not r[4]),
              ("本身場數 1（一般信心）", lambda r: r[2] == "normal" and r[5] == 1),
              ("本身場數 2–5（一般信心）", lambda r: r[2] == "normal" and 2 <= r[5] <= 5),
              ("本身場數 6+（一般信心）", lambda r: r[2] == "normal" and r[5] >= 6),
              ("最晚等到第 1 場", lambda r: r[6] == 1), ("最晚等到第 2–3 場", lambda r: 2 <= r[6] <= 3),
              ("最晚等到第 4 場以後", lambda r: r[6] >= 4)]
    for name, sel in groups:
        m = np.array([sel(r) for r in rows])
        if m.any():
            out.append(f"| {name} | {m.sum():,} | {p[m].mean():.1%} → {y[m].mean():.1%} |")
    out.append("\n| 預測（0.1 一組） | 決策數 | 預測 → 實際 |\n|---|---|---|")
    for lo, n, pm, am in bins(p, y):
        out.append(f"| {lo:.1f}–{lo + 0.1:.1f} | {n:,} | {pm:.1%} → {am:.1%} |")
    return "\n".join(out)


P21, P31 = Preferences(), Preferences(wait_cost_twd=20)
runs = {}
for variant in (None, "global", "by_conf"):
    t1 = time.monotonic()
    d21, d31 = run("2.1.0", P21, variant), run("3.1.0", P31, variant)
    s21, s31 = score(d21), score(d31)
    runs[variant] = {"d21": d21, "d31": d31, "r21": as_result(s21, "2.1.0", None), "r31": as_result(s31, "3.1.0", 20)}
    print(f"variant {variant}: {time.monotonic() - t1:.0f}s; errors 2.1.0 "
          f"{sum(isinstance(d, str) for d in d21.values())}, 3.1.0 {sum(isinstance(d, str) for d in d31.values())}")

# parity with production
for rule, key in (("2.1.0", "r21"), ("3.1.0", "r31")):
    prod = json.loads(PROD[rule].read_text(encoding="utf-8"))
    mine = runs[None][key]["cases"]
    same = [list(r) for r in prod["cases"]] == [list(r) for r in mine]
    print(f"parity {rule}: production cases {len(prod['cases'])}, prototype {len(mine)}, identical {same}")

base = runs[None]["r21"]
lines = ["\n## 3b. 規則 2.1.0 的決策改變（和原始曲線的 2.1.0 相比）\n",
         "| 版本 | 分組改變 | 甜蜜價改變 | 甜蜜時點改變 | 現在買 / 即將 / 繼續等 / 低信心 |", "|---|---|---|---|---|"]
d0 = runs[None]["d21"]
for variant in (None, "global", "by_conf"):
    dv = runs[variant]["d21"]
    g = pc = ti = 0
    groups = Counter()
    for key, a in d0.items():
        b = dv[key]
        if isinstance(a, str) or isinstance(b, str):
            continue
        groups[b.group] += 1
        g += a.group != b.group
        pc += a.sweet_pct != b.sweet_pct
        ti += a.sweet_index != b.sweet_index
    n = len(d0)
    lines.append(f"| {variant or '原始'} | {g:,}（{g / n:.1%}） | {pc:,}（{pc / n:.1%}） | {ti:,}（{ti / n:.1%}） | "
                 f"{groups['now']:,} / {groups['soon']:,} / {groups['wait']:,} / {groups['low']:,} |")

lines += ["\n## 3c. 淨效益（每月重新評估；和原始曲線的 2.1.0 成對比較；依遊戲重抽樣 2,000 次）\n",
          "| 候選 | c | 決策數 | 多省 | 多等（天） | 淨效益 | 2.1.0 原始（同一批）多省／多等／淨效益 | 差距 [95% 區間] |", "|---|---|---|---|---|---|---|---|"]
for variant in (None, "global", "by_conf"):
    for key, rule, cost_list in (("r21", "2.1.0", (0, 20)), ("r31", "3.1.0", (0, 20))):
        if variant is None and key == "r21":
            continue
        for c in cost_list:
            a = dict(base, preferences={"wait_cost_twd": c})
            b = dict(runs[variant][key], preferences={"wait_cost_twd": c})
            nc = net_comparison(a, b, default_cost=-1)["modes"]["monthly"]
            lines.append(f"| {rule} {variant or '原始'} | {c} | {nc['n']:,} | {nc['b']['saving']:.1f} | "
                         f"{nc['b']['wait_days']:.1f} | {nc['b']['net']:.1f} | "
                         f"{nc['a']['saving']:.1f}／{nc['a']['wait_days']:.1f}／{nc['a']['net']:.1f} | "
                         f"{nc['diff']:+.1f} [{nc['ci'][0]:+.1f}, {nc['ci'][1]:+.1f}] |")
lines.append("\n2.1.0 原始的淨效益同一批決策：c = 0 / 20 見上表的「多省」與基準；")
print("\n".join(lines))

print()
for variant in (None, "global", "by_conf"):
    print(opt_table(option_calibration(runs[variant]["d31"]), f"3.1.0 c=20，{variant or '原始'}"))
    print()
print(f"total {time.monotonic() - t_start:.0f}s")
