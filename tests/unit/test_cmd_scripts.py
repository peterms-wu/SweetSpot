"""更新資料.cmd and 背景更新.cmd (feature 016 contracts/migrate.md §5): the new command name, exit 4 and the order of
the overall exit code 1 > 4 > 3 > 2 > 0."""

import re
from pathlib import Path

import pytest

from sweetspot import legacy
from sweetspot.decision import engine

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ["更新資料.cmd", "背景更新.cmd"]


def read(name: str) -> str:
    return (ROOT / name).read_bytes().decode("utf-8")


@pytest.mark.parametrize("name", SCRIPTS)
def test_calls_the_new_command(name):
    text = read(name)
    assert text.splitlines()[2] == "chcp 65001 >nul"
    calls = re.findall(r"^uv run (\S+)", text, re.M)
    assert calls and set(calls) <= {"sweetspot", "python"}
    assert "uv run sweetspot update" in text and "uv run sweetspot report" in text


@pytest.mark.parametrize("name", SCRIPTS)
def test_overall_exit_code_order(name):
    """Later lines win, so the assignments must go from the mildest to the most serious: 2, 3, 4, 5, 1
    (014: 5 = not set up yet, one step before 4)."""
    lines = [line.strip() for line in read(name).splitlines()]
    start = lines.index('set "final=0"')
    sets = [re.search(r'set "final=(\d)"', line).group(1) for line in lines[start + 1:]
            if re.search(r'set "final=(\d)"', line)]
    order = [s for i, s in enumerate(sets) if s not in sets[:i]]
    assert order == ["2", "3", "4", "5", "1"]
    for n in ("4", "5"):
        assert f'if "%code%"=="{n}" set "final={n}"' in lines and f'if "%rcode%"=="{n}" set "final={n}"' in lines
    assert "1 > 5 > 4 > 3 > 2 > 0" in read(name)


def test_double_click_script_runs_setup_when_there_are_no_settings():
    """014 contracts/cli.md §5: no sweetspot.toml -> setup first; anything but 0 stops before the update."""
    lines = [line.strip() for line in read("更新資料.cmd").splitlines()]
    check = lines.index('if exist "sweetspot.toml" goto :ready')
    assert lines[check + 1] == "uv run sweetspot setup"
    assert lines[check + 2] == 'set "scode=%errorlevel%"'
    assert lines[check + 3] == 'if not "%scode%"=="0" ('
    block = lines[check + 4:lines.index(":ready")]
    assert "exit /b %scode%" in block and 'if not "%~1"=="--no-pause" pause' in block
    assert lines.index(":ready") < lines.index("uv run sweetspot update")


def test_background_script_says_it_is_in_the_background():
    """014 research R2: the background is told by a variable, not by isatty() of a headless console."""
    lines = [line.strip() for line in read("背景更新.cmd").splitlines()]
    assert 'set "SWEETSPOT_BACKGROUND=1"' in lines
    assert lines.index('set "SWEETSPOT_BACKGROUND=1"') < lines.index('uv run sweetspot update >> "%log%" 2>&1')
    assert "sweetspot setup" not in read("背景更新.cmd")


def test_background_script_skips_the_backup_when_not_set_up():
    """014 T059 (contracts/cli.md §2): with no settings file the Python side leaves no daily log; backup_db.py would
    write one. A goto, not an if (...) block: %errorlevel% inside a block is read before the block runs."""
    lines = [line.strip() for line in read("背景更新.cmd").splitlines()]
    backup = lines.index(r'uv run python scripts\backup_db.py >> "%log%" 2>&1')
    assert lines[backup - 1] == 'if "%code%"=="5" goto :overall'
    assert lines[backup - 2].startswith('set "bcode=') and "%" not in lines[backup - 2]
    assert lines[backup + 1] == 'set "bcode=%errorlevel%"' and lines[backup + 2] == ":overall"
    assert lines.index(":overall") < lines.index('set "final=0"')


def tracked_batch_files() -> list[str]:
    import subprocess

    out = subprocess.run(["git", "ls-files", "-z", "*.cmd", "*.bat"], cwd=ROOT, capture_output=True, check=True).stdout
    return sorted(filter(None, out.decode("utf-8").split("\0")))


def test_every_batch_file_is_found():
    assert set(SCRIPTS) <= set(tracked_batch_files())


@pytest.mark.parametrize("name", tracked_batch_files())
def test_rem_lines_are_ascii(name):
    """014 T059: after `chcp 65001` cmd.exe sometimes starts the line after a Chinese rem line in its middle and runs
    the rest as a command; which line depends on the length of the folder the script is in. Seen in 背景更新.cmd:
    the third header line ran as a command, and `set "bcode=略過…"` after a Chinese rem lost its value. With ASCII rem
    lines no misread showed in 120 folder lengths (tests/integration/test_cmd_run.py runs the scripts)."""
    rems = [line for line in read(name).splitlines() if line.lstrip().lower().startswith(("rem ", "::"))]
    assert rems and all(line.isascii() for line in rems), [line for line in rems if not line.isascii()]


def test_double_click_script_explains_exit_4():
    text = read("更新資料.cmd")
    assert f'if "%code%"=="4" echo 找到舊名稱的檔案，請先執行搬家：{legacy.MIGRATE_COMMAND}' in text


def test_the_migration_command_is_spelled_the_same_everywhere():
    """The hint lives in sweetspot.legacy; the scripts and README cannot import it, so they are pinned to it here."""
    assert legacy.MIGRATE_COMMAND == "uv run sweetspot migrate"
    assert legacy.refusal(Path("x.toml")).endswith(f"請先執行搬家：{legacy.MIGRATE_COMMAND}")
    assert legacy.MIGRATE_COMMAND in engine.REFRESH_NOTES[4]
    assert legacy.MIGRATE_COMMAND in read("README.md")
    for name in SCRIPTS:
        found = re.findall(r"uv run sweetspot migrate\S*", read(name))
        assert set(found) <= {legacy.MIGRATE_COMMAND}, name
