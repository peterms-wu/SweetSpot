"""Rules 2.1.0 and 3.1.0 (feature 006 spec FR-010, FR-018; research R5): 2.0.0 / 3.0.0 plus one data-quality
condition, "the price history stopped updating" → low confidence. Identical whenever the flag is false."""

import random
from dataclasses import asdict

import pytest

from sweetspot.config import Preferences
from sweetspot.decision.rule import CURRENT_RULE, RULES, DecisionError, decide
from tests.decision_builders import AS_OF, curve_from_shares, points


def random_cases(seed: int, n: int = 300):
    rng = random.Random(seed)
    levels = [50, 60, 70, 75, 80, 85, 90]
    for _ in range(n):
        chosen = sorted(rng.sample(levels, rng.randint(1, 4)))
        spec = {lv: round(rng.uniform(0.02, 1.0) / (i + 1), 3) for i, lv in enumerate(chosen)}
        regular = rng.choice([18800, 30000, 67000, 159900])
        current = rng.choice([None, regular, regular * rng.randint(10, 90) // 100])
        yield dict(probabilities=curve_from_shares(spec, 20), points=points(20), as_of=AS_OF,
                   confidence=rng.choice(["normal", "low"]), evidence_max_cut=max(chosen), regular_cents=regular,
                   current_price_cents=current, regular_mismatch=rng.random() < 0.2,
                   no_history=curve_from_shares({50: 0.5, 80: 0.1}, 20))


def outcome(rule, case, prefs, **kw):
    try:
        result = asdict(decide(**case, preferences=prefs, rule=rule, **kw))
    except DecisionError as exc:
        return ("error", str(exc))
    result.pop("rule")
    return result


@pytest.mark.parametrize("old,new,prefs", [
    ("2.0.0", "2.1.0", Preferences()),
    ("3.0.0", "3.1.0", Preferences(wait_cost_twd=20)),
])
def test_identical_to_the_previous_version_without_the_flag(old, new, prefs):
    for case in random_cases(seed=20260926):
        assert outcome(new, case, prefs) == outcome(old, case, prefs)
        assert outcome(new, case, prefs, history_stopped=False) == outcome(old, case, prefs)


def first_normal(rule, prefs):
    for case in random_cases(seed=7):
        result = outcome(rule, case, prefs)
        if isinstance(result, dict) and result["confidence"] == "normal":
            return case
    raise AssertionError("no normal-confidence case")


@pytest.mark.parametrize("rule,prefs", [("2.1.0", Preferences()), ("3.1.0", Preferences(wait_cost_twd=20))])
def test_stopped_history_makes_the_decision_low_confidence(rule, prefs):
    case = first_normal(rule, prefs)
    r = decide(**case, preferences=prefs, rule=rule, history_stopped=True)
    assert r.confidence == "low" and "history-stopped" in r.tags and "low-confidence" in r.tags
    assert r.group in ("now", "low")


@pytest.mark.parametrize("rule", ["2.0.0", "3.0.0"])
def test_older_versions_ignore_the_flag(rule):
    prefs = Preferences(wait_cost_twd=20)
    for case in random_cases(seed=3, n=50):
        assert outcome(rule, case, prefs, history_stopped=True) == outcome(rule, case, prefs)


def test_registry_and_current_rule():
    assert CURRENT_RULE == "2.1.0"
    assert RULES["2.1.0"]["constants"] == {**RULES["2.0.0"]["constants"], "history_stopped_low": True}
    assert RULES["3.1.0"]["constants"] == {**RULES["3.0.0"]["constants"], "history_stopped_low": True}
    assert RULES["2.1.0"]["kind"] == "tolerance" and RULES["3.1.0"]["kind"] == "wait-cost"
    assert Preferences().for_rule("2.1.0") == Preferences().for_rule("2.0.0")
    assert Preferences().for_rule("3.1.0") == Preferences().for_rule("3.0.0")


def test_current_rule_quotes_backtest_figures():
    from sweetspot.decision.rule import lookup_backtest

    model = {"name": "seasonal-record", "version": "1.0.0",
             "params": {"min_sales": 1, "half_life": 2, "hazard_history": "TW+US"}}
    now, old = lookup_backtest("2.1.0", model), lookup_backtest("2.0.0", model)
    assert now is not None and now["hit_rate"] == old["hit_rate"]
    assert now["now_deeper_within_12m"] == old["now_deeper_within_12m"]
