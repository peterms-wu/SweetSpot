"""Feature 005 prototype, stage 1: forecast every (tuning game, as_of) once with the current model and cache
what the waiting-cost rule needs. Validation games are never read.

uv run python proto_cache.py [--split tuning] -> cache_<split>.pkl
"""

import argparse
import pickle
import sys
import time
from array import array
from pathlib import Path

ROOT = Path(r"〈專案資料夾〉")
sys.path.insert(0, str(ROOT / "src"))

from steamsage.config import Preferences  # noqa: E402
from steamsage.decision.rule import decide  # noqa: E402
from steamsage.forecast.backtest.dataset import build_dataset, default_cutoff  # noqa: E402
from steamsage.forecast.backtest.scoring import window_points  # noqa: E402
from steamsage.forecast.engine import all_apps, is_paid_at, load_games, no_history_curve, predict_one  # noqa: E402
from steamsage.forecast.evidence import game_evidence, population_view  # noqa: E402
from steamsage.forecast.models import current_model  # noqa: E402
from steamsage.forecast.salepoints import sale_points  # noqa: E402
from steamsage.store.query import PriceStore  # noqa: E402
from steamsage.timeutil import add_months  # noqa: E402

MONTH_DAYS = 365 / 12


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="tuning")
    args = ap.parse_args()
    t0 = time.monotonic()
    store = PriceStore.open(ROOT / "data" / "steamsage.db", ROOT / "data" / "steam_sales.toml")
    cutoff = default_cutoff(store)
    games = load_games(store, all_apps(store), cutoff)
    events = store.calendar_events()
    dataset = build_dataset(store, games, events, cutoff=cutoff, regions=("TW",), split=args.split)
    store.close()
    rd = dataset.regions["TW"]
    print(f"load {time.monotonic() - t0:.0f}s; games {len(rd.apps)}; as_of {len(rd.schedule)}", flush=True)
    model = current_model()
    prefs = Preferences()
    cases = {}          # (app, as_of) -> dict
    for n, as_of in enumerate(rd.schedule, 1):
        present = [a for a in rd.apps if games[a].series["TW"].first_start <= as_of and is_paid_at(games[a], as_of)]
        points = sale_points([e for e in events if e.start <= as_of], as_of)
        if not present or not window_points(points, as_of, "TW"):
            continue
        pool = present if rd.population_apps == rd.apps else \
            [a for a in rd.population_apps if games[a].series["TW"].first_start <= as_of and is_paid_at(games[a], as_of)]
        model.prepare(population_view((games[a] for a in pool), as_of, "TW"))
        nh = no_history_curve(model, as_of, points)
        nh_flat = array("d", [p for row in nh.probabilities for p in row]) if nh else None
        pts = [((p.start - as_of).total_seconds() / 86400 / MONTH_DAYS, (p.end - as_of).total_seconds() / 86400 / MONTH_DAYS,
                p.end <= add_months(as_of, 12), p.end <= add_months(as_of, 24), p.label, p.sale_key) for p in points]
        for app in present:
            f = predict_one(model, game_evidence(games[app], as_of, "TW"), points)
            if isinstance(f, str):
                continue
            st = games[app].series["TW"].state_at(as_of)
            price = st.regular_cents * (100 - st.cut) // 100
            try:
                r2 = decide(probabilities=f.probabilities, points=points, as_of=as_of, confidence=f.confidence,
                            evidence_max_cut=f.evidence.get("max_cut"), regular_cents=st.regular_cents,
                            current_price_cents=price, regular_mismatch=False,
                            no_history=nh.probabilities if nh else None, preferences=prefs, rule="2.0.0")
                d2 = (r2.group, r2.sweet_pct, r2.sweet_index, r2.confidence, r2.basis)
            except Exception as exc:  # noqa: BLE001
                d2 = ("error", str(exc))
            cases[(app, as_of)] = {
                "curve": array("d", [p for row in f.probabilities for p in row]), "conf": f.confidence,
                "regular": st.regular_cents, "price": price, "cut": st.cut, "d2": d2, "npts": len(points)}
        cases.setdefault("_points", {})[as_of] = (pts, nh_flat)
        print(f"{n}/{len(rd.schedule)} {as_of:%Y-%m-%d} {len(present)} games {time.monotonic() - t0:.0f}s", flush=True)
    out = Path(__file__).with_name(f"cache_{args.split}.pkl")
    with open(out, "wb") as fh:
        pickle.dump({"cases": cases, "schedule": rd.schedule, "apps": rd.apps, "cutoff": cutoff,
                     "dataset_id": rd.dataset_id}, fh)
    print("saved", out, f"{time.monotonic() - t0:.0f}s")


if __name__ == "__main__":
    main()
