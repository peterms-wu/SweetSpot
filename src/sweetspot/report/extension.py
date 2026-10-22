"""The Chrome extension's data file `steamsage.extension/1` (feature 011; contracts/extension-data.md; research R1).

Presentation only, like the HTML report: it reads the same decision contract dict and never imports the analysis
core (constitution VII). Every sentence comes from the report's own text builders, so the extension and the report
say the same thing; numbers are copied, never recomputed. Unknowns stay null (constitution I).
"""

import json
from pathlib import Path, PurePath
from statistics import median_low
from typing import Any

from sweetspot.report import html

FORMAT = "steamsage.extension/1"
STALE_HOURS = 26          # spec FR-007: the daily schedule (24 h) plus a 2-hour margin; a presentation default
NUMBERS = ("price_twd", "cut_pct", "sweet_twd", "sweet_pct", "point", "probability", "p_min_twd", "p_min_pct")


def _data_time(decisions: list[dict]) -> str | None:
    """Median (low) of the current prices' last confirmation times (research R0.3; spec FR-007)."""
    stamps = [(d.get("current") or {}).get("confirmed_at") for d in decisions]
    stamps = [s for s in stamps if s]
    return median_low(stamps) if stamps else None          # same-format UTC strings sort like the times


def _option(d: dict) -> dict | None:
    v = d.get("version") or {}
    opt = v.get("option")
    if not opt:
        return None
    return {"kind": opt.get("kind"), "id": opt.get("id"), "name": opt.get("name"), "user": v.get("basis") == "user"}


def _version_entry(kind, id_, name, price_twd, cut_pct, *, is_default, tracked, action=None, reason=None,
                   manual=None) -> dict[str, Any]:
    return {"kind": kind, "id": id_, "name": name, "price_twd": price_twd, "cut_pct": cut_pct, "is_default": is_default,
            "tracked": tracked, "action": action, "reason": reason, "manual": manual}


def _versions(d: dict) -> list[dict[str, Any]]:
    """Feature 015 (data-model §1): the tracked purchase option first, then the report's other editions, each with
    what its button does. Copied from the decision contract; nothing is recomputed (constitution VII)."""
    v = d.get("version") or {}
    opt = v.get("option")
    if not opt:
        return []
    editions = d.get("editions") or []
    cur = d.get("current") or {}
    out = [_version_entry(opt.get("kind"), opt.get("id"), opt.get("name"), cur.get("price_twd"), cur.get("cut_pct"),
                          is_default=v.get("basis") != "user" or not any(e.get("is_default") for e in editions),
                          tracked=True)]
    for e in editions:
        if e.get("unset_hint"):
            action, manual = "reset", f"刪掉設定檔 [purchase_options] 中 {d['app_id']} 那一行"
        elif e.get("config_line"):
            action, manual = "choose", e["config_line"]
        else:
            action, manual = None, None
        out.append(_version_entry(e.get("kind"), e.get("id"), e.get("name"), e.get("price_twd"), e.get("cut_pct"),
                                  is_default=bool(e.get("is_default")), tracked=False, action=action, manual=manual,
                                  reason=None if action else html.edition_refusal_text(e)))
    return out


def _game(d: dict, by_id: dict) -> dict[str, Any]:
    out: dict[str, Any] = {
        "app_id": d["app_id"], "name": d["name"], "group": d["group"], "status_reason": d.get("status_reason"),
        **dict.fromkeys(NUMBERS), "stale": (d.get("current") or {}).get("stale"),
        "tags": html.tag_labels(d.get("tags") or []), "option": _option(d), "version_text": html.version_text(d),
        "editions": len(d.get("editions") or []), "bundle_hints": html.bundle_hint_texts(d, by_id),
        "ns_reasons": list((d.get("non_seasonal") or {}).get("reasons") or []), "reasons": list(d.get("reasons") or []),
        "versions": _versions(d),
    }
    cur = d.get("current") or {}
    out["price_twd"], out["cut_pct"] = cur.get("price_twd"), cur.get("cut_pct")
    if d["group"] != "na":
        point = d["sweet_point"]
        out.update(sweet_twd=d["sweet_twd"], sweet_pct=d["sweet_pct"], probability=d["sweet_probability"],
                   point={k: point[k] for k in ("label", "status", "start", "end")},
                   p_min_twd=d["p_min_twd"], p_min_pct=d["p_min_pct"])
    return out


def _bundle(b: dict) -> dict[str, Any]:
    texts = html.bundle_card_texts(b)
    return {"id": b["id"], "name": b["name"], "grade_text": texts["grade_text"], "discount_text": texts["discount_text"],
            "price_twd": b.get("price_twd"), "lines": [line for line in texts["lines"] if line],
            "advice_text": texts["advice_text"], "advice_low": texts["advice_low"], "check_text": texts["check_text"],
            "contents": [c["name"] or f"App {c['app_id']}" for c in b["contents"]], "owned_note": b.get("owned_note")}


def build(data: dict, record: dict | None = None, config_path: Path | None = None) -> dict[str, Any]:
    """The extension payload for one report. `record` is the report's record status ({"saved", "file"});
    `config_path` the settings file it ran with, shown in the version section's steps by hand (2026-10-14)."""
    bundles = data.get("bundles") or []
    by_id = {b["id"]: b for b in bundles}
    games = [d for group, _ in html.GROUPS
             for d in html.sorted_games(group, [x for x in data["decisions"] if x["group"] == group])]
    model, rule = data["forecast"]["model"], data["rule"]
    return {
        "format": FORMAT, "generated_at": data["generated_at"], "as_of": data["as_of"],
        "data_time": _data_time(data["decisions"]), "stale_hours": STALE_HOURS, "lowest_label": html.lowest_label(data),
        "refresh_note": (data.get("data_refresh") or {}).get("note"),
        "calendar_notices": list(data.get("calendar_notices") or []),     # feature 012 (plan D1)
        **({"reference_notice": html.reference_notice_text(data["reference_notice"])}      # feature 014: same words
           if data.get("reference_notice") else {}),
        "record": PurePath(record["file"].replace("\\", "/")).name if record and record.get("saved") else None,
        "versions": {"model": f"{model['name']} {model['version']}", "rule": f"{rule['name']} {rule['version']}"},
        "config_path": str(Path(config_path).resolve()) if config_path is not None else None,
        "summary": {group: sum(1 for d in games if d["group"] == group) for group, _ in html.GROUPS},
        "games": [_game(d, by_id) for d in games],
        "bundles": [_bundle(b) for b in bundles],
    }


def dumps(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
