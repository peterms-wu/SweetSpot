"""014 T031: the notice for a small reference dataset (FR-014a; contracts/cli.md §6; data-model `reference_notice`).
Presentation only: the decisions are the same with or without it (constitution IV); both presentations show the
same words from one place (constitution VII)."""

import dataclasses
import re
from pathlib import Path

import pytest

from sweetspot import commands
from sweetspot.report import extension, html
from tests.decision_builders import contract_dict, decision


def test_the_threshold_is_001s_target():
    assert commands.REFERENCE_TARGET == 2000


@pytest.mark.parametrize(("size", "key", "expected"), [
    (1999, True, {"dataset_size": 1999, "threshold": 2000, "broad_sample": "ok", "sampling": "incomplete"}),
    (340, False, {"dataset_size": 340, "threshold": 2000, "broad_sample": "disabled", "sampling": "incomplete"}),
    (2000, True, None),
    (2632, False, None),
])
def test_notice_below_the_threshold_only(size, key, expected):
    assert commands.reference_notice(size, has_steam_key=key) == expected


def test_a_complete_sampling_is_carried_and_asked_only_below_the_threshold():
    """014 T048: the check reads the database, so it runs only when there is a notice to show."""
    asked = []

    def complete():
        asked.append(1)
        return True

    assert commands.reference_notice(1659, has_steam_key=True, complete=complete)["sampling"] == "complete"
    assert commands.reference_notice(2632, has_steam_key=True, complete=complete) is None
    assert commands.reference_notice(1659, has_steam_key=False, complete=complete)["sampling"] == "incomplete"
    assert len(asked) == 1


def test_the_record_carries_it_only_when_there_is_one():
    data = contract_dict([decision(1)])
    assert "reference_notice" not in data                     # records above the threshold stay byte-identical
    from sweetspot.decision.contract import DecisionBatch
    assert "reference_notice" in {f.name for f in dataclasses.fields(DecisionBatch)}


def notice(size=340, broad="ok", sampling=None):
    found = {"dataset_size": size, "threshold": 2000, "broad_sample": broad}
    return found if sampling is None else {**found, "sampling": sampling}      # None: a record from before 014 T048


CONTRACT = Path(__file__).resolve().parents[2] / "specs" / "014-publish-github" / "contracts" / "cli.md"


def contract_texts() -> list[str]:
    """The quoted notice texts of contracts/cli.md §6, so the words cannot drift from the contract."""
    section = CONTRACT.read_text(encoding="utf-8").split("## 6. 參考資料集提示", 1)[1]
    return re.findall("「(參考資料集[^」]+)」", section)


@pytest.mark.parametrize("sampling", [None, "incomplete"])
def test_text_says_how_many_and_how_to_complete_it(sampling):
    text = html.reference_notice_text(notice(sampling=sampling))
    assert text == contract_texts()[0]                                  # the contract's example is 340 games
    assert "uv run sweetspot reference" in text and "每日更新" in text and "2～3 小時" in text
    assert "STEAM_WEB_API_KEY" not in text
    assert "STEAM_WEB_API_KEY" in html.reference_notice_text(notice(broad="disabled", sampling=sampling))


def test_a_complete_sampling_says_so_and_advises_nothing():
    text = html.reference_notice_text(notice(1659, sampling="complete"))
    assert text == contract_texts()[1]
    assert "uv run sweetspot reference" not in text and "1,659" in text and "2,000" in text


def test_report_header_and_extension_show_the_same_words():
    data = {**contract_dict([decision(1)]), "reference_notice": notice(1234)}
    page = html.render(data)
    text = html.reference_notice_text(notice(1234))
    assert text in page                                         # no character in it needs HTML escaping
    payload = extension.build(data)
    assert payload["reference_notice"] == text
    assert "1,234" in text


def test_without_a_notice_nothing_changes():
    data = contract_dict([decision(1)])
    assert "參考資料集目前" not in html.render(data)
    assert "reference_notice" not in extension.build(data)


def test_the_decisions_do_not_change():
    data = contract_dict([decision(1), decision(2, "wait")])
    with_notice = {**data, "reference_notice": notice()}
    assert with_notice["decisions"] == data["decisions"] and with_notice["summary"] == data["summary"]
    assert extension.build(with_notice)["games"] == extension.build(data)["games"]
