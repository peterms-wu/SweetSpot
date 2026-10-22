"""Rule versions: `sweet-price` 2.0.0 looks 12 months ahead for every game (004 research R5; tasks T023)."""

import pytest

from sweetspot.decision.rule import CONSTANTS, CURRENT_RULE, RULES, decide
from tests.decision_builders import AS_OF, curve_from_shares, points
from tests.unit.decision.test_rule import PREFS

# 5 years: P(≥ -85%) = 1 − 0.96^20 = 0.56 → P_min -85%. Within 12 months (4 sales): P(≥ -85%) = 0.15 and
# P(≥ -75%) = 1 − 0.6^4 = 0.87 → P_min -75%.
SPEC = {50: 1.0, 75: 0.4, 85: 0.04}


def run(rule, *, confidence="normal", regular=100000, current=100000):
    pts = points(20)
    return decide(probabilities=curve_from_shares(SPEC, 20), points=pts, as_of=AS_OF, confidence=confidence,
                  evidence_max_cut=85, regular_cents=regular, current_price_cents=current, regular_mismatch=False,
                  no_history=None, preferences=PREFS, rule=rule)


def test_rule_registry():
    assert set(RULES) == {"1.0.0", "2.0.0", "2.1.0", "3.0.0", "3.1.0"}
    assert RULES["1.0.0"]["constants"] == {"p_min_threshold": 0.5, "timing_threshold": 0.5, "low_confidence_months": 12,
                                           "stale_hours": 24}
    assert CONSTANTS == RULES[CURRENT_RULE]["constants"]
    assert "p_min_months" not in RULES["1.0.0"]["constants"]
    assert RULES["2.0.0"]["constants"] == {"p_min_threshold": 0.5, "timing_threshold": 0.5, "low_confidence_months": 12,
                                           "stale_hours": 24, "p_min_months": 12}


def test_version_2_looks_twelve_months_ahead_for_normal_confidence():
    r = run("2.0.0")
    assert r.rule == "2.0.0" and r.horizon_points == 4
    # P_min -75% (NT$250); 5pp = NT$50 → target NT$300 → -70% (NT$300), P(≥ -70%) = 0.4, 0.64 → the 2nd sale
    assert (r.p_min_pct, r.gap_pp, r.tolerance_cents) == (75, 5, 5000)
    assert (r.sweet_pct, r.sweet_cents, r.sweet_index, r.group) == (70, 30000, 2, "wait")
    assert r.sweet_index <= r.horizon_points


def test_version_1_still_looks_five_years_ahead():
    r = run("1.0.0")
    assert r.rule == "1.0.0" and r.horizon_points == 20
    # P_min -85% (NT$150) + NT$50 → NT$200 → -80%, P(≥ -80%) = 1 − 0.96^k ≥ 0.5 first at k = 17
    assert (r.p_min_pct, r.sweet_pct, r.sweet_index) == (85, 80, 17)


def test_low_confidence_is_the_same_in_both_versions():
    a, b = run("1.0.0", confidence="low"), run("2.0.0", confidence="low")
    assert (a.p_min_pct, a.sweet_pct, a.sweet_index, a.horizon_points) == \
        (b.p_min_pct, b.sweet_pct, b.sweet_index, b.horizon_points)


def test_default_is_the_current_rule():
    assert run(None).rule == CURRENT_RULE


def test_unknown_rule_version():
    with pytest.raises(ValueError, match="9.9.9"):
        run("9.9.9")
