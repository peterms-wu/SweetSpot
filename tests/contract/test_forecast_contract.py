"""contracts/forecast-output.md guarantees 1-8 for sweetspot.forecast.contract (tasks T009)."""

import json

import pytest

from sweetspot.forecast.contract import (LEVELS, SCHEMA, CurveError, Forecast, ForecastBatch, ModelInfo,
                                         batch_to_dict, dumps, validate_curve, write_json_atomic)
from sweetspot.forecast.salepoints import SalePoint
from tests.forecast_builders import dt


def point(i: int) -> SalePoint:
    return SalePoint(index=i, season="summer", year=2025 + i, label=f"{2025 + i} 夏特",
                     start=dt(f"{2025 + i}-06-26T17:00"), end=dt(f"{2025 + i}-07-10T17:00"), status="estimated",
                     basis={"reference_year": 2024})


def curve(n_points: int, p: float = 0.5) -> tuple[tuple[float, ...], ...]:
    return tuple(tuple(min(1.0, p * (i + 1) * (1 - j / 20)) for j in range(len(LEVELS))) for i in range(n_points))


def ok_forecast(app_id: int = 10, **kw) -> Forecast:
    base = dict(app_id=app_id, name="Game", status="ok", confidence="normal", reasons=("理由",),
                evidence={"regions": ["TW"]}, regular_price_cents=42000, points=(point(1), point(2)),
                probabilities=curve(2, 0.3))
    base.update(kw)
    return Forecast(**base)


def batch(*games: Forecast) -> ForecastBatch:
    return ForecastBatch(model=ModelInfo("seasonal-freq", "1.0.0", {"min_sales": 1, "history": "TW"}),
                         as_of=dt("2025-06-01"), data_cutoff=dt("2025-05-31"), generated_at=dt("2025-06-01T03:00"),
                         levels=LEVELS, confidence_levels={"normal": "a", "low": "b"}, games=games)


def test_levels_are_5_to_95():
    assert LEVELS == tuple(range(5, 100, 5))


@pytest.mark.parametrize("bad", [
    [[0.1] * 19],                                   # wrong number of points
    [[0.1] * 18, [0.1] * 18],                       # wrong number of levels
    [[0.1] * 19, [1.2] + [0.1] * 18],               # out of range
    [[0.5] * 19, [0.4] + [0.4] * 18],               # decreasing over time
    [[0.1] + [0.2] * 18, [0.3] * 19],               # increasing with deeper discount
    [[float("nan")] * 19, [0.3] * 19],
])
def test_validate_curve_rejects(bad):
    with pytest.raises(CurveError):
        validate_curve(bad, n_points=2, n_levels=19)


def test_validate_curve_accepts_monotone_curve():
    validate_curve(curve(3, 0.2), n_points=3, n_levels=19)


def test_ok_requires_confidence_reasons_and_curve():
    with pytest.raises(ValueError):
        ok_forecast(confidence=None)
    with pytest.raises(ValueError):
        ok_forecast(reasons=())
    with pytest.raises(ValueError):
        ok_forecast(points=(), probabilities=())
    with pytest.raises(ValueError):
        ok_forecast(confidence="high")


def test_non_ok_has_reason_and_no_curve():
    f = Forecast(app_id=2, name="x", status="unreleased", status_reason="預定 2027-03 發售")
    assert batch_to_dict(batch(f))["games"][0]["curve"] is None
    with pytest.raises(ValueError):
        Forecast(app_id=2, name="x", status="unreleased")
    with pytest.raises(ValueError):
        Forecast(app_id=2, name="x", status="free", status_reason="免費", points=(point(1),),
                 probabilities=curve(1))
    with pytest.raises(ValueError):
        Forecast(app_id=2, name="x", status="weird", status_reason="?")


def test_json_shape_and_guarantees():
    data = batch_to_dict(batch(ok_forecast(10), ok_forecast(11, confidence="low", regular_price_cents=None),
                               Forecast(app_id=12, name="y", status="no-history", status_reason="沒有歷史")))
    assert data["schema"] == SCHEMA == "steamsage.forecast/1"
    assert data["model"] == {"name": "seasonal-freq", "version": "1.0.0", "params": {"history": "TW", "min_sales": 1}}
    assert data["as_of"] == "2025-06-01T00:00:00Z" and data["data_cutoff"] == "2025-05-31T00:00:00Z"
    assert data["levels"] == list(LEVELS)
    first = data["games"][0]
    assert first["curve"]["points"][0] == {
        "index": 1, "label": "2026 夏特", "season": "summer", "year": 2026, "start": "2026-06-26T17:00:00Z",
        "end": "2026-07-10T17:00:00Z", "status": "estimated", "basis": {"reference_year": 2024}}
    assert len(first["curve"]["probabilities"]) == 2 and len(first["curve"]["probabilities"][0]) == 19
    assert data["games"][1]["regular_price_cents"] is None          # unknown is null, never 0
    assert data["summary"] == {"ok": 2, "low_confidence": 1, "unreleased": 0, "free": 0, "unsupported_bundle": 0,
                               "no_history": 1, "unverified": 0, "model_error": 0}


def test_only_tw_regular_price_carries_money():
    text = dumps(batch_to_dict(batch(ok_forecast())))
    keys = set()

    def walk(node):
        if isinstance(node, dict):
            keys.update(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(json.loads(text))
    assert {k for k in keys if "cents" in k or "price" in k} == {"regular_price_cents"}


def test_dumps_is_deterministic_with_sorted_keys():
    a = dumps(batch_to_dict(batch(ok_forecast())))
    assert a == dumps(batch_to_dict(batch(ok_forecast())))
    assert list(json.loads(a)) == sorted(json.loads(a))


def test_write_json_atomic(tmp_path):
    target = tmp_path / "out" / "forecast.json"
    write_json_atomic(target, {"a": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}
    assert not target.with_name(target.name + ".tmp").exists()


def test_write_json_atomic_leaves_no_file_on_failure(tmp_path):
    target = tmp_path / "forecast.json"
    with pytest.raises(TypeError):
        write_json_atomic(target, {"bad": object()})
    assert not target.exists()


# --- feature 003: optional top-level no_history (research R2) ---------------------------------------------

def test_no_history_is_optional_and_serialised():
    from sweetspot.forecast.contract import NoHistoryCurve

    plain = batch_to_dict(batch(ok_forecast()))
    assert plain["no_history"] is None
    with_curve = ForecastBatch(**{**batch(ok_forecast()).__dict__,
                                  "no_history": NoHistoryCurve("low", ("整體比例",), curve(2, 0.2))})
    data = batch_to_dict(with_curve)
    assert data["no_history"]["confidence"] == "low"
    assert data["no_history"]["reasons"] == ["整體比例"]
    assert len(data["no_history"]["probabilities"]) == 2
    assert data["schema"] == SCHEMA == "steamsage.forecast/1"
