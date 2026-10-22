"""P1: the 2026 autumn sale's actual outcome for every game in the pre-sale record (read-only).

For each decision: the series the record read (its version / user edition), then
  (a) the backtest's outcome per level (first crossing after as_of, before the actual sale end; feature 008 FR-011),
  (b) the deepest cut during the sale (sale_outcomes: the state in effect at the start counts),
  (c) the lowest TWD price during the sale vs the record's sweet price,
  (d) the deepest cut the daily Steam snapshots saw during the sale (cross-check).
Prints where (a) and (b) disagree, the seasonal Brier under both, and the decision table by group.

Usage (from the worktree root): uv run python specs/013-post-sale-comparison/prototype/p1_actual.py
"""

import collections
import json
from pathlib import Path

from steamsage.forecast.contract import LEVELS
from steamsage.forecast.series import build_series, sale_outcomes

from common import NOW, autumn_2026, load_record, open_store, pre_sale_record, tracked_key

OUT = Path(__file__).parent / "out"


def sale_min_price(rows, sale):
    """Lowest price_cents of the states in effect during [start, end): the one at the start plus later ones."""
    best, at_start = None, None
    for o in rows:
        if o.observed_at <= sale.start:
            at_start = o
        elif o.observed_at < sale.end and o.price_cents is not None:
            best = o.price_cents if best is None else min(best, o.price_cents)
    if at_start is not None and at_start.price_cents is not None:
        best = at_start.price_cents if best is None else min(best, at_start.price_cents)
    return best


def main() -> None:
    store = open_store()
    sale = autumn_2026(store)
    when, path = pre_sale_record(sale)
    rec = load_record(path)
    as_of = rec["as_of"]
    from common import parse_time
    as_of = parse_time(as_of)
    print(f"sale {sale.start:%Y-%m-%d %H:%M}Z – {sale.end:%Y-%m-%d %H:%M}Z; record {path.name} as_of {as_of:%Y-%m-%d %H:%M}Z "
          f"({(sale.start - as_of).total_seconds() / 3600:.1f} h before)")
    probs = {g["app_id"]: g for g in rec["forecast"]["games"]}
    rows_out, units, disagree, status = [], [], [], collections.Counter()

    for d in rec["decisions"]:
        app = d["app_id"]
        ext, sources = tracked_key(d)
        if d["status"] != "ok":
            status[f"not scored: {d['status']}"] += 1
            rows_out.append({"app": app, "name": d["name"], "status": d["status"]})
            continue
        rows = store.series_rows([app], "TW", NOW, keys={app: ext}, sources=sources).get(app, [])
        known = store.history_known_until_all("TW", keys={app: ext}, apps=(app,)).get(app)
        series = build_series(rows, "TW", known)
        if not series.states or known is None or known < sale.end:
            status["no actual"] += 1
            rows_out.append({"app": app, "name": d["name"], "status": "no-actual", "known_until": str(known)})
            continue
        outcome = sale_outcomes(series, [sale])
        max_cut = outcome[0].max_cut if outcome else None
        firsts = series.first_crossings(as_of, LEVELS)
        crossed = [int(firsts[l] is not None and firsts[l] < sale.end) for l in LEVELS]
        running = series.state_at(as_of).cut if series.state_at(as_of) else None
        low = sale_min_price(rows, sale)
        steam = [o.cut_pct for o in store.observations(app, NOW) if o.source == "steam-current"
                 and sale.start <= o.observed_at < sale.end and o.cut_pct is not None]
        steam_max = max(steam) if steam else None
        status["scored"] += 1
        g = probs.get(app)
        point0 = (g.get("curve") or {}).get("points", [{}])[0] if g else {}
        if g and g.get("curve") and point0.get("label") == "2026 秋特":
            p = g["curve"]["probabilities"][0]
            for i, lvl in enumerate(LEVELS):
                b = int(max_cut is not None and max_cut >= lvl)
                units.append((app, g["confidence"], p[i], crossed[i], b))
                if crossed[i] != b:
                    disagree.append((d["name"], lvl, running, max_cut))
        rows_out.append({"app": app, "name": d["name"], "group": d["group"],
                         "sweet_point": (d.get("sweet_point") or {}).get("label"), "sweet_cents": d["sweet_cents"],
                         "sweet_pct": d["sweet_pct"], "current_cents": d["current"]["price_cents"],
                         "running_cut_at_as_of": running, "sale_max_cut": max_cut, "sale_min_cents": low,
                         "steam_max_cut": steam_max, "source": "user" if sources != ("itad-history", "legacy-itad") else "default",
                         "hit_sweet": None if low is None else low <= d["sweet_cents"]})

    print("status:", dict(status))
    games_disagree = sorted({n for n, *_ in disagree})
    print(f"units where crossing (backtest) != sale max cut: {len(disagree)} in {len(games_disagree)} games")
    for n in games_disagree:
        lv = [l for m, l, *_ in disagree if m == n]
        r = next(x for x in disagree if x[0] == n)
        print(f"   {n}: levels {min(lv)}–{max(lv)}%, cut at as_of {r[2]}, sale max {r[3]}")

    for name, idx in (("crossing (backtest)", 3), ("sale max cut", 4)):
        unw = sum((u[2] - u[idx]) ** 2 for u in units) / len(units)
        per = collections.defaultdict(list)
        for u in units:
            per[u[0]].append((u[2] - u[idx]) ** 2)
        game_w = sum(sum(v) / len(v) for v in per.values()) / len(per)
        print(f"Brier [{name}]: units {len(units)}, games {len(per)}: unit-weighted {unw:.4f}, game-weighted {game_w:.4f}")

    print("decision: (group, sweet point) -> n, hit sweet price in sale, no price")
    table = collections.defaultdict(lambda: [0, 0, 0])
    for r in rows_out:
        if "group" not in r:
            continue
        k = (r["group"], r["sweet_point"])
        table[k][0] += 1
        table[k][1] += r["hit_sweet"] is True
        table[k][2] += r["hit_sweet"] is None
    for k in sorted(table, key=str):
        print("  ", k, table[k])
    print("now group: current at as_of vs sale low (NT$)")
    for r in rows_out:
        if r.get("group") == "now":
            print(f"   {r['name']}: {r['current_cents'] / 100:.0f} → {r['sale_min_cents'] / 100:.0f}")
    print("ITAD sale max cut vs Steam daily snapshot max cut (differences):")
    for r in rows_out:
        if r.get("sale_max_cut") is not None and r.get("steam_max_cut") != r.get("sale_max_cut"):
            print(f"   {r['name']} [{r['source']}]: ITAD {r['sale_max_cut']} vs Steam {r['steam_max_cut']}")
    OUT.mkdir(exist_ok=True)
    (OUT / "p1_actual.json").write_text(json.dumps(rows_out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
