"""P3 setup: copies of the real data dir where Dying Light's history is replaced (research R4).

Variants (each a separate data dir under the scratch directory given as argv[1]):
  base      unchanged copy (today's behaviour)
  version   Dying Light: old ITAD rows removed, Essentials Edition TW + US history inserted (spec FR-007)
  stopped   Dying Light: old rows kept, but known-until capped at the last observation (spec FR-009/FR-010)
Only the copies are modified (append-only triggers dropped there); the real database is opened read-only.
"""
import shutil
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from steamsage.config import load_secrets
from steamsage.pipeline.history import to_observations
from steamsage.sources.itad import parse_history
from steamsage.store.writer import StoreWriter
from steamsage.timeutil import to_db

APP, NEW_GAME = 239140, "0197ad38-0c21-73fa-bb69-9c7b41676553"
NOW = datetime.now(UTC) - timedelta(hours=1)   # before the report's as_of
scratch = Path(sys.argv[1])
H = {"ITAD-API-Key": load_secrets().itad_api_key.reveal()}
history = {}
for region in ("TW", "US"):
    r = httpx.get("https://api.isthereanydeal.com/games/history/v2", headers=H, timeout=60,
                  params={"id": NEW_GAME, "country": region, "shops": 61, "since": "2010-01-01T00:00:00Z"})
    history[region] = parse_history(r.json())
    print(region, len(history[region]), "entries, first", history[region][0].observed_at.date(),
          "regulars", sorted({e.regular_cents for e in history[region]}))


def copy(name: str) -> sqlite3.Connection:
    target = scratch / name
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    shutil.copy("data/steam_sales.toml", target / "steam_sales.toml")
    shutil.copytree("data/forecasts", target / "forecasts")
    src = sqlite3.connect("file:data/steamsage.db?mode=ro", uri=True)
    dst = sqlite3.connect(target / "steamsage.db", isolation_level=None)
    src.backup(dst)
    src.close()
    for (trigger,) in dst.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall():
        dst.execute(f"DROP TRIGGER {trigger}")
    dst.commit()
    toml = Path("steamsage.toml").read_text(encoding="utf-8").replace('data_dir = "data"', f"data_dir = '{target}'")
    (scratch / f"{name}.toml").write_text(toml, encoding="utf-8")
    return dst


copy("base").close()

db = copy("version")
db.execute("DELETE FROM price_observations WHERE app_id=? AND source IN ('itad-history','legacy-itad')", (APP,))
db.execute("DELETE FROM history_fetches WHERE app_id=?", (APP,))
db.commit()
writer = StoreWriter(db)
for region, entries in history.items():
    writer.add_observations("p3", to_observations(APP, entries, region=region, primary_region="TW", retrieved_at=NOW))
    db.execute("INSERT INTO history_fetches (app_id, source, region, fetched_at, entries, run_id) VALUES "
               "(?, 'itad', ?, ?, ?, 'p3')", (APP, region, to_db(NOW), len(entries)))
db.commit()
db.close()

db = copy("stopped")
last = db.execute("SELECT MAX(observed_at) FROM price_observations WHERE app_id=? AND region='TW' AND source IN "
                  "('itad-history','legacy-itad')", (APP,)).fetchone()[0]
db.execute("UPDATE history_fetches SET fetched_at=? WHERE app_id=?", (last, APP))
db.execute("UPDATE price_observations SET retrieved_at=? WHERE app_id=? AND source='legacy-itad'", (last, APP))
db.commit()
print("stopped: known-until capped at", last)
db.close()
