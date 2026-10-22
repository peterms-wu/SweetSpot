"""SC-007 / FR-015: a process killed mid-write leaves a usable database, committed data intact,
the run marked interrupted and its lock taken over by the next writer."""

import os
import subprocess
import sys
import textwrap

from sweetspot.lock import WriterLock
from sweetspot.store.writer import StoreWriter

CHILD = textwrap.dedent("""
    import os, sys
    from datetime import UTC, datetime
    from sweetspot.lock import WriterLock
    from sweetspot.store.writer import NewObservation, StoreWriter

    data = sys.argv[1]
    WriterLock(os.path.join(data, ".lock")).acquire()
    writer = StoreWriter.open(os.path.join(data, "sweetspot.db"))
    run_id = writer.start_run("daily")
    now = datetime(2026, 9, 25, tzinfo=UTC)
    obs = lambda app: NewObservation(app, "steam-current", "TW", "TWD", 1000, 500, 50, now, None, now)
    writer.add_observations(run_id, [obs(1)])            # committed
    writer.conn.execute("BEGIN IMMEDIATE")
    writer.conn.execute(
        "INSERT INTO price_observations (app_id, source, region, currency, regular_cents, price_cents, cut_pct, "
        "observed_at, retrieved_at) VALUES (2, 'steam-current', 'TW', 'TWD', 1000, 500, 50, "
        "'2026-09-25T00:00:00.000000Z', '2026-09-25T00:00:00.000000Z')")
    print("ready", flush=True)
    os._exit(9)                                          # killed mid-transaction: no commit, no cleanup
""")


def test_killed_writer_leaves_consistent_database(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    result = subprocess.run([sys.executable, "-c", CHILD, str(data)], capture_output=True, text=True, timeout=60,
                            env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)})
    assert result.returncode == 9 and "ready" in result.stdout, result.stderr
    assert (data / ".lock").exists()                     # left behind by the dead process

    lock = WriterLock(data / ".lock")
    lock.acquire()                                       # stale lock is taken over
    try:
        writer = StoreWriter.open(data / "sweetspot.db")
        assert writer.conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        apps = [a for (a,) in writer.conn.execute("SELECT app_id FROM price_observations ORDER BY app_id")]
        assert apps == [1]                               # committed row kept, uncommitted row gone
        interrupted = writer.mark_interrupted_runs()
        assert len(interrupted) == 1
        assert writer.conn.execute("SELECT status FROM runs").fetchone()[0] == "interrupted"
        writer.close()
    finally:
        lock.release()
