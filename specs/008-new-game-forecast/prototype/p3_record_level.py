"""008 first step, diagnosis: is the overconfidence at the game's own record depth M (d = M)?

Unit level (finished-sale scoring, normal confidence): by M - d and by the first window point vs later.
Option level (3.1.0 c=20, raw): is the chosen target equal to M?
"""

import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from ulib import load

ROOT = Path(r"〈專案資料夾〉")
sys.path.insert(0, str(ROOT / "src"))
from steamsage.forecast.contract import LEVELS  # noqa: E402

data = load()
u = data["units"]
cases, schedule = data["cases"], data["schedule"]
lv = np.array(LEVELS)[u["j"]]
mc = np.array([(cases[(a, schedule[t])]["max_cut"] if cases[(a, schedule[t])]["max_cut"] is not None else -1)
               for a, t in zip(u["app"], u["t"])])
ok = (u["fin"] >= 0) & (u["conf"] == 0)
y = u["fin"].astype(float)
gap = mc - lv
first_pt = np.zeros(len(lv), bool)
# first window point of each (t, app): smallest k among its units
kmin = defaultdict(lambda: 99)
for t, a, k in zip(u["t"], u["app"], u["k"]):
    kmin[(t, a)] = min(kmin[(t, a)], k)
first_pt = np.array([k == kmin[(t, a)] for t, a, k in zip(u["t"], u["app"], u["k"])])


def row(name, m):
    m = ok & m
    if not m.any():
        return
    print(f"| {name} | {m.sum():,} | {u['p'][m].mean():.3f} → {y[m].mean():.3f} | "
          f"{(u['p'][m].mean() - y[m].mean()) * 100:+.1f} |")


print("## 單位層級（只計已結束、一般信心）：和過去最深 M 的距離\n")
print("| 分組 | 單位數 | 預測 → 實際 | 高估（百分點） |\n|---|---|---|---|")
for name, m in (("d = M（剛好是過去最深）", gap == 0), ("d = M − 5", gap == 5), ("d = M − 10", gap == 10),
                ("d = M − 15～−25", (gap >= 15) & (gap <= 25)), ("d ≤ M − 30", gap >= 30),
                ("d = M + 5（比過去深一級）", gap == -5), ("d ≥ M + 10", gap <= -10)):
    row(name, m)
print("\n只看下一場（每個分析時點的第一個窗口時點）：\n")
print("| 分組 | 單位數 | 預測 → 實際 | 高估（百分點） |\n|---|---|---|---|")
for name, m in (("d = M", gap == 0), ("d = M − 5", gap == 5), ("d = M − 10", gap == 10), ("d ≤ M − 15", gap >= 15)):
    row(name + "，下一場", m & first_pt)
print("\nd = M、下一場，依本身場數：\n")
print("| 分組 | 單位數 | 預測 → 實際 | 高估（百分點） |\n|---|---|---|---|")
for name, m in (("1 場", u["sales"] == 1), ("2 場", u["sales"] == 2), ("3–5 場", (u["sales"] >= 3) & (u["sales"] <= 5)),
                ("6+ 場", u["sales"] >= 6)):
    row(f"d = M、下一場、{name}", m & first_pt & (gap == 0))
print("\nd = M、下一場，依預測機率：\n")
print("| 分組 | 單位數 | 預測 → 實際 | 高估（百分點） |\n|---|---|---|---|")
for lo, hi in ((0, 0.5), (0.5, 0.8), (0.8, 0.95), (0.95, 0.9999), (0.9999, 1.01)):
    row(f"d = M、下一場、預測 {lo:.2f}–{min(hi, 1):.2f}", first_pt & (gap == 0) & (u["p"] >= lo) & (u["p"] < hi))
