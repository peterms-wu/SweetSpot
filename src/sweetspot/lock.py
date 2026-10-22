"""Single-writer lock file (FR-027). A lock whose owner process is gone can be taken over."""

import os
import sys
from collections.abc import Callable
from pathlib import Path

from sweetspot.timeutil import now_utc, to_db


class LockHeld(Exception):
    def __init__(self, pid: int):
        super().__init__(f"另一個更新正在執行（PID {pid}）")
        self.pid = pid


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        process_query_limited_information, still_active = 0x1000, 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_lock_pid(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").splitlines()[0])
    except (OSError, ValueError, IndexError):
        return None


class WriterLock:
    def __init__(self, path: Path, pid_alive: Callable[[int], bool] = pid_alive):
        self.path = Path(path)
        self._pid_alive = pid_alive
        self._held = False
        self.took_over_pid: int | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                owner = read_lock_pid(self.path)
                if owner is not None and owner != os.getpid() and self._pid_alive(owner):
                    raise LockHeld(owner) from None
                if owner == os.getpid():
                    raise LockHeld(owner) from None
                self.took_over_pid = owner
                self.path.unlink(missing_ok=True)
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(f"{os.getpid()}\n{to_db(now_utc())}\n")
            self._held = True
            return
        raise LockHeld(read_lock_pid(self.path) or -1)

    def release(self) -> None:
        if self._held:
            self.path.unlink(missing_ok=True)
            self._held = False

    def __enter__(self) -> "WriterLock":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()
