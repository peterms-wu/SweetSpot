"""contracts/extension-data.md: required keys and types of `steamsage.extension/1` (feature 011; tasks T009)."""

import re
from pathlib import Path

from sweetspot.decision.contract import na_decision
from sweetspot.report.extension import build
from tests.decision_builders import decision
from tests.unit.report import test_bundles_html as tb

UTC = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
HEADER = {"format", "generated_at", "as_of", "data_time", "stale_hours", "lowest_label", "refresh_note", "record",
          "versions", "summary", "games", "bundles", "calendar_notices",           # calendar_notices: feature 012
          "config_path"}                                                         # config_path: 2026-10-14
GAME = {"app_id", "name", "group", "status_reason", "price_twd", "cut_pct", "stale", "sweet_twd", "sweet_pct", "point",
        "probability", "p_min_twd", "p_min_pct", "tags", "option", "version_text", "editions", "bundle_hints",
        "ns_reasons", "reasons", "versions"}                                   # versions: feature 015
VERSION = {"kind", "id", "name", "price_twd", "cut_pct", "is_default", "tracked", "action", "reason", "manual"}
BUNDLE = {"id", "name", "grade_text", "discount_text", "price_twd", "lines", "advice_text", "advice_low", "check_text",
          "contents", "owned_note"}


def payload():
    data = tb.sample()
    extra = [decision(20, "wait", name="Wait"), decision(21, "low", name="Low", confidence="low"),
             na_decision(22, "Future", "unreleased", "尚未發行")]
    from tests.decision_builders import contract_dict
    more = contract_dict(extra, rule="2.1.0")["decisions"]
    for d in more:
        d["bundles"] = []
    data["decisions"] += more
    return build(data, record={"saved": True, "file": "20260927T050639Z.json.gz"})


def test_the_fields_the_extension_insists_on_are_written_for_every_game():
    """extension/lib.js GAME_FIELDS: a data file without them makes the panel say "資料檔是舊版" (2026-10-14).
    Listing a field the report does not write would show that warning forever."""
    lib = (Path(__file__).resolve().parents[2] / "extension" / "lib.js").read_text(encoding="utf-8")
    match = re.search(r"const GAME_FIELDS = \[([^\]]*)\];", lib)
    assert match, "GAME_FIELDS not found in extension/lib.js"
    fields = re.findall(r"'([a-z_]+)'", match.group(1))
    assert fields and set(fields) <= GAME
    assert all(set(fields) <= set(g) for g in payload()["games"])


def test_header_keys_and_types():
    p = payload()
    assert set(p) == HEADER
    for key in ("generated_at", "as_of", "data_time"):
        assert UTC.match(p[key]), key
    assert isinstance(p["stale_hours"], int) and set(p["summary"]) == {"now", "soon", "wait", "low", "na"}
    assert sum(p["summary"].values()) == len(p["games"])
    assert {g["group"] for g in p["games"]} == {"now", "soon", "wait", "low", "na"}


def test_every_game_has_the_keys_of_its_group():
    p = payload()
    ids = [g["app_id"] for g in p["games"]]
    assert len(ids) == len(set(ids))
    bundle_ids = {b["id"] for b in p["bundles"]}
    for g in p["games"]:
        assert set(g) == GAME, g["app_id"]
        assert isinstance(g["reasons"], list) and isinstance(g["tags"], list) and isinstance(g["editions"], int)
        assert all(h["id"] in bundle_ids and isinstance(h["text"], str) for h in g["bundle_hints"])
        assert isinstance(g["versions"], list)
        for v in g["versions"]:
            assert set(v) == VERSION and v["kind"] in ("sub", "bundle") and isinstance(v["id"], int)
            assert v["action"] in (None, "choose", "reset") and isinstance(v["tracked"], bool)
        assert sum(v["tracked"] for v in g["versions"]) == (1 if g["versions"] else 0)
        if g["group"] == "na":
            assert g["status_reason"] and g["sweet_twd"] is None and g["point"] is None
            continue
        assert isinstance(g["sweet_twd"], int) and isinstance(g["sweet_pct"], int) and isinstance(g["p_min_twd"], int)
        assert 0 <= g["probability"] <= 1
        assert g["price_twd"] is None or isinstance(g["price_twd"], int)
        assert set(g["point"]) == {"label", "status", "start", "end"}
        assert UTC.match(g["point"]["start"]) and UTC.match(g["point"]["end"])


def test_every_bundle_has_its_keys():
    p = payload()
    assert p["bundles"]
    for b in p["bundles"]:
        assert set(b) == BUNDLE
        assert all(isinstance(line, str) and line for line in b["lines"])
        assert isinstance(b["advice_low"], bool) and all(isinstance(c, str) for c in b["contents"])
