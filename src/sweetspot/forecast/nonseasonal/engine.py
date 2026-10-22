"""Non-seasonal forecasts at the present (the report) and the output checks (contracts/ns-model-api.md).

A failing or contract-breaking model only affects that game (constitution III): its entry becomes a reason string.
"""

import math
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sweetspot.forecast.contract import LEVELS
from sweetspot.forecast.engine import all_apps, is_paid_at, load_games
from sweetspot.forecast.evidence import GameData
from sweetspot.forecast.nonseasonal import HORIZONS, LOOKBACK_DAYS, P_CAP
from sweetspot.forecast.nonseasonal.evidence import NSEvidence, NSFrame
from sweetspot.forecast.nonseasonal.model import NSOutput
from sweetspot.store.query import PriceStore


def check_output(out: NSOutput, as_of: datetime, levels: Iterable[str]) -> str | None:
    """The contract's guarantees 1-5; None when the output is fine."""
    rows = out.probabilities
    if len(rows) != len(HORIZONS) or any(len(r) != len(LEVELS) for r in rows):
        return f"機率的形狀必須是 {len(HORIZONS)} × {len(LEVELS)}"
    for i, row in enumerate(rows):
        for j, p in enumerate(row):
            if not isinstance(p, (int, float)) or math.isnan(p) or not 0 <= p <= P_CAP:
                return f"機率超出 [0, {P_CAP}]：{p!r}"
            if j and p > row[j - 1]:
                return "較深的折扣機率不可較高"
            if i and p < rows[i - 1][j]:
                return "較長的期間機率不可較低"
    if out.confidence not in set(levels):
        return f"未知的信心等級：{out.confidence!r}"
    b = out.basis
    if any(t is not None and t > as_of for t in (b.history_start, b.last_start)):
        return "依據中的日期不可晚於分析時點"
    return None


def predict_ns(model, ev: NSEvidence) -> NSOutput | str:
    try:
        out = model.predict(ev)
    except Exception as exc:  # noqa: BLE001 - isolated to this game
        return f"{type(exc).__name__}: {exc}"
    problem = check_output(out, ev.as_of, model.confidence_levels())
    return problem if problem else out


@dataclass(frozen=True)
class NSForecastBatch:
    model: Mapping[str, Any]
    as_of: datetime
    outputs: Mapping[int, NSOutput | str]
    seconds: float


def ns_forecast(store: PriceStore, app_ids: Iterable[int], as_of: datetime, model,
                games: Mapping[int, GameData] | None = None,
                targets: Mapping[int, GameData] | None = None) -> NSForecastBatch:
    """Forecast the given apps at as_of from what the store knew then; the population is every paid game.
    `games` may be passed when the caller already loaded every app up to as_of (TW and US), as the report does.
    Feature 009: `targets` (the user's chosen editions) give only their own game's evidence (spec FR-012)."""
    clock = time.monotonic()
    wanted = sorted(set(app_ids))
    if games is None:
        universe = sorted(set(all_apps(store)) | set(wanted))
        games = load_games(store, universe, as_of, regions=("TW", "US"))
    population = [a for a, g in games.items() if is_paid_at(g, as_of)]
    frame = NSFrame(games, store.sales(as_of, include_estimates=False), model.params["history"],
                    population=population, clock=bool(model.params["clock"]),
                    since=as_of - timedelta(days=LOOKBACK_DAYS), live=True)
    model.prepare(frame.population_at(as_of, population))
    chosen = NSFrame(targets, frame.events, model.params["history"], population=[], clock=False,
                     since=as_of - timedelta(days=LOOKBACK_DAYS), live=True) if targets else None
    outputs: dict[int, NSOutput | str] = {}
    for app in wanted:
        source = chosen if chosen is not None and app in targets else frame
        if app not in source.games:
            outputs[app] = "沒有台灣區的價格歷史"
            continue
        outputs[app] = predict_ns(model, source.evidence(app, as_of))
    info = {"name": model.name, "version": model.version, "params": dict(model.params)}
    return NSForecastBatch(info, as_of, outputs, round(time.monotonic() - clock, 2))
