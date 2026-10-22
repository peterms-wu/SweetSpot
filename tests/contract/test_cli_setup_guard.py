"""014 contracts/cli.md §2: with no settings file, a command that cannot ask refuses with exit 5 and creates nothing;
one that can ask runs the setup first (FR-001, FR-004, SC-004). The 016 old-name refusal (4) still comes first."""

import io
import sqlite3
from pathlib import Path

import pytest

from sweetspot import cli, legacy, setup
from tests.config_builders import TEST_TOML
from tests.contract.test_cli_migrate_guard import minimal_args, subcommands


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(argv, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))


@pytest.fixture
def background(monkeypatch):
    monkeypatch.setenv("SWEETSPOT_BACKGROUND", "1")
    monkeypatch.setattr(setup, "ask", lambda prompt: pytest.fail("must not ask in the background"))


def test_the_table_covers_every_subcommand(tmp_path):
    """The 016 table, enumerated from the parser; `setup` is in it (refused with 4 next to old names) and is
    checked on its own below."""
    assert set(minimal_args(tmp_path)) == subcommands() - {"migrate"}


@pytest.mark.parametrize("command", sorted(set(minimal_args(Path("."))) - {"setup"}))
def test_no_settings_in_the_background_refuses_every_command(tmp_path, background, command):
    home = tmp_path / "home"
    home.mkdir()
    code, _, err = run([command, *minimal_args(tmp_path)[command], "--config", str(home / "sweetspot.toml")])
    assert code == cli.EXIT_NOT_SET_UP == 5
    assert "還沒設定願望清單：請先在視窗中執行 uv run sweetspot setup" in err
    assert files(home) == []                              # no settings, no data/, no log, no lock


def test_stdin_that_is_not_a_terminal_counts_as_background(tmp_path, monkeypatch):
    monkeypatch.delenv("SWEETSPOT_BACKGROUND", raising=False)
    monkeypatch.setattr(setup, "stdin_is_terminal", lambda: False)
    code, _, _ = run(["coverage", "--config", str(tmp_path / "sweetspot.toml")])
    assert code == 5 and files(tmp_path) == []


def test_interactive_runs_setup_then_the_command(tmp_path, monkeypatch):
    monkeypatch.delenv("SWEETSPOT_BACKGROUND", raising=False)
    monkeypatch.setattr(setup, "stdin_is_terminal", lambda: True)
    monkeypatch.setattr(cli, "load_secrets", lambda: cli.Secrets())
    calls = []

    def fake_setup(path, stdout, stderr):
        calls.append(path)
        Path(path).write_text(TEST_TOML, encoding="utf-8")
        return 0

    monkeypatch.setattr(setup, "ensure", fake_setup)
    monkeypatch.setitem(cli.HANDLERS, "coverage", lambda ctx, args: cli.CommandResult(0, {"ran": True}))
    code, out, _ = run(["coverage", "--config", str(tmp_path / "sweetspot.toml")])
    assert code == 0 and calls and "ran: True" in out


def test_interactive_setup_that_fails_stops_the_command(tmp_path, monkeypatch):
    monkeypatch.delenv("SWEETSPOT_BACKGROUND", raising=False)
    monkeypatch.setattr(setup, "stdin_is_terminal", lambda: True)
    monkeypatch.setattr(setup, "ensure", lambda path, stdout, stderr: 5)
    monkeypatch.setitem(cli.HANDLERS, "coverage", lambda ctx, args: pytest.fail("must not run"))
    code, _, _ = run(["coverage", "--config", str(tmp_path / "sweetspot.toml")])
    assert code == 5 and files(tmp_path) == []


def test_existing_settings_are_used_as_before(tmp_path, background, monkeypatch):
    """FR-004: the owner's own settings file means no question and no change in behaviour."""
    monkeypatch.setattr(cli, "load_secrets", lambda: cli.Secrets())
    (tmp_path / "sweetspot.toml").write_text(TEST_TOML, encoding="utf-8")
    monkeypatch.setitem(cli.HANDLERS, "coverage", lambda ctx, args: cli.CommandResult(0, {"ran": True}))
    code, out, _ = run(["coverage", "--config", str(tmp_path / "sweetspot.toml")])
    assert code == 0 and "ran: True" in out


def test_old_names_still_come_first(tmp_path, background):
    (tmp_path / legacy.CONFIG.old).write_text(TEST_TOML, encoding="utf-8")
    (tmp_path / "data").mkdir()
    sqlite3.connect(tmp_path / "data" / legacy.DB.old).close()
    code, _, err = run(["coverage", "--config", str(tmp_path / "sweetspot.toml")])
    assert code == cli.EXIT_NEEDS_MIGRATION == 4


def test_help_version_and_migrate_are_not_refused(tmp_path, background, capsys):
    for argv in (["update", "--help", "--config", str(tmp_path / "sweetspot.toml")], ["--version"]):
        with pytest.raises(SystemExit) as info:
            cli.main(argv)
        assert info.value.code == 0
    code, _, err = run(["migrate", "--dry-run", "--config", str(tmp_path / "sweetspot.toml")])
    assert code != 5 and "還沒設定" not in err


def test_setup_itself_in_the_background_says_where_to_run_it(tmp_path, background):
    code, out, err = run(["setup", "--config", str(tmp_path / "sweetspot.toml")])
    assert code == 5 and "請在視窗中執行 sweetspot setup" in out + err
    assert files(tmp_path) == []


def test_report_accepts_update_exit_5():
    assert cli.build_parser().parse_args(["report", "--update-exit", "5"]).update_exit == 5
