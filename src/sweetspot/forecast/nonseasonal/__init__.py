"""Non-seasonal forecasts (feature 007; specs/007-non-seasonal-discounts research R1, R3).

A separate family from the seasonal models in `sweetspot.forecast.models`: the output is "within the next h days"
instead of "by the k-th seasonal sale", so the two never share a protocol or a result format.

CURRENT_NS_MODEL stays None until a validation comparison judged 優於 and the user agreed (research R3). Until then
the report shows only the game's past non-seasonal promotions, never probabilities (spec FR-016).
"""

from collections.abc import Mapping
from datetime import timedelta
from typing import Any

HORIZONS = (30, 60, 90)                 # framework setting: days after as_of (spec FR-003)
TOL = timedelta(days=1)                 # structure constant: a change this close before a seasonal start is seasonal
LOOKBACK_DAYS = 365                     # structure constant: own history the model looks at
CLOCK_STEP_DAYS = 14                    # structure constant: clock sample spacing
CLOCK_SMOOTHING = 20                    # structure constant: additive smoothing of the clock table
P_CAP = 0.99                            # structure constant: no probability above this
EARLIER_THRESHOLD = 0.5                 # display constant: "可能更早到價" (user confirmed 2026-09-26)
DEFAULT_PARAMS: Mapping[str, Any] = {"smoothing": 2, "history": "TW+US", "clock": True}

NS_REGISTRY: dict[str, type] = {}

# (name, version, params) once adopted (research R3); None = not adopted. Feature 007: tuning grid, then 優於 on the
# validation part (attempt 1) and adopted by the user on 2026-09-26 (docs/model/comparisons.md).
CURRENT_NS_MODEL: tuple[str, str, Mapping[str, Any]] | None = (
    "non-seasonal", "1.0.0", {"smoothing": 2, "history": "TW+US", "clock": True})

# The figures the report quotes (decision contract non_seasonal.backtest); checked against the model definition.
# 014 T078: run again on 2026-10-22 with the current seasonal model (seasonal-record 1.1.0 since 008): the
# "earlier" decisions come from it, and the first figures were from 1.0.0 (73.6%, dataset 96fe5584, 2,583 games).
NS_BACKTESTS: tuple[dict[str, Any], ...] = (
    {"model": {"name": "non-seasonal", "version": "1.0.0", "params": {"smoothing": 2, "history": "TW+US", "clock": True}},
     "date": "2026-09-25", "split": "all", "ns_dataset_id": "663fa7c5", "games": 2636,
     "brier": 0.1172, "reference_brier": 0.1904,
     "brier_by_horizon": {"30": 0.1069, "60": 0.1302, "90": 0.1191},
     "earlier_threshold": 0.5, "earlier_said": 6903, "earlier_hit": 5168, "earlier_hit_rate": 0.749,
     "seasonal_model": "seasonal-record 1.1.0", "source": "docs/model/model-definition.md"},
)


def register_ns(cls: type) -> type:
    NS_REGISTRY[cls.name] = cls
    return cls


def build_ns_model(name: str, params: Mapping[str, Any] | None = None):
    cls = NS_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"未知的非季節模型：{name}（可用：{', '.join(sorted(NS_REGISTRY)) or '無'}）")
    return cls.from_params(dict(params or {}))


def current_ns_model():
    """The adopted model, or None before adoption."""
    if CURRENT_NS_MODEL is None:
        return None
    name, version, params = CURRENT_NS_MODEL
    model = build_ns_model(name, params)
    if model.version != version:
        raise ValueError(f"CURRENT_NS_MODEL 指定 {name} {version}，但程式中的版本是 {model.version}")
    return model


def ns_backtest_figures() -> dict[str, Any] | None:
    """The figures for the adopted model, or None."""
    if CURRENT_NS_MODEL is None:
        return None
    name, version, params = CURRENT_NS_MODEL
    for entry in NS_BACKTESTS:
        if (entry["model"]["name"], entry["model"]["version"], dict(entry["model"]["params"])) == \
                (name, version, dict(params)):
            return entry
    return None


# Register built-in models (imported for their @register_ns side effect).
from sweetspot.forecast.nonseasonal import model as _model  # noqa: E402,F401
