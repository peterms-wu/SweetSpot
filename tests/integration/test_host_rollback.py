"""A failure after the settings file was changed rolls back the settings file, the HTML report and the extension
data file; an official record report already saved is kept (feature 015 tasks T013; spec FR-009, SC-004; plan D5,
analyze C1)."""

import gzip
import json

import pytest

from sweetspot import commands
from sweetspot.decision import records
from sweetspot.host import service
from tests.forecast_builders import dt
from tests.host_builders import APP, make_env
from tests.report_builders import run_report

DAY1, DAY2 = "2025-08-01T12:00", "2025-08-02T12:00"
CHOOSE = {"v": 1, "cmd": "choose", "app": APP, "option": "bundle/900"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    assert run_report(env.config)[0] == 0
    monkeypatch.setattr(commands, "NOW", lambda: dt(DAY1))
    return env


def files(env):
    return env.toml(), env.report.read_bytes(), env.ext_data.read_bytes()


def boom(*args, **kwargs):
    raise RuntimeError("injected")


def test_the_settings_file_cannot_be_written(env, monkeypatch):
    before, old_records = files(env), env.records()
    monkeypatch.setattr(service, "_write_atomic", boom)
    reply = service.handle(CHOOSE, config_path=env.config)
    assert (reply["ok"], reply["code"], reply["step"]) == (False, "config-write", "config-write")
    assert reply["message"].startswith("設定檔寫入失敗（RuntimeError: injected）")
    assert files(env) == before and env.records() == old_records
    assert not list(env.root.glob("sweetspot.toml.*"))                  # no temporary file left


def test_the_report_fails(env, monkeypatch):
    before, old_records = files(env), env.records()
    monkeypatch.setattr(commands, "run_decisions", boom)
    reply = service.handle(CHOOSE, config_path=env.config)
    assert (reply["ok"], reply["code"], reply["step"]) == (False, "report", "report")
    assert reply["message"] == "報告產生失敗（RuntimeError: injected），設定檔與報告已還原"
    assert files(env) == before and env.records() == old_records


def test_the_record_is_not_saved(env, monkeypatch):
    before, old_records = files(env), env.records()
    monkeypatch.setattr(records, "write_record", boom)
    reply = service.handle(CHOOSE, config_path=env.config)
    assert (reply["code"], reply["step"]) == ("record", "record")
    assert reply["message"] == "正式紀錄沒有保存（RuntimeError: injected），設定檔與報告已還原"
    assert files(env) == before and env.records() == old_records


def test_the_data_file_is_not_written_but_the_saved_record_stays(env, monkeypatch):
    before, old_records = files(env), env.records()
    monkeypatch.setattr(commands.extension_data, "build", boom)
    reply = service.handle(CHOOSE, config_path=env.config)
    assert (reply["code"], reply["step"]) == ("extension-data", "extension-data")
    assert reply["message"] == "擴充功能資料沒有寫入（RuntimeError: injected），設定檔與報告已還原"
    assert files(env) == before                                    # the HTML report was written, then restored
    new = sorted(set(env.records()) - set(old_records))
    assert len(new) == 1 and env.records()[:-1] == old_records     # constitution IV: the official record is kept
    with gzip.open(env.forecasts / new[0]) as f:
        chosen = next(d for d in json.load(f)["decisions"] if d["app_id"] == APP)
    assert chosen["version"]["basis"] == "user"                    # it records the run that happened
    monkeypatch.undo()                                             # the next report marks the version change back
    env2_now = "2025-08-02T12:00"
    monkeypatch.setattr(commands, "NOW", lambda: dt(env2_now))
    from sweetspot import cli
    monkeypatch.setattr(cli, "load_secrets", lambda: cli.Secrets())
    assert run_report(env.config)[0] == 0
    with gzip.open(env.forecasts / env.records()[-1]) as f:
        back = next(d for d in json.load(f)["decisions"] if d["app_id"] == APP)
    assert back["change"]["version"]["cause"] == "unset"


def test_restoring_fails_and_the_original_is_kept_aside(env, monkeypatch):
    original = env.toml()
    monkeypatch.setattr(commands.extension_data, "build", boom)
    real = service._write_atomic
    calls = []

    def first_only(path, data):
        calls.append(path)
        if len(calls) > 1 and path == env.config:
            raise PermissionError("locked by an editor")
        real(path, data)
    monkeypatch.setattr(service, "_write_atomic", first_only)
    reply = service.handle(CHOOSE, config_path=env.config)
    assert (reply["ok"], reply["code"]) == (False, "restore")
    kept = list((env.data / "host").glob("restore-*.toml"))
    assert len(kept) == 1 and kept[0].read_bytes() == original
    assert reply["message"] == f"還原失敗：請手動檢查 sweetspot.toml（原本的內容在 data/host/{kept[0].name}）"


def test_a_per_game_problem_is_not_a_failure(env, monkeypatch):
    # a day before DAY1 (Taipei) and newer than the baseline, so the comparison reads it first and skips it:
    # exit 2, nothing failed
    (env.forecasts / "20250731T130000Z.json.gz").write_bytes(b"not a record")
    reply = service.handle(CHOOSE, config_path=env.config)
    assert reply["ok"] and reply["changed"] and reply["partial"] is True
    assert env.extension_game()["option"]["user"] is True


def test_locks_are_released_after_a_failure(env, monkeypatch):
    monkeypatch.setattr(commands, "run_decisions", boom)
    service.handle(CHOOSE, config_path=env.config)
    assert not (env.data / ".lock").exists() and not (env.data / ".host.lock").exists()
    monkeypatch.undo()
    monkeypatch.setattr(commands, "NOW", lambda: dt(DAY2))
    from sweetspot import cli
    monkeypatch.setattr(cli, "load_secrets", lambda: cli.Secrets())
    assert service.handle(CHOOSE, config_path=env.config)["ok"]
