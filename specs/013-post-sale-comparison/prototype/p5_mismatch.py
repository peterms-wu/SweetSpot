"""P5: why the ITAD series and the daily Steam snapshots disagree for a game (default: 劍星 / Stellar Blade).

Usage: uv run python specs/013-post-sale-comparison/prototype/p5_mismatch.py [name-substring]
"""

import json
import sys
from datetime import timedelta

from common import NOW, autumn_2026, load_record, open_store, pre_sale_record, tracked_key


def main() -> None:
    needle = sys.argv[1] if len(sys.argv) > 1 else "劍星"
    store = open_store()
    sale = autumn_2026(store)
    _, path = pre_sale_record(sale)
    rec = load_record(path)
    d = next(x for x in rec["decisions"] if needle in x["name"])
    app = d["app_id"]
    print(d["name"], app, "group", d["group"], "current", json.dumps(d["current"], ensure_ascii=False))
    print("version:", json.dumps(d["version"], ensure_ascii=False))
    ext, sources = tracked_key(d)
    for o in store.observations(app, NOW):
        if sale.start - timedelta(days=3) <= o.observed_at < sale.end + timedelta(days=2):
            print(f"   {o.observed_at:%m-%d %H:%M} {o.source:22s} ext={o.external_id} cut={o.cut_pct} price={o.price_cents} regular={o.regular_cents}")
    rows = store.conn.execute(
        "SELECT checked_at, kind, option_id, name, final_cents, original_cents, is_default, external_id FROM purchase_options "
        "WHERE app_id = ? AND checked_at >= '2026-10-01' AND checked_at < '2026-10-03' ORDER BY checked_at, position",
        (app,)).fetchall()
    for r in rows:
        print("   option", r)


if __name__ == "__main__":
    main()
