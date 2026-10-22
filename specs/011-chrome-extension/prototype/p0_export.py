"""P0 (plan research R0.3): build the compact extension data file from the latest official record; size and time.

uv run python specs/011-chrome-extension/prototype/p0_export.py

Writes ext/data/steamsage-extension.json (ignored by git). The real exporter lives in the report package and reuses
the report's text helpers; this prototype only checks the shape, the size and the "data time" (median fetch time).
"""
import gzip
import json
import os
import statistics
import time
from datetime import datetime
from pathlib import Path

from steamsage.report import html

ROOT = Path(__file__).resolve().parents[3]
DATA = Path(__file__).resolve().parent / "ext" / "data" / "steamsage-extension.json"


def stamp(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")


def game(d, bundles):
    cur = d.get("current") or {}
    v = d.get("version") or {}
    opt = v.get("option") or {}
    out = {"app_id": d["app_id"], "name": d["name"], "group": d["group"], "status_reason": d.get("status_reason"),
           "tags": [html.TAGS[t] for t in d.get("tags") or [] if t in html.TAGS],
           "option": {"kind": opt.get("kind"), "id": opt.get("id"), "name": opt.get("name"),
                      "user": v.get("basis") == "user"} if opt else None,
           "editions": len(d.get("editions") or []), "bundles": d.get("bundles") or [],
           "reasons": d.get("reasons") or [], "ns": (d.get("non_seasonal") or {}).get("reasons") or []}
    if d["group"] != "na":
        point = d["sweet_point"]
        out.update(price_twd=cur.get("price_twd"), cut_pct=cur.get("cut_pct"), stale=cur.get("stale"),
                   sweet_twd=d["sweet_twd"], sweet_pct=d["sweet_pct"], probability=d["sweet_probability"],
                   point={"label": point["label"], "status": point["status"], "start": point["start"], "end": point["end"]},
                   p_min_twd=d["p_min_twd"], p_min_pct=d["p_min_pct"])
    return out


def main():
    t0 = time.perf_counter()
    path = max((ROOT / "data" / "forecasts").glob("*.json.gz"))
    rec = json.load(gzip.open(path))
    t_read = time.perf_counter()
    fetched = sorted(stamp(d["current"]["confirmed_at"]) for d in rec["decisions"]
                     if (d.get("current") or {}).get("confirmed_at"))
    median = fetched[len(fetched) // 2] if fetched else None
    payload = {
        "format": "steamsage.extension/1", "generated_at": rec["generated_at"], "as_of": rec["as_of"],
        "data_time": median.strftime("%Y-%m-%dT%H:%M:%SZ") if median else None,
        "refresh_note": (rec.get("data_refresh") or {}).get("note"), "record": path.name,
        "summary": rec["summary"],
        "games": [game(d, rec.get("bundles") or []) for d in rec["decisions"]],
        "bundles": [{"id": b["id"], "name": b["name"], "grade": b["grade"], "discount_pct": b.get("discount_pct"),
                     "price_twd": b.get("price_twd"),
                     "text": (b.get("advice") or {}).get("text") or (b.get("advice") or {}).get("reason_text"),
                     "extra_twd": b.get("extra_twd"), "contents": [c["name"] for c in b["contents"]]}
                    for b in rec.get("bundles") or []],
    }
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    DATA.parent.mkdir(exist_ok=True)
    tmp = DATA.with_name(DATA.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, DATA)
    t_end = time.perf_counter()
    spread = (fetched[-1] - fetched[0]).total_seconds() / 3600 if fetched else None
    print(f"record {path.name}: {len(rec['decisions'])} games, {len(payload['bundles'])} bundles")
    print(f"file {DATA.stat().st_size / 1024:.0f} KB; build+write {1000 * (t_end - t_read):.0f} ms "
          f"(record read {1000 * (t_read - t0):.0f} ms, not needed in report: the dict is in memory)")
    print(f"as_of {rec['as_of']}; data_time (median confirmed_at) {payload['data_time']}; "
          f"fetch times {len(fetched)}, spread {spread:.2f} h; median of observed_at: {statistics.median_low([f.timestamp() for f in fetched]) if fetched else None}")


if __name__ == "__main__":
    main()
