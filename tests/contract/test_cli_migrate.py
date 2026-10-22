"""016 contracts/migrate.md §1–§3: `sweetspot migrate` on the command line (exit codes, output, --json, log, keys)."""

import io
import json
import os
import shutil

import pytest

from sweetspot import cli, legacy, migrate
from tests.integration.test_migrate import BACKUP, NOW, FakeScheduler, make_folder, summary

FAKE_KEYS = {"ITAD_API_KEY": "itad-key-0123456789abcdef", "STEAM_WEB_API_KEY": "STEAMKEY0123456789ABCDEF"}


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(migrate, "now_utc", lambda: NOW)
    return make_folder(tmp_path)


def run(root, *args):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(["migrate", "--config", str(root / "sweetspot.toml"), *args], stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_help_lists_the_options(capsys):
    with pytest.raises(SystemExit) as info:
        cli.main(["migrate", "--help"])
    assert info.value.code == 0
    text = capsys.readouterr().out
    assert "--dry-run" in text and "--json" in text and "--config" in text


def test_output_has_the_four_parts_in_order(root):
    code, out, _ = run(root)
    assert code == 0, out
    marks = ["設定檔 steamsage.toml → sweetspot.toml：已搬（SHA-256 相同）",
             "資料庫 steamsage.db → sweetspot.db：已搬（SHA-256 相同）",
             "擴充功能資料檔 steamsage-extension.json → sweetspot-extension.json：已搬（SHA-256 相同）",
             f"備份：{(root / BACKUP).resolve()}",
             "本機程式：不適用：這個資料夾沒有登記本機程式",
             f"排程工作：不適用：沒有「{legacy.OLD_TASK}」排程工作",
             "接下來要你做的事"]
    positions = [out.index(m) for m in marks]
    assert positions == sorted(positions)
    steps = out[out.index("接下來要你做的事"):]
    assert "1. " in steps and "chrome://extensions" in steps and "1.2.0 以上" in steps and "暫時不顯示" in steps
    assert "下一次報告" in steps and "更新資料.cmd" in steps
    assert f"刪除備份資料夾 {(root / BACKUP).resolve()}" in steps


def test_json_matches_the_record(root):
    code, out, _ = run(root, "--json")
    assert code == 0
    payload = json.loads(out)
    record = json.loads((root / BACKUP / "migration.json").read_text(encoding="utf-8"))
    assert payload == record


def test_exit_1_when_old_and_new_are_side_by_side(root):
    shutil.copy(root / "steamsage.toml", root / "sweetspot.toml")
    code, out, _ = run(root)
    assert code == 1 and "同時存在" in out


def test_exit_2_when_an_environment_step_fails(root, monkeypatch):
    sched = FakeScheduler({legacy.OLD_TASK: summary(root)}, fail={"register"})
    monkeypatch.setattr(migrate, "default_scheduler", lambda: sched)
    code, out, _ = run(root)
    assert code == 2
    assert "排程工作：失敗：" in out and "改成手動步驟" in out
    assert "Register-ScheduledTask" in out[out.index("接下來要你做的事"):]


def test_exit_3_when_the_writer_lock_is_held(root):
    (root / "data" / ".lock").write_text(f"{os.getpid()}\n", encoding="utf-8")
    code, out, err = run(root)
    assert code == 3 and "什麼都沒改" in out + err


def test_every_step_is_logged_and_keys_never_appear(root, monkeypatch):
    for name, value in FAKE_KEYS.items():
        monkeypatch.setenv(name, value)
    code, out, err = run(root)
    assert code == 0
    logs = list((root / "data" / "logs").glob("sweetspot-*.log"))
    assert len(logs) == 1
    log = logs[0].read_text(encoding="utf-8")
    for word in ("搬家開始", "備份", "改名", "驗證", "本機程式", "排程工作", "搬家結束"):
        assert word in log, word
    assert "本機程式：本機程式" not in log and "排程工作：排程工作" not in log   # seen in the real log 2026-10-15
    record = (root / BACKUP / "migration.json").read_text(encoding="utf-8")
    for value in FAKE_KEYS.values():
        assert (value in out, value in err, value in log, value in record) == (False, False, False, False)


def test_dry_run_on_the_command_line_writes_nothing(root):
    before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
    code, out, _ = run(root, "--dry-run")
    assert code == 0 and "會" in out
    assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) == before
