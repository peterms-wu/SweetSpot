"""HTML report from a steamsage.decision/1 dict (tasks T017; contracts/report-html.md; SC-003, SC-007)."""

import re
from pathlib import Path
import subprocess
import sys
import time

import pytest

from sweetspot.decision.contract import na_decision
from sweetspot.report.html import render
from tests.decision_builders import contract_dict, decision

BACKTEST = {"date": "2026-09-25", "region": "TW", "window_months": 12, "hit_rate": {"soon": 0.95, "wait": 0.88,
            "low": 0.2}, "now_deeper_within_12m": 0.51, "source": "docs/model/model-definition.md"}


def sample(**kw):
    games = [
        decision(1, "now", name="Cheap Now", current=20000, sweet_pct=50),
        decision(2, "soon", name="Soon Game", sweet_pct=40, p_min_pct=50),
        decision(3, "wait", name="Wait Game", sweet_pct=80, p_min_pct=85, sweet_index=5, regular=86000,
                 current=86000, change={"group": {"from": "soon", "to": "wait"},
                                        "sweet_point": {"from": "2026 秋特", "to": "2027 秋特"},
                                        "sweet_twd": {"from": 215, "to": 172}}),
        decision(4, "low", name="Low Game", confidence="low", tags=("low-confidence", "regular-mismatch")),
        na_decision(5, "Future Game", "unreleased", "尚未發行（預定 2027-01-01）"),
    ]
    return contract_dict(games, **kw)


def sections(page):
    """{group: html of its section}."""
    return dict(re.findall(r'<section id="group-(\w+)".*?>(.*?)</section>', page, flags=re.S))


def game_block(page, app_id):
    match = re.search(rf'<details class="game" data-app="{app_id}".*?</details>', page, flags=re.S)
    assert match, app_id
    return match.group(0)


def test_every_game_exactly_once_in_its_group():
    data = sample()
    page = render(data)
    groups = sections(page)
    assert list(groups) == ["now", "soon", "wait", "low", "na"]
    for d in data["decisions"]:
        assert page.count(f'data-app="{d["app_id"]}"') == 1
        assert f'data-app="{d["app_id"]}"' in groups[d["group"]]
    for group, count in data["summary"].items():
        if group in groups:
            assert f"（{count}）" in page


def test_values_match_the_contract():
    data = sample()
    page = render(data)
    for d in data["decisions"]:
        block = game_block(page, d["app_id"])
        if d["group"] == "na":
            assert d["status_reason"] in block
            continue
        assert f"NT${d['sweet_twd']:,}" in block and f"-{d['sweet_pct']}%" in block
        assert f"NT${d['p_min_twd']:,}" in block and f"-{d['p_min_pct']}%" in block
        assert f"NT${d['current']['price_twd']:,}" in block
        assert d["sweet_point"]["label"] in block and ("官方" in block or "預估" in block)
        assert "54%" in block                                                # 0.537
        assert "2026-09-25 08:00" in block                                   # confirmed_at in Taipei time
        assert "Steam 現價" in block                                         # current.source
        for row in d["ladder"]:
            assert row["label"] in block and f"NT${row['twd']:,}" in block
        for reason in d["reasons"]:
            assert reason in block
    wait = game_block(page, 3)
    assert "上次：即將到價" in wait and "上次：2026 秋特" in wait and "上次：NT$215" in wait
    low = game_block(page, 4)
    assert "原價不一致" in low and "低信心" in low


def test_probability_hover_text_says_what_it_forecasts():
    """2026-10-18: a buy-now game's 到價機率 is not about the current price; the same text as the extension's."""
    data = sample()
    d = next(d for d in data["decisions"] if d["group"] == "now")
    block = game_block(render(data), d["app_id"])
    want = (f'到 {d["sweet_point"]["label"]}為止，季節特賣打到 -{d["sweet_pct"]}%（NT${d["sweet_twd"]:,}）'
            "以上的機率；跟現價無關")
    assert f'<span class="cell" title="{want}"><small>到價機率</small>' in block


def test_header():
    page = render({**sample(data_refresh={"update_exit": 1, "note": "本次資料更新失敗，使用既有資料"}),
                   "notes": ["長期最低價可能更低：目前的模型無法預測比過去更深的折扣"]})
    head = page.split('<section id="group-now"')[0]
    for text in ("seasonal-freq 1.0.0", "sweet-price 1.0.0", "使用者偏好", "2026-09-25 08:00",
                 "本次資料更新失敗，使用既有資料", "沒有前一天或更早的紀錄，無法比較",
                 "長期最低價可能更低：目前的模型無法預測比過去更深的折扣",
                 "價格指 Steam 商店預設的購買選項（通常是一般版）；在設定檔 [purchase_options] 指定了版本的遊戲，指那個版本",
                 "折扣差距", "NT$30", "NT$100"):
        assert text in head, text


def test_unofficial_and_baseline_headers():
    assert "以過去時點執行" in render(contract_dict([decision(1), decision(2, "wait", sweet_index=3)], official=False))
    page = render(sample(comparison={"baseline": {"file": "20260924T010000Z.json.gz", "as_of": "2026-09-24T01:00:00Z"},
                                     "version_changes": ["偏好 gap_pp_deep 5 → 10"], "skipped_records": ["bad.json.gz"],
                                     "changed_games": 1}))
    assert "2026-09-24 09:00" in page and "偏好 gap_pp_deep 5 → 10" in page and "bad.json.gz" in page


def test_calendar_changes_line_follows_the_version_changes():
    """Feature 012 (FR-015): one line per sale whose dates became official or moved."""
    comparison = {"baseline": {"file": "f", "as_of": "2026-09-24T01:00:00Z"}, "version_changes": ["偏好 x 1 → 2"],
                  "skipped_records": [], "changed_games": 0,
                  "calendar_changes": ["2026 冬特 預估 → 官方（太平洋時間 12/17–1/4）"]}
    page = render(sample(comparison=comparison))
    line = "特賣日期更新：2026 冬特 預估 → 官方（太平洋時間 12/17–1/4）（部分變動可能來自這個改變）"
    assert line in page
    assert page.index("偏好 x 1 → 2") < page.index(line)
    without = render(sample(comparison={**comparison, "calendar_changes": []}))
    older = render(sample(comparison={k: v for k, v in comparison.items() if k != "calendar_changes"}))
    assert "特賣日期更新" not in without and without == older


def test_rule_backtest_figures():
    assert "規則尚未以現行模型與規則回測" in render(sample())
    page = render(sample(rule_backtest=BACKTEST))
    groups = sections(page)
    assert "規則尚未以現行模型與規則回測" not in page
    assert "95%" in page.split('id="group-soon"')[1].split("</summary>")[0]
    assert "88%" in page.split('id="group-wait"')[1].split("</summary>")[0]
    low_title = page.split('id="group-low"')[1].split("</summary>")[0]
    assert "回測中只有約 20% 在這個時點前到價，僅供參考" in low_title
    now_title = page.split('id="group-now"')[1].split("</summary>")[0]
    assert "51%" in now_title and "更深折扣" in now_title
    assert "%" not in page.split('id="group-na"')[1].split("</summary>")[0]
    assert groups


def test_external_text_is_escaped():
    page = render(contract_dict([decision(1, name="<script>alert(1)</script>")]))
    assert "<script>alert(1)" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_no_external_resources():
    page = render(sample())
    refs = re.findall(r'(?:src|href)="([^"]+)"', page)
    external = [r for r in refs if r.startswith(("http://", "https://", "//"))]
    assert external and all(r.startswith("https://store.steampowered.com/app/") for r in external)
    assert "<link" not in page and "@import" not in page
    assert all('src="' not in tag for tag in re.findall(r"<script[^>]*>", page))


def test_filter_box_and_collapsible_groups():
    page = render(sample())
    assert 'id="filter"' in page and "<script>" in page
    assert page.count('<details class="group" open>') == 5


def test_same_contract_same_page():
    data = sample()
    assert render(data) == render(data)


def test_report_module_does_not_import_the_core():
    code = ("import sys, sweetspot.report.html; "
            "print([m for m in sys.modules if m.startswith(('sweetspot.forecast', 'sweetspot.decision'))])")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    assert out == "[]"


def test_five_hundred_games():
    groups = ["now", "soon", "wait", "low"]
    games = [decision(i, groups[i % 4], name=f"遊戲 {i:03d}", current=20000 if i % 4 == 0 else 50000,
                      confidence="low" if i % 4 == 3 else "normal") for i in range(1, 501)]
    data = contract_dict(games, rule_backtest=BACKTEST)
    started = time.perf_counter()
    page = render(data)
    elapsed = time.perf_counter() - started
    assert elapsed < 2.0
    assert len(page.encode("utf-8")) < 3 * 1024 * 1024
    assert all(f'data-app="{i}"' in page for i in range(1, 501))
    assert 'id="filter"' in page


def test_lowest_price_wording_follows_the_rule():
    """004 research R5: rule 2.0.0 calls P_min the 12-month lowest price."""
    old = render(sample())
    assert "<small>長期最低</small>" in old and "12 個月內最低" not in old
    data = sample()
    data["rule"] = {**data["rule"], "version": "2.0.0",
                    "constants": {**data["rule"]["constants"], "p_min_months": 12}}
    page = render(data)
    assert "<small>12 個月內最低</small>" in page and "折扣差距：12 個月內最低價淺於" in page
    assert "<small>長期最低</small>" not in page



def test_header_shows_the_notes_of_the_contract():
    """004 research R9: the caveat is data, not report code."""
    data = sample()
    data["notes"] = ["12 個月內最低價可能更低：回測中判為現在買之後 12 個月內，仍有 42% 出現更深折扣"]
    head = render(data).split('<section id="group-now"')[0]
    assert "仍有 42% 出現更深折扣" in head
    assert "目前的模型無法預測" not in render({**sample(), "notes": []})
    import sweetspot.report.html as html
    assert "無法預測比過去更深" not in Path(html.__file__).read_text(encoding="utf-8")


# --- feature 005: rule 3.0.0 (tasks T017; contracts/report-html-v005.md) ------------------------------------

from tests.decision_builders import v3_decision  # noqa: E402

V3_BACKTEST = {**BACKTEST, "rule": "3.0.0", "wait_cost_twd": 20}


def v3_sample(**kw):
    games = [v3_decision(1, name="Wait <b>Game</b>"),                    # -50%: likely sale 1, deadline sale 2
             v3_decision(2, name="Buy Now", current=50000),               # already -50%: nothing pays
             v3_decision(3, name="Later", rows=[{5: 0.9, 50: 0.2}, {5: 0.95, 50: 0.7}])]
    return contract_dict(games, rule="3.0.0", **kw)


def test_v3_header_shows_the_waiting_cost_not_the_tolerance():
    page = render(v3_sample())
    assert "等待成本 NT$20／月（使用者偏好）" in page and "sweet-price 3.0.0" in page
    assert "容許差距" not in page and "折扣差距" not in page


def test_v3_preview_banner():
    assert "預覽：非現行規則" in render({**v3_sample(official=False), "preview": True})
    assert "預覽：非現行規則" not in render(v3_sample())


def test_v3_summary_cells_match_the_contract():
    data = v3_sample()
    page = render(data)
    d = next(x for x in data["decisions"] if x["app_id"] == 1)
    block = game_block(page, 1)
    e = d["expected"]
    assert f"NT${d['sweet_twd']:,} -{d['sweet_pct']}%" in block
    assert d["sweet_point"]["label"] in block and f"{d['sweet_probability']:.0%}" in block
    assert f"<small>最晚等到</small>{d['deadline_point']['label']}" in block
    assert f"<small>期望多省</small>NT${e['expected_saving_twd']:,}" in block
    assert f"<small>淨效益</small>NT${e['net_twd']:,}" in block
    assert "Wait &lt;b&gt;Game&lt;/b&gt;" in block


def test_v3_buy_now_row_shows_dashes():
    data = v3_sample()
    block = game_block(render(data), 2)
    assert next(x for x in data["decisions"] if x["app_id"] == 2)["group"] == "now"
    assert "<small>期望多省</small>—" in block and "<small>淨效益</small>—" in block
    assert "<small>最晚等到</small>—" in block


def test_v3_waiting_table():
    data = v3_sample()
    page = render(data)
    for d in data["decisions"]:
        block = game_block(page, d["app_id"])
        table = re.search(r"<table class=\"wait\">.*?</table>", block, flags=re.S).group(0)
        rows = re.findall(r"<tr[ >].*?</tr>", table, flags=re.S)[1:]            # skip the header
        assert len(rows) == len(d["wait_options"])
        assert table.count("建議") == 1 and "現在買" in rows[0]
        for row, o in zip(rows, d["wait_options"]):
            assert f"{o['expected_wait_months']:.1f}" in row
            if o["chosen"]:
                assert 'class="chosen"' in row
            if o["net_twd"] is not None and o["deadline_index"]:
                assert f"NT${o['net_twd']:,}" in row or f"-NT${-o['net_twd']:,}" in row


def test_v3_negative_amounts():
    data = v3_sample()
    block = game_block(render(data), 2)
    worst = [o for o in next(x for x in data["decisions"] if x["app_id"] == 2)["wait_options"] if o["deadline_index"]]
    assert worst and all(o["net_twd"] < 0 for o in worst)
    assert f"-NT${-worst[0]['net_twd']:,}" in block


def test_v3_backtest_figures_name_the_cost():
    page = render(v3_sample(rule_backtest=V3_BACKTEST))
    assert "以等待成本 NT$20 回測" in page
    page = render(v3_sample())
    assert "回測到價率" not in page


def test_v3_cost_change_is_shown():
    comparison = {"baseline": {"file": "x", "as_of": "2026-09-24T04:00:00Z"},
                  "version_changes": ["等待成本從 NT$20 改成 NT$30"], "skipped_records": [], "changed_games": 2}
    page = render(v3_sample(comparison=comparison))
    assert "版本或偏好改變：等待成本從 NT$20 改成 NT$30（部分變動可能來自這個改變）" in page


def test_v3_lowest_price_is_only_in_the_details():
    data = v3_sample()
    block = game_block(render(data), 1)
    summary = block.split("</summary>")[0]
    assert "12 個月內最低" not in summary and "12 個月內最低價（參考）" in block


# --- feature 006: which version's history (spec FR-013, contracts/cli-and-report.md) ----------------------------

from dataclasses import replace as _replace  # noqa: E402

ESSENTIALS = {"basis": "version", "basis_reason": None, "package_id": 1345940,
              "package_name": "Dying Light Essentials Edition", "itad_id": "itad-new",
              "history_start": "2025-06-26T23:26:51Z", "known_until": "2026-09-27T01:00:00Z", "tracking": "ok",
              "last_confirmed": None, "change": None, "reason_code": None, "reason_detail": None,
              "checked_at": "2026-09-27T01:00:00Z", "own_itad_id": "itad-old"}


def versioned(version, name="Dying Light"):
    return contract_dict([_replace(decision(7, "soon", name=name), version=version)])


def test_tracked_version_is_shown_when_it_is_not_the_app_itself():
    block = game_block(render(versioned(ESSENTIALS)), 7)
    assert "追蹤 Dying Light Essentials Edition · 歷史從 2025-06-27 起" in block      # Taipei date


def test_no_version_line_when_the_product_is_the_apps_own():
    """A package named differently (language, "Standard Edition") is not another version (real data: 18 games)."""
    same = {**ESSENTIALS, "package_name": "DAVE THE DIVER", "itad_id": "itad-old"}
    assert "追蹤" not in game_block(render(versioned(same, name="潛水員戴夫 DAVE THE DIVER")), 7)
    assert "追蹤" not in game_block(render(versioned(None)), 7)


def test_unconfirmed_and_unrecorded_versions_are_marked():
    own = {**ESSENTIALS, "basis": "own", "basis_reason": "ambiguous", "itad_id": "itad-old"}
    assert "無法確認 Steam 目前賣的版本，沿用 App 本身的價格歷史" in game_block(render(versioned(own)), 7)
    none = {**own, "basis_reason": "no-record"}
    assert "這個時點沒有版本紀錄，沿用 App 本身的價格歷史" in game_block(render(versioned(none)), 7)


def test_unverified_game_shows_its_reason():
    from sweetspot.decision.contract import na_decision

    reason = "ITAD 把 Steam 目前的購買選項（範例分季作品）和組合包 bundle/99003 算成同一個商品，價格歷史混了不同商品的價格，無法使用"
    page = render(contract_dict([na_decision(8, "範例分季作品 - Season 1", "unverified", reason,
                                             {**ESSENTIALS, "basis": "rejected"})]))
    block = game_block(page, 8)
    assert "組合包 bundle/99003" in block and "沿用" not in block



def test_version_change_marker_and_detection_date():
    change = {"from_itad_id": "itad-old", "from_title": "Dying Light", "to_itad_id": "itad-new",
              "to_title": "Dying Light Essentials Edition", "detected_at": "2026-09-27T01:00:00Z"}
    d = _replace(decision(7, "soon", name="Dying Light", change={
        "group": None, "sweet_point": None, "sweet_twd": None,
        "version": {"from": "Dying Light", "to": "Dying Light Essentials Edition", "detected_at": "2026-09-27T01:00:00Z"}}),
        version={**ESSENTIALS, "change": change})
    block = game_block(render(contract_dict([d])), 7)
    assert "版本更換：Dying Light → Dying Light Essentials Edition（偵測於 2026-09-27）" in block
    assert "追蹤 Dying Light Essentials Edition · 歷史從 2025-06-27 起 · 2026-09-27 偵測到版本更換" in block


def test_stopped_history_is_marked():
    stopped = {**ESSENTIALS, "tracking": "stopped", "last_confirmed": "2025-01-27T18:00:30Z"}
    assert "價格歷史停止更新（最後確認 2025-01-28）" in game_block(render(versioned(stopped)), 7)   # Taipei date


# --- feature 009: other editions (contracts/cli-and-report.md) -------------------------------------------------

def edition(kind, id_, name, price, regular, *, low=None, low_at=None, start=None, verification="verified",
            reason=None, detail=None, line=None, is_default=False, unset=False):
    return {"kind": kind, "id": id_, "name": name, "is_default": is_default, "price_cents": price * 100,
            "price_twd": price, "regular_cents": regular * 100, "regular_twd": regular,
            "cut_pct": round(100 - 100 * price / regular) if price < regular else 0,
            "checked_at": "2026-09-27T01:00:00Z", "verification": verification, "reason_code": reason,
            "reason_detail": detail, "itad_id": "x" if verification == "verified" else None, "history_start": start,
            "low_cents": low * 100 if low is not None else None, "low_twd": low, "low_at": low_at,
            "config_line": line, "unset_hint": unset}


def with_editions(editions, group="soon"):
    data = contract_dict([decision(7, group, name="Cyberpunk 2077")])
    data["decisions"][0]["editions"] = editions
    return data


ULT = edition("bundle", 32470, "《電馭叛客 2077：終極版》", 2206, 2206, low=882, low_at="2026-06-25T17:10:00Z",
              start="2024-12-11T15:09:33Z", line='1091500 = "bundle/32470"')
BROKEN = edition("sub", 1265945, "Definitive <Edition>", 149, 749, verification="rejected", reason="bundle",
                 detail="bundle/47759")


def test_summary_counts_the_other_editions():
    block = game_block(render(with_editions([ULT, BROKEN])), 7)
    summary = re.search(r"<summary>.*?</summary>", block, flags=re.S).group(0)
    assert "另有 2 個版本" in summary


def test_no_edition_hint_without_editions():
    for editions in ([], None):
        assert "個版本" not in game_block(render(with_editions(editions)), 7)


def test_edition_table_in_the_details():
    block = game_block(render(with_editions([ULT, BROKEN])), 7)
    body = block.split("</summary>", 1)[1]
    assert "《電馭叛客 2077：終極版》" in body and "NT$2,206" in body
    assert "NT$882" in body and "2026-06-26" in body                  # the low and its Taipei date
    assert "2024-12-11" in body                                        # history start (Taipei)
    assert '1091500 = &quot;bundle/32470&quot;' in body and 'class="copy"' in body
    assert "Definitive &lt;Edition&gt;" in body and "NT$149" in body and "-80%" in body
    assert "核對未通過" in body and "bundle/47759" in body       # reason_text absent: raw code and detail
    assert body.count('class="copy"') == 1                            # no config line for the rejected one


def test_edition_without_history_shows_a_dash_not_zero():
    bare = edition("bundle", 77856, "豪華版", 837, 837, line='4570720 = "bundle/77856"')
    body = game_block(render(with_editions([bare])), 7).split("</summary>", 1)[1]
    assert "—（還沒有價格歷史）" in body and "NT$0" not in body


def test_unset_hint_on_the_default_row():
    default = edition("sub", 367653, "Cyberpunk 2077", 1599, 1599, low=479, is_default=True, unset=True)
    body = game_block(render(with_editions([default])), 7).split("</summary>", 1)[1]
    assert "刪掉設定檔中的這一行即可取消指定" in body


def test_unpredictable_game_still_lists_its_editions():
    data = contract_dict([na_decision(8, "Projekt", "unverified", "核對未通過")])
    data["decisions"][0]["editions"] = [ULT]
    block = game_block(render(data), 8)
    assert "另有 1 個版本" in block and "《電馭叛客 2077：終極版》" in block


def test_copy_button_script_is_inline():
    page = render(with_editions([ULT]))
    assert "navigator.clipboard" in page


USER = {**ESSENTIALS, "basis": "user", "source": "user", "package_id": None, "package_name": "《電馭叛客 2077：終極版》",
        "option": {"kind": "bundle", "id": 32470, "name": "《電馭叛客 2077：終極版》"}, "fallback": None,
        "history_start": "2024-12-11T15:09:33Z", "aux_pending": False}


def test_users_choice_is_always_shown():
    block = game_block(render(versioned(USER, name="Cyberpunk 2077")), 7)
    assert "追蹤 《電馭叛客 2077：終極版》（使用者指定） · 歷史從 2024-12-11 起" in block


def test_the_header_says_which_price_is_meant():
    """014 T077: since 006 the price is Steam's default purchase option (it may hold DLC), and since 009 a game can
    track an edition the user chose (a deluxe one, say); "the standard edition, no deluxe packages" was wrong."""
    page = render(versioned(None))
    assert "不含豪華版" not in page
    assert "價格指 Steam 商店預設的購買選項（通常是一般版）；在設定檔 [purchase_options] 指定了版本的遊戲，指那個版本。" in page


@pytest.mark.parametrize("basis", ["version", "own"])
def test_a_choice_of_the_steam_default_is_shown_too(basis):
    """014 T073 (009 contracts/cli-and-report.md: `source = user` is always shown): choosing the Steam default, or an
    edition on its product, keeps basis version/own, and the line keyed on basis said nothing. The default row is
    then the tracked one and not listed, so the line also says how to undo the choice."""
    same = {**ESSENTIALS, "basis": basis, "source": "user", "itad_id": "itad-old",
            "option": {"kind": "sub", "id": 1345940, "name": "Dying Light Essentials Edition"}, "aux_pending": False}
    text = _html.version_text(versioned(same)["decisions"][0])
    assert text is not None and text.startswith("追蹤 Dying Light Essentials Edition（使用者指定）")
    assert "刪掉設定檔中的這一行即可取消指定" in text
    assert "沿用 App 本身的價格歷史" not in text


def test_missing_aux_history_is_explained():
    block = game_block(render(versioned({**USER, "aux_pending": True}, name="Cyberpunk 2077")), 7)
    assert "美國區歷史下一次更新才會取得" in block



@pytest.mark.parametrize("cause,text", [
    ("user", "版本更換（使用者指定）：Cyberpunk 2077 → 終極版"),
    ("unset", "版本更換（取消指定）：Cyberpunk 2077 → 終極版"),
    ("fallback", "版本更換（指定的版本不能用）：Cyberpunk 2077 → 終極版"),
    ("steam", "版本更換：Cyberpunk 2077 → 終極版（偵測於 2026-09-27）"),
])
def test_version_change_names_its_cause(cause, text):
    detected = "2026-09-27T01:00:00Z" if cause == "steam" else None
    d = decision(7, "soon", name="Cyberpunk 2077", change={
        "group": None, "sweet_point": None, "sweet_twd": None,
        "version": {"from": "Cyberpunk 2077", "to": "終極版", "detected_at": detected, "cause": cause}})
    assert text in game_block(render(contract_dict([d])), 7)


# --- feature 011: plain-text sentence builders shared with the extension data file (tasks T005) ----------------

from sweetspot.report import html as _html  # noqa: E402


def test_version_text_is_the_version_line_without_html():
    d = versioned({**USER, "aux_pending": True}, name="Cyberpunk 2077")["decisions"][0]
    assert _html.version_text(d) == "追蹤 《電馭叛客 2077：終極版》（使用者指定） · 歷史從 2024-12-11 起 · 美國區歷史下一次更新才會取得"
    assert _html.version_text(versioned(None)["decisions"][0]) is None
    same = {**ESSENTIALS, "package_name": "DAVE THE DIVER", "itad_id": "itad-old"}
    assert _html.version_text(versioned(same)["decisions"][0]) is None


def test_bundle_hint_texts_match_the_report_sentence():
    from tests.unit.report import test_bundles_html as tb

    data = tb.sample(specified={2592160})
    by_id = {b["id"]: b for b in data["bundles"]}
    dispatch = next(d for d in data["decisions"] if d["app_id"] == 2592160)
    assert _html.bundle_hint_texts(dispatch, by_id) == [
        {"id": 74895, "text": "可和 光與影：33號遠征隊 一起買：組合包 −10%；組合包含的是 Steam 預設的版本，不是你指定的版本"}]
    dave = next(d for d in data["decisions"] if d["app_id"] == 1868140)
    texts = [h["text"] for h in _html.bundle_hint_texts(dave, by_id)]
    assert texts == ["可和 MiSide 一起買：組合包 −10%", "可和 MiSide 一起買：組合包 −15%（另含其他內容）"]
    assert _html.bundle_hint_texts(next(d for d in data["decisions"] if d["app_id"] == 3), by_id) == []


def test_bundle_card_texts_match_the_card():
    from tests.unit.report import test_bundles_html as tb

    data = tb.sample()
    page = render(data)
    for b in data["bundles"]:
        t = _html.bundle_card_texts(b)
        card = tb.card(page, b["id"])
        assert t["grade_text"] in card and t["discount_text"] in card
        for line in t["lines"]:
            assert _html._t(line) in card
        if t["advice_text"]:
            assert f"<strong>{_html._t(t['advice_text'])}</strong>" in card
    pure = _html.bundle_card_texts(next(b for b in data["bundles"] if b["id"] == 74895))
    assert pure["grade_text"] == "只含願望清單遊戲" and pure["discount_text"] == "組合包 −10%"
    assert pure["lines"] == ["現在：組合包 NT$1,150｜分開買 NT$1,278｜各自在甜蜜時點買 NT$1,132（最晚 2026 冬特）",
                             "任何一場季節特賣（最早 2026 秋特）：約 NT$1,063，同時到價 73%"]
    assert pure["advice_low"] is False and pure["check_text"] is None
    mixed = _html.bundle_card_texts(next(b for b in data["bundles"] if b["id"] == 74673))
    assert mixed["advice_text"] is None and mixed["lines"][0].startswith("組合包 NT$910｜只買願望清單遊戲 NT$618")


def test_tag_labels_sorted_games_and_lowest_label():
    assert _html.tag_labels(["low-confidence", "unknown-tag", "stale-price"]) == ["低信心", "現價可能已變"]
    games = sample()["decisions"]
    assert _html.sorted_games("now", games[:1]) == games[:1]
    data = sample()
    assert _html.lowest_label(data) == "長期最低"
    data["rule"]["constants"]["p_min_months"] = 12
    assert _html.lowest_label(data) == "12 個月內最低"


def test_calendar_notices_are_banners_after_the_refresh_note():
    """Feature 012 (plan D1; FR-021)."""
    data = sample()
    data["data_refresh"] = {"update_exit": 1, "note": "本次資料更新失敗，使用既有資料"}
    data["calendar_notices"] = ["官方特賣頁面的 2026 冬特是 12/18–1/4，data/steam_sales.toml 是 12/17–1/4；預測沿用檔案的日期。"]
    page = render(data)
    notice = f'<p class="banner">{data["calendar_notices"][0]}</p>'
    assert notice in page
    assert page.index("本次資料更新失敗") < page.index(notice)
    empty = sample()
    empty["calendar_notices"] = []
    assert render(empty) == render(sample())
