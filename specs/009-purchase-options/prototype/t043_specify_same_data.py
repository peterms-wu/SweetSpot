"""T045 (SC-002, FR-011): on the real database (read-only), choosing an edition changes only its game.

Runs the decisions at one as_of three times: no choice; Cyberpunk 2077 -> 《電馭叛客 2077：終極版》 (bundle/32470);
Granblue Fantasy: Relink -> 無盡黃昏（一般版） (sub/1587333). Compares every other game, prints the chosen games,
and renders the Cyberpunk report to out/t043_report.html. Writes no record and never touches steamsage.toml.
"""
import json
from pathlib import Path

from steamsage.config import load_config
from steamsage.decision.contract import batch_to_dict
from steamsage.decision.engine import run_decisions
from steamsage.forecast.models import current_model
from steamsage.report.html import render
from steamsage.store.query import PriceStore
from steamsage.timeutil import now_utc

OUT = Path(__file__).parent / "out"
CYBERPUNK, GRANBLUE = 1091500, 881020
prefs = load_config(Path("steamsage.toml"))[0].preferences
store = PriceStore.open(Path("data/steamsage.db"))
as_of = now_utc()


def decide(choices):
    batch = run_decisions(store, store.wishlist_apps(), as_of, current_model(), prefs, now=as_of, choices=choices)
    data = batch_to_dict(batch)
    return data, {d["app_id"]: d for d in data["decisions"]}


def brief(d):
    cur = d["current"] or {}
    return {"group": d["group"], "confidence": d["confidence"], "regular": d["regular_twd"],
            "price": cur.get("price_twd"), "source": cur.get("source"), "sweet": d["sweet_twd"], "pct": d["sweet_pct"],
            "point": (d["sweet_point"] or {}).get("label"), "prob": d["sweet_probability"],
            "version": {k: (d["version"] or {}).get(k) for k in ("basis", "source", "itad_id", "aux_pending")}}


_, base = decide({})
report = {}
for app, choice in ((CYBERPUNK, ("bundle", 32470)), (GRANBLUE, ("sub", 1587333))):
    data, got = decide({app: choice})
    others = [a for a in base if a != app and json.dumps(base[a], sort_keys=True) != json.dumps(got[a], sort_keys=True)]
    report[app] = {"name": base[app]["name"], "others_changed": others, "default": brief(base[app]),
                   "chosen": brief(got[app]), "reasons": got[app]["reasons"],
                   "editions": [(e["name"], e["unset_hint"]) for e in got[app]["editions"] or []]}
    print(f"{base[app]['name']}: other games changed {len(others)} of {len(base) - 1}")
    print("  default:", brief(base[app]))
    print("  chosen: ", brief(got[app]))
    for r in got[app]["reasons"]:
        print("   -", r)
    if app == CYBERPUNK:
        (OUT / "t043_report.html").write_text(render(data), encoding="utf-8")
(OUT / "t043.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
store.close()
