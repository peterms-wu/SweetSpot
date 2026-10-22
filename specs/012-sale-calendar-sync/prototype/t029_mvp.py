"""T029 (MVP on real data): the branch's update + report on a copy of the main folder's database, compared with master
on the same data, plus a simulation of "the file lacks 2026 winter, the official page lists it".

Nothing here writes to 〈專案資料夾〉\\data; the main database is only read (sqlite backup API).

Usage (from the worktree root):
  uv run python specs/012-sale-calendar-sync/prototype/t029_mvp.py prepare
      out/mvp/: steamsage.toml (the user's, copied), data/steamsage.db (backup of the main one, v5),
      data/steam_sales.toml (this branch's), data/forecasts/ (the main folder's records, so the report has a baseline)
  uv run steamsage update --config specs/012-sale-calendar-sync/prototype/out/mvp/steamsage.toml --json
  uv run steamsage report --config specs/012-sale-calendar-sync/prototype/out/mvp/steamsage.toml --json
  uv run python specs/012-sale-calendar-sync/prototype/t029_mvp.py same-data <AS_OF>
      out/master.db = the updated copy without the two feature-012 tables (schema 5, what master knows)
  uv run python .../t029_mvp.py decide out/mvp/data/steamsage.db out/branch.json <AS_OF>
  uv run --project 〈專案資料夾〉 python .../t029_mvp.py decide out/master.db out/master.json <AS_OF>
  uv run python .../t029_mvp.py compare out/branch.json out/master.json
  uv run python .../t029_mvp.py sim-prepare
      out/sim/: the updated copy with empty feature-012 tables and a calendar file without 2026 winter
  (then: steamsage calendar, report, rename the record to the previous day, restore the sightings, report again)
"""

import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "out"
MAIN = Path(r"〈專案資料夾〉")
ROOT = HERE.parents[2]
CAL_TABLES = ("sale_sightings", "calendar_fetches")
ADDED_BATCH_KEYS: set[str] = set()


def _backup(src_path: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        Path(f"{target}{suffix}").unlink(missing_ok=True)
    src = sqlite3.connect(f"file:{src_path.as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    src.backup(dst)
    dst.close()
    src.close()


def prepare() -> None:
    mvp = OUT / "mvp"
    if mvp.exists():
        shutil.rmtree(mvp)
    (mvp / "data").mkdir(parents=True)
    shutil.copy(MAIN / "steamsage.toml", mvp / "steamsage.toml")
    _backup(MAIN / "data" / "steamsage.db", mvp / "data" / "steamsage.db")
    shutil.copy(ROOT / "data" / "steam_sales.toml", mvp / "data" / "steam_sales.toml")
    shutil.copytree(MAIN / "data" / "forecasts", mvp / "data" / "forecasts")
    version = sqlite3.connect(mvp / "data" / "steamsage.db").execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()[0]
    print(f"prepared {mvp}: schema v{version}, {len(list((mvp / 'data' / 'forecasts').iterdir()))} records")


def _without_calendar_tables(target: Path, version: str) -> None:
    conn = sqlite3.connect(target)
    for table in CAL_TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.execute("UPDATE schema_meta SET value = ? WHERE key = 'schema_version'", (version,))
    conn.commit()
    conn.close()


def same_data(as_of: str) -> None:
    target = OUT / "master.db"
    _backup(OUT / "mvp" / "data" / "steamsage.db", target)
    _without_calendar_tables(target, "5")
    print(f"{target}: the updated copy without {CAL_TABLES}, schema v5")


def decide(db: str, out: str, as_of: str) -> None:
    from steamsage.config import load_config
    from steamsage.decision.contract import batch_to_dict
    from steamsage.decision.engine import run_decisions
    from steamsage.forecast.models import current_model
    from steamsage.store.query import PriceStore

    moment = datetime.fromisoformat(as_of)
    config = load_config(OUT / "mvp" / "steamsage.toml")[0]
    store = PriceStore.open(Path(db), OUT / "mvp" / "data" / "steam_sales.toml")
    batch = run_decisions(store, store.wishlist_apps(), moment, current_model(), config.preferences, now=moment,
                          choices=config.purchase_options)
    Path(out).write_text(json.dumps(batch_to_dict(batch), ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(f"{out}: {len(batch.decisions)} decisions")


def compare(branch: str, master: str) -> None:
    bb = json.loads(Path(branch).read_text(encoding="utf-8"))
    mb = json.loads(Path(master).read_text(encoding="utf-8"))
    b = {d["app_id"]: d for d in bb["decisions"]}
    m = {d["app_id"]: d for d in mb["decisions"]}
    assert set(b) == set(m), set(b) ^ set(m)
    differ = [(a, b[a]["name"], sorted(k for k in set(b[a]) | set(m[a]) if b[a].get(k) != m[a].get(k)))
              for a in sorted(b) if b[a] != m[a]]
    batch_extra = sorted(set(bb) - set(mb))
    other = sorted(k for k in set(bb) & set(mb) if k not in ("decisions", "generated_at") and bb[k] != mb[k])
    print(f"{len(b)} decisions; identical {len(b) - len(differ)}/{len(b)}; batch keys only on the branch: "
          f"{batch_extra}; other differing batch keys: {other}")
    for row in differ:
        print("  ", row)


def master_folder() -> None:
    """T043 (SC-004): out/mvp_master/ = the same config and calendar file with out/master.db, for master's backtest."""
    folder = OUT / "mvp_master"
    if folder.exists():
        shutil.rmtree(folder)
    (folder / "data").mkdir(parents=True)
    shutil.copy(OUT / "mvp" / "steamsage.toml", folder / "steamsage.toml")
    shutil.copy(OUT / "mvp" / "data" / "steam_sales.toml", folder / "data" / "steam_sales.toml")
    _backup(OUT / "master.db", folder / "data" / "steamsage.db")
    print(f"prepared {folder}")


def compare_backtests(branch: str, master: str) -> None:
    """The two backtest result files, ignoring when they were written."""
    def load(path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if k not in ("generated_at", "started_at", "finished_at", "seconds")}
    b, m = load(branch), load(master)
    differ = sorted(k for k in set(b) | set(m) if b.get(k) != m.get(k))
    print(f"keys {len(b)}; differing: {differ}")
    for key in ("dataset", "datasets", "dataset_id"):
        if key in b:
            print(f"  {key}: branch {json.dumps(b[key], ensure_ascii=False)[:200]}")
            print(f"  {key}: master {json.dumps(m.get(key), ensure_ascii=False)[:200]}")


def sim_prepare() -> None:
    sim = OUT / "sim"
    if sim.exists():
        shutil.rmtree(sim)
    (sim / "data" / "forecasts").mkdir(parents=True)
    shutil.copy(OUT / "mvp" / "steamsage.toml", sim / "steamsage.toml")
    _backup(OUT / "mvp" / "data" / "steamsage.db", sim / "data" / "steamsage.db")
    _backup(OUT / "mvp" / "data" / "steamsage.db", OUT / "sim_with_sightings.db")
    _without_calendar_tables(sim / "data" / "steamsage.db", "5")      # the next writer open recreates them empty
    head, *blocks = (ROOT / "data" / "steam_sales.toml").read_text(encoding="utf-8").split("\n[[sale]]\n")
    kept = [b for b in blocks if 'season = "winter"\nyear = 2026\n' not in b]
    assert len(kept) == len(blocks) - 1
    (sim / "data" / "steam_sales.toml").write_text("\n[[sale]]\n".join([head, *kept]), encoding="utf-8")
    print(f"prepared {sim}: calendar without 2026 winter, empty official-page tables after the next writer open")


def sim_restore() -> None:
    """Copy the official-page rows of the updated copy into the simulation database (append-only: INSERT only)."""
    sim_db = OUT / "sim" / "data" / "steamsage.db"
    conn = sqlite3.connect(sim_db)
    conn.execute("ATTACH DATABASE ? AS src", (str(OUT / "sim_with_sightings.db"),))
    conn.execute("INSERT INTO calendar_fetches SELECT * FROM src.calendar_fetches")
    conn.execute("INSERT INTO sale_sightings SELECT * FROM src.sale_sightings")
    conn.commit()
    print("restored", conn.execute("SELECT COUNT(*) FROM sale_sightings").fetchone()[0], "sightings")
    conn.close()


def sim_summary(record: str) -> None:
    import gzip

    data = json.loads(gzip.decompress(Path(record).read_bytes()))
    on = [d for d in data["decisions"] if (d.get("sweet_point") or {}).get("label") == "2026 冬特"]
    status = sorted({d["sweet_point"]["status"] for d in on})
    comp = data.get("comparison") or {}
    print(f"{Path(record).name}: {len(on)} games on 2026 冬特, status {status}; "
          f"calendar_changes {comp.get('calendar_changes')}; changed_games {comp.get('changed_games')}")


if __name__ == "__main__":
    {"prepare": prepare, "same-data": same_data, "decide": decide, "compare": compare, "master-folder": master_folder,
     "compare-backtests": compare_backtests, "sim-prepare": sim_prepare,
     "sim-restore": sim_restore, "sim-summary": sim_summary}[sys.argv[1]](*sys.argv[2:])
