"""P2 (plan): a copy of the real database with every listable edition's ITAD history added (research R3).

The real database is only read (sqlite backup API). In the copy, each edition's TW and US history is stored under the
wishlist app's id with its own ITAD product id and a separate source `itad-option-history` (history_fetches source
`itad-option`), so every existing reader that filters on the ITAD history sources ignores it. Needs out/p1.json.
Writes out/p2.db (+ steam_sales.toml next to it) and out/p2.json (timings, rows added).
"""
import json
from dataclasses import replace
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from steamsage.cli import Context
from steamsage.commands import itad_source
from steamsage.config import load_config, load_secrets
from steamsage.pipeline.history import to_observations
from steamsage.store.writer import StoreWriter
from steamsage.timeutil import now_utc, to_db

OUT = Path(__file__).parent / "out"
OPTION_SOURCE, OPTION_FETCH = "itad-option-history", "itad-option"
p1 = json.loads((OUT / "p1.json").read_text(encoding="utf-8"))
editions = [r for r in p1["rows"] if r["cls"] in ("P+", "BO") and r["verdict"][0] == "verified"]

t0 = time.perf_counter()
target = OUT / "p2.db"
for suffix in ("", "-wal", "-shm"):
    Path(f"{target}{suffix}").unlink(missing_ok=True)
src = sqlite3.connect("file:data/steamsage.db?mode=ro", uri=True)
dst = sqlite3.connect(target)
src.backup(dst)
dst.close()
src.close()
shutil.copy("data/steam_sales.toml", OUT / "steam_sales.toml")
copy_s = round(time.perf_counter() - t0, 1)

ctx = Context(load_config(Path("steamsage.toml"))[0], load_secrets(), None, None)
itad = itad_source(ctx)
writer = StoreWriter.open(target)
run_id = None   # no runs row: the copy must differ from the real database only by the edition histories
now = now_utc()
since = datetime(2010, 1, 1, tzinfo=timezone.utc)
added, t1 = 0, time.perf_counter()
for r in editions:
    for region in ("TW", "US"):
        entries = itad.history(r["itad_id"], region, since)
        obs = [replace(o, source=OPTION_SOURCE)
               for o in to_observations(r["app_id"], entries, region=region, primary_region="TW", retrieved_at=now,
                                        external_id=r["itad_id"])]
        with writer.transaction():
            added += writer.add_observations(run_id, obs)
            writer.conn.execute("INSERT INTO history_fetches (app_id, source, region, fetched_at, entries, run_id, "
                                "external_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                (r["app_id"], OPTION_FETCH, region, to_db(now), len(entries), run_id, r["itad_id"]))

writer.close()
info = {"copy_seconds": copy_s, "history_seconds": round(time.perf_counter() - t1, 1), "editions": len(editions),
        "rows_added": added, "fetched_at": to_db(now)}
(OUT / "p2.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
print(info)
