"""008 first step, part 1: seasonal-record calibration on the tuning split under two scorings, by group.

official = 002 framework (occurred counts as soon as it happens; not-occurred waits for the sale to end)
finished = only units whose sale ended inside the known history (both outcomes judged the same way)
"""

import numpy as np
from ulib import bins, fmt_row, load, summary

data = load()
u = data["units"]
print(f"dataset {data['dataset_id'][:8]}, cutoff {data['cutoff']:%Y-%m-%d}, units {len(u['p']):,}\n")

GROUPS = [
    ("全部", lambda: np.ones(len(u["p"]), bool)),
    ("期間 0–3 個月", lambda: u["hg"] == 0),
    ("期間 3–6 個月", lambda: u["hg"] == 1),
    ("期間 6–12 個月", lambda: u["hg"] == 2),
    ("信心 normal", lambda: u["conf"] == 0),
    ("信心 low", lambda: u["conf"] == 1),
    ("見過的等級（d ≤ 過去最深）", lambda: u["seen"] == 1),
    ("比過去更深", lambda: u["seen"] == 0),
    ("本身場數 1", lambda: (u["sales"] == 1) & (u["conf"] == 0)),
    ("本身場數 2", lambda: (u["sales"] == 2) & (u["conf"] == 0)),
    ("本身場數 3–5", lambda: (u["sales"] >= 3) & (u["sales"] <= 5) & (u["conf"] == 0)),
    ("本身場數 6+", lambda: (u["sales"] >= 6) & (u["conf"] == 0)),
    ("見過的等級 × 場數 1", lambda: (u["seen"] == 1) & (u["sales"] == 1)),
    ("見過的等級 × 場數 2–5", lambda: (u["seen"] == 1) & (u["sales"] >= 2) & (u["sales"] <= 5)),
    ("見過的等級 × 場數 6+", lambda: (u["seen"] == 1) & (u["sales"] >= 6)),
    ("比過去更深 × 期間 0–3", lambda: (u["seen"] == 0) & (u["hg"] == 0)),
    ("比過去更深 × 期間 6–12", lambda: (u["seen"] == 0) & (u["hg"] == 2)),
    ("預測 = 1.0（只有 1 場時見過的等級）", lambda: u["p"] >= 0.9999),
]

for key, title in (("off", "現行（002 框架）"), ("fin", "只計特賣已結束的單位")):
    ok = u[key] >= 0
    print(f"## {title}\n")
    print("| 分組 | 單位數 | 預測平均 → 實際 | Brier | 預測 ≥ 0.7 的高估（百分點，單位數） |\n|---|---|---|---|---|")
    for name, sel in GROUPS:
        m = ok & sel()
        print(fmt_row(name, summary(u["p"][m], u[key][m].astype(float))))
    print("\n| 預測機率 | 單位數 | 預測 → 實際 | 差（百分點） |\n|---|---|---|---|")
    for lo, n, pm, am in bins(u["p"][ok], u[key][ok].astype(float)):
        print(f"| {lo:.1f}–{lo + 0.1:.1f} | {n:,} | {pm:.3f} → {am:.3f} | {(am - pm) * 100:+.1f} |")
    print()

# where does the high-bin overconfidence (finished scoring, p >= 0.7) sit? share of units and of the excess
ok = u["fin"] >= 0
hi = ok & (u["p"] >= 0.7)
exc = u["p"] - u["fin"]
tot = exc[hi].sum()
print("## 只計已結束、預測 ≥ 0.7：高估集中在哪裡\n")
print("| 分組 | 佔單位 | 佔高估總量 | 高估（百分點） |\n|---|---|---|---|")
for name, sel in GROUPS[1:]:
    m = hi & sel()
    if m.any():
        print(f"| {name} | {m.sum() / hi.sum():.1%} | {exc[m].sum() / tot:.1%} | {exc[m].mean() * 100:+.1f} |")

# the as_of effect: finished units exist only for early as_of; compare early as_of under both scorings
print("\n## 依分析時點（兩種計分都有的單位：特賣已結束）\n")
print("| 分析時點 | 單位數 | 預測 → 002 實際 | 預測 → 已結束實際 | 預測 ≥ 0.7 的高估（已結束） |\n|---|---|---|---|---|")
for ti, t in enumerate(data["schedule"]):
    m = ok & (u["t"] == ti)
    if not m.any():
        continue
    s = summary(u["p"][m], u["fin"][m].astype(float))
    mo = m & (u["off"] >= 0)
    hi_gap = "—" if s["hi_gap"] is None else f"{s['hi_gap'] * 100:+.1f}"
    print(f"| {t:%Y-%m} | {s['n']:,} | {u['p'][mo].mean():.3f} → {u['off'][mo].mean():.3f} | "
          f"{s['pred']:.3f} → {s['act']:.3f} | {hi_gap} |")
