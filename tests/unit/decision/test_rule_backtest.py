"""Scoring the sweet-price rule against what happened (tasks T031; research R10; FR-033)."""

from sweetspot.calendar import SaleEvent
from sweetspot.decision.backtest import CaseScore, RuleMetrics, score_case
from sweetspot.decision.rule import RuleResult
from sweetspot.forecast.salepoints import SalePoint
from sweetspot.forecast.series import PriceSeries, PriceState
from tests.forecast_builders import dt

AS_OF = dt("2025-02-01")
SALES = [("spring", 2025, "2025-03-13T17:00", "2025-03-20T17:00"), ("summer", 2025, "2025-06-26T17:00", "2025-07-10T17:00"),
         ("autumn", 2025, "2025-09-29T17:00", "2025-10-06T17:00"), ("winter", 2025, "2025-12-18T18:00", "2026-01-05T18:00"),
         ("spring", 2026, "2026-03-19T17:00", "2026-03-26T17:00")]
POINTS = tuple(SalePoint(i, s, y, f"{y} {s}", dt(a), dt(b), "estimated", None) for i, (s, y, a, b) in enumerate(SALES, 1))
WINDOW = POINTS[:4]                                                # ending within 12 months of 2025-02-01
ACTUAL = {(s, y): SaleEvent(s, s, "seasonal", s, y, dt(a), dt(b), "ended", "test") for s, y, a, b in SALES}


def series(*changes, known="2026-06-01"):
    states = [PriceState(dt("2024-12-11"), 0, True, 50000)] + [PriceState(dt(t), c, False, 50000) for t, c in changes]
    return PriceSeries("TW", tuple(states), dt(known))


def result(group="wait", sweet_pct=50, sweet_index=2):
    return RuleResult(group=group, confidence="normal", basis="own", horizon_points=5, p_min_pct=sweet_pct,
                      p_min_cents=0, gap_pp=10, tolerance_cents=3000, tolerance_bound=None, target_cents=0,
                      sweet_pct=sweet_pct, sweet_cents=0, sweet_index=sweet_index, sweet_probability=0.6, ladder=(),
                      tags=())


def score(s, r, current_cut=0):
    return score_case(s, AS_OF, r, POINTS, WINDOW, ACTUAL, regular_cents=50000, current_cut=current_cut)


def test_hit_in_the_sweet_sale():
    assert score(series(("2025-06-27", 50), ("2025-07-10T17:00", 0)), result()) == CaseScore("hit", 0, None)


def test_hit_earlier_than_predicted_counts_and_timing_is_positive():
    assert score(series(("2025-03-14", 60), ("2025-03-20T17:00", 0)), result()) == CaseScore("hit", 1, None)


def test_miss_when_the_sale_ends_without_the_discount():
    assert score(series(("2025-06-27", 40), ("2025-07-10T17:00", 0)), result()) == CaseScore("miss", None, None)


def test_miss_with_a_late_crossing_has_negative_timing():
    assert score(series(("2025-09-30", 50), ("2025-10-06T17:00", 0)), result()) == CaseScore("miss", -1, None)


def test_censored_when_the_data_ends_before_the_sale_does():
    assert score(series(known="2025-07-01"), result()).outcome == "censored"


def test_sweet_sale_beyond_the_window():
    assert score(series(), result(sweet_index=5)).outcome == "beyond"


def test_buy_now_followup():
    deeper = score(series(("2025-06-27", 70), ("2025-07-10T17:00", 0)), result("now"), current_cut=50)
    assert deeper == CaseScore("now", None, (True, 10000))                  # 20 more points of NT$500
    same = score(series(("2025-06-27", 50), ("2025-07-10T17:00", 0)), result("now"), current_cut=50)
    assert same.followup == (False, 0)
    assert score(series(known="2025-12-01"), result("now")).followup is None   # not 12 months of data


def test_metrics_aggregate_by_group_and_confidence():
    m = RuleMetrics()
    m.add("normal", "soon", CaseScore("hit", 0, None))
    m.add("normal", "wait", CaseScore("hit", 1, None))
    m.add("normal", "wait", CaseScore("miss", -1, None))
    m.add("low", "low", CaseScore("miss", None, None))
    m.add("low", "low", CaseScore("censored", None, None))
    m.add("normal", "wait", CaseScore("beyond", None, None))
    m.add("normal", "now", CaseScore("now", None, (True, 4900)))
    m.add("normal", "now", CaseScore("now", None, (False, 0)))
    m.add("low", "now", CaseScore("now", None, None))
    r = m.result()
    assert r["decisions"] == {"total": 9, "now": 3, "soon": 1, "wait": 3, "low": 2, "beyond_window": 1}
    assert r["hit_rate"]["overall"] == {"group": "overall", "hits": 2, "misses": 2, "censored": 1, "rate": 0.5}
    by_group = {g["group"]: g for g in r["hit_rate"]["by_group"]}
    assert by_group["soon"]["rate"] == 1.0 and by_group["wait"]["rate"] == 0.5 and by_group["low"]["rate"] == 0.0
    by_conf = {g["group"]: g for g in r["hit_rate"]["by_confidence"]}
    assert by_conf["normal"]["rate"] == 2 / 3 and by_conf["low"]["rate"] == 0.0
    assert r["timing_error"] == {"n": 3, "mean": 0.0, "mean_abs": 2 / 3, "distribution": {"-1": 1, "0": 1, "1": 1}}
    follow = r["now_followup"]
    assert (follow["evaluated"], follow["deeper_within_12m"], follow["rate"]) == (2, 1, 0.5)
    assert follow["by_confidence"] == [{"group": "normal", "evaluated": 2, "deeper": 1}]
    assert follow["extra_saving_twd"] == {"median": 49, "p75": 49, "p90": 49}
