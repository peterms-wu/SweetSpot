"""P0 (feature 007, before specify): quantify non-seasonal discounts on real data. Read-only, tuning split only.

A. Discount episodes (cut goes 0 -> >0 until back to 0) in the TW tuning games, classified by overlap with seasonal
   sales (else themed sales from the calendar, else "other"): frequency, depth, depth vs the game's own seasonal
   record, duration, interval regularity. US over the same period as a cross-check.
B. Forecast calibration (current model, TW 12-month window): how much of the "occurred" units were first reached
   outside seasonal sales, and the calibration if only seasonal sales counted.
C. Rule 2.1.0 follow-the-advice (monthly re-evaluation): where the purchase happened (seasonal / non-seasonal),
   how many bought earlier than the sweet sale; a "seasonal-only buyer" counterfactual; the 12-month low in hindsight.
"""
import json
import statistics as st
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from steamsage.config import Preferences
from steamsage.decision.backtest import follow_advice_monthly, _Compact
from steamsage.decision.rule import decide
from steamsage.forecast.backtest.dataset import build_dataset
from steamsage.forecast.backtest.scoring import actual_sales, unit_outcome, window_points
from steamsage.forecast.engine import all_apps, is_paid_at, load_games, no_history_curve, predict_one
from steamsage.forecast.evidence import game_evidence, population_view
from steamsage.forecast.models import current_model
from steamsage.forecast.salepoints import sale_points
from steamsage.store.query import PriceStore
from steamsage.timeutil import add_months

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "out" / "p0_out.json"
CUTOFF = datetime(2026, 9, 25, tzinfo=UTC)
TOL = timedelta(days=1)          # ITAD may record a sale start a few hours late / early
t_start = time.perf_counter()

store = PriceStore.open(Path("data/steamsage.db"))
games = load_games(store, all_apps(store), CUTOFF)
events = store.calendar_events()
dataset = build_dataset(store, games, events, cutoff=CUTOFF, regions=("TW",), split="tuning")
rd = dataset.regions["TW"]
apps = list(rd.apps)
wishlist = set(store.wishlist_apps())
names = {a: store.facts(a, CUTOFF).name.value for a in apps if a in wishlist}
print(f"load {time.perf_counter() - t_start:.0f}s; TW tuning {len(apps)} apps, dataset {rd.dataset_id[:8]}, "
      f"wishlist in tuning {len(names)}", flush=True)

seasonal = sorted([(e.start, e.end) for e in events if e.kind == "seasonal" and e.start < CUTOFF])
themed = sorted([(e.start, e.end, e.name_zh) for e in events if e.kind == "themed" and e.start < CUTOFF])


def overlaps(a, b, windows):
    return any(s < b and a < e for s, e, *_ in windows)


def in_seasonal(t):
    return any(s - TOL <= t < e for s, e in seasonal)


def episodes(series):
    """[(start, end, max_cut, left_censored, right_censored, kind)]"""
    out, s = [], series.states
    i = 0
    while i < len(s):
        if s[i].cut <= 0:
            i += 1
            continue
        j, best = i, 0
        while j < len(s) and s[j].cut > 0:
            best = max(best, s[j].cut)
            j += 1
        end = s[j].start if j < len(s) else series.known_until
        start = s[i].start
        kind = "seasonal" if overlaps(start, end, seasonal) else ("themed" if overlaps(start, end, themed) else "other")
        out.append((start, end, best, i == 0, j >= len(s), kind))
        i = j
    return out


def bucket(v, edges, labels):
    for e, l in zip(edges, labels):
        if v < e:
            return l
    return labels[-1]


# ---------------------------------------------------------------- A. episodes
def part_a(region, since=None):
    res = {"games": 0, "exposure_years": 0.0, "episodes": Counter(), "ns_depth": Counter(), "ns_vs_record": Counter(),
           "ns_days": [], "s_days": [], "per_game_rate": Counter(), "regularity": Counter(), "median_interval": Counter(),
           "ns_same_depth": Counter(), "ns_new_low": 0, "ns_total": 0, "per_game": {}}
    for app in apps:
        series = games[app].series.get(region)
        if series is None or not series.states or series.known_until is None:
            continue
        lo = max(series.states[0].start, since) if since else series.states[0].start
        years = (series.known_until - lo).days / 365.25
        if years <= 0:
            continue
        res["games"] += 1
        res["exposure_years"] += years
        eps = [e for e in episodes(series) if not e[3] and e[0] >= lo]
        outcomes = games[app].outcomes.get(region, ())
        ns = [e for e in eps if e[5] != "seasonal"]
        prior_low = max([st_.cut for st_ in series.states if st_.start < lo], default=0)
        for e in eps:
            res["episodes"][e[5]] += 1
            days = (e[1] - e[0]).total_seconds() / 86400
            if not e[4]:
                (res["ns_days"] if e[5] != "seasonal" else res["s_days"]).append(days)
        running_low = prior_low
        for e in eps:
            if e[5] != "seasonal":
                res["ns_total"] += 1
                if e[2] > running_low:
                    res["ns_new_low"] += 1
                res["ns_depth"][bucket(e[2], (25, 50, 70, 80), ("<25", "25-45", "50-65", "70-75", "80+"))] += 1
                rec = max((o.max_cut for o in outcomes if o.end <= e[0]), default=None)
                res["ns_vs_record"]["no-record" if rec is None else
                                    ("deeper" if e[2] > rec else "equal" if e[2] == rec else "shallower")] += 1
            running_low = max(running_low, e[2])
        if years >= 0.5:
            rate = len(ns) / years
            res["per_game_rate"][bucket(rate, (0.01, 1.5, 3.5, 6.5), ("0", "<1.5", "1.5-3.5", "3.5-6.5", "6.5+"))] += 1
        starts = [e[0] for e in ns]
        cls = "0" if not ns else "1-2" if len(ns) < 3 else None
        if cls is None:
            gaps = [(b - a).days for a, b in zip(starts, starts[1:])]
            cv = st.pstdev(gaps) / st.mean(gaps) if st.mean(gaps) else 9
            cls = "3+ regular (CV<0.5)" if cv < 0.5 else "3+ irregular"
            res["median_interval"][bucket(st.median(gaps), (46, 91, 181), ("<=45d", "46-90d", "91-180d", ">180d"))] += 1
            depths = Counter(e[2] for e in ns)
            res["ns_same_depth"]["mode>=70%" if depths.most_common(1)[0][1] / len(ns) >= 0.7 else "mixed"] += 1
        res["regularity"][cls] += 1
        s_max = max((e[2] for e in eps if e[5] == "seasonal"), default=None)
        res["per_game"][app] = {"ns": len(ns), "ns_max": max((e[2] for e in ns), default=None), "s_max": s_max,
                                "years": round(years, 2), "cls": cls,
                                "ns_list": [(e[0].strftime("%Y-%m-%d"), e[2], e[5]) for e in ns]}
    return res


A = {"TW": part_a("TW")}
tw_since = min(games[a].series["TW"].states[0].start for a in apps)
A["US"] = part_a("US", since=datetime(2024, 12, 11, tzinfo=UTC))
# TW non-seasonal episodes that have a US non-seasonal episode starting within 3 days
match = Counter()
for app in apps:
    if "US" not in games[app].series:
        continue
    us = [e[0] for e in episodes(games[app].series["US"]) if e[5] != "seasonal"]
    for e in episodes(games[app].series["TW"]):
        if e[5] != "seasonal" and not e[3]:
            match["same" if any(abs((u - e[0]).days) <= 3 for u in us) else "tw-only"] += 1
A["tw_us_match"] = match
print(f"A done {time.perf_counter() - t_start:.0f}s", flush=True)

# ---------------------------------------------------------------- B + C. model and rule over the schedule
model = current_model()
prefs = Preferences()
actual = actual_sales(events)
calib = defaultdict(lambda: [0, 0.0, 0, 0, 0])   # bin -> [n, sum p, occurred, occurred seasonal-only, first NS]
compact = defaultdict(dict)
cases = []
for n, as_of in enumerate(rd.schedule, 1):
    present = [a for a in apps if games[a].series["TW"].first_start <= as_of and is_paid_at(games[a], as_of)]
    points = sale_points([e for e in events if e.start <= as_of], as_of)
    window = window_points(points, as_of, "TW")
    if not present or not window:
        continue
    pool = [a for a in rd.population_apps if games[a].series["TW"].first_start <= as_of and is_paid_at(games[a], as_of)]
    model.prepare(population_view((games[a] for a in pool), as_of, "TW"))
    nohist = no_history_curve(model, as_of, points)
    fw = points.index(window[0])
    levels = list(dataset.levels)
    for app in present:
        g = games[app]
        series = g.series["TW"]
        fc = predict_one(model, game_evidence(g, as_of, "TW"), points)
        if isinstance(fc, str):
            continue
        # B: calibration units
        firsts = series.first_crossings(as_of, levels)
        outs = {o.sale_key: o for o in g.outcomes.get("TW", ()) if o.start > as_of}
        for k, p in enumerate(window):
            act = actual.get(p.sale_key)
            for li, d in enumerate(levels):
                o = unit_outcome(firsts[d], act, series.known_until, p.end)
                if o not in ("occurred", "not-occurred") or act is None or series.known_until < act.end:
                    continue
                prob = fc.probabilities[fw + k][li]
                b = calib[min(int(prob * 10), 9)]
                b[0] += 1
                b[1] += prob
                if o == "occurred":
                    b[2] += 1
                    if not in_seasonal(firsts[d]):
                        b[4] += 1
                if act is not None and any(q.max_cut >= d and q.end <= act.end for q in outs.values()):
                    b[3] += 1
        # C: decision
        state = series.state_at(as_of)
        now_price = state.regular_cents * (100 - state.cut) // 100
        try:
            r = decide(probabilities=fc.probabilities, points=points, as_of=as_of, confidence=fc.confidence,
                       evidence_max_cut=fc.evidence.get("max_cut"), regular_cents=state.regular_cents,
                       current_price_cents=now_price, regular_mismatch=False,
                       no_history=nohist.probabilities if nohist else None, preferences=prefs)
        except Exception:  # noqa: BLE001
            continue
        compact[app][as_of] = _Compact(r.group, r.sweet_pct)
        cases.append((app, as_of, r.group, r.confidence, now_price, points[r.sweet_index - 1].start))
    print(f"  as_of {n}/{len(rd.schedule)} {as_of:%Y-%m-%d} {time.perf_counter() - t_start:.0f}s", flush=True)


def price(state):
    return state.regular_cents * (100 - state.cut) // 100


def walk(series, t0, decisions, now_price, seasonal_only):
    """Mirror of follow_advice_monthly that also returns the purchase time and kind. seasonal_only: a buyer who
    only buys during seasonal sales (or when the decision says buy now)."""
    horizon = add_months(t0, 12)
    known = series.known_until
    checks = [t0, *[t for t in rd.schedule if t0 < t < horizon]]
    cur = decisions[t0]
    for step, t in enumerate(checks):
        cur = decisions.get(t, cur) if step else cur
        if cur.group == "now":
            return now_price - price(series.state_at(t)), (t - t0).days, t, "now"
        nxt = checks[step + 1] if step + 1 < len(checks) else horizon
        if not seasonal_only:
            first = series.first_crossings(t, [cur.sweet_pct])[cur.sweet_pct]
            if first is not None and first <= nxt and (known is None or first <= known):
                return now_price - price(series.state_at(first)), (first - t0).days, first, \
                    "seasonal" if in_seasonal(first) else "non-seasonal"
        else:
            hit = None
            for i, s_ in enumerate(series.states):
                end = series.states[i + 1].start if i + 1 < len(series.states) else known
                if s_.cut < cur.sweet_pct or end is None or end <= t or s_.start > nxt:
                    continue
                for ws, we in seasonal:
                    a, b = max(s_.start, ws, t), min(end, we, nxt)
                    if a < b or (a == b == s_.start):
                        hit = (a, s_)
                        break
                if hit:
                    break
            if hit and (known is None or hit[0] <= known):
                return now_price - price(hit[1]), (hit[0] - t0).days, hit[0], "seasonal"
        if known is None or known < nxt:
            return None
    return now_price - price(series.state_at(horizon)), (horizon - t0).days, horizon, "12m"


C = {"kind": Counter(), "early": Counter(), "early_days": [], "all": [], "sonly": [], "by_group": defaultdict(list),
     "hind": Counter(), "hind_gap": [], "now_deeper": Counter(), "kind_full": Counter(),
     "full_all": [], "full_sonly": []}
mismatch = 0
for app, as_of, group, conf, now_price, sweet_start in cases:
    series = games[app].series["TW"]
    a = walk(series, as_of, compact[app], now_price, False)
    ref = follow_advice_monthly(series, as_of, rd.schedule, compact[app], now_price_cents=now_price)
    if (a is None) != ref.censored or (a and (a[0], a[1]) != (ref.saving_cents, ref.wait_days)):
        mismatch += 1
    b = walk(series, as_of, compact[app], now_price, True)
    if a is None:
        continue
    C["kind"][(group, a[3])] += 1
    if a[3] == "non-seasonal" and group != "now":
        early = a[2] < sweet_start
        C["early"]["before sweet sale" if early else "after sweet sale start"] += 1
        if early:
            C["early_days"].append((sweet_start - a[2]).days)
    full12 = series.known_until is not None and series.known_until >= add_months(as_of, 12)
    if full12:
        C["kind_full"][(group, a[3])] += 1
        if b is not None:
            C["full_all"].append((a[0], a[1]))
            C["full_sonly"].append((b[0], b[1]))
    if b is not None:
        C["all"].append((a[0], a[1]))
        C["sonly"].append((b[0], b[1]))
        C["by_group"][group].append((a[0], a[1], b[0], b[1]))
    # hindsight 12-month low: first reached in a seasonal sale or not
    horizon = add_months(as_of, 12)
    if series.known_until and series.known_until >= horizon:
        sts = [s_ for s_ in series.states if as_of < s_.start <= horizon and s_.regular_cents]
        if sts:
            low = min(price(s_) for s_ in sts)
            if low < now_price:
                first = next(s_ for s_ in sts if price(s_) == low)
                s_low = min([price(s_) for s_ in sts if in_seasonal(s_.start)], default=None)
                kind = "seasonal" if in_seasonal(first.start) else \
                    ("non-seasonal, equal to a seasonal price" if s_low == low else "non-seasonal, strictly lower")
                C["hind"][kind] += 1
                if kind.endswith("strictly lower"):
                    C["hind_gap"].append(((s_low if s_low is not None else now_price) - low) / 100)
                if group == "now":
                    C["now_deeper"][kind] += 1


def summ(pairs):
    if not pairs:
        return None
    return {"n": len(pairs), "saving_mean": round(sum(p[0] for p in pairs) / len(pairs) / 100, 1),
            "wait_mean": round(sum(p[1] for p in pairs) / len(pairs), 1)}


result = {
    "dataset": rd.dataset_id, "apps": len(apps), "schedule": [t.strftime("%Y-%m-%d") for t in rd.schedule],
    "A": {r: {k: (dict(v) if isinstance(v, Counter) else v) for k, v in A[r].items() if k not in ("ns_days", "s_days", "per_game")}
          | {"ns_days_median": st.median(A[r]["ns_days"]) if A[r]["ns_days"] else None,
             "s_days_median": st.median(A[r]["s_days"]) if A[r]["s_days"] else None,
             "ns_days_buckets": dict(Counter(bucket(d, (2, 4, 8, 15), ("<2", "2-3", "4-7", "8-14", "15+"))
                                             for d in A[r]["ns_days"]))}
          for r in ("TW", "US")},
    "tw_us_match": dict(match),
    "B_calibration": {f"{b / 10:.1f}": {"n": v[0], "pred": round(v[1] / v[0], 3), "actual": round(v[2] / v[0], 3),
                                        "seasonal_only": round(v[3] / v[0], 3),
                                        "occurred_first_non_seasonal": round(v[4] / v[2], 3) if v[2] else None}
                      for b, v in sorted(calib.items())},
    "C": {"cases": len(cases), "parity_mismatch": mismatch,
          "kind": {f"{g}/{k}": v for (g, k), v in sorted(C["kind"].items())},
          "early": dict(C["early"]),
          "early_days_median": st.median(C["early_days"]) if C["early_days"] else None,
          "follow_all": summ(C["all"]),
          "full12_all": summ(C["full_all"]), "full12_sonly": summ(C["full_sonly"]),
          "kind_full": {f"{g}/{k}": v for (g, k), v in sorted(C["kind_full"].items())}, "follow_seasonal_only": summ(C["sonly"]),
          "by_group": {g: {"all": summ([(x[0], x[1]) for x in v]), "sonly": summ([(x[2], x[3]) for x in v])}
                       for g, v in C["by_group"].items()},
          "hindsight_low": dict(C["hind"]),
          "hindsight_strict_gap_median": st.median(C["hind_gap"]) if C["hind_gap"] else None,
          "now_later_low": dict(C["now_deeper"])},
    "wishlist_tuning": {names[a]: A["TW"]["per_game"].get(a) for a in sorted(names, key=lambda a: names[a])},
    "seconds": round(time.perf_counter() - t_start, 1),
}
OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
print(f"done {result['seconds']}s -> {OUT}")
