"""Model comparison: per-region checks, paired bootstrap and the FR-029 verdict (tasks T033, SC-008)."""

import random

import pytest

from sweetspot.forecast.backtest.compare import (CompareError, append_record, baseline_record, compare_results,
                                                 format_record)

TW_ID, US_ID = "a" * 64, "b" * 64


def result(tw_errors: list[float] | None, us_errors: list[float] | None = None, *, params=None, name="seasonal-freq",
           version="1.0.0", units: int = 10, tw_id=TW_ID) -> dict:
    """A backtest result whose per-game mean Brier values are the given numbers."""
    regions, per_game, dataset = {}, {}, {}
    for region, errors, ds in (("TW", tw_errors, tw_id), ("US", us_errors, US_ID)):
        if errors is None:
            continue
        per_game[region] = {str(100 + i): [units, e * units] for i, e in enumerate(errors)}
        regions[region] = {"brier": sum(errors) / len(errors), "games": len(errors)}
        dataset[region] = {"dataset_id": ds}
    return {"schema": "steamsage.backtest/1",
            "model": {"name": name, "version": version, "params": params or {"min_sales": 1, "history": "TW"}},
            "dataset": {"cutoff": "2026-09-24T00:00:00Z", "regions": dataset}, "regions": regions,
            "per_game": per_game}


def noisy(base: float, n: int = 200, seed: int = 1, spread: float = 0.05) -> list[float]:
    rng = random.Random(seed)
    return [max(0.0, base + rng.uniform(-spread, spread)) for _ in range(n)]


def shifted(errors: list[float], delta: float) -> list[float]:
    return [e + delta for e in errors]


TW_BASE, US_BASE = noisy(0.10, seed=1), noisy(0.20, seed=2)


def test_clearly_better_in_both_regions_is_better():
    c = compare_results(result(TW_BASE, US_BASE), result(shifted(TW_BASE, -0.02), shifted(US_BASE, -0.02)))
    assert c.verdict == "優於"
    tw = c.regions["TW"]
    assert tw.diff == pytest.approx(-0.02) and tw.high < 0 and tw.games == 200


def test_better_in_tw_but_significantly_worse_in_us_is_not_better():
    c = compare_results(result(TW_BASE, US_BASE), result(shifted(TW_BASE, -0.02), shifted(US_BASE, 0.03)))
    assert c.verdict == "未優於" and any("美國區" in r for r in c.reasons)


def test_insignificant_tw_difference_is_not_better():
    candidate = [e + random.Random(i).uniform(-0.03, 0.03) for i, e in enumerate(TW_BASE)]
    c = compare_results(result(TW_BASE, US_BASE), result(candidate, US_BASE))
    assert c.regions["TW"].low < 0 < c.regions["TW"].high
    assert c.verdict == "未優於" and any("台灣區" in r for r in c.reasons)


def test_tw_only_candidate_differing_only_in_history_is_compared_with_us_as_zero():
    current = result(TW_BASE, US_BASE, params={"min_sales": 1, "history": "TW"})
    candidate = result(shifted(TW_BASE, -0.02), None, params={"min_sales": 1, "history": "TW+US"})
    c = compare_results(current, candidate)
    assert c.verdict == "優於"
    assert c.regions["US"].omitted and c.regions["US"].diff == 0
    assert "依構造相同，未重跑" in format_record(c, date="2026-10-01", files=("a.json", "b.json"))


def test_missing_us_with_other_param_changes_is_refused():
    current = result(TW_BASE, US_BASE, params={"min_sales": 1, "history": "TW"})
    candidate = result(shifted(TW_BASE, -0.02), None, params={"min_sales": 2, "history": "TW+US"})
    with pytest.raises(CompareError, match="美國區"):
        compare_results(current, candidate)


def test_missing_tw_is_refused():
    with pytest.raises(CompareError, match="台灣區"):
        compare_results(result(TW_BASE, US_BASE), result(None, US_BASE))


def test_different_dataset_is_refused():
    with pytest.raises(CompareError, match="台灣區.*資料集"):
        compare_results(result(TW_BASE), result(TW_BASE, tw_id="c" * 64))


def test_different_unit_counts_are_refused():
    b = result(TW_BASE)
    b["per_game"]["TW"]["105"][0] = 11
    with pytest.raises(CompareError, match="105"):
        compare_results(result(TW_BASE), b)


def test_bootstrap_is_reproducible():
    a, b = result(TW_BASE), result(shifted(TW_BASE, -0.01))
    first, second = compare_results(a, b), compare_results(a, b)
    assert (first.regions["TW"].low, first.regions["TW"].high) == (second.regions["TW"].low, second.regions["TW"].high)


def test_append_record_keeps_existing_content(tmp_path):
    path = tmp_path / "comparisons.md"
    path.write_bytes("# 模型比較紀錄\r\n\r\n舊紀錄\r\n".encode("utf-8"))
    before = path.read_bytes()
    c = compare_results(result(TW_BASE, US_BASE), result(shifted(TW_BASE, -0.02), shifted(US_BASE, -0.02)))
    append_record(path, format_record(c, date="2026-10-01", files=("a.json", "b.json")))
    after = path.read_bytes()
    assert after.startswith(before)
    text = after.decode("utf-8")
    assert "## 2026-10-01 · seasonal-freq 1.0.0" in text and "**判定：優於**" in text
    assert "| 台灣區（≤12 個月） |" in text and "| 美國區（1–5 年） |" in text


def test_baseline_record_establishes_the_floor(tmp_path):
    text = baseline_record(result(TW_BASE, US_BASE), date="2026-10-01", file="base.json",
                           reason="網格中台灣區 Brier 最低")
    assert "**判定：建立下限**" in text and "網格中台灣區 Brier 最低" in text
    assert "min_sales=1" in text and "history=TW" in text


def test_reasons_say_when_the_candidate_is_significantly_worse():
    c = compare_results(result(TW_BASE, US_BASE), result(shifted(TW_BASE, 0.02), US_BASE))
    assert c.verdict == "未優於"
    assert "下限 > 0，顯著較差" in c.reasons[0]


# --- feature 004: splits and validation attempts (spec FR-012, FR-013; tasks T019) -----------------------

from sweetspot.forecast.backtest.compare import check_attempt  # noqa: E402


def split_result(split, *args, deeper=None, **kw):
    r = result(*args, **kw)
    r["dataset"]["split"] = {"name": split, "salt": "steamsage-004-split"}
    for region, value in (deeper or {}).items():
        r["regions"][region]["deeper_than_past"] = {"brier": value, "games": 5, "units": 50}
    return r


def test_different_splits_are_refused():
    with pytest.raises(CompareError, match="切分"):
        compare_results(split_result("tuning", TW_BASE, US_BASE), split_result("validation", TW_BASE, US_BASE))


def test_old_results_count_as_split_all():
    c = compare_results(result(TW_BASE, US_BASE), split_result("all", shifted(TW_BASE, -0.02), US_BASE))
    assert c.split == "all"


def validation_pair(**kw):
    a = split_result("validation", TW_BASE, US_BASE, deeper={"TW": 0.17, "US": 0.40}, **kw)
    b = split_result("validation", shifted(TW_BASE, -0.02), shifted(US_BASE, -0.02), name="seasonal-record",
                     params={"min_sales": 1}, deeper={"TW": 0.10, "US": 0.13})
    return compare_results(a, b)


def test_validation_record_title_change_and_deeper_line():
    c = validation_pair()
    text = format_record(c, date="2026-09-26", files=("a.json", "b.json"), attempt=2, change="加上遊戲年齡")
    assert text.splitlines()[0].endswith("（驗證組 · 第 2 次）")
    assert "- 這次的修改：加上遊戲年齡" in text
    assert "「比過去更深」的 Brier：台灣區 0.1700 → 0.1000；美國區 0.4000 → 0.1300（不影響判定）" in text


def test_attempt_rules(tmp_path):
    c = validation_pair()
    doc = tmp_path / "comparisons.md"
    with pytest.raises(CompareError, match="--attempt"):
        check_attempt(doc, c, None, None)
    for bad in (0, 4):
        with pytest.raises(CompareError, match="1–3"):
            check_attempt(doc, c, bad, "x")
    with pytest.raises(CompareError, match="--change"):
        check_attempt(doc, c, 2, None)
    check_attempt(doc, c, 1, None)                                  # the first attempt needs no explanation
    append_record(doc, format_record(c, date="2026-09-26", files=("a", "b"), attempt=1))
    with pytest.raises(CompareError, match="第 1 次"):
        check_attempt(doc, c, 1, None)
    check_attempt(doc, c, 2, "修正")


def test_attempts_do_not_apply_outside_the_validation_split(tmp_path):
    c = compare_results(split_result("tuning", TW_BASE, US_BASE), split_result("tuning", shifted(TW_BASE, -0.02),
                                                                               US_BASE))
    check_attempt(tmp_path / "comparisons.md", c, None, None)
    text = format_record(c, date="2026-09-26", files=("a", "b"))
    assert "驗證組" not in text and "比過去更深" not in text


# --- feature 008: target own-sales groups (spec FR-009; research R6; tasks T021) --------------------------------

def with_groups(r, groups: dict[str, list[float]], finished: dict[str, tuple[float, float]] | None = None):
    """Per-game group errors {group: [error of game 100, 101, …]} and finished-only (predicted, actual) per group."""
    r["per_game_by_own_sales"] = {"TW": {}}
    for g, errors in groups.items():
        for i, e in enumerate(errors):
            r["per_game_by_own_sales"]["TW"].setdefault(str(100 + i), {})[g] = [10, e * 10]
    r["regions"]["TW"]["by_own_sales"] = [{"group": g, "brier": sum(v) / len(v), "games": len(v)}
                                          for g, v in groups.items()]
    r["regions"]["TW"]["finished_calibration"] = {"groups": {"own_sales": [
        {"group": g, "n": 100, "predicted": p, "actual": a, "brier": 0.1} for g, (p, a) in (finished or {}).items()]}}
    return r


def pair(zero_delta: float, one_delta: float):
    base = with_groups(result(TW_BASE, US_BASE), {"0": noisy(0.23, seed=3), "1": noisy(0.07, seed=4)},
                       {"0": (0.67, 0.30), "1": (0.58, 0.56)})
    cand = with_groups(result(shifted(TW_BASE, -0.02), shifted(US_BASE, -0.02), version="1.1.0"),
                       {"0": shifted(noisy(0.23, seed=3), zero_delta), "1": shifted(noisy(0.07, seed=4), one_delta)},
                       {"0": (0.33, 0.30), "1": (0.57, 0.56)})
    return base, cand


def test_target_groups_both_lower_is_better():
    base, cand = pair(-0.15, -0.001)
    c = compare_results(base, cand, target_groups=("0", "1"))
    assert c.verdict == "優於"
    g0 = c.groups["0"]
    assert g0.brier_a == pytest.approx(sum(noisy(0.23, seed=3)) / 200) and g0.diff == pytest.approx(-0.15)
    assert g0.low <= g0.diff <= g0.high and g0.finished == ((0.67, 0.30), (0.33, 0.30))   # constant shift: zero width


def test_one_target_group_not_lower_is_not_better():
    base, cand = pair(-0.15, +0.001)
    c = compare_results(base, cand, target_groups=("0", "1"))
    assert c.verdict == "未優於"
    assert any("1 場" in r and "沒有比現行低" in r for r in c.reasons)
    assert c.regions["TW"].high < 0                                   # FR-029 alone would have passed


def test_fr029_failing_is_not_better_even_with_lower_groups():
    base, cand = pair(-0.15, -0.01)
    cand["per_game"]["US"] = {k: [n, s + 0.03 * n] for k, (n, s) in cand["per_game"]["US"].items()}
    assert compare_results(base, cand, target_groups=("0", "1")).verdict == "未優於"


def test_record_states_the_condition_and_the_groups():
    base, cand = pair(-0.15, -0.001)
    c = compare_results(base, cand, target_groups=("0", "1"))
    text = format_record(c, date="2026-09-26", files=("a.json", "b.json"))
    assert "另外要求本身 0 場、1 場兩組的台灣區 Brier 都比現行低（點估計）" in text
    assert "| 0 場（低信心） |" in text and "| 1 場 |" in text
    assert "+37.0 → +3.0" in text                                   # finished-only predicted − actual, in pp


def test_unknown_target_group_is_an_error():
    base, cand = pair(-0.15, -0.001)
    with pytest.raises(CompareError, match="場數組"):
        compare_results(base, cand, target_groups=("7",))
