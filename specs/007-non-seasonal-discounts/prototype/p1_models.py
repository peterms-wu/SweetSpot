"""P1 (plan, research R0/R1): candidate non-seasonal models on the TW tuning split. Read-only.

Units: game x as_of x h x d (h = 30/60/90 days, d = 5..95), scored only when the game's history is known through
as_of + h (spec FR-007). Event: a non-seasonal arrival of d within (as_of, as_of + h] (spec FR-001/FR-003).

Models:
- M0  population share: mean over population games of the share of past windows (last 365 days) with an arrival >= d.
- M1  own share, smoothed to M0 with strength k months of history; history TW or TW+US (US fills before TW tracking).
- M2  clock: P(any arrival within h | past-year promo count, phase of the typical interval, discounted now,
      seasonal sale inside the horizon) from a population table, x P(depth >= d) from own promo depths smoothed to
      the population depth share given the game's deepest past discount.
Also: the report sentence "可能比〈甜蜜時點〉更早到價" (spec FR-014) under rule 2.1.0 decisions, hit rate by threshold.
"""
import json
import random
import statistics as st
import sys
import time
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from nslib import CUTOFF, HORIZONS, LEVELS, GameNS, Windows, arrived, history_view, window_fraction  # noqa: E402

from steamsage.config import Preferences
from steamsage.decision.rule import decide
from steamsage.forecast.backtest.dataset import build_dataset
from steamsage.forecast.engine import all_apps, is_paid_at, load_games, no_history_curve, predict_one
from steamsage.forecast.evidence import game_evidence, population_view
from steamsage.forecast.models import current_model
from steamsage.forecast.salepoints import sale_points
from steamsage.store.query import PriceStore

OUT = Path(__file__).parent / "out" / (sys.argv[1] if len(sys.argv) > 1 else "p1_models.json")
LOOKBACK = 365
T0 = time.perf_counter()


def log(msg):
    print(f"[{time.perf_counter() - T0:5.0f}s] {msg}", flush=True)


store = PriceStore.open(Path("data/steamsage.db"))
games = load_games(store, all_apps(store), CUTOFF)
events = store.calendar_events()
rd = build_dataset(store, games, events, cutoff=CUTOFF, regions=("TW",), split="tuning").regions["TW"]
seasonal = [(e.start, e.end) for e in events if e.kind == "seasonal"]
win = Windows(seasonal)
pop_apps = list(rd.population_apps)
ns = {a: {r: GameNS(games[a].series[r], win) for r in ("TW", "US") if r in games[a].series}
      for a in set(pop_apps) | set(rd.apps)}
log(f"loaded: tuning {len(rd.apps)} apps, population {len(pop_apps)}, {len(rd.schedule)} as_of")

# seasonal-record ends tolerance check: arrivals within [start - 1 day, start)
tol_hits = 0
for a in rd.apps:
    for s in games[a].series["TW"].states:
        if any(st_ - timedelta(days=1) <= s.start < st_ for st_, _ in seasonal):
            tol_hits += 1


def present(a, as_of):
    tw = games[a].series["TW"]
    return tw.first_start <= as_of and is_paid_at(games[a], as_of)


# ---------------------------------------------------------------- M0 population share
def m0_table(as_of):
    lo = as_of - timedelta(days=LOOKBACK)
    sums = defaultdict(float)
    ns_ = defaultdict(int)
    for a in pop_apps:
        if not present(a, as_of):
            continue
        g = ns[a]["TW"]
        start = max(g.first, lo)
        arrs = [x for x in g.arrs if start < x[0] <= as_of]
        for h in HORIZONS:
            if (as_of - start).days < h + 30:
                continue
            for d in LEVELS:
                f = window_fraction(sorted(t for t, p, c in arrs if p < d <= c), start, as_of, h)
                if f is not None:
                    sums[(h, d)] += f
                    ns_[(h, d)] += 1
    return {k: sums[k] / ns_[k] for k in sums}


# ---------------------------------------------------------------- M1 own share
def m1(a, as_of, m0, k, mode):
    arrs, _, start = history_view(ns[a]["TW"], ns[a].get("US"), mode, as_of)
    start = max(start, as_of - timedelta(days=LOOKBACK))
    months = (as_of - start).days / 30.44
    out = {}
    for h in HORIZONS:
        for d in LEVELS:
            base = m0.get((h, d), 0.0)
            f = window_fraction(sorted(t for t, p, c in arrs if p < d <= c and t > start), start, as_of, h) \
                if (as_of - start).days >= h + 30 else None
            if f is None:
                out[(h, d)] = base
            else:
                w = max(months - h / 30.44, 0)
                out[(h, d)] = (w * f + k * base) / (w + k)
    return out


# ---------------------------------------------------------------- M2 clock x depth
def kgroup(n):
    return 0 if n == 0 else 1 if n <= 2 else 2 if n <= 4 else 3


def features(a, t, mode):
    """(k group, phase group, discounted now, promo depths in the past year, deepest past discount)"""
    _, prom, start = history_view(ns[a]["TW"], ns[a].get("US"), mode, t)
    year = [p for p in prom if t - timedelta(days=LOOKBACK) < p[0] <= t]
    phase = 4
    if len(year) >= 3:
        gaps = [(y[0] - x[0]).days for x, y in zip(year, year[1:])]
        med = st.median(gaps)
        r = (t - year[-1][0]).days / med if med else 9
        phase = 0 if r < 0.5 else 1 if r < 1 else 2 if r < 1.5 else 3
    state = games[a].series["TW"].state_at(t)
    now = int(bool(state and state.cut > 0))
    past_max = max((s.cut for s in games[a].series["TW"].states if s.start <= t), default=0)
    return kgroup(len(year)), phase, now, [p[1] for p in year], past_max - past_max % 5


def any_arrival(a, lo, hi):
    return any(lo < x[0] <= hi for x in ns[a]["TW"].arrs)


def m2_tables(as_of, mode):
    hz = defaultdict(lambda: [0, 0])          # (h, k, phase, now, seasonal) -> [n, hits]
    hz_k = defaultdict(lambda: [0, 0])
    hz_hk = defaultdict(lambda: [0, 0])
    depth = defaultdict(lambda: [0, Counter()])   # past-max group -> [promos, Counter(depth5)]
    lo = as_of - timedelta(days=LOOKBACK)
    for a in pop_apps:
        if not present(a, as_of):
            continue
        g = ns[a]["TW"]
        t = max(g.first, lo) + timedelta(days=30)
        while t <= as_of - timedelta(days=30):
            k, phase, now, _, _ = features(a, t, mode)
            for h in HORIZONS:
                if t + timedelta(days=h) > as_of:
                    continue
                seas = int(win.overlaps(t, t + timedelta(days=h)))
                hit = any_arrival(a, t, t + timedelta(days=h))
                for key, table in (((h, k, phase, now, seas), hz), ((h, k, now, seas), hz_k), ((h, k), hz_hk)):
                    table[key][0] += 1
                    table[key][1] += hit
            t += timedelta(days=14)
        for pt, cut in g.promos:
            if lo < pt <= as_of:
                past = max((s.cut for s in g.series.states if s.start < pt), default=0)
                cell = depth[min(past - past % 5, 90) // 10]
                cell[0] += 1
                cell[1][cut - cut % 5] += 1
    return hz, hz_k, depth, hz_hk


def clock_ratio(a, as_of, tables, mode, points):
    hz, hz_k, _, hz_hk = tables
    k, phase, now, _, _ = features(a, as_of, mode)
    out = {}
    for h in HORIZONS:
        hi = as_of + timedelta(days=h)
        seas = int(any(p_start < hi and as_of < p_end for p_start, p_end in points))
        n0, r0 = hz_hk.get((h, k), (0, 0))
        marg = r0 / n0 if n0 else 0.0
        n1, r1 = hz_k.get((h, k, now, seas), (0, 0))
        base = (r1 + 20 * marg) / (n1 + 20)
        n2, r2 = hz.get((h, k, phase, now, seas), (0, 0))
        cell = (r2 + 20 * base) / (n2 + 20)
        out[h] = cell / marg if marg else 1.0
    return out


def m2(a, as_of, tables, mode, points):
    hz, hz_k, depth, _ = tables
    k, phase, now, depths, past5 = features(a, as_of, mode)
    cell = depth.get(min(past5, 90) // 10)
    out = {}
    for h in HORIZONS:
        hi = as_of + timedelta(days=h)
        seas = int(any(p_start < hi and as_of < p_end for p_start, p_end in points))
        n1, r1 = hz_k.get((h, k, now, seas), (0, 0))
        base = r1 / n1 if n1 else 0.0
        n2, r2 = hz.get((h, k, phase, now, seas), (0, 0))
        p_any = (r2 + 20 * base) / (n2 + 20)
        for d in LEVELS:
            prior = sum(v for c, v in cell[1].items() if c >= d) / cell[0] if cell and cell[0] else 0.0
            own = sum(1 for x in depths if x >= d)
            q = (own + 3 * prior) / (len(depths) + 3)
            out[(h, d)] = p_any * q
    return out


# ---------------------------------------------------------------- run
CANDIDATES = [("M0", None), ("M1", (1, "TW+US")), ("M1", (2, "TW+US")), ("M1", (5, "TW+US")), ("M2", "TW+US"),
              ("M3", (2, "TW+US")), ("M3", (5, "TW+US")), ("M4", (5, "TW+US"))]
names = [f"{m}" if p is None else f"{m}{p}" for m, p in CANDIDATES]
sse = {n: defaultdict(lambda: [0, 0.0]) for n in names}           # name -> (app, h) -> [units, sse]
calib = {n: defaultdict(lambda: [0, 0.0, 0]) for n in names}
by_k = {n: defaultdict(lambda: [0, 0.0]) for n in names}
store_probs = {}                                                  # (app, as_of) -> {name: probs}
skipped = Counter()
model = current_model()
prefs = Preferences()
decisions = {}
for i, as_of in enumerate(rd.schedule, 1):
    apps = [a for a in rd.apps if present(a, as_of)]
    m0 = m0_table(as_of)
    tabs = {mode: m2_tables(as_of, mode) for mode in ("TW+US",)}
    pts = sale_points([e for e in events if e.start <= as_of], as_of)
    windows_now = [(p.start, p.end) for p in pts] + [(e.start, e.end) for e in events
                                                      if e.kind == "seasonal" and e.start <= as_of < e.end]
    # rule 2.1.0 decisions (for the report sentence)
    pool = [a for a in rd.population_apps if present(a, as_of)]
    model.prepare(population_view((games[a] for a in pool), as_of, "TW"))
    nohist = no_history_curve(model, as_of, pts)
    for a in apps:
        fc = predict_one(model, game_evidence(games[a], as_of, "TW"), pts)
        if isinstance(fc, str):
            continue
        state = games[a].series["TW"].state_at(as_of)
        try:
            r = decide(probabilities=fc.probabilities, points=pts, as_of=as_of, confidence=fc.confidence,
                       evidence_max_cut=fc.evidence.get("max_cut"), regular_cents=state.regular_cents,
                       current_price_cents=state.regular_cents * (100 - state.cut) // 100, regular_mismatch=False,
                       no_history=nohist.probabilities if nohist else None, preferences=prefs)
        except Exception:  # noqa: BLE001
            continue
        decisions[(a, as_of)] = (r.group, r.sweet_pct, pts[r.sweet_index - 1].start)
    for a in apps:
        g = ns[a]["TW"]
        k_now = features(a, as_of, "TW")[0]
        probs = {}
        for (m, p), n in zip(CANDIDATES, names):
            if m == "M0":
                probs[n] = {key: m0.get(key, 0.0) for key in ((h, d) for h in HORIZONS for d in LEVELS)}
            elif m == "M1":
                probs[n] = m1(a, as_of, m0, *p)
            elif m == "M2":
                probs[n] = m2(a, as_of, tabs[p], p, windows_now)
            elif m == "M3":
                base = m1(a, as_of, m0, *p)
                ratio = clock_ratio(a, as_of, tabs[p[1]], p[1], windows_now)
                probs[n] = {key: min(v * ratio[key[0]], 0.99) for key, v in base.items()}
            else:
                one = m1(a, as_of, m0, *p)
                two = m2(a, as_of, tabs[p[1]], p[1], windows_now)
                probs[n] = {key: (one[key] + two[key]) / 2 for key in one}
        store_probs[(a, as_of)] = probs
        for h in HORIZONS:
            hi = as_of + timedelta(days=h)
            if g.known is None or g.known < hi:
                skipped[h] += len(LEVELS)
                continue
            got = arrived(g.arrs, as_of, hi)
            for n in names:
                for d in LEVELS:
                    pr = probs[n][(h, d)]
                    o = d in got
                    e = (pr - o) ** 2
                    c = sse[n][(a, h)]
                    c[0] += 1
                    c[1] += e
                    b = calib[n][min(int(pr * 10), 9)]
                    b[0] += 1
                    b[1] += pr
                    b[2] += o
                    kk = by_k[n][k_now]
                    kk[0] += 1
                    kk[1] += e
    log(f"as_of {i}/{len(rd.schedule)} {as_of:%Y-%m-%d}: {len(apps)} apps")


def brier(n, h=None):
    per_game = defaultdict(lambda: [0, 0.0])
    for (a, hh), (u, e) in sse[n].items():
        if h is None or hh == h:
            per_game[a][0] += u
            per_game[a][1] += e
    vals = [e / u for u, e in per_game.values() if u]
    return sum(vals) / len(vals), per_game


def boot(n, ref="M0"):
    _, pa = brier(n)
    _, pb = brier(ref)
    diffs = [pa[a][1] / pa[a][0] - pb[a][1] / pb[a][0] for a in pa if a in pb and pa[a][0]]
    rng = random.Random(7)
    means = sorted(sum(rng.choices(diffs, k=len(diffs))) / len(diffs) for _ in range(2000))
    return sum(diffs) / len(diffs), means[50], means[1949], len(diffs)


result = {"tolerance_hits": tol_hits, "skipped_units": dict(skipped), "models": {}}
for n in names:
    result["models"][n] = {
        "brier": round(brier(n)[0], 5), **{f"brier_{h}d": round(brier(n, h)[0], 5) for h in HORIZONS},
        "vs_M0": None if n == "M0" else [round(x, 5) if isinstance(x, float) else x for x in boot(n)],
        "by_k": {["0", "1-2", "3-4", "5+"][k]: round(v[1] / v[0], 5) for k, v in sorted(by_k[n].items())},
        "calibration": {f"{b / 10:.1f}": [v[0], round(v[1] / v[0], 3), round(v[2] / v[0], 3)]
                        for b, v in sorted(calib[n].items())}}

# ---------------------------------------------------------------- the report sentence (spec FR-014)
sentence = {}
for n in names[1:]:
    rows = Counter()
    for (a, as_of), (group, pct, sale_start) in decisions.items():
        if group == "now":
            continue
        days = (sale_start - as_of).days
        hs = [h for h in HORIZONS if h <= days]
        if not hs:
            rows["no horizon (sale within 30 days)"] += 1
            continue
        h = hs[-1]
        g = ns[a]["TW"]
        hi = as_of + timedelta(days=h)
        pr = store_probs[(a, as_of)][n][(h, pct)]
        if g.known is None or g.known < hi:
            rows["censored"] += 1
            continue
        hit = pct in arrived(g.arrs, as_of, hi)
        rows["eligible"] += 1
        rows["eligible_hit"] += hit
        for th in (0.3, 0.4, 0.5, 0.6, 0.7):
            if pr >= th:
                rows[f"said@{th}"] += 1
                rows[f"hit@{th}"] += hit
    sentence[n] = dict(rows)
result["sentence"] = sentence
result["seconds"] = round(time.perf_counter() - T0, 1)
OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
for n in names:
    m = result["models"][n]
    print(n, m["brier"], m["brier_30d"], m["brier_60d"], m["brier_90d"], m["vs_M0"], m["by_k"])
for n, s in sentence.items():
    print(n, {k: s.get(k) for k in ("eligible", "eligible_hit", "said@0.5", "hit@0.5", "said@0.7", "hit@0.7")})
log("done")
