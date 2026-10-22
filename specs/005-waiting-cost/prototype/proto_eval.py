"""Feature 005 prototype, stage 2: waiting-cost rule (3.0.0 candidates) vs sweet-price 2.0.0 on the TUNING split.

uv run python proto_eval.py [--split tuning]
"""

import argparse
import pickle
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(r"〈專案資料夾〉")
sys.path.insert(0, str(ROOT / "src"))

from steamsage.decision.backtest import follow_advice  # noqa: E402
from steamsage.forecast.contract import LEVELS  # noqa: E402
from steamsage.forecast.engine import load_games  # noqa: E402
from steamsage.store.query import PriceStore  # noqa: E402
from steamsage.timeutil import add_months  # noqa: E402

MONTH_DAYS = 365 / 12
NL = len(LEVELS)
C_LIST = [0, 10, 20, 30, 50, 80, 120]
FALLBACKS = ["current", "regular", "maxbelow"]


def rows_of(flat, npts):
    return [flat[i * NL:(i + 1) * NL] for i in range(npts)]


def price_at(regular, pct):
    return regular * (100 - pct) // 100


def expectations(curve, pts, n, regular, price):
    """For each deadline K (0-based, < n), level j and fallback: (expected saving, expected wait months, P reach)."""
    out = {}   # (K, j) -> (P, E_paid_reached, E_wait_reached, {fb: (fb_price_given_miss)}, end_K)
    cum = [[0.0, 0.0, 0.0] for _ in range(NL)]   # per level: F_prev, E_paid part, E_wait part
    for K in range(n):
        row = curve[K]
        start, end = pts[K][0], pts[K][1]
        # max-below prefix: S(j) = sum_{x < level j} (G(x) - G(x+5)) * price(x), G(0)=1
        g = [1.0] + list(row)                       # g[0] = level 0, g[k] = level LEVELS[k-1]
        pre = [0.0]
        for k in range(NL):                          # contribution of level index k (0 = 0%)
            pct = 0 if k == 0 else LEVELS[k - 1]
            pre.append(pre[-1] + (g[k] - g[k + 1]) * price_at(regular, pct))
        for j in range(NL):
            F = row[j]
            c = cum[j]
            dp = F - c[0]
            if dp > 0:
                c[1] += dp * price_at(regular, LEVELS[j])
                c[2] += dp * start
                c[0] = F
            miss = 1.0 - c[0]
            maxbelow = pre[j + 1] / miss if miss > 1e-12 else 0.0     # levels 0..LEVELS[j]-5
            out[(K, j)] = (c[0], c[1], c[2], miss, end, maxbelow)
    return out


def decide3(case, ptsinfo, nh_flat, c, fb, horizon="12"):
    pts, _ = ptsinfo
    npts = case["npts"]
    col = {"12": 2, "24": 3}.get(horizon)
    n = sum(1 for p in pts if p[col]) if col else npts
    curve = rows_of(case["curve"], npts)
    conf = case["conf"]
    low = conf == "low"
    basis = "own"
    # same P_min = 0 path as 2.0.0: own curve without any level >= 50% within 12 months -> no-history curve, low
    n12 = sum(1 for p in pts if p[2])
    if n12 == 0:
        return None
    if not low and max((p for p in curve[n12 - 1]), default=0) < 0.5:
        if nh_flat is None:
            return None
        curve, low, basis = rows_of(nh_flat, npts), True, "no-history"
        n = n12            # no-history path keeps 12 months
    if low and basis == "own":
        n = n12            # low confidence keeps 12 months (as 2.0.0)
    regular, price = case["regular"], case["price"]
    key = (id(case), n, basis)
    ex = case.setdefault("_ex", {}).get(key)
    if ex is None:
        ex = expectations(curve, pts, n, regular, price)
        case["_ex"][key] = ex
    best_rows = []
    for K in range(n):
        best = None
        for j in range(NL):
            pd = price_at(regular, LEVELS[j])
            if pd >= price:
                continue
            P, epaid, ewait, miss, end, maxbelow = ex[(K, j)]
            fbp = {"current": price, "regular": regular, "maxbelow": maxbelow}[fb]
            e_paid = epaid + miss * fbp
            e_wait = ewait + miss * end
            net = (price - e_paid) - c * e_wait
            if best is None or net > best[0] + 1e-9:
                best = (net, j, K, P, price - e_paid, e_wait)
        best_rows.append(best)
    chosen = None
    for b in best_rows:
        if b is not None and b[0] > 1e-9 and (chosen is None or b[0] > chosen[0] + 1e-9):
            chosen = b
    if chosen is None:
        return SimpleNamespace(group="now", sweet_pct=0, K=0, confidence="low" if low else "normal", net=0.0,
                               key=None, esave=0.0, ewait=0.0, P=None)
    net, j, K, P, esave, ewait = chosen
    T = next((i for i in range(K + 1) if curve[i][j] >= 0.5), K)      # likely sale: first with P >= 50%, else deadline
    group = "low" if low else ("soon" if T == 0 else "wait")
    return SimpleNamespace(group=group, sweet_pct=LEVELS[j], K=K + 1, T=T + 1, confidence="low" if low else "normal",
                           net=net, key=pts[K][5], esave=esave, ewait=ewait, P=P, end=pts[K][1],
                           PT=curve[T][j])


def d2_ns(d2, pts):
    if d2[0] == "error":
        return None
    group, pct, idx, conf, basis = d2
    return SimpleNamespace(group=group, sweet_pct=pct, K=idx, confidence=conf, key=pts[idx - 1][5], end=pts[idx - 1][1])


def monthly(series, t0, s, schedule, decs, app, price0):
    horizon = add_months(t0, 12)
    known = series.known_until
    D = decs[(app, t0)]
    j = s
    while True:
        t = schedule[j]
        if D.group == "now":
            st = series.state_at(t)
            return price0 - price_at(st.regular_cents, st.cut), (t - t0).days
        nxt = schedule[j + 1] if j + 1 < len(schedule) and schedule[j + 1] < horizon else horizon
        first = series.first_crossings(t, [D.sweet_pct])[D.sweet_pct]
        if first is not None and first <= nxt and (known is None or first <= known):
            st = series.state_at(first)
            return price0 - price_at(st.regular_cents, st.cut), (first - t0).days
        if known is None or known < nxt:
            return None
        if nxt == horizon:
            st = series.state_at(horizon)
            return price0 - price_at(st.regular_cents, st.cut), (horizon - t0).days
        j += 1
        D = decs.get((app, schedule[j]), D)


def fixed(series, t0, D, price0):
    f = follow_advice(series, t0, SimpleNamespace(group=D.group, sweet_pct=D.sweet_pct), now_price_cents=price0)
    return None if f.censored else (f.saving_cents, f.wait_days)


def boot(pairs_by_game, reps=2000, seed=5):
    """Mean difference per decision; resample games. pairs_by_game: {app: [sum_diff, count]}"""
    games = list(pairs_by_game.values())
    tot = sum(g[0] for g in games) / sum(g[1] for g in games)
    rnd = random.Random(seed)
    k = len(games)
    stats = []
    for _ in range(reps):
        sd = sc = 0.0
        for _ in range(k):
            g = games[rnd.randrange(k)]
            sd += g[0]
            sc += g[1]
        stats.append(sd / sc)
    stats.sort()
    return tot, stats[int(0.025 * reps)], stats[int(0.975 * reps) - 1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="tuning")
    args = ap.parse_args()
    t_start = time.monotonic()
    data = pickle.load(open(Path(__file__).with_name(f"cache_{args.split}.pkl"), "rb"))
    cases, schedule, apps = data["cases"], data["schedule"], data["apps"]
    ptsmap = cases.pop("_points")
    store = PriceStore.open(ROOT / "data" / "steamsage.db", ROOT / "data" / "steam_sales.toml")
    games = load_games(store, apps, data["cutoff"], regions=("TW",))
    store.close()
    print(f"loaded {len(cases)} cases {time.monotonic() - t_start:.0f}s", flush=True)

    variants = {"2.0.0": None}
    for fb in FALLBACKS:
        for c in C_LIST:
            variants[f"3|{fb}|{c}"] = (fb, c)
    decs = {v: {} for v in variants}
    for (app, t), case in cases.items():
        pts, nh = ptsmap[t]
        d = d2_ns(case["d2"], pts)
        if d is not None:
            decs["2.0.0"][(app, t)] = d
        for v, spec in variants.items():
            if spec is None:
                continue
            r = decide3(case, ptsmap[t], nh, spec[1] * 100, spec[0])
            if r is not None:
                decs[v][(app, t)] = r
        case.pop("_ex", None)
    print(f"decided {time.monotonic() - t_start:.0f}s", flush=True)

    idx = {t: i for i, t in enumerate(schedule)}
    outcome = {}   # (variant, mode) -> {(app,t0): (saving_cents, wait_days)}
    for v in variants:
        for mode in ("monthly", "fixed"):
            res = {}
            for (app, t0), D in decs[v].items():
                series = games[app].series["TW"]
                price0 = cases[(app, t0)]["price"]
                r = monthly(series, t0, idx[t0], schedule, decs[v], app, price0) if mode == "monthly" \
                    else fixed(series, t0, D, price0)
                if r is not None:
                    res[(app, t0)] = r
            outcome[(v, mode)] = res
    print(f"followed {time.monotonic() - t_start:.0f}s", flush=True)

    # --- groups and timing
    print("\n## 分組（決策數）\n\n| 變體 | 決策 | 現在買 | 即將到價 | 繼續等 | 低信心 | 期望等待（月，非現在買） |\n|---|---|---|---|---|---|---|")
    for v in variants:
        g = Counter(d.group for d in decs[v].values())
        ew = [d.ewait for d in decs[v].values() if d.group != "now" and hasattr(d, "ewait")]
        print(f"| {v} | {len(decs[v])} | {g['now']} | {g['soon']} | {g['wait']} | {g['low']} | "
              f"{sum(ew) / len(ew) if ew else float('nan'):.1f} |")

    # --- follow the advice, common evaluated set per comparison
    for mode in ("monthly", "fixed"):
        print(f"\n## 照建議買（{mode}）：淨效益 = 多省 − c × 多等月數；3.0.0(c) 與 2.0.0 在同一個 c 下比較\n")
        print("| c | 變體 | 評估數 | 平均多省 | 平均多等（天） | 2.0.0 淨效益 | 3.0.0 淨效益 | 差距 [95% 區間] |\n|---|---|---|---|---|---|---|---|")
        base = outcome[("2.0.0", mode)]
        for c in C_LIST:
            for fb in FALLBACKS:
                v = f"3|{fb}|{c}"
                cand = outcome[(v, mode)]
                common = base.keys() & cand.keys()
                pg = defaultdict(lambda: [0.0, 0])
                s3 = w3 = n3b = 0.0
                sb = wb = 0.0
                for key in common:
                    sa, wa = base[key]
                    sc_, wc = cand[key]
                    na = sa / 100 - c * wa / MONTH_DAYS
                    nc = sc_ / 100 - c * wc / MONTH_DAYS
                    pg[key[0]][0] += nc - na
                    pg[key[0]][1] += 1
                    s3 += sc_; w3 += wc; sb += sa; wb += wa
                    n3b += na
                N = len(common)
                mean, lo, hi = boot(pg, reps=400)
                print(f"| {c} | {fb} | {N} | {s3 / N / 100:.0f}（2.0.0 {sb / N / 100:.0f}） | {w3 / N:.0f}（{wb / N:.0f}） | "
                      f"{n3b / N:.1f} | {n3b / N + mean:.1f} | {mean:+.1f} [{lo:+.1f}, {hi:+.1f}] |")
    print(f"\n耗時 {time.monotonic() - t_start:.0f}s")
    pickle.dump({"decs": {v: {k: vars(d) for k, d in dd.items()} for v, dd in decs.items()}, "outcome": outcome},
                open(Path(__file__).with_name(f"eval_{args.split}.pkl"), "wb"))


if __name__ == "__main__":
    main()
