"""Changes of each game against the comparison baseline (research R7; FR-019 to FR-021).

Works on contract dicts (the baseline is read back from a record). Sweet prices are compared in whole NT$, the
value the user sees, so a one-cent difference is not a change.
"""

from typing import Any

from sweetspot.calendar import pacific_days
from sweetspot.timeutil import parse_iso

NOW_LABEL = "現在"


def _timing(d: dict) -> str | None:
    if d["group"] == "na":
        return None
    return NOW_LABEL if d["group"] == "now" else d["sweet_point"]["label"]


def _diff(old: Any, new: Any) -> dict | None:
    if old is None or new is None or old == new:
        return None
    return {"from": old, "to": new}


def _params(params: dict) -> str:
    return "{" + ", ".join(f"{k}={v}" for k, v in sorted(params.items())) + "}"


def _non_seasonal(new: dict, old: dict) -> list[str]:
    """Feature 007: the non-seasonal model starts showing probabilities, or changes. A record without the block
    (before 007) counts as not adopted."""
    nb, ob = new.get("non_seasonal") or {}, old.get("non_seasonal") or {}
    nm, om = (nb.get("model") if nb.get("adopted") else None), (ob.get("model") if ob.get("adopted") else None)
    if nm == om or nm is None:
        return []
    label = f"{nm['name']} {nm['version']} {_params(nm['params'])}"
    if om is None:
        return [f"非季節預測模型開始顯示機率（{label}）"]
    return [f"非季節預測模型 {om['name']} {om['version']} {_params(om['params'])} → {label}"]


def _versions(new: dict, old: dict) -> list[str]:
    out = _non_seasonal(new, old)
    nm, om = new["forecast"]["model"], old["forecast"]["model"]
    if (nm["name"], nm["version"], nm["params"]) != (om["name"], om["version"], om["params"]):
        out.append(f"模型 {om['name']} {om['version']} {_params(om['params'])} → "
                   f"{nm['name']} {nm['version']} {_params(nm['params'])}")
    if new["rule"]["version"] != old["rule"]["version"] or new["rule"]["name"] != old["rule"]["name"]:
        out.append(f"規則 {old['rule']['name']} {old['rule']['version']} → {new['rule']['version']}")
    for key, value in new["preferences"].items():             # only keys both rules use (005 research R5)
        if key in old["preferences"] and old["preferences"][key] != value:
            if key == "wait_cost_twd":
                out.append(f"等待成本從 NT${old['preferences'][key]} 改成 NT${value}")
            else:
                out.append(f"偏好 {key} {old['preferences'][key]} → {value}")
    return out


def _sale_points(contract: dict) -> dict[str, dict]:
    """label -> the sweet point of that sale (every game on the same sale shares it). Records before feature 003's
    point dates have only the label and are skipped."""
    out: dict[str, dict] = {}
    for d in contract["decisions"]:
        p = d.get("sweet_point") or {}
        if p.get("label") and p.get("status") and p.get("start") and p.get("end"):
            out.setdefault(p["label"], p)
    return out


def _calendar_changes(new: dict, old: dict) -> list[str]:
    """Feature 012 (research R6): seasonal sales, as sweet points in both records, whose dates became official or
    whose official dates moved. The per-game comparison cannot show this: the label stays the same."""
    before, after = _sale_points(old), _sale_points(new)
    lines = []
    for label, p in sorted(after.items(), key=lambda kv: kv[1]["start"]):
        q = before.get(label)
        if q is None:
            continue
        new_days = pacific_days(parse_iso(p["start"]), parse_iso(p["end"]))
        if q["status"] == "estimated" and p["status"] == "announced":
            lines.append(f"{label} 預估 → 官方（太平洋時間 {new_days}）")
        elif q["status"] == p["status"] == "announced" and (q["start"], q["end"]) != (p["start"], p["end"]):
            old_days = pacific_days(parse_iso(q["start"]), parse_iso(q["end"]))
            lines.append(f"{label} 官方日期 {old_days} → {new_days}（太平洋時間）")
    return lines


def _tracked(v: dict | None) -> tuple | None:
    """The tracked purchase option (feature 009); a record before 009 names only its default package."""
    if not v:
        return None
    option = v.get("option")
    if option:
        return option["kind"], option["id"]
    return ("sub", v["package_id"]) if v.get("package_id") else None


def _title(v: dict | None, fallback: str | None) -> str | None:
    if not v:
        return fallback
    option = v.get("option") or {}
    return option.get("name") or v.get("package_name") or fallback


def _version(old: dict, new: dict) -> dict | None:
    """Feature 009 (contracts/outputs-options.md): the user chose, unset or lost a chosen option since the
    baseline, else feature 006's check (spec FR-013) with cause `steam`."""
    nv, ov = new.get("version"), old.get("version")
    new_source = (nv or {}).get("source") or "steam-default"
    old_source = (ov or {}).get("source") or "steam-default"
    name = old.get("name") or new.get("name")
    cause = None
    if new_source == "user" and (old_source != "user" or _tracked(ov) != _tracked(nv)):
        cause = "user"
    elif old_source == "user" and new_source == "steam-default":
        cause = "unset"
    elif old_source == "user" and new_source == "user-fallback":
        cause = "fallback"
    if cause is not None:
        return {"from": _title(ov, name), "to": _title(nv, new.get("name")), "detected_at": None, "cause": cause}
    steam = _steam_version(old, new)
    return None if steam is None else {**steam, "cause": "steam"}


def _steam_version(old: dict, new: dict) -> dict | None:
    """Feature 006 (spec FR-013): the ITAD product changed since the baseline. A baseline written before 006 has no
    version: it used the app's own product."""
    nv = new.get("version")
    if not nv or nv.get("basis") not in ("version", "rejected"):
        return None
    ov = old.get("version")
    old_id = ov.get("itad_id") if ov else nv.get("own_itad_id")
    if old_id == nv.get("itad_id"):
        return None
    moved = ov and ov.get("itad_id") != ov.get("own_itad_id")
    old_title = ov.get("package_name") if moved else (old.get("name") or new.get("name"))
    detected = (nv.get("change") or {}).get("detected_at")
    return {"from": old_title, "to": nv.get("package_name"), "detected_at": detected}


def compare(new: dict, baseline: dict | None, *, file: str | None = None, as_of: str | None = None,
            skipped: list[str] | None = None) -> tuple[dict[int, dict | None], dict]:
    """({app_id: change or None}, comparison) for the new contract against the baseline contract."""
    skipped = list(skipped or [])
    if baseline is None:
        return ({d["app_id"]: None for d in new["decisions"]},
                {"baseline": None, "version_changes": [], "skipped_records": skipped, "changed_games": 0,
                 "calendar_changes": []})
    before = {d["app_id"]: d for d in baseline["decisions"]}
    changes = {}
    for d in new["decisions"]:
        old = before.get(d["app_id"])
        change = None
        if old is not None:
            change = {"group": _diff(old["group"], d["group"]), "sweet_point": _diff(_timing(old), _timing(d)),
                      "sweet_twd": _diff(old["sweet_twd"], d["sweet_twd"])}
            version = _version(old, d)
            if version:
                change["version"] = version
            if not any(change.values()):
                change = None
        changes[d["app_id"]] = change
    return changes, {"baseline": {"file": file, "as_of": as_of}, "version_changes": _versions(new, baseline),
                     "skipped_records": skipped, "changed_games": sum(c is not None for c in changes.values()),
                     "calendar_changes": _calendar_changes(new, baseline)}
