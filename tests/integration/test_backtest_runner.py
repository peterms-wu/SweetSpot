"""Backtest runner end to end on a synthetic store (tasks T027)."""

import json
from dataclasses import replace

import pytest

from sweetspot.forecast.backtest.dataset import build_dataset
from sweetspot.forecast.backtest.runner import run_backtest
from sweetspot.forecast.engine import all_apps, load_games
from sweetspot.forecast.models import build_model
from sweetspot.store.query import PriceStore
from tests.forecast_builders import BASIC_CALENDAR, GameSpec, Sale, build_db, dt

CUTOFF = dt("2026-09-24")
EXTRA_CALENDAR = [Sale("summer", 2022, "2022-06-23T17:00", "2022-07-07T17:00"),
                  Sale("autumn", 2022, "2022-11-22T18:00", "2022-11-29T18:00"),
                  Sale("winter", 2022, "2022-12-22T18:00", "2023-01-05T18:00"),
                  Sale("spring", 2023, "2023-03-16T17:00", "2023-03-23T17:00")]


def tw(app: int) -> list[tuple]:
    cut = 30 + 10 * (app % 4)
    rows = [("2024-12-11", 0)]
    for s in BASIC_CALENDAR:
        if dt(s.start) > dt("2024-12-11"):
            rows += [(s.start, cut if (app + s.year) % 3 else cut + 20), (s.end, 0)]
    return rows


def us(app: int) -> list[tuple]:
    rows = [("2022-01-01", 0)]
    for s in EXTRA_CALENDAR + BASIC_CALENDAR:
        rows += [(s.start, 20 + 10 * (app % 5)), (s.end, 0)]
    return rows


@pytest.fixture
def store(db_path):
    games = [GameSpec(a, tw=tw(a), us=us(a) if a % 2 else [], known_until={"TW": "2026-09-24", "US": "2026-09-24"},
                      pool="broad", wishlist=(a == 1)) for a in range(1, 9)]
    build_db(db_path, games, calendar=EXTRA_CALENDAR + BASIC_CALENDAR)
    s = PriceStore.open(db_path)
    yield s
    s.close()


def setup(store, regions=("TW", "US")):
    games = load_games(store, all_apps(store), CUTOFF)
    events = store.calendar_events()
    return build_dataset(store, games, events, cutoff=CUTOFF, regions=regions), games, events


class Failing:
    def __init__(self, fail_app, fail_as_of):
        self.inner = build_model("seasonal-freq")
        self.name, self.version, self.params = "failing", "0.0.1", {}
        self.tw_only_params = frozenset()
        self.fail = (fail_app, fail_as_of)

    def confidence_levels(self):
        return self.inner.confidence_levels()

    def prepare(self, population):
        self.inner.prepare(population)
        self.as_of = population.as_of

    def predict(self, game, points, levels):
        if (game.app_id, game.as_of) == self.fail:
            raise RuntimeError("故意失敗")
        return self.inner.predict(game, points, levels)


def test_result_matches_the_contract(store, tmp_path):
    ds, games, events = setup(store)
    messages = []
    result, path = run_backtest(store, ds, games, events, build_model("seasonal-freq"), out_dir=tmp_path,
                                progress=messages.append)
    assert path.parent == tmp_path and path.suffix == ".json"
    assert json.loads(path.read_text(encoding="utf-8")) == result
    assert result["schema"] == "steamsage.backtest/1"
    assert result["model"] == {"name": "seasonal-freq", "version": "1.0.0", "params": {"history": "TW", "min_sales": 1}}
    assert set(result["dataset"]["regions"]) == {"TW", "US"}
    assert result["dataset"]["regions"]["TW"]["dataset_id"] == ds.regions["TW"].dataset_id
    for region in ("TW", "US"):
        r = result["regions"][region]
        assert 0 <= r["brier"] <= 1 and 0 <= r["reference_brier"] <= 1
        assert r["units"]["scored"] > 0 and r["games"] > 0 and r["as_of_count"] == len(ds.regions[region].schedule)
        assert result["per_game"][region]
    assert result["errors"] == []
    assert set(result["run"]) == {"started_at", "finished_at", "seconds", "steamsage_version"}
    assert messages[0].startswith("回測 TW 分析時點 1/") and "（2025-" in messages[0]


def test_rerun_is_identical_except_run(store, tmp_path):
    ds, games, events = setup(store)
    a, _ = run_backtest(store, ds, games, events, build_model("seasonal-freq"), out_dir=tmp_path / "a")
    b, _ = run_backtest(store, ds, games, events, build_model("seasonal-freq"), out_dir=tmp_path / "b")
    a.pop("run"), b.pop("run")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_model_errors_are_isolated(store, tmp_path):
    ds, games, events = setup(store, regions=("TW",))
    fail_at = ds.regions["TW"].schedule[2]
    result, _ = run_backtest(store, ds, games, events, Failing(3, fail_at), out_dir=tmp_path)
    assert result["errors"] == [{"app_id": 3, "as_of": fail_at.strftime("%Y-%m-%d"), "region": "TW",
                                 "reason": "RuntimeError: 故意失敗"}]
    assert result["regions"]["TW"]["units"]["scored"] > 0


def test_interrupted_run_leaves_no_result(store, tmp_path):
    ds, games, events = setup(store)

    def stop(message):
        if "3/" in message:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_backtest(store, ds, games, events, build_model("seasonal-freq"), out_dir=tmp_path, progress=stop)
    assert list(tmp_path.glob("*.json")) == []


def test_file_name_identifies_model_regions_and_data(store, tmp_path):
    ds, games, events = setup(store, regions=("TW",))
    _, path = run_backtest(store, ds, games, events, build_model("seasonal-freq", {"min_sales": 2}), out_dir=tmp_path,
                           now=dt("2026-09-25T01:02:03"))
    name = path.name
    assert name.startswith("20260925T010203Z_seasonal-freq-1.0.0_") and "_TW_" in name


def test_split_scores_one_part_with_the_whole_population(store, tmp_path):
    """004 research R2, R4: new groups in the result; a split scores its own games only, with the same
    population-share forecasts as the full run (tasks T005, T007)."""
    from sweetspot.forecast.backtest.split import part

    games = load_games(store, all_apps(store), CUTOFF)
    events = store.calendar_events()
    full_ds = build_dataset(store, games, events, cutoff=CUTOFF, regions=("TW",))
    val_ds = build_dataset(store, games, events, cutoff=CUTOFF, regions=("TW",), split="validation")
    model = build_model("seasonal-freq", {"min_sales": 20})          # everyone on the population share
    full, _ = run_backtest(store, full_ds, games, events, model, out_dir=tmp_path / "a")
    val, _ = run_backtest(store, val_ds, games, events, model, out_dir=tmp_path / "b")
    assert full["dataset"]["split"] == {"name": "all", "salt": "steamsage-004-split"}
    assert val["dataset"]["split"]["name"] == "validation"
    assert val["dataset"]["regions"]["TW"]["population_games"] == len(full_ds.regions["TW"].apps)
    expected = {a for a in full["per_game"]["TW"] if part(int(a)) == "validation"}
    assert set(val["per_game"]["TW"]) == expected
    for app in expected:
        assert val["per_game"]["TW"][app] == pytest.approx(full["per_game"]["TW"][app])
    for key in ("deeper_than_past", "by_own_sales"):
        assert key in full["regions"]["TW"]


# --- feature 008 (research R3, R5; tasks T011) -------------------------------------------------------------------

def test_release_facts_and_finished_calibration_are_recorded(store):
    dataset, games, events = setup(store)
    result, _ = run_backtest(store, dataset, games, events, build_model("seasonal-record@1.0.0"))
    facts = result["release_facts"]
    assert facts["count"] == 8 and facts["known"] == 8 and len(facts["sha256"]) == 64
    for region in ("TW", "US"):
        fc = result["regions"][region]["finished_calibration"]
        assert fc["units"] > 0 and fc["brier"] is not None
        assert sum(b["n"] for b in fc["bins"]) == fc["units"]
    assert set(result["per_game_by_own_sales"]) == {"TW", "US"}


def test_release_dates_never_change_the_dataset_id_or_the_score(store, db_path):
    dataset, games, events = setup(store)
    before, _ = run_backtest(store, dataset, games, events, build_model("seasonal-record@1.0.0"))
    shifted = {a: replace(g, release_date=None) for a, g in games.items()}
    dataset2 = build_dataset(store, shifted, events, cutoff=CUTOFF, regions=("TW", "US"))
    after, _ = run_backtest(store, dataset2, shifted, events, build_model("seasonal-record@1.0.0"))
    assert {r: rd.dataset_id for r, rd in dataset.regions.items()} == \
        {r: rd.dataset_id for r, rd in dataset2.regions.items()}
    assert before["release_facts"]["sha256"] != after["release_facts"]["sha256"]
    for region in ("TW", "US"):
        assert before["regions"][region]["brier"] == after["regions"][region]["brier"]
