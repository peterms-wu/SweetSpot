"""T031 (SC-001): with nothing specified, the branch's decisions equal master's on the same data.

Usage (from the repo root):
  uv run python specs/009-purchase-options/prototype/t029_same_data.py prepare
      copies data/steamsage.db to out/t029_master.db and removes feature 009's rows there (edition histories,
      edition fetches, purchase_options); the real database is only read.
  uv run --project <master worktree> python specs/009-purchase-options/prototype/t029_same_data.py decide <db> <out>
      runs the decisions of whichever code base executes it, at AS_OF, and writes the contract dict.
  uv run python specs/009-purchase-options/prototype/t029_same_data.py compare <branch.json> <master.json>
      compares every decision; the branch may only add `editions` (and nothing else).
"""
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).parent / "out"
AS_OF = datetime(2026, 9, 27, 0, 51, 5, tzinfo=timezone.utc)
ADDED_KEYS = {"editions"}


def prepare() -> None:
    target = OUT / "t029_master.db"
    for suffix in ("", "-wal", "-shm"):
        Path(f"{target}{suffix}").unlink(missing_ok=True)
    src = sqlite3.connect("file:data/steamsage.db?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    src.backup(dst)
    src.close()
    dst.execute("DROP TRIGGER IF EXISTS trg_price_observations_no_delete")
    removed = dst.execute("DELETE FROM price_observations WHERE source = 'itad-option-history'").rowcount
    fetches = dst.execute("DELETE FROM history_fetches WHERE source = 'itad-option'").rowcount
    dst.execute("DROP TABLE IF EXISTS purchase_options")
    dst.execute("UPDATE schema_meta SET value = '3' WHERE key = 'schema_version'")
    dst.commit()
    dst.close()
    print(f"copy {target}: removed {removed} edition rows, {fetches} edition fetches, purchase_options")


def decide(db: str, out: str) -> None:
    from steamsage.config import load_config
    from steamsage.decision.contract import batch_to_dict
    from steamsage.decision.engine import run_decisions
    from steamsage.forecast.models import current_model
    from steamsage.store.query import PriceStore

    prefs = load_config(Path("steamsage.toml"))[0].preferences
    store = PriceStore.open(Path(db), Path("data/steam_sales.toml"))
    batch = run_decisions(store, store.wishlist_apps(), AS_OF, current_model(), prefs, now=AS_OF)
    Path(out).write_text(json.dumps(batch_to_dict(batch), ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(f"{out}: {len(batch.decisions)} decisions")


def compare(branch: str, master: str) -> None:
    b = {d["app_id"]: d for d in json.loads(Path(branch).read_text(encoding="utf-8"))["decisions"]}
    m = {d["app_id"]: d for d in json.loads(Path(master).read_text(encoding="utf-8"))["decisions"]}
    assert set(b) == set(m), set(b) ^ set(m)
    extra, differ = set(), []
    for app in sorted(b):
        extra |= set(b[app]) - set(m[app])
        same = {k: v for k, v in b[app].items() if k not in ADDED_KEYS} == m[app]
        if not same:
            differ.append((app, b[app]["name"], sorted(k for k in m[app] if b[app].get(k) != m[app][k])))
    print(f"{len(b)} decisions; keys only on the branch: {sorted(extra)}; differing decisions: {len(differ)}")
    for row in differ:
        print("  ", row)
    assert extra <= ADDED_KEYS and not differ


if __name__ == "__main__":
    {"prepare": prepare, "decide": decide, "compare": compare}[sys.argv[1]](*sys.argv[2:])
