"""T018: why the formal model scores better than prototype M3/M1 at 60 and 90 days. Tuning only, read-only.

For every scored unit of the TW tuning split, the prototype's M1 probability (nslib) and the formal model's own
share (smoothing 2, TW+US, no clock) are computed side by side, with the same scoring. Result (2026-09-26):
- the probabilities and outcomes are identical for every unit (0 differing units);
- game-weighted Brier without the monotone steps = the prototype (0.12626 / 0.13777 / 0.13738);
- with the formal steps (non-increasing in d, then non-decreasing in h) = the formal model exactly
  (0.12626 / 0.1341 / 0.12609). At early as_ofs the population share for 60/90 days is 0 (no TW history is
  long enough yet), and the non-decreasing step lifts those rows to the 30-day row.
"""
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
sys.path.insert(0, "specs/007-non-seasonal-discounts/prototype")
from nslib import GameNS as PGame, Windows, history_view, window_fraction as pwf, HORIZONS, LEVELS, arrived
from steamsage.forecast.backtest.dataset import build_dataset
from steamsage.forecast.engine import all_apps, is_paid_at, load_games
from steamsage.forecast.nonseasonal.backtest import build_frame
from steamsage.forecast.nonseasonal.events import window_fraction, arrived_levels
from steamsage.store.query import PriceStore

CUTOFF = datetime(2026, 9, 25, tzinfo=UTC)
store = PriceStore.open(Path("data/steamsage.db"))
games = load_games(store, all_apps(store), CUTOFF)
events = store.calendar_events()
ds = build_dataset(store, games, events, cutoff=CUTOFF, regions=("TW",), split="tuning")
rd = ds.regions["TW"]
win = Windows([(e.start, e.end) for e in events if e.kind == "seasonal"])
frame = build_frame(ds, games, events, "TW+US")
tot = {h: [0, 0.0, 0.0] for h in HORIZONS}
from collections import defaultdict
pg = defaultdict(lambda: [0, 0.0, 0.0])
pm = defaultdict(lambda: [0, 0.0])
for as_of in rd.schedule:
    pool = [a for a in rd.population_apps if games[a].series["TW"].first_start <= as_of and is_paid_at(games[a], as_of)]
    pop = frame.population_at(as_of, pool)
    apps = [a for a in rd.apps if games[a].series["TW"].first_start <= as_of and is_paid_at(games[a], as_of)]
    nd = 0
    for a in apps:
        rowsp = {}
        tw = PGame(games[a].series["TW"], win); us = PGame(games[a].series["US"], win) if "US" in games[a].series else None
        arrs, _, start = history_view(tw, us, "TW+US", as_of)
        start = max(start, as_of - timedelta(days=365))
        months = (as_of - start).days / 30.44
        ev = frame.evidence(a, as_of)
        fstart = max(ev.history_start, as_of - timedelta(days=365)); span = (ev.known_until - fstart).days
        for h in HORIZONS:
            known = tw.known
            if known is None or known < as_of + timedelta(days=h):
                continue
            got_p = arrived(tw.arrs, as_of, as_of + timedelta(days=h))
            got_f = arrived_levels(frame.games[a].tw_arrivals, as_of, as_of + timedelta(days=h), LEVELS)
            for d in LEVELS:
                base = pop.share[(h, d)]
                if (as_of - start).days >= h + 30:
                    f = pwf(sorted(t for t, p, c in arrs if p < d <= c and t > start), start, as_of, h)
                    w = max(months - h / 30.44, 0); p_p = (w * f + 2 * base) / (w + 2)
                else:
                    p_p = base
                if span >= h + 30:
                    f2 = window_fraction([x.at for x in ev.arrivals if x.reaches(d) and x.at > fstart], fstart, ev.known_until, h) or 0.0
                    w2 = max(span / 30.44 - h / 30.44, 0); p_f = (w2 * f2 + 2 * base) / (w2 + 2)
                else:
                    p_f = base
                if abs(p_p - p_f) > 1e-9 or (d in got_p) != (d in got_f):
                    nd += 1
                tot[h][0] += 1; tot[h][1] += (p_p - (d in got_p)) ** 2; tot[h][2] += (p_f - (d in got_f)) ** 2
                g = pg[(a, h)]; g[0] += 1; g[1] += (p_p - (d in got_p)) ** 2
                rowsp.setdefault(h, {})[d] = (p_p, d in got_p)
        # full rows are needed for the monotone steps: recompute p for every h (scored or not)
        full = {}
        for h in HORIZONS:
            row = []
            for d in LEVELS:
                base = pop.share[(h, d)]
                if (as_of - start).days >= h + 30:
                    f = pwf(sorted(t for t, p, c in arrs if p < d <= c and t > start), start, as_of, h)
                    w = max(months - h / 30.44, 0); row.append((w * f + 2 * base) / (w + 2))
                else:
                    row.append(base)
            fl, out = 1.0, []
            for x in row:
                fl = min(fl, min(x, 0.99)); out.append(fl)
            if full:
                out = [max(x, y) for x, y in zip(out, full[max(full)])]
            full[h] = out
        for h, cells in rowsp.items():
            for d, (pp, o) in cells.items():
                q = full[h][LEVELS.index(d)]
                m = pm[(a, h)]; m[0] += 1; m[1] += (q - o) ** 2
print({h: (v[0], round(v[1] / v[0], 5), round(v[2] / v[0], 5)) for h, v in tot.items()})

for h in HORIZONS:
    vals = [v[1] / v[0] for (a, hh), v in pg.items() if hh == h]
    print(h, "game-weighted", round(sum(vals) / len(vals), 5), len(vals))

for h in HORIZONS:
    vals = [v[1] / v[0] for (a, hh), v in pm.items() if hh == h]
    print(h, "with monotone steps", round(sum(vals) / len(vals), 5))
