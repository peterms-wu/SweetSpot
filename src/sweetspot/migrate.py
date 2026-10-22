"""改名搬家（016），不是資料庫升級（schema 升級在 sweetspot.store.schema）。

`sweetspot migrate` moves the user's files from the pre-016 names to the new ones once (research R4–R6, data-model §2,
contracts/migrate.md). Two parts:

  files        settings file, database (with -wal/-shm), extension data file: under the writer lock, copied to
               data/pre-016-backup-<time>/ first, renamed, checked by SHA-256; any failure renames everything back.
  environment  the local program (launcher rewritten when it is registered for this folder) and the scheduled task
               (rebuilt under the new name when it runs this folder's 背景更新.cmd). Each step stands alone; a failure
               becomes a manual step and never undoes the files (the old task runs the same 背景更新.cmd).

The registry and the Task Scheduler come from default_registry() / default_scheduler(); tests replace both
(tests/conftest.py), so a test never reaches this machine's settings.
"""

import base64
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from sweetspot import legacy
from sweetspot.cli import EXIT_FAILED, EXIT_LOCKED, EXIT_OK, EXIT_PARTIAL
from sweetspot.config import ConfigError, load_config, load_secrets
from sweetspot.host import install
from sweetspot.lock import LockHeld, WriterLock
from sweetspot.logs import setup_logging
from sweetspot.schedule import (PRELUDE, TASK_FIELDS, PowerShellScheduler, SchedulerError,  # noqa: F401
                                _decode, _one_line, _ps, powershell_args, powershell_runner,
                                run_powershell, runs_here, same_folder)
from sweetspot.timeutil import now_utc

FORMAT = "sweetspot.migration/1"
RESULT_TEXT = {"done": "完成", "already": "已完成", "skipped": "不適用", "failed": "失敗"}
STEP_LABEL = {"host": "本機程式", "task": "排程工作"}
log = logging.getLogger(__name__)


class VerifyError(Exception):
    pass


@dataclass
class Result:
    exit_code: int
    record: dict
    lines: list[str]

    @property
    def environment(self) -> list[dict]:
        return self.record["environment"]


# --- small pieces ---------------------------------------------------------------------------------------------------

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def wal_checkpoint(db: Path) -> bool:
    """Fold the WAL into the database file. True when another connection kept it from finishing (busy)."""
    try:
        conn = sqlite3.connect(db, timeout=5)
        try:
            busy = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error:
        return True
    return bool(busy)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- the Task Scheduler: sweetspot.schedule (moved there by feature 014; behaviour unchanged) ---------------------

def default_scheduler():
    return PowerShellScheduler()


def default_registry():
    return install.default_registry()


def task_manual(old: str, new: str) -> str:
    return ("在 PowerShell 依序執行下面三行，用新名稱重建排程工作：\n"
            f"   $xml = (Export-ScheduledTask -TaskName \"{old}\") -replace '<URI>[^<]*</URI>', '<URI>\\{new}</URI>'\n"
            f"   Register-ScheduledTask -TaskName \"{new}\" -Xml $xml\n"
            f"   Unregister-ScheduledTask -TaskName \"{old}\" -Confirm:$false")


# --- environment steps ----------------------------------------------------------------------------------------------

def _entry(step: str, result: str, detail: str) -> dict:
    return {"step": step, "result": result, "detail": detail}


_same_folder, _runs_here = same_folder, runs_here


def task_step(folder: Path, scheduler, old: str, new: str, *, dry_run: bool = False) -> tuple[dict, list[str]]:
    try:
        old_task, new_task = scheduler.query(old), scheduler.query(new)
    except SchedulerError as exc:
        return _entry("task", "failed", f"讀不到排程工作：{exc}"), [task_manual(old, new)]
    if old_task is None:
        if new_task is not None:
            return _entry("task", "already", f"已經是「{new}」"), []
        return _entry("task", "skipped", f"沒有「{old}」排程工作"), []
    if not _runs_here(old_task, folder):
        return _entry("task", "skipped", f"「{old}」執行的不是這個資料夾的 背景更新.cmd，沒有改"), []
    if new_task is not None:
        return (_entry("task", "failed", f"「{old}」與「{new}」同時存在，每天會執行兩次"),
                [f"確認「{new}」正常後，在 PowerShell 執行：Unregister-ScheduledTask -TaskName \"{old}\" -Confirm:$false"])
    if dry_run:
        return _entry("task", "planned", f"會把「{old}」重建為「{new}」，設定不變"), []
    try:
        xml = re.sub(r"<URI>[^<]*</URI>", lambda m: f"<URI>\\{escape(new)}</URI>", scheduler.export(old), count=1)
        scheduler.register(new, xml)
    except SchedulerError as exc:
        _remove_quietly(scheduler, new)
        return _entry("task", "failed", f"建立「{new}」失敗：{exc}；保留「{old}」"), [task_manual(old, new)]
    try:
        got = scheduler.query(new) or {}
    except SchedulerError:
        got = {}
    differ = [k for k in TASK_FIELDS if got.get(k) != old_task.get(k)]
    if differ:
        _remove_quietly(scheduler, new)
        return (_entry("task", "failed", f"「{new}」讀回的設定和舊的不同（{', '.join(differ)}），已刪除新工作、保留「{old}」"),
                [task_manual(old, new)])
    try:
        scheduler.unregister(old)
    except SchedulerError as exc:
        return (_entry("task", "failed", f"已建立「{new}」，但刪除「{old}」失敗：{exc}；兩個工作都在，每天會執行兩次"),
                [f"在 PowerShell 執行：Unregister-ScheduledTask -TaskName \"{old}\" -Confirm:$false"])
    return _entry("task", "done", f"{old} → {new}，觸發時間與設定不變"), []


def _remove_quietly(scheduler, name: str) -> None:
    try:
        if scheduler.query(name) is not None:
            scheduler.unregister(name)
    except SchedulerError:
        pass


def host_step(folder: Path, registry, *, python: Path | None, encoding: str | None,
              dry_run: bool = False) -> tuple[dict, list[str]]:
    path = folder / legacy.CONFIG.new
    if not path.exists() and dry_run:
        path = folder / legacy.CONFIG.old
    if not path.exists():
        return _entry("host", "skipped", "沒有設定檔"), []
    try:
        config, _ = load_config(path)
    except ConfigError as exc:
        return _entry("host", "failed", f"設定檔有錯誤：{exc}"), ["修正設定檔後執行：uv run sweetspot host install"]
    where = install.registration(config, registry=registry)
    if where == "none":
        return _entry("host", "skipped", "這個資料夾沒有登記本機程式"), []
    if where == "elsewhere":
        return (_entry("host", "skipped", f"本機程式登記在別的資料夾（{registry.get_default(install.REG_KEY)}），沒有改"),
                [])
    launcher = install.launcher_path(config)
    raw = launcher.read_bytes() if launcher.exists() else b""
    text = raw.decode(encoding or (install.oem_encoding() if sys.platform == "win32" else "utf-8"), "replace")
    new_config = str((folder / legacy.CONFIG.new).resolve())
    if f"-m {legacy.NEW_HOST_MODULE} " in text and new_config in text:
        return _entry("host", "already", "本機程式已經使用新名稱"), []
    if dry_run:
        return _entry("host", "planned", f"會重寫 {launcher}（改用 {legacy.NEW_HOST_MODULE} 與 {legacy.CONFIG.new}）"), []
    try:
        install.install(config, registry=registry, python=python, encoding=encoding)
    except install.InstallError as exc:
        return _entry("host", "failed", f"重新安裝失敗：{exc}"), ["執行：uv run sweetspot host install"]
    return _entry("host", "done", f"重寫 {launcher}"), []


# --- the files ------------------------------------------------------------------------------------------------------

def _backup(moving: list[legacy.FileItem], target: Path) -> list[dict]:
    target.mkdir(parents=True)
    out = []
    for f in moving:
        dst = target / f.old.name
        if f.item is legacy.DB:
            # read only, so closing it never checkpoints or deletes the -wal of the database being moved
            src = sqlite3.connect(f"{f.old.resolve().as_uri()}?mode=ro", uri=True)
            copy = sqlite3.connect(dst)
            try:
                src.backup(copy)
                check = copy.execute("PRAGMA quick_check").fetchone()[0]
            finally:
                copy.close()
                src.close()
            if check != "ok":
                raise sqlite3.DatabaseError(f"備份的資料庫檢查不通過：{check}")
        else:
            shutil.copy2(f.old, dst)
            check = "copied"
        out.append({"name": dst.name, "bytes": dst.stat().st_size, "check": check})
    return out


def _standard_steps(backup_dir: Path | None) -> list[str]:
    steps = ["在 Chrome 開 chrome://extensions，對 SweetSpot 按「重新載入」（版本應顯示 1.2.0 以上）；"
             "重新載入前，Steam 頁面上的面板與願望清單那一行會暫時不顯示",
             "擴充功能面板中的設定檔路徑會在下一次報告後更新；想立即更新可以執行 更新資料.cmd，否則等 02:30"]
    if backup_dir is not None:
        steps.append(f"確認 02:30 背景更新正常後，可以刪除備份資料夾 {backup_dir}")
    return steps


def _write(record: dict, backup_dir: Path) -> None:
    (backup_dir / "migration.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _file_line(f: legacy.FileItem, entry: dict) -> str:
    label, old, new = f.item.label, f.old.name, f.new.name
    return {"moved": f"{label} {old} → {new}：已搬（SHA-256 相同）",
            "already": f"{label} {new}：已經是新名稱",
            "absent": f"{label}：沒有這個檔案，略過",
            "rolled-back": f"{label} {old}：已改回舊名稱",
            "conflict": f"{label}：新舊名稱同時存在（{old} 與 {new}）"}.get(entry["result"], f"{label}：{entry['result']}")


def _env_line(entry: dict) -> str:
    label = STEP_LABEL[entry["step"]]
    if entry["result"] == "planned":
        return f"{label}：{entry['detail']}"
    if entry["result"] == "failed":
        return f"{label}：失敗：{entry['detail']}，改成手動步驟"
    return f"{label}：{RESULT_TEXT[entry['result']]}：{entry['detail']}"


def _environment(folder: Path, *, registry, scheduler, python: Path | None, encoding: str | None, old_task: str,
                 new_task: str, dry_run: bool) -> tuple[list[dict], list[str]]:
    """The local program and the scheduled task, each on its own; the fakes of the tests come in as arguments."""
    entries, manual = [], []
    for entry, steps in (host_step(folder, registry if registry is not None else default_registry(), python=python,
                                   encoding=encoding, dry_run=dry_run),
                         task_step(folder, scheduler if scheduler is not None else default_scheduler(), old_task,
                                   new_task, dry_run=dry_run)):
        if not dry_run:
            log.info("%s", _env_line(entry))                # the line already starts with the step's label
        entries.append(entry)
        manual += steps
    return entries, manual


def _plan_lines(files: list[legacy.FileItem], entries: list[dict], data_dir: Path, environment: list[dict]) -> list[str]:
    lines = ["只列出計畫，沒有改任何檔案："]
    lines += [f"{f.item.label} {f.old.name} → {f.new.name}：會搬" if f.state == legacy.OLD_ONLY else _file_line(f, e)
              for f, e in zip(files, entries)]
    if any(f.state == legacy.OLD_ONLY for f in files):
        lines.append(f"會先備份到 {data_dir / 'pre-016-backup-<時間>'}")
    return lines + [_env_line(e) for e in environment]


def _summary_lines(files: list[legacy.FileItem], entries: list[dict], backup_dir: Path | None,
                   environment: list[dict], manual_steps: list[str]) -> list[str]:
    moved = backup_dir is not None
    if all(f.state == legacy.ABSENT for f in files):
        lines = ["這個資料夾沒有改名前或改名後的檔案"]
    else:
        lines = [_file_line(f, e) for f, e in zip(files, entries) if e["result"] != "absent" or moved]
    if moved:
        lines.append(f"備份：{backup_dir}")
    if not moved and not any(e["result"] in ("done", "failed") for e in environment):
        lines.append("已經是新名稱，什麼都沒改")
    lines += [_env_line(e) for e in environment]
    if manual_steps:
        lines.append("接下來要你做的事：")
        lines += [f"{n}. {step}" for n, step in enumerate(manual_steps, 1)]
    return lines


def _move_under_lock(moving: list[legacy.FileItem], entries: list[dict], data_dir: Path, backup_dir: Path,
                     record: dict, *, rename, checkpoint, hasher, rel) -> tuple[int, list[str]] | None:
    """The file part under the writer lock. None when every file moved; otherwise (exit code, output lines) of a
    refusal (nothing changed) or a failure (everything renamed back, migration.json written)."""
    lock = WriterLock(data_dir / ".lock")
    try:
        lock.acquire()
    except LockHeld as exc:
        message = f"{exc}：背景更新或本機程式正在執行，什麼都沒改；等它結束後再執行一次"
        log.warning("搬家拒絕：%s", message)
        record.update(outcome="refused", error=message)
        return EXIT_LOCKED, [message]
    try:
        db = next((f for f in moving if f.item is legacy.DB), None)
        if db is not None and checkpoint(db.old):
            message = "資料庫正在被其他程式使用（例如正在產生報告或指定版本），什麼都沒改；稍後再執行一次"
            log.warning("搬家拒絕：%s", message)
            record.update(outcome="refused", error=message)
            return EXIT_FAILED, [message]
        failed = _move(moving, entries, backup_dir, record, rename, hasher, rel)
        if failed is not None:
            return EXIT_FAILED, failed
        record["outcome"] = "migrated"
        return None
    finally:
        lock.release()


def run(folder: Path, *, dry_run: bool = False, rename: Callable[[Path, Path], None] | None = None,
        checkpoint: Callable[[Path], bool] | None = None, hasher: Callable[[Path], str] | None = None,
        now: Callable[[], datetime] | None = None, registry=None, scheduler=None, python: Path | None = None,
        encoding: str | None = None, old_task: str = legacy.OLD_TASK, new_task: str = legacy.NEW_TASK) -> Result:
    rename = rename or os.rename
    checkpoint = checkpoint or wal_checkpoint
    hasher = hasher or sha256
    now = now or (lambda: now_utc())
    folder = Path(folder).resolve()
    started = now()
    env_args = dict(registry=registry, scheduler=scheduler, python=python, encoding=encoding, old_task=old_task,
                    new_task=new_task)

    def rel(path: Path) -> str:
        try:
            return str(path.relative_to(folder))
        except ValueError:
            return str(path)

    try:
        files = legacy.items(folder)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        message = f"讀不了設定檔中的資料夾設定：{_one_line(exc)}；什麼都沒改"
        log.warning("搬家拒絕：%s", message)
        return Result(EXIT_FAILED, {"format": FORMAT, "outcome": "refused", "error": message}, [message])
    data_dir = legacy.read_data_dir(folder)
    entries = [{"kind": f.item.kind, "old": rel(f.old), "new": rel(f.new), "state_before": f.state,
                "result": {legacy.OLD_ONLY: "pending", legacy.NEW_ONLY: "already", legacy.ABSENT: "absent",
                           legacy.BOTH: "conflict"}[f.state],
                "bytes": None, "sha256": None, "companions": []} for f in files]
    record = {"format": FORMAT, "started_at": _iso(started), "finished_at": None, "folder": str(folder),
              "outcome": None, "failed_step": None, "error": None, "files": entries, "backup": None,
              "environment": [], "manual_steps": []}
    moving = [f for f in files if f.state == legacy.OLD_ONLY]

    def finish(code: int, outcome: str, lines: list[str], error: str | None = None) -> Result:
        record.update(outcome=outcome, error=error, finished_at=_iso(now()))
        return Result(code, record, lines)

    conflicts = [f for f in files if f.state == legacy.BOTH]
    if conflicts:
        lines = [f"{f.item.label}新舊名稱同時存在：{f.old} 與 {f.new}。請確認要用哪一個，把另一個移開後再執行"
                 for f in conflicts] + ["什麼都沒改"]
        log.warning("搬家拒絕：%s", "；".join(lines))
        return finish(EXIT_FAILED, "refused", lines, lines[0])

    if dry_run:
        record["environment"], _ = _environment(folder, **env_args, dry_run=True)
        return finish(EXIT_OK, "dry-run", _plan_lines(files, entries, data_dir, record["environment"]))

    anything = any(f.state != legacy.ABSENT for f in files)
    if anything:
        log.info("搬家開始：%s", folder)
    backup_dir = None
    if moving:
        backup_dir = data_dir / f"pre-016-backup-{started.astimezone(timezone.utc):%Y%m%d-%H%M%S}"
        stopped = _move_under_lock(moving, entries, data_dir, backup_dir, record, rename=rename,
                                   checkpoint=checkpoint, hasher=hasher, rel=rel)
        if stopped is not None:
            code, lines = stopped
            record["finished_at"] = _iso(now())
            if backup_dir.is_dir():                    # a failure after the backup: keep its record next to it
                _write(record, backup_dir)
            return Result(code, record, lines)
        record["finished_at"] = _iso(now())
        _write(record, backup_dir)                     # the files moved; written again after the environment

    environment, manual = _environment(folder, **env_args, dry_run=False)
    record["environment"] = environment
    record["manual_steps"] = (_standard_steps(backup_dir) if moving else []) + manual
    code = EXIT_PARTIAL if any(e["result"] == "failed" for e in environment) else EXIT_OK
    result = finish(code, "migrated" if moving else "already",
                    _summary_lines(files, entries, backup_dir, environment, record["manual_steps"]))
    if backup_dir is not None:
        _write(record, backup_dir)
    if anything:
        log.info("搬家結束：結束代碼 %s", code)
    return result


def _move(moving, entries, backup_dir, record, rename, hasher, rel) -> list[str] | None:
    """Backup, rename and verify under the lock. Returns the output lines of a failure (everything renamed back),
    or None when every file moved."""
    by_kind = {e["kind"]: e for e in entries}
    step = "backup"
    try:
        record["backup"] = {"dir": rel(backup_dir), "files": _backup(moving, backup_dir)}
        log.info("備份到 %s", backup_dir)
    except (OSError, sqlite3.Error) as exc:
        record.update(outcome="failed", failed_step=step, error=f"備份失敗：{_one_line(exc)}")
        log.error("搬家失敗：%s", record["error"])
        return [f"沒有搬：{record['error']}；什麼都沒改名", f"備份資料夾：{backup_dir}"]
    for f in moving:
        e = by_kind[f.item.kind]
        e["bytes"], e["sha256"] = f.old.stat().st_size, hasher(f.old)
    done: list[tuple[Path, Path]] = []
    try:
        step = "rename"
        # the database first (research R4): it is the file another program is most likely to hold open
        for f in sorted(moving, key=lambda f: f.item is not legacy.DB):
            pairs = [(f.old, f.new)] + [(o, n) for o, n in f.companions() if o.exists()]
            for src, dst in pairs:
                if dst.exists():
                    raise FileExistsError(f"{dst} 已經存在")
                rename(src, dst)
                done.append((src, dst))
                log.info("改名 %s → %s", rel(src), rel(dst))
            by_kind[f.item.kind]["companions"] = [{"old": rel(o), "new": rel(n), "bytes": n.stat().st_size}
                                                  for o, n in pairs[1:]]
        step = "verify"
        for f in moving:
            e = by_kind[f.item.kind]
            if f.new.stat().st_size != e["bytes"] or hasher(f.new) != e["sha256"]:
                raise VerifyError(f"{f.new.name} 的內容和搬家前不同")
            e["result"] = "moved"
        log.info("驗證完成：%s 個檔案的 SHA-256 與搬家前相同", len(moving))
        return None
    except (OSError, VerifyError) as exc:
        undo_errors = []
        for src, dst in reversed(done):
            try:
                rename(dst, src)
            except OSError as undo:
                undo_errors.append(f"{rel(dst)} → {rel(src)}：{_one_line(undo)}")
        for f in moving:
            by_kind[f.item.kind]["result"] = "rolled-back"
        record.update(outcome="failed", failed_step=step, error=_one_line(exc))
        log.error("搬家失敗（%s）：%s；已改回 %s 個檔案", step, record["error"], len(done) - len(undo_errors))
        what = {"rename": "改名", "verify": "驗證"}[step]
        lines = [f"沒有搬：{what}失敗：{record['error']}。已把改過的檔案全部改回舊名稱"]
        if undo_errors:
            lines.append("改回時也失敗，請依備份資料夾中的 migration.json 手動改回：" + "；".join(undo_errors))
        lines += [f"{f.item.label}：{f.old if f.old.exists() else f.new}" for f in moving]
        lines.append(f"備份資料夾：{backup_dir}")
        return lines


def main(args, stdout, stderr) -> int:
    """`sweetspot migrate` (sweetspot.cli hands it over before reading the settings file)."""
    folder = Path(args.config).resolve().parent
    if not args.dry_run:
        try:
            data_dir = legacy.read_data_dir(folder)
            if any(f.state != legacy.ABSENT for f in legacy.items(folder, data_dir)):
                setup_logging(data_dir, load_secrets().redaction_values())
        except (OSError, tomllib.TOMLDecodeError):
            pass                                           # run() reports it
    result = run(folder, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(result.record, ensure_ascii=False, indent=2), file=stdout)
    else:
        print("\n".join(result.lines), file=stdout)
    return result.exit_code
