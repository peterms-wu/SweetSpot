"""016 contracts/migrate.md §4–§5: while only old-name files exist, every command but `migrate` refuses with exit 4 and
creates nothing (FR-010); old and new side by side, the new one is used with a warning (FR-011)."""

import argparse
import hashlib
import importlib.util
import io
import shutil
import sqlite3
from pathlib import Path

import pytest

from sweetspot import cli, legacy
from tests.config_builders import TEST_TOML

ROOT = Path(__file__).resolve().parents[2]
HINT = "請先執行搬家：uv run sweetspot migrate"


def minimal_args(tmp: Path) -> dict[str, list[str]]:
    """The fewest arguments each sub-command parses with; the refusal comes before any of them is used."""
    a, b = str(tmp / "a.json"), str(tmp / "b.json")
    return {"update": [], "reference": [], "import-legacy": [], "coverage": [], "calendar": [], "forecast": [],
            "backtest": [], "grid": ["--model", "seasonal-record"], "report": [], "backtest-rule": [],
            "compare-rule": [a, b], "compare": [a, b], "ns-backtest": [], "ns-grid": [], "ns-compare": [a],
            "review": [], "host": ["status"], "setup": [], "schedule": ["status"]}


def subcommands() -> set[str]:
    parser = cli.build_parser()
    return set(next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction)).choices)


def test_the_table_covers_every_subcommand(tmp_path):
    """Enumerated from the parser, not picked by hand: a new sub-command must be added here."""
    assert set(minimal_args(tmp_path)) == subcommands() - {"migrate"}


def old_folder(root: Path, *, new_config=False) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    if new_config:
        (root / "sweetspot.toml").write_text(TEST_TOML, encoding="utf-8")
    else:
        (root / "steamsage.toml").write_text(TEST_TOML, encoding="utf-8")
    (root / "data").mkdir()
    conn = sqlite3.connect(root / "data" / "steamsage.db")
    conn.execute("CREATE TABLE t (x)")
    conn.close()
    return root


def hashes(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(argv, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


@pytest.mark.parametrize("command", sorted(minimal_args(Path("."))))
def test_only_the_old_settings_file_refuses_every_command(tmp_path, command):
    root = old_folder(tmp_path / "home")
    before = hashes(root)
    code, _, err = run([command, *minimal_args(tmp_path)[command], "--config", str(root / "sweetspot.toml")])
    assert code == cli.EXIT_NEEDS_MIGRATION == 4
    assert f"找到舊名稱的檔案（{legacy.CONFIG.old}），{HINT}" in err
    assert hashes(root) == before                                         # nothing created, nothing changed
    assert not (root / "data" / "logs").exists() and not (root / "data" / ".lock").exists()


@pytest.mark.parametrize("command", sorted(minimal_args(Path("."))))
def test_only_the_old_database_refuses_every_command(tmp_path, command):
    root = old_folder(tmp_path / "home", new_config=True)
    before = hashes(root)
    code, _, err = run([command, *minimal_args(tmp_path)[command], "--config", str(root / "sweetspot.toml")])
    assert code == 4
    assert f"找到舊名稱的檔案（{legacy.DB.old}），{HINT}" in err
    assert hashes(root) == before
    assert not (root / "data" / "logs").exists() and not (root / "data" / ".lock").exists()


def test_old_and_new_side_by_side_uses_the_new_ones_and_warns(tmp_path):
    root = old_folder(tmp_path)
    shutil.copy(root / "steamsage.toml", root / "sweetspot.toml")
    shutil.copy(root / "data" / "steamsage.db", root / "data" / "sweetspot.db")
    (root / "extension" / "data").mkdir(parents=True)
    for name in ("steamsage-extension.json", "sweetspot-extension.json"):
        (root / "extension" / "data" / name).write_text("{}", encoding="utf-8")
    old = {k: v for k, v in hashes(root).items() if "steamsage" in k}
    code, _, err = run(["coverage", "--config", str(root / "sweetspot.toml")])
    assert code != 4
    for name in (legacy.CONFIG.old, legacy.DB.old, Path(legacy.EXTENSION_DATA.old).name):
        assert f"警告：舊名稱的檔案還在（{name}），沒有使用；確認不需要後可以自行刪除" in err
    assert {k: v for k, v in hashes(root).items() if k in old} == old    # never deleted or merged


def test_an_empty_folder_is_not_a_migration(tmp_path, monkeypatch):
    """No file at all (a new user): not the old-name refusal. Since 014 nothing is created from defaults either;
    with no one to answer it is exit 5 (tests/contract/test_cli_setup_guard.py)."""
    monkeypatch.setenv("SWEETSPOT_BACKGROUND", "1")
    code, _, err = run(["coverage", "--config", str(tmp_path / "sweetspot.toml")])
    assert "搬家" not in err and code == cli.EXIT_NOT_SET_UP
    assert not (tmp_path / "sweetspot.toml").exists() and not (tmp_path / "steamsage.toml").exists()


def test_help_and_version_are_not_refused(tmp_path, capsys):
    old_folder(tmp_path)
    for argv in (["update", "--help", "--config", str(tmp_path / "sweetspot.toml")], ["--version"]):
        with pytest.raises(SystemExit) as info:
            cli.main(argv)
        assert info.value.code == 0
    assert "搬家" not in capsys.readouterr().err


def test_update_exit_4_is_accepted_by_report():
    args = cli.build_parser().parse_args(["report", "--update-exit", "4"])
    assert args.update_exit == 4


# --- scripts/backup_db.py --------------------------------------------------------------------------------------------

def load_backup_db():
    spec = importlib.util.spec_from_file_location("backup_db", ROOT / "scripts" / "backup_db.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backup_refuses_with_4_while_only_the_old_database_exists(tmp_path, monkeypatch, capsys):
    backup_db = load_backup_db()
    old_folder(tmp_path)
    monkeypatch.setattr(backup_db, "ROOT", tmp_path)

    def no_gh(*args):
        raise AssertionError("gh must not run")

    monkeypatch.setattr(backup_db, "gh", no_gh)
    assert backup_db.main([]) == 4
    assert HINT in capsys.readouterr().err
    assert not list(tmp_path.rglob("*.zip"))
