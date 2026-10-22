"""Model registry and the current model (research R9).

CURRENT_MODEL changes only with a comparison record judged 優於 in docs/model/comparisons.md; the first model
is set by a 建立下限 record (FR-031).
"""

from collections.abc import Mapping
from typing import Any

from sweetspot.forecast.models.base import Model, ModelOutput

REGISTRY: dict[str, dict[str, type]] = {}        # name → version → class (feature 008 research R4)

__all__ = ["CURRENT_MODEL", "REGISTRY", "Model", "ModelOutput", "build_model", "current_model", "model_class",
           "register", "split_name"]


def register(cls: type) -> type:
    REGISTRY.setdefault(cls.name, {})[cls.version] = cls
    return cls


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def split_name(name: str) -> tuple[str, str | None]:
    """"seasonal-record@1.0.0" → ("seasonal-record", "1.0.0"); a bare name has no version."""
    base, _, version = name.partition("@")
    return base, version or None


def model_class(name: str, version: str | None = None) -> type:
    """The registered class of `name` at `version`. Without a version: the current model's version when `name` is
    the current model (so a bare name keeps meaning what it meant before a new version was added), else the latest."""
    base, at = split_name(name)
    version = version or at
    if version is None and base == CURRENT_MODEL[0]:
        version = CURRENT_MODEL[1]
    versions = REGISTRY.get(base)
    if not versions:
        raise ValueError(f"未知的模型：{base}（可用：{', '.join(sorted(REGISTRY)) or '無'}）")
    if version is None:
        return versions[max(versions, key=_version_key)]
    if version not in versions:
        raise ValueError(f"模型 {base} 沒有版本 {version}（可用：{', '.join(sorted(versions, key=_version_key))}）")
    return versions[version]


def build_model(name: str, params: Mapping[str, Any] | None = None, version: str | None = None) -> Model:
    """Build a registered model (`name` may carry `@version`; default the latest version). String parameter values
    (from the CLI) are converted by the model."""
    return model_class(name, version).from_params(dict(params or {}))


def current_model() -> Model:
    name, version, params = CURRENT_MODEL
    model = build_model(name, params, version)
    if model.version != version:
        raise ValueError(f"CURRENT_MODEL 指定 {name} {version}，但程式中的版本是 {model.version}")
    return model


# Feature 008: seasonal-record 1.1.0 chosen by the tuning grid, 優於 on the validation part (attempt 1, FR-029 plus the
# 0- and 1-sale groups) and adopted by the user on 2026-09-27 (docs/model/comparisons.md). seasonal-record 1.0.0
# {min_sales=1, half_life=2, hazard_history=TW+US} (feature 004) stays registered and can be put back here (008 FR-016);
# seasonal-freq 1.0.0 remains the baseline.
CURRENT_MODEL: tuple[str, str, Mapping[str, Any]] = ("seasonal-record", "1.1.0",
                                                     {"min_sales": 1, "half_life": 2, "hazard_history": "TW+US",
                                                      "low_base": "new-split", "shrink": 0.5})

# Register built-in models (imported for their @register side effect).
from sweetspot.forecast.models import seasonal_freq as _seasonal_freq  # noqa: E402,F401
from sweetspot.forecast.models import seasonal_record as _seasonal_record  # noqa: E402,F401
