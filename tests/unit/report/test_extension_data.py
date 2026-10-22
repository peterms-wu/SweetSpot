"""feature 011: the extension data file `steamsage.extension/1` (contracts/extension-data.md; tasks T007)."""

import json
import subprocess
import sys

from sweetspot.decision.contract import na_decision
from sweetspot.report import html
from sweetspot.report.extension import FORMAT, STALE_HOURS, build, dumps
from tests.decision_builders import contract_dict, decision
from tests.unit.report import test_bundles_html as tb
from tests.unit.report import test_html as th


def sample():
    games = [decision(1, "now", name="Cheap Now", current=20000, sweet_pct=50, tags=("below-history", "nope")),
             decision(2, "soon", name="Soon B", sweet_pct=40, p_min_pct=50),
             decision(9, "soon", name="Soon A", sweet_pct=40, p_min_pct=50, regular=40000, current=40000),
             decision(3, "wait", name="Wait Game", sweet_pct=80, p_min_pct=85, sweet_index=5),
             decision(4, "low", name="Low Game", confidence="low", tags=("low-confidence",)),
             na_decision(5, "Future Game", "unreleased", "尚未發行（預定 2027-01-01）")]
    return contract_dict(games, rule="2.1.0")


def game(payload, app_id):
    return next(g for g in payload["games"] if g["app_id"] == app_id)


def test_header():
    data = sample()
    data["data_refresh"] = {"update_exit": 1, "note": "資料更新失敗，本報告使用上次的資料"}
    p = build(data, record={"saved": True, "file": "C:\\data\\forecasts\\20260927T050639Z.json.gz"})
    assert p["format"] == FORMAT == "steamsage.extension/1"
    assert p["generated_at"] == data["generated_at"] and p["as_of"] == data["as_of"]
    assert p["stale_hours"] == STALE_HOURS == 26
    assert p["refresh_note"] == "資料更新失敗，本報告使用上次的資料"
    assert p["record"] == "20260927T050639Z.json.gz"
    assert p["lowest_label"] == html.lowest_label(data) == "12 個月內最低"
    model, rule = data["forecast"]["model"], data["rule"]
    assert p["versions"] == {"model": f"{model['name']} {model['version']}", "rule": f"{rule['name']} {rule['version']}"}
    assert p["summary"] == {"now": 1, "soon": 2, "wait": 1, "low": 1, "na": 1}


def test_config_path_is_the_settings_file_the_report_ran_with(tmp_path):
    """2026-10-14: the version section's steps by hand name the full path (015 extension-ui contract)."""
    config = tmp_path / "SweetSpot" / "sweetspot.toml"
    assert build(sample(), config_path=config)["config_path"] == str(config.resolve())
    assert build(sample())["config_path"] is None


def test_record_is_null_when_not_saved_and_lowest_label_follows_the_rule():
    assert build(sample(), record={"saved": False, "error": "x"})["record"] is None
    assert build(sample())["record"] is None
    old = contract_dict([decision(1, "soon")], rule="1.0.0")
    assert build(old)["lowest_label"] == "長期最低"


def test_data_time_is_the_median_low_of_confirmation_times():
    data = sample()
    stamps = ["2026-09-27T07:00:00Z", "2026-09-27T05:00:00Z", "2026-09-27T06:00:00Z"]
    for d, s in zip(data["decisions"], stamps):
        d["current"]["confirmed_at"] = s
    for d in data["decisions"][3:]:
        if d.get("current"):
            d["current"]["confirmed_at"] = None
    assert build(data)["data_time"] == "2026-09-27T06:00:00Z"
    data["decisions"][2]["current"]["confirmed_at"] = None                    # 05:00 and 07:00 -> the earlier one
    data["decisions"][0]["current"]["confirmed_at"] = "2026-09-27T07:00:00Z"
    data["decisions"][1]["current"]["confirmed_at"] = "2026-09-27T05:00:00Z"
    assert build(data)["data_time"] == "2026-09-27T05:00:00Z"
    for d in data["decisions"]:
        d["current"] = None
    assert build(data)["data_time"] is None


def test_game_fields_come_from_the_decision():
    data = sample()
    d = data["decisions"][0]
    d["non_seasonal"] = {"reasons": ["非季節一句話"]}
    d["editions"] = [{"id": 1}, {"id": 2}]
    d["version"] = {**th.USER, "aux_pending": False}
    g = game(build(data), 1)
    cur, point = d["current"], d["sweet_point"]
    assert g["name"] == "Cheap Now" and g["group"] == "now" and g["status_reason"] is None
    assert (g["price_twd"], g["cut_pct"], g["stale"]) == (cur["price_twd"], cur["cut_pct"], cur["stale"])
    assert (g["sweet_twd"], g["sweet_pct"], g["probability"]) == (d["sweet_twd"], d["sweet_pct"], d["sweet_probability"])
    assert g["point"] == {k: point[k] for k in ("label", "status", "start", "end")}
    assert (g["p_min_twd"], g["p_min_pct"]) == (d["p_min_twd"], d["p_min_pct"])
    assert g["tags"] == ["低於過去最低"] == html.tag_labels(d["tags"])
    assert g["option"] == {"kind": "bundle", "id": 32470, "name": "《電馭叛客 2077：終極版》", "user": True}
    assert g["version_text"] == html.version_text(d)
    assert g["editions"] == 2 and g["ns_reasons"] == ["非季節一句話"] and g["reasons"] == d["reasons"]
    plain = game(build(sample()), 2)
    assert plain["option"] is None and plain["version_text"] is None and plain["editions"] == 0
    assert plain["ns_reasons"] == [] and plain["bundle_hints"] == []


def test_unpredictable_game_has_null_numbers():
    g = game(build(sample()), 5)
    assert g["group"] == "na" and g["status_reason"] == "尚未發行（預定 2027-01-01）"
    for key in ("price_twd", "cut_pct", "sweet_twd", "sweet_pct", "point", "probability", "p_min_twd", "p_min_pct"):
        assert g[key] is None, key


def test_games_follow_the_report_order():
    data = sample()
    p = build(data)
    expected = [d["app_id"] for group, _ in html.GROUPS
                for d in html.sorted_games(group, [x for x in data["decisions"] if x["group"] == group])]
    assert [g["app_id"] for g in p["games"]] == expected
    assert expected.index(9) < expected.index(2)                 # soon: cheaper sweet price first


def test_bundles_and_hints_use_the_report_sentences():
    data = tb.sample(specified={2592160})
    p = build(data)
    by_id = {b["id"]: b for b in data["bundles"]}
    for d in data["decisions"]:
        assert game(p, d["app_id"])["bundle_hints"] == html.bundle_hint_texts(d, by_id)
    assert [b["id"] for b in p["bundles"]] == [b["id"] for b in data["bundles"]]
    for out, b in zip(p["bundles"], data["bundles"]):
        texts = html.bundle_card_texts(b)
        assert out["name"] == b["name"] and out["price_twd"] == b["price_twd"] and out["owned_note"] == b["owned_note"]
        assert out["contents"] == [c["name"] or f"App {c['app_id']}" for c in b["contents"]]
        for key in ("grade_text", "discount_text", "advice_text", "advice_low", "check_text"):
            assert out[key] == texts[key], key
        assert out["lines"] == [line for line in texts["lines"] if line]
    assert build(sample())["bundles"] == []


def test_leaves_out_curves_ids_and_secrets(monkeypatch):
    monkeypatch.setenv("ITAD_API_KEY", "itad-secret-123")
    data = tb.sample()
    data["forecast"]["games"] = [{"app_id": 1, "curve": {"probabilities": [[0.5]]}}]
    text = dumps(build(data))
    for word in ("probabilities", "curve", "itad_id", "comparison", "itad-secret-123", "own_itad_id"):
        assert word not in text, word
    assert json.loads(text)["format"] == FORMAT and ", " not in text[:80]         # compact separators


def test_size_stays_under_500_kb_for_150_games():
    games = [decision(i, ("soon", "wait", "low")[i % 3], name=f"遊戲名稱 {i} " * 3) for i in range(1, 151)]
    data = contract_dict(games, rule="2.1.0")
    for d in data["decisions"]:
        d["reasons"] = [f"第 {k} 個原因：依本身的季節特賣紀錄，台灣區 7 場（2024 冬特–2026 夏特），過去最大折扣 -60%" for k in range(12)]
    assert len(dumps(build(data)).encode("utf-8")) <= 500_000


def test_module_does_not_import_the_core():
    code = ("import sys, sweetspot.report.extension; "
            "bad = [m for m in sys.modules if m.startswith(('sweetspot.decision', 'sweetspot.forecast', "
            "'sweetspot.store', 'sweetspot.sources', 'sweetspot.pipeline'))]; print(bad)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    assert out == "[]"


def test_calendar_notices_are_passed_through():
    """Feature 012 (plan D1; FR-021): the same sentences as the report; an older contract without the field."""
    data = sample()
    data["calendar_notices"] = ["官方特賣頁面已 8 天沒有成功讀取（最後一次 2026-09-28 20:00 台北）"]
    assert build(data)["calendar_notices"] == data["calendar_notices"]
    assert build(sample())["calendar_notices"] == []


# --- feature 015: each game's versions (data-model §1; tasks T007) --------------------------------------------------

BASE = th.edition("sub", 367653, "Cyberpunk 2077", 479, 1599, is_default=True, unset=True)
ULTIMATE = th.edition("bundle", 32470, "《電馭叛客 2077：終極版》", 882, 2206, line='7 = "bundle/32470"')
REJECTED = th.edition("sub", 5, "Bad Edition", 900, 1000, verification="rejected", reason="bundle", detail="bundle/9")
REJECTED["reason_text"] = "ITAD 的商品還對應到組合包 bundle/9，價格歷史可能混了組合包的價格"
STEAM = {**th.ESSENTIALS, "basis": "version", "source": "steam-default",
         "option": {"kind": "sub", "id": 367653, "name": "Cyberpunk 2077"}}


def versions_of(version, editions, current=48000):
    data = th.with_editions(editions)
    d = data["decisions"][0]
    d["version"] = version
    d["current"] = {**d["current"], "price_twd": current // 100, "cut_pct": 60}
    return game(build(data), 7)["versions"]


def test_a_user_choice_lists_the_choice_first_and_the_default_to_go_back_to():
    got = versions_of({**th.USER, "aux_pending": False}, [BASE], current=88200)
    assert got == [
        {"kind": "bundle", "id": 32470, "name": "《電馭叛客 2077：終極版》", "price_twd": 882, "cut_pct": 60,
         "is_default": False, "tracked": True, "action": None, "reason": None, "manual": None},
        {"kind": "sub", "id": 367653, "name": "Cyberpunk 2077", "price_twd": 479, "cut_pct": 70,
         "is_default": True, "tracked": False, "action": "reset", "reason": None,
         "manual": "刪掉設定檔 [purchase_options] 中 7 那一行"},
    ]


def test_the_steam_default_lists_choosable_and_rejected_editions_in_order():
    got = versions_of(STEAM, [ULTIMATE, REJECTED], current=47900)
    assert [v["id"] for v in got] == [367653, 32470, 5]
    assert got[0] == {"kind": "sub", "id": 367653, "name": "Cyberpunk 2077", "price_twd": 479, "cut_pct": 60,
                      "is_default": True, "tracked": True, "action": None, "reason": None, "manual": None}
    assert got[1]["action"] == "choose" and got[1]["manual"] == '7 = "bundle/32470"' and got[1]["is_default"] is False
    assert got[2]["action"] is None and got[2]["manual"] is None
    assert got[2]["reason"] == ("核對未通過：ITAD 的商品還對應到組合包 bundle/9，價格歷史可能混了組合包的價格；"
                                "不能指定，也不使用它的價格歷史") == html.edition_refusal_text(REJECTED)
    no_itad = versions_of(STEAM, [th.edition("sub", 6, "No ITAD", 900, 1000, verification="unverified")])[1]
    assert no_itad["action"] is None and no_itad["reason"] == "沒有 ITAD 的價格歷史，不能指定"


def test_a_user_who_chose_the_default_itself_tracks_the_default():
    """resolve_choice keeps basis "user" for an explicit default; the default is then not among the editions."""
    chosen_default = {**th.USER, "option": {"kind": "sub", "id": 367653, "name": "Cyberpunk 2077"}}
    got = versions_of(chosen_default, [ULTIMATE])
    assert got[0]["is_default"] is True and got[0]["tracked"] is True


def test_unknown_prices_stay_null():
    data = th.with_editions([{**ULTIMATE, "price_twd": None, "cut_pct": None}])
    d = data["decisions"][0]
    d["version"], d["current"] = STEAM, None
    got = game(build(data), 7)["versions"]
    assert (got[0]["price_twd"], got[0]["cut_pct"]) == (None, None)
    assert (got[1]["price_twd"], got[1]["cut_pct"]) == (None, None)


def test_no_option_record_gives_no_versions():
    assert versions_of(None, None) == []
    assert versions_of({**th.ESSENTIALS, "basis": "own", "option": None}, None) == []
    assert game(build(sample()), 5)["versions"] == []                     # na game without a version


def test_a_game_with_one_option_has_one_version():
    assert len(versions_of(STEAM, [])) == 1
