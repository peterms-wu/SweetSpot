"""T035 (SC-002): on the same data, the branch's decisions equal master's; the branch only adds `bundles`.

Usage (from the repo root):
  uv run python specs/010-wishlist-bundles/prototype/t035_same_data.py prepare
      copies data/steamsage.db to out/t035_branch.db and out/t035_master.db (the real database is only read).
      The v5 columns stay: master never reads them (research R7).
  uv run python specs/010-wishlist-bundles/prototype/t035_same_data.py decide out/t035_branch.db out/t035_branch.json
  uv run --project <master worktree> python specs/010-wishlist-bundles/prototype/t035_same_data.py decide \
      out/t035_master.db out/t035_master.json
      runs the decisions of whichever code base executes it, at AS_OF, and writes the contract dict.
  uv run python specs/010-wishlist-bundles/prototype/t035_same_data.py compare out/t035_branch.json out/t035_master.json
"""
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).parent / "out"
AS_OF = datetime(2026, 9, 27, 4, 15, tzinfo=timezone.utc)
ADDED_KEYS = {"bundles"}                      # per decision
ADDED_BATCH_KEYS = {"bundles", "bundle_rule"}


def prepare() -> None:
    OUT.mkdir(exist_ok=True)
    src = sqlite3.connect("file:data/steamsage.db?mode=ro", uri=True)
    for name in ("t035_branch.db", "t035_master.db"):
        target = OUT / name
        for suffix in ("", "-wal", "-shm"):
            Path(f"{target}{suffix}").unlink(missing_ok=True)
        dst = sqlite3.connect(target)
        src.backup(dst)
        dst.close()
        print(f"copy {target}")
    src.close()


def decide(db: str, out: str) -> None:
    from steamsage.config import load_config
    from steamsage.decision.contract import batch_to_dict
    from steamsage.decision.engine import run_decisions
    from steamsage.forecast.models import current_model
    from steamsage.store.query import PriceStore

    config = load_config(Path("steamsage.toml"))[0]
    store = PriceStore.open(Path(db), Path("data/steam_sales.toml"))
    batch = run_decisions(store, store.wishlist_apps(), AS_OF, current_model(), config.preferences, now=AS_OF,
                          choices=config.purchase_options)
    Path(out).write_text(json.dumps(batch_to_dict(batch), ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(f"{out}: {len(batch.decisions)} decisions")


def compare(branch: str, master: str) -> None:
    bb = json.loads(Path(branch).read_text(encoding="utf-8"))
    mb = json.loads(Path(master).read_text(encoding="utf-8"))
    batch_extra = set(bb) - set(mb)
    b = {d["app_id"]: d for d in bb["decisions"]}
    m = {d["app_id"]: d for d in mb["decisions"]}
    assert set(b) == set(m), set(b) ^ set(m)
    extra, differ = set(), []
    for app in sorted(b):
        extra |= set(b[app]) - set(m[app])
        same = {k: v for k, v in b[app].items() if k not in ADDED_KEYS} == m[app]
        if not same:
            differ.append((app, b[app]["name"], sorted(k for k in m[app] if b[app].get(k) != m[app][k])))
    other = sorted(k for k in set(bb) & set(mb) if k not in ("decisions", "generated_at") and bb[k] != mb[k])
    print(f"{len(b)} decisions; decision keys only on the branch: {sorted(extra)}; differing decisions: {len(differ)}")
    print(f"batch keys only on the branch: {sorted(batch_extra)}; other differing batch keys: {other}")
    print(f"branch bundles: {[(x['id'], x['grade'], (x['advice'] or {}).get('kind')) for x in bb['bundles'] or []]}")
    for row in differ:
        print("  ", row)
    assert extra <= ADDED_KEYS and batch_extra <= ADDED_BATCH_KEYS and not differ and not other


if __name__ == "__main__":
    {"prepare": prepare, "decide": decide, "compare": compare}[sys.argv[1]](*sys.argv[2:])
