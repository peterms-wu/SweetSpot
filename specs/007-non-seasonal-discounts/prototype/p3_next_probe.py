"""P3 (after 007, for the next direction; 2026-09-26) — proposal probe (tuning only, read-only): buy-now decisions of rule 2.1.0 vs the non-seasonal forecast.

For each buy-now decision: p = non-seasonal probability (60 days) of reaching at least 5 pp deeper than the current
cut; outcome = the price went at least 5 pp deeper within 60 days (any sale, seasonal or not), and the saving then.
"""
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from steamsage.forecast.backtest.dataset import build_dataset
from steamsage.forecast.contract import LEVELS
from steamsage.forecast.engine import all_apps, is_paid_at, load_games
from steamsage.forecast.nonseasonal import current_ns_model
from steamsage.forecast.nonseasonal.backtest import _present, build_frame, earlier_decisions
from steamsage.forecast.nonseasonal.engine import predict_ns
from steamsage.store.query import PriceStore

CUTOFF = datetime(2026, 9, 25, tzinfo=UTC)
store = PriceStore.open(Path("data/steamsage.db"))
games = load_games(store, all_apps(store), CUTOFF)
events = store.calendar_events()
ds = build_dataset(store, games, events, cutoff=CUTOFF, regions=("TW",), split="tuning")
rd = ds.regions["TW"]
decisions = earlier_decisions(ds, games, events)
model = current_ns_model()
frame = build_frame(ds, games, events, model.params["history"])
buckets = defaultdict(lambda: [0, 0, 0.0, 0])        # bucket -> [n, deeper, saving NT$ sum, known]
total_now = 0
for as_of in rd.schedule:
    model.prepare(frame.population_at(as_of, _present(games, rd.population_apps, as_of)))
    for app in _present(games, rd.apps, as_of):
        dec = decisions.get((app, as_of))
        if not dec or dec[0] != "now":
            continue
        s = games[app].series["TW"]
        st = s.state_at(as_of)
        target = st.cut - st.cut % 5 + 5
        if target > 95:
            continue
        total_now += 1
        out = predict_ns(model, frame.evidence(app, as_of))
        if isinstance(out, str):
            continue
        p = out.probabilities[1][LEVELS.index(target)]
        b = "<0.2" if p < 0.2 else "0.2-0.35" if p < 0.35 else "0.35-0.5" if p < 0.5 else ">=0.5"
        hi = as_of + timedelta(days=60)
        if s.known_until is None or s.known_until < hi:
            continue
        later = [x for x in s.states if as_of < x.start <= hi]
        best = max((x.cut for x in later), default=0)
        row = buckets[b]
        row[3] += 1
        if best >= target:
            row[1] += 1
            row[2] += st.regular_cents * (best - st.cut) / 100 / 100
        row[0] += 1
print("buy-now decisions", total_now)
for b in ("<0.2", "0.2-0.35", "0.35-0.5", ">=0.5"):
    n, deeper, saving, _ = buckets[b]
    if n:
        print(b, "n", n, "deeper within 60d", f"{deeper / n:.1%}", "mean extra saving when deeper NT$",
              round(saving / deeper, 1) if deeper else None)
