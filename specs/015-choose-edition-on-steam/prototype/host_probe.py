"""Prototype native messaging host (015 plan research R0). Standard library only.

Started by Chrome through host.bat: `python host_probe.py <log dir> <Chrome's arguments...>`. Every step is appended to
<log dir>/host-<pid>.log so the probe can see what happened even when Chrome killed the process.
With `--child <seconds> <log dir>` it is the breakaway child of the "spawn" command instead.
"""
import ctypes
import json
import os
import struct
import subprocess
import sys
import time
from ctypes import wintypes

STARTED = time.time()


def log(path, text):
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{time.time():.3f} {text}\n")


def job_flags():
    """(in a job?, the job's limit flags) for this process."""
    kernel32 = ctypes.windll.kernel32
    in_job = wintypes.BOOL()
    kernel32.IsProcessInJob(kernel32.GetCurrentProcess(), None, ctypes.byref(in_job))

    class Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class Extended(ctypes.Structure):
        _fields_ = [("Basic", Basic), ("Io", ctypes.c_uint64 * 6), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    info = Extended()
    ok = kernel32.QueryInformationJobObject(None, 9, ctypes.byref(info), ctypes.sizeof(info), None)
    flags = info.Basic.LimitFlags if ok else None
    names = {0x2000: "KILL_ON_JOB_CLOSE", 0x800: "BREAKAWAY_OK", 0x1000: "SILENT_BREAKAWAY_OK"}
    return bool(in_job.value), None if flags is None else [n for bit, n in names.items() if flags & bit]


def read_message():
    head = sys.stdin.buffer.read(4)
    if len(head) < 4:
        return None
    (size,) = struct.unpack("=I", head)
    return json.loads(sys.stdin.buffer.read(size).decode("utf-8"))


def write_message(obj):
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("=I", len(data)) + data)
    sys.stdout.buffer.flush()


def work(path, seconds):
    log(path, f"work start {seconds}")
    end = time.time() + seconds
    while time.time() < end:
        time.sleep(0.5)
        log(path, "tick")
    log(path, "work done")


def spawn(path, log_dir, seconds):
    flags = subprocess.CREATE_BREAKAWAY_FROM_JOB | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    args = [sys.executable, os.path.abspath(__file__), "--child", str(seconds), log_dir]
    try:
        child = subprocess.Popen(args, creationflags=flags, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, close_fds=True)
        breakaway = True
    except OSError as exc:
        log(path, f"breakaway failed: {exc}")
        child = subprocess.Popen(args, creationflags=flags & ~subprocess.CREATE_BREAKAWAY_FROM_JOB,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        breakaway = False
    log(path, f"spawned child {child.pid} breakaway={breakaway}")
    return child.pid, breakaway


def child_main(seconds, log_dir):
    path = os.path.join(log_dir, f"child-{os.getpid()}.log")
    log(path, f"child start in_job={job_flags()}")
    time.sleep(seconds)
    log(path, "child done")


def main():
    if sys.argv[1] == "--child":
        child_main(float(sys.argv[2]), sys.argv[3])
        return
    log_dir = sys.argv[1]
    path = os.path.join(log_dir, f"host-{os.getpid()}.log")
    log(path, f"start argv={sys.argv[2:]!r} cwd={os.getcwd()!r} exe={sys.executable!r} ppid={os.getppid()}")
    try:
        while True:
            msg = read_message()
            if msg is None:
                log(path, "eof")
                return
            log(path, f"message {msg!r}")
            cmd = msg.get("cmd")
            reply = {"cmd": cmd, "pid": os.getpid()}
            if cmd == "hello":
                in_job, flags = job_flags()
                reply.update(argv=sys.argv[2:], cwd=os.getcwd(), started_ms=round((time.time() - STARTED) * 1000),
                             in_job=in_job, job_flags=flags, exe=sys.executable)
            elif cmd == "work":
                work(path, msg["seconds"])
            elif cmd == "spawn_then_work":
                reply["child"], reply["breakaway"] = spawn(path, log_dir, msg["child_seconds"])
                work(path, msg["seconds"])
            try:
                write_message(reply)
                log(path, "replied")
            except OSError as exc:
                log(path, f"write failed: {exc!r}")
                return
    except Exception as exc:  # noqa: BLE001 - a probe: record everything
        log(path, f"error {exc!r}")


if __name__ == "__main__":
    main()
