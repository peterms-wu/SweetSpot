"""P2 (plan, research R0.3; spec FR-020): how much could a rule that uses non-seasonal promotions gain? Tuning only.

Follow the advice with monthly re-evaluation (005 FR-011; the library function, so the baseline is the real metric):
- V0  rule 2.1.0 as is.
- V1  "non-seasonal record": when the deepest non-seasonal promotion of the past 365 days (TW, floored to 5) is
      deeper than P_min, it becomes P_min and the same tolerance gives the sweet level; a buy-now whose current cut
      is shallower than the new sweet level becomes a wait.
- V2  "timing only": the sweet sale may be a non-seasonal promotion. Following the advice buys at the first time the
      price reaches the sweet level whatever the label says, so V2 = V0 by construction (checked here).
- V3  hindsight ceiling: the lowest price within 12 months (needs the full 12 months).
"""
import json
import random
import sys
import time
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from nslib import CUTOFF, GameNS, Windows  # noqa: E402

from steamsage.config import Preferences
from steamsage.decision.backtest import MONTH_DAYS, _Compact, follow_advice_monthly
from steamsage.decision.rule import _tolerance, decide, price_cents
from steamsage.forecast.backtest.dataset import build_dataset
from steamsage.forecast.engine import all_apps, is_paid_at, load_games, no_history_curve, predict_one
from steamsage.forecast.evidence import game_evidence, population_view
from steamsage.forecast.models import current_model
from steamsage.forecast.salepoints import sale_points
from steamsage.store.query import PriceStore
from steamsage.timeutil import add_months

OUT = Path(__file__).parent / "out" / "p2_rule_bound.json"
T0 = time.perf_counter()
store = PriceStore.open(Path("data/steamsage.db"))
games = load_games(store, all_apps(store), CUTOFF, regions=("TW", "US"))
events = store.calendar_events()
rd = build_dataset(store, games, events, cutoff=CUTOFF, regions=("TW",), split="tuning").regions["TW"]
win = Windows([(e.start, e.end) for e in events if e.kind == "seasonal"])
ns = {a: GameNS(games[a].series["TW"], win) for a in rd.apps}
model, prefs = current_model(), Preferences()


def present(a, as_of):
    return games[a].series["TW"].first_start <= as_of and is_paid_at(games[a], as_of)


dec = {"V0": defaultdict(dict), "V1": defaultdict(dict)}
cases = []
for as_of in rd.schedule:
    pts = sale_points([e for e in events if e.start <= as_of], as_of)
    pool = [a for a in rd.population_apps if present(a, as_of)]
    model.prepare(population_view((games[a] for a in pool), as_of, "TW"))
    nohist = no_history_curve(model, as_of, pts)
    for a in rd.apps:
        if not present(a, as_of):
            continue
        fc = predict_one(model, game_evidence(games[a], as_of, "TW"), pts)
        if isinstance(fc, str):
            continue
        state = games[a].series["TW"].state_at(as_of)
        now_price = state.regular_cents * (100 - state.cut) // 100
        try:
            r = decide(probabilities=fc.probabilities, points=pts, as_of=as_of, confidence=fc.confidence,
                       evidence_max_cut=fc.evidence.get("max_cut"), regular_cents=state.regular_cents,
                       current_price_cents=now_price, regular_mismatch=False,
                       no_history=nohist.probabilities if nohist else None, preferences=prefs)
        except Exception:  # noqa: BLE001
            continue
        dec["V0"][a][as_of] = _Compact(r.group, r.sweet_pct)
        record = max((c for t, c in ns[a].promos if as_of - timedelta(days=365) < t <= as_of), default=0)
        record -= record % 5
        pct = r.sweet_pct
        if record > r.p_min_pct:          # the record becomes P_min; the same tolerance gives the sweet level
            _, tol, _ = _tolerance(state.regular_cents, record, prefs)
            target = price_cents(state.regular_cents, record) + tol
            pct = min(d for d in range(5, 100, 5) if price_cents(state.regular_cents, d) <= target)
            pct = max(pct, r.sweet_pct)
        group = r.group
        if pct > r.sweet_pct:
            group = "now" if state.cut >= pct else ("wait" if r.group == "now" else r.group)
        dec["V1"][a][as_of] = _Compact(group, pct)
        cases.append((a, as_of, now_price, pct > r.sweet_pct))
print(f"decisions {len(cases)} ({time.perf_counter() - T0:.0f}s)", flush=True)


def price(s):
    return s.regular_cents * (100 - s.cut) // 100


rows = defaultdict(dict)       # (app, as_of) -> variant -> (saving, wait)
for a, as_of, now_price, changed in cases:
    series = games[a].series["TW"]
    for v in ("V0", "V1"):
        s = follow_advice_monthly(series, as_of, rd.schedule, dec[v][a], now_price_cents=now_price)
        if not s.censored:
            rows[(a, as_of)][v] = (s.saving_cents, s.wait_days)
    horizon = add_months(as_of, 12)
    if series.known_until and series.known_until >= horizon:
        low = min([now_price] + [price(s) for s in series.states if as_of < s.start <= horizon and s.regular_cents])
        rows[(a, as_of)]["V3"] = (now_price - low, None)
    rows[(a, as_of)]["changed"] = changed


def summary(keys, v, ref="V0", cost=20):
    both = [k for k in keys if all(x in rows[k] for x in ("V0", "V1")) and (v != "V3" or "V3" in rows[k])]
    sav = [rows[k][v][0] / 100 for k in both]
    out = {"n": len(both), "saving_mean": round(sum(sav) / len(sav), 1) if sav else None}
    if v != "V3":
        waits = [rows[k][v][1] for k in both]
        nets = [rows[k][v][0] / 100 - cost * rows[k][v][1] / MONTH_DAYS
                - (rows[k][ref][0] / 100 - cost * rows[k][ref][1] / MONTH_DAYS) for k in both]
        out["wait_mean"] = round(sum(waits) / len(waits), 1)
        per_game = defaultdict(list)
        for k, x in zip(both, nets):
            per_game[k[0]].append(x)
        # per-decision mean difference, games resampled in pairs (005 FR-013)
        games_ = list(per_game)
        rng = random.Random(11)
        means = []
        for _ in range(2000):
            pick = rng.choices(games_, k=len(games_))
            vals = [x for g in pick for x in per_game[g]]
            means.append(sum(vals) / len(vals))
        means.sort()
        out[f"net_diff_c{cost}"] = [round(sum(nets) / len(nets), 2), round(means[50], 2), round(means[1949], 2)]
    return out


keys = list(rows)
changed = [k for k in keys if rows[k]["changed"]]
result = {
    "decisions": len(cases), "changed_by_V1": len(changed),
    "all": {v: summary(keys, v) for v in ("V0", "V1")},
    "changed_only": {v: summary(changed, v) for v in ("V0", "V1")},
    "ceiling_full12": {"V0": summary([k for k in keys if "V3" in rows[k]], "V0"),
                       "V3": summary([k for k in keys if "V3" in rows[k]], "V3")},
    "seconds": round(time.perf_counter() - T0, 1),
    "v0_cases": sorted([a, t.strftime("%Y-%m-%d"), r["V0"][0], r["V0"][1]] for (a, t), r in rows.items() if "V0" in r),
}
OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps({k: v for k, v in result.items() if k != "v0_cases"}, ensure_ascii=False, indent=1))
