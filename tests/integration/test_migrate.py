"""Feature 016: `sweetspot migrate` moves the user's old-name files to the new names (research R4–R6, data-model §2).

Every test builds its own folder under tmp_path. The registry and the Task Scheduler are fakes; tests/conftest.py makes
the real PowerShell fail and gives migrate an empty fake registry, so nothing here can touch this machine's settings.
"""

import base64
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from sweetspot import legacy, migrate
from sweetspot.config import load_config
from tests.config_builders import TEST_TOML
from sweetspot.host import install

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 16, 5, 0, 0, tzinfo=timezone.utc)
BACKUP = "data/pre-016-backup-20261016-050000"
ROWS = [(i, f"row {i}") for i in range(50)]
LEAVE_WAL = """
import os, sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, text TEXT)")
conn.executemany("INSERT INTO t VALUES (?, ?)", [(i, f"row {i}") for i in range(50)])
conn.commit()
os._exit(0)   # no close: -wal and -shm stay, as the real database after a run
"""


class FakeRegistry:
    def __init__(self):
        self.values: dict[str, str] = {}

    def set_default(self, key, value):
        self.values[key] = value

    def get_default(self, key):
        return self.values.get(key)

    def delete(self, key):
        self.values.pop(key, None)


def summary(folder: Path, **extra) -> dict:
    return {"execute": r"C:\WINDOWS\system32\conhost.exe",
            "arguments": f'--headless cmd.exe /d /c "{folder}\\背景更新.cmd"', "working_directory": str(folder),
            "start_boundary": "2026-09-27T02:30:00+08:00", "start_when_available": True, "logon_type": "Interactive",
            "run_level": "Limited", **extra}


class FakeScheduler:
    def __init__(self, tasks=None, *, fail=None, readback=None):
        self.tasks: dict[str, dict] = dict(tasks or {})
        self.fail = fail or set()          # operations that raise
        self.readback = readback           # summary returned for the new task after register (a mismatch)
        self.calls: list[tuple] = []

    def _maybe_fail(self, op):
        if op in self.fail:
            raise migrate.SchedulerError(f"{op} failed")

    def query(self, name):
        self.calls.append(("query", name))
        return dict(self.tasks[name]) if name in self.tasks else None

    def export(self, name):
        self.calls.append(("export", name))
        self._maybe_fail("export")
        return f'<?xml version="1.0" encoding="UTF-16"?>\n<Task><RegistrationInfo><URI>\\{name}</URI></RegistrationInfo></Task>'

    def register(self, name, xml):
        self.calls.append(("register", name, xml))
        self._maybe_fail("register")
        old = next(iter(self.tasks.values()))
        self.tasks[name] = dict(self.readback or old)

    def unregister(self, name):
        self.calls.append(("unregister", name))
        self._maybe_fail(f"unregister {name}")
        self.tasks.pop(name, None)


def make_folder(root: Path, *, wal=False, ext=True) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "steamsage.toml").write_text(TEST_TOML, encoding="utf-8")
    data = root / "data"
    data.mkdir()
    db = data / "steamsage.db"
    if wal:
        subprocess.run([sys.executable, "-c", LEAVE_WAL, str(db)], check=True)
    else:
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, text TEXT)")
        conn.executemany("INSERT INTO t VALUES (?, ?)", ROWS)
        conn.commit()
        conn.close()
    if ext:
        (root / "extension" / "data").mkdir(parents=True)
        (root / "extension" / "data" / "steamsage-extension.json").write_text('{"format": "x"}', encoding="utf-8")
    return root


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(root: Path) -> dict[str, tuple[str, int]]:
    """Hash and mtime of every file, without what the migration itself adds (spec SC-003)."""
    out = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.is_file() and not rel.startswith(("data/pre-016-backup-", "data/logs/")):
            out[rel] = (sha(p), p.stat().st_mtime_ns)
    return out


def rows(db: Path) -> list[tuple]:
    conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return conn.execute("SELECT id, text FROM t ORDER BY id").fetchall()
    finally:
        conn.close()


def run(root: Path, **kw):
    kw.setdefault("now", lambda: NOW)
    kw.setdefault("registry", FakeRegistry())
    kw.setdefault("scheduler", FakeScheduler())
    kw.setdefault("encoding", "cp950")
    return migrate.run(root, **kw)


# --- files (016 T018) -----------------------------------------------------------------------------------------------

def test_moves_the_three_files_byte_for_byte(tmp_path):
    root = make_folder(tmp_path)
    before = {name: sha(root / name) for name in ("steamsage.toml", "data/steamsage.db",
                                                  "extension/data/steamsage-extension.json")}
    result = run(root)
    assert result.exit_code == 0, result.lines
    for old, new in [("steamsage.toml", "sweetspot.toml"), ("data/steamsage.db", "data/sweetspot.db"),
                     ("extension/data/steamsage-extension.json", "extension/data/sweetspot-extension.json")]:
        assert not (root / old).exists()
        assert sha(root / new) == before[old]
    assert rows(root / "data" / "sweetspot.db") == ROWS


def test_wal_companions_move_with_the_database(tmp_path):
    root = make_folder(tmp_path, wal=True)
    assert (root / "data" / "steamsage.db-wal").exists() and (root / "data" / "steamsage.db-shm").exists()
    result = run(root, checkpoint=lambda path: False)        # leave the companions in place to rename them
    assert result.exit_code == 0, result.lines
    assert not any((root / "data").glob("steamsage.db*"))
    assert (root / "data" / "sweetspot.db-wal").exists() and (root / "data" / "sweetspot.db-shm").exists()
    assert rows(root / "data" / "sweetspot.db") == ROWS        # the WAL is still found under the new name
    db = next(f for f in result.record["files"] if f["kind"] == "db")
    assert {c["new"] for c in db["companions"]} == {os.path.join("data", "sweetspot.db-wal"),
                                                    os.path.join("data", "sweetspot.db-shm")}


def test_the_real_checkpoint_folds_the_wal_into_the_database(tmp_path):
    root = make_folder(tmp_path, wal=True)
    result = run(root)
    assert result.exit_code == 0, result.lines
    assert rows(root / "data" / "sweetspot.db") == ROWS
    wal = root / "data" / "sweetspot.db-wal"
    assert not wal.exists() or wal.stat().st_size == 0


def test_backup_copies_and_checks(tmp_path):
    root = make_folder(tmp_path)
    toml, ext = sha(root / "steamsage.toml"), sha(root / "extension/data/steamsage-extension.json")
    run(root)
    backup = root / BACKUP
    assert sorted(p.name for p in backup.iterdir()) == ["migration.json", "steamsage-extension.json", "steamsage.db",
                                                        "steamsage.toml"]
    assert sha(backup / "steamsage.toml") == toml and sha(backup / "steamsage-extension.json") == ext
    assert rows(backup / "steamsage.db") == ROWS
    conn = sqlite3.connect(backup / "steamsage.db")
    assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    conn.close()


def test_migration_record(tmp_path):
    root = make_folder(tmp_path)
    sizes = {k: (root / p).stat().st_size for k, p in [("config", "steamsage.toml"), ("db", "data/steamsage.db"),
                                                         ("extension_data", "extension/data/steamsage-extension.json")]}
    hashes = {k: sha(root / p) for k, p in [("config", "steamsage.toml"), ("db", "data/steamsage.db"),
                                             ("extension_data", "extension/data/steamsage-extension.json")]}
    result = run(root)
    record = json.loads((root / BACKUP / "migration.json").read_text(encoding="utf-8"))
    assert record == result.record
    assert record["format"] == "sweetspot.migration/1"
    assert record["started_at"] == "2026-10-16T05:00:00Z" and record["finished_at"] == "2026-10-16T05:00:00Z"
    assert record["folder"] == str(root.resolve())
    assert record["outcome"] == "migrated" and record["failed_step"] is None and record["error"] is None
    assert [f["kind"] for f in record["files"]] == ["config", "db", "extension_data"]
    for f in record["files"]:
        assert f["state_before"] == "old-only" and f["result"] == "moved"
        assert f["bytes"] == sizes[f["kind"]] and f["sha256"] == hashes[f["kind"]]
    assert record["files"][0]["old"] == "steamsage.toml" and record["files"][0]["new"] == "sweetspot.toml"
    assert record["backup"]["dir"] == os.path.join("data", "pre-016-backup-20261016-050000")
    assert {f["name"]: f["check"] for f in record["backup"]["files"]} == {
        "steamsage.toml": "copied", "steamsage.db": "ok", "steamsage-extension.json": "copied"}
    assert record["manual_steps"] and record["environment"] == [
        {"step": "host", "result": "skipped", "detail": "這個資料夾沒有登記本機程式"},
        {"step": "task", "result": "skipped", "detail": f"沒有「{legacy.OLD_TASK}」排程工作"}]


def test_again_says_already_and_changes_nothing(tmp_path):
    root = make_folder(tmp_path)
    run(root)
    shutil.rmtree(root / BACKUP)
    before = snapshot(root)
    result = run(root, now=lambda: NOW.replace(hour=6))
    assert result.exit_code == 0
    assert any("已經是新名稱" in line for line in result.lines)
    assert snapshot(root) == before
    assert not list((root / "data").glob("pre-016-backup-*"))


@pytest.mark.parametrize("both", ["steamsage.toml", "data/steamsage.db", "extension/data/steamsage-extension.json"])
def test_old_and_new_side_by_side_is_refused(tmp_path, both):
    root = make_folder(tmp_path)
    new = both.replace("steamsage", "sweetspot")
    shutil.copy(root / both, root / new)
    before = snapshot(root)
    result = run(root)
    assert result.exit_code == 1
    assert any("同時存在" in line and Path(new).name in line for line in result.lines)
    assert snapshot(root) == before
    assert not list((root / "data").glob("pre-016-backup-*"))


def test_writer_lock_held_is_refused(tmp_path):
    root = make_folder(tmp_path)
    (root / "data" / ".lock").write_text(f"{os.getpid()}\n", encoding="utf-8")
    before = snapshot(root)
    result = run(root)
    assert result.exit_code == 3
    assert snapshot(root) == before
    assert not list((root / "data").glob("pre-016-backup-*"))


def test_busy_checkpoint_is_refused(tmp_path):
    root = make_folder(tmp_path)
    before = snapshot(root)
    result = run(root, checkpoint=lambda path: True)
    assert result.exit_code == 1
    assert any("其他程式" in line for line in result.lines)
    assert snapshot(root) == before
    assert not (root / "data" / ".lock").exists()
    assert not list((root / "data").glob("pre-016-backup-*"))


def test_the_database_is_renamed_first(tmp_path):
    """research R4: the file another program most likely holds open goes first, so a failure has nothing to undo."""
    root = make_folder(tmp_path)
    order = []

    def rename(src, dst):
        order.append(Path(dst).name)
        os.rename(src, dst)

    assert run(root, rename=rename).exit_code == 0
    assert order == ["sweetspot.db", "sweetspot.toml", "sweetspot-extension.json"]


@pytest.mark.parametrize("target", ["sweetspot.db", "sweetspot.toml", "sweetspot-extension.json"])
def test_a_failed_rename_puts_everything_back(tmp_path, target):
    root = make_folder(tmp_path)
    before = snapshot(root)

    def rename(src, dst):
        if Path(dst).name == target:
            raise PermissionError(13, "the file is in use", str(src))
        os.rename(src, dst)

    result = run(root, rename=rename)
    assert result.exit_code == 1
    assert snapshot(root) == before
    record = json.loads((root / BACKUP / "migration.json").read_text(encoding="utf-8"))
    assert record["outcome"] == "failed" and record["failed_step"] == "rename"
    assert "in use" in record["error"]
    assert all(f["result"] in ("rolled-back", "absent") or f["state_before"] != "old-only" for f in record["files"])
    assert any("沒有搬" in line for line in result.lines)
    assert not (root / "data" / ".lock").exists()


def test_a_failed_verification_puts_everything_back(tmp_path):
    root = make_folder(tmp_path)
    before = snapshot(root)

    def fake_sha(path):
        return "0" * 64 if Path(path).name == "sweetspot.toml" else migrate.sha256(path)

    result = run(root, hasher=fake_sha)
    assert result.exit_code == 1
    assert snapshot(root) == before
    record = json.loads((root / BACKUP / "migration.json").read_text(encoding="utf-8"))
    assert record["failed_step"] == "verify"


def test_dry_run_changes_nothing_and_writes_no_log(tmp_path):
    root = make_folder(tmp_path)
    before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
    snap = snapshot(root)
    result = run(root, dry_run=True)
    assert result.exit_code == 0
    assert any("steamsage.toml → sweetspot.toml" in line for line in result.lines)
    assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) == before    # no lock, backup or log
    assert snapshot(root) == snap


def test_dry_run_with_a_conflict_exits_1(tmp_path):
    root = make_folder(tmp_path)
    shutil.copy(root / "steamsage.toml", root / "sweetspot.toml")
    assert run(root, dry_run=True).exit_code == 1


def test_without_the_extension_data_file_the_other_two_move(tmp_path):
    root = make_folder(tmp_path, ext=False)
    result = run(root)
    assert result.exit_code == 0, result.lines
    assert (root / "sweetspot.toml").exists() and (root / "data" / "sweetspot.db").exists()
    ext = next(f for f in result.record["files"] if f["kind"] == "extension_data")
    assert ext["result"] == "absent" and ext["state_before"] == "absent"


def test_a_folder_without_old_files_has_nothing_to_do(tmp_path):
    result = run(tmp_path)
    assert result.exit_code == 0
    assert list(tmp_path.iterdir()) == []


# --- environment: the local program (016 T019) ----------------------------------------------------------------------

def registered(root: Path, registry: FakeRegistry) -> Path:
    """Install the host for this folder the way 015 did: the launcher calls the old module with the old file."""
    (root / "extension" / "manifest.json").write_bytes((ROOT / "extension" / "manifest.json").read_bytes())
    config, _ = load_config(root / "steamsage.toml")
    install.install(config, registry=registry, python=Path(sys.executable), encoding="cp950")
    launcher = install.launcher_path(config)
    old = launcher.read_bytes().decode("cp950")
    old = old.replace(f"-m {legacy.NEW_HOST_MODULE} ", f"-m {legacy.OLD_HOST_MODULE} ")
    launcher.write_bytes(old.encode("cp950"))
    return launcher


def test_host_registered_here_is_installed_again(tmp_path):
    root = make_folder(tmp_path)
    reg = FakeRegistry()
    launcher = registered(root, reg)
    result = run(root, registry=reg, python=Path(sys.executable))
    assert result.exit_code == 0, result.lines
    text = launcher.read_bytes().decode("cp950")
    assert f"-m {legacy.NEW_HOST_MODULE} " in text and str((root / "sweetspot.toml").resolve()) in text
    assert legacy.OLD_HOST_MODULE not in text
    host = next(e for e in result.record["environment"] if e["step"] == "host")
    assert host["result"] == "done"
    assert reg.values[install.REG_KEY] == str(install.manifest_path(load_config(root / "sweetspot.toml")[0]).resolve())


def test_host_registered_elsewhere_is_left_alone(tmp_path):
    root = make_folder(tmp_path / "here")
    reg = FakeRegistry()
    launcher = registered(root, reg)
    reg.values[install.REG_KEY] = str(tmp_path / "elsewhere" / "data" / "host" / f"{install.NAME}.json")
    before = launcher.read_bytes()
    result = run(root, registry=reg)
    host = next(e for e in result.record["environment"] if e["step"] == "host")
    assert host["result"] == "skipped" and launcher.read_bytes() == before


def test_host_already_new_is_already(tmp_path):
    root = make_folder(tmp_path)
    reg = FakeRegistry()
    launcher = registered(root, reg)
    run(root, registry=reg, python=Path(sys.executable))
    after = launcher.read_bytes()
    shutil.rmtree(root / BACKUP)
    result = run(root, registry=reg, python=Path(sys.executable), now=lambda: NOW.replace(hour=6))
    assert result.exit_code == 0
    assert any(e == {"step": "host", "result": "already", "detail": "本機程式已經使用新名稱"} for e in
               result.environment)
    assert launcher.read_bytes() == after


# --- environment: the scheduled task (016 T019) ---------------------------------------------------------------------

def test_task_is_rebuilt_under_the_new_name(tmp_path):
    root = make_folder(tmp_path)
    sched = FakeScheduler({legacy.OLD_TASK: summary(root)})
    result = run(root, scheduler=sched)
    assert result.exit_code == 0, result.lines
    assert set(sched.tasks) == {legacy.NEW_TASK}
    ops = [c[0] for c in sched.calls if c[0] != "query"]
    assert ops == ["export", "register", "unregister"]
    xml = next(c[2] for c in sched.calls if c[0] == "register")
    assert f"<URI>\\{legacy.NEW_TASK}</URI>" in xml and legacy.OLD_TASK not in xml
    task = next(e for e in result.record["environment"] if e["step"] == "task")
    assert task["result"] == "done"


def test_task_register_failure_keeps_the_old_task(tmp_path):
    root = make_folder(tmp_path)
    sched = FakeScheduler({legacy.OLD_TASK: summary(root)}, fail={"register"})
    result = run(root, scheduler=sched)
    assert result.exit_code == 2
    assert set(sched.tasks) == {legacy.OLD_TASK}
    assert (root / "sweetspot.toml").exists()                       # the files stay moved
    task = next(e for e in result.record["environment"] if e["step"] == "task")
    assert task["result"] == "failed"
    manual = "\n".join(result.record["manual_steps"])
    assert "Export-ScheduledTask" in manual and "Register-ScheduledTask" in manual and "Unregister-ScheduledTask" in manual


def test_task_readback_mismatch_removes_the_new_task(tmp_path):
    root = make_folder(tmp_path)
    sched = FakeScheduler({legacy.OLD_TASK: summary(root)}, readback=summary(root, run_level="Highest"))
    result = run(root, scheduler=sched)
    assert result.exit_code == 2
    assert set(sched.tasks) == {legacy.OLD_TASK}
    task = next(e for e in result.record["environment"] if e["step"] == "task")
    assert task["result"] == "failed" and "run_level" in task["detail"]


def test_task_of_another_folder_is_left_alone(tmp_path):
    root = make_folder(tmp_path / "here")
    sched = FakeScheduler({legacy.OLD_TASK: summary(tmp_path / "elsewhere")})
    result = run(root, scheduler=sched)
    assert result.exit_code == 0
    assert [c[0] for c in sched.calls] == ["query", "query"]
    task = next(e for e in result.record["environment"] if e["step"] == "task")
    assert task["result"] == "skipped"


def test_only_the_new_task_is_already(tmp_path):
    root = make_folder(tmp_path)
    sched = FakeScheduler({legacy.NEW_TASK: summary(root)})
    result = run(root, scheduler=sched)
    task = next(e for e in result.record["environment"] if e["step"] == "task")
    assert task["result"] == "already"


def test_task_names_can_be_given(tmp_path):
    """016 T045 uses throwaway names to try the real Task Scheduler without touching the daily task."""
    root = make_folder(tmp_path)
    sched = FakeScheduler({"測試（舊）": summary(root)})
    result = run(root, scheduler=sched, old_task="測試（舊）", new_task="測試（新）")
    assert set(sched.tasks) == {"測試（新）"} and result.exit_code == 0


# --- the PowerShell runner ------------------------------------------------------------------------------------------

def decode(args: list[str]) -> str:
    assert args[:4] == ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand"]
    return base64.b64decode(args[4]).decode("utf-16-le")


def test_powershell_scheduler_passes_chinese_names_intact():
    seen = []

    def runner(args):
        script = decode(args)
        seen.append(script)
        out = json.dumps({"exists": True, **summary(Path(r"D:\Tools\SweetSpot"))}, ensure_ascii=False)
        return subprocess.CompletedProcess(args, 0, out.encode("utf-8"), b"")

    sched = migrate.PowerShellScheduler(runner)
    got = sched.query(legacy.OLD_TASK)
    assert got["logon_type"] == "Interactive"
    assert "'SteamSage2 每日背景更新'" in seen[0] and "ConvertTo-Json" in seen[0]


def test_powershell_scheduler_reports_failures():
    def runner(args):
        return subprocess.CompletedProcess(args, 1, b"", "存取被拒".encode("utf-8"))

    with pytest.raises(migrate.SchedulerError, match="存取被拒"):
        migrate.PowerShellScheduler(runner).unregister(legacy.OLD_TASK)


def test_powershell_scheduler_register_sends_the_xml_as_base64():
    seen = []

    def runner(args):
        seen.append(decode(args))
        return subprocess.CompletedProcess(args, 0, b"", b"")

    xml = '<Task><URI>\\SweetSpot 每日背景更新</URI></Task>'
    migrate.PowerShellScheduler(runner).register(legacy.NEW_TASK, xml)
    encoded = base64.b64encode(xml.encode("utf-8")).decode("ascii")
    assert encoded in seen[0] and "Register-ScheduledTask" in seen[0] and "'SweetSpot 每日背景更新'" in seen[0]


def test_tests_cannot_reach_the_real_powershell():
    with pytest.raises(AssertionError, match="PowerShell"):
        migrate.run_powershell("Get-Date")
