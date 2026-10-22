"""FR-031 / research R9: the current model is backed by a comparison record and the model definition (T037)."""

import re
from pathlib import Path

from sweetspot.forecast.models import CURRENT_MODEL, current_model

DOCS = Path(__file__).parents[3] / "docs" / "model"


def _label(name: str, version: str, params: dict) -> str:
    return f"{name} {version} {{{', '.join(f'{k}={v}' for k, v in sorted(params.items()))}}}"


def test_current_model_builds_with_its_declared_version():
    model = current_model()
    name, version, params = CURRENT_MODEL
    assert (model.name, model.version, model.params) == (name, version, dict(params))


def test_comparison_record_adopts_the_current_model():
    text = (DOCS / "comparisons.md").read_text(encoding="utf-8")
    label = _label(*CURRENT_MODEL)
    adopted = False
    for section in re.split(r"\n(?=## )", text):
        heading = section.splitlines()[0]
        candidate = heading.split(" · ", 1)[-1].split(" vs ")[0].replace("（建立下限）", "")
        baseline = "（建立下限）" in heading
        on_validation = "驗證組" in heading                  # 004 spec FR-012: a switch is judged on held-out games
        if candidate.strip() == label and re.search(r"\*\*判定：(優於|建立下限)\*\*", section) \
                and (baseline or on_validation):
            adopted = True
    assert adopted, f"docs/model/comparisons.md 沒有採用 {label} 的紀錄"


def test_model_definition_documents_the_current_version():
    name, version, params = CURRENT_MODEL
    text = (DOCS / "model-definition.md").read_text(encoding="utf-8")
    assert f"`{name}`" in text and f"v{version}" in text
    for key, value in params.items():
        assert f"`{key}` = `{value}`" in text
