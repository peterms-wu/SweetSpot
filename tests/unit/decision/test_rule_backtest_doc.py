"""Every rule-backtest figure the report may quote must be in the model definition document (003 T036; FR-034;
004 research R9: one entry per rule + model combination)."""

from pathlib import Path

from sweetspot.decision.rule import RULE_BACKTESTS, RULES
from sweetspot.forecast.models import build_model

DOC = Path(__file__).resolve().parents[3] / "docs" / "model" / "model-definition.md"


def test_every_quoted_figure_is_in_the_model_definition():
    text = DOC.read_text(encoding="utf-8")
    assert RULE_BACKTESTS and "### 規則回測" in text
    for entry in RULE_BACKTESTS:
        assert entry["rule"] in RULES and entry["date"] in text
        model = build_model(entry["model"]["name"], entry["model"]["params"], entry["model"]["version"])
        assert (model.version, dict(model.params)) == (entry["model"]["version"], entry["model"]["params"])
        for value in (*entry["hit_rate"].values(), entry["now_deeper_within_12m"]):
            assert f"{value * 100:.1f}%" in text, (entry["rule"], entry["model"]["name"], value)
        assert entry["source"] == "docs/model/model-definition.md"
