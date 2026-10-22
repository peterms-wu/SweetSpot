"""014 T029: `sweetspot schedule install|uninstall|status` (contracts/cli.md §3; data-model 「排程工作」; FR-012,
FR-012a). A fake scheduler stands in for the Task Scheduler; nothing real is registered."""

import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import pytest

from sweetspot import schedule

NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
TODAY = date(2026, 10, 18)


class FakeScheduler:
    def __init__(self, tasks=None, fail=None):
        self.tasks = dict(tasks or {})        # name -> xml
        self.fail = fail or set()
        self.calls = []

    def _maybe_fail(self, op):
        if op in self.fail:
            raise schedule.SchedulerError(f"{op}: 存取被拒")

    def query(self, name):
        self._maybe_fail("query")
        xml = self.tasks.get(name)
        if xml is None:
            return None
        root = ET.fromstring(xml)
        exec_ = root.find("t:Actions/t:Exec", NS)
        return {"execute": exec_.findtext("t:Command", namespaces=NS),
                "arguments": exec_.findtext("t:Arguments", namespaces=NS),
                "working_directory": exec_.findtext("t:WorkingDirectory", namespaces=NS),
                "start_boundary": root.findtext("t:Triggers/t:CalendarTrigger/t:StartBoundary", namespaces=NS),
                "start_when_available": root.findtext("t:Settings/t:StartWhenAvailable", namespaces=NS) == "true",
                "logon_type": "Interactive", "run_level": "Limited"}

    def info(self, name):
        return {"last_run_time": "2026/10/18 02:30:01", "last_task_result": 0, "next_run_time": "2026/10/19 02:30:00"}

    def register(self, name, xml):
        self._maybe_fail("register")
        self.calls.append(("register", name))
        self.tasks[name] = xml

    def unregister(self, name):
        self._maybe_fail("unregister")
        self.calls.append(("unregister", name))
        del self.tasks[name]


@pytest.fixture
def folder(tmp_path):
    f = tmp_path / "我的 SweetSpot"
    f.mkdir()
    return f


def run(action, folder, sched, **kw):
    lines = []
    code = schedule.run(action, folder.resolve(), sched, name=kw.get("name", schedule.DEFAULT_NAME),
                        replace=kw.get("replace", False), dry_run=kw.get("dry_run", False), today=TODAY, say=lines.append)
    return code, "\n".join(lines)


# --- the task definition -------------------------------------------------------------------------------------------

def test_task_xml_has_every_setting_of_the_data_model(folder):
    root = ET.fromstring(schedule.task_xml(folder.resolve(), TODAY))
    trigger = root.find("t:Triggers/t:CalendarTrigger", NS)
    assert trigger.findtext("t:StartBoundary", namespaces=NS) == "2026-10-18T02:30:00"
    assert trigger.findtext("t:ScheduleByDay/t:DaysInterval", namespaces=NS) == "1"
    exec_ = root.find("t:Actions/t:Exec", NS)
    assert exec_.findtext("t:Command", namespaces=NS).lower().endswith(r"\system32\conhost.exe")
    script = folder.resolve() / "背景更新.cmd"
    assert exec_.findtext("t:Arguments", namespaces=NS) == f'--headless cmd.exe /d /c "{script}"'
    assert exec_.findtext("t:WorkingDirectory", namespaces=NS) == str(folder.resolve())
    settings = root.find("t:Settings", NS)
    assert settings.findtext("t:StartWhenAvailable", namespaces=NS) == "true"
    assert settings.findtext("t:ExecutionTimeLimit", namespaces=NS) == "PT1H"
    assert settings.findtext("t:MultipleInstancesPolicy", namespaces=NS) == "IgnoreNew"
    assert settings.findtext("t:DisallowStartIfOnBatteries", namespaces=NS) == "false"
    assert settings.findtext("t:StopIfGoingOnBatteries", namespaces=NS) == "false"
    principal = root.find("t:Principals/t:Principal", NS)
    assert principal.findtext("t:LogonType", namespaces=NS) == "InteractiveToken"
    assert principal.findtext("t:RunLevel", namespaces=NS) == "LeastPrivilege"
    assert principal.find("t:UserId", NS) is None                        # the current user; no name written
    assert "02:30" in root.findtext("t:RegistrationInfo/t:Description", namespaces=NS)


def test_task_xml_escapes_the_folder(tmp_path):
    odd = tmp_path / "A&B's 資料夾"
    odd.mkdir()
    root = ET.fromstring(schedule.task_xml(odd.resolve(), TODAY))
    assert root.findtext("t:Actions/t:Exec/t:WorkingDirectory", namespaces=NS) == str(odd.resolve())


# --- install -------------------------------------------------------------------------------------------------------

def test_install_creates_the_task(folder):
    sched = FakeScheduler()
    code, out = run("install", folder, sched)
    assert code == 0 and sched.calls == [("register", schedule.DEFAULT_NAME)]
    assert "02:30" in out


def test_install_twice_leaves_it(folder):
    sched = FakeScheduler()
    run("install", folder, sched)
    code, out = run("install", folder, sched)
    assert code == 0 and "已註冊" in out and sched.calls == [("register", schedule.DEFAULT_NAME)]


def test_install_replace_rebuilds_ours(folder):
    sched = FakeScheduler()
    run("install", folder, sched)
    code, _ = run("install", folder, sched, replace=True)
    assert code == 0 and sched.calls[-2:] == [("unregister", schedule.DEFAULT_NAME), ("register", schedule.DEFAULT_NAME)]


def test_install_refuses_a_task_of_another_folder(folder, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    sched = FakeScheduler({schedule.DEFAULT_NAME: schedule.task_xml(other.resolve(), TODAY)})
    code, out = run("install", folder, sched)
    assert code == 1 and str(other.resolve()) in out and "--replace" in out
    assert sched.calls == []
    code, _ = run("install", folder, sched, replace=True)
    assert code == 0 and str(folder.resolve()) in sched.tasks[schedule.DEFAULT_NAME]


def test_install_under_another_name(folder):
    sched = FakeScheduler()
    code, _ = run("install", folder, sched, name="SweetSpot 驗收")
    assert code == 0 and list(sched.tasks) == ["SweetSpot 驗收"]


def test_install_dry_run_registers_nothing(folder):
    sched = FakeScheduler()
    code, out = run("install", folder, sched, dry_run=True)
    assert code == 0 and sched.calls == [] and "conhost.exe" in out


def test_install_failure_gives_manual_steps(folder):
    sched = FakeScheduler(fail={"register"})
    code, out = run("install", folder, sched)
    assert code == 1 and "存取被拒" in out and "工作排程器" in out and "02:30" in out


# --- uninstall -----------------------------------------------------------------------------------------------------

def test_uninstall_removes_ours(folder):
    sched = FakeScheduler()
    run("install", folder, sched)
    code, _ = run("uninstall", folder, sched)
    assert code == 0 and sched.tasks == {}


def test_uninstall_without_a_task(folder):
    code, out = run("uninstall", folder, FakeScheduler())
    assert code == 0 and "沒有" in out


def test_uninstall_never_removes_another_folders_task(folder, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    sched = FakeScheduler({schedule.DEFAULT_NAME: schedule.task_xml(other.resolve(), TODAY)})
    code, out = run("uninstall", folder, sched)
    assert code == 1 and schedule.DEFAULT_NAME in sched.tasks and str(other.resolve()) in out


# --- status --------------------------------------------------------------------------------------------------------

def test_status_of_ours_and_of_none(folder):
    sched = FakeScheduler()
    code, out = run("status", folder, sched)
    assert code == 0 and "沒有註冊" in out
    run("install", folder, sched)
    code, out = run("status", folder, sched)
    assert code == 0 and "02:30" in out and "2026/10/18 02:30:01" in out and "結果 0" in out


def test_status_says_when_it_runs_another_folder(folder, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    sched = FakeScheduler({schedule.DEFAULT_NAME: schedule.task_xml(other.resolve(), TODAY)})
    code, out = run("status", folder, sched)
    assert code == 0 and "別的資料夾" in out and str(other.resolve()) in out


@pytest.mark.parametrize(("info", "said", "not_said"), [
    # what Get-ScheduledTaskInfo reports for a task that never ran (seen in 014 T045)
    ({"last_run_time": "11/30/1999 00:00:00", "last_task_result": 267011, "next_run_time": "10/22/2026 02:30:00"},
     "上次：還沒執行過", ("1999", "267011")),
    ({"last_run_time": "", "last_task_result": 0, "next_run_time": "10/22/2026 02:30:00"},
     "上次：還沒執行過", ("結果",)),
    ({"last_run_time": "10/18/2026 12:25:01", "last_task_result": 267009, "next_run_time": "10/19/2026 02:30:00"},
     "上次 10/18/2026 12:25:01，執行中", ("267009",)),
    ({"last_run_time": "10/18/2026 02:30:01", "last_task_result": 1, "next_run_time": "10/19/2026 02:30:00"},
     "上次 10/18/2026 02:30:01，結果 1", ()),
])
def test_status_says_the_schedulers_own_values_in_words(folder, info, said, not_said):
    """014 T051 (contracts/cli.md §3): 267011 / 267009 are states, not results."""
    sched = FakeScheduler()
    run("install", folder, sched)
    sched.info = lambda name: info
    code, out = run("status", folder, sched)
    assert code == 0 and said in out and "下次 " + info["next_run_time"] in out
    assert not any(text in out for text in not_said)


def test_status_says_the_tasks_own_start_time(folder):
    """014 T056: the time comes from the task's trigger, not from what install would write (02:30)."""
    sched = FakeScheduler()
    run("install", folder, sched)
    sched.tasks[schedule.DEFAULT_NAME] = sched.tasks[schedule.DEFAULT_NAME].replace("T02:30:00", "T04:15:00")
    sched.info = lambda name: {"last_run_time": "", "last_task_result": 267011, "next_run_time": "10/19/2026 04:15:00"}
    code, out = run("status", folder, sched)
    assert code == 0 and "每天 04:15 執行" in out and "02:30" not in out


@pytest.mark.parametrize("boundary", ["2026-09-27T02:30:00+08:00", "2026-10-18T02:30:00"])
def test_start_time_reads_both_forms_of_the_boundary(boundary):
    assert schedule.start_time({"start_boundary": boundary}) == "02:30"


def test_start_time_unknown():
    assert schedule.start_time({"start_boundary": None}) == "（不明的時間）"


@pytest.mark.parametrize("action", ["uninstall", "status"])
@pytest.mark.parametrize("flag", ["dry_run", "replace"])
def test_only_install_takes_dry_run_and_replace(folder, action, flag):
    """014 T056 (contracts/cli.md §3): `uninstall --dry-run` used to remove the task for real."""
    sched = FakeScheduler()
    run("install", folder, sched)
    code, out = run(action, folder, sched, **{flag: True})
    assert code == 1 and "install" in out
    assert sched.calls == [("register", schedule.DEFAULT_NAME)] and schedule.DEFAULT_NAME in sched.tasks


def test_query_failure_is_1(folder):
    code, out = run("status", folder, FakeScheduler(fail={"query"}))
    assert code == 1 and "存取被拒" in out


# --- the PowerShell side stays as 016 left it ----------------------------------------------------------------------

def test_migrate_still_uses_the_same_scheduler():
    from sweetspot import migrate

    assert migrate.PowerShellScheduler is schedule.PowerShellScheduler
    assert migrate.SchedulerError is schedule.SchedulerError
