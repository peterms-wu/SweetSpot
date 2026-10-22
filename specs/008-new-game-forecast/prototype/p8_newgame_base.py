"""008 plan R0.1b (tuning split, cutoff 2026-09-25): a "new game" base for games without own TW records.

Population sequences (only records ended before as_of): a game's TW seasonal records in order, kept when its first
record started at most 365 days after its release (a new game then). Pre-release sequences: the first record started
before the release date.
  B2n  first-record share, later sales population share (p7)
  B4   per-index shares s_i (i-th record of new-game sequences, i <= 4, then population), 1 - prod(1 - s_i)
  B5   empirical cumulative: among new-game sequences with >= k records, share whose max of the first k >= d
       (k > available: carry the last value up; monotone in k and d)
  B6   B5 with separate sequences for targets not yet released at as_of (pre-release first record) vs released
Scored on the tuning units of low-confidence games, game-weighted Brier (002 scoring) and finished-only.
"""

import sys
import time
from datetime import timedelta
from pathlib import Path

import numpy as np
from ulib import load

ROOT = Path(r"〈專案資料夾〉")
sys.path.insert(0, str(ROOT / "src"))
from steamsage.forecast.backtest.dataset import build_dataset  # noqa: E402
from steamsage.forecast.contract import LEVELS  # noqa: E402
from steamsage.forecast.engine import all_apps, is_paid_at, load_games  # noqa: E402
from steamsage.forecast.evidence import population_view  # noqa: E402
from steamsage.store.query import PriceStore  # noqa: E402

NEW_DAYS = 365
MIN_SEQ = 30          # fewer sequences with >= k records: carry the previous k (and fall back to all new games)
t0 = time.monotonic()
data = load()
u = data["units"]
cases, per_as_of, schedule, cutoff = data["cases"], data["per_as_of"], data["schedule"], data["cutoff"]
store = PriceStore.open(ROOT / "data" / "steamsage.db", ROOT / "data" / "steam_sales.toml")
games = load_games(store, all_apps(store), cutoff)
events = store.calendar_events()
rd = build_dataset(store, games, events, cutoff=cutoff, regions=("TW",), split="tuning").regions["TW"]
release = {a: store.facts(a, cutoff).release_date.value for a in rd.population_apps}
store.close()
L = np.array(LEVELS)


def cumulative(seqs, K):
    """[k][j]: share of sequences with >= k records whose max of the first k >= d; monotone; carry when thin."""
    out = np.zeros((K, len(L)))
    prev = None
    for k in range(1, K + 1):
        ms = [max(s[:k]) for s in seqs if len(s) >= k]
        if len(ms) >= MIN_SEQ:
            row = (np.array(ms)[:, None] >= L[None, :]).mean(axis=0)
            prev = row if prev is None else np.maximum(prev, row)
        out[k - 1] = prev if prev is not None else 0
    return out


curves, info = {}, {}
for ti, as_of in enumerate(schedule):
    low = [a for (a, t), c in cases.items() if t == as_of and not isinstance(c, str) and c["conf"] == "low"]
    if not low:
        continue
    pool = [a for a in rd.population_apps if games[a].series["TW"].first_start <= as_of and is_paid_at(games[a], as_of)]
    pv = population_view((games[a] for a in pool), as_of, "TW")
    K = len(per_as_of[as_of]["points"])
    allcuts = [o.max_cut for h in pv.sale_history.values() for o in h.get("TW", ())]
    s_all = (np.array(allcuts)[:, None] >= L[None, :]).mean(axis=0)
    new, pre, post = [], [], []
    for a, h in pv.sale_history.items():
        tw = h.get("TW", ())
        r = release.get(a)
        if not tw or r is None or tw[0].start.date() - r > timedelta(days=NEW_DAYS):
            continue
        seq = [o.max_cut for o in tw]
        new.append(seq)
        (pre if tw[0].start.date() < r else post).append(seq)
    s_i = []
    for i in range(4):
        cuts = [s[i] for s in new if len(s) > i]
        s_i.append((np.array(cuts)[:, None] >= L[None, :]).mean(axis=0) if len(cuts) >= MIN_SEQ else s_all)
    kk = np.arange(1, K + 1)[:, None]
    b2n = 1 - (1 - s_i[0][None, :]) * (1 - s_all[None, :]) ** (kk - 1)
    surv, rows = np.ones(len(L)), []
    for k in range(K):
        surv = surv * (1 - (s_i[k] if k < 4 else s_all))
        rows.append(1 - surv)
    b4 = np.array(rows)
    b5 = cumulative(new, K)
    b5_pre, b5_post = cumulative(pre, K), cumulative(post, K)
    for a in low:
        r = release.get(a)
        unreleased = r is not None and r > as_of.date()
        curves[(ti, a)] = {"B0": np.array(cases[(a, as_of)]["curve"]), "B2n": b2n, "B4": b4, "B5": b5,
                           "B6": b5_pre if unreleased else b5_post}
        info[(ti, a)] = unreleased
    print(f"{as_of:%Y-%m} low {len(low)}; new seqs {len(new)} (pre {len(pre)}, post {len(post)}); "
          f"s1 {s_i[0][9]:.2f} s2 {s_i[1][9]:.2f} s3 {s_i[2][9]:.2f}; B5 k1..3 at -50%: "
          f"{' '.join(f'{b5[k][9]:.2f}' for k in range(min(3, K)))}; pre k1 {b5_pre[0][9]:.2f} post k1 {b5_post[0][9]:.2f}",
          flush=True)

sel = np.nonzero(u["conf"] == 1)[0]
keys = list(zip(u["t"][sel].tolist(), u["app"][sel].tolist()))
bases = ("B0", "B2n", "B4", "B5", "B6")
P = {b: np.array([curves[k][b][kk, jj] for k, kk, jj in zip(keys, u["k"][sel], u["j"][sel])]) for b in bases}
unrel = np.array([info[k] for k in keys])
appv = u["app"][sel]


def gw(p, y, apps):
    _, inv = np.unique(apps, return_inverse=True)
    return (np.bincount(inv, weights=(p - y) ** 2) / np.bincount(inv)).mean()


for key, title in (("off", "002 計分"), ("fin", "只計已結束")):
    yv = u[key][sel]
    ok = yv >= 0
    print(f"\n## 低信心單位，{title}（預測平均／每款同權重 Brier）\n")
    print("| 分組 | 單位數 | 實際 | " + " | ".join(bases) + " |\n|---|---|---|" + "---|" * len(bases))
    for name, m0 in (("全部", np.ones(len(sel), bool)), ("已發行", ~unrel), ("尚未發行", unrel)):
        m = ok & m0
        y = yv[m].astype(float)
        print(f"| {name} | {m.sum():,} | {y.mean():.3f} | "
              + " | ".join(f"{P[b][m].mean():.3f}／{gw(P[b][m], y, appv[m]):.4f}" for b in bases) + " |")
    # calibration of the best candidates by horizon (first window point vs later)
yv = u["fin"][sel]
ok = yv >= 0
print("\n## 只計已結束，依預測機率（B0 → B5 → B6）\n\n| 預測（原始分組） | 單位數 | 實際 | B0 | B5 | B6 |\n|---|---|---|---|---|---|")
b = np.minimum((P["B6"] * 10).astype(int), 9)
for i in range(10):
    m = ok & (b == i)
    if m.any():
        print(f"| B6 {i / 10:.1f}–{(i + 1) / 10:.1f} | {m.sum():,} | {yv[m].mean():.3f} | {P['B0'][m].mean():.3f} | "
              f"{P['B5'][m].mean():.3f} | {P['B6'][m].mean():.3f} |")
print(f"\ntotal {time.monotonic() - t0:.0f}s")
