"""Rule backtest decisions never see anything after as_of (tasks T032; contracts/rule-backtest-result.md 2).

Same tampered databases as feature 002's leak test. The test proves it can catch a leak: reading the price state at
the end of the series instead of at as_of is detected.
"""

import pytest

from sweetspot.config import Preferences
from sweetspot.decision import backtest
from sweetspot.decision.backtest import decisions_at
from sweetspot.forecast.engine import all_apps, load_games
from sweetspot.forecast.evidence import population_view
from sweetspot.forecast.models import build_model
from sweetspot.forecast.salepoints import sale_points
from sweetspot.store.query import PriceStore
from tests.contract.test_no_future_leak import AS_OF, build
from tests.forecast_builders import dt


def decisions(path, name="seasonal-freq", params=None, rule=None):
    store = PriceStore.open(path)
    try:
        games = load_games(store, all_apps(store), dt("2026-09-25"))
        events = store.calendar_events()
    finally:
        store.close()
    points = sale_points([e for e in events if e.start <= AS_OF], AS_OF)
    model = build_model(name, {"min_sales": 2} if params is None else params)
    apps = sorted(a for a, g in games.items() if "TW" in g.series)
    model.prepare(population_view((games[a] for a in apps), AS_OF, "TW"))
    return decisions_at(games, apps, AS_OF, points, model, Preferences(), rule)


def test_tampering_after_as_of_changes_no_decision(tmp_path):
    a = decisions(build(tmp_path / "a" / "sweetspot.db", False))
    b = decisions(build(tmp_path / "b" / "sweetspot.db", True))
    assert a and all(not isinstance(v, str) for v in a.values())
    assert a == b


@pytest.mark.parametrize("rule", ["1.0.0", "2.0.0"])
def test_the_new_model_and_rule_leak_nothing(tmp_path, rule):
    """004 tasks T027: seasonal-record × both rule versions."""
    params = {"min_sales": 1, "half_life": 2, "hazard_history": "TW+US"}
    a = decisions(build(tmp_path / "a" / "sweetspot.db", False), "seasonal-record", params, rule)
    b = decisions(build(tmp_path / "b" / "sweetspot.db", True), "seasonal-record", params, rule)
    assert a and all(not isinstance(v, str) for v in a.values())
    assert a == b


def test_the_leak_test_catches_a_peek(tmp_path, monkeypatch):
    a_path = build(tmp_path / "a" / "sweetspot.db", False)
    b_path = build(tmp_path / "b" / "sweetspot.db", True)
    monkeypatch.setattr(backtest, "current_state", lambda series, as_of: series.states[-1])
    assert decisions(a_path) != decisions(b_path)


def test_rule_three_leaks_nothing(tmp_path):
    """005 tasks T012: the waiting-cost rule, down to every cent of the waiting table."""
    params = {"min_sales": 1, "half_life": 2, "hazard_history": "TW+US"}
    a = decisions(build(tmp_path / "a" / "sweetspot.db", False), "seasonal-record", params, "3.0.0")
    b = decisions(build(tmp_path / "b" / "sweetspot.db", True), "seasonal-record", params, "3.0.0")
    assert a and all(not isinstance(v, str) for v in a.values())
    assert all(v.wait_options for v in a.values())
    assert a == b


def games_of(path):
    store = PriceStore.open(path)
    try:
        return load_games(store, all_apps(store), dt("2026-09-25"))
    finally:
        store.close()


def test_monthly_scoring_uses_later_prices_but_decisions_do_not(tmp_path):
    """005 tasks T027: at t0 the decision is the same on both databases; only the monthly score differs."""
    from sweetspot.decision.backtest import follow_advice_monthly
    from sweetspot.timeutil import add_months

    params = {"min_sales": 1, "half_life": 2, "hazard_history": "TW+US"}
    paths = build(tmp_path / "a" / "sweetspot.db", False), build(tmp_path / "b" / "sweetspot.db", True)
    a, b = (decisions(p, "seasonal-record", params, "3.0.0") for p in paths)
    assert a == b
    schedule = [add_months(AS_OF, k) for k in range(13)]
    scores = []
    for path, decided in zip(paths, (a, b)):
        games = games_of(path)
        out = {}
        for app, d in decided.items():
            state = games[app].series["TW"].state_at(AS_OF)
            out[app] = follow_advice_monthly(games[app].series["TW"], AS_OF, schedule, {AS_OF: d},
                                             now_price_cents=state.regular_cents * (100 - state.cut) // 100)
        scores.append(out)
    assert scores[0] != scores[1]                      # the tampered future is only seen by the scoring


def test_a_peeking_rule_three_decision_is_caught(tmp_path, monkeypatch):
    params = {"min_sales": 1, "half_life": 2, "hazard_history": "TW+US"}
    a_path = build(tmp_path / "a" / "sweetspot.db", False)
    b_path = build(tmp_path / "b" / "sweetspot.db", True)
    monkeypatch.setattr(backtest, "current_state", lambda series, as_of: series.states[-1])
    assert decisions(a_path, "seasonal-record", params, "3.0.0") != decisions(b_path, "seasonal-record", params,
                                                                                "3.0.0")
