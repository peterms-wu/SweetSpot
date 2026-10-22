"""008 plan R0.2 (tuning split, cutoff 2026-09-25): candidate grid vs seasonal-record 1.0.0, TW region.

Game-weighted Brier (002 scoring, each game equal weight, game-paired resampling 2,000x, seed from the dataset id),
overall and by the unit's own TW record count at as_of (0 = low-confidence group, 1, 2, 3-5, 6+).
FR-004: groups 2 / 3-5 / 6+ must not be significantly worse (interval lower bound <= 0).
FR-009 condition 2 (proxy on tuning): groups 0 and 1 lower (point estimate). FR-008 step 3: lowest overall.
Finished-only: overall Brier, the p >= 0.7 excess, and predicted - actual for groups 0 and 1.
"""

import sys
from pathlib import Path

import numpy as np
from ulib import OUT, load

raw = load()
u0 = raw["units"]
seed = int(raw["dataset_id"][:8], 16)
GROUPS = [("全部", np.ones(len(u0["p"]), bool)), ("0 場（低信心）", u0["sales"] == 0), ("1 場", u0["sales"] == 1),
          ("2 場", u0["sales"] == 2), ("3–5 場", (u0["sales"] >= 3) & (u0["sales"] <= 5)), ("6 場以上", u0["sales"] >= 6)]
off_ok = u0["off"] >= 0
y_off = u0["off"].astype(float)


def per_game(p, sel):
    m = off_ok & sel
    apps, inv = np.unique(u0["app"][m], return_inverse=True)
    return apps, np.bincount(inv, weights=(p[m] - y_off[m]) ** 2) / np.bincount(inv)


base = {name: per_game(u0["p"], sel) for name, sel in GROUPS}


def diff(p, name, sel):
    apps, b1 = per_game(p, sel)
    _, b0 = base[name]
    d = b1 - b0
    rng = np.random.default_rng(seed)
    boots = d[rng.integers(0, len(d), (2000, len(d)))].mean(axis=1)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return b1.mean(), d.mean(), lo, hi


files = sorted(OUT.glob("cand_*.pkl"), key=lambda f: f.name) + sorted(OUT.glob("cache_shrink*.pkl"))
rows, summary = [], []
print("基準 1.0.0（002 計分、每款同權重）：" + "、".join(f"{n} {base[n][1].mean():.4f}（{len(base[n][0])} 款）"
                                             for n, _ in GROUPS) + "\n")
print("| 候選 | 全部 | 0 場 | 1 場 | 2 場 | 3–5 場 | 6 場以上 | FR-004 | FR-009② | 已結束 Brier | ≥0.7 高估 | 0 場 預測−實際 | 1 場 預測−實際 |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
fin_ok = u0["fin"] >= 0
y_fin = u0["fin"].astype(float)
for label, p in [("1.0.0", u0["p"])] + [(f.stem, load(f.name)["units"]) for f in files]:
    if not isinstance(p, np.ndarray):
        v = p
        assert (v["app"] == u0["app"]).all() and (v["off"] == u0["off"]).all() and (v["j"] == u0["j"]).all()
        p = v["p"]
    cells, res = [], {}
    for name, sel in GROUPS:
        b, dm, lo, hi = diff(p, name, sel)
        res[name] = (dm, lo, hi)
        cells.append("—" if label == "1.0.0" else f"{dm:+.4f} [{lo:+.4f}, {hi:+.4f}]")
    fr004 = all(res[n][1] <= 0 for n in ("2 場", "3–5 場", "6 場以上"))
    fr009 = res["0 場（低信心）"][0] < 0 and res["1 場"][0] < 0
    fb = ((p - y_fin) ** 2)[fin_ok].mean()
    hi7 = fin_ok & (p >= 0.7)
    gap = lambda m: (p[m].mean() - y_fin[m].mean()) * 100  # noqa: E731
    print(f"| {label} | " + " | ".join(cells) + f" | {'✓' if fr004 else '✗'} | {'✓' if fr009 else '✗'} | {fb:.4f} | "
          f"{gap(hi7):+.1f} | {gap(fin_ok & (u0['sales'] == 0)):+.1f} | {gap(fin_ok & (u0['sales'] == 1)):+.1f} |")
