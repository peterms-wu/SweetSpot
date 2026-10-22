"""Stage 4: groups and hit rates when the sweet timing = first sale with P(>= target) >= 50% (else the deadline);
fallback 'regular' vs 'current' on the wishlist."""

import pickle
import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from proto_eval import MONTH_DAYS, ROOT, decide3, d2_ns  # noqa: E402

from steamsage.config import Preferences  # noqa: E402
from steamsage.decision.engine import run_decisions  # noqa: E402
from steamsage.forecast.engine import load_games  # noqa: E402
from steamsage.forecast.models import current_model  # noqa: E402
from steamsage.store.query import PriceStore  # noqa: E402
from steamsage.timeutil import add_months, now_utc  # noqa: E402

CS = [10, 20, 30, 50]


def main():
    data = pickle.load(open(HERE / "cache_tuning.pkl", "rb"))
    cases, schedule, apps = data["cases"], data["schedule"], data["apps"]
    ptsmap = cases.pop("_points")
    store = PriceStore.open(ROOT / "data" / "steamsage.db", ROOT / "data" / "steam_sales.toml")
    games = load_games(store, apps, data["cutoff"], regions=("TW",))

    print("| 變體 | 現在買 | 即將到價 | 繼續等 | 低信心 | 即將到價 到價率 | 繼續等 到價率 | 甜蜜時點：下一場 / 1 年內 |")
    print("|---|---|---|---|---|---|---|---|")
    for name, spec in [("2.0.0", None)] + [(f"3.0.0 {fb} c={c}", (fb, c)) for fb in ("regular", "current") for c in CS]:
        g = Counter()
        hits = Counter()
        tim = Counter()
        for (app, t), case in cases.items():
            pts, nh = ptsmap[t]
            d = d2_ns(case["d2"], pts) if spec is None else decide3(case, ptsmap[t], nh, spec[1] * 100, spec[0])
            case.pop("_ex", None)
            if d is None:
                continue
            g[d.group] += 1
            if d.group in ("now",):
                continue
            T = d.K if spec is None else d.T
            tim["next" if T == 1 else "later"] += 1
            if d.group not in ("soon", "wait"):
                continue
            end = t + timedelta(days=pts[T - 1][1] * MONTH_DAYS)
            series = games[app].series["TW"]
            first = series.first_crossings(t, [d.sweet_pct])[d.sweet_pct]
            if first is not None and first <= end and (series.known_until is None or first <= series.known_until):
                hits[(d.group, "hit")] += 1
            elif series.known_until is not None and series.known_until >= end:
                hits[(d.group, "miss")] += 1

        def rate(gr):
            h, m = hits[(gr, "hit")], hits[(gr, "miss")]
            return f"{h / (h + m):.1%}（{h + m}）" if h + m else "—"
        print(f"| {name} | {g['now']} | {g['soon']} | {g['wait']} | {g['low']} | {rate('soon')} | {rate('wait')} | "
              f"{tim['next']} / {tim['later']} |")

    now = now_utc()
    batch = run_decisions(store, store.wishlist_apps(), now, current_model(), Preferences(), now=now, rule="2.0.0")
    store.close()
    fc = {g.app_id: g for g in batch.forecast.games}
    nh = batch.forecast.no_history.probabilities if batch.forecast.no_history else None
    nh_flat = [p for row in nh for p in row] if nh else None
    rows = []
    for d in batch.decisions:
        if d.status != "ok" or d.current.price_cents is None:
            continue
        g = fc[d.app_id]
        pts = [((p.start - now).total_seconds() / 86400 / MONTH_DAYS, (p.end - now).total_seconds() / 86400 / MONTH_DAYS,
                p.end <= add_months(now, 12), p.end <= add_months(now, 24), p.label, p.sale_key) for p in g.points]
        case = {"curve": [p for row in g.probabilities for p in row],
                "conf": "low" if "regular-mismatch" in d.tags else g.confidence,
                "regular": d.regular_cents, "price": d.current.price_cents, "npts": len(g.points)}
        rows.append((d, pts, {(fb, c): decide3(case, (pts, nh_flat), nh_flat, c * 100, fb)
                              for fb in ("regular", "current") for c in CS}))
    print("\n願望清單\n\n| 變體 | 現在買 | 即將到價 | 繼續等 | 低信心 |\n|---|---|---|---|---|")
    g2 = Counter(d.group for d, _, _ in rows)
    print(f"| 2.0.0 | {g2['now']} | {g2['soon']} | {g2['wait']} | {g2['low']} |")
    for fb in ("regular", "current"):
        for c in CS:
            g = Counter(r[(fb, c)].group for _, _, r in rows)
            print(f"| {fb} c={c} | {g['now']} | {g['soon']} | {g['wait']} | {g['low']} |")

    def fmt(r, pts):
        if r.group == "now":
            return "現在買"
        return (f"{pts[r.T - 1][4]} -{r.sweet_pct}%（{r.PT:.0%}），最晚 {pts[r.K - 1][4]}；期望省 {r.esave / 100:.0f}、"
                f"等 {r.ewait:.1f} 月、淨 {r.net / 100:.0f}")
    print("\nc=30：regular 與 current 不同的遊戲\n")
    for d, pts, r in rows:
        a, b = r[("regular", 30)], r[("current", 30)]
        if (a.group, a.sweet_pct, a.K) != (b.group, b.sweet_pct, b.K):
            print(f"- {d.name}（原價 {d.regular_cents // 100}、現價 {d.current.price_cents // 100}）：regular {fmt(a, pts)}；current {fmt(b, pts)}")
    print("\nc=30 regular 全部\n")
    for d, pts, r in sorted(rows, key=lambda x: -x[0].regular_cents):
        old = "現在買" if d.group == "now" else f"{d.sweet_point.label} -{d.sweet_pct}%"
        print(f"- {d.name[:24]}（{d.regular_cents // 100}/{d.current.price_cents // 100}）2.0.0 {old}（{d.group}）→ "
              f"{fmt(r[('regular', 30)], pts)}（{r[('regular', 30)].group}）")


if __name__ == "__main__":
    main()
