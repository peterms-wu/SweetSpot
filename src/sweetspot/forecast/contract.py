"""The versioned forecast output `steamsage.forecast/1` (contracts/forecast-output.md).

Presentation layers read this and never recompute it (constitution VII).
"""

import json
import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sweetspot.forecast.salepoints import SalePoint

SCHEMA = "steamsage.forecast/1"
LEVELS: tuple[int, ...] = tuple(range(5, 100, 5))
STATUSES = ("ok", "unreleased", "free", "unsupported-bundle", "no-history", "unverified", "model-error")
CONFIDENCES = ("normal", "low")


class CurveError(ValueError):
    pass


def validate_curve(probabilities: Sequence[Sequence[float]], n_points: int, n_levels: int) -> None:
    """FR-004: shape, 0..1, non-decreasing over time, non-increasing with deeper discounts."""
    if len(probabilities) != n_points:
        raise CurveError(f"時點數不符：{len(probabilities)} ≠ {n_points}")
    previous = None
    for i, row in enumerate(probabilities):
        if len(row) != n_levels:
            raise CurveError(f"第 {i + 1} 個時點的折扣等級數不符：{len(row)} ≠ {n_levels}")
        for j, p in enumerate(row):
            if not (isinstance(p, (int, float)) and math.isfinite(p) and 0.0 <= p <= 1.0):
                raise CurveError(f"機率超出 0–1：時點 {i + 1}、等級 {j + 1} = {p!r}")
            if j and p > row[j - 1] + 1e-12:
                raise CurveError(f"時點 {i + 1} 的機率隨折扣加深而上升（等級 {j} → {j + 1}）")
            if previous is not None and p < previous[j] - 1e-12:
                raise CurveError(f"等級 {j + 1} 的機率隨時間下降（時點 {i} → {i + 1}）")
        previous = row


@dataclass(frozen=True)
class ModelInfo:
    name: str
    version: str
    params: Mapping[str, Any]


@dataclass(frozen=True)
class VersionChange:
    from_itad_id: str | None
    from_title: str | None
    to_itad_id: str | None
    to_title: str | None
    detected_at: datetime


@dataclass(frozen=True)
class VersionInfo:
    """Which product's price history a forecast used (feature 006, contracts/outputs-version.md)."""
    basis: str                              # version | own | rejected | user (feature 009)
    basis_reason: str | None = None         # basis=own: no-record | no-option | ambiguous | not-in-itad
    package_id: int | None = None
    package_name: str | None = None
    itad_id: str | None = None
    history_start: datetime | None = None
    known_until: datetime | None = None
    tracking: str | None = None             # ok | stopped
    last_confirmed: datetime | None = None
    change: VersionChange | None = None
    reason_code: str | None = None          # basis=rejected
    reason_detail: str | None = None
    checked_at: datetime | None = None      # when the version row was recorded
    own_itad_id: str | None = None          # the app's own 001 product; differs from itad_id after a version switch
    # feature 009 (contracts/outputs-options.md)
    source: str | None = None               # steam-default | user | user-fallback
    option: Mapping[str, Any] | None = None     # the tracked purchase option {kind, id, name}
    fallback: Mapping[str, Any] | None = None   # {code, detail, requested: {kind, id, name}}
    aux_pending: bool = False               # a chosen edition whose aux-region history is not fetched yet (plan D2)


@dataclass(frozen=True)
class Forecast:
    app_id: int
    name: str | None
    status: str
    status_reason: str | None = None
    confidence: str | None = None
    reasons: tuple[str, ...] = ()
    evidence: Mapping[str, Any] = field(default_factory=dict)
    regular_price_cents: int | None = None      # TW only; None = unknown, never 0 for unknown
    points: tuple[SalePoint, ...] = ()
    probabilities: tuple[tuple[float, ...], ...] = ()
    version: VersionInfo | None = None          # feature 006, optional field

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"未知的狀態：{self.status!r}")
        if self.status == "ok":
            if self.confidence not in CONFIDENCES:
                raise ValueError(f"status=ok 必須有信心等級 {CONFIDENCES}")
            if not self.reasons:
                raise ValueError("status=ok 必須附原因")
            if not self.points:
                raise ValueError("status=ok 必須有曲線")
            validate_curve(self.probabilities, len(self.points), len(LEVELS))
        else:
            if not self.status_reason:
                raise ValueError(f"status={self.status} 必須附 status_reason")
            if self.points or self.probabilities:
                raise ValueError(f"status={self.status} 不可有曲線")


@dataclass(frozen=True)
class NoHistoryCurve:
    """What the model predicts for a game with no own history (feature 003 research R2), same points as the
    batch. The decision core falls back to it when a game's own curve gives no discount at all."""

    confidence: str
    reasons: tuple[str, ...]
    probabilities: tuple[tuple[float, ...], ...]


@dataclass(frozen=True)
class ForecastBatch:
    model: ModelInfo
    as_of: datetime
    data_cutoff: datetime | None
    generated_at: datetime
    levels: tuple[int, ...]
    confidence_levels: Mapping[str, str]
    games: tuple[Forecast, ...]
    no_history: NoHistoryCurve | None = None      # optional field; the contract version is unchanged


def iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def point_to_dict(p: SalePoint) -> dict[str, Any]:
    return {"index": p.index, "label": p.label, "season": p.season, "year": p.year, "start": iso(p.start),
            "end": iso(p.end), "status": p.status, "basis": p.basis}


def version_to_dict(v: VersionInfo | None) -> dict[str, Any] | None:
    if v is None:
        return None
    change = None
    if v.change is not None:
        change = {"from_itad_id": v.change.from_itad_id, "from_title": v.change.from_title,
                  "to_itad_id": v.change.to_itad_id, "to_title": v.change.to_title,
                  "detected_at": iso(v.change.detected_at)}
    return {"basis": v.basis, "basis_reason": v.basis_reason, "package_id": v.package_id,
            "package_name": v.package_name, "itad_id": v.itad_id, "history_start": iso(v.history_start),
            "known_until": iso(v.known_until), "tracking": v.tracking, "last_confirmed": iso(v.last_confirmed),
            "change": change, "reason_code": v.reason_code, "reason_detail": v.reason_detail,
            "checked_at": iso(v.checked_at), "own_itad_id": v.own_itad_id, "source": v.source,
            "option": None if v.option is None else dict(v.option),
            "fallback": None if v.fallback is None else {**v.fallback, "requested": dict(v.fallback["requested"])},
            "aux_pending": v.aux_pending}


def forecast_to_dict(f: Forecast) -> dict[str, Any]:
    curve = None
    if f.status == "ok":
        curve = {"points": [point_to_dict(p) for p in f.points],
                 "probabilities": [[round(p, 6) for p in row] for row in f.probabilities]}
    return {"app_id": f.app_id, "name": f.name, "status": f.status, "status_reason": f.status_reason,
            "confidence": f.confidence, "regular_price_cents": f.regular_price_cents, "reasons": list(f.reasons),
            "evidence": dict(f.evidence), "curve": curve, "version": version_to_dict(f.version)}


def summarize(games: Sequence[Forecast]) -> dict[str, int]:
    summary = {s.replace("-", "_"): 0 for s in STATUSES}
    summary["low_confidence"] = 0
    for g in games:
        summary[g.status.replace("-", "_")] += 1
        summary["low_confidence"] += g.confidence == "low"
    return summary


def batch_to_dict(batch: ForecastBatch) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "model": {"name": batch.model.name, "version": batch.model.version, "params": dict(batch.model.params)},
        "as_of": iso(batch.as_of),
        "data_cutoff": iso(batch.data_cutoff),
        "generated_at": iso(batch.generated_at),
        "levels": list(batch.levels),
        "confidence_levels": dict(batch.confidence_levels),
        "games": [forecast_to_dict(g) for g in batch.games],
        "summary": summarize(batch.games),
        "no_history": None if batch.no_history is None else {
            "confidence": batch.no_history.confidence, "reasons": list(batch.no_history.reasons),
            "probabilities": [[round(p, 6) for p in row] for row in batch.no_history.probabilities]},
    }


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True)


def write_json_atomic(path: Path, obj: Any) -> Path:
    """Write to <path>.tmp, then rename; a failure never leaves a file at `path` (FR-017)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = dumps(obj)                 # serialise first: a bad object must not touch the disk
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path
