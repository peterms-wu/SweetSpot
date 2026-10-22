"""Feature 005 prototype, stage 3 (tuning split + current wishlist):
 A. calibration of the expected saving / wait of chosen 3.0.0 options vs what the exact policy realised
 B. FR-017: horizon 24 months / 5 years -> how many decisions pick a sale beyond 12 months
 C. stability: month-to-month change of the target sale before it started
 D. wishlist under several c
"""

import pickle
import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from proto_eval import (MONTH_DAYS, ROOT, decide3, d2_ns, price_at)  # noqa: E402

from steamsage.config import Preferences  # noqa: E402
from steamsage.decision.engine import run_decisions  # noqa: E402
from steamsage.forecast.engine import load_games  # noqa: E402
from steamsage.forecast.models import current_model  # noqa: E402
from steamsage.store.query import PriceStore  # noqa: E402
from steamsage.timeutil import add_months, now_utc  # noqa: E402

FB = "regular"
CS = [10, 20, 30, 50]


def main():
    data = pickle.load(open(HERE / "cache_tuning.pkl", "rb"))
    cases, schedule, apps = data["cases"], data["schedule"], data["apps"]
    ptsmap = cases.pop("_points")
    store = PriceStore.open(ROOT / "data" / "steamsage.db", ROOT / "data" / "steam_sales.toml")
    games = load_games(store, apps, data["cutoff"], regions=("TW",))

    # A. calibration: exact policy (d, K): buy at first crossing >= d before end of K, else at price at end of K
    print("## A. 期望值 vs 實際（調參組，選中的等待選項，照該選項本身行動）\n")
    print("| c | 等待決策數（可評估） | 預測期望多省 | 實際多省 | 預測期望等待（月） | 實際等待（月） | 預測達到機率 | 實際達到 |")
    print("|---|---|---|---|---|---|---|---|")
    for c in CS:
        n = 0
        ps = rs = pw = rw = pp = rp = 0.0
        for (app, t), case in cases.items():
            r = decide3(case, ptsmap[t], ptsmap[t][1], c * 100, FB)
            if r is None or r.group == "now":
                continue
            series = games[app].series["TW"]
            end = t + timedelta(days=r.end * MONTH_DAYS)
            if series.known_until is None or series.known_until < end:
                continue
            first = series.first_crossings(t, [r.sweet_pct])[r.sweet_pct]
            price0 = case["price"]
            if first is not None and first <= end:
                st = series.state_at(first)
                paid, wait, hit = price_at(st.regular_cents, st.cut), (first - t).days / MONTH_DAYS, 1
            else:
                st = series.state_at(end)
                paid, wait, hit = price_at(st.regular_cents, st.cut), r.end, 0
            n += 1
            ps += r.esave; rs += price0 - paid; pw += r.ewait; rw += wait; pp += r.P; rp += hit
        print(f"| {c} | {n} | {ps / n / 100:.0f} | {rs / n / 100:.0f} | {pw / n:.2f} | {rw / n:.2f} | {pp / n:.1%} | {rp / n:.1%} |")
        for (app, t), case in cases.items():
            case.pop("_ex", None)

    # B. horizons
    print("\n## B. 放寬範圍（調參組）：選到 12 個月以後的決策\n")
    print("| c | 範圍 | 決策數 | 選到 12 個月以後 | 其中平均期望等待（月） |\n|---|---|---|---|---|")
    for c in CS:
        for hz in ("24", "60"):
            n = beyond = 0
            ew = 0.0
            for (app, t), case in cases.items():
                pts = ptsmap[t][0]
                r = decide3(case, ptsmap[t], ptsmap[t][1], c * 100, FB, horizon=hz)
                if r is None:
                    continue
                n += 1
                if r.group != "now" and not pts[r.K - 1][2]:
                    beyond += 1
                    ew += r.ewait
            print(f"| {c} | {hz} 個月 | {n} | {beyond}（{beyond / n:.1%}） | {ew / beyond if beyond else 0:.1f} |")
            for case in cases.values():
                case.pop("_ex", None)

    # C. stability: at consecutive as_of, target sale changed although it had not started yet
    print("\n## C. 穩定度：下個月的決策改了目標特賣（而且原目標還沒開始）或改了分組（現在買↔等）\n")
    print("| 變體 | 相鄰月份的成對決策 | 目標特賣改變 | 現在買↔等待 互換 |\n|---|---|---|---|")
    idx = {t: i for i, t in enumerate(schedule)}
    variants = {"2.0.0": None, **{f"3.0.0 c={c}": c for c in CS}}
    for name, c in variants.items():
        decs = {}
        for (app, t), case in cases.items():
            pts, nh = ptsmap[t]
            decs[(app, t)] = d2_ns(case["d2"], pts) if c is None else decide3(case, ptsmap[t], nh, c * 100, FB)
            case.pop("_ex", None)
        pairs = moved = flip = 0
        for (app, t), d in decs.items():
            i = idx[t]
            if d is None or i + 1 >= len(schedule):
                continue
            t2 = schedule[i + 1]
            d2 = decs.get((app, t2))
            if d2 is None:
                continue
            pairs += 1
            if (d.group == "now") != (d2.group == "now"):
                flip += 1
            elif d.group != "now":
                start = t + timedelta(days=ptsmap[t][0][d.K - 1][0] * MONTH_DAYS)
                if start > t2 and d.key != d2.key:
                    moved += 1
        print(f"| {name} | {pairs} | {moved}（{moved / pairs:.1%}） | {flip}（{flip / pairs:.1%}） |")

    # D. wishlist
    now = now_utc()
    model = current_model()
    batch = run_decisions(store, store.wishlist_apps(), now, model, Preferences(), now=now, rule="2.0.0")
    store.close()
    fc = {g.app_id: g for g in batch.forecast.games}
    nh = batch.forecast.no_history.probabilities if batch.forecast.no_history else None
    nh_flat = [p for row in nh for p in row] if nh else None
    print("\n## D. 願望清單（現在）\n")
    rows = []
    for d in batch.decisions:
        if d.status != "ok" or d.current.price_cents is None:
            continue
        g = fc[d.app_id]
        pts = [((p.start - now).total_seconds() / 86400 / MONTH_DAYS, (p.end - now).total_seconds() / 86400 / MONTH_DAYS,
                p.end <= add_months(now, 12), p.end <= add_months(now, 24), p.label, p.sale_key) for p in g.points]
        case = {"curve": [p for row in g.probabilities for p in row], "conf": g.confidence,
                "regular": d.regular_cents, "price": d.current.price_cents, "npts": len(g.points)}
        if d.tags and "regular-mismatch" in d.tags:
            case["conf"] = "low"
        res = {}
        for c in CS:
            res[c] = decide3(case, (pts, nh_flat), nh_flat, c * 100, FB)
        res["24@30"] = decide3(case, (pts, nh_flat), nh_flat, 3000, FB, horizon="24")
        res["60@30"] = decide3(case, (pts, nh_flat), nh_flat, 3000, FB, horizon="60")
        rows.append((d, pts, res))
    print("| c | 現在買 | 即將到價 | 繼續等 | 低信心 |\n|---|---|---|---|---|")
    g2 = Counter(d.group for d, _, _ in rows)
    print(f"| 2.0.0 | {g2['now']} | {g2['soon']} | {g2['wait']} | {g2['low']} |")
    for c in CS:
        g = Counter(r[c].group for _, _, r in rows if r[c] is not None)
        print(f"| {c} | {g['now']} | {g['soon']} | {g['wait']} | {g['low']} |")
    for hz in ("24@30", "60@30"):
        beyond = sum(1 for _, pts, r in rows if r[hz] is not None and r[hz].group != "now" and not pts[r[hz].K - 1][2])
        print(f"\n範圍 {hz}：選到 12 個月以後的有 {beyond} 款")

    def fmt(r, pts):
        if r is None:
            return "—"
        if r.group == "now":
            return "現在買"
        return f"{pts[r.K - 1][4]} -{r.sweet_pct}%（P {r.P:.0%}，期望省 {r.esave / 100:.0f}、等 {r.ewait:.1f} 月）"

    print("\n| 遊戲 | 原價 | 現價 | 2.0.0 | " + " | ".join(f"c={c}" for c in CS) + " |")
    print("|---|---|---|---|" + "---|" * len(CS))
    for d, pts, res in sorted(rows, key=lambda x: -x[0].regular_cents):
        old = "現在買" if d.group == "now" else f"{d.sweet_point.label} -{d.sweet_pct}%"
        print(f"| {d.name[:22]} | {d.regular_cents // 100} | {d.current.price_cents // 100} | {old} | "
              + " | ".join(fmt(res[c], pts) for c in CS) + " |")


if __name__ == "__main__":
    main()
