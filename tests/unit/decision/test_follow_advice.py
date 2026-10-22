"""Following the advice vs buying at once; hindsight; sweet-sale spread (004 research R6; spec FR-020, FR-021;
tasks T025). Every case is computed by hand. AS_OF 2025-02-01, 12 months later = 2026-02-01."""

import pytest

from sweetspot.decision.backtest import FollowScore, RuleMetrics, follow_advice, sweet_timing_bucket
from sweetspot.forecast.series import PriceSeries, PriceState
from tests.forecast_builders import dt
from tests.unit.decision.test_rule_backtest import AS_OF, POINTS, result


def series(*changes, known="2026-06-01", regular=50000, start_cut=0):
    """(time, cut) or (time, cut, regular) after a tracking start at NT$500 regular."""
    states = [PriceState(dt("2024-12-11"), start_cut, True, regular)]
    states += [PriceState(dt(c[0]), c[1], False, c[2] if len(c) > 2 else regular) for c in changes]
    return PriceSeries("TW", tuple(states), dt(known))


def follow(s, r, now=50000):
    return follow_advice(s, AS_OF, r, now_price_cents=now)


def test_buy_now():
    assert follow(series(("2025-03-14", 80)), result("now")) == FollowScore(0, 0, False, 40000)


def test_buy_when_the_price_first_reaches_the_sweet_level():
    # -60% on 2025-03-03 (30 days later) when the sweet level is -50%: paid NT$500 × 40% = NT$200
    s = series(("2025-03-03", 60), ("2025-03-10", 0), ("2025-07-01", 80), ("2025-07-10", 0))
    assert follow(s, result("wait", 50)) == FollowScore(30000, 30, False, 40000)


def test_price_is_floored_to_the_cent():
    s = series(("2025-03-03", 33, 33333))
    assert follow(s, result("soon", 30)).saving_cents == 50000 - 33333 * 67 // 100


def test_never_reached_buys_at_the_price_twelve_months_later():
    s = series(("2025-06-27", 30), ("2025-07-10", 0), ("2026-01-20", 20))
    score = follow(s, result("wait", 50))
    assert score == FollowScore(50000 - 40000, 365, False, 50000 - 35000)


def test_short_data_without_reaching_is_censored():
    assert follow(series(("2025-03-03", 30), known="2025-08-20"), result("wait", 50)) == FollowScore(None, None, True,
                                                                                                    None)


def test_short_data_already_reached_counts():
    s = series(("2025-05-12", 50), known="2025-08-20")
    assert follow(s, result("wait", 50)) == FollowScore(25000, 100, False, None)


def test_a_price_rise_can_make_waiting_cost_money():
    s = series(("2025-04-01", 0, 60000), ("2025-06-01", 10, 60000))       # regular up to NT$600, -10% = NT$540
    score = follow(s, result("wait", 50))
    assert score.saving_cents == 50000 - 54000 and score.wait_days == 365


def test_sweet_timing_buckets():
    assert sweet_timing_bucket(result(sweet_index=1), POINTS, AS_OF) == "next"
    assert sweet_timing_bucket(result(sweet_index=4), POINTS, AS_OF) == "within_1y"     # ends 2026-01-05
    assert sweet_timing_bucket(result(sweet_index=5), POINTS, AS_OF) == "beyond_1y"     # ends 2026-03-26


def test_aggregation():
    m = RuleMetrics()
    from sweetspot.decision.backtest import CaseScore

    m.add("normal", "now", CaseScore("now", None, None), follow=FollowScore(0, 0, False, 40000), timing="next")
    m.add("normal", "wait", CaseScore("hit", 0, None), follow=FollowScore(30000, 30, False, 40000),
          timing="within_1y")
    m.add("low", "low", CaseScore("miss", None, None), follow=FollowScore(-4000, 365, False, 15000),
          timing="within_1y")
    m.add("normal", "wait", CaseScore("censored", None, None), follow=FollowScore(None, None, True, None),
          timing="beyond_1y")
    r = m.result()
    assert r["sweet_timing"] == {"next": 1, "within_1y": 2, "beyond_1y": 1}
    overall = r["follow_advice"]["overall"]
    assert (overall["evaluated"], overall["censored"]) == (3, 1)
    assert overall["saving_twd"] == {"mean": pytest.approx(86.67, abs=0.01), "median": 0, "p75": 300, "p90": 300}
    assert overall["wait_days"] == {"mean": pytest.approx(131.67, abs=0.01), "median": 30}
    groups = {g["group"]: g for g in r["follow_advice"]["by_group"]}
    assert groups["wait"]["evaluated"] == 1 and groups["wait"]["censored"] == 1
    assert groups["low"]["saving_twd"]["median"] == -40
    conf = {g["group"]: g for g in r["follow_advice"]["by_confidence"]}
    assert conf["normal"]["evaluated"] == 2 and conf["low"]["evaluated"] == 1
    assert r["hindsight"] == {"evaluated": 3, "saving_twd": {"mean": pytest.approx(316.67, abs=0.01), "median": 400}}
