"""Produce forecasts for a set of apps at one as_of (shared by `forecast` and the backtest runner).

The engine owns the forecast grid (sale points × LEVELS), status decisions and output validation; the model
only fills in probabilities (contracts/model-api.md).
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime

from sweetspot.choices import ChoiceResult
from sweetspot.forecast.contract import (LEVELS, CurveError, Forecast, ForecastBatch, ModelInfo, NoHistoryCurve,
                                         VersionChange, VersionInfo, validate_curve)
from sweetspot.forecast.evidence import REGIONS, GameData, GameEvidence, game_evidence, population_view
from sweetspot.forecast.models.base import Model, ModelOutput
from sweetspot.forecast.salepoints import SalePoint, future_sale_points
from sweetspot.forecast.series import build_series, sale_outcomes
from sweetspot.store.query import ITAD_SOURCES, HistoryKey, OptionKey, PriceStore
from sweetspot.timeutil import now_utc

BUNDLE_TYPES = ("package", "bundle")
ALL_STATES = frozenset({"in_wishlist", "removed_tracking", "reference_only"})


def all_apps(store: PriceStore) -> list[int]:
    return sorted(set(store.wishlist_apps(ALL_STATES)) | set(store.reference_apps()))


def load_games(store: PriceStore, app_ids: Iterable[int], cutoff: datetime,
               regions: Sequence[str] = REGIONS, keys: dict[int, HistoryKey] | None = None,
               sources: Sequence[str] = ITAD_SOURCES) -> dict[int, GameData]:
    """Series and seasonal-sale outcomes for each app, using only data observed at or before `cutoff`. Each app
    reads one ITAD product: its version at `cutoff`, else its own (feature 006, research R4). Feature 009: an
    edition chosen by the user is read with its key and sources=(OPTION_HISTORY_SOURCE,)."""
    apps = sorted(set(app_ids))
    keys = keys if keys is not None else store.history_keys(apps, cutoff)
    ids = store.key_ids(keys)
    sales = [e for e in store.sales(cutoff, include_estimates=False) if e.kind == "seasonal"]
    per_region = {}
    for region in regions:
        rows = store.series_rows(apps, region, cutoff, keys=ids, sources=sources)
        known = store.capped_known_until(store.history_known_until_all(region, keys=ids), keys)
        per_region[region] = {}
        for app in apps:
            until = known.get(app)
            series = build_series(rows.get(app, []), region, None if until is None else min(until, cutoff))
            per_region[region][app] = series
    releases = store.release_dates(apps)            # one query for all apps (feature 008 research R3)
    games = {}
    for app in apps:
        series = {r: per_region[r][app] for r in regions if per_region[r][app].states}
        games[app] = GameData(app, series, {r: sale_outcomes(s, sales) for r, s in series.items()},
                              releases.get(app))
    return games


def is_paid_at(game: GameData, moment: datetime) -> bool:
    series = game.series.get("TW")
    state = series.state_at(moment) if series else None
    return bool(state and state.regular_cents)


def predict_one(model: Model, evidence: GameEvidence, points: Sequence[SalePoint],
                levels: Sequence[int] = LEVELS) -> ModelOutput | str:
    """The model's output, or a reason string when it raised or broke FR-004 (constitution III)."""
    if not points:
        return "沒有未來的季節特賣時點（行事曆不足）"
    try:
        out = model.predict(evidence, points, levels)
        validate_curve(out.probabilities, len(points), len(levels))
        if out.confidence not in ("normal", "low") or not out.reasons:
            raise CurveError(f"模型輸出不完整：confidence={out.confidence!r}")
    except Exception as exc:  # noqa: BLE001 - any model failure is isolated to this game
        return f"{type(exc).__name__}: {exc}"
    return out


REJECT_REASONS = {
    "bundle": "ITAD 把 Steam 目前的購買選項（{package}）和組合包 {detail} 算成同一個商品，價格歷史混了不同商品的價格，無法使用",
    "other-games": "Steam 目前的購買選項（{package}）還包含其他遊戲（{detail}），不是這款遊戲本身",
    "price-mismatch": "ITAD 的商品同時對應到價格不同的購買選項（{detail}），價格歷史可能混了不同版本",
}
REJECT_DEFAULT = "Steam 目前的購買選項（{package}）在 ITAD 的商品核對未通過（{code} {detail}），沒有可信的價格歷史"


def rejected_reason(key: HistoryKey) -> str:
    record = key.record
    code = record.reason_code if record else None
    fmt = REJECT_REASONS.get(code, REJECT_DEFAULT)
    return fmt.format(package=(record.package_name if record else None) or "未知", detail=(record.reason_detail if
                      record else None) or "", code=code or "").replace("（ ）", "").strip()


def _option_ref(kind: str, option_id: int | None, name: str | None) -> dict | None:
    return None if option_id is None else {"kind": kind, "id": option_id, "name": name}


def version_info(key: HistoryKey, game: GameData | None, own_id: str | None = None,
                 app_name: str | None = None, choice: OptionKey | None = None,
                 aux_pending: bool = False) -> VersionInfo:
    """Feature 006's version object; feature 009 adds where the tracked option came from."""
    if choice is not None and choice.source == "user" and not choice.same_as_default:
        tw = game.series.get("TW") if game else None
        r = choice.record
        return VersionInfo(
            basis="user", package_id=r.option_id if r.kind == "sub" else None, package_name=r.name,
            itad_id=key.external_id, history_start=tw.first_start if tw else None,
            known_until=tw.known_until if tw else None,
            tracking=None if not tw else ("stopped" if key.stopped else "ok"),
            last_confirmed=key.last_confirmed if key.stopped else None, checked_at=r.checked_at, own_itad_id=own_id,
            source="user", option=_option_ref(r.kind, r.option_id, r.name), aux_pending=aux_pending)
    base = _version_info(key, game, own_id, app_name)
    record = key.record
    option = _option_ref("sub", record.package_id, record.package_name) if record else None
    if choice is None:
        return replace(base, source="steam-default", option=option)
    if choice.source == "user":               # the Steam default itself, or an edition on the default's product
        r = choice.record
        return replace(base, source="user", option=_option_ref(r.kind, r.option_id, r.name))
    requested = choice.record
    label = f"{requested.name}，{choice.requested[0]}/{choice.requested[1]}" if requested and requested.name \
        else f"{choice.requested[0]}/{choice.requested[1]}"
    text = ChoiceResult(False, requested, choice.fallback_code, choice.fallback_detail).fallback_text(label)
    fallback = {"code": choice.fallback_code, "detail": choice.fallback_detail, "text": text,
                "requested": {"kind": choice.requested[0], "id": choice.requested[1],
                              "name": requested.name if requested else None}}
    return replace(base, source="user-fallback", option=option, fallback=fallback)


def _version_info(key: HistoryKey, game: GameData | None, own_id: str | None = None,
                  app_name: str | None = None) -> VersionInfo:
    record = key.record
    tw = game.series.get("TW") if game else None
    change = None
    if key.change is not None:
        c = key.change
        change = VersionChange(c.from_itad_id, c.from_title or app_name, c.to_itad_id, c.to_title or app_name,
                               c.detected_at)
    tracking = None if not tw or key.basis == "rejected" else ("stopped" if key.stopped else "ok")
    return VersionInfo(
        basis=key.basis, basis_reason=key.basis_reason,
        package_id=record.package_id if record else None, package_name=record.package_name if record else None,
        itad_id=key.external_id, history_start=tw.first_start if tw else None,
        known_until=tw.known_until if tw else None, tracking=tracking,
        last_confirmed=key.last_confirmed if key.stopped else None, change=change,
        reason_code=record.reason_code if record and key.basis == "rejected" else None,
        reason_detail=record.reason_detail if record and key.basis == "rejected" else None,
        checked_at=record.checked_at if record else None, own_itad_id=own_id)


def _status(store: PriceStore, app_id: int, game: GameData | None, as_of: datetime, facts,
            key: HistoryKey | None = None) -> tuple[str, str] | None:
    product_type = facts.product_type.value
    if product_type in BUNDLE_TYPES:
        return "unsupported-bundle", "套裝（Package／Bundle）不在分析範圍內"
    if facts.released_as_of is False:
        return "unreleased", f"尚未發行（預定 {facts.release_date.value.isoformat()}）"
    if facts.released_as_of is None and facts.release_state.value == "coming_soon":
        return "unreleased", "尚未發行（發售日未定）"
    tw = game.series.get("TW") if game else None
    state = tw.state_at(as_of) if tw else None
    if state is not None and state.regular_cents == 0:
        return "free", "免費遊戲（台灣區原價為 0）"
    if key is not None and key.basis == "rejected":
        return "unverified", rejected_reason(key)
    if (key is None or key.basis == "own") and store.itad_mapping_state(app_id) == "rejected":
        return "unverified", "ITAD 的商品核對未通過，沒有可信的價格歷史"
    if state is None:
        return "no-history", "沒有台灣區的 ITAD 價格歷史"
    return None


def run_forecast(store: PriceStore, app_ids: Iterable[int], as_of: datetime, model: Model, *,
                 now: datetime | None = None,
                 progress: Callable[[int, int], None] | None = None,
                 games: Mapping[int, GameData] | None = None,
                 targets: Mapping[int, GameData] | None = None,
                 choices: Mapping[int, OptionKey] | None = None) -> ForecastBatch:
    """Forecast the given apps at as_of. Data is read with cutoff = as_of, so nothing later can leak (FR-009).
    `games` may be passed when the caller already loaded every app up to as_of (feature 007: the report loads once
    for the seasonal and the non-seasonal forecast). Feature 009: `targets` are the user's chosen editions, used
    only for their own game's evidence; the population always comes from `games` (spec FR-012). `choices` are the
    resolved choices (store.option_keys) for the version object."""
    targets = targets or {}
    choices = choices or {}
    wanted = sorted(set(app_ids))
    universe = sorted(set(all_apps(store)) | set(wanted))
    keys = store.history_keys(universe, as_of)
    own_ids = store.own_keys(wanted)
    tracking = store.has_versions()          # before the first version step there is nothing to report
    if games is None:
        games = load_games(store, universe, as_of, keys=keys)
    population = [g for g in games.values() if is_paid_at(g, as_of)]
    model.prepare(population_view(population, as_of, "TW"))
    points = future_sale_points(store, as_of)
    no_history = no_history_curve(model, as_of, points)

    forecasts = []
    pending = _aux_pending(store, targets, choices)
    for n, app_id in enumerate(wanted, 1):
        game = targets.get(app_id, games.get(app_id))
        facts = store.facts(app_id, as_of)
        name = facts.name.value
        choice = choices.get(app_id)
        key = choice.key if choice is not None else keys[app_id]
        status = _status(store, app_id, game, as_of, facts, key)
        version = version_info(key, game, own_ids[app_id], name, choice, app_id in pending) if tracking else None
        if status:
            forecasts.append(Forecast(app_id, name, status[0], status[1], version=version))
        else:
            evidence = game_evidence(game, as_of, "TW", facts_loader=lambda f=facts: f)
            out = predict_one(model, evidence, points)
            if isinstance(out, str):
                forecasts.append(Forecast(app_id, name, "model-error", out, version=version))
            else:
                regular = game.series["TW"].state_at(as_of).regular_cents
                forecasts.append(Forecast(
                    app_id, name, "ok", confidence=out.confidence, reasons=tuple(out.reasons),
                    evidence=dict(out.evidence), regular_price_cents=regular, points=tuple(points),
                    probabilities=tuple(tuple(row) for row in out.probabilities), version=version))
        if progress:
            progress(n, len(wanted))

    known = [s.known_until for g in games.values() for s in g.series.values() if s.known_until]
    return ForecastBatch(
        model=ModelInfo(model.name, model.version, dict(model.params)), as_of=as_of,
        data_cutoff=max(known) if known else None, generated_at=now or now_utc(), levels=LEVELS,
        confidence_levels=dict(model.confidence_levels()), games=tuple(forecasts), no_history=no_history)


def _aux_pending(store: PriceStore, targets: Mapping[int, GameData], choices: Mapping[int, OptionKey]) -> set[int]:
    """Chosen editions whose aux-region history was never fetched (plan D2: it comes with the next update)."""
    keys = {a: choices[a].key.external_id for a in targets if a in choices}
    if not keys:
        return set()
    known = store.history_known_until_all(REGIONS[1], keys=keys, apps=list(keys))
    return {a for a in keys if a not in known}


def no_history_curve(model: Model, as_of: datetime, points: Sequence[SalePoint]) -> NoHistoryCurve | None:
    """The prepared model's curve for a game without any own history (feature 003 research R2)."""
    empty = GameEvidence(app_id=0, as_of=as_of, target_region="TW", series={}, sale_history={"TW": (), "US": ()})
    out = predict_one(model, empty, points)
    if isinstance(out, str):
        return None
    return NoHistoryCurve(out.confidence, tuple(out.reasons), tuple(tuple(row) for row in out.probabilities))


def model_info(model: Model) -> Mapping:
    return {"name": model.name, "version": model.version, "params": dict(model.params)}
