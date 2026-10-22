"""P4 (spec US3): the pre-sale record's bundle advice vs the bundle's own daily price rows during the sale.

Usage: uv run python specs/013-post-sale-comparison/prototype/p4_bundles.py   (after p1_actual.py)
"""

import json
from pathlib import Path

from steamsage.store.query import from_db

from common import autumn_2026, load_record, open_store, pre_sale_record

OUT = Path(__file__).parent / "out"


def main() -> None:
    store = open_store()
    sale = autumn_2026(store)
    _, path = pre_sale_record(sale)
    rec = load_record(path)
    actual = {r["app"]: r for r in json.loads((OUT / "p1_actual.json").read_text(encoding="utf-8"))}
    for b in rec["bundles"]:
        a = b.get("advice") or {}
        print(f"{b['name']} (bundle/{b['id']}, {b['grade']}): advice {a.get('kind')} est NT${a.get('estimate_twd')} "
              f"joint {a.get('joint_probability')}; bundle discount {b['discount_pct']}%; price at as_of NT${b['price_twd']}; "
              f"separate plan NT${(b.get('plan') or {}).get('twd')}")
        rows = store.conn.execute(
            "SELECT checked_at, app_id, final_cents, original_cents, bundle_discount_pct FROM purchase_options "
            "WHERE kind = 'bundle' AND option_id = ? AND checked_at >= ? AND checked_at < ? ORDER BY checked_at",
            (b["id"], "2026-09-30", "2026-10-10")).fetchall()
        days = {}
        for checked, app, final, original, disc in rows:
            t = from_db(checked)
            days.setdefault(t.strftime("%m-%d %H:%M"), set()).add((final, disc, t >= sale.start and t < sale.end))
        for k, v in days.items():
            print(f"    {k}: {sorted(v)}")
        for lvl in a.get("levels") or []:
            r = actual.get(lvl["app_id"], {})
            print(f"    content {lvl['app_id']}: needed -{lvl['pct']}% (p={lvl['probability']:.3f}); sale max {r.get('sale_max_cut')}%")


if __name__ == "__main__":
    main()
