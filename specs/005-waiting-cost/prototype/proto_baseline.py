"""Stage 5: simple reference rule 'next sale' vs 3.0.0 (regular fallback) vs 2.0.0, monthly re-evaluation, tuning."""

import pickle
import sys
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from proto_eval import LEVELS, MONTH_DAYS, NL, ROOT, boot, d2_ns, decide3, monthly, price_at  # noqa: E402

from steamsage.forecast.engine import load_games  # noqa: E402
from steamsage.store.query import PriceStore  # noqa: E402

CS = [0, 10, 20, 30, 50, 80]


def next_sale(case):
    row = case["curve"][:NL]
    d = max((lv for lv, p in zip(LEVELS, row) if p >= 0.5), default=0)
    if d == 0 or price_at(case["regular"], d) >= case["price"]:
        return SimpleNamespace(group="now", sweet_pct=0)
    return SimpleNamespace(group="soon", sweet_pct=d)


def main():
    data = pickle.load(open(HERE / "cache_tuning.pkl", "rb"))
    cases, schedule, apps = data["cases"], data["schedule"], data["apps"]
    ptsmap = cases.pop("_points")
    store = PriceStore.open(ROOT / "data" / "steamsage.db", ROOT / "data" / "steam_sales.toml")
    games = load_games(store, apps, data["cutoff"], regions=("TW",))
    store.close()
    idx = {t: i for i, t in enumerate(schedule)}
    rules = {"2.0.0": lambda case, t: d2_ns(case["d2"], ptsmap[t][0]), "next": lambda case, t: next_sale(case)}
    for c in CS[1:]:
        rules[f"3.0.0 c={c}"] = (lambda cc: lambda case, t: decide3(case, ptsmap[t], ptsmap[t][1], cc * 100, "regular"))(c)
    out = {}
    for name, fn in rules.items():
        decs = {}
        for (app, t), case in cases.items():
            d = fn(case, t)
            case.pop("_ex", None)
            if d is not None:
                decs[(app, t)] = d
        res = {}
        for (app, t0) in decs:
            r = monthly(games[app].series["TW"], t0, idx[t0], schedule, decs, app, cases[(app, t0)]["price"])
            if r is not None:
                res[(app, t0)] = r
        out[name] = res
    common = set.intersection(*(set(r) for r in out.values()))
    print(f"共同評估數 {len(common)}\n")
    print("| 規則 | 平均多省 | 平均多等（天） | " + " | ".join(f"淨效益 c={c}" for c in CS) + " |")
    print("|---|---|---|" + "---|" * len(CS))
    for name, res in out.items():
        s = sum(res[k][0] for k in common) / len(common) / 100
        w = sum(res[k][1] for k in common) / len(common)
        print(f"| {name} | {s:.0f} | {w:.0f} | " + " | ".join(f"{s - c * w / MONTH_DAYS:.1f}" for c in CS) + " |")
    print("\n3.0.0(c) − 下一場就買（同一個 c）\n\n| c | 差距 [95% 區間] |\n|---|---|")
    for c in CS[1:]:
        pg = defaultdict(lambda: [0.0, 0])
        for k in common:
            a, b = out["next"][k], out[f"3.0.0 c={c}"][k]
            pg[k[0]][0] += (b[0] / 100 - c * b[1] / MONTH_DAYS) - (a[0] / 100 - c * a[1] / MONTH_DAYS)
            pg[k[0]][1] += 1
        m, lo, hi = boot(pg, reps=400)
        print(f"| {c} | {m:+.1f} [{lo:+.1f}, {hi:+.1f}] |")


if __name__ == "__main__":
    main()
