"""feature 010 (spec FR-019, research R0.2): every hit rate the report may quote for a bundle is in the model
definition's bundle-advice section, and the rule constants match it."""

from pathlib import Path

from sweetspot.decision import bundles

DOC = Path(__file__).resolve().parents[3] / "docs" / "model" / "model-definition.md"


def section() -> str:
    text = DOC.read_text(encoding="utf-8")
    start = text.index("## 組合包建議 `bundle-advice` v1.0.0")
    end = text.index("\n## ", start + 1)
    return text[start:end]


def test_rule_name_and_constants():
    assert bundles.RULE == ("bundle-advice", "1.0.0")
    assert (bundles.JOINT_THRESHOLD, bundles.CHECK_MIN_CENTS, bundles.CHECK_SHARE) == (0.5, 200, 0.01)
    text = section()
    assert "50%" in text and "NT$2" in text and "1%" in text


def test_every_quoted_hit_rate_is_in_the_bundle_section():
    text = section()
    bt = bundles.BUNDLE_BACKTESTS
    assert bt["source"] == "docs/model/model-definition.md"
    assert bt["dataset"][:8] in text and bt["cutoff"] in text and bt["split"] == "tuning"
    assert [b["bin"] for b in bt["bins"]] == [[0.5, 0.6], [0.6, 0.7], [0.7, 0.8], [0.8, 0.9], [0.9, 1.0]]
    for b in bt["bins"]:
        assert f"{b['observed'] * 100:.1f}%" in text, b
        assert f"{b['units']:,}" in text, b
    overall = bt["overall"]
    assert f"{overall['units']:,}" in text and f"{overall['mean_forecast']:.3f}" in text
    assert f"{overall['observed']:.3f}" in text


def test_hit_rate_lookup_uses_the_bin_of_the_probability():
    assert bundles.hit_rate(0.51)["bin"] == [0.5, 0.6]
    assert bundles.hit_rate(0.728)["observed"] == 0.830
    assert bundles.hit_rate(1.0)["bin"] == [0.9, 1.0]
    assert bundles.hit_rate(0.9)["bin"] == [0.9, 1.0]
    assert bundles.hit_rate(0.49) is None                     # below the threshold nothing is quoted
