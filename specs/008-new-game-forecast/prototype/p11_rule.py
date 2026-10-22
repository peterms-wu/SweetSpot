"""008 plan R0.4 (tuning split, cutoff 2026-09-25): rule 2.1.0 with each candidate's curves vs seasonal-record 1.0.0.

Decisions with the production decide(); monthly re-evaluation and fixed follow-advice with the production scorers;
net-benefit difference with the production net_comparison (game-paired, 2,000 resamples). Hit rates per group with
the production score_case. The raw run is checked against the production backtest-rule cases.

uv run --with numpy python p11_rule.py cand_new_split_a0npop.pkl [...]
"""

import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from ulib import load

ROOT = Path(r"〈專案資料夾〉")
sys.path.insert(0, str(ROOT / "src"))
from steamsage.config import Preferences  # noqa: E402
from steamsage.decision.backtest import (_Compact, case_rows, follow_advice, follow_advice_monthly,  # noqa: E402
                                         score_case)
from steamsage.decision.compare_rule import net_comparison  # noqa: E402
from steamsage.decision.rule import decide  # noqa: E402
from steamsage.forecast.backtest.scoring import actual_sales, window_points  # noqa: E402
from steamsage.forecast.engine import all_apps, load_games  # noqa: E402
from steamsage.store.query import PriceStore  # noqa: E402

t0 = time.monotonic()
raw = load()
schedule = raw["schedule"]
store = PriceStore.open(ROOT / "data" / "steamsage.db", ROOT / "data" / "steam_sales.toml")
games = load_games(store, all_apps(store), raw["cutoff"], regions=("TW",))
actual = actual_sales(store.calendar_events())
store.close()
PREFS = Preferences()


def decisions(data):
    out = {}
    for (app, as_of), case in data["cases"].items():
        info = data["per_as_of"][as_of]
        out[(app, as_of)] = decide(probabilities=case["curve"], points=info["points"], as_of=as_of,
                                   confidence=case["conf"], evidence_max_cut=case["max_cut"],
                                   regular_cents=case["regular"],
                                   current_price_cents=case["regular"] * (100 - case["cut"]) // 100,
                                   regular_mismatch=False, no_history=info["no_history"], preferences=PREFS,
                                   rule="2.1.0")
    return out


def evaluate(data, decs):
    by_app = defaultdict(dict)
    for (app, as_of), d in decs.items():
        by_app[app][as_of] = _Compact(d.group, d.sweet_pct)
    scores, hits = {}, defaultdict(Counter)
    for (app, as_of), d in decs.items():
        series = games[app].series["TW"]
        st = series.state_at(as_of)
        now = st.regular_cents * (100 - st.cut) // 100
        scores[("fixed", app, as_of)] = follow_advice(series, as_of, d, now_price_cents=now)
        scores[("monthly", app, as_of)] = follow_advice_monthly(series, as_of, schedule, by_app[app],
                                                                now_price_cents=now)
        points = data["per_as_of"][as_of]["points"]
        cs = score_case(series, as_of, d, points, window_points(points, as_of, "TW"), actual,
                        regular_cents=st.regular_cents, current_cut=st.cut)
        hits[d.group][cs.outcome] += 1
    res = {"cases": case_rows(scores), "preferences": {"wait_cost_twd": 20},
           "dataset": {"dataset_id": raw["dataset_id"], "split": {"name": "tuning"}},
           "model": {"name": "x", "version": "x", "params": {}}, "rule": {"name": "sweet-price", "version": "2.1.0"}}
    return res, hits


def rate(c):
    return c["hit"] / (c["hit"] + c["miss"]) if c["hit"] + c["miss"] else float("nan")


d0 = decisions(raw)
r0, h0 = evaluate(raw, d0)
prod = sorted(ROOT.glob("data/backtests/*sweet-price-2.1.0_seasonal-record-1.0.0_b5c69b_TW_858b3147.json"))[-1]
same = [list(r) for r in json.loads(prod.read_text(encoding="utf-8"))["cases"]] == [list(r) for r in r0["cases"]]
print(f"parity with production 2.1.0 tuning backtest: {same}")
print("\n| 候選 | 分組改變 | 甜蜜價改變 | 現在買／即將／繼續等／低信心 | 到價率 即將／繼續等／低信心 | 淨效益差距 c=0 | c=20 |")
print("|---|---|---|---|---|---|---|")
g0 = Counter(d.group for d in d0.values())
print(f"| 1.0.0 | — | — | {g0['now']:,}／{g0['soon']:,}／{g0['wait']:,}／{g0['low']:,} | "
      f"{rate(h0['soon']):.1%}／{rate(h0['wait']):.1%}／{rate(h0['low']):.1%} | — | — |")
for name in sys.argv[1:]:
    data = load(name)
    d1 = decisions(data)
    r1, h1 = evaluate(data, d1)
    g1 = Counter(d.group for d in d1.values())
    ch = sum(d1[k].group != d0[k].group for k in d0)
    sp = sum(d1[k].sweet_pct != d0[k].sweet_pct for k in d0)
    nets = []
    for c in (0, 20):
        nc = net_comparison(dict(r0, preferences={"wait_cost_twd": c}), dict(r1, preferences={"wait_cost_twd": c}),
                            default_cost=-1)["modes"]["monthly"]
        nets.append(f"{nc['diff']:+.1f} [{nc['ci'][0]:+.1f}, {nc['ci'][1]:+.1f}]")
    print(f"| {Path(name).stem} | {ch:,}（{ch / len(d0):.1%}） | {sp:,}（{sp / len(d0):.1%}） | "
          f"{g1['now']:,}／{g1['soon']:,}／{g1['wait']:,}／{g1['low']:,} | "
          f"{rate(h1['soon']):.1%}／{rate(h1['wait']):.1%}／{rate(h1['low']):.1%} | {nets[0]} | {nets[1]} |")
print(f"\ntotal {time.monotonic() - t0:.0f}s")
