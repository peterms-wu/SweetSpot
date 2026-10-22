import os

import pytest

from sweetspot.lock import LockHeld, WriterLock


def test_second_acquire_reports_holder_pid(tmp_path):
    path = tmp_path / ".lock"
    with WriterLock(path):
        with pytest.raises(LockHeld) as info:
            WriterLock(path).acquire()
        assert info.value.pid == os.getpid()
    assert not path.exists()


def test_stale_lock_from_dead_pid_is_taken_over(tmp_path):
    path = tmp_path / ".lock"
    path.write_text("999999999\n2026-01-01T00:00:00Z\n", encoding="utf-8")
    lock = WriterLock(path, pid_alive=lambda pid: False)
    lock.acquire()
    assert path.read_text(encoding="utf-8").splitlines()[0] == str(os.getpid())
    assert lock.took_over_pid == 999999999
    lock.release()


def test_live_foreign_lock_is_respected(tmp_path):
    path = tmp_path / ".lock"
    path.write_text("4242\n2026-01-01T00:00:00Z\n", encoding="utf-8")
    with pytest.raises(LockHeld) as info:
        WriterLock(path, pid_alive=lambda pid: True).acquire()
    assert info.value.pid == 4242


def test_garbage_lock_file_is_treated_as_stale(tmp_path):
    path = tmp_path / ".lock"
    path.write_text("not a pid", encoding="utf-8")
    lock = WriterLock(path, pid_alive=lambda pid: True)
    lock.acquire()
    lock.release()
