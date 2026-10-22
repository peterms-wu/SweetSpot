"""Rule `sweet-price` 3.0.0: waiting cost (005 research R1-R4; tasks T008; SC-001, SC-002).

Hand-computed example used below (regular = current = NT$1,000; c = NT$20 a month):

- sale 1 starts 1.0 and ends 1.5 months after as_of; sale 2 starts 4.0 and ends 4.5 months after as_of
- P(>= -50%) is 0.6 by sale 1 and 0.9 by sale 2; nothing deeper than -50%

Waiting at most until sale 2 for -50%: expected price 0.6 x 500 + 0.3 x 500 + 0.1 x 1,000 = NT$550, so the expected
saving is NT$450; expected wait 0.6 x 1.0 + 0.3 x 4.0 + 0.1 x 4.5 = 2.25 months, cost NT$45, net NT$405.
Only until sale 1: price 0.6 x 500 + 0.4 x 1,000 = NT$700, saving NT$300; wait 0.6 x 1.0 + 0.4 x 1.5 = 1.2 months,
cost NT$24, net NT$276.
"""

import random

import pytest

from sweetspot.decision.rule import (CONSTANTS, CURRENT_RULE, RULES, DecisionError, decide, option_value,
                                     price_cents)
from sweetspot.forecast.contract import LEVELS
from tests.decision_builders import AS_OF, curve_from_shares, prefs, step_curve, timed_points

PTS = timed_points(AS_OF, [(1.0, 1.5), (4.0, 4.5)])
CURVE = step_curve([{50: 0.6}, {50: 0.9}])


def run(curve=CURVE, points=PTS, *, confidence="normal", regular=100000, current=100000, c=20, no_history=None,
        mismatch=False, max_cut=50, **pref):
    return decide(probabilities=curve, points=points, as_of=AS_OF, confidence=confidence, evidence_max_cut=max_cut,
                  regular_cents=regular, current_price_cents=current, regular_mismatch=mismatch,
                  no_history=no_history, preferences=prefs(wait_cost_twd=c, **pref), rule="3.0.0")


def test_registry():
    assert set(RULES) == {"1.0.0", "2.0.0", "2.1.0", "3.0.0", "3.1.0"}
    assert RULES["3.0.0"]["kind"] == "wait-cost" and RULES["3.0.0"]["p_min_months"] == 12
    assert RULES["3.0.0"]["constants"] == {"p_min_threshold": 0.5, "timing_threshold": 0.5,
                                           "low_confidence_months": 12, "stale_hours": 24, "p_min_months": 12,
                                           "miss_price": "regular", "month_days": 365 / 12}
    assert CURRENT_RULE == "2.1.0" and CONSTANTS == RULES["2.1.0"]["constants"]      # feature 006


def test_expected_values_by_hand():
    r = run()
    rows = {o.deadline_index: o for o in r.wait_options}
    assert [o.deadline_index for o in r.wait_options] == [0, 1, 2]
    one, two = rows[1], rows[2]
    assert (one.target_pct, one.target_cents, one.reach_probability) == (50, 50000, pytest.approx(0.6))
    assert (one.expected_saving_cents, one.wait_cost_cents, one.net_cents) == (30000, 2400, 27600)
    assert one.expected_wait_months == pytest.approx(1.2)
    assert (two.target_pct, two.reach_probability) == (50, pytest.approx(0.9))
    assert (two.expected_saving_cents, two.wait_cost_cents, two.net_cents) == (45000, 4500, 40500)
    assert two.expected_wait_months == pytest.approx(2.25)
    assert rows[0].net_cents == 0 and rows[0].expected_saving_cents == 0 and rows[0].target_cents == 100000


def test_choice_timing_and_deadline():
    r = run()
    assert r.expected == r.wait_options[2] and r.expected.chosen and sum(o.chosen for o in r.wait_options) == 1
    assert r.deadline_index == 2
    # the most likely sale is the first one where P(>= -50%) >= 50%: sale 1 (0.6)
    assert (r.sweet_index, r.sweet_pct, r.sweet_cents, r.sweet_probability) == (1, 50, 50000, pytest.approx(0.6))
    assert (r.expected.likely_index, r.expected.likely_label) == (1, PTS[0].label)
    assert r.group == "soon" and r.wait_cost_twd == 20 and r.rule == "3.0.0"
    assert [row.index for row in r.ladder] == [1]


def test_timing_falls_back_to_the_deadline_when_never_likely():
    r = run(step_curve([{5: 0.9, 50: 0.2}, {5: 0.95, 50: 0.4}]), c=0)
    assert r.expected.target_pct == 50 and r.expected.deadline_index == 2 and r.sweet_index == 2 and r.group == "wait"
    assert r.sweet_probability == pytest.approx(0.4)


def test_net_equals_saving_minus_cost_on_every_row():
    for o in run().wait_options:
        assert o.net_cents == o.expected_saving_cents - o.wait_cost_cents


def test_same_net_picks_the_shallower_target_within_a_sale():
    # every level up to -50% has the same probability; at a price where two levels give the same net, the
    # shallower one wins. Construct: current 50,000, levels -55 and -60 both unreachable -> only negative nets.
    r = run(current=50000)
    one = next(o for o in r.wait_options if o.deadline_index == 1)
    assert one.target_pct == 55        # all targets deeper than -50% have P = 0: the shallowest loses least


def test_buy_now_when_nothing_pays():
    r = run(current=50000)            # already -50%: waiting only risks paying the regular price
    assert r.group == "now" and r.expected.deadline_index == 0 and r.deadline_index is None
    best = max((o for o in r.wait_options if o.deadline_index), key=lambda o: (o.net_cents, -o.deadline_index))
    assert best.net_cents <= 0
    # the sweet-price fields show the best waiting row (report layout, data-model.md)
    assert (r.sweet_pct, r.sweet_index) == (best.target_pct, best.likely_index)


def test_high_cost_buys_now_or_waits_for_the_next_sale_only():
    assert run(c=10000).group == "now"
    r = run(c=200)
    assert r.group == "now" or r.deadline_index == 1


def test_no_target_below_the_current_price():
    r = run(current=4000)             # already cheaper than -95%
    assert r.group == "now" and all(o.target_pct is None for o in r.wait_options if o.deadline_index)
    assert all(o.net_cents is None for o in r.wait_options if o.deadline_index)
    assert (r.sweet_cents, r.sweet_pct, r.sweet_index, r.sweet_probability) == (4000, 96, 1, None)


def test_unknown_price_uses_the_regular_price_and_never_buys_now():
    r = run(step_curve([{5: 0.9, 50: 0.01}, {5: 0.95, 50: 0.02}]), current=None, c=10000)
    assert r.group != "now" and "price-unknown" in r.tags
    assert all(o.deadline_index for o in r.wait_options)          # no buy-now row
    assert r.expected is not None and r.expected.net_cents < 0    # the best option even if it does not pay


def test_low_confidence_path():
    r = run(confidence="low")
    assert (r.group, r.confidence, r.basis) == ("low", "low", "own")
    assert "low-confidence" in r.tags


def test_no_history_path_when_nothing_is_likely():
    nh = step_curve([{50: 0.7}, {50: 0.95}])
    r = run(step_curve([{50: 0.2}, {50: 0.4}]), no_history=nh)
    assert (r.basis, r.confidence, r.group) == ("no-history", "low", "low")
    assert r.expected.reach_probability == pytest.approx(0.95)
    with pytest.raises(DecisionError):
        run(step_curve([{50: 0.2}, {50: 0.4}]), no_history=None)


def test_regular_mismatch_is_low_confidence():
    r = run(mismatch=True)
    assert r.confidence == "low" and r.group == "low" and "regular-mismatch" in r.tags


def test_no_sale_within_twelve_months():
    far = timed_points(AS_OF, [(13.0, 13.5)])
    with pytest.raises(DecisionError):
        run(step_curve([{50: 0.9}]), far)


def test_only_sales_within_twelve_months_are_options():
    pts = timed_points(AS_OF, [(1.0, 1.5), (4.0, 4.5), (11.0, 11.8), (14.0, 14.5)])
    r = run(step_curve([{50: 0.6}, {50: 0.9}, {50: 0.95}, {50: 0.99}]), pts)
    assert r.horizon_points == 3 and [o.deadline_index for o in r.wait_options] == [0, 1, 2, 3]


def test_tolerance_preferences_do_not_matter():
    a = run()
    b = run(gap_pp_shallow=50, gap_pp_deep=50, tolerance_min_twd=0, tolerance_max_twd=1)
    assert a == b
    assert (a.gap_pp, a.tolerance_cents, a.tolerance_bound, a.target_cents) == (None, None, None, None)


def test_p_min_is_reference_only():
    base = dict(probabilities=CURVE, points=PTS, as_of=AS_OF, confidence="normal", evidence_max_cut=50,
                regular_cents=100000, current_price_cents=100000, regular_mismatch=False, no_history=None,
                preferences=prefs())
    v2, v3 = decide(**base, rule="2.0.0"), decide(**base, rule="3.0.0")
    assert (v3.p_min_pct, v3.p_min_cents) == (v2.p_min_pct, v2.p_min_cents) == (50, 50000)


def test_forty_percent_chance_counts_in_proportion():
    # -80% with P 0.4 only: saving 0.4 x NT$800 - (miss pays the regular price) = NT$320 expected
    r = run(step_curve([{5: 0.9, 80: 0.4}]), timed_points(AS_OF, [(0.5, 1.0)]), c=0)
    assert r.expected.target_pct == 80 and r.expected.expected_saving_cents == 32000


def test_reproducible():
    assert run() == run()


def test_option_value_matches_the_table():
    r = run()
    o = option_value(CURVE, PTS, AS_OF, regular_cents=100000, base_cents=100000, pct=50, deadline_index=2,
                     wait_cost_twd=20)
    assert (o.expected_saving_cents, o.wait_cost_cents, o.net_cents, o.likely_index) == (45000, 4500, 40500, 1)
    assert o == r.wait_options[2].__class__(**{**r.wait_options[2].__dict__, "chosen": False})


# --- c is monotonic (SC-002) --------------------------------------------------------------------------------

def random_case(rnd):
    n = rnd.randint(1, 4)
    shares = sorted((rnd.random() ** 2 for _ in LEVELS), reverse=True)
    shares[0] = max(shares[0], 0.6)              # something is likely: the own-curve path, never no-history
    curve = tuple(tuple(1 - (1 - s) ** k for s in shares) for k in range(1, n + 1))
    starts = sorted(rnd.uniform(0.1, 11) for _ in range(n))
    pts = timed_points(AS_OF, [(s, s + rnd.uniform(0.2, 0.5)) for s in starts])
    regular = rnd.choice([17800, 49900, 99000, 199000])
    current = regular if rnd.random() < 0.7 else price_cents(regular, rnd.choice([10, 30, 50, 70]))
    return curve, pts, regular, current


def test_waiting_never_grows_with_the_cost():
    rnd = random.Random(20260926)
    for _ in range(200):
        curve, pts, regular, current = random_case(rnd)
        waits = []
        for c in (0, 10, 20, 30, 50, 80, 120):
            r = run(curve, pts, regular=regular, current=current, c=c)
            waits.append(r.expected.expected_wait_months)
            if c == 0:
                best = max(o.expected_saving_cents for o in r.wait_options if o.expected_saving_cents is not None)
                assert r.expected.expected_saving_cents == best
        assert all(a >= b - 1e-12 for a, b in zip(waits, waits[1:])), waits


def test_versions_one_and_two_are_unchanged():
    pts = timed_points(AS_OF, [(1, 1.5), (4, 4.5), (7, 7.5), (10, 10.5)])
    base = dict(probabilities=curve_from_shares({50: 1.0}, 4), points=pts, as_of=AS_OF, confidence="normal",
                evidence_max_cut=50, regular_cents=100000, current_price_cents=100000, regular_mismatch=False,
                no_history=None, preferences=prefs())
    r = decide(**base, rule="2.0.0")
    assert r.wait_options == () and r.expected is None and r.gap_pp == 10
