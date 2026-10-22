"""Scoring one seasonal sale against an official record (feature 013 research R4–R6, FR-007–FR-012).

Every per-game result is a plain dict in the shape of steamsage.review/1 (data-model §2). Games that cannot be
compared (no-actual, not-scored) never enter a denominator. Intervals resample games (one value per game) with a
seed derived from the record's file name, so the same data always gives the same bytes (FR-018).
"""

import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sweetspot.calendar import SaleEvent, label
from sweetspot.forecast.backtest.compare import bootstrap_interval
from sweetspot.forecast.contract import LEVELS
from sweetspot.forecast.nonseasonal.events import arrivals, arrived_levels
from sweetspot.review.actual import SaleActual, Tracked
from sweetspot.timeutil import parse_iso

SEASONAL_SOURCE = "docs/model/model-definition.md#seasonal-record-v110現行 回測結果摘要"
SEASONAL_BACKTEST = 0.0604        # 只計已結束的 Brier（每款同權重），台灣區：same conditions as a finished sale
SEASONAL_BACKTEST_ALL = 0.0579    # the 002-framework Brier over all units, listed only
DEFINITIONS = ("sale_max", "crossing")
GROUPS = ("now", "soon", "wait", "low")


def r4(x: float | None) -> float | None:
    return None if x is None else round(x, 4)


def seed_for(record_name: str) -> int:
    return int(hashlib.sha256(record_name.encode("utf-8")).hexdigest()[:8], 16)


def stat(values: list[float], seed: int, backtest: float | None = None, source: str | None = None) -> dict[str, Any]:
    """Mean over games with a resampled interval; `differs` only when the backtest figure lies outside it (FR-008)."""
    out: dict[str, Any] = {"value": None, "n": len(values), "interval": None}
    if values:
        lo, hi = bootstrap_interval(values, seed)
        out.update(value=r4(sum(values) / len(values)), interval=[r4(lo), r4(hi)])
    if backtest is not None:
        out.update(backtest=backtest, backtest_source=source,
                   differs=None if not values else not (out["interval"][0] <= backtest <= out["interval"][1]))
    return out


# --- one game ---------------------------------------------------------------------------------------------

def _curve_row(game: dict | None, sale: SaleEvent) -> tuple[str | None, list[float] | None, str | None]:
    """(point label, the 19 probabilities for this sale, reason when there are none)."""
    if not game or game.get("status") != "ok" or not game.get("curve"):
        return None, None, "紀錄中沒有這款的預測曲線"
    curve = game["curve"]
    want = label(sale)
    for i, point in enumerate(curve.get("points") or []):
        same = ((point.get("season"), point.get("year")) == (sale.season, sale.year) if point.get("season")
                else point.get("label") == want)
        if same:
            return point.get("label"), list(curve["probabilities"][i]), None
    return None, None, f"預測曲線沒有這一場（{want}）"


def _brier(p: list[float], outcomes: list[int]) -> float:
    return sum((x - o) ** 2 for x, o in zip(p, outcomes)) / len(p)


def _series_block(tr: Tracked | None) -> dict | None:
    if tr is None:
        return None
    return {"itad_id": tr.itad_id, "basis": tr.basis, "option": tr.option,
            "known_until": None if tr.known_until is None else tr.known_until.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "version_changed": tr.version_changed}


def _actual_block(a: SaleActual) -> dict:
    return {"max_cut": a.max_cut, "history_max_cut": a.history_max_cut, "min_cents": a.min_cents,
            "running_cut_at_as_of": a.running_cut_at_as_of,
            "daily_max_cut": a.daily_max_cut, "daily_min_cents": a.daily_min_cents, "corrected": a.corrected,
            "noted": a.noted, "regular_changed": a.regular_changed}


def early_switch(app_id: int, during, missing_days) -> dict:
    """FR-010a: the first record during the sale that put the game in 現在買; missed only when no record is missing."""
    last = None
    for path, record in during:
        d = next((x for x in record.get("decisions") or [] if x.get("app_id") == app_id), None)
        if d is None:
            continue
        if d.get("group") == "now":
            return {"state": "first_now", "as_of": record["as_of"], "file": Path(path).name}
        last = d.get("group")
    if missing_days:
        return {"state": "unknown", "missing_days": list(missing_days)}
    return {"state": "missed", "last_group": last}


def _after(point: dict | None, sale: SaleEvent) -> bool:
    if not point or not point.get("start"):
        return False
    return parse_iso(point["start"]) > sale.start


def review_game(decision: dict, game: dict | None, tracked: Tracked | None, actual: SaleActual | None,
                sale: SaleEvent, during=(), missing_days=()) -> dict[str, Any]:
    app = decision["app_id"]
    out: dict[str, Any] = {"app_id": app, "name": decision.get("name"), "status": "reviewed", "reason": None,
                           "series": _series_block(tracked), "actual": None, "seasonal": None, "seasonal_reason": None,
                           "decision": None, "timing": "n/a", "switch": None, "now_vs_sale": None,
                           "non_seasonal": None, "recomputed": None}
    if decision.get("status") != "ok":
        out.update(status="not-scored", reason=decision.get("status_reason") or decision.get("status"))
        return out
    point, probs, why = _curve_row(game, sale)
    group = decision.get("group")
    sweet = decision.get("sweet_cents")
    current = (decision.get("current") or {}).get("price_cents")
    out["decision"] = {"group": group, "confidence": decision.get("confidence"), "sweet_cents": sweet,
                       "sweet_pct": decision.get("sweet_pct"),
                       "sweet_point": (decision.get("sweet_point") or {}).get("label"),
                       "sweet_probability": decision.get("sweet_probability"), "current_cents": current,
                       "hit": None, "gap_cents": None}
    if tracked is None or tracked.reason is not None or actual is None:
        out.update(status="no-actual", reason=(tracked.reason if tracked else None) or "沒有實際價格")
        return out
    out["actual"] = _actual_block(actual)
    if probs is None:
        out["seasonal_reason"] = why
    else:
        sm = [int(actual.sale_max(d)) for d in LEVELS]
        cr = [int(actual.crossing(d)) for d in LEVELS]
        out["seasonal"] = {"point": point, "confidence": (game or {}).get("confidence"), "probabilities": probs,
                           "sale_max": sm, "crossing": cr,
                           "brier": {"sale_max": r4(_brier(probs, sm)), "crossing": r4(_brier(probs, cr))}}
    low = actual.min_cents
    if sweet is not None and low is not None:
        out["decision"].update(hit=low <= sweet, gap_cents=low - sweet)
    if group == "now":
        if current is not None and low is not None:
            kind = "lower" if low < current else "higher" if low > current else "same"
            out["now_vs_sale"] = {"kind": kind, "diff_cents": low - current}
    elif group in ("soon", "wait", "low"):
        sp = decision.get("sweet_point")
        if sp and sp.get("label") == label(sale) and not _after(sp, sale):
            out["timing"] = "on-time"
        elif _after(sp, sale):
            out["timing"] = "early" if out["decision"]["hit"] else "not-yet"
            if out["timing"] == "early":
                out["switch"] = early_switch(app, during, missing_days)
    return out


# --- summaries --------------------------------------------------------------------------------------------

def _scored(games: list[dict]) -> list[dict]:
    return [g for g in games if g["status"] == "reviewed" and g["seasonal"]]


def _calibration(games: list[dict], key: str) -> list[dict]:
    bins: dict[int, list] = {}
    for g in games:
        for p, o in zip(g["seasonal"]["probabilities"], g["seasonal"][key]):
            b = bins.setdefault(min(int(p * 10), 9), [0, 0.0, 0, set()])
            b[0] += 1
            b[1] += p
            b[2] += o
            b[3].add(g["app_id"])
    return [{"bin": f"{k / 10:.1f}", "units": v[0], "games": len(v[3]), "predicted": r4(v[1] / v[0]),
             "actual": r4(v[2] / v[0])} for k, v in sorted(bins.items())]


def seasonal_summary(games: list[dict], seed: int) -> dict[str, Any]:
    scored = _scored(games)
    brier = {k: stat([g["seasonal"]["brier"][k] for g in scored], seed) for k in DEFINITIONS}
    brier["crossing"] = stat([g["seasonal"]["brier"]["crossing"] for g in scored], seed, SEASONAL_BACKTEST,
                             SEASONAL_SOURCE)
    by_conf: dict[str, dict] = {}
    for conf in sorted({g["seasonal"]["confidence"] or "unknown" for g in scored}):
        part = [g for g in scored if (g["seasonal"]["confidence"] or "unknown") == conf]
        by_conf[conf] = {"games": len(part), **{k: r4(sum(g["seasonal"]["brier"][k] for g in part) / len(part))
                                                for k in DEFINITIONS}}
    return {"brier": brier, "backtest_all_units": SEASONAL_BACKTEST_ALL, "units": len(scored) * len(LEVELS),
            "differs_games": [g["app_id"] for g in scored if g["seasonal"]["sale_max"] != g["seasonal"]["crossing"]],
            "by_confidence": by_conf, "calibration": {k: _calibration(scored, k) for k in DEFINITIONS}}


def decision_summary(games: list[dict], record: dict, seed: int) -> dict[str, Any]:
    reviewed = [g for g in games if g["status"] == "reviewed" and g["decision"]]
    rb = record.get("rule_backtest") or {}
    rates = rb.get("hit_rate") or {}
    source = rb.get("source")
    on_time = {}
    for group in ("soon", "wait", "low"):
        part = [g for g in reviewed if g["decision"]["group"] == group and g["timing"] == "on-time"
                and g["decision"]["hit"] is not None]
        if part:
            hits = [float(g["decision"]["hit"]) for g in part]
            on_time[group] = {**stat(hits, seed, rates.get(group), source), "hits": int(sum(hits))}
    misses = [{"app_id": g["app_id"], "name": g["name"], "group": g["decision"]["group"],
               "gap_cents": g["decision"]["gap_cents"]}
              for g in reviewed if g["timing"] == "on-time" and g["decision"]["hit"] is False]
    early = [g for g in reviewed if g["timing"] == "early"]
    states = [g["switch"]["state"] for g in early]
    now = [g for g in reviewed if g["now_vs_sale"]]
    return {
        "counts": {k: n for k in GROUPS if (n := sum(g["decision"]["group"] == k for g in reviewed))},
        "on_time": on_time, "misses": misses,
        "early": {"n": len(early), "first_now": states.count("first_now"), "missed": states.count("missed"),
                  "unknown": states.count("unknown"),
                  "games": [{"app_id": g["app_id"], "name": g["name"], "group": g["decision"]["group"],
                             "sweet_point": g["decision"]["sweet_point"], "switch": g["switch"]} for g in early]},
        "not_yet": sum(g["timing"] == "not-yet" for g in reviewed),
        "now": {"n": len(now), **{k: sum(g["now_vs_sale"]["kind"] == k for g in now) for k in ("lower", "same", "higher")},
                "backtest_now_deeper_within_12m": rb.get("now_deeper_within_12m")},
    }


def bundle_review(bundle: dict, steps, games: dict[int, dict], sale: SaleEvent) -> dict[str, Any]:
    """FR-011: a record's bundle against the bundle's own daily rows during the sale and its contents' outcomes.
    Only a pure bundle with advice to buy (next sale or now) is scored; the rest are listed (FR-012: no rates)."""
    advice = bundle.get("advice") if (bundle.get("advice") or {}).get("status") == "ok" else None
    scored = bundle.get("grade") == "pure" and advice is not None and advice.get("kind") in ("next-sale", "now")
    priced = [r for r in steps if r.final_cents is not None]
    actual, reason = None, None
    if priced:
        discounts = sorted({r.bundle_discount_pct for r in priced if r.bundle_discount_pct is not None})
        actual = {"min_cents": min(r.final_cents for r in priced), "discounts": discounts,
                  "discount_same": discounts == [bundle.get("discount_pct")], "days": len(priced)}
    else:
        reason = "特賣期間沒有這個組合包的每日價格紀錄"
    needed = {lv["app_id"]: lv["pct"] for lv in (advice or {}).get("levels") or []}
    contents = []
    for c in bundle.get("contents") or []:
        g = games.get(c["app_id"])
        cut = (g.get("actual") or {}).get("max_cut") if g else None
        want = needed.get(c["app_id"])
        contents.append({"app_id": c["app_id"], "name": c.get("name"), "needed_pct": want, "max_cut": cut,
                         "hit": None if want is None or cut is None else cut >= want})
    joint = None
    if advice and advice.get("kind") == "next-sale" and contents:
        joint = None if any(x["hit"] is None for x in contents) else all(x["hit"] for x in contents)
    gap = None
    if actual and advice:
        base = advice.get("estimate_cents") if advice.get("kind") == "next-sale" else bundle.get("price_cents")
        gap = None if base is None else actual["min_cents"] - base
    spent, pending = 0, []
    for c in bundle.get("contents") or []:
        g = games.get(c["app_id"])
        dec = (g or {}).get("decision") or {}
        if dec.get("group") == "now" and dec.get("current_cents") is not None:
            spent += dec["current_cents"]
        elif g and g.get("timing") == "on-time" and (g.get("actual") or {}).get("min_cents") is not None:
            spent += g["actual"]["min_cents"]
        else:
            pending.append(c["app_id"])
    return {"id": bundle.get("id"), "name": bundle.get("name"), "grade": bundle.get("grade"), "scored": scored,
            "advice": None if advice is None else {
                "kind": advice.get("kind"), "estimate_cents": advice.get("estimate_cents"),
                "joint_probability": advice.get("joint_probability"), "sale": (advice.get("sale") or {}).get("label"),
                "discount_pct": bundle.get("discount_pct"), "price_cents": bundle.get("price_cents")},
            "actual": actual, "actual_reason": reason, "contents": contents, "joint_hit": joint,
            "estimate_gap_cents": gap, "separate_plan": {"cents": spent, "complete": not pending, "pending": pending}}


def ns_review(decision: dict, series, windows, as_of: datetime, today: datetime,
              horizons) -> dict[str, Any] | None:
    """US4 (FR-013, FR-014): the record's non-seasonal probabilities per period. A period is scored only once it has
    ended and the history is known through its end, judged as the non-seasonal backtest does (arrivals outside
    seasonal windows, whole calendar); otherwise it is pending with its due date."""
    ns = decision.get("non_seasonal") or {}
    if ns.get("status") != "ok" or not ns.get("probabilities"):
        return None
    arrived_all = arrivals(series, windows) if series is not None and series.states else ()
    units = []
    for i, h in enumerate(horizons):
        due = as_of + timedelta(days=h)
        unit: dict[str, Any] = {"h": h, "due": due.strftime("%Y-%m-%dT%H:%M:%SZ"), "state": "pending", "reason": None,
                                "probabilities": list(ns["probabilities"][i]), "arrived": None}
        if due > today:
            unit["reason"] = "未到期"
        elif series is None or not series.states:
            unit.update(state="no-actual", reason="沒有價格序列")
        elif series.known_until is None or series.known_until < due:
            unit["reason"] = "價格歷史還沒到到期日"
        else:
            got = arrived_levels(arrived_all, as_of, due, LEVELS)
            unit.update(state="scored", arrived=[int(d in got) for d in LEVELS],
                        brier=r4(_brier(unit["probabilities"], [int(d in got) for d in LEVELS])))
        units.append(unit)
    earlier = None
    if ns.get("earlier"):
        e = ns["earlier"]
        unit = next((u for u in units if u["h"] == e.get("horizon_days")), None)
        hit = None
        if unit and unit["state"] == "scored" and decision.get("sweet_pct") is not None:
            hit = bool(unit["arrived"][LEVELS.index(decision["sweet_pct"])])
        earlier = {"horizon_days": e.get("horizon_days"), "probability": e.get("probability"),
                   "sale_label": e.get("sale_label"), "sweet_pct": decision.get("sweet_pct"),
                   "state": unit["state"] if unit else "pending", "hit": hit, "backtest": e.get("hit_rate")}
    return {"confidence": ns.get("confidence"), "units": units, "earlier": earlier}


def ns_summary(games: list[dict], record: dict, seed: int) -> dict[str, Any]:
    back = (record.get("non_seasonal") or {}).get("backtest") or {}
    by_h = back.get("brier_by_horizon") or {}
    horizons: dict[str, Any] = {}
    pending_dues = []
    rows = [g for g in games if g.get("non_seasonal")]
    hs = sorted({u["h"] for g in rows for u in g["non_seasonal"]["units"]})
    for h in hs:
        units = [(g, u) for g in rows for u in g["non_seasonal"]["units"] if u["h"] == h]
        scored = [(g, u) for g, u in units if u["state"] == "scored"]
        pending = [u for _, u in units if u["state"] == "pending"]
        pending_dues += [u["due"] for u in pending if u["reason"] == "未到期"]   # not those waiting for history
        horizons[str(h)] = {"scored_units": len(scored) * len(LEVELS), "games": len(scored),
                            "pending_games": len(pending),
                            "waiting_history_games": sum(u["reason"] == "價格歷史還沒到到期日" for u in pending),
                            "no_actual_games": sum(u["state"] == "no-actual" for _, u in units),
                            "brier": stat([u["brier"] for _, u in scored], seed, by_h.get(str(h)), back.get("source")),
                            "first_due": min((u["due"] for u in pending), default=None)}
    earlier = [{"app_id": g["app_id"], "name": g.get("name"), **g["non_seasonal"]["earlier"]}
               for g in rows if g["non_seasonal"]["earlier"]]
    return {"horizons": horizons, "next_due": min(pending_dues, default=None), "earlier": earlier}


DRIFT = 0.0001      # a probability that moved less than this is the same (records keep 6 decimals)


def _why_different(record_d: dict, current_d: dict) -> str:
    if (record_d.get("version") or {}).get("itad_id") != (current_d.get("version") or {}).get("itad_id"):
        return "追蹤的版本不同"
    if (record_d.get("current") or {}).get("price_cents") != (current_d.get("current") or {}).get("price_cents"):
        return "紀錄當時的現價不同"
    return "分析時點以前的資料在紀錄之後有補上或修正（這款或參考資料集）"


def recompute_summary(games: list[dict], record: dict, recomputed: dict, sale: SaleEvent, seed: int) -> dict:
    """US5 (FR-015, FR-016): the record, the recomputed current model and the baseline on the same games and
    levels (the primary definition), side by side; no verdict."""
    cur_games = {g["app_id"]: g for g in (recomputed["current"].get("forecast") or {}).get("games") or []}
    base_games = {g["app_id"]: g for g in recomputed["baseline"].get("games") or []}
    cur_dec = {d["app_id"]: d for d in recomputed["current"].get("decisions") or []}
    rec_dec = {d["app_id"]: d for d in record.get("decisions") or []}
    scores = {"record": [], "current": [], "baseline": []}
    different, drift = [], []
    for g in games:
        app = g["app_id"]
        if g["status"] == "not-scored" or app not in cur_dec:
            continue
        pc = _curve_row(cur_games.get(app), sale)[1]
        mine = g["seasonal"]["probabilities"] if g["seasonal"] else None
        diff = None if mine is None or pc is None else r4(max(abs(a - b) for a, b in zip(mine, pc)))
        g["recomputed"] = {"brier": None, "max_probability_diff": diff}
        if diff is not None:
            drift.append(diff)
        if g["status"] == "reviewed" and mine is not None:
            pb = _curve_row(base_games.get(app), sale)[1]
            if pc is not None and pb is not None:
                o = g["seasonal"]["sale_max"]
                b = {"record": g["seasonal"]["brier"]["sale_max"], "current": r4(_brier(pc, o)),
                     "baseline": r4(_brier(pb, o))}
                g["recomputed"]["brier"] = b
                for k, v in b.items():
                    scores[k].append(v)
        rd, cd = rec_dec.get(app) or {}, cur_dec[app]
        if (rd.get("group"), rd.get("sweet_cents")) != (cd.get("group"), cd.get("sweet_cents")):
            different.append({"app_id": app, "name": g["name"], "record_group": rd.get("group"),
                              "current_group": cd.get("group"), "record_sweet_cents": rd.get("sweet_cents"),
                              "current_sweet_cents": cd.get("sweet_cents"), "max_probability_diff": diff,
                              "reason": _why_different(rd, cd)})
    moved = [x for x in drift if x >= DRIFT]
    return {**{k: stat(v, seed) for k, v in scores.items()}, "different": different,
            "probability_drift": {"games": len(drift), "moved": len(moved), "max": max(drift, default=None)},
            "note": recomputed.get("note")}


def mismatches(games: list[dict]) -> dict[str, list]:
    def row(g):
        a = g["actual"]
        return {"app_id": g["app_id"], "name": g["name"], "history_max_cut": a["history_max_cut"],
                "daily_max_cut": a["daily_max_cut"]}
    done = [g for g in games if g["actual"]]
    return {"corrected": [row(g) for g in done if g["actual"]["corrected"]],
            "noted": [row(g) for g in done if g["actual"]["noted"]]}
