"""`sweetspot ns-backtest`, `ns-grid`, `ns-compare` (feature 007 contracts/cli-and-report.md; tasks T014)."""

import io
import json
import re
from datetime import timedelta

import pytest

from sweetspot import cli
from tests.config_builders import TEST_TOML
from sweetspot.forecast.backtest.split import part
from tests.forecast_builders import BASIC_CALENDAR, GameSpec, build_db, dt


def promos(app):
    """A promotion every 45-65 days (some fall inside seasonal sales)."""
    rows = [("2024-12-11", 0)]
    t = dt("2025-01-20")
    while t < dt("2026-09-01"):
        rows += [(t.isoformat(), 40 + 10 * (app % 3)), ((t + timedelta(days=5)).isoformat(), 0)]
        t += timedelta(days=45 + 10 * (app % 3))
    return rows


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_secrets", lambda: cli.Secrets())
    path = tmp_path / "sweetspot.toml"
    path.write_text(TEST_TOML, encoding="utf-8")
    games = [GameSpec(a, tw=promos(a), known_until={"TW": "2026-09-24"}) for a in range(1, 13)]
    build_db(tmp_path / "data" / "sweetspot.db", games, calendar=BASIC_CALENDAR)
    return path


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(list(argv), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_before_adoption_the_defaults_are_used_and_said_so(config_path, monkeypatch):
    from sweetspot.forecast import nonseasonal
    monkeypatch.setattr(nonseasonal, "CURRENT_NS_MODEL", None)
    code, out, err = run("ns-backtest", "--split", "tuning", "--no-earlier", "--json", "--config", str(config_path))
    assert code == cli.EXIT_OK, err
    s = json.loads(out)
    assert s["model"]["params"] == {"smoothing": 2, "history": "TW+US", "clock": True}
    assert "尚未採用" in s["model_note"]


def test_ns_backtest_writes_a_result(config_path):
    code, out, err = run("ns-backtest", "--split", "tuning", "--no-earlier", "--json", "--config", str(config_path))
    assert code == cli.EXIT_OK, err
    s = json.loads(out)
    assert s["model"]["params"] == {"smoothing": 2, "history": "TW+US", "clock": True}     # the adopted model
    assert s["model_note"] is None
    assert s["split"] == "tuning" and s["games"] == sum(part(a) == "tuning" for a in range(1, 13))
    for key in ("result", "as_of_count", "units", "brier", "reference_brier", "errors", "seconds"):
        assert key in s
    name = s["result"].replace("\\", "/").rsplit("/", 1)[-1]
    assert re.fullmatch(r"\d{8}T\d{6}Z_ns-non-seasonal-1\.0\.0_[0-9a-f]{6}_TW_[0-9a-f]{8}\.json", name)
    data = json.loads((config_path.parent / "data" / "backtests" / name).read_text(encoding="utf-8"))
    assert data["schema"] == "steamsage.ns-backtest/1" and data["earlier"] is None


def test_ns_compare_against_the_reference(config_path, tmp_path):
    code, out, _ = run("ns-backtest", "--split", "tuning", "--no-earlier", "--json", "--config", str(config_path))
    path = json.loads(out)["result"]
    record = tmp_path / "records.md"
    code, out, err = run("ns-compare", path, "--record-to", str(record), "--json", "--config", str(config_path))
    s = json.loads(out)
    assert s["verdict"] is None and s["against"] == "整體比例"
    assert code == cli.EXIT_PARTIAL                                   # not judged outside the validation part
    assert "非季節" in record.read_text(encoding="utf-8")


def test_ns_grid_records_every_setting(config_path, tmp_path):
    record = tmp_path / "records.md"
    code, out, err = run("ns-grid", "--grid", "smoothing=1,5", "--grid", "clock=true,false", "--no-earlier",
                         "--record-to", str(record), "--json", "--config", str(config_path))
    assert code in (cli.EXIT_OK, cli.EXIT_PARTIAL), err
    s = json.loads(out)
    assert s["split"] == "tuning" and len(s["rows"]) == 4
    assert s["chosen"] in [r["params"] for r in s["rows"]]
    assert "non-seasonal 調參組網格" in record.read_text(encoding="utf-8")
    assert "網格 1/4" in err


def test_ns_grid_refuses_the_validation_split(config_path):
    code, _, err = run("ns-grid", "--grid", "smoothing=1", "--split", "validation", "--config", str(config_path))
    assert code == cli.EXIT_FAILED and "驗證組" in err


def test_ns_compare_needs_an_attempt_on_the_validation_part(config_path):
    code, out, _ = run("ns-backtest", "--split", "validation", "--no-earlier", "--json", "--config", str(config_path))
    path = json.loads(out)["result"]
    code, _, err = run("ns-compare", path, "--record", "--config", str(config_path))
    assert code == cli.EXIT_FAILED and "--attempt" in err
