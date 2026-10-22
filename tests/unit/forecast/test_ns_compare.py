"""Comparing non-seasonal results and the validation attempts (feature 007 contracts/cli-and-report.md; tasks T013)."""

import pytest

from sweetspot.forecast.backtest.compare import CompareError
from sweetspot.forecast.nonseasonal.backtest import (check_ns_attempt, compare_ns, format_ns_compare_record,
                                                     format_ns_grid_record, select_ns)

MODEL = {"name": "non-seasonal", "version": "1.0.0", "params": {"clock": True, "history": "TW+US", "smoothing": 2}}


def result(per_game, *, split="validation", ns_id="a1b2c3d4" + "0" * 56, model=MODEL, brier=None):
    games = [v[1] / v[0] for v in per_game.values()]
    refs = [v[2] / v[0] for v in per_game.values()]
    return {"schema": "steamsage.ns-backtest/1", "model": model,
            "dataset": {"cutoff": "2026-09-25T00:00:00.000000Z", "split": {"name": split, "salt": "s"},
                        "ns_dataset_id": ns_id, "dataset_id": "f" * 64},
            "brier": brier if brier is not None else sum(games) / len(games), "reference_brier": sum(refs) / len(refs),
            "by_horizon": {"30": {"brier": 0.1, "reference_brier": 0.15, "units": 10},
                           "60": {"brier": 0.12, "reference_brier": 0.2, "units": 10},
                           "90": {"brier": 0.13, "reference_brier": 0.22, "units": 10}},
            "earlier": {"eligible": 10, "eligible_hit": 4,
                        "thresholds": [{"threshold": 0.5, "said": 3, "hit": 2, "rate": 2 / 3}]},
            "per_game": {str(k): list(v) for k, v in per_game.items()}}


BETTER = {1: (57, 5.7, 11.4), 2: (57, 6.0, 12.0), 3: (57, 4.0, 9.0), 4: (19, 2.0, 3.0)}


def test_against_the_reference():
    c = compare_ns(result(BETTER))
    assert c.verdict == "優於" and c.high < 0 and c.games == 4
    assert c.diff == pytest.approx(sum(v[1] / v[0] - v[2] / v[0] for v in BETTER.values()) / 4)
    assert c.against == "整體比例"


def test_only_the_validation_split_is_judged():
    assert compare_ns(result(BETTER, split="tuning")).verdict is None


def test_not_better_when_the_interval_contains_zero():
    mixed = {1: (57, 5.7, 5.0), 2: (57, 5.0, 5.7), 3: (57, 6.0, 5.9)}
    assert compare_ns(result(mixed)).verdict == "未優於"


def test_against_another_result():
    base = result({1: (57, 6.0, 11.4), 2: (57, 6.5, 12.0), 3: (57, 4.5, 9.0), 4: (19, 2.2, 3.0)},
                  model=MODEL | {"params": {"clock": False, "history": "TW", "smoothing": 5}})
    c = compare_ns(result(BETTER), base)
    assert c.against.startswith("non-seasonal 1.0.0 {clock=False")
    assert c.diff < 0
    with pytest.raises(CompareError, match="資料集"):
        compare_ns(result(BETTER), result(BETTER, ns_id="9" * 64))
    with pytest.raises(CompareError, match="切分"):
        compare_ns(result(BETTER), result(BETTER, split="tuning"))
    with pytest.raises(CompareError, match="評分單位"):
        compare_ns(result(BETTER), result({1: (57, 6.0, 11.4)}))


def test_attempts(tmp_path):
    path = tmp_path / "comparisons.md"
    c = compare_ns(result(BETTER))
    with pytest.raises(CompareError, match="--attempt"):
        check_ns_attempt(path, c, None, None)
    with pytest.raises(CompareError, match="1–3"):
        check_ns_attempt(path, c, 4, "x")
    with pytest.raises(CompareError, match="--change"):
        check_ns_attempt(path, c, 2, None)
    # a 004 model comparison and a 005 rule comparison do not count
    path.write_text("## 2026-09-25 · seasonal-record 1.0.0 {} vs 現行 seasonal-freq 1.0.0 {}（驗證組 · 第 1 次）\n"
                    "## 2026-09-26 · 規則驗證組比較（sweet-price 3.0.0）第 1 次\n", encoding="utf-8")
    check_ns_attempt(path, c, 1, None)
    path.write_text(path.read_text(encoding="utf-8") + format_ns_compare_record(
        c, date="2026-09-27", files=("r.json",), attempt=1, change=None), encoding="utf-8")
    with pytest.raises(CompareError, match="第 1 次"):
        check_ns_attempt(path, c, 1, None)
    check_ns_attempt(path, c, 2, "換了參數")
    check_ns_attempt(path, compare_ns(result(BETTER, split="tuning")), None, None)     # not validation: no limit


def test_record_texts():
    c = compare_ns(result(BETTER))
    text = format_ns_compare_record(c, date="2026-09-27", files=("r.json",), attempt=1, change=None)
    assert text.startswith("## 2026-09-27 · non-seasonal 1.0.0 {clock=True, history=TW+US, smoothing=2} vs 整體比例"
                           "（非季節驗證組 · 第 1 次）")
    assert "**判定：優於**" in text and "| 30 天 |" in text and "門檻 50%：說 3 次，實際到價 2 次" in text
    rows = [(MODEL["params"], result(BETTER, split="tuning", brier=0.13)),
            ({"clock": False, "history": "TW", "smoothing": 5}, result(BETTER, split="tuning", brier=0.1305))]
    chosen, notes = select_ns(rows)
    assert chosen == {"clock": False, "history": "TW", "smoothing": 5}      # within 0.001: the simpler one
    grid = format_ns_grid_record(date="2026-09-27", split="tuning", rows=rows, chosen=chosen, notes=notes,
                                 files=["a.json", "b.json"])
    assert grid.startswith("## 2026-09-27 · non-seasonal 調參組網格") and grid.count("| `") == 2


def test_selection_prefers_the_lowest_brier_beyond_the_margin():
    rows = [({"clock": True, "history": "TW+US", "smoothing": 2}, result(BETTER, split="tuning", brier=0.127)),
            ({"clock": False, "history": "TW", "smoothing": 5}, result(BETTER, split="tuning", brier=0.1516))]
    assert select_ns(rows)[0] == {"clock": True, "history": "TW+US", "smoothing": 2}
