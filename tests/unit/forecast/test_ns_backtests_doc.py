"""Every non-seasonal figure the report quotes is in the model definition's non-seasonal section (feature 007 spec
FR-017, SC-007; tasks T034)."""

from pathlib import Path

from sweetspot.forecast import nonseasonal
from sweetspot.forecast.nonseasonal import build_ns_model

DOC = Path(__file__).resolve().parents[3] / "docs" / "model" / "model-definition.md"


def section() -> str:
    text = DOC.read_text(encoding="utf-8")
    start = text.index("## `non-seasonal`")
    end = text.index("\n## ", start + 1)
    return text[start:end]


def test_quoted_figures_are_in_the_model_definition():
    text = section()
    assert nonseasonal.CURRENT_NS_MODEL is not None and nonseasonal.NS_BACKTESTS
    for entry in nonseasonal.NS_BACKTESTS:
        model = build_ns_model(entry["model"]["name"], entry["model"]["params"])
        assert (model.version, dict(model.params)) == (entry["model"]["version"], entry["model"]["params"])
        assert entry["date"] in text and entry["ns_dataset_id"] in text
        for value in (entry["brier"], entry["reference_brier"], *entry["brier_by_horizon"].values()):
            assert f"{value:.4f}" in text, value
        assert f"{entry['earlier_hit_rate'] * 100:.1f}%" in text
        assert f"{entry['earlier_said']:,}" in text and f"{entry['earlier_hit']:,}" in text
        assert entry["source"] == "docs/model/model-definition.md"
    assert nonseasonal.ns_backtest_figures() is nonseasonal.NS_BACKTESTS[0]


def test_constants_are_in_the_model_definition():
    text = section()
    for phrase in ("365 天", "14 天", "強度 20", "0.99", "1 天", "50%", "30／60／90 天"):
        assert phrase in text, phrase
