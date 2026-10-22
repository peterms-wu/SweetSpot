"""The local program and the locks (feature 015 tasks T026; spec US3 scenario 3, FR-018, FR-019, SC-007).

choose / reset hold data/.host.lock (one choice at a time) and data/.lock (the writer lock the daily update
holds) for the whole change; a lock held by a living process is an immediate refusal that changes nothing.
"""

import os
import subprocess
import sys
import time

import pytest

from sweetspot import commands
from sweetspot.host import service
from tests.forecast_builders import dt
from tests.host_builders import APP, make_env
from tests.report_builders import run_report


@pytest.fixture
def env(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    assert run_report(env.config)[0] == 0
    monkeypatch.setattr(commands, "NOW", lambda: dt("2025-08-01T12:00"))
    return env


@pytest.fixture
def living():
    """A process that is alive for the test: its pid owns a lock."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        yield proc.pid
    finally:
        proc.kill()
        proc.wait()


def dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def hold(path, pid):
    path.write_text(f"{pid}\n2025-08-01T11:59:00Z\n", encoding="utf-8")


def choose(env):
    return service.handle({"v": 1, "cmd": "choose", "app": APP, "option": "bundle/900"}, config_path=env.config)


@pytest.mark.parametrize("lock, code", [(".lock", "busy-update"), (".host.lock", "busy-host")])
def test_a_living_owner_is_an_immediate_refusal(env, living, lock, code):
    hold(env.data / lock, living)
    before = env.snapshot()
    started = time.monotonic()
    reply = choose(env)
    assert time.monotonic() - started < 1.0                            # SC-007
    assert reply["ok"] is False and reply["code"] == code
    assert reply["message"] == service.MESSAGES[code]
    assert env.snapshot() == before
    assert (env.data / lock).read_text(encoding="utf-8").startswith(f"{living}\n")   # still theirs
    other = ".host.lock" if lock == ".lock" else ".lock"
    assert not (env.data / other).exists()                             # the one we took is given back


def test_reset_waits_for_the_update_too(env, living):
    env.config.write_text(env.config.read_text(encoding="utf-8").replace(
        "[purchase_options]\n", '[purchase_options]\n1 = "bundle/900"\n'), encoding="utf-8")
    hold(env.data / ".lock", living)
    before = env.snapshot()
    reply = service.handle({"v": 1, "cmd": "reset", "app": APP}, config_path=env.config)
    assert reply["code"] == "busy-update" and env.snapshot() == before


def test_status_needs_no_lock(env, living):
    hold(env.data / ".lock", living)
    hold(env.data / ".host.lock", living)
    reply = service.handle({"v": 1, "cmd": "status", "app": APP}, config_path=env.config)
    assert reply["ok"] is True and reply["choice"] is None


@pytest.mark.parametrize("lock", [".lock", ".host.lock"])
def test_a_lock_whose_owner_is_gone_is_taken_over(env, lock):
    hold(env.data / lock, dead_pid())
    reply = choose(env)
    assert reply["ok"] is True and reply["changed"] is True
    assert not (env.data / lock).exists()


def both_held(env) -> bool:
    mine = f"{os.getpid()}\n"
    return all((env.data / name).read_text(encoding="utf-8").startswith(mine) for name in (".lock", ".host.lock"))


def test_both_locks_are_held_while_the_report_runs_and_released_after(env, monkeypatch):
    seen = []
    real = service._run_report

    def watched(config_path):
        seen.append(both_held(env))
        return real(config_path)

    monkeypatch.setattr(service, "_run_report", watched)
    assert choose(env)["ok"] is True
    assert seen == [True]
    assert not (env.data / ".lock").exists() and not (env.data / ".host.lock").exists()


@pytest.mark.parametrize("how", ["exit 1", "exception"])
def test_locks_are_released_after_a_failure(env, monkeypatch, how):
    seen = []

    def failing(config_path):
        seen.append(both_held(env))
        if how == "exception":
            raise RuntimeError("boom")
        return 1, None, "執行失敗：資料庫無法開啟\n"

    monkeypatch.setattr(service, "_run_report", failing)
    before = env.toml()
    reply = choose(env)
    assert reply["ok"] is False and reply["step"] in ("report", "internal")
    assert seen == [True] and env.toml() == before
    assert not (env.data / ".lock").exists() and not (env.data / ".host.lock").exists()
