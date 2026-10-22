"""One post-sale comparison from start to finish (feature 013): pick the target, review every game, the bundles and
the recompute, then summarise. The command only parses arguments, writes the file and prints."""

from datetime import datetime
from pathlib import Path
from typing import Any

from sweetspot.forecast.nonseasonal.events import SeasonalWindows
from sweetspot.review import contract, score
from sweetspot.review.actual import SaleActual, Tracked, cross_check, sale_actual, tracked_series
from sweetspot.review.recompute import recompute
from sweetspot.review.target import ReviewTarget, select_target
from sweetspot.store.query import PriceStore


def review_one(store: PriceStore, decision: dict, target: ReviewTarget,
               today: datetime) -> tuple[Tracked | None, SaleActual | None]:
    """(tracked series, sale actual) for one decision; a failure only makes this game no-actual (constitution III)."""
    if decision.get("status") != "ok":
        return None, None
    try:
        tracked = tracked_series(store, decision, target.sale, today)
        if tracked.reason is not None:
            return tracked, None
        actual = sale_actual(tracked, target.sale, target.as_of)
        option = tracked.option or {}
        if option.get("kind") and option.get("id") is not None:
            actual = cross_check(actual, store.option_steps(decision["app_id"], option["kind"], option["id"],
                                                            target.sale.start, target.sale.end))
        return tracked, actual
    except Exception as exc:  # noqa: BLE001
        version = decision.get("version") or {}
        return Tracked(version.get("itad_id"), "user" if version.get("source") == "user" else "default",
                       version.get("option"), None, (), None, f"讀取價格時發生錯誤：{type(exc).__name__}: {exc}"), None


def _bundle_steps(store: PriceStore, bundle: dict, target: ReviewTarget) -> list:
    for c in bundle.get("contents") or []:          # the bundle's rows are stored under each content app
        steps = store.option_steps(c["app_id"], "bundle", bundle["id"], target.sale.start, target.sale.end)
        if steps:
            return steps
    return []


def run_review(store: PriceStore, forecasts_dir: Path, *, sale: str | None, record: str | None, today: datetime,
               force: bool, with_recompute: bool, run: dict[str, Any]) -> tuple[ReviewTarget, dict[str, Any]]:
    """(target, steamsage.review/1 dict). Raises TargetError when there is nothing to compare."""
    events = store.calendar_events()
    target = select_target(events, forecasts_dir, sale=sale, record=record, today=today, force=force)
    rec = target.record
    forecasts = {g["app_id"]: g for g in (rec.get("forecast") or {}).get("games") or []}
    windows = SeasonalWindows.from_events(events)
    horizons = tuple((rec.get("non_seasonal") or {}).get("horizons_days") or (30, 60, 90))
    games = []
    for d in rec.get("decisions") or []:
        tracked, actual = review_one(store, d, target, today)
        game = score.review_game(d, forecasts.get(d["app_id"]), tracked, actual, target.sale, target.during,
                                 target.missing_days)
        game["non_seasonal"] = score.ns_review(d, tracked.series if tracked else None, windows, target.as_of, today,
                                               horizons)
        games.append(game)
    by_app = {g["app_id"]: g for g in games}
    bundles = [score.bundle_review(b, _bundle_steps(store, b, target), by_app, target.sale)
               for b in rec.get("bundles") or []]
    recomputed = recompute(store, rec, target.as_of) if with_recompute else None
    seed = score.seed_for(target.record_path.name)
    summary = {"counts": contract.counts(rec, games),
               "seasonal": score.seasonal_summary(games, seed),
               "decisions": score.decision_summary(games, rec, seed),
               "bundles": bundles, "non_seasonal": score.ns_summary(games, rec, seed),
               "recompute": None if recomputed is None else score.recompute_summary(games, rec, recomputed,
                                                                                    target.sale, seed),
               "mismatches": score.mismatches(games)}
    sources = {"seasonal": score.SEASONAL_SOURCE, "rule": (rec.get("rule_backtest") or {}).get("source"),
               "non_seasonal": ((rec.get("non_seasonal") or {}).get("backtest") or {}).get("source")}
    return target, contract.review_dict(target, games, summary, sources, run)


def partial(target: ReviewTarget, data: dict) -> bool:
    """Exit code 2 (contracts/review.md §1): unknown or corrected games, skipped records, or a forced run."""
    c = data["summary"]["counts"]
    return bool(c["no_actual"] or c["corrected"] or target.skipped_records or target.forced)
