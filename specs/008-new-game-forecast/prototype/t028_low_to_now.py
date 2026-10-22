"""T028: which rule 2.1.0 decisions change group between seasonal-record 1.0.0 and 1.1.0 {new-split, 0.5} on the
VALIDATION split (cutoff 2026-09-25), and why. Production decisions_at; read-only."""

import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(r"〈專案資料夾〉")
sys.path.insert(0, str(ROOT / "src"))
from steamsage.config import Preferences  # noqa: E402
from steamsage.decision.backtest import decisions_at  # noqa: E402
from steamsage.forecast.backtest.dataset import build_dataset  # noqa: E402
from steamsage.forecast.backtest.scoring import window_points  # noqa: E402
from steamsage.forecast.engine import all_apps, is_paid_at, load_games  # noqa: E402
from steamsage.forecast.evidence import population_view  # noqa: E402
from steamsage.forecast.models import build_model  # noqa: E402
from steamsage.forecast.salepoints import sale_points  # noqa: E402
from steamsage.store.query import PriceStore  # noqa: E402

CUTOFF = datetime(2026, 9, 25, tzinfo=UTC)
store = PriceStore.open(ROOT / "data" / "steamsage.db", ROOT / "data" / "steam_sales.toml")
games = load_games(store, all_apps(store), CUTOFF)
events = store.calendar_events()
rd = build_dataset(store, games, events, cutoff=CUTOFF, regions=("TW",), split="validation").regions["TW"]
store.close()
models = {"1.0.0": build_model("seasonal-record@1.0.0", {}),
          "1.1.0": build_model("seasonal-record@1.1.0", {"low_base": "new-split", "shrink": 0.5})}
moves, examples, total = Counter(), [], 0
for as_of in rd.schedule:
    present = [a for a in rd.apps if games[a].series["TW"].first_start <= as_of and is_paid_at(games[a], as_of)]
    points = sale_points([e for e in events if e.start <= as_of], as_of)
    if not present or not window_points(points, as_of, "TW"):
        continue
    pool = [a for a in rd.population_apps if games[a].series["TW"].first_start <= as_of and is_paid_at(games[a], as_of)]
    out = {}
    for name, model in models.items():
        model.prepare(population_view((games[a] for a in pool), as_of, "TW"))
        out[name] = decisions_at(games, present, as_of, points, model, Preferences(), rule="2.1.0")
    for app in present:
        a, b = out["1.0.0"][app], out["1.1.0"][app]
        if isinstance(a, str) or isinstance(b, str):
            continue
        total += 1
        if a.group != b.group:
            st = games[app].series["TW"].state_at(as_of)
            key = (a.group, b.group, a.confidence, st.cut > 0)
            moves[key] += 1
            if sum(1 for e in examples if e[0][:2] == key[:2]) < 3:
                examples.append((key, app, as_of, st.cut, a.p_min_pct, b.p_min_pct, a.sweet_pct, b.sweet_pct,
                                 a.sweet_index, b.sweet_index, a.basis, b.basis, b.confidence,
                                 len([o for o in games[app].outcomes.get("TW", ()) if o.end <= as_of]),
                                 a.sweet_probability, b.sweet_probability))
print(f"驗證組決策 {total:,}；分組改變 {sum(moves.values()):,}\n")
print("| 改變 | 信心（1.0.0） | 分析時點正在打折 | 決策數 |\n|---|---|---|---|")
for (g1, g2, conf, disc), n in moves.most_common():
    print(f"| {g1} → {g2} | {conf} | {'是' if disc else '否'} | {n:,} |")
print("\n例子：app、分析時點、本身場數、現價折扣、P_min、甜蜜價、甜蜜時點（第幾場）與機率、曲線來源、1.1.0 的信心")
for key, app, as_of, cut, p0, p1, s0, s1, i0, i1, b0, b1, c1, n, q0, q1 in examples:
    print(f"- {key[0]} → {key[1]}：app {app}、{as_of:%Y-%m}、本身 {n} 場、現價 -{cut}%、P_min -{p0}% → -{p1}%、"
          f"甜蜜價 -{s0}% → -{s1}%、時點 {i0} → {i1}（{q0 or 0:.0%} → {q1 or 0:.0%}）、來源 {b0} → {b1}、信心 {c1}")
