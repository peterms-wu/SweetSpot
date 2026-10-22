"""004 contracts/cli.md: `sweetspot grid` (tasks T019)."""

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
    # apps 2, 4 and 12 are in the tuning part; give US history to some of them
    games = [GameSpec(a, tw=tw(a), us=us(a) if a % 2 == 0 or a == 1 else [],
                      known_until={"TW": "2026-09-24", "US": "2026-09-24"}) for a in (1, 2, 3, 4, 5, 12)]
    build_db(tmp_path / "data" / "sweetspot.db", games, calendar=EXTRA_CALENDAR + BASIC_CALENDAR)
    return path


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(list(argv), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_grid_runs_every_setting_and_records_the_choice(config_path, tmp_path):
    record = tmp_path / "records.md"
    code, out, err = run("grid", "--model", "seasonal-record", "--grid", "half_life=0,2", "--grid",
                         "hazard_history=TW,TW+US", "--param", "min_sales=2", "--record-to", str(record), "--json",
                         "--config", str(config_path))
    assert code in (cli.EXIT_OK, cli.EXIT_PARTIAL), err
    summary = json.loads(out)
    assert summary["split"] == "tuning" and len(summary["rows"]) == 4
    assert all(r["params"]["min_sales"] == 2 for r in summary["rows"])
    files = list((config_path.parent / "data" / "backtests").glob("*.json"))
    assert len(files) == 1 + 4 + 2                     # current (both regions), 4 TW runs, 2 US runs
    text = record.read_text(encoding="utf-8")
    assert "seasonal-record 調參組網格" in text and text.count("| `") == 4
    assert "網格 1/4：" in err
    if code == cli.EXIT_OK:
        assert summary["chosen"] in [r["params"] for r in summary["rows"]]


def test_grid_refuses_the_validation_split(config_path):
    code, _, err = run("grid", "--model", "seasonal-record", "--grid", "half_life=0", "--split", "validation",
                       "--config", str(config_path))
    assert code == cli.EXIT_FAILED and "FR-011" in err


def test_grid_needs_a_well_formed_grid(config_path):
    code, _, err = run("grid", "--model", "seasonal-record", "--grid", "half_life", "--config", str(config_path))
    assert code == cli.EXIT_FAILED and "--grid" in err
