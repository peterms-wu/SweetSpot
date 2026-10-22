"""feature 011 (tasks T004; spec SC-009): the HTML report is byte-identical after its sentence builders were split
into plain-text functions shared with the extension data file.

The golden pages in tests/fixtures/report/ were rendered by the report code *before* that split:
    uv run python -m tests.unit.report.test_html_golden
Regenerate them only when the report is meant to change.
"""

from pathlib import Path

import pytest

from sweetspot.decision.contract import na_decision
from sweetspot.report.html import render
from tests.decision_builders import contract_dict, decision
from tests.unit.report import test_bundles_html as tb
from tests.unit.report import test_html as th

GOLDEN = Path(__file__).resolve().parents[2] / "fixtures" / "report"
STOPPED = {**th.ESSENTIALS, "tracking": "stopped", "last_confirmed": "2025-01-27T18:00:30Z"}
# back on the Steam default: basis is the default's (version on the App's own product), never "user" (014 T073:
# the line used to key on basis, so this fixture had basis "user" and showed the choice as tracked as well)
FALLBACK = {**th.USER, "basis": "version", "source": "user-fallback", "package_name": "Cyberpunk 2077",
            "itad_id": "itad-old", "option": {"kind": "sub", "id": 1, "name": "Cyberpunk 2077"},
            "fallback": {"text": "指定的 bundle/32470 這次沒有價格，改用 Steam 預設版本"}}


def _unverified():
    return contract_dict([na_decision(8, "範例分季作品 - Season 1", "unverified", "ITAD 把 <商品> 算成同一個",
                                      {**th.ESSENTIALS, "basis": "rejected"})])


def _changed():
    d = decision(7, "soon", name="Cyberpunk 2077", change={
        "group": None, "sweet_point": None, "sweet_twd": None,
        "version": {"from": "Cyberpunk 2077", "to": "終極版", "detected_at": None, "cause": "user"}})
    return contract_dict([d])


def _low_confidence_bundle():
    data = tb.sample()
    next(b for b in data["bundles"] if b["id"] == 77855)["advice"]["confidence"] = "low"
    return data


CASES = {
    "sample": lambda: th.sample(),
    "sample_backtest": lambda: th.sample(rule_backtest=th.BACKTEST),
    "v3": lambda: th.v3_sample(),
    "bundles": lambda: tb.sample(),
    "bundles_specified": lambda: tb.sample(specified={2592160}),
    "bundles_low": _low_confidence_bundle,
    "version_essentials": lambda: th.versioned(th.ESSENTIALS),
    "version_own": lambda: th.versioned({**th.ESSENTIALS, "basis": "own", "basis_reason": "ambiguous",
                                         "itad_id": "itad-old"}),
    "version_stopped": lambda: th.versioned(STOPPED),
    "version_user": lambda: th.versioned({**th.USER, "aux_pending": True}, name="Cyberpunk 2077"),
    "version_fallback": lambda: th.versioned(FALLBACK, name="Cyberpunk 2077"),
    "editions": lambda: th.with_editions([th.ULT, th.BROKEN]),
    "unverified": _unverified,
    "changed": _changed,
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_report_is_byte_identical_to_the_golden_page(name):
    expected = (GOLDEN / f"golden_{name}.html").read_text(encoding="utf-8")
    assert render(CASES[name]()) == expected


if __name__ == "__main__":
    GOLDEN.mkdir(parents=True, exist_ok=True)
    for key, build in CASES.items():
        (GOLDEN / f"golden_{key}.html").write_text(render(build()), encoding="utf-8", newline="")
        print("wrote", key)
