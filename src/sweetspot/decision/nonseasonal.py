"""The non-seasonal part of each decision (feature 007 spec FR-013–FR-016; contracts/outputs-non-seasonal.md).

The rule never reads any of this (spec FR-012): it is added to a finished decision. Before the model is adopted
only the basis is shown (FR-016); after adoption the probabilities of reaching the sweet price, and "可能比〈甜蜜時點〉
更早到價" when the judging horizon's probability reaches the threshold (FR-014). All text is written here; the report
only prints it (constitution VII).
"""

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from sweetspot.decision.contract import Decision, twd
from sweetspot.forecast.contract import LEVELS, iso
from sweetspot.forecast.nonseasonal import EARLIER_THRESHOLD, HORIZONS
from sweetspot.forecast.nonseasonal.evidence import MIN_EXTRA_DAYS, NSBasis
from sweetspot.forecast.nonseasonal.model import NSOutput

TAG = "earlier-possible"
EARLIER_GROUPS = ("soon", "wait", "low")


def _day(moment: datetime | None) -> str:
    """Taipei date."""
    return (moment + timedelta(hours=8)).strftime("%Y-%m-%d") if moment else "未知"


def _basis_dict(b: NSBasis) -> dict[str, Any]:
    return {"history_start": iso(b.history_start), "history_source": b.history_source, "history_days": b.history_days,
            "promos_365d": b.promos_365d, "interval_days": b.interval_days, "common_depth": b.common_depth,
            "last_start": iso(b.last_start), "last_depth": b.last_depth, "days_since": b.days_since,
            "in_promo_now": b.in_promo_now}


def judging_horizon(sale_start: datetime, as_of: datetime) -> int | None:
    """The longest horizon that ends before the sweet sale starts (spec FR-014; clarify 2026-09-26)."""
    fits = [h for h in HORIZONS if as_of + timedelta(days=h) <= sale_start]
    return fits[-1] if fits else None


def earlier(d: Decision, out: NSOutput, as_of: datetime, figures: Mapping | None,
            threshold: float = EARLIER_THRESHOLD, confidence: str | None = None) -> dict[str, Any] | None:
    """"可能比〈甜蜜時點〉更早到價", or None. Needs a backtest figure to quote (constitution IV)."""
    if figures is None or figures.get("earlier_hit_rate") is None:
        return None
    if d.group not in EARLIER_GROUPS or (confidence or out.confidence) != "normal" or d.sweet_point is None:
        return None
    h = judging_horizon(d.sweet_point.start, as_of)
    if h is None:
        return None
    p = round(out.probabilities[HORIZONS.index(h)][LEVELS.index(d.sweet_pct)], 6)
    if p < threshold:
        return None
    return {"horizon_days": h, "probability": p, "threshold": threshold, "sale_label": d.sweet_point.label,
            "hit_rate": figures["earlier_hit_rate"]}


def _basis_reasons(b: NSBasis, *, tw_start: datetime | None, adopted: bool) -> list[str]:
    last = f"{_day(b.last_start)}（-{b.last_depth}%）" if b.last_start else None
    if b.promos_365d == 0:
        out = ["過去一年季節特賣以外沒有促銷" + (f"（上一次 {last}）" if last else "")]
    elif b.promos_365d == 1:
        out = [f"過去一年季節特賣以外有 1 次促銷：{last}"]
    else:
        out = [f"過去一年季節特賣以外有 {b.promos_365d} 次促銷，約每 {b.interval_days} 天一次，常見 -{b.common_depth}%；"
               f"上一次 {last}，{b.days_since} 天前"]
    if b.in_promo_now:
        text = f"目前正在季節特賣以外的促銷（-{b.last_depth}%，{_day(b.last_start)} 開始）"
        out.append(text + ("；以下機率是這次結束之後再次到價" if adopted else ""))
    if b.history_source == "TW+US" and tw_start is not None:
        out.append(f"台灣區的價格歷史從 {_day(tw_start)} 開始，之前以美國區同一商品的折扣日期補足")
    return out


def attach(d: Decision, out: NSOutput | str | None, *, adopted: bool, as_of: datetime,
           tw_start: datetime | None, figures: Mapping | None) -> Decision:
    """The decision with its `non_seasonal` part (and the `earlier-possible` tag). Nothing else changes."""
    empty = {"status": None, "status_reason": None, "confidence": None, "basis": None, "sweet": None,
             "probabilities": None, "earlier": None, "reasons": []}
    if d.group == "na":
        return replace(d, non_seasonal={**empty, "status": "na"})
    if out is None or isinstance(out, str):
        reason = out or "沒有非季節預測"
        return replace(d, non_seasonal={**empty, "status": "model-error", "status_reason": reason,
                                        "reasons": [f"非季節預測暫時無法計算：{reason}"]})
    stopped = (d.version or {}).get("tracking") == "stopped"
    confidence = "low" if stopped else out.confidence
    reasons = _basis_reasons(out.basis, tw_start=tw_start, adopted=adopted)
    ns = {**empty, "status": "ok" if adopted else "not-adopted", "confidence": confidence,
          "basis": _basis_dict(out.basis), "reasons": reasons}
    if not adopted:
        return replace(d, non_seasonal=ns)
    rows = [[round(p, 6) for p in row] for row in out.probabilities]
    j = LEVELS.index(d.sweet_pct)
    ns["probabilities"] = rows
    ns["sweet"] = {str(h): rows[i][j] for i, h in enumerate(HORIZONS)}
    short = [h for h, s in zip(HORIZONS, out.sources) if s == "population"]
    if short:
        reasons.append(f"價格歷史不到 {short[-1] + MIN_EXTRA_DAYS} 天，{'、'.join(f'{h} 天' for h in short)}"
                       "的機率改用所有遊戲的整體比例（低信心）")
    probs = "、".join(f"{h} 天內 {ns['sweet'][str(h)]:.0%}" for h in HORIZONS)
    reasons.append(f"季節特賣以外降到甜蜜價 NT${twd(d.sweet_cents)}（-{d.sweet_pct}%）以下的機率：{probs}")
    e = earlier(d, out, as_of, figures, confidence=confidence)
    ns["earlier"] = e
    tags = d.tags
    if e:
        reasons.append(f"可能比 {e['sale_label']}更早到價：{e['horizon_days']} 天內有 {e['probability']:.0%} 的機率"
                       f"在季節特賣以外降到甜蜜價以下（回測中這類說法有 {e['hit_rate']:.0%} 實際到價）")
        tags = tags + (TAG,)
    return replace(d, non_seasonal=ns, tags=tags)


def batch_block(model, *, adopted: bool, figures: Mapping | None) -> dict[str, Any]:
    return {"adopted": adopted,
            "model": {"name": model.name, "version": model.version, "params": dict(model.params)} if adopted else None,
            "confidence_levels": dict(model.confidence_levels()), "horizons_days": list(HORIZONS),
            "threshold": EARLIER_THRESHOLD, "backtest": dict(figures) if adopted and figures else None}


def check(d: Decision, as_of: datetime) -> str | None:
    """The contract's guarantees 1, 2 and 4 for one decision; None when fine."""
    ns = d.non_seasonal
    if not ns:
        return None
    rows, early = ns.get("probabilities"), ns.get("earlier")
    if ns.get("status") == "ok":
        if not rows or len(rows) != len(HORIZONS) or any(len(r) != len(LEVELS) for r in rows):
            return "非季節機率的形狀不對"
        for i, row in enumerate(rows):
            if any(b > a for a, b in zip(row, row[1:])) or (i and any(b < a for a, b in zip(rows[i - 1], row))):
                return "非季節機率必須隨折扣加深不增加、隨期間加長不減少"
        j = LEVELS.index(d.sweet_pct)
        if ns.get("sweet") != {str(h): rows[i][j] for i, h in enumerate(HORIZONS)}:
            return "非季節的甜蜜價機率必須等於機率表中的那一格"
    if (d.version or {}).get("tracking") == "stopped" and (ns.get("confidence") != "low" or early):
        return "價格歷史停止更新時，非季節預測必須是低信心，而且不寫更早到價"
    if early:
        if ns.get("status") != "ok":
            return "只有已採用的非季節預測可以寫更早到價"
        if ns.get("confidence") != "normal":
            return "非季節預測的信心是低，不可寫更早到價"
        if d.group not in EARLIER_GROUPS:
            return "「現在買」或無法預測的遊戲不可寫更早到價"
        if judging_horizon(d.sweet_point.start, as_of) != early["horizon_days"]:
            return "判斷期間必須是甜蜜時點那場特賣開始前就結束的最長期間"
        if early["probability"] < early["threshold"]:
            return "更早到價的機率必須達到門檻"
    return None
