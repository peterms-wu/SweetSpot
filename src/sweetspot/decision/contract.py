"""The versioned decision output `steamsage.decision/2` (003 contracts/decision-output.md; 005 decision-output-v2.md).

/2 (feature 005) adds the rule 3.0.0 waiting table; its tolerance fields are null because 3.0.0 has no tolerance
(constitution I: an unknown is not written as zero). /1 records stay readable (decision.records).
Feature 007 adds the optional `non_seasonal` parts (per decision and per batch) without changing the schema
(specs/007-non-seasonal-discounts/contracts/outputs-non-seasonal.md).

It embeds the full forecast, so one file is both the report's input and the official forecast record. Display
amounts in whole NT$ are computed here (0.5 rounds up); presentation layers never compute (constitution VII).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sweetspot.decision.prices import CurrentPrice
from sweetspot.decision.rule import LadderRow, WaitOption
from sweetspot.forecast.contract import ForecastBatch, iso
from sweetspot.forecast.contract import batch_to_dict as forecast_to_dict
from sweetspot.forecast.salepoints import SalePoint

SCHEMA = "steamsage.decision/2"
GROUPS = ("now", "soon", "wait", "low", "na")


def twd(cents: int | None) -> int | None:
    """Whole NT$, 0.5 rounds up (toward +infinity, also for the negative expected savings of feature 005)."""
    return None if cents is None else (cents + 50) // 100


@dataclass(frozen=True)
class Decision:
    app_id: int
    name: str | None
    group: str
    status: str                        # forecast status, or decision-error
    status_reason: str | None
    confidence: str | None
    basis: str | None                  # own | no-history
    horizon_points: int | None
    regular_cents: int | None
    current: CurrentPrice | None
    p_min_pct: int | None
    p_min_cents: int | None
    gap_pp: int | None
    tolerance_cents: int | None
    tolerance_bound: str | None
    target_cents: int | None
    sweet_pct: int | None
    sweet_cents: int | None
    sweet_point: SalePoint | None
    sweet_probability: float | None
    ladder: tuple[LadderRow, ...]
    tags: tuple[str, ...]
    reasons: tuple[str, ...]
    change: Mapping[str, Any] | None = None
    wait_options: tuple[WaitOption, ...] = ()     # rule 3.0.0 only
    deadline_point: SalePoint | None = None       # rule 3.0.0: latest sale of the chosen option; None = buy now
    expected: WaitOption | None = None            # rule 3.0.0: the chosen row
    version: Mapping[str, Any] | None = None       # feature 006: the forecast's version, copied (constitution VII)
    non_seasonal: Mapping[str, Any] | None = None  # feature 007: decision.nonseasonal.attach (the rule never reads it)
    editions: tuple[Mapping[str, Any], ...] | None = None   # feature 009: decision.editions.build_editions
    bundles: tuple[int, ...] | None = None        # feature 010: ids of the batch's bundles holding this game

    def __post_init__(self) -> None:
        if self.group not in GROUPS:
            raise ValueError(f"未知的分組：{self.group!r}")
        if self.group == "na":
            if not self.status_reason:
                raise ValueError("無法預測的遊戲必須附原因")
            if self.sweet_point is not None or self.ladder:
                raise ValueError("無法預測的遊戲不可有甜蜜價")
            return
        if self.sweet_point is None or self.sweet_cents is None or not self.ladder or not self.reasons:
            raise ValueError("有建議的遊戲必須有甜蜜時點、甜蜜價、等待對照表與原因")
        if self.ladder[-1].index != self.sweet_point.index:
            raise ValueError("等待對照表的最後一列必須是甜蜜時點")
        if self.wait_options:
            self._check_wait_cost()
            return
        if self.sweet_pct > self.p_min_pct or self.sweet_cents < self.p_min_cents:
            raise ValueError("甜蜜價不可比長期最低價更低")
        if self.group == "now":
            price = self.current.price_cents if self.current else None
            if price is None or price * 100 > self.regular_cents * (100 - self.sweet_pct):
                raise ValueError("「現在買」的現價必須已知且不高於甜蜜價")

    def _check_wait_cost(self) -> None:
        """contracts/decision-output-v2.md guarantees 5-7 (rule 3.0.0)."""
        chosen = [o for o in self.wait_options if o.chosen]
        if len(chosen) != 1:
            raise ValueError("等待對照表必須恰好一列是選中的選項")
        if self.expected != chosen[0]:
            raise ValueError("expected 必須是等待對照表中選中的那一列")
        if (self.group == "now") != (self.expected.deadline_index == 0):
            raise ValueError("只有選中「現在買」那一列時，分組才是現在買")
        if self.group == "now":
            if self.current is None or self.current.price_cents is None or self.deadline_point is not None:
                raise ValueError("「現在買」的現價必須已知，而且沒有最晚時點")
            return
        if self.deadline_point is None or self.deadline_point.index != self.expected.deadline_index:
            raise ValueError("等待的建議必須有最晚時點，而且等於選中選項的最晚時點")
        if (self.sweet_point.index != self.expected.likely_index
                or self.sweet_probability != self.expected.likely_probability):
            raise ValueError("甜蜜時點必須是選中選項最可能到價的那一場")


def na_decision(app_id: int, name: str | None, status: str, reason: str,
                version: Mapping[str, Any] | None = None) -> Decision:
    return Decision(app_id, name, "na", status, reason, None, None, None, None, None, None, None, None, None, None,
                    None, None, None, None, None, (), (), (), version=version)


@dataclass(frozen=True)
class DecisionBatch:
    official: bool
    as_of: datetime
    generated_at: datetime
    rule: Mapping[str, Any]
    preferences: Mapping[str, int]
    data_refresh: Mapping[str, Any]
    rule_backtest: Mapping[str, Any] | None
    comparison: Mapping[str, Any] | None
    decisions: tuple[Decision, ...]
    forecast: ForecastBatch
    notes: tuple[str, ...] = ()           # the current model's caveats, numbers filled in (004 research R9)
    non_seasonal: Mapping[str, Any] | None = None     # feature 007: decision.nonseasonal.batch_block
    warnings: tuple[str, ...] = ()        # feature 009: [purchase_options] entries that were ignored
    bundles: tuple[Mapping[str, Any], ...] | None = None   # feature 010: decision.bundles.build_bundles
    bundle_rule: Mapping[str, str] | None = None
    calendar_notices: tuple[str, ...] = ()   # feature 012 (plan D1): sale-calendar alerts to act on
    reference_notice: Mapping[str, Any] | None = None   # feature 014 FR-014a: written only when set

    def __post_init__(self) -> None:
        from sweetspot.decision.nonseasonal import check

        ids = [d.app_id for d in self.decisions]
        if len(ids) != len(set(ids)):
            raise ValueError("決策中有重複的遊戲")
        for d in self.decisions:
            problem = check(d, self.as_of)
            if problem:
                raise ValueError(f"遊戲 {d.app_id}：{problem}")
        if not self.official and (self.comparison is not None or any(d.change for d in self.decisions)):
            raise ValueError("只有正式執行才有比較基準與變動")


def _current(c: CurrentPrice | None) -> dict[str, Any] | None:
    if c is None:
        return None
    return {"price_cents": c.price_cents, "price_twd": twd(c.price_cents), "regular_cents": c.regular_cents,
            "cut_pct": c.cut_pct, "source": c.source, "observed_at": iso(c.observed_at),
            "confirmed_at": iso(c.confirmed_at), "stale": c.stale, "history_regular_cents": c.history_regular_cents,
            "history_regular_twd": twd(c.history_regular_cents), "regular_mismatch": c.regular_mismatch}


def _point(p: SalePoint | None) -> dict[str, Any] | None:
    if p is None:
        return None
    return {"index": p.index, "label": p.label, "start": iso(p.start), "end": iso(p.end), "status": p.status}


def decision_to_dict(d: Decision) -> dict[str, Any]:
    return {
        "app_id": d.app_id, "name": d.name, "group": d.group, "status": d.status, "status_reason": d.status_reason,
        "confidence": d.confidence, "basis": d.basis, "horizon_points": d.horizon_points,
        "regular_cents": d.regular_cents, "regular_twd": twd(d.regular_cents), "current": _current(d.current),
        "p_min_pct": d.p_min_pct, "p_min_cents": d.p_min_cents, "p_min_twd": twd(d.p_min_cents),
        "gap_pp": d.gap_pp, "tolerance_cents": d.tolerance_cents, "tolerance_twd": twd(d.tolerance_cents),
        "tolerance_bound": d.tolerance_bound, "target_cents": d.target_cents,
        "sweet_pct": d.sweet_pct, "sweet_cents": d.sweet_cents, "sweet_twd": twd(d.sweet_cents),
        "sweet_point": _point(d.sweet_point),
        "sweet_probability": None if d.sweet_probability is None else round(d.sweet_probability, 6),
        "ladder": [{"index": r.index, "label": r.label, "pct": r.pct, "cents": r.cents, "twd": twd(r.cents),
                    "probability": None if r.probability is None else round(r.probability, 6)} for r in d.ladder],
        "tags": list(d.tags), "reasons": list(d.reasons),
        "change": None if d.change is None else dict(d.change),
        "version": None if d.version is None else dict(d.version),
        "deadline_point": _point(d.deadline_point),
        "expected": _option(d.expected),
        "wait_options": [_option(o) for o in d.wait_options],
        "non_seasonal": None if d.non_seasonal is None else dict(d.non_seasonal),
        "editions": None if d.editions is None else [dict(e) for e in d.editions],
        "bundles": None if d.bundles is None else list(d.bundles),
    }


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def _option(o: WaitOption | None) -> dict[str, Any] | None:
    if o is None:
        return None
    return {"deadline_index": o.deadline_index, "deadline_label": o.deadline_label, "target_pct": o.target_pct,
            "target_cents": o.target_cents, "target_twd": twd(o.target_cents),
            "reach_probability": _round(o.reach_probability, 6), "likely_index": o.likely_index,
            "likely_label": o.likely_label, "likely_probability": _round(o.likely_probability, 6),
            "expected_saving_cents": o.expected_saving_cents, "expected_saving_twd": twd(o.expected_saving_cents),
            "expected_wait_months": _round(o.expected_wait_months, 4),
            "wait_cost_cents": o.wait_cost_cents, "wait_cost_twd": twd(o.wait_cost_cents),
            "net_cents": o.net_cents, "net_twd": twd(o.net_cents), "chosen": o.chosen}


def summarize(decisions: Sequence[Decision]) -> dict[str, int]:
    summary = {g: 0 for g in GROUPS}
    for d in decisions:
        summary[d.group] += 1
    summary["decision_error"] = sum(d.status == "decision-error" for d in decisions)
    summary["changed"] = sum(bool(d.change) for d in decisions)
    return summary


def batch_to_dict(batch: DecisionBatch) -> dict[str, Any]:
    out = {
        "schema": SCHEMA,
        "official": batch.official,
        "as_of": iso(batch.as_of),
        "generated_at": iso(batch.generated_at),
        "rule": dict(batch.rule),
        "preferences": dict(batch.preferences),
        "data_refresh": dict(batch.data_refresh),
        "rule_backtest": None if batch.rule_backtest is None else dict(batch.rule_backtest),
        "notes": list(batch.notes),
        "comparison": None if batch.comparison is None else dict(batch.comparison),
        "decisions": [decision_to_dict(d) for d in batch.decisions],
        "summary": summarize(batch.decisions),
        "forecast": forecast_to_dict(batch.forecast),
        "non_seasonal": None if batch.non_seasonal is None else dict(batch.non_seasonal),
        "warnings": list(batch.warnings),
        "bundle_rule": None if batch.bundle_rule is None else dict(batch.bundle_rule),
        "bundles": None if batch.bundles is None else [dict(b) for b in batch.bundles],
        "calendar_notices": list(batch.calendar_notices),
    }
    if batch.reference_notice is not None:             # absent above the target: older records stay the same
        out["reference_notice"] = dict(batch.reference_notice)
    return out
