"""Feature 008 first step, stage 0 (read-only, TUNING split only, cutoff 2026-09-25 explicit).

Forecast every (tuning game, as_of) once with the current model, exactly as run_rule_backtests does, and cache:
- per case: the full curve, confidence, own-sale evidence and the TW price state at as_of
- per as_of: the sale points and the no-history curve
- per scoring unit (window point x level): probability, 002 outcome, finished-sale outcome, actual sale end, groups
Validation games are never scored (they only enter the population share, as in every tuning backtest).

uv run --with numpy python p0_cache.py -> out/cache.pkl
"""

import argparse
import pickle
import sys
import time
from array import array
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(r"〈專案資料夾〉")
sys.path.insert(0, str(ROOT / "src"))

from steamsage.forecast.backtest.dataset import build_dataset  # noqa: E402
from steamsage.forecast.backtest.scoring import actual_sales, horizon_group, unit_outcome, window_points  # noqa: E402
from steamsage.forecast.contract import LEVELS  # noqa: E402
from steamsage.forecast.engine import all_apps, is_paid_at, load_games, no_history_curve, predict_one  # noqa: E402
from steamsage.forecast.evidence import game_evidence, population_view  # noqa: E402
from steamsage.forecast.models import current_model  # noqa: E402
from steamsage.forecast.salepoints import sale_points  # noqa: E402
from steamsage.store.query import PriceStore  # noqa: E402
from shrunk import Shrunk  # noqa: E402
from candidate import Candidate  # noqa: E402

CUTOFF = datetime(2026, 9, 25, tzinfo=UTC)
OUT = Path(__file__).parent / "out"
HG = {"0-3m": 0, "3-6m": 1, "6-12m": 2}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shrink", type=float, default=None, help="prior weight a (in sales) toward the population share")
    ap.add_argument("--cand", default=None, help="low_base,shrink_a,shrink_form,shrink_target (candidate.py)")
    ap.add_argument("--prod", default=None, help="low_base,shrink: the production seasonal-record 1.1.0 (T017)")
    args = ap.parse_args()
    t0 = time.monotonic()
    store = PriceStore.open(ROOT / "data" / "steamsage.db", ROOT / "data" / "steam_sales.toml")
    games = load_games(store, all_apps(store), CUTOFF)
    events = store.calendar_events()
    dataset = build_dataset(store, games, events, cutoff=CUTOFF, regions=("TW",), split="tuning")
    release = {a: store.facts(a, CUTOFF).release_date.value for a in dataset.regions["TW"].population_apps}
    store.close()
    rd = dataset.regions["TW"]
    print(f"load {time.monotonic() - t0:.0f}s; dataset {rd.dataset_id[:8]}; games {len(rd.apps)}; "
          f"population {len(rd.population_apps)}; as_of {len(rd.schedule)}", flush=True)
    actual = actual_sales(events)
    model = current_model() if args.shrink is None else Shrunk(args.shrink)
    if args.cand:
        lb, a, form, target = args.cand.split(",")
        model = Candidate(release, lb, float(a), form, target)
    if args.prod:
        from steamsage.forecast.models import build_model
        lb, a = args.prod.split(",")
        model = build_model("seasonal-record@1.1.0", {"low_base": lb, "shrink": a})
    cases, per_as_of = {}, {}
    u = {k: array(t) for k, t in (("t", "b"), ("app", "i"), ("k", "b"), ("j", "b"), ("p", "d"), ("off", "b"),
                                  ("fin", "b"), ("end", "d"), ("hg", "b"), ("conf", "b"), ("seen", "b"),
                                  ("sales", "h"))}
    errors = 0
    for ti, as_of in enumerate(rd.schedule):
        present = [a for a in rd.apps if games[a].series["TW"].first_start <= as_of and is_paid_at(games[a], as_of)]
        points = sale_points([e for e in events if e.start <= as_of], as_of)
        window = window_points(points, as_of, "TW")
        if not present or not window:
            continue
        pool = present if rd.population_apps == rd.apps else \
            [a for a in rd.population_apps if games[a].series["TW"].first_start <= as_of and is_paid_at(games[a], as_of)]
        model.prepare(population_view((games[a] for a in pool), as_of, "TW"))
        nh = no_history_curve(model, as_of, points)
        per_as_of[as_of] = {"points": points, "no_history": nh.probabilities if nh else None,
                            "window": [points.index(p) for p in window]}
        for app in present:
            g = games[app]
            f = predict_one(model, game_evidence(g, as_of, "TW"), points)
            if isinstance(f, str):
                cases[(app, as_of)] = f
                errors += 1
                continue
            st = g.series["TW"].state_at(as_of)
            cases[(app, as_of)] = {"curve": tuple(tuple(r) for r in f.probabilities), "conf": f.confidence,
                                   "max_cut": f.evidence.get("max_cut"), "sales": f.evidence.get("sales_used") or 0,
                                   "regular": st.regular_cents, "cut": st.cut}
            series = g.series["TW"]
            firsts = series.first_crossings(as_of, LEVELS)
            mc = f.evidence.get("max_cut")
            for p in window:
                k = points.index(p)
                act = actual.get(p.sale_key)
                fin_ok = act is not None and series.known_until is not None and series.known_until >= act.end
                hg = HG[horizon_group("TW", as_of, p.end)]
                for j, d in enumerate(LEVELS):
                    o = unit_outcome(firsts[d], act, series.known_until, p.end)
                    off = 1 if o == "occurred" else 0 if o == "not-occurred" else -1
                    fin = (1 if firsts[d] is not None and firsts[d] < act.end else 0) if fin_ok else -1
                    if off < 0 and fin < 0:
                        continue
                    u["t"].append(ti); u["app"].append(app); u["k"].append(k); u["j"].append(j)
                    u["p"].append(f.probabilities[k][j]); u["off"].append(off); u["fin"].append(fin)
                    u["end"].append(act.end.timestamp() if act is not None else -1.0)
                    u["hg"].append(hg); u["conf"].append(0 if f.confidence == "normal" else 1)
                    u["seen"].append(2 if mc is None or f.confidence == "low" else 1 if d <= mc else 0)
                    u["sales"].append(min(f.evidence.get("sales_used") or 0, 999))
        print(f"{ti + 1}/{len(rd.schedule)} {as_of:%Y-%m-%d} {len(present)} games, units {len(u['p'])}, "
              f"{time.monotonic() - t0:.0f}s", flush=True)
    OUT.mkdir(exist_ok=True)
    name = "cache.pkl" if args.shrink is None else f"cache_shrink{args.shrink:g}.pkl"
    if args.cand:
        name = f"cand_{model.tag}.pkl"
    if args.prod:
        name = f"prod_{args.prod.replace(',', '_')}.pkl"
    with open(OUT / name, "wb") as fh:
        pickle.dump({"cases": cases, "per_as_of": per_as_of, "units": {k: v.tobytes() for k, v in u.items()},
                     "unit_types": {k: v.typecode for k, v in u.items()}, "schedule": rd.schedule,
                     "apps": rd.apps, "dataset_id": rd.dataset_id, "cutoff": CUTOFF, "errors": errors}, fh)
    print(f"saved; model errors {errors}; {time.monotonic() - t0:.0f}s")


if __name__ == "__main__":
    main()
