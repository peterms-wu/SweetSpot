"""`sweetspot schedule install|uninstall|status`: the daily background update in the Task Scheduler (014 research R4,
contracts/cli.md §3, data-model 「排程工作」; FR-012, FR-012a).

The PowerShell access to the Task Scheduler came from feature 016's migrate.py and lives here now; migrate imports it.
Tests never reach the real Task Scheduler: tests/conftest.py replaces powershell_runner and default_scheduler.
"""

import base64
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import TextIO
from xml.sax.saxutils import escape

from sweetspot import legacy
from sweetspot.host import install

DEFAULT_NAME = legacy.NEW_TASK                          # 「SweetSpot 每日背景更新」
SCRIPT = "背景更新.cmd"
TASK_FIELDS = ("execute", "arguments", "working_directory", "start_boundary", "start_when_available", "logon_type",
               "run_level")
DESCRIPTION = ("每天 02:30 在背景執行 SweetSpot 的 update、report 與雲端備份；錯過時在電腦可用時補跑。"
               "輸出：data\\logs\\background-update.log")


class SchedulerError(Exception):
    pass


# --- the Task Scheduler through PowerShell (moved from migrate.py, feature 016) -------------------------------------

def _one_line(exc: BaseException) -> str:
    return " ".join(str(exc).split()) or type(exc).__name__


def powershell_args(script: str) -> list[str]:
    """-EncodedCommand takes UTF-16LE base64, so the Chinese task names never pass through a code page."""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]


def powershell_runner(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, timeout=120)


def run_powershell(script: str) -> subprocess.CompletedProcess:
    return powershell_runner(powershell_args(script))


def _ps(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _decode(data: bytes | str) -> str:
    if isinstance(data, str):
        return data
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode(install.oem_encoding() if sys.platform == "win32" else "utf-8", "replace")


PRELUDE = "$ErrorActionPreference = 'Stop'\n[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"


class PowerShellScheduler:
    """query / info / export / register / unregister one task in the root folder of the current user's Task Scheduler."""

    def __init__(self, runner: Callable[[list[str]], subprocess.CompletedProcess] | None = None):
        self._runner = runner

    def _run(self, body: str) -> str:
        runner = self._runner or powershell_runner          # looked up at call time (tests/conftest.py)
        try:
            proc = runner(powershell_args(PRELUDE + body))
        except (OSError, subprocess.SubprocessError) as exc:
            raise SchedulerError(_one_line(exc)) from None
        if proc.returncode != 0:
            error = _decode(proc.stderr or b"").strip().splitlines()
            raise SchedulerError(" ".join(error[:3]) if error else f"PowerShell 結束代碼 {proc.returncode}")
        return _decode(proc.stdout or b"")

    def query(self, name: str) -> dict | None:
        out = self._run(
            f"$t = Get-ScheduledTask -TaskName {_ps(name)} -ErrorAction SilentlyContinue\n"
            "if ($null -eq $t) { '{\"exists\": false}' } else {\n"
            "  $a = @($t.Actions)[0]; $g = @($t.Triggers)[0]\n"
            "  [pscustomobject]@{ exists = $true; execute = $a.Execute; arguments = $a.Arguments;\n"
            "    working_directory = $a.WorkingDirectory; start_boundary = $g.StartBoundary;\n"
            "    start_when_available = [bool]$t.Settings.StartWhenAvailable;\n"
            "    logon_type = [string]$t.Principal.LogonType; run_level = [string]$t.Principal.RunLevel\n"
            "  } | ConvertTo-Json -Compress }\n")
        try:
            data = json.loads(out.strip())
        except ValueError:
            raise SchedulerError(f"看不懂排程工作的查詢結果：{out.strip()[:200]}") from None
        if not data.get("exists"):
            return None
        return {k: data.get(k) for k in TASK_FIELDS}

    def info(self, name: str) -> dict:
        out = self._run(
            f"$i = Get-ScheduledTaskInfo -TaskName {_ps(name)}\n"
            "[pscustomobject]@{ last_run_time = [string]$i.LastRunTime; last_task_result = $i.LastTaskResult;\n"
            "  next_run_time = [string]$i.NextRunTime } | ConvertTo-Json -Compress\n")
        try:
            return json.loads(out.strip())
        except ValueError:
            raise SchedulerError(f"看不懂排程工作的執行紀錄：{out.strip()[:200]}") from None

    def export(self, name: str) -> str:
        return self._run(f"Export-ScheduledTask -TaskName {_ps(name)}\n").strip()

    def register(self, name: str, xml: str) -> None:
        encoded = base64.b64encode(xml.encode("utf-8")).decode("ascii")
        self._run(f"$xml = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{encoded}'))\n"
                  f"Register-ScheduledTask -TaskName {_ps(name)} -Xml $xml | Out-Null\n")

    def unregister(self, name: str) -> None:
        self._run(f"Unregister-ScheduledTask -TaskName {_ps(name)} -Confirm:$false\n")


def default_scheduler():
    return PowerShellScheduler()


def same_folder(a: str, folder: Path) -> bool:
    try:
        return os.path.normcase(str(Path(a).resolve())) == os.path.normcase(str(folder))
    except OSError:
        return False


def runs_here(task: dict, folder: Path) -> bool:
    """The task runs this folder's 背景更新.cmd (its working directory, or the script path in its arguments)."""
    script = os.path.normcase(str(folder / SCRIPT))
    return bool(task.get("working_directory")) and same_folder(task["working_directory"], folder) \
        or script in os.path.normcase(task.get("arguments") or "")


# --- the task this feature registers --------------------------------------------------------------------------------

def conhost() -> str:
    return str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "conhost.exe")


def task_xml(folder: Path, today: date) -> str:
    """Every setting of data-model 「排程工作」; no user name: the task is the current user's (InteractiveToken)."""
    script = folder / SCRIPT
    return (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        '<Task version="1.3" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        f"  <RegistrationInfo><Description>{escape(DESCRIPTION)}</Description></RegistrationInfo>\n"
        "  <Principals><Principal id=\"Author\"><LogonType>InteractiveToken</LogonType>"
        "<RunLevel>LeastPrivilege</RunLevel></Principal></Principals>\n"
        "  <Settings>\n"
        "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n"
        "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n"
        "    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>\n"
        "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n"
        "    <StartWhenAvailable>true</StartWhenAvailable>\n"
        "    <Enabled>true</Enabled>\n"
        "  </Settings>\n"
        f"  <Triggers><CalendarTrigger><StartBoundary>{today.isoformat()}T02:30:00</StartBoundary>"
        "<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger></Triggers>\n"
        '  <Actions Context="Author"><Exec>'
        f"<Command>{escape(conhost())}</Command>"
        f"<Arguments>{escape(f'--headless cmd.exe /d /c \"{script}\"')}</Arguments>"
        f"<WorkingDirectory>{escape(str(folder))}</WorkingDirectory>"
        "</Exec></Actions>\n"
        "</Task>\n")


def manual_steps(folder: Path, name: str) -> str:
    return ("可以改用「工作排程器」手動建立：建立基本工作「" + name + "」→ 每天 02:30 → 啟動程式 "
            f"{conhost()}，引數 --headless cmd.exe /d /c \"{folder / SCRIPT}\"，開始位置 {folder}；"
            "完成後在內容中勾選「錯過排定的開始時間後，盡快執行工作」。")


TASK_HAS_NOT_RUN, TASK_RUNNING = 0x41303, 0x41301     # SCHED_S_TASK_HAS_NOT_RUN 267011, SCHED_S_TASK_RUNNING 267009


def start_time(task: dict) -> str:
    """HH:MM of the task's trigger (014 T056): what it really runs at, also after a change in the Task Scheduler."""
    m = re.search(r"T(\d{2}:\d{2})", task.get("start_boundary") or "")
    return m.group(1) if m else "（不明的時間）"


def _last_run(info: dict) -> str:
    """014 T051: the two status values the Task Scheduler reports as a result, in words (not 1999-11-30 / 267011)."""
    result = info.get("last_task_result")
    if result == TASK_HAS_NOT_RUN or not info.get("last_run_time"):
        return "上次：還沒執行過"
    if result == TASK_RUNNING:
        return f"上次 {info['last_run_time']}，執行中"
    return f"上次 {info['last_run_time']}，結果 {result}"


def _where(task: dict) -> str:
    return task.get("working_directory") or task.get("arguments") or "（不明）"


def run(action: str, folder: Path, scheduler, *, name: str, replace: bool, dry_run: bool, today: date,
        say: Callable[[str], None]) -> int:
    if action != "install" and (dry_run or replace):     # 014 T056: uninstall --dry-run used to remove the task
        say(f"--dry-run 和 --replace 只用於 install；{action} 不接受，什麼都沒改。")
        return 1
    try:
        task = scheduler.query(name)
    except SchedulerError as exc:
        say(f"讀不到排程工作「{name}」：{exc}")
        return 1
    ours = task is not None and runs_here(task, folder)
    if action == "status":
        if task is None:
            say(f"沒有註冊「{name}」。要每天自動更新：uv run sweetspot schedule install")
            return 0
        if not ours:
            say(f"「{name}」存在，但執行的是別的資料夾：{_where(task)}")
            return 0
        try:
            info = scheduler.info(name)
        except SchedulerError as exc:
            info = {"error": str(exc)}
        say(f"「{name}」：每天 {start_time(task)} 執行 {folder / SCRIPT}")
        if "error" in info:
            say(f"  讀不到執行紀錄：{info['error']}")
        else:
            say(f"  {_last_run(info)}；下次 {info.get('next_run_time') or '（不明）'}")
        return 0
    if action == "uninstall":
        if task is None:
            say(f"沒有「{name}」這個排程工作，不需要移除。")
            return 0
        if not ours:
            say(f"「{name}」執行的是別的資料夾（{_where(task)}），不是這裡的；沒有移除。")
            return 1
        try:
            scheduler.unregister(name)
        except SchedulerError as exc:
            say(f"移除「{name}」失敗：{exc}")
            return 1
        say(f"已移除「{name}」。")
        return 0
    # install
    if task is not None and ours and not replace:
        say(f"「{name}」已註冊，每天 {start_time(task)} 執行這個資料夾的 {SCRIPT}；要重建請加 --replace。")
        return 0
    if task is not None and not ours and not replace:
        say(f"「{name}」已經存在，執行的是別的資料夾：{_where(task)}。")
        say(f"要改成這個資料夾（{folder}）請加 --replace；或用 --name 另取一個名稱。")
        return 1
    xml = task_xml(folder, today)
    if dry_run:
        say(f"會{'重建' if task is not None else '建立'}「{name}」：每天 02:30，{conhost()} --headless cmd.exe /d /c "
            f"\"{folder / SCRIPT}\"，錯過時補跑，上限 1 小時（試算，沒有改任何東西）")
        return 0
    try:
        if task is not None:
            scheduler.unregister(name)
        scheduler.register(name, xml)
    except SchedulerError as exc:
        say(f"建立「{name}」失敗：{exc}")
        say(manual_steps(folder, name))
        return 1
    say(f"已建立「{name}」：每天 02:30 在背景執行 {folder / SCRIPT}（錯過時補跑）。")
    return 0


def main(args, stdout: TextIO, stderr: TextIO) -> int:
    """`sweetspot schedule` (sweetspot.cli hands it over once the settings file exists)."""
    folder = Path(args.config).resolve().parent
    return run(args.action, folder, default_scheduler(), name=args.name, replace=args.replace, dry_run=args.dry_run,
               today=date.today(), say=lambda line: print(line, file=stdout, flush=True))
