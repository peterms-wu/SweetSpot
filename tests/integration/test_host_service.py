"""The local program's choose / reset / status flow (feature 015 tasks T011; spec US1 scenarios 1-4, FR-003,
FR-007, FR-008, FR-020; contracts/native-host.md)."""

import gzip
import json
import logging

import pytest

from sweetspot import __version__, commands
from tests.config_builders import TEST_TOML
from sweetspot.host import service
from tests.forecast_builders import dt
from tests.host_builders import APP, GONE, NAMES, make_env
from tests.report_builders import run_report

DAY1, DAY2, DAY3 = "2025-08-01T12:00", "2025-08-02T12:00", "2025-08-03T12:00"
EDITION_LINE = '1 = "bundle/900"   # 《Cyber：終極版》（{date} 從 Steam 頁面指定）\n'


@pytest.fixture
def env(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    assert run_report(env.config)[0] == 0                  # the baseline: the report and the data file exist
    return env


def at(monkeypatch, moment):
    monkeypatch.setattr(commands, "NOW", lambda: dt(moment))


def ask(env, cmd, **fields):
    return service.handle({"v": 1, "cmd": cmd, "app": APP, **fields}, config_path=env.config)


def latest_decision(env, app=APP):
    with gzip.open(env.forecasts / env.records()[-1]) as f:
        return next(d for d in json.load(f)["decisions"] if d["app_id"] == app)


def test_choose_an_edition_adds_one_line_and_reruns_the_official_report(env, monkeypatch):
    at(monkeypatch, DAY1)
    before = env.records()
    reply = ask(env, "choose", option="bundle/900")
    assert {k: v for k, v in reply.items() if k != "seconds"} == {
        "v": 1, "ok": True, "cmd": "choose", "app": APP, "option": "bundle/900", "changed": True, "partial": False}
    assert isinstance(reply["seconds"], float)
    assert env.toml().decode("utf-8") == TEST_TOML + EDITION_LINE.format(date="2025-08-01")
    assert len(env.records()) == len(before) + 1                         # an official run: a record (clarify Q1)
    game = env.extension_game()
    assert game["option"] == {"kind": "bundle", "id": 900, "name": NAMES[("bundle", 900)], "user": True}
    assert game["versions"][0]["tracked"] and (game["versions"][0]["kind"], game["versions"][0]["id"]) == ("bundle", 900)
    assert "《Cyber：終極版》（使用者指定）" in env.report.read_text(encoding="utf-8")
    assert latest_decision(env)["change"]["version"]["cause"] == "user"   # FR-007: the change marker


def test_the_data_file_names_the_settings_file_it_was_made_with(env):
    """The official report writes the settings file's full path for the extension's steps by hand (2026-10-14)."""
    data = json.loads(env.ext_data.read_text(encoding="utf-8"))
    assert data["config_path"] == str(env.config.resolve())


def test_reset_removes_the_line_and_gives_back_the_original_file(env, monkeypatch):
    at(monkeypatch, DAY1)
    ask(env, "choose", option="bundle/900")
    at(monkeypatch, DAY2)
    reply = ask(env, "reset")
    assert reply["ok"] and reply["changed"] and reply["cmd"] == "reset"
    assert env.toml().decode("utf-8") == TEST_TOML
    assert env.extension_game()["option"]["user"] is False
    assert latest_decision(env)["change"]["version"]["cause"] == "unset"


def test_choosing_the_steam_default_is_a_reset(env, monkeypatch):
    at(monkeypatch, DAY1)
    ask(env, "choose", option="bundle/900")
    at(monkeypatch, DAY2)
    reply = ask(env, "choose", option="sub/100")
    assert reply["ok"] and reply["changed"] and (reply["cmd"], reply["option"]) == ("choose", "sub/100")
    assert env.toml().decode("utf-8") == TEST_TOML                 # FR-003: no line equal to the default


def test_an_existing_line_is_replaced_not_duplicated(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch, toml=TEST_TOML + '1 = "sub/902"   # an edition that failed its check\n')
    assert run_report(env.config)[0] in (0, 2)
    at(monkeypatch, DAY1)
    assert ask(env, "choose", option="bundle/900")["changed"]
    assert env.toml().decode("utf-8") == TEST_TOML + EDITION_LINE.format(date="2025-08-01")


def test_nothing_to_change_runs_no_report(env, monkeypatch):
    at(monkeypatch, DAY1)
    assert ask(env, "reset") == {"v": 1, "ok": True, "cmd": "reset", "app": APP, "changed": False}
    ask(env, "choose", option="bundle/900")
    records, page, data = env.records(), env.report.read_bytes(), env.ext_data.read_bytes()
    at(monkeypatch, DAY2)
    assert ask(env, "choose", option="bundle/900") == {
        "v": 1, "ok": True, "cmd": "choose", "app": APP, "option": "bundle/900", "changed": False}
    assert (env.records(), env.report.read_bytes(), env.ext_data.read_bytes()) == (records, page, data)


def test_status_reports_the_choice_in_the_settings_file(env, monkeypatch):
    assert ask(env, "status") == {"v": 1, "ok": True, "cmd": "status", "app": APP, "choice": None, "config_ok": True,
                                  "host": __version__}
    at(monkeypatch, DAY1)
    ask(env, "choose", option="bundle/900")
    assert ask(env, "status")["choice"] == "bundle/900"
    reply = service.handle({"v": 1, "cmd": "status", "app": GONE}, config_path=env.config)
    assert reply["ok"] and reply["choice"] is None


def test_a_game_removed_but_still_tracked_can_be_chosen(env, monkeypatch):
    """014 T074 (009 spec Edge Case: a game removed from the wishlist but still tracked keeps its choice): the local
    program refused it as not-tracked, unlike the daily update."""
    import sqlite3

    with sqlite3.connect(env.db) as conn:
        conn.execute("UPDATE wishlist_membership SET state = 'removed_tracking' WHERE app_id = ?", (APP,))
    at(monkeypatch, DAY1)
    reply = ask(env, "choose", option="bundle/900")
    assert reply["ok"] is True and reply["changed"] is True, reply


def test_status_on_a_broken_settings_file(env):
    env.config.write_bytes(env.toml() + b"\n[broken\n")
    reply = ask(env, "status")
    assert reply["ok"] and reply["config_ok"] is False and reply["choice"] is None
    assert reply["message"].startswith("設定檔有錯誤，請先修正 sweetspot.toml")


def test_every_request_is_one_log_line(env, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="sweetspot.host")
    at(monkeypatch, DAY1)
    ask(env, "choose", option="bundle/900")
    ask(env, "status")
    ask(env, "choose", option="sub/902")
    lines = [r.getMessage() for r in caplog.records if r.name == "sweetspot.host"]
    assert len(lines) == 3
    assert lines[0].startswith("host choose app=1 option=bundle/900 result=ok changed=true seconds=")
    assert lines[1] == "host status app=1 result=ok choice=bundle/900"
    assert lines[2] == "host choose app=1 option=sub/902 result=rejected code=not-choosable"
