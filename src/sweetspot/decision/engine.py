"""Decisions for a set of apps at one as_of: forecast → current prices → sweet-price rule → reasons.

A failure for one game becomes a `decision-error` for that game only (constitution III).
"""

from collections.abc import Iterable, Mapping
from typing import Any
from dataclasses import replace
from datetime import datetime, timedelta

from sweetspot import legacy
from sweetspot.config import Preferences
from sweetspot.decision.contract import Decision, DecisionBatch, na_decision, twd
from sweetspot.choices import TRACKED_STATES, ignored_warning
from sweetspot.decision import bundles as bundle_rule
from sweetspot.decision.editions import build_editions
from sweetspot.store.query import OPTION_HISTORY_SOURCE
from sweetspot.decision.prices import CurrentPrice, current_prices, non_seasonal_deeper
from sweetspot.decision.rule import (LOW_CONFIDENCE_MONTHS, RULE_NAME, RULE_VERSION,
                                     RULES, STALE_HOURS, RuleResult, WaitOption, backtested_costs, decide,
                                     lookup_backtest)
from sweetspot.forecast.contract import Forecast, version_to_dict
from sweetspot.decision.nonseasonal import attach as ns_attach
from sweetspot.decision.nonseasonal import batch_block as ns_batch_block
from sweetspot.forecast.engine import all_apps, load_games, run_forecast
from sweetspot.forecast.nonseasonal import build_ns_model, current_ns_model, ns_backtest_figures
from sweetspot.forecast.nonseasonal.engine import ns_forecast
from sweetspot.forecast.models.base import Model
from sweetspot.store.query import PriceStore
from sweetspot.timeutil import now_utc

REFRESH_NOTES = {1: "本次資料更新失敗，使用既有資料", 2: "本次資料更新有部分項目未完成",
                 3: "另一個更新正在執行，使用既有資料",
                 4: f"找到舊名稱的檔案，本次沒有更新資料：請先執行搬家（{legacy.MIGRATE_COMMAND}）"}   # feature 016
POINT_STATUS = {"announced": "官方公告", "estimated": "預估"}


def refresh_note(update_exit: int | None) -> str | None:
    """The report's line about this update; a code no command gives (a killed update's status) did not finish
    (014 T069). 5 (not set up) has none: report itself stops with 5 then."""
    if update_exit in (None, 0, 5):
        return None
    return REFRESH_NOTES.get(update_exit, REFRESH_NOTES[1])


def rule_info(rule: str | None = None) -> dict:
    version = rule or RULE_VERSION
    return {"name": RULE_NAME, "version": version, "constants": dict(RULES[version]["constants"])}


def lowest_label(rule: str) -> str:
    """What P_min is called: the whole curve (1.0.0) or 12 months (2.0.0; 004 research R5)."""
    return "12 個月內最低價" if RULES[rule]["p_min_months"] else "長期最低價"


def run_decisions(store: PriceStore, app_ids: Iterable[int], as_of: datetime, model: Model, preferences: Preferences,
                  *, now: datetime | None = None, official: bool = False,
                  update_exit: int | None = None, rule: str | None = None,
                  choices: Mapping[int, tuple[str, int]] | None = None,
                  calendar_notices: Iterable[str] = (),
                  reference_notice: Mapping[str, Any] | None = None) -> DecisionBatch:
    """`choices` (feature 009): the user's [purchase_options]; a chosen edition's history is read for its own game
    only, the population and every other game stay on the default versions (spec FR-010, FR-012).
    `calendar_notices` (feature 012, plan D1): sale-calendar alerts the user must act on, computed by the caller.
    `reference_notice` (feature 014 FR-014a): the reference dataset is below its target; presentation only, it changes
    no forecast or decision."""
    wanted = sorted(set(app_ids))
    games = load_games(store, sorted(set(all_apps(store)) | set(wanted)), as_of)     # once, for both forecasts
    chosen = {a: c for a, c in (choices or {}).items() if a in wanted}
    # 009 FR-008's tracking scope is the daily update's: the wishlist and games removed but still tracked (009 spec
    # Edge Case); a removed game is not in the report, but its choice is not "ignored" (014 T074)
    tracked = set(wanted) | (set(store.wishlist_apps(TRACKED_STATES)) if choices else set())
    warnings = tuple(ignored_warning(a) for a in sorted(set(choices or {}) - tracked))
    option_keys = store.option_keys(chosen, as_of, store.history_keys(sorted(chosen), as_of)) if chosen else {}
    user_keys = {a: k.key for a, k in option_keys.items() if k.source == "user" and not k.same_as_default}
    targets = (load_games(store, sorted(user_keys), as_of, keys=user_keys, sources=(OPTION_HISTORY_SOURCE,))
               if user_keys else {})
    forecast = run_forecast(store, wanted, as_of, model, now=now, games=games, targets=targets, choices=option_keys)
    history_regular = {g.app_id: g.regular_price_cents for g in forecast.games}
    prices = current_prices(store, wanted, as_of, history_regular, option_keys=option_keys)
    own = {**games, **targets}
    series = {a: own[a].series.get("TW") if a in own else None for a in wanted}
    windows = [(e.start, e.end) for e in store.sales(as_of, include_estimates=False)
               if e.kind == "seasonal" and e.start <= as_of]
    no_history = forecast.no_history.probabilities if forecast.no_history else None
    no_history_reasons = forecast.no_history.reasons if forecast.no_history else ()

    version = rule or RULE_VERSION
    model_info = {"name": model.name, "version": model.version, "params": dict(model.params)}
    wait_cost = preferences.wait_cost_twd if RULES[version]["kind"] == "wait-cost" else None
    figures = lookup_backtest(version, model_info, wait_cost)
    decisions = []
    for game in forecast.games:
        tracked = version_to_dict(game.version)
        if game.status != "ok":
            decisions.append(na_decision(game.app_id, game.name, game.status, game.status_reason, tracked))
            continue
        try:
            decisions.append(_decide_one(game, prices[game.app_id], series.get(game.app_id), windows, as_of,
                                         no_history, no_history_reasons, preferences, rule, model))
        except Exception as exc:  # noqa: BLE001 - isolated to this game
            decisions.append(na_decision(game.app_id, game.name, "decision-error", f"{type(exc).__name__}: {exc}",
                                         tracked))

    decisions, ns_block = _with_non_seasonal(decisions, store, wanted, as_of, games, targets)
    decisions = _with_editions(decisions, store, wanted, as_of, chosen)
    decisions, bundles = _with_bundles(decisions, store, wanted, as_of, forecast, set(user_keys))
    return DecisionBatch(
        official=official, as_of=as_of, generated_at=now or now_utc(), rule=rule_info(rule),
        preferences=preferences.for_rule(rule or RULE_VERSION),
        data_refresh={"update_exit": update_exit, "note": refresh_note(update_exit)},
        rule_backtest=figures, comparison=None, decisions=tuple(decisions), forecast=forecast,
        notes=tuple(model_notes(model, figures) + cost_notes(version, model_info, wait_cost, figures)),
        non_seasonal=ns_block, warnings=warnings, bundles=bundles, bundle_rule=BUNDLE_RULE,
        calendar_notices=tuple(calendar_notices),
        reference_notice=None if reference_notice is None else dict(reference_notice))


def _with_non_seasonal(decisions, store: PriceStore, wanted, as_of: datetime, games, targets=None):
    """Feature 007: add each game's non-seasonal part to its finished decision (the rule never sees it). Before the
    model is adopted the default parameters give the basis only (spec FR-016). A failure of the whole step turns
    into a per-game `model-error`, never a failed report (constitution III)."""
    model = current_ns_model()
    adopted = model is not None
    model = model or build_ns_model("non-seasonal")
    figures = ns_backtest_figures() if adopted else None
    try:
        outputs = ns_forecast(store, wanted, as_of, model, games=games, targets=targets).outputs
    except Exception as exc:  # noqa: BLE001 - the seasonal decisions stand on their own
        outputs = {a: f"{type(exc).__name__}: {exc}" for a in wanted}
    out = []
    for d in decisions:
        g = (targets or {}).get(d.app_id) or games.get(d.app_id)
        tw = g.series.get("TW") if g else None
        out.append(ns_attach(d, outputs.get(d.app_id), adopted=adopted, as_of=as_of,
                             tw_start=tw.first_start if tw else None, figures=figures))
    return out, ns_batch_block(model, adopted=adopted, figures=figures)


BUNDLE_RULE = {"name": bundle_rule.RULE[0], "version": bundle_rule.RULE[1]}


def _with_bundles(decisions, store: PriceStore, wanted, as_of: datetime, forecast, specified):
    """Feature 010: bundles holding several wishlist games (contracts/outputs-bundles.md). The rule only reads the
    finished decisions. Without purchase-option records, or when the whole step fails, `bundles` is None
    (unknown) and every decision stays as it was (constitution III)."""
    try:
        records = store.purchase_options(wanted, as_of)
        if not records:
            return decisions, None
        inside = {c["app_id"] for rows in records.values() for r in rows if r.kind == "bundle"
                  for c in r.contents or []} - set(wanted)
        block = bundle_rule.build_bundles(records, decisions, {g.app_id: g for g in forecast.games}, as_of=as_of,
                                          names=store.app_names(sorted(inside)), specified=specified)
    except Exception:  # noqa: BLE001 - the decisions stand on their own
        return decisions, None
    return ([replace(d, bundles=tuple(block.per_app.get(d.app_id, ()))) for d in decisions],
            tuple(block.bundles))


def _with_editions(decisions, store: PriceStore, wanted, as_of: datetime, chosen=None):
    """Feature 009: each game's other editions (contracts/outputs-options.md). Never fails a report: a problem
    leaves the list unknown (None) for every game."""
    try:
        editions = build_editions(store, wanted, as_of, store.history_keys(wanted, as_of), chosen)
    except Exception:  # noqa: BLE001 - the decisions stand on their own (constitution III)
        return decisions
    return [replace(d, editions=None if editions.get(d.app_id) is None else tuple(editions[d.app_id]))
            for d in decisions]


def cost_notes(rule: str, model_info, wait_cost: int | None, figures) -> list[str]:
    """005 research R8 (spec FR-020): figures belong to one waiting cost; never quote them for another."""
    if wait_cost is None or figures is not None:
        return []
    costs = backtested_costs(rule, model_info)
    if not costs:
        return []
    which = "、".join(f"NT${c}" for c in costs)
    return [f"規則回測是以等待成本 {which} 算的，目前設定為 NT${wait_cost}，沒有對應的回測，所以不引用到價率"]


def model_notes(model: Model, figures) -> list[str]:
    """The model's own caveat (004 research R9), with its number from this combination's rule backtest. A caveat
    that needs a number is left out when there is no backtest: the report never quotes an unverified figure."""
    caveat = model.deeper_caveat
    if "{" not in caveat:
        return [caveat]
    if figures is None or figures.get("now_deeper_within_12m") is None:
        return []
    return [caveat.format(now_deeper_within_12m=f"{figures['now_deeper_within_12m']:.0%}")]


def _decide_one(game: Forecast, price: CurrentPrice, series, windows, as_of: datetime, no_history, no_history_reasons,
                prefs: Preferences, rule: str | None = None, model: Model | None = None) -> Decision:
    regular = price.regular_cents if price.regular_cents is not None else game.regular_price_cents
    max_cut = game.evidence.get("max_cut")
    stopped = game.version is not None and game.version.tracking == "stopped"
    r = decide(probabilities=game.probabilities, points=game.points, as_of=as_of, confidence=game.confidence,
               evidence_max_cut=max_cut, regular_cents=regular, current_price_cents=price.price_cents,
               regular_mismatch=price.regular_mismatch, no_history=no_history, preferences=prefs, rule=rule,
               history_stopped=stopped)
    tags = list(r.tags)
    if model is not None and model.predicts_deeper:
        tags = [t for t in tags if t != "deeper-possible"]        # the model does forecast deeper cuts
    if price.price_cents is not None and price.stale:
        tags.append("stale-price")
    extra = non_seasonal_deeper(series, windows, max_cut, as_of) if series else None
    if extra is not None:
        tags.append("non-seasonal-deeper")
    reasons = _reasons(game, price, r, regular, extra, no_history_reasons, prefs, tags,
                       model.deeper_caveat if model is not None else None)
    point = game.points[r.sweet_index - 1]
    deadline = game.points[r.deadline_index - 1] if r.deadline_index else None
    return Decision(
        app_id=game.app_id, name=game.name, group=r.group, status="ok", status_reason=None,
        confidence=r.confidence, basis=r.basis, horizon_points=r.horizon_points, regular_cents=regular,
        current=price, p_min_pct=r.p_min_pct, p_min_cents=r.p_min_cents, gap_pp=r.gap_pp,
        tolerance_cents=r.tolerance_cents, tolerance_bound=r.tolerance_bound, target_cents=r.target_cents,
        sweet_pct=r.sweet_pct, sweet_cents=r.sweet_cents, sweet_point=point, sweet_probability=r.sweet_probability,
        ladder=r.ladder, tags=tuple(tags), reasons=tuple(reasons), wait_options=r.wait_options,
        deadline_point=deadline, expected=r.expected, version=version_to_dict(game.version))


def _money(cents: int) -> str:
    """Whole NT$ with thousands separators, as in the report's waiting table (rule 3.0.0 reasons only)."""
    return f"NT${twd(cents):,}" if cents >= 0 else f"-NT${twd(-cents):,}"


def _saving_text(cents: int) -> str:
    return f"期望多省 {_money(cents)}" if cents >= 0 else f"期望反而多付 {_money(-cents)}"


def _option_text(o: WaitOption) -> str:
    return (f"最晚等到 {o.deadline_label}、目標 -{o.target_pct}%：{_saving_text(o.expected_saving_cents)}、"
            f"多等 {o.expected_wait_months:.1f} 個月，淨效益 {_money(o.net_cents)}")


def _wait_cost_reasons(r: RuleResult, price: CurrentPrice, prefs: Preferences) -> list[str]:
    """Rule 3.0.0 (005 research R11): cost, the chosen option, at least one alternative that lost."""
    c = prefs.wait_cost_twd
    out = [f"等待成本 NT${c}／月（使用者偏好）：每多等一個月要多省 NT${c} 才值得"]
    rows = [o for o in r.wait_options if o.deadline_index and o.net_cents is not None]
    e = r.expected
    if e.deadline_index == 0:
        best = max(rows, key=lambda o: (o.net_cents, -o.deadline_index), default=None)
        if best is None:
            out.append("沒有比現價更低的折扣等級可以等；現在買")
        else:
            out.append(f"等下去最好的選項是{_option_text(best)}，不划算；現在買")
        return out
    if e.likely_probability is not None and e.likely_probability >= 0.5:
        when = f"最可能在 {e.likely_label}到價（{e.likely_probability:.0%}）"
        if e.likely_index != e.deadline_index:
            when += f"，最晚等到 {e.deadline_label}（到期前 {e.reach_probability:.0%}）"
    else:
        when = f"最晚等到 {e.deadline_label}，到期前達到的機率 {e.reach_probability:.0%}（沒有任何一場達到 50%）"
    out.append(f"建議：目標 -{e.target_pct}%（{_money(e.target_cents)}）以下，{when}")
    against = "現價" if price.price_cents is not None else "原價"
    saving = (f"多省 {_money(e.expected_saving_cents)}" if e.expected_saving_cents >= 0
              else f"反而多付 {_money(-e.expected_saving_cents)}")
    out.append(f"期望比{against}{saving}、期望多等 {e.expected_wait_months:.1f} 個月，"
               f"等待成本 {_money(e.wait_cost_cents)}，淨效益 {_money(e.net_cents)}；到期沒達到時以原價計算（規則常數）")
    alternatives = []
    if price.price_cents is not None:
        alternatives.append(f"現在買（{_money(price.price_cents)}），淨效益 NT$0")
    seen = {e.deadline_index}
    for o in (next((o for o in rows if o.deadline_index == 1), None),
              max(rows, key=lambda o: (o.expected_saving_cents, -o.deadline_index), default=None)):
        if o is not None and o.deadline_index not in seen:
            seen.add(o.deadline_index)
            alternatives.append(f"{_option_text(o)}，較低")
    out.extend(f"對照：{text}" for text in alternatives)
    return out


UNCONFIRMED = {
    "ambiguous": "價格和現價相同的購買選項不只一個，或一個都沒有",
    "not-in-itad": "ITAD 沒有追蹤這個購買選項",
    "no-option": "Steam 沒有可購買的選項",
}


def _taipei_date(moment) -> str:
    return (moment + timedelta(hours=8)).strftime("%Y-%m-%d")


def version_reasons(version) -> list[str]:
    """Feature 006 (spec FR-010, FR-011, FR-014): which product's history is used and why. Feature 009: the user's
    chosen edition, or why the choice could not be used (spec FR-016)."""
    if version is None:
        return []
    if version.basis == "user":
        start = _taipei_date(version.history_start) if version.history_start else "未知"
        out = [f"價格歷史來自使用者指定的購買選項 {version.package_name}（ITAD 從 {start} 開始追蹤）"]
        if version.aux_pending:
            out.append("這個版本的美國區歷史下一次更新才會取得，這次只用台灣區的紀錄")
        if version.tracking == "stopped":
            last = _taipei_date(version.last_confirmed) if version.last_confirmed else "未知"
            out.append(f"價格歷史停止更新：ITAD 在 {last} 之後就沒有這個商品在 Steam 的價格，之後的特賣視為未知；決策改為低信心")
        return out
    lead = []
    if version.source == "user-fallback" and version.fallback:
        lead = [version.fallback["text"]]
    elif version.source == "user" and version.option:
        lead = [f"使用者指定的購買選項 {version.option['name'] or version.option['kind'] + '/' + str(version.option['id'])}"
                "就是 Steam 預設版本的商品，價格歷史照常"]
    return lead + _default_reasons(version)


def _default_reasons(version) -> list[str]:
    if version.basis == "version":
        out = []
        if version.change is not None and version.itad_id != version.own_itad_id:
            start = _taipei_date(version.history_start) if version.history_start else "未知"
            out.append(f"價格歷史來自 Steam 目前預設的購買選項 {version.package_name}（ITAD 從 {start} 開始追蹤）；"
                       f"{_taipei_date(version.change.detected_at)} 偵測到 Steam 換了版本，舊版本的歷史不使用")
        if version.tracking == "stopped":
            last = _taipei_date(version.last_confirmed) if version.last_confirmed else "未知"
            out.append(f"價格歷史停止更新：ITAD 在 {last} 之後就沒有這個商品在 Steam 的價格，之後的特賣視為未知；決策改為低信心")
        return out
    if version.basis != "own":
        return []
    if version.basis_reason == "no-record":
        return ["這個時點沒有版本紀錄，沿用這款遊戲本身的價格歷史"]
    text = UNCONFIRMED.get(version.basis_reason, version.basis_reason or "")
    return [f"無法確認 Steam 目前賣的版本（{text}），沿用這款遊戲本身的價格歷史"]


def _reasons(game: Forecast, price: CurrentPrice, r: RuleResult, regular: int, extra, no_history_reasons,
             prefs: Preferences, tags=None, caveat: str | None = None) -> list[str]:
    tags = r.tags if tags is None else tags
    out = list(game.reasons) + version_reasons(game.version)
    if r.basis == "no-history":
        out.append("過去季節特賣沒有打折（本身的曲線沒有任何折扣達到 50%），改用沒有本身歷史時的預測，"
                   f"只看未來 {LOW_CONFIDENCE_MONTHS} 個月")
        out.extend(f"沒有本身歷史時的預測依據：{text}" for text in no_history_reasons)
    elif r.confidence == "low" and game.confidence == "low":
        out.append(f"低信心：甜蜜價只看未來 {LOW_CONFIDENCE_MONTHS} 個月內的季節特賣")
    if price.regular_mismatch:
        out.append(f"原價與價格歷史不一致（歷史 NT${twd(price.history_regular_cents)}，目前 NT${twd(regular)}）："
                   "可能漲價，或 Steam 改賣其他版本；以目前原價換算，決策改為低信心")
    last = game.points[r.horizon_points - 1]
    scope = (f"未來 {LOW_CONFIDENCE_MONTHS} 個月（到 {last.label}）" if r.horizon_points < len(game.points)
             else f"曲線範圍（到 {last.label}）")
    if r.wait_options:
        stated = any("只看未來" in line for line in out)
        return out + _wait_cost_tail(game, price, r, extra, prefs, tags, caveat, scope, stated)
    lowest = lowest_label(r.rule)
    spaced = f" {lowest}" if lowest[0].isdigit() else lowest      # a space between Chinese and a number
    out.append(f"{lowest} -{r.p_min_pct}%（NT${twd(r.p_min_cents)}）：{scope}內累積機率 ≥ 50% 的最深折扣")
    shallow = r.gap_pp == prefs.gap_pp_shallow and r.p_min_pct < prefs.gap_boundary_pct
    tier = (f"P_min 淺於 -{prefs.gap_boundary_pct}% 用 {r.gap_pp} 個百分點" if shallow
            else f"P_min 達到 -{prefs.gap_boundary_pct}% 用 {r.gap_pp} 個百分點")
    bound = {"min": f"，低於下限 NT${prefs.tolerance_min_twd}，改用下限",
             "max": f"，超過上限 NT${prefs.tolerance_max_twd}，改用上限"}.get(r.tolerance_bound, "")
    out.append(f"容許差距 NT${twd(r.tolerance_cents)}：{tier}（使用者偏好）{bound}")
    out.append(f"甜蜜價 NT${twd(r.sweet_cents)}（-{r.sweet_pct}%）以下：不超過{spaced}加容許差距"
               f"（NT${twd(r.target_cents)}）的最淺折扣")
    point = game.points[r.sweet_index - 1]
    out.append(f"甜蜜時點 {point.label}（{POINT_STATUS.get(point.status, point.status)}）：≥ -{r.sweet_pct}% 的"
               f"累積機率第一次達到 50%（{r.sweet_probability:.0%}）")
    if price.price_cents is None:
        out.append("現價未知，無法判斷是否現在買")
    else:
        where = "已經不高於甜蜜價，現在買" if r.group == "now" else "還沒到甜蜜價"
        discount = f"-{price.cut_pct}%" if price.cut_pct else "原價"
        out.append(f"現價 NT${twd(price.price_cents)}（{discount}），{where}")
        if "below-history" in r.tags:
            out.append(f"現價低於{spaced} NT${twd(r.p_min_cents)}")
        if price.stale:
            when = price.confirmed_at.strftime("%Y-%m-%d %H:%M UTC") if price.confirmed_at else "未知"
            out.append(f"現價的最後確認時間 {when}，超過 {STALE_HOURS} 小時，現價可能已變")
    if "deeper-possible" in tags and caveat and "{" not in caveat:
        out.append(caveat)
    if extra is not None:
        out.append(f"季節特賣以外出現過 -{extra.cut}%（{extra.start.strftime('%Y-%m-%d')}），模型不預測這類折扣")
    return out


def _wait_cost_tail(game: Forecast, price: CurrentPrice, r: RuleResult, extra, prefs: Preferences, tags, caveat,
                    scope: str, stated: bool) -> list[str]:
    out = [] if stated else [f"只看{scope}內的季節特賣"]      # the 003 low-confidence lines already say it
    out += _wait_cost_reasons(r, price, prefs)
    out.append(f"12 個月內最低價（參考）-{r.p_min_pct}%（{_money(r.p_min_cents)}）：{scope}內累積機率 ≥ 50% 的最深折扣")
    if price.price_cents is None:
        out.append("現價未知，以原價估計，無法判斷是否現在買")
    else:
        discount = f"-{price.cut_pct}%" if price.cut_pct else "原價"
        out.append(f"現價 {_money(price.price_cents)}（{discount}）")
        if "below-history" in r.tags:
            out.append(f"現價低於 12 個月內最低價 {_money(r.p_min_cents)}")
        if price.stale:
            when = price.confirmed_at.strftime("%Y-%m-%d %H:%M UTC") if price.confirmed_at else "未知"
            out.append(f"現價的最後確認時間 {when}，超過 {STALE_HOURS} 小時，現價可能已變")
    if "deeper-possible" in tags and caveat and "{" not in caveat:
        out.append(caveat)
    if extra is not None:
        out.append(f"季節特賣以外出現過 -{extra.cut}%（{extra.start.strftime('%Y-%m-%d')}），模型不預測這類折扣")
    return out
