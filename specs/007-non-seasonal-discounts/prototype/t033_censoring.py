"""T033 (spec FR-018): seasonal-record calibration under three ways of scoring, full TW dataset, cutoff 2026-09-25.

1. official  : the 002 framework — "occurred" counts once it happened, even before the sale ended; "not occurred"
               waits for the sale to end (unfinished ones are censored).
2. finished  : only units whose sale ended within the known history (the outcome is known either way).
3. seasonal  : like 2, but only seasonal sales count as reaching the level (what the model is built to predict).
Also: in the finished units, the share of "occurred" units whose first crossing was outside seasonal sales.
Read-only; writes out/t033_censoring.json.
"""
import json
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from steamsage.forecast.backtest.dataset import build_dataset
from steamsage.forecast.backtest.scoring import actual_sales, unit_outcome, window_points
from steamsage.forecast.engine import all_apps, is_paid_at, load_games, predict_one
from steamsage.forecast.evidence import game_evidence, population_view
from steamsage.forecast.models import current_model
from steamsage.forecast.salepoints import sale_points
from steamsage.store.query import PriceStore

CUTOFF = datetime(2026, 9, 25, tzinfo=UTC)
TOL = timedelta(days=1)
t0 = time.perf_counter()
store = PriceStore.open(Path("data/steamsage.db"))
games = load_games(store, all_apps(store), CUTOFF)
events = store.calendar_events()
rd = build_dataset(store, games, events, cutoff=CUTOFF, regions=("TW",)).regions["TW"]
seasonal = sorted((e.start, e.end) for e in events if e.kind == "seasonal")
actual = actual_sales(events)
model = current_model()
levels = list(range(5, 100, 5))


def in_seasonal(t):
    return any(s - TOL <= t < e for s, e in seasonal)


def present(a, as_of):
    return games[a].series["TW"].first_start <= as_of and is_paid_at(games[a], as_of)


bins = {k: defaultdict(lambda: [0, 0.0, 0]) for k in ("official", "finished", "seasonal")}
first_ns = defaultdict(lambda: [0, 0])          # bin -> [occurred finished units, first crossing non-seasonal]
for as_of in rd.schedule:
    apps = [a for a in rd.apps if present(a, as_of)]
    points = sale_points([e for e in events if e.start <= as_of], as_of)
    window = window_points(points, as_of, "TW")
    if not apps or not window:
        continue
    model.prepare(population_view((games[a] for a in apps), as_of, "TW"))
    fw = points.index(window[0])
    for a in apps:
        g = games[a]
        series = g.series["TW"]
        fc = predict_one(model, game_evidence(g, as_of, "TW"), points)
        if isinstance(fc, str):
            continue
        firsts = series.first_crossings(as_of, levels)
        outs = [o for o in g.outcomes.get("TW", ()) if o.start > as_of]
        for k, p in enumerate(window):
            act = actual.get(p.sale_key)
            for j, d in enumerate(levels):
                o = unit_outcome(firsts[d], act, series.known_until, p.end)
                if o not in ("occurred", "not-occurred"):
                    continue
                prob = fc.probabilities[fw + k][j]
                b = min(int(prob * 10), 9)
                hit = o == "occurred"
                for key, ok, value in (("official", True, hit),):
                    x = bins[key][b]
                    x[0] += 1
                    x[1] += prob
                    x[2] += value
                if act is None or series.known_until < act.end:
                    continue
                x = bins["finished"][b]
                x[0] += 1
                x[1] += prob
                x[2] += hit
                seasonal_hit = any(q.max_cut >= d and q.end <= act.end for q in outs)
                y = bins["seasonal"][b]
                y[0] += 1
                y[1] += prob
                y[2] += seasonal_hit
                if hit:
                    first_ns[b][0] += 1
                    first_ns[b][1] += not in_seasonal(firsts[d])
out = {"dataset": rd.dataset_id[:8], "games": len(rd.apps), "cutoff": "2026-09-25",
       "calibration": {key: {f"{b / 10:.1f}": {"n": v[0], "predicted": round(v[1] / v[0], 3),
                                               "actual": round(v[2] / v[0], 3)} for b, v in sorted(t.items())}
                       for key, t in bins.items()},
       "occurred_first_non_seasonal": {f"{b / 10:.1f}": round(v[1] / v[0], 3) for b, v in sorted(first_ns.items()) if v[0]},
       "seconds": round(time.perf_counter() - t0, 1)}
(Path(__file__).parent / "out" / "t033_censoring.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
print(json.dumps(out, indent=1))
