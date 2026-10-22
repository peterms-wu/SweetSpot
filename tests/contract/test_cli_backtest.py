"""contracts/cli.md: `sweetspot backtest` (tasks T029)."""

import io
import json

import pytest

from sweetspot import cli
from tests.config_builders import TEST_TOML
from tests.forecast_builders import BASIC_CALENDAR, GameSpec, build_db
from tests.integration.test_backtest_runner import EXTRA_CALENDAR, tw, us


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_secrets", lambda: cli.Secrets())
    path = tmp_path / "sweetspot.toml"
    path.write_text(TEST_TOML, encoding="utf-8")
    games = [GameSpec(a, tw=tw(a), us=us(a) if a % 2 else [], known_until={"TW": "2026-09-24", "US": "2026-09-24"})
             for a in range(1, 7)]
    build_db(tmp_path / "data" / "sweetspot.db", games, calendar=EXTRA_CALENDAR + BASIC_CALENDAR)
    return path


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(list(argv), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_backtest_writes_result_and_summarises(config_path):
    code, out, err = run("backtest", "--json", "--config", str(config_path))
    assert code == cli.EXIT_OK, err
    summary = json.loads(out)
    path = config_path.parent / "data" / "backtests"
    assert summary["result"].startswith(str(path)) and (path / summary["result"].split("\\")[-1].split("/")[-1]).exists()
    assert summary["cutoff"] == "2026-09-24T00:00:00Z"
    for region in ("TW", "US"):
        r = summary["regions"][region]
        assert set(r) == {"games", "as_of_count", "brier", "reference_brier", "units"}
        assert set(r["units"]) == {"scored", "censored", "not_held"}
    assert summary["errors"] == 0 and "seconds" in summary
    assert "回測 TW 分析時點 1/" in err


def test_options(config_path):
    code, out, _ = run("backtest", "--json", "--region", "TW", "--apps-limit", "3", "--cutoff", "2026-06-01",
                       "--model", "seasonal-freq", "--param", "min_sales=2", "--param", "history=TW+US",
                       "--config", str(config_path))
    summary = json.loads(out)
    assert code == 0 and set(summary["regions"]) == {"TW"}
    assert summary["regions"]["TW"]["games"] == 3
    assert summary["cutoff"] == "2026-06-01T00:00:00Z"
    assert summary["model"]["params"] == {"min_sales": 2, "history": "TW+US"}


def test_does_not_take_the_writer_lock(config_path):
    (config_path.parent / "data" / ".lock").write_text("4242\n", encoding="utf-8")
    code, _, err = run("backtest", "--region", "TW", "--apps-limit", "2", "--config", str(config_path))
    assert code == cli.EXIT_OK, err


@pytest.mark.parametrize("argv", [("--param", "min_sales=0"), ("--model", "nope"), ("--cutoff", "someday")])
def test_bad_arguments_exit_1(config_path, argv):
    code, _, err = run("backtest", *argv, "--config", str(config_path))
    assert code == cli.EXIT_FAILED and err


def test_split(config_path):
    """004 contracts/cli.md: --split scores one part; the summary and the result say which."""
    _, out, _ = run("backtest", "--json", "--region", "TW", "--config", str(config_path))
    full = json.loads(out)
    code, out, err = run("backtest", "--json", "--region", "TW", "--split", "tuning", "--config", str(config_path))
    assert code == cli.EXIT_OK, err
    tuning = json.loads(out)
    assert tuning["split"] == "tuning" and full["split"] == "all"
    assert 0 < tuning["regions"]["TW"]["games"] < full["regions"]["TW"]["games"]
    result = json.loads(open(tuning["result"], encoding="utf-8").read())
    assert result["dataset"]["split"]["name"] == "tuning"


def test_unknown_split_is_an_argument_error(config_path):
    with pytest.raises(SystemExit):
        run("backtest", "--split", "test", "--config", str(config_path))


def test_summary_shows_the_finished_only_line(config_path):
    """feature 008 contracts/cli.md: finished-only Brier and the p >= 0.7 excess, per region."""
    code, out, _ = run("backtest", "--json", "--region", "TW", "--config", str(config_path))
    finished = json.loads(out)["finished"]["TW"]
    assert code == 0 and set(finished) == {"units", "brier", "high_excess_pp"}
    assert finished["units"] > 0 and finished["brier"] is not None
