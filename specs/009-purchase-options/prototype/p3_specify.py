"""P3 (plan): does specifying editions change only those games? (spec SC-001, SC-002, SC-007; research R3–R5)

Runs on the real database (read-only) and on out/p2.db (the copy with edition histories, P2):
  A  real database, current code                              -> baseline decisions
  B0 copy, no specification, current code                     -> do the added rows leak into anything?
  B  copy, no specification, with the R3 reader fix           -> must equal A (SC-001)
  C  copy, 10 editions specified, population from the default  -> non-targets must equal A (SC-002)
  D  dataset ids at cutoff 2026-09-25 (TW), real vs copy       -> must be equal (SC-007)
The design is emulated with monkeypatches (research R4, R5); nothing is written. Writes out/p3.json.
"""
import gzip
import json
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import steamsage.decision.engine as dengine
import steamsage.forecast.engine as fengine
import steamsage.forecast.series as fseries
import steamsage.store.query as query
from steamsage.config import load_config
from steamsage.decision.contract import batch_to_dict
from steamsage.decision.prices import CurrentPrice
from steamsage.forecast.backtest.dataset import build_dataset
from steamsage.forecast.engine import all_apps, is_paid_at, load_games
from steamsage.forecast.models import current_model
from steamsage.forecast.nonseasonal.evidence import NSFrame
from steamsage.forecast.nonseasonal.engine import LOOKBACK_DAYS, predict_ns
from steamsage.store.query import HistoryKey, PriceStore
from steamsage.timeutil import now_utc

OUT = Path(__file__).parent / "out"
OPTION = "itad-option-history"
TARGETS = {1091500: ("bundle", 32470), 489830: ("sub", 626153), 812140: ("sub", 349020), 1402110: ("sub", 874282),
           601150: ("sub", 613145), 881020: ("sub", 1587333), 1259420: ("bundle", 51775), 4570720: ("bundle", 77856),
           1771300: ("sub", 1109733), 1903340: ("sub", 1218615)}
p1 = json.loads((OUT / "p1.json").read_text(encoding="utf-8"))
edition = {}
for r in p1["rows"]:
    kind, oid = ("sub", r["package_id"]) if r["package_id"] else ("bundle", r["bundle_id"])
    if TARGETS.get(r["app_id"]) == (kind, oid):
        edition[r["app_id"]] = r
assert len(edition) == len(TARGETS), set(TARGETS) - set(edition)
prefs = load_config(Path("steamsage.toml"))[0].preferences
AS_OF = now_utc()
T = {}


def decisions(store, label):
    t0 = time.perf_counter()
    batch = dengine.run_decisions(store, store.wishlist_apps(), AS_OF, current_model(), prefs, now=AS_OF)
    T[label] = round(time.perf_counter() - t0, 1)
    return {d["app_id"]: d for d in batch_to_dict(batch)["decisions"]}


def diff(a, b):
    return sorted(k for k in a if json.dumps(a[k], sort_keys=True, default=str) != json.dumps(b.get(k), sort_keys=True,
                                                                                               default=str))


# --- R3 reader fix: rows of the option source are ITAD rows of a product, filtered by key like itad-history --------
def latest_observations(self, app_ids, region, as_of, keys=None):
    wanted, keep, out = set(app_ids), self._key_filter(keys), {}
    rows = self.conn.execute(
        "SELECT app_id, region, source, observed_at, retrieved_at, regular_cents, price_cents, cut_pct, "
        "is_tracking_start, external_id FROM price_observations WHERE region = ? AND observed_at <= ? "
        "AND anomaly IS NULL AND source != ? ORDER BY app_id, observed_at, "
        "CASE source WHEN 'steam-current' THEN 1 ELSE 0 END, obs_id", (region, query.to_db(as_of), OPTION))
    for r in rows:
        if r[0] in wanted and (r[2] not in query.ITAD_SOURCES or keep(r[0], r[9])):
            out[r[0]] = query._observation(r)
    return out


ORIGINAL_LATEST = PriceStore.latest_observations


@contextmanager
def patched(pairs):
    saved = [(obj, name, getattr(obj, name)) for (obj, name), value in pairs.items()]
    for (obj, name), value in pairs.items():
        setattr(obj, name, value)
    try:
        yield
    finally:
        for obj, name, value in saved:
            setattr(obj, name, value)


def load_option_games(store, apps, as_of):
    """R4: each target app reads its specified edition's rows (option source) with the edition's ITAD product."""
    keys = {a: HistoryKey(edition[a]["itad_id"], "user") for a in apps}
    with patched({(query, "ITAD_SOURCES"): (OPTION, OPTION), (fseries, "ITAD_SOURCES"): (OPTION,)}):
        return load_games(store, apps, as_of, keys=keys)


real = PriceStore.open(Path("data/steamsage.db"))
A = decisions(real, "A_real")
copy = PriceStore.open(OUT / "p2.db", Path("data/steam_sales.toml"))
B0 = decisions(copy, "B0_copy_nofix")
with patched({(PriceStore, "latest_observations"): latest_observations}):
    B = decisions(copy, "B_copy_fix")

    # --- C: specified editions ----------------------------------------------------------------------------------
    universe = sorted(set(all_apps(copy)) | set(copy.wishlist_apps()))
    t0 = time.perf_counter()
    base_games = load_games(copy, universe, AS_OF)
    chosen = load_option_games(copy, sorted(TARGETS), AS_OF)
    T["C_load_targets"] = round(time.perf_counter() - t0, 1)
    merged = {**base_games, **chosen}
    population = [g for g in base_games.values() if is_paid_at(g, AS_OF)]
    original_view = fengine.population_view

    def view(_pop, as_of, region):             # R4: the population always comes from the default versions
        return original_view(population, as_of, region)

    original_prices = dengine.current_prices

    def prices(store, app_ids, as_of, history_regular):     # R5: current price of the chosen option
        out = original_prices(store, app_ids, as_of, history_regular)
        for a in TARGETS:
            r = edition[a]
            hist = history_regular.get(a)
            cut = round(100 - 100 * r["final_cents"] / r["original_cents"]) if r["original_cents"] else 0
            out[a] = CurrentPrice(r["final_cents"], r["original_cents"], cut, "steam-option", AS_OF, AS_OF, False,
                                  hist, hist is not None and hist != r["original_cents"])
        return out

    original_ns = dengine.ns_forecast

    def ns(store, wanted, as_of, model, games=None):        # R4: non-seasonal population also from the defaults
        batch = original_ns(store, wanted, as_of, model, games=base_games)
        frame = NSFrame(chosen, store.sales(as_of, include_estimates=False), model.params["history"], population=[],
                        clock=False, since=as_of - __import__("datetime").timedelta(days=LOOKBACK_DAYS), live=True)
        for a in TARGETS:
            batch.outputs[a] = predict_ns(model, frame.evidence(a, as_of)) if a in frame.games else "沒有台灣區的價格歷史"
        return batch

    with patched({(fengine, "population_view"): view, (dengine, "load_games"): lambda s, apps, as_of: merged,
                    (dengine, "current_prices"): prices, (dengine, "ns_forecast"): ns}):
        C = decisions(copy, "C_specified")

# --- D: dataset ids ------------------------------------------------------------------------------------------------
cutoff = datetime(2025, 9, 25, tzinfo=timezone.utc).replace(year=2026)
ids = {}
if "--no-dataset" not in sys.argv:
    for label, store in (("real", real), ("copy", copy)):
        t0 = time.perf_counter()
        games = load_games(store, all_apps(store), cutoff)
        ds = build_dataset(store, games, store.calendar_events(), cutoff=cutoff, regions=("TW",))
        ids[label] = ds.regions["TW"].dataset_id
        T[f"D_{label}"] = round(time.perf_counter() - t0, 1)


def brief(d):
    return {k: d.get(k) for k in ("group", "confidence", "sweet_twd", "p_min_twd")} | {
        "sweet_pct": d.get("sweet_pct"),
        "point": (d.get("sweet_point") or {}).get("label"), "prob": d.get("sweet_probability"),
        "regular": (d.get("current") or {}).get("regular_twd"), "price": (d.get("current") or {}).get("price_twd"),
        "mismatch": (d.get("current") or {}).get("regular_mismatch")}


result = {
    "as_of": AS_OF.isoformat(), "seconds": T, "dataset_ids": ids,
    "B0_vs_A": diff(A, B0), "B_vs_A": diff(A, B),
    "C_nontarget_vs_A": [a for a in diff(A, C) if a not in TARGETS],
    "targets": {a: {"name": A[a]["name"], "edition": edition[a]["option_name"], "default": brief(A[a]),
                    "specified": brief(C[a]), "reasons": C[a].get("reasons")} for a in TARGETS},
}
(OUT / "p3.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
print(json.dumps({k: result[k] for k in ("seconds", "dataset_ids", "B0_vs_A", "B_vs_A", "C_nontarget_vs_A")},
                 ensure_ascii=False))
for a, t in result["targets"].items():
    print(f"{t['name'][:22]:22} | {t['edition'][:28]:28}\n   default  {t['default']}\n   specified {t['specified']}")
