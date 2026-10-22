"""T031 (SC-008): the purchase-option step on a normal day (kinds and verifications cached), on a database copy.

Copies data/steamsage.db (read-only) to out/t031_timing.db, runs the production step twice there with real sources:
the first run reuses the kinds and verifications the real update recorded this morning (a normal day); then the
edition TW histories are fetched once with timing. Nothing is written to the real database.
"""
import sqlite3
import time
from datetime import timedelta
from pathlib import Path

from steamsage.cli import Context
from steamsage.commands import itad_source, steam_sources
from steamsage.config import load_config, load_secrets
from steamsage.pipeline import history
from steamsage.pipeline.options import resolve_options
from steamsage.pipeline.versions import AppVersion
from steamsage.store import schema
from steamsage.store.writer import StoreWriter
from steamsage.timeutil import from_db, now_utc

OUT = Path(__file__).parent / "out"
target = OUT / "t031_timing.db"
for suffix in ("", "-wal", "-shm"):
    Path(f"{target}{suffix}").unlink(missing_ok=True)
src = sqlite3.connect("file:data/steamsage.db?mode=ro", uri=True)
dst = sqlite3.connect(target)
src.backup(dst)
src.close()
dst.close()

config = load_config(Path("steamsage.toml"))[0]
ctx = Context(config, load_secrets(), None, None)
_, steam = steam_sources(ctx)
itad = itad_source(ctx)
writer = StoreWriter.open(target)
apps = [a for (a,) in writer.conn.execute("SELECT app_id FROM wishlist_membership WHERE state='in_wishlist'")]
versions = {}
for row in writer.conn.execute("SELECT app_id, status, checked_at, package_id, package_name, external_id, "
                               "verification FROM app_versions v WHERE checked_at = (SELECT MAX(checked_at) FROM "
                               "app_versions w WHERE w.app_id = v.app_id)"):
    versions[row[0]] = AppVersion(row[0], row[1], from_db(row[2]), row[3], row[4], row[5], row[6],
                                  history_id=row[5] if row[6] == "verified" else None)
t0 = time.perf_counter()
options = steam.purchase_options([a for a in apps if a in versions])
t_options = time.perf_counter() - t0
now = now_utc()
t0 = time.perf_counter()
run = resolve_options(writer, steam, itad, steam, apps, options, versions, config.purchase_options, run_id=None,
                      now=now, max_age=timedelta(days=config.cache.mapping_days),
                      kinds_age=timedelta(days=config.cache.static_metadata_days))
t_step = time.perf_counter() - t0
t0 = time.perf_counter()
for f in run.fetch:
    history.ingest_history(writer, itad, app_id=f.app_id, external_id=f.external_id, region="TW", primary_region="TW",
                           now=now, run_id=None, observation_source=schema.OPTION_HISTORY_SOURCE,
                           fetch_source=schema.OPTION_FETCH_SOURCE)
t_hist = time.perf_counter() - t0
writer.close()
print(f"purchase options request (already made by the version step in production): {t_options:.1f}s")
print(f"purchase-option step, caches warm: {t_step:.1f}s; editions {run.summary['editions']}, "
      f"verified {run.summary['editions_verified']}")
print(f"edition TW histories: {len(run.fetch)} in {t_hist:.1f}s")
print(f"normal-day addition to update: {t_step + t_hist:.1f}s")
