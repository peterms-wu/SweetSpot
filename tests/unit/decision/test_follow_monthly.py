"""Following the advice with monthly re-evaluation, and the net benefit (005 research R6; spec FR-010, FR-011;
tasks T021; SC-003). Every case is computed by hand.

Analysis times are the 1st of each month from 2025-02-01; t0 = 2025-02-01, 12 months later = 2026-02-01.
"""

from types import SimpleNamespace

import pytest

from sweetspot.decision.backtest import (EVALUATION_COSTS, MonthlyScore, case_rows, evaluation_costs,
                                         follow_advice_monthly, net_summary)
from sweetspot.timeutil import add_months
from tests.forecast_builders import dt
from tests.unit.decision.test_follow_advice import series

T0 = dt("2025-02-01")
SCHEDULE = tuple(add_months(T0, k) for k in range(20))
MONTH = 365 / 12


def d(group="wait", pct=50):
    return SimpleNamespace(group=group, sweet_pct=pct)


def monthly(s, decisions, now=50000, t0=T0):
    return follow_advice_monthly(s, t0, SCHEDULE, decisions, now_price_cents=now)


def test_buy_now_at_t0():
    assert monthly(series(("2025-03-14", 80)), {T0: d("now")}) == MonthlyScore(0, 0, False, 0)


def test_reached_between_two_analysis_times():
    s = series(("2025-02-20", 60), ("2025-03-10", 0))
    assert monthly(s, {T0: d("wait", 50)}) == MonthlyScore(30000, 19, False, 0)


def test_the_next_decision_changes_the_target():
    # t0 waits for -70%; on 2025-03-01 the new decision waits for -40%, reached on 2025-03-14 at -40%
    s = series(("2025-03-14", 40), ("2025-03-20", 0), ("2025-06-01", 70))
    decisions = {T0: d("wait", 70), SCHEDULE[1]: d("soon", 40)}
    assert monthly(s, decisions) == MonthlyScore(20000, 41, False, 1)


def test_the_next_decision_buys_now_at_that_price():
    # a -30% sale runs from 2025-02-25; on 2025-03-01 the decision is "now": paid NT$350, 28 days
    s = series(("2025-02-25", 30), ("2025-03-10", 0))
    decisions = {T0: d("wait", 50), SCHEDULE[1]: d("now")}
    assert monthly(s, decisions) == MonthlyScore(15000, 28, False, 1)


def test_a_missing_decision_keeps_the_previous_one():
    s = series(("2025-04-14", 50), ("2025-04-20", 0))
    decisions = {T0: d("wait", 50)}                   # every later analysis time has no decision
    assert monthly(s, decisions) == MonthlyScore(25000, 72, False, 2)


def test_never_bought_within_twelve_months():
    s = series(("2025-06-27", 30), ("2025-07-10", 0), ("2026-01-20", 20))
    score = monthly(s, {T0: d("wait", 50)})
    assert score == MonthlyScore(50000 - 40000, 365, False, 11)


def test_censored_when_the_data_ends_before_the_next_check():
    s = series(("2025-03-03", 30), known="2025-05-15")
    assert monthly(s, {T0: d("wait", 50)}).censored is True
    reached = series(("2025-04-10", 50), known="2025-05-15")
    assert monthly(reached, {T0: d("wait", 50)}) == MonthlyScore(25000, 68, False, 2)


def test_a_crossing_after_the_known_data_is_not_used():
    s = series(("2025-06-10", 50), known="2025-05-15")
    assert monthly(s, {T0: d("wait", 50)}).censored is True


def test_the_last_analysis_time_holds_until_twelve_months():
    t0 = SCHEDULE[-2]                                 # only one later analysis time
    s = series(("2026-12-01", 50), known="2027-12-01")
    score = monthly(s, {t0: d("wait", 50)}, t0=t0)
    assert score.saving_cents == 25000 and score.wait_days == (dt("2026-12-01") - t0).days


def test_evaluation_costs():
    assert EVALUATION_COSTS == (0, 10, 20, 30, 50, 80)
    assert evaluation_costs(20) == [0, 10, 20, 30, 50, 80]
    assert evaluation_costs(35) == [0, 10, 20, 30, 35, 50, 80]
    assert evaluation_costs(None) == [0, 10, 20, 30, 50, 80]


def test_net_summary_by_hand():
    # saving NT$300 after 0 days, NT$100 after 73 days (2.4 months), NT$-50 after 365 days (12 months)
    scores = [MonthlyScore(30000, 0, False, 0), MonthlyScore(10000, 73, False, 0), MonthlyScore(-5000, 365, False, 0),
              MonthlyScore(None, None, True, 0)]
    out = {row["cost_twd"]: row for row in net_summary(scores, [0, 20])}
    assert out[0] == {"cost_twd": 0, "mean": pytest.approx(350 / 3), "median": 100, "p25": -50, "p75": 300}
    nets = [300.0, 100 - 20 * 73 / MONTH, -50 - 20 * 12]
    assert out[20]["mean"] == pytest.approx(sum(nets) / 3)
    assert out[20]["median"] == pytest.approx(round(sorted(nets)[1], 2))
    assert net_summary([MonthlyScore(None, None, True, 0)], [0]) == [
        {"cost_twd": 0, "mean": None, "median": None, "p25": None, "p75": None}]


def test_case_rows_are_sorted_and_skip_censored():
    rows = case_rows({("monthly", 2, T0): MonthlyScore(100, 3, False, 0),
                      ("fixed", 1, T0): MonthlyScore(200, 4, False, 0),
                      ("monthly", 1, T0): MonthlyScore(None, None, True, 0)})
    assert rows == [[1, "2025-02-01", "fixed", 200, 4], [2, "2025-02-01", "monthly", 100, 3]]
