"""scripts/backup_db.py: retention and remote parsing (the upload itself needs gh and the network; checked by hand)."""

import importlib.util
import sqlite3
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location("backup_db", Path(__file__).resolve().parents[2] / "scripts" / "backup_db.py")
backup_db = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(backup_db)


def _daily(start: date, days: int) -> list[str]:
    return [f"db-{start + timedelta(days=i):%Y-%m-%d}" for i in range(days)]


def test_keeps_everything_while_short():
    tags = _daily(date(2026, 9, 28), 10)
    assert backup_db.keep_tags(tags) == set(tags)


def test_keeps_newest_daily_plus_first_of_each_month():
    tags = _daily(date(2026, 9, 28), 60)  # 2026-09-28 .. 2026-11-26
    keep = backup_db.keep_tags(tags, daily=14, monthly=12)
    assert set(tags[-14:]) <= keep
    assert {"db-2026-09-28", "db-2026-10-01", "db-2026-11-01"} <= keep
    assert len(keep) == 14 + 3
    assert "db-2026-10-02" not in keep


def test_monthly_limit_drops_oldest_months():
    tags = _daily(date(2025, 1, 1), 500)
    keep = backup_db.keep_tags(tags, daily=14, monthly=12)
    firsts = sorted(t for t in keep if t.endswith("-01"))
    assert len(firsts) == 12
    assert "db-2025-01-01" not in keep


def test_foreign_tags_are_never_deleted():
    tags = ["v1.0.0", *_daily(date(2026, 1, 1), 40)]
    assert "v1.0.0" in backup_db.keep_tags(tags, daily=1, monthly=0)


@pytest.mark.parametrize(
    "url",
    ["git@github.com:someone/SweetSpot-private.git", "https://github.com/someone/SweetSpot-private.git\n",
     "https://github.com/someone/SweetSpot-private"],
)
def test_repo_from_remote(url):
    assert backup_db.repo_from_remote(url) == "someone/SweetSpot-private"


def test_repo_from_remote_rejects_non_github():
    with pytest.raises(ValueError):
        backup_db.repo_from_remote("https://gitlab.com/a/b.git")


def test_zip_holds_the_new_file_names(tmp_path):
    """Feature 016 FR-004: the backup zip uses the new names (older zips keep theirs; README explains restoring)."""
    (tmp_path / "data" / "forecasts").mkdir(parents=True)
    conn = sqlite3.connect(tmp_path / "data" / "sweetspot.db")
    conn.execute("CREATE TABLE t (x)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()
    (tmp_path / "sweetspot.toml").write_text("schema_version = 1\n", encoding="utf-8")
    (tmp_path / "data" / "forecasts" / "20261016T000000Z.json.gz").write_bytes(b"gz")
    dest = tmp_path / "out" / "backup.zip"
    dest.parent.mkdir()
    backup_db.build_zip(dest, root=tmp_path)
    with zipfile.ZipFile(dest) as z:
        assert sorted(z.namelist()) == ["data/forecasts/20261016T000000Z.json.gz", "data/sweetspot.db", "sweetspot.toml"]


def _today_log(root: Path) -> str:
    import logging
    from datetime import datetime

    for handler in logging.getLogger("sweetspot").handlers:
        handler.flush()
    return (root / "data" / "logs" / f"sweetspot-{datetime.now():%Y%m%d}.log").read_text(encoding="utf-8")


class _FakeSubprocess:
    def __init__(self, error=None):
        self.error = error

    def run(self, *args, **kwargs):
        if self.error:
            raise self.error
        return type("Done", (), {"stdout": "git@github.com:owner/repo.git\n"})()


def test_the_result_goes_to_the_daily_log(tmp_path, monkeypatch, capsys):
    """2026-10-18: background-update.log is overwritten each night; the daily log keeps the backup's outcome."""
    (tmp_path / "data").mkdir()
    sqlite3.connect(tmp_path / "data" / "sweetspot.db").close()
    monkeypatch.setattr(backup_db, "ROOT", tmp_path)
    monkeypatch.setattr(backup_db, "subprocess", _FakeSubprocess())
    calls = []
    monkeypatch.setattr(backup_db, "gh", lambda *args: calls.append(args[:2]) or "db-2000-01-01\n")
    assert backup_db.main([]) == 0
    text = _today_log(tmp_path)
    assert "INFO sweetspot.result: backup 結束：代碼 0，" in text
    assert "備份已上傳：owner/repo db-" in text and "已刪除舊備份" not in text
    assert ("release", "create") in calls

    monkeypatch.setattr(backup_db, "subprocess", _FakeSubprocess(RuntimeError("no remote")))
    assert backup_db.main([]) == 1
    assert "WARNING sweetspot.result: backup 結束：代碼 1，" in _today_log(tmp_path)
    assert "備份失敗：no remote" in _today_log(tmp_path)


def test_a_dry_run_writes_no_log(tmp_path, monkeypatch, capsys):
    (tmp_path / "data").mkdir()
    sqlite3.connect(tmp_path / "data" / "sweetspot.db").close()
    monkeypatch.setattr(backup_db, "ROOT", tmp_path)
    monkeypatch.setattr(backup_db, "subprocess", _FakeSubprocess())
    monkeypatch.setattr(backup_db, "gh", lambda *args: "")
    assert backup_db.main(["--dry-run"]) == 0
    assert "[dry-run]" in capsys.readouterr().out
    assert not (tmp_path / "data" / "logs").exists()


class _NoRemote:
    """`git remote get-url private` failing the way git does when there is no such remote."""

    def run(self, args, **kwargs):
        assert args[:3] == ["git", "remote", "get-url"]
        return type("Done", (), {"returncode": 2, "stdout": "", "stderr": "error: No such remote 'private'"})()


def test_without_a_private_remote_the_backup_is_skipped(tmp_path, monkeypatch, capsys):
    """014 FR-013: a new user has no private repo; the nightly run skips the backup, which is not a failure."""
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(backup_db, "ROOT", tmp_path)
    monkeypatch.setattr(backup_db, "subprocess", _NoRemote())
    monkeypatch.setattr(backup_db, "gh", lambda *args: pytest.fail("gh must not run"))
    assert backup_db.main([]) == 0
    assert "略過雲端備份：沒有名為 private 的 git remote" in capsys.readouterr().out
    text = _today_log(tmp_path)
    assert "INFO sweetspot.result: backup 結束：代碼 0，" in text and "略過" in text
    assert not list(tmp_path.rglob("*.zip"))
