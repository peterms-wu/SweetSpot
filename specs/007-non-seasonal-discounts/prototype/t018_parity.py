"""T018 (spec SC-001): the formal definitions against the prototype's, on the TW tuning split. Read-only.

1. Non-seasonal arrivals: formal `events.arrivals` + full-calendar classification vs `nslib.arrivals`, per game.
2. Promotion starts used by the clock: formal (non-seasonal arrivals from no discount) vs `nslib.promos` starts.
3. Promotions for the basis (overlap-based, with the 1-day tolerance) vs P0 (`p0_quantify.py` episodes, whose
   overlap check had no tolerance): counts per game-year and the depth-vs-record split, with the difference.
"""
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import nslib  # noqa: E402

from steamsage.forecast.backtest.dataset import build_dataset
from steamsage.forecast.engine import all_apps, load_games
from steamsage.forecast.nonseasonal.events import SeasonalWindows, arrivals, promos
from steamsage.store.query import PriceStore

CUTOFF = datetime(2026, 9, 25, tzinfo=UTC)
store = PriceStore.open(Path("data/steamsage.db"))
games = load_games(store, all_apps(store), CUTOFF, regions=("TW",))
events = store.calendar_events()
apps = build_dataset(store, games, events, cutoff=CUTOFF, regions=("TW",), split="tuning").regions["TW"].apps
seasonal = [(e.start, e.end) for e in events if e.kind == "seasonal"]
formal_w, proto_w = SeasonalWindows(seasonal), nslib.Windows(seasonal)

diff_arr = diff_starts = 0
episodes_formal = episodes_p0 = 0
by_game = Counter()
for a in apps:
    s = games[a].series["TW"]
    f_arr = [(x.at, x.from_cut, x.to_cut) for x in arrivals(s, formal_w) if not x.seasonal()]
    p_arr = nslib.arrivals(s, proto_w)
    diff_arr += f_arr != p_arr
    f_starts = [x[0] for x in f_arr if x[1] == 0]
    p_starts = [t for t, _ in nslib.promos(s, proto_w)]
    diff_starts += f_starts != p_starts
    n_formal = len(promos(s, formal_w, CUTOFF))
    # P0: episodes that overlap no seasonal sale, without the tolerance, and not the tracking start
    st, n_p0, i = s.states, 0, 0
    while i < len(st):
        if st[i].cut <= 0:
            i += 1
            continue
        j = i
        while j < len(st) and st[j].cut > 0:
            j += 1
        end = st[j].start if j < len(st) else s.known_until
        if i > 0 and not any(x < end and st[i].start < y for x, y in seasonal):
            n_p0 += 1
        i = j
    episodes_formal += n_formal
    episodes_p0 += n_p0
    if n_formal != n_p0:
        by_game[n_formal - n_p0] += 1

out = {"games": len(apps), "arrivals_differ": diff_arr, "clock_starts_differ": diff_starts,
       "promotions_formal": episodes_formal, "promotions_p0": episodes_p0,
       "games_with_a_difference": sum(by_game.values()), "difference_per_game": dict(sorted(by_game.items()))}
(Path(__file__).parent / "out" / "t018_parity.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
print(json.dumps(out, indent=1))
