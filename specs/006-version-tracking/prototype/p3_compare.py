"""P3 compare: Dying Light's forecast and decision in each variant's newest official record (research R4)."""
import gzip
import json
import sys
from pathlib import Path

APP = 239140
scratch = Path(sys.argv[1])


def pick(variant):
    f = sorted((scratch / variant / "forecasts").glob("*.json.gz"))[-1]
    rec = json.load(gzip.open(f, "rt", encoding="utf-8"))
    fc = next(g for g in rec["forecast"]["games"] if g["app_id"] == APP)
    dc = next(d for d in rec["decisions"] if d["app_id"] == APP)
    groups = {}
    for d in rec["decisions"]:
        groups[d["group"]] = groups.get(d["group"], 0) + 1
    return fc, dc, groups


for v in ("base", "version", "stopped"):
    fc, dc, groups = pick(v)
    print(f"== {v}: groups {groups}")
    print("  forecast:", fc["status"], fc.get("confidence"), "regular", fc.get("regular_price_cents"))
    for r in fc.get("reasons", []):
        print("    -", r)
    cur = dc.get("current") or {}
    print("  decision:", dc["group"], dc.get("confidence"), "basis", dc.get("basis"),
          "| now", cur.get("price_twd"), "regular", cur.get("regular_cents"), "hist", cur.get("history_regular_twd"),
          "mismatch", cur.get("regular_mismatch"))
    print("  sweet:", {k: dc.get(k) for k in ("sweet_twd", "sweet_cut_pct", "sweet_point", "p_min") if k in dc},
          "change", dc.get("change"))
    print("  ladder:", [(l.get("label"), l.get("cut_pct"), l.get("cents")) for l in dc.get("ladder", [])])
    for r in dc.get("reasons", []):
        print("    *", r if isinstance(r, str) else r.get("text", r))
