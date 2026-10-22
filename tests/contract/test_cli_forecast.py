"""contracts/cli.md: `sweetspot forecast` (tasks T017)."""

import io
import json

import pytest

from sweetspot import cli
from sweetspot.forecast.models import CURRENT_MODEL
from tests.config_builders import TEST_TOML
from tests.forecast_builders import BASIC_CALENDAR, GameSpec, build_db

HISTORY = [("2024-12-11", 0), ("2024-12-19T18:00", 50), ("2025-01-02T18:00", 0), ("2025-03-13T17:00", 40),
           ("2025-03-20T17:00", 0)]


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_secrets", lambda: cli.Secrets())
    path = tmp_path / "sweetspot.toml"
    path.write_text(TEST_TOML, encoding="utf-8")
    return path


@pytest.fixture
def db(config_path):
    games = [GameSpec(1, tw=HISTORY, name="Alpha", wishlist=True),
             GameSpec(2, tw=HISTORY, name="Beta", wishlist=True),
             GameSpec(3, tw=HISTORY, name="Reference only"),
             GameSpec(4, name="Coming soon", release_date="2099-01-01", wishlist=True)]
    return build_db(config_path.parent / "data" / "sweetspot.db", games, calendar=BASIC_CALENDAR)


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(list(argv), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_json_outputs_the_full_contract(config_path, db):
    code, out, _ = run("forecast", "--json", "--config", str(config_path))
    assert code == cli.EXIT_OK
    data = json.loads(out)
    assert data["schema"] == "steamsage.forecast/1"
    assert [g["app_id"] for g in data["games"]] == [1, 2, 4]           # wishlist by default
    assert data["games"][2]["status"] == "unreleased"


def test_scope_all_and_repeated_app(config_path, db):
    _, out, _ = run("forecast", "--json", "--scope", "all", "--config", str(config_path))
    assert [g["app_id"] for g in json.loads(out)["games"]] == [1, 2, 3, 4]
    _, out, _ = run("forecast", "--json", "--app", "3", "--app", "1", "--config", str(config_path))
    assert [g["app_id"] for g in json.loads(out)["games"]] == [1, 3]


def test_as_of_in_the_past_uses_estimated_points_only(config_path, db):
    code, out, _ = run("forecast", "--json", "--as-of", "2025-06-01", "--app", "1", "--config", str(config_path))
    data = json.loads(out)
    assert code == 0 and data["as_of"] == "2025-06-01T00:00:00Z"
    assert all(p["status"] == "estimated" for p in data["games"][0]["curve"]["points"])


def test_out_writes_file_and_prints_summary(config_path, db):
    target = config_path.parent / "data" / "forecast.json"
    code, out, _ = run("forecast", "--out", str(target), "--json", "--config", str(config_path))
    assert code == 0 and json.loads(target.read_text(encoding="utf-8"))["schema"] == "steamsage.forecast/1"
    summary = json.loads(out)
    assert summary["games"] == 3 and summary["ok"] == 2 and summary["unreleased"] == 1
    assert summary["out"] == str(target) and summary["model"]["name"] == CURRENT_MODEL[0]


def test_human_output_has_one_line_per_game(config_path, db):
    code, out, _ = run("forecast", "--config", str(config_path))
    assert code == 0
    lines = [line for line in out.splitlines() if line.startswith(("Alpha", "Beta", "Coming soon"))]
    assert len(lines) == 3
    assert "≥-50%" in lines[0] and "信心" in lines[0]
    assert "unreleased" in lines[2]


def test_runs_while_the_writer_lock_is_held_and_never_opens_a_writer(config_path, db, monkeypatch):
    (config_path.parent / "data" / ".lock").write_text("4242\n", encoding="utf-8")

    def no_writer(*a, **k):
        raise AssertionError("forecast must not open a StoreWriter")

    monkeypatch.setattr(cli.StoreWriter, "open", no_writer)
    code, _, err = run("forecast", "--config", str(config_path))
    assert code == cli.EXIT_OK, err


def test_model_error_exits_2(config_path):
    # the only product was tracked from mid-sale: no ended sale anywhere, so the baseline cannot estimate
    build_db(config_path.parent / "data" / "sweetspot.db",
             [GameSpec(1, tw=[("2025-06-30", 30), ("2025-07-12", 0)], wishlist=True)], calendar=BASIC_CALENDAR)
    code, out, _ = run("forecast", "--json", "--as-of", "2025-08-01", "--config", str(config_path))
    assert code == cli.EXIT_PARTIAL
    assert json.loads(out)["games"][0]["status"] == "model-error"


@pytest.mark.parametrize("argv", [("--as-of", "yesterday"), ("--model", "nope"), ("--param", "min_sales=0"),
                                  ("--param", "novalue")])
def test_bad_arguments_exit_1(config_path, db, argv):
    code, _, err = run("forecast", *argv, "--config", str(config_path))
    assert code == cli.EXIT_FAILED and err
