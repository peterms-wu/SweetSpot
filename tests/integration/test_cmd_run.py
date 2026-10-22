"""更新資料.cmd and 背景更新.cmd run for real by cmd.exe, with a fake uv (014 T059).

cmd.exe reads a UTF-8 batch file after `chcp 65001` by a byte position it sometimes gets wrong: after some lines
holding Chinese (two long rem lines in a row; a rem before a set of a Chinese value) it starts the next line in the
middle and runs the rest as a command. Reading the text (tests/unit/test_cmd_scripts.py) cannot see that, so the
scripts run here, in a temporary folder, and nothing may be left on stderr.

The fake uv is a copy of this Python's python.exe named uv.exe: cmd.exe treats it as the real uv.exe (a fake uv.cmd
would need `call`). `uv run sweetspot update` then runs the file named `run` in the folder, which records the call
and exits with the code the test asked for.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows batch files")

ROOT = Path(__file__).resolve().parents[2]
BASE = Path(sys._base_executable).parent

RUN = """import json, sys
open("calls.txt", "a", encoding="utf-8").write(" ".join(sys.argv[1:]) + "\\n")
codes = json.loads(open("codes.json", encoding="utf-8").read())
sys.exit(codes.get(" ".join(sys.argv[1:3]), 0))
"""


@pytest.fixture(scope="module")
def fake_uv(tmp_path_factory):
    bin_ = tmp_path_factory.mktemp("bin")
    shutil.copy(BASE / "python.exe", bin_ / "uv.exe")
    for dll in BASE.glob("*.dll"):
        shutil.copy(dll, bin_)
    return bin_


def run(name, folder, fake_uv, codes, *args, settings=True):
    (folder / name).write_bytes((ROOT / name).read_bytes())
    (folder / "run").write_text(RUN, encoding="utf-8")
    (folder / "codes.json").write_text(json.dumps(codes), encoding="utf-8")
    if settings:
        (folder / "sweetspot.toml").write_text("", encoding="utf-8")
    env = {**os.environ, "PATH": str(fake_uv) + os.pathsep + os.environ["PATH"], "PYTHONHOME": str(BASE)}
    done = subprocess.run(["cmd.exe", "/d", "/c", str(folder / name), *args], env=env, capture_output=True,
                          stdin=subprocess.DEVNULL, timeout=60)
    calls = (folder / "calls.txt").read_text(encoding="utf-8").splitlines() if (folder / "calls.txt").exists() else []
    return done, calls


def last_log_line(folder):
    return (folder / "data" / "logs" / "background-update.log").read_bytes().decode("utf-8").splitlines()[-1]


def test_the_fake_uv_is_what_cmd_runs(tmp_path, fake_uv):
    done, calls = run("背景更新.cmd", tmp_path, fake_uv, {})
    assert calls and calls[0] == "sweetspot update", done


def test_background_update_runs_every_line_as_written(tmp_path, fake_uv):
    done, calls = run("背景更新.cmd", tmp_path, fake_uv, {})
    assert done.stderr == b"", done.stderr.decode("utf-8", "replace")
    assert calls == ["sweetspot update", "sweetspot report --update-exit 0", r"python scripts\backup_db.py"]
    assert done.returncode == 0 and last_log_line(tmp_path).endswith("update 0，report 0，backup 0，整體 0 =====")


def test_background_update_skips_the_backup_when_not_set_up(tmp_path, fake_uv):
    """014 T059 (contracts/cli.md §2): not set up, nothing to back up; backup_db.py would leave a daily log."""
    done, calls = run("背景更新.cmd", tmp_path, fake_uv, {"sweetspot update": 5, "sweetspot report": 5},
                      settings=False)
    assert done.stderr == b"", done.stderr.decode("utf-8", "replace")
    assert calls == ["sweetspot update", "sweetspot report --update-exit 5"]
    assert done.returncode == 5
    assert last_log_line(tmp_path).endswith("update 5，report 5，backup 略過（還沒設定），整體 5 =====")


def test_background_update_keeps_the_worse_code(tmp_path, fake_uv):
    done, calls = run("背景更新.cmd", tmp_path, fake_uv, {"sweetspot update": 2, "python scripts\\backup_db.py": 1})
    assert done.stderr == b"" and len(calls) == 3
    assert done.returncode == 2 and last_log_line(tmp_path).endswith("update 2，report 0，backup 1，整體 2 =====")


@pytest.mark.parametrize("name", ["背景更新.cmd", "更新資料.cmd"])
def test_an_update_code_no_one_knows_is_a_failure(tmp_path, fake_uv, name):
    """014 T069: a killed update ends with a Windows status (here 7); the overall code was 0 (no line matched)."""
    done, calls = run(name, tmp_path, fake_uv, {"sweetspot update": 7}, *(["--no-pause"] if name == "更新資料.cmd" else []))
    assert done.stderr == b"", done.stderr.decode("utf-8", "replace")
    assert any(c.startswith("sweetspot report") and c.endswith("--update-exit 7") for c in calls)
    assert done.returncode == 1
    if name == "更新資料.cmd":
        assert "資料更新沒有正常結束（代碼 7）" in done.stdout.decode("utf-8")


def test_double_click_update_runs_every_line_as_written(tmp_path, fake_uv):
    done, calls = run("更新資料.cmd", tmp_path, fake_uv, {}, "--no-pause")
    assert done.stderr == b"", done.stderr.decode("utf-8", "replace")
    assert calls == ["sweetspot update", "sweetspot report --open --update-exit 0"]
    assert done.returncode == 0 and "更新完成，報告已開啟。" in done.stdout.decode("utf-8")


def test_double_click_update_asks_for_the_wishlist_first(tmp_path, fake_uv):
    done, calls = run("更新資料.cmd", tmp_path, fake_uv, {"sweetspot setup": 5}, "--no-pause", settings=False)
    assert done.stderr == b"" and calls == ["sweetspot setup"] and done.returncode == 5
