"""P2 (plan, read-only; tuning part only, TW, cutoff 2026-09-25): per-sale probabilities and the joint "both reach
in the same sale" check on made-up pairs (spec FR-008, FR-017; research R0.1, R0.2).

Per-sale probability that a game's max cut *during* sale k is >= d, from the current model (seasonal-record 1.1.0):
  M1 "next"  : the cumulative probability of the first point (k = 1) for every k (state held still).
  M2 "chain" : from the model's own parts. r_k = P(first new record at sale k) = prod_{j<k}(1 - h_j) * h_k.
               d <= M: 1 - (1 - p(d)) (1 - r_k)   (p = shrunk recency-weighted own share)
               d >  M: r_k * P(M + 5J >= d)        (J = the model's jump distribution)
               k = 1 equals the model's cumulative output exactly. Low confidence (no own record): M1.
Scoring: a unit counts only when its actual sale ended inside the known history (SaleOutcome exists), so occurred
and not-occurred are judged the same way (007 lesson).
Pairs: random (3 seeded permutations, consecutive apps) and same-publisher (first publisher, <= 20 pairs each).
Pair unit = pair x as_of x sale in the 12-month window where both games have an outcome; each game's level is the
deepest with per-sale P >= 0.5 (skipped when a game has none); predicted q = P_A * P_B; occurred = both reached.
P2 variant: per pair and sale, the cheapest level pair (regular prices at as_of) whose joint M1 probability is >= 0.5.
Writes out/p2.json. Never writes the database.
"""
import json
import random
import sqlite3
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from steamsage.forecast.backtest.dataset import build_dataset
from steamsage.forecast.backtest.scoring import actual_sales, window_points
from steamsage.forecast.contract import LEVELS
from steamsage.forecast.engine import all_apps, is_paid_at, load_games, predict_one
from steamsage.forecast.evidence import game_evidence, population_view
from steamsage.forecast.models import current_model
from steamsage.forecast.models.seasonal_record import S_CAP, record_state
from steamsage.forecast.salepoints import sale_points
from steamsage.store.query import PriceStore

CUTOFF = datetime(2026, 9, 25, tzinfo=UTC)
OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)
T0 = time.perf_counter()
store = PriceStore.open(Path("data/steamsage.db"), Path("data/steam_sales.toml"))
games = load_games(store, all_apps(store), CUTOFF)
events = store.calendar_events()
dataset = build_dataset(store, games, events, cutoff=CUTOFF, regions=("TW",), split="tuning")
rd = dataset.regions["TW"]
store.close()
actual = actual_sales(events)
model = current_model()
levels = list(LEVELS)
t_load = time.perf_counter() - T0
print(f"loaded {len(rd.apps)} tuning games, {len(rd.schedule)} as_of, dataset {rd.dataset_id[:8]} in {t_load:.0f}s")


def chain_per_sale(evidence, k_max):
    own = model._freq._history(evidence.sale_history, "TW")
    if len(own) < model.min_sales:
        return None
    cuts = [o.max_cut for o in own]
    n = len(cuts)
    w = [0.5 ** ((n - 1 - i) / model.half_life) if model.half_life else 1.0 for i in range(n)]
    tot = sum(w)
    m5, s, _ = record_state(cuts)
    raw = {d: sum(x for x, c in zip(w, cuts) if c >= d) / tot for d in levels if d <= m5}
    if model.shrink:
        pool_total, at_least = model._freq._pool
        a = model.shrink
        shares = {d: (n * p + a * at_least[d] / pool_total) / (n + a) for d, p in raw.items()}
    else:
        shares = raw
    jump = model.table.jump(m5)
    rows, alive = [], 1.0
    for k in range(k_max):
        h = model.table.rate(m5, min(s + k, S_CAP))
        r = alive * h
        alive *= 1.0 - h
        row, low = [], 1.0
        for d in levels:
            if d <= m5:
                v = 1.0 - (1.0 - shares[d]) * (1.0 - r)
            else:
                v = r * sum(p for j, p in jump.items() if min(m5 + 5 * j, 95) >= d)
            low = min(low, v)
            row.append(low)
        rows.append(row)
    return rows


# --- per game x as_of: per-sale probabilities (both methods) and outcomes --------------------------------------
recs = {}          # (app, as_of) -> {"conf", "keys", "m1", "m2", "out"}
single = {m: defaultdict(lambda: [0, 0.0, 0]) for m in ("m1", "m2")}      # (group) -> [n, sse, occ]
calib = {m: [[0, 0.0, 0] for _ in range(10)] for m in ("m1", "m2")}
calib_k2 = {m: [[0, 0.0, 0] for _ in range(10)] for m in ("m1", "m2")}
for as_of in rd.schedule:
    present = [a for a in rd.apps if games[a].series["TW"].first_start <= as_of and is_paid_at(games[a], as_of)]
    pool = [a for a in rd.population_apps if games[a].series["TW"].first_start <= as_of and is_paid_at(games[a], as_of)]
    points = sale_points([e for e in events if e.start <= as_of], as_of)
    window = window_points(points, as_of, "TW")
    if not window:
        continue
    first = points.index(window[0])
    model.prepare(population_view((games[a] for a in pool), as_of, "TW"))
    for app in present:
        ev = game_evidence(games[app], as_of, "TW")
        out = predict_one(model, ev, points, levels)
        if isinstance(out, str):
            continue
        k_max = first + len(window)
        m1 = [list(out.probabilities[0])] * k_max
        ch = chain_per_sale(ev, k_max)
        m2 = ch if ch is not None else m1
        oc = {o.sale_key: o.max_cut for o in games[app].outcomes.get("TW", ())}
        keys, r1, r2, res = [], [], [], []
        for i, p in enumerate(window, start=first):
            if p.sale_key not in actual or p.sale_key not in oc:
                continue
            keys.append(p.sale_key)
            r1.append(m1[i])
            r2.append(m2[i])
            res.append(oc[p.sale_key])
            for m, row in (("m1", m1[i]), ("m2", m2[i])):
                for j, d in enumerate(levels):
                    o = int(oc[p.sale_key] >= d)
                    for g in ("all", out.confidence, "k1" if i == 0 else "k2+"):
                        acc = single[m][g]
                        acc[0] += 1
                        acc[1] += (row[j] - o) ** 2
                        acc[2] += o
                    b = min(int(row[j] * 10), 9)
                    for table in ((calib[m],) if i == 0 else (calib[m], calib_k2[m])):
                        table[b][0] += 1
                        table[b][1] += row[j]
                        table[b][2] += o
        if keys:
            recs[(app, as_of)] = {"conf": out.confidence, "keys": keys, "m1": r1, "m2": r2, "out": res, "reg": games[app].series["TW"].state_at(as_of).regular_cents}
t_single = time.perf_counter() - T0
print(f"per-sale done in {t_single:.0f}s, game x as_of with scored sales: {len(recs)}")


# --- P2: cheapest bundle with joint P >= 0.5 (M1 per-sale probabilities) ------------------------------------
conn = sqlite3.connect("file:data/steamsage.db?mode=ro", uri=True)
publisher = {}
for app, value in conn.execute("SELECT app_id, value_json FROM product_facts WHERE field='publishers' ORDER BY retrieved_at"):
    names = json.loads(value) if value else None
    if names:
        publisher[app] = str(names[0]).casefold()
apps = sorted(rd.apps)
pairs = {"random": set(), "publisher": set()}
for seed in (1, 2, 3):
    order = apps[:]
    random.Random(20260927 + seed).shuffle(order)
    pairs["random"] |= {tuple(sorted(order[i:i + 2])) for i in range(0, len(order) - 1, 2)}
groups = defaultdict(list)
for a in apps:
    if a in publisher:
        groups[publisher[a]].append(a)
rng = random.Random(20260927)
for name, members in groups.items():
    combos = [(a, b) for i, a in enumerate(members) for b in members[i + 1:]]
    rng.shuffle(combos)
    pairs["publisher"] |= set(combos[:20])

LV = [0] + levels


def cheapest(ra, i, rb, j, reg_a, reg_b):
    pa = [1.0] + ra["m1"][i]
    pb = [1.0] + rb["m1"][j]
    best = None
    for x, da in enumerate(LV):
        for y, db in enumerate(LV):
            q = pa[x] * pb[y]
            if q < 0.5:
                continue
            price = reg_a * (100 - da) + reg_b * (100 - db)
            if best is None or price < best[0] or (price == best[0] and q > best[1]):
                best = (price, q, da, db)
    return best


out = {}
for kind, ps in pairs.items():
    n = occ = 0
    qs = 0.0
    cal = [[0, 0.0, 0] for _ in range(10)]
    zero = 0
    for a, b in ps:
        for as_of in rd.schedule:
            ra, rb = recs.get((a, as_of)), recs.get((b, as_of))
            if not ra or not rb or not ra["reg"] or not rb["reg"]:
                continue
            ib = {k: i for i, k in enumerate(rb["keys"])}
            for i, key in enumerate(ra["keys"]):
                if key not in ib:
                    continue
                j = ib[key]
                best = cheapest(ra, i, rb, j, ra["reg"], rb["reg"])
                if best is None:
                    continue
                _, q, da, db = best
                if da == 0 and db == 0:
                    zero += 1
                o = int(ra["out"][i] >= da and rb["out"][j] >= db)
                n += 1
                occ += o
                qs += q
                c = cal[min(int(q * 10), 9)]
                c[0] += 1
                c[1] += q
                c[2] += o
    out[kind] = {"pairs": len(ps), "units": n, "mean_q": qs / n, "observed": occ / n, "no_discount_units": zero,
                 "calibration": [[b / 10, c[0], round(c[1] / c[0], 3) if c[0] else None,
                                  round(c[2] / c[0], 3) if c[0] else None] for b, c in enumerate(cal)]}
    print(kind, {k: v for k, v in out[kind].items() if k != "calibration"})
    for r in out[kind]["calibration"]:
        print("   ", r)
(OUT / "p2.json").write_text(json.dumps({"dataset": rd.dataset_id, "cutoff": CUTOFF.isoformat(), "opt": out,
                                         "seconds": round(time.perf_counter() - T0, 1)}, indent=1), encoding="utf-8")
print("seconds", round(time.perf_counter() - T0, 1))
