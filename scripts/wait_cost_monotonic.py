"""Feature 005 quickstart C (spec SC-002): on the current wishlist, a higher waiting cost never makes the rule 3.0.0
recommendation wait longer, and c = 0 picks the option with the highest expected saving. Read-only.

Usage: uv run python scripts/wait_cost_monotonic.py
"""

import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sweetspot.cli import _utf8_when_redirected  # noqa: E402
from sweetspot.config import load_config  # noqa: E402
from sweetspot.decision.engine import run_decisions  # noqa: E402
from sweetspot.forecast.models import current_model  # noqa: E402
from sweetspot.store.query import PriceStore  # noqa: E402
from sweetspot.timeutil import now_utc  # noqa: E402

COSTS = (0, 10, 20, 30, 50, 80, 120)


def main() -> int:
    _utf8_when_redirected()
    config, _ = load_config(ROOT / "sweetspot.toml")
    store = PriceStore.open(config.db_path, config.data_dir / "steam_sales.toml")
    now = now_utc()
    try:
        apps = store.wishlist_apps()
        batches = {c: run_decisions(store, apps, now, current_model(), replace(config.preferences, wait_cost_twd=c),
                                    now=now, rule="3.0.0") for c in COSTS}
    finally:
        store.close()
    names = {d.app_id: d.name for d in batches[0].decisions}
    games = [d.app_id for d in batches[0].decisions if d.expected is not None]
    longer, not_max = [], []
    for app in games:
        waits = [next(d for d in batches[c].decisions if d.app_id == app).expected.expected_wait_months for c in COSTS]
        if any(b > a + 1e-12 for a, b in zip(waits, waits[1:])):
            longer.append((names[app], waits))
        zero = next(d for d in batches[0].decisions if d.app_id == app)
        best = max(o.expected_saving_cents for o in zero.wait_options if o.expected_saving_cents is not None)
        if zero.expected.expected_saving_cents != best:
            not_max.append(names[app])
    print(f"願望清單 {len(games)} 款，c = {', '.join(map(str, COSTS))}")
    print(f"c 提高時期望等待變長：{len(longer)} 款")
    for name, waits in longer:
        print(f"  {name}：{['%.2f' % w for w in waits]}")
    print(f"c = 0 時不是期望多省最高：{len(not_max)} 款 {not_max}")
    return 1 if longer or not_max else 0


if __name__ == "__main__":
    raise SystemExit(main())
