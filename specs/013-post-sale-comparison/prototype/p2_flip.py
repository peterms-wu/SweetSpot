"""P2 (spec FR-010a): games the pre-sale record told to wait that reached their sweet price in the sale — did a
daily record during the sale switch them to 現在買, and on which day? Also which soon game missed. Reads p1's out/.

Usage: uv run python specs/013-post-sale-comparison/prototype/p2_flip.py   (after p1_actual.py)
"""

import json
from pathlib import Path

from common import autumn_2026, load_record, open_store, records

OUT = Path(__file__).parent / "out"


def main() -> None:
    rows = json.loads((OUT / "p1_actual.json").read_text(encoding="utf-8"))
    sale = autumn_2026(open_store())
    during = [(t, p) for t, p in records() if sale.start <= t < sale.end]
    print("records during the sale:", [p.name for _, p in during])
    daily = []
    for t, p in during:
        rec = load_record(p)
        daily.append((t, rec["official"], {d["app_id"]: d for d in rec["decisions"]}))
    for t, official, decs in daily:
        groups = {}
        for d in decs.values():
            groups[d["group"]] = groups.get(d["group"], 0) + 1
        print(f"  {t:%m-%d %H:%M}Z official={official} {groups}")

    early = [r for r in rows if r.get("group") in ("wait", "low") and r.get("hit_sweet")]
    print(f"early hits (wait/low that reached the sweet price): {len(early)}")
    for r in early:
        seen = []
        for t, official, decs in daily:
            d = decs.get(r["app"])
            seen.append(f"{t:%m-%d}:{d['group'] if d else '-'}")
        first = next((s for s in seen if s.endswith(":now")), None)
        print(f"   {r['name']}: sweet NT${r['sweet_cents'] / 100:.0f}, sale low NT${r['sale_min_cents'] / 100:.0f}; "
              f"first now: {first or 'never'}  [{' '.join(seen)}]")
    for r in rows:
        if r.get("group") == "soon" and r.get("hit_sweet") is False:
            print(f"soon miss: {r['name']}: sweet NT${r['sweet_cents'] / 100:.0f} ({r['sweet_pct']}%), "
                  f"sale low NT${r['sale_min_cents'] / 100:.0f}, max cut {r['sale_max_cut']}%")
    # did sweet prices themselves move during the sale? (same game, sweet_cents in the during-sale records)
    moved = 0
    for r in rows:
        if "sweet_cents" not in r:
            continue
        vals = {decs[r["app"]]["sweet_cents"] for _, _, decs in daily if r["app"] in decs}
        moved += len(vals - {r["sweet_cents"], None}) > 0
    print("games whose sweet price changed in a during-sale record:", moved)


if __name__ == "__main__":
    main()
