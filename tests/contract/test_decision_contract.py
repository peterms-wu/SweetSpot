"""contracts/decision-output.md guarantees 1-10 for sweetspot.decision.contract (tasks T011)."""

import json
from dataclasses import replace

import pytest

from sweetspot.config import Preferences
from sweetspot.decision.contract import (GROUPS, SCHEMA, Decision, DecisionBatch, batch_to_dict, na_decision,
                                         summarize, twd)
from sweetspot.decision.prices import CurrentPrice
from sweetspot.decision.rule import CONSTANTS, RULE_NAME, RULE_VERSION, LadderRow
from sweetspot.forecast.contract import ForecastBatch, ModelInfo, LEVELS
from sweetspot.forecast.contract import batch_to_dict as forecast_to_dict
from tests.decision_builders import AS_OF, make_forecast, points

PTS = points(5)
NOW_PRICE = CurrentPrice(25000, 50000, 50, "steam-current", AS_OF, AS_OF, False, 50000, False)


def ok_decision(app_id=1, **kw):
    base = dict(app_id=app_id, name="Game", group="soon", status="ok", status_reason=None, confidence="normal",
                basis="own", horizon_points=5, regular_cents=50000, current=NOW_PRICE, p_min_pct=60,
                p_min_cents=20000, gap_pp=10, tolerance_cents=5000, tolerance_bound=None, target_cents=25000,
                sweet_pct=50, sweet_cents=25000, sweet_point=PTS[0], sweet_probability=1.0,
                ladder=(LadderRow(1, PTS[0].label, 50, 25000, 1.0),), tags=(), reasons=("理由",), change=None)
    base.update(kw)
    return Decision(**base)


def forecast_batch(n=2):
    return ForecastBatch(model=ModelInfo("seasonal-freq", "1.0.0", {"min_sales": 2, "history": "TW"}), as_of=AS_OF,
                         data_cutoff=AS_OF, generated_at=AS_OF, levels=LEVELS, confidence_levels={"normal": "a",
                         "low": "b"}, games=tuple(make_forecast(i, n_points=5) for i in range(1, n + 1)))


def batch(*decisions, official=True, comparison=None):
    return DecisionBatch(official=official, as_of=AS_OF, generated_at=AS_OF,
                         rule={"name": RULE_NAME, "version": RULE_VERSION, "constants": dict(CONSTANTS)},
                         preferences=Preferences().as_dict(), data_refresh={"update_exit": None, "note": None},
                         rule_backtest=None, comparison=comparison, decisions=decisions,
                         forecast=forecast_batch(len(decisions)))


def test_twd_rounds_half_up():
    assert [twd(16750), twd(33450), twd(33449), twd(0), twd(99)] == [168, 335, 334, 0, 1]
    # negative amounts (expected saving, net benefit; feature 005): 0.5 rounds up too
    assert [twd(-150), twd(-149), twd(-151), twd(-50), twd(-49)] == [-1, -1, -2, 0, 0]


def test_json_shape():
    data = batch_to_dict(batch(ok_decision(1), ok_decision(2, group="wait")))
    assert data["schema"] == SCHEMA == "steamsage.decision/2"
    assert data["official"] is True and data["as_of"] == "2026-09-25T00:00:00Z"
    assert data["rule"] == {"name": "sweet-price", "version": RULE_VERSION, "constants": CONSTANTS}
    assert data["preferences"]["gap_pp_deep"] == 5
    d = data["decisions"][0]
    assert (d["sweet_cents"], d["sweet_twd"], d["regular_twd"], d["p_min_twd"], d["tolerance_twd"]) == (
        25000, 250, 500, 200, 50)
    assert d["current"]["price_twd"] == 250 and d["current"]["confirmed_at"] == "2026-09-25T00:00:00Z"
    assert d["sweet_point"]["label"] == PTS[0].label and d["sweet_point"]["status"] == "announced"
    assert d["ladder"] == [{"index": 1, "label": PTS[0].label, "pct": 50, "cents": 25000, "twd": 250,
                            "probability": 1.0}]
    assert data["summary"] == {"now": 0, "soon": 1, "wait": 1, "low": 0, "na": 0, "decision_error": 0, "changed": 0}
    assert data["forecast"] == forecast_to_dict(batch(ok_decision(1), ok_decision(2)).forecast)
    json.dumps(data, ensure_ascii=False)


def test_every_app_exactly_once():
    with pytest.raises(ValueError, match="重複"):
        batch(ok_decision(1), ok_decision(1))
    assert GROUPS == ("now", "soon", "wait", "low", "na")


@pytest.mark.parametrize("change", [
    dict(group="later"),
    dict(sweet_point=None),
    dict(ladder=()),
    dict(reasons=()),
    dict(sweet_pct=65),                                             # deeper than P_min
    dict(sweet_cents=19000),                                        # below the P_min price
    dict(ladder=(LadderRow(2, PTS[1].label, 50, 25000, 1.0),)),     # last row is not the sweet point
    dict(group="now", current=replace(NOW_PRICE, price_cents=30000)),
    dict(group="now", current=replace(NOW_PRICE, price_cents=None)),
])
def test_invalid_decisions_are_rejected(change):
    with pytest.raises(ValueError):
        ok_decision(**change)


def test_na_decision_needs_a_reason_and_no_sweet_price():
    d = na_decision(7, "Old", "unreleased", "尚未發行")
    assert (d.group, d.status, d.status_reason, d.sweet_point) == ("na", "unreleased", "尚未發行", None)
    with pytest.raises(ValueError):
        na_decision(7, "Old", "unreleased", "")
    data = batch_to_dict(batch(ok_decision(1), d))
    assert data["decisions"][1]["sweet_twd"] is None and data["summary"]["na"] == 1


def test_decision_error_is_counted():
    d = na_decision(3, "X", "decision-error", "曲線不一致")
    assert summarize((d,))["decision_error"] == 1 and summarize((d,))["na"] == 1


def test_unofficial_batch_has_no_comparison_or_changes():
    with pytest.raises(ValueError, match="正式"):
        batch(ok_decision(1), official=False, comparison={"baseline": {"file": "x", "as_of": "y"}})
    with pytest.raises(ValueError, match="正式"):
        batch(ok_decision(1, change={"group": {"from": "wait", "to": "soon"}}), official=False)
    data = batch_to_dict(batch(ok_decision(1), official=False))
    assert data["comparison"] is None


def test_changed_count_in_summary():
    data = batch_to_dict(batch(ok_decision(1, change={"group": {"from": "wait", "to": "soon"},
                                                       "sweet_point": None, "sweet_twd": None}), ok_decision(2)))
    assert data["summary"]["changed"] == 1


def test_money_is_tw_only():
    data = batch_to_dict(batch(ok_decision(1), ok_decision(2)))
    text = json.dumps(data["decisions"], ensure_ascii=False)
    assert "USD" not in text and '"US"' not in text
    assert all(d["current"]["source"] in ("steam-current", "itad-history", "legacy-itad") for d in data["decisions"])


# --- feature 005: steamsage.decision/2 with rule 3.0.0 (tasks T004; contracts/decision-output-v2.md) -----------

from sweetspot.decision.rule import WaitOption  # noqa: E402

PTS4 = points(4)


def option(k, *, target=60, reach=0.9, likely=1, likely_p=0.6, saving=20000, wait=1.5, cost=3000, chosen=False):
    if k == 0:
        return WaitOption(0, None, None, 50000, None, None, None, None, 0, 0.0, 0, 0, chosen)
    return WaitOption(k, PTS4[k - 1].label, target, 50000 * (100 - target) // 100, reach, likely,
                      PTS4[likely - 1].label, likely_p, saving, wait, cost, saving - cost, chosen)


def v3_rows(chosen):
    return (option(0, chosen=chosen == 0),
            option(1, target=50, reach=0.6, likely=1, likely_p=0.6, saving=24000, wait=0.3, cost=600,
                   chosen=chosen == 1),
            option(2, target=60, reach=0.9, likely=2, likely_p=0.7, saving=28000, wait=2.0, cost=4000,
                   chosen=chosen == 2))


def v3_decision(app_id=1, chosen=2, **kw):
    rows = kw.pop("wait_options", None) or v3_rows(chosen)
    expected = kw.pop("expected", None) or rows[chosen]
    sweet = expected if chosen else rows[2]
    group = "now" if chosen == 0 else ("soon" if sweet.likely_index == 1 else "wait")
    current = NOW_PRICE if chosen == 0 else CurrentPrice(50000, 50000, 0, "steam-current", AS_OF, AS_OF, False,
                                                         50000, False)
    base = dict(app_id=app_id, name="Game", group=group, status="ok", status_reason=None, confidence="normal",
                basis="own", horizon_points=2, regular_cents=50000, current=current,
                p_min_pct=55, p_min_cents=22500, gap_pp=None, tolerance_cents=None, tolerance_bound=None,
                target_cents=None, sweet_pct=sweet.target_pct, sweet_cents=sweet.target_cents,
                sweet_point=PTS4[sweet.likely_index - 1], sweet_probability=sweet.likely_probability,
                ladder=tuple(LadderRow(p.index, p.label, 50, 25000, 1.0) for p in PTS4[:sweet.likely_index]),
                tags=(), reasons=("理由",), change=None, wait_options=rows,
                deadline_point=None if chosen == 0 else PTS4[expected.deadline_index - 1], expected=expected)
    base.update(kw)
    return Decision(**base)


def test_v3_decision_dict():
    d = batch_to_dict(batch(v3_decision(1)))["decisions"][0]
    assert d["gap_pp"] is None and d["tolerance_cents"] is None and d["tolerance_twd"] is None
    assert d["target_cents"] is None and d["tolerance_bound"] is None
    assert d["sweet_pct"] == 60 and d["sweet_twd"] == 200 and d["sweet_point"]["index"] == 2
    assert d["deadline_point"]["label"] == PTS4[1].label
    e = d["expected"]
    assert (e["deadline_index"], e["target_pct"], e["target_twd"], e["reach_probability"]) == (2, 60, 200, 0.9)
    assert (e["likely_index"], e["likely_label"], e["likely_probability"]) == (2, PTS4[1].label, 0.7)
    assert (e["expected_saving_cents"], e["expected_saving_twd"], e["expected_wait_months"]) == (28000, 280, 2.0)
    assert (e["wait_cost_cents"], e["wait_cost_twd"], e["net_cents"], e["net_twd"], e["chosen"]) == (
        4000, 40, 24000, 240, True)
    assert [r["deadline_index"] for r in d["wait_options"]] == [0, 1, 2]
    assert [r["chosen"] for r in d["wait_options"]] == [False, False, True]
    assert d["wait_options"][0]["net_twd"] == 0 and d["wait_options"][0]["target_twd"] == 500
    json.dumps(d, ensure_ascii=False)


def test_v2_decision_has_no_wait_options():
    d = batch_to_dict(batch(ok_decision(1)))["decisions"][0]
    assert d["wait_options"] == [] and d["expected"] is None and d["deadline_point"] is None
    assert d["gap_pp"] == 10 and d["tolerance_twd"] == 50


def test_v3_negative_amounts_round_half_up():
    rows = (option(0), option(1, target=50, reach=0.6, likely=1, likely_p=0.6, saving=-150, wait=0.5, cost=1000,
                               chosen=True))
    d = batch_to_dict(batch(v3_decision(1, chosen=1, wait_options=rows)))["decisions"][0]
    assert (d["expected"]["expected_saving_twd"], d["expected"]["net_twd"]) == (-1, -11)


def test_v3_buy_now_uses_the_best_waiting_row_as_sweet_price():
    d = v3_decision(1, chosen=0)
    assert d.group == "now" and d.expected.deadline_index == 0 and d.deadline_point is None
    assert d.sweet_point.index == d.wait_options[2].likely_index


def test_v3_target_may_be_deeper_than_p_min():
    d = v3_decision(1, p_min_pct=40, p_min_cents=30000)
    assert d.sweet_pct > d.p_min_pct


@pytest.mark.parametrize("change", [
    dict(group="now"),                     # the chosen row is not the buy-now row
    dict(deadline_point=None),             # waiting needs a deadline
    dict(sweet_point=PTS4[0]),             # sweet timing != expected.likely_index
])
def test_invalid_v3_decisions_are_rejected(change):
    with pytest.raises(ValueError):
        v3_decision(1, **change)


def test_v3_expected_must_be_the_chosen_row():
    rows = v3_rows(2)
    with pytest.raises(ValueError):
        v3_decision(1, chosen=2, wait_options=rows, expected=rows[1])


def test_v3_exactly_one_chosen_row():
    rows = (option(0), option(1, chosen=True), option(2, target=60, reach=0.9, likely=2, likely_p=0.7, chosen=True))
    with pytest.raises(ValueError, match="恰好一列"):
        v3_decision(1, chosen=2, wait_options=rows, expected=rows[2])


def test_v3_buy_now_needs_the_now_row_chosen():
    d = v3_decision(1, chosen=0)
    assert d.group == "now"
    with pytest.raises(ValueError):
        v3_decision(1, chosen=0, group="soon", deadline_point=PTS4[1])
