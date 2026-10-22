"""Feature analysis for `seasonal-record` on the TUNING part only (feature 004 research R0.1; spec FR-004).

Usage: uv run python scripts/feature_analysis.py [--cutoff YYYY-MM-DD]

For every tuning game and every ended seasonal sale with at least 2 earlier ones: did it set a new record (deeper
than every earlier sale)? Rates by candidate feature, and how far records deepen. Read-only; prints Markdown.
The validation part is never read.
"""

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sweetspot.cli import _utf8_when_redirected  # noqa: E402
from sweetspot.commands import parse_moment  # noqa: E402
from sweetspot.forecast.backtest.dataset import build_dataset, default_cutoff  # noqa: E402
from sweetspot.forecast.engine import all_apps, load_games  # noqa: E402
from sweetspot.forecast.models.seasonal_record import M_GROUP_LABELS, f5, m_group  # noqa: E402
from sweetspot.store.query import PriceStore  # noqa: E402

MIN_PRIOR = 2


def rows(games, apps, region):
    for app in apps:
        cuts = [o.max_cut for o in games[app].outcomes.get(region, ())]
        years = [o.year for o in games[app].outcomes.get(region, ())]
        for i in range(MIN_PRIOR, len(cuts)):
            prior = cuts[:i]
            m = max(prior)
            first = prior.index(m)
            last = len(prior) - 1 - prior[::-1].index(m)
            tail = prior[-4:]
            slope = tail[-1] - tail[0]
            yield {
                "record": cuts[i] > m, "jump": min((f5(cuts[i]) - f5(m)) // 5, 5), "year": years[i],
                "過去最深": M_GROUP_LABELS[m_group(f5(m))],
                "距上次創新低": "4 場以上" if i - 1 - first >= 4 else f"{i - 1 - first} 場",
                "距上次達到最深": "4 場以上" if i - 1 - last >= 4 else f"{i - 1 - last} 場",
                "最近 4 場的趨勢": "加深" if slope > 0 else "持平" if slope == 0 else "變淺",
                "場數": "12 場以上" if i >= 12 else f"{i} 場",
            }


def table(data, key):
    agg = defaultdict(lambda: [0, 0])
    for r in data:
        agg[r[key]][0] += 1
        agg[r[key]][1] += r["record"]
    lines = [f"| {key} | 場數 | 創新低 |", "|---|---|---|"]
    order = M_GROUP_LABELS if key == "過去最深" else sorted(agg, key=lambda v: (len(v), v))
    for k in (k for k in order if k in agg):
        n, rec = agg[k]
        lines.append(f"| {k} | {n:,} | {rec / n:.1%} |")
    return "\n".join(lines)


def main() -> None:
    _utf8_when_redirected()
    parser = argparse.ArgumentParser()
    parser.add_argument("--cutoff")
    args = parser.parse_args()
    store = PriceStore.open(ROOT / "data" / "sweetspot.db", ROOT / "data" / "steam_sales.toml")
    try:
        cutoff = parse_moment(args.cutoff) if args.cutoff else default_cutoff(store)
        games = load_games(store, all_apps(store), cutoff)
        dataset = build_dataset(store, games, store.calendar_events(), cutoff=cutoff, split="tuning")
    finally:
        store.close()
    print(f"# 特徵分析（調參組，資料截止 {cutoff:%Y-%m-%d}）\n")
    for region in ("TW", "US"):
        data = list(rows(games, dataset.regions[region].apps, region))
        if region == "US":
            data = [r for r in data if r["year"] >= 2016]          # no daily deals (model definition, limit 5)
        n = len(data)
        rate = sum(r["record"] for r in data) / n if n else 0
        title = "台灣區" if region == "TW" else "美國區（2016 年起）"
        print(f"## {title}：{len(dataset.regions[region].apps):,} 款、{n:,} 場，創新低 {rate:.1%}\n")
        for key in ("過去最深", "距上次創新低", "距上次達到最深", "最近 4 場的趨勢", "場數"):
            print(table(data, key) + "\n")
        jumps = defaultdict(Counter)
        for r in data:
            if r["record"]:
                jumps[r["過去最深"]][r["jump"]] += 1
        print("| 過去最深 | 創新低時加深（每 5 個百分點一級） |\n|---|---|")
        for label in M_GROUP_LABELS:
            total = sum(jumps[label].values())
            if total:
                parts = "、".join(f"{j} 級 {c / total:.0%}" for j, c in sorted(jumps[label].items()))
                print(f"| {label} | {parts}（{total:,} 次） |")
        print()


if __name__ == "__main__":
    main()
