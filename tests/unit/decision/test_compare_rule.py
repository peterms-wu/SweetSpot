"""Side-by-side rule backtests and the wishlist difference (004 research R8; spec FR-015-FR-021; tasks T029)."""

import pytest

from sweetspot.decision.compare_rule import (CompareRuleError, compare_rule_results, format_rule_record,
                                             wishlist_diff)


def rb(*, rule="1.0.0", model="seasonal-freq", hits=(90, 10, 5), wait=(40, 10, 2), low=(10, 40, 3), now=100,
       deeper=0.49, saving=(194.4, 150, 300, 520), days=(55.0, 0), hind=(400.0, 300), timing=(80, 20, 0),
       dataset_id="d" * 64, cutoff="2026-09-25T00:00:00Z", prefs=None):
    def row(g, t):
        return {"group": g, "hits": t[0], "misses": t[1], "censored": t[2], "rate": t[0] / (t[0] + t[1])}
    return {
        "rule": {"name": "sweet-price", "version": rule, "constants": {}},
        "model": {"name": model, "version": "1.0.0", "params": {"min_sales": 2}},
        "preferences": prefs or {"gap_pp_shallow": 10},
        "dataset": {"dataset_id": dataset_id, "cutoff": cutoff, "split": {"name": "validation"}, "games": 1313},
        "decisions": {"total": 1000, "now": now, "soon": 500, "wait": 300, "low": 100, "beyond_window": 7},
        "hit_rate": {"overall": row("overall", (hits[0] + wait[0], hits[1] + wait[1], hits[2] + wait[2])),
                     "by_group": [row("soon", hits), row("wait", wait), row("low", low)],
                     "by_confidence": [row("normal", hits), row("low", low)]},
        "timing_error": {"n": 100, "mean_abs": 0.29},
        "now_followup": {"evaluated": 50, "deeper_within_12m": 25, "rate": deeper,
                         "extra_saving_twd": {"median": 49, "p75": 90, "p90": 179}},
        "sweet_timing": dict(zip(("next", "within_1y", "beyond_1y"), timing)),
        "follow_advice": {"overall": {"evaluated": 900, "censored": 100,
                                      "saving_twd": dict(zip(("mean", "median", "p75", "p90"), saving)),
                                      "wait_days": dict(zip(("mean", "median"), days))},
                          "by_group": [], "by_confidence": []},
        "hindsight": {"evaluated": 800, "saving_twd": dict(zip(("mean", "median"), hind))},
    }


def test_refuses_different_datasets_cutoffs_or_preferences():
    base = rb()
    for other, word in ((rb(dataset_id="e" * 64), "資料集"), (rb(cutoff="2026-09-01T00:00:00Z"), "截止"),
                        (rb(prefs={"gap_pp_shallow": 5}), "偏好")):
        with pytest.raises(CompareRuleError, match=word):
            compare_rule_results(base, other)


def test_side_by_side_values_and_differences():
    a = rb()
    b = rb(rule="2.0.0", model="seasonal-record", hits=(80, 20, 5), wait=(30, 20, 2), now=90, deeper=0.42,
           saving=(207.7, 160, 310, 530), days=(52.0, 0), timing=(70, 30, 0))
    rows = {r["key"]: r for r in compare_rule_results(a, b)["rows"]}
    assert rows["hit_rate.soon"]["a"] == pytest.approx(0.9) and rows["hit_rate.soon"]["b"] == pytest.approx(0.8)
    assert rows["hit_rate.soon"]["diff"] == pytest.approx(-0.1)
    assert rows["decisions.now"]["diff"] == -10
    assert rows["now_followup.rate"]["diff"] == pytest.approx(-0.07)
    assert rows["follow_advice.saving_mean"]["diff"] == pytest.approx(13.3)
    assert rows["follow_advice.wait_mean"]["diff"] == pytest.approx(-3.0)
    assert rows["sweet_timing.within_1y"]["b"] == 30
    assert rows["hindsight.saving_mean"]["a"] == 400.0
    assert {"timing_error.mean_abs", "decisions.beyond_window", "hit_rate.normal", "follow_advice.evaluated"} <= set(rows)


def decision(app, group, twd=300, pct=50, label="2026 秋特", status="ok", name=None):
    return {"app_id": app, "name": name or f"Game {app}", "group": group, "status": status, "sweet_twd": twd,
            "sweet_pct": pct, "sweet_point": {"label": label} if status == "ok" else None}


def test_wishlist_diff():
    a = {"decisions": [decision(1, "soon"), decision(2, "now"), decision(3, "wait", 200, 60, "2027 春特"),
                       decision(4, "na", status="unreleased", twd=None, pct=None), decision(5, "low")]}
    b = {"decisions": [decision(1, "wait", 250, 60, "2026 冬特"), decision(2, "now"), decision(3, "wait", 200, 60,
                                                                                         "2027 春特"),
                       decision(4, "na", status="unreleased", twd=None, pct=None), decision(5, "na",
                                                                                        status="decision-error")]}
    diff = wishlist_diff(a, b)
    assert diff["counts"]["a"] == {"now": 1, "soon": 1, "wait": 1, "low": 1, "na": 1}
    assert diff["counts"]["b"] == {"now": 1, "soon": 0, "wait": 2, "low": 0, "na": 2}
    assert [c["app_id"] for c in diff["changed"]] == [1]
    change = diff["changed"][0]
    assert change["from"] == {"group": "soon", "sweet_twd": 300, "sweet_pct": 50, "point": "2026 秋特"}
    assert change["to"] == {"group": "wait", "sweet_twd": 250, "sweet_pct": 60, "point": "2026 冬特"}
    assert [c["app_id"] for c in diff["one_side"]] == [5]
    assert diff["mean_sweet_change_twd"] == pytest.approx((-50 + 0 + 0) / 3)


def test_record_format():
    a, b = rb(), rb(rule="2.0.0", model="seasonal-record")
    comparison = compare_rule_results(a, b)
    diff = wishlist_diff({"decisions": [decision(1, "soon")]}, {"decisions": [decision(1, "wait")]})
    text = format_rule_record(date="2026-09-26", comparison=comparison, files=("a.json", "b.json"), wishlist=diff)
    lines = text.splitlines()
    assert lines[0] == ("## 2026-09-26 · 規則回測並列：seasonal-freq 1.0.0 {min_sales=2} ＋ sweet-price 1.0.0 vs "
                        "seasonal-record 1.0.0 {min_sales=2} ＋ sweet-price 2.0.0")
    assert any("照建議買" in line for line in lines) and any("Game 1" in line for line in lines)
    assert "驗證組" in text
    with_decision = format_rule_record(date="2026-09-26", comparison=comparison, files=("a", "b"), wishlist=None,
                                       decision="換上新模型與規則 2.0.0")
    assert "**使用者的決定**：換上新模型與規則 2.0.0" in with_decision


# --- feature 005: net benefit side by side, verdict, attempts (tasks T025; research R7) -------------------------

from sweetspot.decision.compare_rule import (check_rule_attempt, net_comparison,  # noqa: E402
                                             shared_preferences_differ)

MONTH = 365 / 12


def with_cases(result, cases, *, cost=None, split="validation", rule=None):
    r = dict(result)
    r["cases"] = cases
    r["preferences"] = {"soon_sales": 1} if cost is None else {"wait_cost_twd": cost, "soon_sales": 1}
    r["dataset"] = {**r["dataset"], "split": {"name": split}}
    if rule:
        r["rule"] = {"name": "sweet-price", "version": rule, "constants": {}}
    return r


BASE_CASES = [[1, "2025-02-01", "monthly", 30000, 60], [1, "2025-03-01", "monthly", 10000, 0],
              [2, "2025-02-01", "monthly", 0, 365], [3, "2025-02-01", "monthly", 5000, 10],
              [1, "2025-02-01", "fixed", 30000, 90]]
CAND_CASES = [[1, "2025-02-01", "monthly", 25000, 0], [1, "2025-03-01", "monthly", 10000, 0],
              [2, "2025-02-01", "monthly", 0, 30], [1, "2025-02-01", "fixed", 30000, 30]]   # game 3: censored


def test_net_comparison_by_hand():
    base = with_cases(rb(rule="2.0.0"), BASE_CASES)
    cand = with_cases(rb(rule="3.0.0"), CAND_CASES, cost=20, rule="3.0.0")
    out = net_comparison(base, cand, default_cost=20)
    m = out["modes"]["monthly"]
    assert out["cost_twd"] == 20 and m["n"] == 3                    # only the decisions both could evaluate
    base_nets = [300 - 20 * 60 / MONTH, 100, 0 - 20 * 365 / MONTH]
    cand_nets = [250, 100, 0 - 20 * 30 / MONTH]
    assert m["a"]["net"] == pytest.approx(sum(base_nets) / 3) and m["b"]["net"] == pytest.approx(sum(cand_nets) / 3)
    assert m["diff"] == pytest.approx((sum(cand_nets) - sum(base_nets)) / 3)
    assert m["a"]["saving"] == pytest.approx(400 / 3) and m["b"]["wait_days"] == pytest.approx(10)
    lo, hi = m["ci"]
    assert lo <= m["diff"] <= hi
    assert net_comparison(base, cand, default_cost=20)["modes"]["monthly"]["ci"] == [lo, hi]   # fixed seed
    assert out["modes"]["fixed"]["n"] == 1
    assert out["verdict"] == ("pass" if lo > 0 else "fail")


def test_verdict_only_on_validation_at_the_default_cost():
    base = with_cases(rb(rule="2.0.0"), BASE_CASES)
    cand = with_cases(rb(rule="3.0.0"), CAND_CASES, cost=20, rule="3.0.0")
    assert net_comparison(base, cand, default_cost=30)["verdict"] is None
    tuning = with_cases(rb(rule="3.0.0"), CAND_CASES, cost=20, rule="3.0.0", split="tuning")
    assert net_comparison(with_cases(rb(rule="2.0.0"), BASE_CASES, split="tuning"), tuning,
                          default_cost=20)["verdict"] is None


def test_results_without_cases_have_no_net_comparison():
    assert net_comparison(rb(), rb(rule="2.0.0"), default_cost=20) is None


def test_only_shared_preferences_must_match():
    assert shared_preferences_differ({"gap_pp_deep": 5, "soon_sales": 1}, {"wait_cost_twd": 20, "soon_sales": 1}) == []
    assert shared_preferences_differ({"soon_sales": 1}, {"wait_cost_twd": 20, "soon_sales": 2}) == ["soon_sales"]
    base = with_cases(rb(rule="2.0.0"), BASE_CASES)
    base["preferences"] = {"gap_pp_deep": 5, "soon_sales": 1}
    compare_rule_results(base, with_cases(rb(rule="3.0.0"), CAND_CASES, cost=20, rule="3.0.0"))   # no error


def test_rule_attempts(tmp_path):
    record = tmp_path / "comparisons.md"
    check_rule_attempt(record, split="tuning", rule="3.0.0", attempt=None, change=None)            # not validation
    with pytest.raises(CompareRuleError, match="--attempt"):
        check_rule_attempt(record, split="validation", rule="3.0.0", attempt=None, change=None)
    with pytest.raises(CompareRuleError, match="最多比較 3 次"):
        check_rule_attempt(record, split="validation", rule="3.0.0", attempt=4, change="x")
    with pytest.raises(CompareRuleError, match="--change"):
        check_rule_attempt(record, split="validation", rule="3.0.0", attempt=2, change=None)
    record.write_text("## 2026-09-27 · 規則驗證組比較（sweet-price 3.0.0）第 1 次\n", encoding="utf-8")
    with pytest.raises(CompareRuleError, match="已有"):
        check_rule_attempt(record, split="validation", rule="3.0.0", attempt=1, change=None)
    check_rule_attempt(record, split="validation", rule="3.0.0", attempt=2, change="改了 c")


def test_multi_record_lists_games_only_for_the_default_cost():
    from sweetspot.decision.compare_rule import format_rule_records

    base = with_cases(rb(rule="2.0.0"), BASE_CASES)
    cands = [with_cases(rb(rule="3.0.0"), CAND_CASES, cost=c, rule="3.0.0") for c in (10, 20)]
    comparisons = [compare_rule_results(base, c) for c in cands]
    nets = [net_comparison(base, c, default_cost=20) for c in cands]
    wl = [wishlist_diff({"decisions": [decision(1, "soon")]}, {"decisions": [decision(1, "wait")]}) for _ in cands]
    for w, c in zip(wl, (10, 20)):
        w["cost_twd"] = c
    text = format_rule_records(date="2026-09-27", comparisons=comparisons, nets=nets, by_cost=[], files=["a", "b", "c"],
                               wishlists=wl, attempt=1, rule="3.0.0", change=None)
    assert text.startswith("## 2026-09-27 · 規則驗證組比較（sweet-price 3.0.0）第 1 次")
    assert "改變的遊戲 1 款（逐款列表只列 c = 20）" in text and text.count("| Game 1 |") == 1
    assert "**硬門檻**" in text


# --- feature 008: the same rule with a different model (research R7; tasks T027) --------------------------------

def test_same_rule_with_another_model_is_not_a_rule_attempt(tmp_path):
    record = tmp_path / "comparisons.md"
    check_rule_attempt(record, split="validation", rule="2.1.0", attempt=None, change=None, base_rule="2.1.0")
    with pytest.raises(CompareRuleError, match="--attempt"):
        check_rule_attempt(record, split="validation", rule="3.1.0", attempt=None, change=None, base_rule="2.1.0")


def test_two_tolerance_results_get_a_net_comparison_at_a_given_cost_without_a_verdict():
    base = with_cases(rb(rule="2.0.0"), BASE_CASES)
    cand = with_cases(rb(rule="2.0.0", model="seasonal-record"), CAND_CASES)
    assert net_comparison(base, cand, default_cost=20) is None                 # unchanged without a cost
    out = net_comparison(base, cand, default_cost=20, cost=20)
    assert out["cost_twd"] == 20 and out["modes"]["monthly"]["n"] == 3
    assert out["verdict"] is None                                               # same rule: not a rule gate
