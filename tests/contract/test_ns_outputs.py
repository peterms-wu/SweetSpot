"""Non-seasonal fields of the decision output and records (feature 007 contracts/outputs-non-seasonal.md; tasks T024)."""

import copy
from dataclasses import replace
from datetime import timedelta

import pytest

from sweetspot.decision.changes import compare
from sweetspot.decision.contract import DecisionBatch, batch_to_dict
from sweetspot.decision.nonseasonal import attach, batch_block
from sweetspot.forecast.nonseasonal import build_ns_model
from sweetspot.forecast.nonseasonal.evidence import NSBasis
from sweetspot.forecast.nonseasonal.model import NSOutput
from tests.decision_builders import AS_OF, contract_dict, decision
from tests.forecast_builders import dt

LEVELS = tuple(range(5, 100, 5))
FIGURES = {"earlier_hit_rate": 0.736, "earlier_threshold": 0.5}
BASIS = NSBasis(dt("2025-06-26"), "TW", 456, 6, 58, 50, dt("2026-08-10"), 50, 46, False)
DAY = timedelta(days=1)


def output(p=0.8):
    rows = tuple(tuple(p if d <= 50 else 0.1 for d in LEVELS) for _ in range(3))
    return NSOutput(rows, "normal", ("own",) * 3, BASIS)


def with_ns(days=75, p=0.8, adopted=True):
    d = decision(1)
    d = replace(d, sweet_point=replace(d.sweet_point, start=AS_OF + days * DAY, end=AS_OF + (days + 7) * DAY))
    return attach(d, output(p), adopted=adopted, as_of=AS_OF, tw_start=dt("2025-06-26"),
                  figures=FIGURES if adopted else None)


def test_serialisation_and_batch_block():
    d = with_ns()
    data = contract_dict([d])
    ns = data["decisions"][0]["non_seasonal"]
    assert ns["status"] == "ok" and ns["sweet"]["60"] == 0.8 and ns["earlier"]["horizon_days"] == 60
    assert data["non_seasonal"] is None                              # the builder sets no batch block
    block = batch_block(build_ns_model("non-seasonal"), adopted=True, figures=FIGURES)
    full = batch_to_dict(replace(_batch(d), non_seasonal=block))
    assert full["non_seasonal"]["adopted"] is True and full["non_seasonal"]["threshold"] == 0.5


def _batch(d):
    from sweetspot.config import Preferences
    from sweetspot.decision.rule import RULE_NAME, RULES
    from sweetspot.forecast.contract import ForecastBatch, ModelInfo
    forecast = ForecastBatch(model=ModelInfo("seasonal-record", "1.0.0", {}), as_of=AS_OF, data_cutoff=AS_OF,
                             generated_at=AS_OF, levels=LEVELS, confidence_levels={"normal": "a", "low": "b"}, games=())
    return DecisionBatch(official=True, as_of=AS_OF, generated_at=AS_OF,
                         rule={"name": RULE_NAME, "version": "2.1.0", "constants": dict(RULES["2.1.0"]["constants"])},
                         preferences=Preferences().for_rule("2.1.0"), data_refresh={"update_exit": None, "note": None},
                         rule_backtest=None, comparison=None, decisions=(d,), forecast=forecast)


def test_guarantees_are_enforced():
    good = with_ns()
    _batch(good)                                                          # fine
    ns = copy.deepcopy(dict(good.non_seasonal))
    ns["probabilities"][1][3] = 0.0                                       # h = 60 below h = 30
    with pytest.raises(ValueError, match="非季節"):
        _batch(replace(good, non_seasonal=ns))
    ns = copy.deepcopy(dict(good.non_seasonal))
    ns["sweet"]["60"] = 0.5
    with pytest.raises(ValueError, match="甜蜜價"):
        _batch(replace(good, non_seasonal=ns))
    ns = copy.deepcopy(dict(good.non_seasonal))
    ns["earlier"]["horizon_days"] = 90                                    # would run into the sweet sale
    with pytest.raises(ValueError, match="判斷期間"):
        _batch(replace(good, non_seasonal=ns))
    ns = copy.deepcopy(dict(good.non_seasonal))
    ns["earlier"]["horizon_days"] = 30                                    # a longer horizon also qualifies
    with pytest.raises(ValueError, match="判斷期間"):
        _batch(replace(good, non_seasonal=ns))
    ns = copy.deepcopy(dict(good.non_seasonal))
    ns["confidence"] = "low"
    with pytest.raises(ValueError, match="信心"):
        _batch(replace(good, non_seasonal=ns))
    ns = copy.deepcopy(dict(good.non_seasonal))
    ns["status"], ns["probabilities"], ns["sweet"] = "not-adopted", None, None
    with pytest.raises(ValueError, match="更早到價"):
        _batch(replace(good, non_seasonal=ns))
    with pytest.raises(ValueError, match="停止更新"):
        _batch(replace(good, version={"tracking": "stopped"}))
    with pytest.raises(ValueError, match="現在買"):
        _batch(replace(good, group="now"))


def test_old_records_without_the_fields_are_read_and_compared():
    new = contract_dict([with_ns()])
    old = copy.deepcopy(new)
    old.pop("non_seasonal")
    for d in old["decisions"]:
        d.pop("non_seasonal")
    changes, comparison = compare(new, old)
    assert changes == {1: None} and comparison["changed_games"] == 0
    changes, _ = compare(old, new)
    assert changes == {1: None}


def test_starting_to_show_probabilities_is_noted():
    new = contract_dict([with_ns()])
    new["non_seasonal"] = batch_block(build_ns_model("non-seasonal"), adopted=True, figures=FIGURES)
    old = copy.deepcopy(new)
    old["non_seasonal"] = batch_block(build_ns_model("non-seasonal"), adopted=False, figures=None)
    _, comparison = compare(new, old)
    assert any("非季節預測模型開始顯示機率（non-seasonal 1.0.0" in c for c in comparison["version_changes"])
    old.pop("non_seasonal")
    _, comparison = compare(new, old)
    assert any("非季節預測模型開始顯示機率" in c for c in comparison["version_changes"])
    _, comparison = compare(new, copy.deepcopy(new))
    assert comparison["version_changes"] == []


def test_records_round_trip(tmp_path):
    from sweetspot.decision import records
    data = contract_dict([with_ns()])
    path = records.write_record(tmp_path, data)
    back = records.load_record(path)
    assert back["decisions"][0]["non_seasonal"] == data["decisions"][0]["non_seasonal"]
