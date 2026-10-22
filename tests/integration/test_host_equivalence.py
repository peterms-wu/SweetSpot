"""Choosing from the panel gives what writing the same line by hand and running `report` gives (feature 015 tasks
T012; spec FR-012, SC-005)."""

import gzip
import json

from sweetspot.host import service
from tests.forecast_builders import dt
from tests.host_builders import APP, make_env
from tests.report_builders import run_report

DAY1 = "2025-08-01T12:00"


def outputs(env):
    data = json.loads(env.ext_data.read_text(encoding="utf-8"))
    with gzip.open(env.forecasts / env.records()[-1]) as f:
        record = json.load(f)
    for payload in (data, record):
        payload.pop("generated_at")
    assert data.pop("config_path") == str(env.config.resolve())       # each environment's own folder
    return data, record, env.records()


def two_envs(tmp_path, monkeypatch):
    from sweetspot import commands

    a = make_env(tmp_path / "a", monkeypatch)
    b = make_env(tmp_path / "b", monkeypatch)
    for env in (a, b):
        assert run_report(env.config)[0] == 0
    monkeypatch.setattr(commands, "NOW", lambda: dt(DAY1))
    return a, b


def test_choose_equals_the_hand_written_line(tmp_path, monkeypatch):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a, b = two_envs(tmp_path, monkeypatch)
    assert service.handle({"v": 1, "cmd": "choose", "app": APP, "option": "bundle/900"}, config_path=a.config)["changed"]
    line = json.loads(b.ext_data.read_text(encoding="utf-8"))
    config_line = next(v["manual"] for g in line["games"] if g["app_id"] == APP for v in g["versions"]
                       if v["action"] == "choose")
    assert config_line == '1 = "bundle/900"'                            # the report's own config line
    b.config.write_text(b.config.read_text(encoding="utf-8") + config_line + "\n", encoding="utf-8")
    assert run_report(b.config)[0] == 0
    assert outputs(a) == outputs(b)


def test_reset_equals_deleting_the_line_by_hand(tmp_path, monkeypatch):
    from sweetspot import commands

    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a, b = two_envs(tmp_path, monkeypatch)
    for env in (a, b):                                   # both start from the same choice
        env.config.write_text(env.config.read_text(encoding="utf-8") + '1 = "bundle/900"\n', encoding="utf-8")
        assert run_report(env.config)[0] == 0
    monkeypatch.setattr(commands, "NOW", lambda: dt("2025-08-02T12:00"))
    assert service.handle({"v": 1, "cmd": "reset", "app": APP}, config_path=a.config)["changed"]
    b.config.write_text(b.config.read_text(encoding="utf-8").replace('1 = "bundle/900"\n', ""), encoding="utf-8")
    assert run_report(b.config)[0] == 0
    assert outputs(a) == outputs(b)
