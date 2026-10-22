"""Run a backtest over a dataset and write `steamsage.backtest/1` (contracts/backtest-result.md).

Everything is loaded once up to the cutoff; for each as_of the evidence is truncated in memory
(research R7; equivalence checked by tests/contract/test_no_future_leak.py).
"""

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from sweetspot import __version__
from sweetspot.calendar import SaleEvent
from sweetspot.forecast.backtest.dataset import BacktestDataset
from sweetspot.forecast.backtest.metrics import RegionMetrics
from sweetspot.forecast.backtest.scoring import (actual_sales, finished_outcomes, horizon_group, score_case,
                                                 window_points)
from sweetspot.forecast.backtest.split import SALT
from sweetspot.forecast.contract import iso, write_json_atomic
from sweetspot.forecast.engine import is_paid_at, predict_one
from sweetspot.forecast.evidence import GameData, game_evidence, population_view
from sweetspot.forecast.models.base import Model
from sweetspot.forecast.models.seasonal_freq import SeasonalFreq
from sweetspot.forecast.salepoints import sale_points
from sweetspot.store.query import PriceStore
from sweetspot.timeutil import now_utc

SCHEMA = "steamsage.backtest/1"


def _reference_model() -> SeasonalFreq:
    """FR-021: everyone gets the population share (TW-only history for a TW target)."""
    return SeasonalFreq(min_sales=10**9, history="TW")


def release_facts(dataset: BacktestDataset, games: Mapping[int, GameData]) -> dict[str, Any]:
    """Which release dates the run could see (feature 008 research R3): not part of any dataset id, recorded so a
    rerun shows whether the static facts changed."""
    apps = sorted({a for rd in dataset.regions.values() for a in (*rd.apps, *rd.population_apps)})
    pairs = [[a, games[a].release_date.isoformat() if games[a].release_date else None] for a in apps]
    return {"count": len(pairs), "known": sum(v is not None for _, v in pairs),
            "sha256": hashlib.sha256(json.dumps(pairs).encode()).hexdigest()}


def result_filename(model: Model, dataset: BacktestDataset, started: datetime) -> str:
    params = hashlib.sha256(json.dumps(dict(model.params), sort_keys=True).encode()).hexdigest()[:6]
    regions = sorted(dataset.regions)
    combined = hashlib.sha256("".join(dataset.regions[r].dataset_id for r in regions).encode()).hexdigest()[:8]
    return f"{started.strftime('%Y%m%dT%H%M%SZ')}_{model.name}-{model.version}_{params}_{'-'.join(regions)}_{combined}.json"


def run_backtest(store: PriceStore, dataset: BacktestDataset, games: Mapping[int, GameData],
                 events: Sequence[SaleEvent], model: Model, *, out_dir: Path | None = None,
                 progress: Callable[[str], None] | None = None,
                 now: datetime | None = None) -> tuple[dict[str, Any], Path | None]:
    started_at = now or now_utc()
    clock = time.monotonic()
    actual = actual_sales(events)
    levels = list(dataset.levels)
    reference = _reference_model()
    regions_out, per_game, per_game_sales, errors = {}, {}, {}, []

    for region in sorted(dataset.regions, key=["TW", "US"].index):
        rd = dataset.regions[region]
        metrics = RegionMetrics(region, levels)
        for n, as_of in enumerate(rd.schedule, 1):
            if progress:
                progress(f"回測 {region} 分析時點 {n}/{len(rd.schedule)}（{as_of.strftime('%Y-%m-%d')}）")
            def here(a):
                return games[a].series[region].first_start <= as_of and (region != "TW" or is_paid_at(games[a], as_of))

            present = [a for a in rd.apps if here(a)]
            if not present:
                continue
            pool = present if rd.population_apps == rd.apps else [a for a in rd.population_apps if here(a)]
            points = sale_points([e for e in events if e.start <= as_of], as_of)
            window = window_points(points, as_of, region)
            if not window:
                continue
            first_window = points.index(window[0])
            horizons = [horizon_group(region, as_of, p.end) for p in window]
            indexes = [p.index for p in window]
            population = population_view((games[a] for a in pool), as_of, region)
            model.prepare(population)
            reference.prepare(population)
            for app in present:
                evidence = game_evidence(games[app], as_of, region)
                out = predict_one(model, evidence, points, levels)
                if isinstance(out, str):
                    errors.append({"app_id": app, "as_of": as_of.strftime("%Y-%m-%d"), "region": region,
                                   "reason": out})
                    continue
                ref = predict_one(reference, evidence, points, levels)
                if isinstance(ref, str):
                    errors.append({"app_id": app, "as_of": as_of.strftime("%Y-%m-%d"), "region": region,
                                   "reason": f"參照分數：{ref}"})
                    continue
                span = slice(first_window, first_window + len(window))
                own = evidence.sale_history.get(region, ())
                series = games[app].series[region]
                firsts = series.first_crossings(as_of, levels)
                metrics.add(app=app, pool=dataset.pools.get(app, "legacy"), confidence=out.confidence,
                            horizons=horizons, indexes=indexes, probs=out.probabilities[span],
                            ref=ref.probabilities[span],
                            outcomes=score_case(series, as_of, window, levels, actual, firsts),
                            own_sales=len(own), past_max=max((o.max_cut for o in own), default=None),
                            finished=finished_outcomes(series, window, levels, actual, firsts))
        summary = metrics.result()
        per_game[region] = summary.pop("per_game")
        per_game_sales[region] = summary.pop("per_game_by_own_sales")
        summary["as_of_count"] = len(rd.schedule)
        regions_out[region] = summary

    result = {
        "schema": SCHEMA,
        "model": {"name": model.name, "version": model.version, "params": dict(model.params)},
        "dataset": {
            "cutoff": iso(dataset.cutoff), "levels": levels, "calendar_hash": dataset.calendar_hash,
            "split": {"name": dataset.split, "salt": SALT},
            "regions": {r: {"dataset_id": rd.dataset_id, "schedule": [t.strftime("%Y-%m-%d") for t in rd.schedule],
                            "window_months": list(rd.window), "games": len(rd.apps),
                            "population_games": len(rd.population_apps)}
                        for r, rd in dataset.regions.items()},
        },
        "regions": regions_out,
        "per_game": per_game,
        "per_game_by_own_sales": per_game_sales,
        "release_facts": release_facts(dataset, games),
        "errors": errors,
        "run": {"started_at": iso(started_at), "finished_at": iso(now_utc()),
                "seconds": round(time.monotonic() - clock, 1), "steamsage_version": __version__},
    }
    path = None
    if out_dir is not None:
        path = write_json_atomic(Path(out_dir) / result_filename(model, dataset, started_at), result)
        result = json.loads(path.read_text(encoding="utf-8"))
    return result, path
