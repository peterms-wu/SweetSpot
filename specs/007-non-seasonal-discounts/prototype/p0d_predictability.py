"""P0-D: is the next non-seasonal discount predictable from the game's own past 12 months? TW tuning, read-only.

At every month start from 2026-01-01 to 2026-08-01 (12 months of TW history behind each), for each tuning game that is
paid and not discounted at as_of: k = non-seasonal episodes that started in the past 12 months. Outcome: a non-seasonal
episode starts within 30 / 60 days (games whose history is known through the horizon), and whether it is at least as
deep as the last non-seasonal one. Also the gap from the end of one discount to the start of the next.
"""
import json
import statistics as st
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from steamsage.forecast.backtest.dataset import build_dataset
from steamsage.forecast.engine import all_apps, is_paid_at, load_games
from steamsage.store.query import PriceStore
from steamsage.timeutil import add_months

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "out" / "p0d_out.json"
CUTOFF = datetime(2026, 9, 25, tzinfo=UTC)
store = PriceStore.open(Path("data/steamsage.db"))
games = load_games(store, all_apps(store), CUTOFF, regions=("TW",))
events = store.calendar_events()
apps = build_dataset(store, games, events, cutoff=CUTOFF, regions=("TW",), split="tuning").regions["TW"].apps
seasonal = sorted([(e.start, e.end) for e in events if e.kind == "seasonal" and e.start < CUTOFF])


def episodes(series):
    out, s, i = [], series.states, 0
    while i < len(s):
        if s[i].cut <= 0:
            i += 1
            continue
        j, best = i, 0
        while j < len(s) and s[j].cut > 0:
            best = max(best, s[j].cut)
            j += 1
        end = s[j].start if j < len(s) else series.known_until
        ns = not any(a < end and s[i].start < b for a, b in seasonal)
        out.append((s[i].start, end, best, i == 0, j >= len(s), ns))
        i = j
    return out


eps = {a: episodes(games[a].series["TW"]) for a in apps}
# gap between the end of a discount and the start of the next one (any kind), days
gaps = Counter()
for a in apps:
    e = eps[a]
    for x, y in zip(e, e[1:]):
        g = (y[0] - x[1]).days
        gaps["<7" if g < 7 else "7-27" if g < 28 else "28-29" if g < 30 else "30-44" if g < 45 else "45+"] += 1

res = defaultdict(lambda: [0, 0, 0, 0, 0])      # key -> [n, ns within 30d, within 60d, 60d & >= last depth, known60]
phase = defaultdict(lambda: [0, 0])
depth_repeat = Counter()
for as_of in [datetime(2026, m, 1, tzinfo=UTC) for m in range(1, 9)]:
    back = add_months(as_of, -12)
    for a in apps:
        series = games[a].series["TW"]
        if series.first_start > back or not is_paid_at(games[a], as_of) or series.state_at(as_of).cut > 0:
            continue
        known = series.known_until
        if known is None or known < as_of + timedelta(days=60):
            continue
        past = [e for e in eps[a] if e[5] and not e[3] and back < e[0] <= as_of]
        k = len(past)
        key = "0" if k == 0 else "1-2" if k < 3 else "3-4" if k < 5 else "5+"
        fut = [e for e in eps[a] if e[5] and as_of < e[0]]
        w30 = any(e[0] <= as_of + timedelta(days=30) for e in fut)
        f60 = [e for e in fut if e[0] <= as_of + timedelta(days=60)]
        deep = bool(past) and any(e[2] >= past[-1][2] for e in f60)
        r = res[key]
        r[0] += 1; r[1] += w30; r[2] += bool(f60); r[3] += deep
        if f60 and past:
            depth_repeat["same" if f60[0][2] == past[-1][2] else "deeper" if f60[0][2] > past[-1][2] else "shallower"] += 1
        if k >= 3:
            starts = [e[0] for e in past]
            med = st.median([(y - x).days for x, y in zip(starts, starts[1:])])
            ratio = (as_of - starts[-1]).days / med if med else 9
            b = "<0.5" if ratio < 0.5 else "0.5-1" if ratio < 1 else "1-1.5" if ratio < 1.5 else "1.5+"
            phase[b][0] += 1
            phase[b][1] += w30

out = {"gap_end_to_next_start_days": dict(gaps),
       "by_past_count": {k: {"n": v[0], "ns_30d": round(v[1] / v[0], 3), "ns_60d": round(v[2] / v[0], 3),
                             "ns_60d_at_least_last_depth": round(v[3] / v[0], 3)} for k, v in sorted(res.items())},
       "k>=3 by elapsed/median interval": {k: {"n": v[0], "ns_30d": round(v[1] / v[0], 3)} for k, v in sorted(phase.items())},
       "next_depth_vs_last": dict(depth_repeat)}
OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=1))
