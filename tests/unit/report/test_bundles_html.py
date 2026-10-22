"""feature 010: the report's 組合包 section (contracts/cli-and-report.md; tasks T019, T031)."""

import re
from dataclasses import replace

from sweetspot.decision import bundles
from sweetspot.report.html import render
from tests.decision_builders import (AS_OF, bundle_record, contract_dict, dave_miside, decision, e33_dispatch)


def sample(extra_records=(), specified=()):
    ds1, fs1, rec1 = e33_dispatch()
    ds2, fs2, rec2 = dave_miside()
    other = decision(3, "soon", name="Lonely Game")
    decisions = ds1 + ds2 + [other]
    mixed = bundle_record(1868140, 74673, [(1868140, None, None), (2527500, 0, None), (457680, 0, None, 30000),
                                           (458740, 11, 457680, 15200)], final_cents=90950, discount=15,
                          name="Mixed Pack")
    records = {}
    for r in (rec1, rec2, mixed, *extra_records):
        records.setdefault(r.app_id, []).append(r)
    block = bundles.build_bundles(records, decisions, {**fs1, **fs2}, as_of=AS_OF, names={457680: "OPUS：地球計畫"},
                                  specified=set(specified))
    data = contract_dict(decisions, rule="2.1.0")
    data["bundles"] = block.bundles
    data["bundle_rule"] = {"name": "bundle-advice", "version": "1.0.0"}
    for d in data["decisions"]:
        d["bundles"] = block.per_app[d["app_id"]]
    return data


def section(page):
    match = re.search(r'<section id="bundles".*?</section>', page, flags=re.S)
    assert match
    return match.group(0)


def card(page, bundle_id):
    match = re.search(rf'<details class="bundle" id="bundle-{bundle_id}".*?</details>', page, flags=re.S)
    assert match, bundle_id
    return match.group(0)


def test_section_comes_before_the_groups_pure_first():
    page = render(sample())
    assert page.index('<section id="bundles"') < page.index('<section id="group-now"')
    ids = re.findall(r'<details class="bundle" id="bundle-(\d+)"', section(page))
    assert ids == ["74895", "77855", "74673"]
    assert '<a class="chip" href="#bundles">組合包（3）</a>' in page


def test_pure_card_shows_comparison_estimate_and_advice():
    data = sample()
    page = render(data)
    c = card(page, 74895)
    assert "組合包 −10%" in c and "只含願望清單遊戲" in c
    assert "現在：組合包 NT$1,150" in c and "分開買 NT$1,278" in c and "各自在甜蜜時點買 NT$1,132（最晚 2026 冬特）" in c
    assert "任何一場季節特賣（最早 2026 秋特）：約 NT$1,063，同時到價 73%" in c
    b = next(b for b in data["bundles"] if b["id"] == 74895)
    assert b["advice"]["text"] in c and b["owned_note"] in c


def test_mixed_card_shows_the_extra_cost():
    c = card(render(sample()), 74673)
    assert "含其他內容" in c and "只買願望清單遊戲 NT$618" in c
    assert "多付 NT$292，多得 1 款遊戲：OPUS：地球計畫、1 個其他內容（DLC、原聲帶等）" in c
    assert "任何一場季節特賣" not in c


def test_low_confidence_and_no_advice_are_shown():
    data = sample()
    b = next(b for b in data["bundles"] if b["id"] == 77855)
    b["advice"]["confidence"] = "low"
    assert '<span class="tag">低信心</span>' in card(render(data), 77855)
    page = render(sample(specified={2592160}))
    c = card(page, 74895)
    assert "Dispatch 指定了其他版本" in c and "任何一場季節特賣" not in c


def test_contents_table_and_mismatch_text():
    ds, fs, rec = e33_dispatch()
    data = sample(extra_records=[replace(rec, option_id=5, name="Broken", final_cents=120000)])
    c = card(render(data), 5)
    assert "<table" in c and "光與影：33號遠征隊" in c and "願望清單遊戲" in c
    assert "依組合包折扣 −10% 與各內容現價推算為 NT$1,150" in c


def test_a_mismatch_is_said_once():
    """014 T075: for a pure bundle the no-advice reason already holds check.text ("…，今天不給組合包建議"); the card
    and the extension's popup added the same text again. A mixed bundle has no reason sentence: it keeps the line."""
    from sweetspot.report.html import bundle_card_texts

    ds, fs, rec = e33_dispatch()
    data = sample(extra_records=[replace(rec, option_id=5, name="Broken", final_cents=120000)])
    broken = next(b for b in data["bundles"] if b["id"] == 5)
    assert broken["grade"] == "pure" and broken["check"]["status"] == "mismatch"
    assert card(render(data), 5).count(broken["check"]["text"]) == 1
    assert bundle_card_texts(broken)["check_text"] is None
    mixed = {**broken, "grade": "mixed", "advice": None, "extra_twd": 0, "extra_games": 1, "wishlist_twd": 0}
    assert bundle_card_texts(mixed)["check_text"] == broken["check"]["text"]


def test_no_bundles_no_section():
    data = sample()
    data["bundles"] = []
    page = render(data)
    assert '<section id="bundles"' not in page and 'href="#bundles"' not in page
    data.pop("bundles")
    assert '<section id="bundles"' not in render(data)          # an old record


def test_numbers_come_from_the_dict():
    data = sample()
    b = next(b for b in data["bundles"] if b["id"] == 74895)
    b["advice"]["estimate_twd"] = 999
    assert "約 NT$999" in card(render(data), 74895)


# --- T031: the pointer line in each game --------------------------------------------------------------------------

def game(page, app_id):
    match = re.search(rf'<details class="game" data-app="{app_id}".*?</details>', page, flags=re.S)
    assert match, app_id
    return match.group(0)


def test_each_game_points_to_its_bundles():
    page = render(sample())
    dave = game(page, 1868140)
    assert dave.count('class="bundle-hint"') == 2
    assert '<a href="#bundle-77855">' in dave and '<a href="#bundle-74673">' in dave
    assert "可和 MiSide 一起買：組合包 −10%" in dave
    assert 'class="bundle-hint"' not in game(page, 3)
    for target in re.findall(r'href="#bundle-(\d+)"', page):
        assert f'id="bundle-{target}"' in page


def test_pointer_warns_about_a_specified_edition():
    page = render(sample(specified={1903340}))
    assert "組合包含的是 Steam 預設的版本，不是你指定的版本" in game(page, 1903340)
