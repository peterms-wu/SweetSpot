"""The report's non-seasonal part (feature 007 contracts/cli-and-report.md; tasks T025)."""

import re
from dataclasses import replace
from datetime import timedelta

from sweetspot.decision.contract import na_decision
from sweetspot.decision.nonseasonal import attach, batch_block
from sweetspot.forecast.nonseasonal import build_ns_model
from sweetspot.forecast.nonseasonal.evidence import NSBasis
from sweetspot.forecast.nonseasonal.model import NSOutput
from sweetspot.report.html import render
from tests.decision_builders import AS_OF, contract_dict, decision
from tests.forecast_builders import dt

LEVELS = tuple(range(5, 100, 5))
FIGURES = {"earlier_hit_rate": 0.736, "earlier_threshold": 0.5}
BASIS = NSBasis(dt("2025-06-26"), "TW", 456, 6, 58, 50, dt("2026-08-10"), 50, 46, False)
DAY = timedelta(days=1)


def output(p=0.8):
    return NSOutput(tuple(tuple(p if d <= 50 else 0.1 for d in LEVELS) for _ in range(3)), "normal",
                    ("own",) * 3, BASIS)


def game(app, *, group="soon", days=75, p=0.8, adopted=True, out=None, name=None):
    d = decision(app, group, name=name or f"<Game {app}>")
    d = replace(d, sweet_point=replace(d.sweet_point, start=AS_OF + days * DAY, end=AS_OF + (days + 7) * DAY))
    return attach(d, out if out is not None else output(p), adopted=adopted, as_of=AS_OF, tw_start=dt("2025-06-26"),
                  figures=FIGURES if adopted else None)


def page(decisions, adopted=True, comparison=None):
    data = contract_dict(decisions, comparison=comparison)
    data["non_seasonal"] = batch_block(build_ns_model("non-seasonal"), adopted=adopted,
                                       figures=FIGURES if adopted else None)
    return render(data)


def block(html, app_id):
    m = re.search(rf'<details class="game" data-app="{app_id}".*?</details>', html, flags=re.S)
    assert m, app_id
    return m.group(0)


def test_section_with_probabilities_and_the_earlier_note():
    html = page([game(1), game(2, days=20)])
    one = block(html, 1)
    assert "季節特賣以外" in one and "可能提早" in one
    assert "60 天內有 80% 的機率" in one and "回測中這類說法有 74% 實際到價" in one
    assert "30 天內 80%、60 天內 80%、90 天內 80%" in one
    two = block(html, 2)
    assert "可能提早" not in two and "30 天內 80%" in two                  # the sale starts within 30 days


def test_before_adoption_only_the_past_is_shown():
    html = page([game(1, adopted=False)], adopted=False)
    one = block(html, 1)
    assert "過去一年季節特賣以外有 6 次促銷" in one
    section = re.search(r'<div class="ns">.*?</div>', one, flags=re.S).group(0)
    assert "機率" not in section and "可能提早" not in one
    assert "非季節預測：只顯示過去紀錄" in html


def test_header_and_model_error():
    html = page([game(1), game(2, out="RuntimeError: boom")])
    assert "非季節 non-seasonal 1.0.0" in html
    assert "非季節預測暫時無法計算：RuntimeError: boom" in block(html, 2)


def test_na_games_have_no_section_and_old_contracts_still_render():
    na = attach(na_decision(3, "Gone", "no-history", "沒有台灣區的 ITAD 價格歷史"), "x", adopted=True, as_of=AS_OF,
                tw_start=None, figures=FIGURES)
    html = page([game(1), na])
    assert "季節特賣以外" not in block(html, 3)
    old = contract_dict([decision(4)])
    old.pop("non_seasonal")
    for d in old["decisions"]:
        d.pop("non_seasonal")
    assert "願望清單甜蜜價報告" in render(old)


def test_first_adoption_is_noted_in_the_header():
    comparison = {"baseline": {"file": "x", "as_of": "2026-09-24T00:00:00Z"}, "changed_games": 0,
                  "skipped_records": [], "version_changes": ["非季節預測模型開始顯示機率（non-seasonal 1.0.0 {…}）"]}
    assert "非季節預測模型開始顯示機率" in page([game(1)], comparison=comparison)


def test_escaping():
    html = page([game(1)])
    assert "&lt;Game 1&gt;" in html and "<Game 1>" not in html
