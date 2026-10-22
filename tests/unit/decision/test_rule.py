"""Sweet-price rule `decide()` on synthetic curves, each case with hand-computed values (tasks T007; SC-001).

Money is in cents. The curves come from tests.decision_builders: per-sale shares, cumulative 1 - (1 - p)^k.
"""

from dataclasses import replace

import pytest

from sweetspot.config import Preferences
from sweetspot.decision.rule import CURRENT_RULE, RULE_NAME, RULE_VERSION, RULES, DecisionError, decide
from sweetspot.forecast.contract import LEVELS
from tests.decision_builders import AS_OF, curve_from_shares, points

PREFS = Preferences()
POPULATION = {50: 0.6, 75: 0.3, 90: 0.05}         # a no-history curve shaped like the population share


def run(spec, *, regular, current=None, confidence="normal", max_cut=None, mismatch=False, prefs=PREFS,
        n_points=20, no_history=None, pts=None, probabilities=None):
    pts = pts or points(n_points)
    probs = probabilities or curve_from_shares(spec, len(pts))
    nh = curve_from_shares(no_history, len(pts)) if no_history is not None else None
    if max_cut is None:
        max_cut = max((lv for lv, p in spec.items() if p > 0), default=0)
    return decide(probabilities=probs, points=pts, as_of=AS_OF, confidence=confidence, evidence_max_cut=max_cut,
                  regular_cents=regular, current_price_cents=current, regular_mismatch=mismatch, no_history=nh,
                  preferences=prefs, rule="1.0.0")        # the 003 scenarios are about rule 1.0.0


def test_rule_identity():
    assert RULE_NAME == "sweet-price" and RULE_VERSION == CURRENT_RULE
    assert RULES["1.0.0"]["constants"] == {"p_min_threshold": 0.5, "timing_threshold": 0.5,
                                           "low_confidence_months": 12, "stale_hours": 24}


def test_case1_normal_ten_points():
    # NT$990, P_min -60% (NT$396); 10pp = NT$99 → target NT$495 → -50% (NT$495) reached at the next sale
    r = run({50: 1.0, 60: 1 / 7}, regular=99000, current=99000)
    assert (r.p_min_pct, r.p_min_cents, r.gap_pp) == (60, 39600, 10)
    assert (r.tolerance_cents, r.tolerance_bound) == (9900, None)
    assert (r.target_cents, r.sweet_pct, r.sweet_cents) == (49500, 50, 49500)
    assert (r.sweet_index, r.sweet_probability, r.group) == (1, 1.0, "soon")
    assert (r.confidence, r.basis, r.horizon_points) == ("normal", "own", 20)


def test_case2_tolerance_floor():
    # NT$300, P_min -80% (NT$60); 5pp = NT$15 < NT$30 floor → target NT$90 → -70%
    r = run({70: 1.0, 80: 1 / 7}, regular=30000, current=30000)
    assert (r.p_min_pct, r.gap_pp, r.tolerance_cents, r.tolerance_bound) == (80, 5, 3000, "min")
    assert (r.sweet_pct, r.sweet_cents, r.sweet_index, r.group) == (70, 9000, 1, "soon")
    assert "tolerance-min" in r.tags


def test_case3_tolerance_cap():
    # NT$1,599, P_min -70% (NT$479.7); 10pp = NT$159.9 > NT$100 cap → target NT$579.7 → -65% (NT$559.65)
    r = run({65: 1.0, 70: 1 / 7}, regular=159900, current=159900)
    assert (r.p_min_pct, r.gap_pp, r.tolerance_cents, r.tolerance_bound) == (70, 10, 10000, "max")
    assert (r.sweet_pct, r.sweet_cents) == (65, 55965)
    assert "tolerance-max" in r.tags


@pytest.mark.parametrize("p_min, gap", [(70, 10), (75, 5)])
def test_case4_gap_boundary(p_min, gap):
    r = run({p_min: 1.0}, regular=60000)
    assert (r.p_min_pct, r.gap_pp) == (p_min, gap)


def test_case5_probability_exactly_half_counts():
    # NT$200, P_min -50% (0.5 per sale); tol = NT$30 floor → target NT$130 → -35%; P(≥35) = 0.5 at the next sale
    r = run({50: 0.5}, regular=20000)
    assert (r.p_min_pct, r.sweet_pct, r.sweet_index, r.sweet_probability) == (50, 35, 1, 0.5)


def test_case6_low_confidence_uses_twelve_months():
    # 4 sales end within 12 months of 2026-09-25; over 20 sales -90% would reach 0.64, over 4 only 0.19
    r = run(POPULATION, regular=40000, confidence="low")
    assert (r.horizon_points, r.p_min_pct, r.group, r.confidence) == (4, 75, "low", "low")
    assert "low-confidence" in r.tags
    normal = run(POPULATION, regular=40000)
    assert (normal.horizon_points, normal.p_min_pct) == (20, 90)


def test_case7_zero_p_min_falls_back_to_the_no_history_curve():
    r = run({}, regular=169000, current=169000, max_cut=0, no_history=POPULATION)
    assert (r.basis, r.confidence, r.group, r.horizon_points, r.p_min_pct) == ("no-history", "low", "low", 4, 75)
    assert {"no-history-curve", "low-confidence"} <= set(r.tags)


def test_case7_zero_p_min_without_a_no_history_curve_is_an_error():
    with pytest.raises(DecisionError, match="沒有本身歷史"):
        run({}, regular=169000, max_cut=0, no_history=None)


def test_case8_regular_price_inside_tolerance_is_not_buy_now():
    # NT$369, P_min -10% (NT$332.1); 10pp = NT$36.9 → target NT$369 exactly; the sweet price is -5% (NT$350.55)
    r = run({10: 1.0}, regular=36900, current=36900)
    assert (r.p_min_pct, r.tolerance_cents, r.target_cents) == (10, 3690, 36900)
    assert (r.sweet_pct, r.sweet_cents, r.group) == (5, 35055, "soon")
    assert run({10: 1.0}, regular=36900, current=33210).group == "now"


def test_case9_group_order():
    low_now = run(POPULATION, regular=40000, current=8000, confidence="low")      # -80% ≤ sweet (-70%)
    assert low_now.group == "now" and "low-confidence" in low_now.tags
    mismatch = run({50: 1.0, 60: 1 / 7}, regular=99000, current=99000, mismatch=True)
    assert (mismatch.confidence, mismatch.group) == ("low", "low") and "regular-mismatch" in mismatch.tags
    later = run({45: 1.0, 50: 0.3}, regular=300000, current=300000)   # cap → target is P_min itself
    assert (later.sweet_pct, later.sweet_index, later.group) == (50, 2, "wait")   # 1 - 0.7^2 = 0.51
    assert run({45: 1.0, 50: 0.3}, regular=300000, prefs=replace(PREFS, soon_sales=2)).group == "soon"
    unknown = run({10: 1.0}, regular=36900, current=None)
    assert unknown.group == "soon" and "price-unknown" in unknown.tags


def test_case10_waiting_ladder():
    # NT$860, -65% every sale, -85% in 1 of 7: target -80% is first ≥ 0.5 at the 5th sale (1 - (6/7)^5 = 0.537)
    r = run({65: 1.0, 85: 1 / 7}, regular=86000, current=86000)
    assert (r.p_min_pct, r.sweet_pct, r.sweet_index, r.group) == (85, 80, 5, "wait")
    assert [(row.index, row.pct) for row in r.ladder] == [(1, 65), (2, 65), (3, 65), (4, 65), (5, 85)]
    assert r.ladder[0].cents == 30100 and r.ladder[-1].cents == 12900
    assert r.ladder[-1].index == r.sweet_index
    assert r.ladder[0].probability == 1.0
    buy_now = run({65: 1.0, 85: 1 / 7}, regular=86000, current=12000)
    assert buy_now.group == "now" and len(buy_now.ladder) >= 1


def test_case11_tags_deeper_possible_and_below_history():
    r = run({50: 1.0, 65: 1 / 7}, regular=100000, current=30000, max_cut=67)
    assert r.p_min_pct == 65 and "deeper-possible" in r.tags        # 67 floors to the 65 level
    assert "below-history" in r.tags                                 # NT$300 < P_min price NT$350
    assert "deeper-possible" not in run({50: 1.0, 65: 1 / 7}, regular=100000, max_cut=80).tags


def test_case12_preferences_change_the_result():
    r = run({70: 1.0, 80: 1 / 7}, regular=30000, prefs=replace(PREFS, tolerance_min_twd=0))
    assert (r.tolerance_cents, r.sweet_pct, r.sweet_index, r.group) == (1500, 75, 5, "wait")


def test_case13_integer_boundaries_are_exact():
    r = run({10: 1.0}, regular=36900, current=35055)                 # exactly the sweet price
    assert r.group == "now"
    assert run({10: 1.0}, regular=36900, current=35056).group == "soon"


def test_case14_unreachable_timing_is_an_error():
    pts = points(3)
    bad = tuple(tuple(0.9 if d == 50 else 0.1 for d in LEVELS) for _ in pts)   # not monotone in level
    with pytest.raises(DecisionError):
        run({}, regular=100000, pts=pts, probabilities=bad)


def test_case15_low_confidence_without_sales_in_twelve_months_is_an_error():
    late = points(8, first_year=2028)
    with pytest.raises(DecisionError, match="未來 12 個月內沒有季節特賣"):
        run(POPULATION, regular=40000, confidence="low", pts=late)
