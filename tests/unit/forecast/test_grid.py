"""Grid on the tuning part and the parameter choice of spec FR-011 (004 research R7; tasks T017)."""

import pytest

from sweetspot.forecast.backtest.compare import compare_results
from sweetspot.forecast.backtest.dataset import BacktestDataset, RegionDataset
from sweetspot.forecast.backtest.grid import GridError, GridRow, expand, format_grid_record, run_grid, select
from tests.unit.forecast.test_compare import TW_BASE, US_BASE, result, shifted

CURRENT = {"min_sales": 2, "history": "TW"}


def with_sales(r, groups):
    r["regions"]["TW"]["by_own_sales"] = [{"group": g, "brier": b, "games": 10, "units": 100} for g, b in groups.items()]
    return r


def current_result():
    return with_sales(result(TW_BASE, US_BASE, params=CURRENT), {"0": 0.23, "1": 0.16, "2": 0.09, "3+": 0.08})


def row(params, tw_delta, us_delta, one_sale=0.07):
    r = with_sales(result(shifted(TW_BASE, tw_delta), shifted(US_BASE, us_delta), name="seasonal-record", params=params),
                   {"0": 0.23, "1": one_sale, "2": 0.05, "3+": 0.04})
    return GridRow(params, r, compare_results(current_result(), r), ("tw.json", "us.json"))


def test_expand_is_a_fixed_order_cartesian_product():
    assert expand([("min_sales", ["1", "2"]), ("half_life", ["0", "2"])]) == [
        {"min_sales": "1", "half_life": "0"}, {"min_sales": "1", "half_life": "2"},
        {"min_sales": "2", "half_life": "0"}, {"min_sales": "2", "half_life": "2"}]


def test_select_excludes_significantly_worse_us_then_takes_the_lowest_tw():
    rows = [row({"min_sales": 2, "half_life": 0}, -0.03, +0.03),     # best TW but US significantly worse
            row({"min_sales": 2, "half_life": 2}, -0.02, 0.0),
            row({"min_sales": 2, "half_life": 4}, -0.01, -0.01)]
    chosen, notes = select(current_result(), CURRENT, rows)
    assert chosen is rows[1]
    assert rows[0].excluded and not rows[1].excluded
    assert notes == []


def test_ties_go_to_the_earlier_setting():
    rows = [row({"min_sales": 2, "half_life": 0}, -0.02, 0.0), row({"min_sales": 2, "half_life": 2}, -0.02, 0.0)]
    assert select(current_result(), CURRENT, rows)[0] is rows[0]


def test_step_3_a_smaller_min_sales_must_not_hurt_the_games_it_turns_normal():
    worse = [row({"min_sales": 1, "half_life": 2}, -0.03, 0.0, one_sale=0.20),   # its 1-sale group: 0.20 > 0.16
             row({"min_sales": 2, "half_life": 2}, -0.02, 0.0),
             row({"min_sales": 2, "half_life": 0}, -0.01, 0.0)]
    chosen, notes = select(current_result(), CURRENT, worse)
    assert chosen is worse[1]
    assert notes and "1 場" in notes[0] and "0.2000" in notes[0] and "0.1600" in notes[0]
    better = [row({"min_sales": 1, "half_life": 2}, -0.03, 0.0, one_sale=0.07), row({"min_sales": 2}, -0.02, 0.0)]
    chosen, notes = select(current_result(), CURRENT, better)
    assert chosen is better[0] and notes == []


def test_nothing_is_chosen_when_every_setting_is_excluded():
    rows = [row({"min_sales": 2}, -0.03, +0.03)]
    assert select(current_result(), CURRENT, rows) == (None, ["每個設定的美國區都比現行模型顯著變差，不推薦任何設定"])


def test_record_lists_every_setting_and_marks_the_choice():
    rows = [row({"min_sales": 2, "half_life": 0}, -0.03, +0.03), row({"min_sales": 2, "half_life": 2}, -0.02, 0.0)]
    chosen, notes = select(current_result(), CURRENT, rows)
    text = format_grid_record(date="2026-09-26", name="seasonal-record", split="tuning", current=current_result(),
                              rows=rows, chosen=chosen, notes=notes)
    lines = text.splitlines()
    assert lines[0] == "## 2026-09-26 · seasonal-record 調參組網格"
    assert sum(1 for line in lines if line.startswith("| `")) == 2
    assert any("美國區顯著變差，排除" in line for line in lines)
    assert any(line.startswith("**選中：") and "half_life=2" in line for line in lines)


# --- run_grid: US runs are shared between settings that differ only in TW-only parameters ------------------

def dataset():
    regions = {r: RegionDataset(r, (100, 101), (), (0, 12), ("a" if r == "TW" else "b") * 64) for r in ("TW", "US")}
    return BacktestDataset(cutoff=None, levels=(50,), calendar_hash="x", pools={}, regions=regions, split="tuning")


def test_run_grid_shares_us_runs_and_compares_every_setting(tmp_path):
    calls = []

    def runner(store, ds, games, events, model, out_dir=None, progress=None):
        region = next(iter(ds.regions))
        calls.append((region, dict(model.params)) if len(ds.regions) == 1 else ("both", dict(model.params)))
        return {**result(TW_BASE if "TW" in ds.regions else None, US_BASE if "US" in ds.regions else None,
                         name=model.name, params=dict(model.params), units=10),
                "dataset": {"cutoff": None, "regions": {r: {"dataset_id": ds.regions[r].dataset_id} for r in ds.regions},
                            "split": {"name": "tuning"}}}, tmp_path / f"{len(calls)}.json"

    current, rows = run_grid(None, dataset(), {}, [], "seasonal-record@1.0.0", {"min_sales": "1"},
                             [("half_life", ["0", "2"]), ("hazard_history", ["TW", "TW+US"])],
                             out_dir=tmp_path, runner=runner)
    assert calls[0][0] == "both"                                      # the current model on both regions
    assert [c[0] for c in calls[1:]].count("TW") == 4
    assert [c[0] for c in calls[1:]].count("US") == 2                 # hazard_history is TW-only
    assert len(rows) == 4 and all(r.comparison.regions["US"].games == 200 for r in rows)
    assert rows[0].params == {"min_sales": 1, "half_life": 0, "hazard_history": "TW"}


def test_validation_split_is_refused():
    ds = dataset()
    ds = BacktestDataset(ds.cutoff, ds.levels, ds.calendar_hash, ds.pools, ds.regions, "validation")
    with pytest.raises(GridError, match="FR-011"):
        run_grid(None, ds, {}, [], "seasonal-record", {}, [("half_life", ["0"])], out_dir=None)


# --- feature 008: FR-003 and FR-004 exclusions (research R6; tasks T019) ----------------------------------------

from tests.unit.forecast.test_compare import noisy as _noisy  # noqa: E402


def with_game_groups(r, deltas: dict[str, float]):
    r["per_game_by_own_sales"] = {"TW": {}}
    for g, base in (("2", 0.05), ("3-5", 0.045), ("6+", 0.04)):
        for i, e in enumerate(_noisy(base, seed=len(g) + 7)):
            r["per_game_by_own_sales"]["TW"].setdefault(str(100 + i), {})[g] = [10, (e + deltas.get(g, 0.0)) * 10]
    return r


def row008(params, tw_delta, group_deltas, *, version="1.1.0"):
    r = with_game_groups(result(shifted(TW_BASE, tw_delta), US_BASE, name="seasonal-record", version=version,
                                params=params), group_deltas)
    return GridRow(params, r, compare_results(current008(), r), ("tw.json", "us.json"))


def current008():
    return with_game_groups(result(TW_BASE, US_BASE, name="seasonal-record", params={"min_sales": 1}), {})


def test_fr004_excludes_a_setting_that_hurts_games_with_more_records():
    rows = [row008({"low_base": "new", "shrink": 1}, -0.03, {"2": +0.01}),     # best TW, 2-sale group worse
            row008({"low_base": "new", "shrink": 0.5}, -0.02, {"2": 0.0})]
    chosen, _ = select(current008(), {"min_sales": 1}, rows)
    assert chosen is rows[1]
    assert rows[0].excluded and rows[0].excluded_reason == "own-sales-worse:2"


def test_fr003_setting_is_listed_but_never_chosen():
    rows = [row008({"low_base": "new", "shrink": 0}, -0.03, {}), row008({"low_base": "new", "shrink": 0.5}, -0.02, {})]
    chosen, _ = select(current008(), {"min_sales": 1}, rows)
    assert chosen is rows[1] and rows[0].excluded_reason == "fr-003"
    text = format_grid_record(date="2026-09-26", name="seasonal-record@1.1.0", split="tuning", current=current008(),
                              rows=rows, chosen=chosen, notes=[])
    assert any("FR-003" in line and "對照" in line for line in text.splitlines())


def test_results_without_group_data_skip_fr004():
    r = result(shifted(TW_BASE, -0.02), US_BASE, name="seasonal-record", params={"min_sales": 2})
    row_ = GridRow({"min_sales": 2}, r, compare_results(current_result(), r), ())
    chosen, _ = select(current_result(), CURRENT, [row_])
    assert chosen is row_ and row_.excluded_reason is None
