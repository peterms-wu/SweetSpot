"""Model `non-seasonal` 1.0.0 (feature 007 research R1; contracts/ns-model-api.md).

For each horizon h and level d:
    own share f(h, d): of the start points t in the past 365 days of visible history, the share whose window
        (t, t + h] held a non-seasonal arrival of d (history TW, or TW+US: US before TW tracking started);
    p1 = (w·f + k·b) / (w + k), w = months of history − h/30.44, k = `smoothing`, b = the population share;
        history shorter than h + 30 days: p1 = b (source "population", confidence low);
    clock (`clock`): p = p1 × ratio, the ratio of the population's arrival rate in the game's state (past-year
        promotion count, phase of its typical interval, discounted now, seasonal sale inside the horizon) to the
        rate for its count group alone;
    p = min(p, 0.99), made non-increasing in d and then non-decreasing in h.
Promotion starts for the clock are non-seasonal arrivals from no discount.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sweetspot.forecast.contract import LEVELS
from sweetspot.forecast.nonseasonal import DEFAULT_PARAMS, HORIZONS, LOOKBACK_DAYS, P_CAP, TOL, register_ns
from sweetspot.forecast.nonseasonal.evidence import (HISTORIES, MIN_EXTRA_DAYS, NSBasis, NSEvidence, NSPopulation,
                                                     basis, clock_state)
from sweetspot.forecast.nonseasonal.events import window_fraction

MONTH_DAYS = 30.44


@dataclass(frozen=True)
class NSOutput:
    probabilities: tuple[tuple[float, ...], ...]      # [h][d], h in HORIZONS, d in LEVELS
    confidence: str                                   # normal | low
    sources: tuple[str, ...]                          # per h: own | population
    basis: NSBasis
    factors: Mapping[str, Any] = field(default_factory=dict)


def _bool(value) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    raise ValueError(f"clock 必須是 true 或 false：{value!r}")


@register_ns
class NonSeasonal:
    name = "non-seasonal"
    version = "1.0.0"

    def __init__(self, smoothing: int = DEFAULT_PARAMS["smoothing"], history: str = DEFAULT_PARAMS["history"],
                 clock: bool = DEFAULT_PARAMS["clock"]):
        if not isinstance(smoothing, int) or isinstance(smoothing, bool) or smoothing <= 0:
            raise ValueError(f"smoothing 必須是正整數：{smoothing!r}")
        if history not in HISTORIES:
            raise ValueError(f"history 必須是 {', '.join(HISTORIES)} 之一：{history!r}")
        self.smoothing, self.history, self.clock = smoothing, history, bool(clock)
        self.population: NSPopulation | None = None

    @property
    def params(self) -> dict[str, Any]:
        return {"smoothing": self.smoothing, "history": self.history, "clock": self.clock}

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "NonSeasonal":
        unknown = set(params) - set(DEFAULT_PARAMS)
        if unknown:
            raise ValueError(f"non-seasonal 沒有這些參數：{', '.join(sorted(unknown))}")
        values = dict(DEFAULT_PARAMS) | dict(params)
        try:
            smoothing = int(values["smoothing"])
        except (TypeError, ValueError):
            raise ValueError(f"smoothing 必須是正整數：{values['smoothing']!r}") from None
        return cls(smoothing, str(values["history"]), _bool(values["clock"]))

    def confidence_levels(self) -> dict[str, str]:
        return {"normal": f"本身的價格歷史至少 {max(HORIZONS) + MIN_EXTRA_DAYS} 天，每個期間都用本身的紀錄",
                "low": "價格歷史太短，至少一個期間改用所有遊戲的整體比例"}

    def prepare(self, population: NSPopulation) -> None:
        self.population = population

    def predict(self, ev: NSEvidence) -> NSOutput:
        pop = self.population
        if pop is None or pop.as_of != ev.as_of:
            raise ValueError("prepare() 必須在同一個分析時點先呼叫")
        start = max(ev.history_start, ev.as_of - timedelta(days=LOOKBACK_DAYS))
        span = (ev.known_until - start).days
        times = {d: [a.at for a in ev.arrivals if a.reaches(d) and a.at > start] for d in LEVELS}
        ratios = [1.0] * len(HORIZONS)
        kg = phase = None
        if self.clock and pop.clock is not None:
            kg, phase = clock_state([a.at for a in ev.arrivals if a.from_cut == 0], ev.as_of)
            for i, h in enumerate(HORIZONS):
                end = ev.as_of + timedelta(days=h)
                seasonal = any(s - TOL < end and ev.as_of < e for s, e in ev.seasonal_ahead)
                ratios[i] = pop.clock.ratio(h, kg, phase, ev.discounted_now, seasonal)
        rows, sources = [], []
        for i, h in enumerate(HORIZONS):
            own = span >= h + MIN_EXTRA_DAYS
            sources.append("own" if own else "population")
            w = max(span / MONTH_DAYS - h / MONTH_DAYS, 0.0)
            row, floor = [], 1.0
            for d in LEVELS:
                b = pop.share.get((h, d), 0.0)
                if own:
                    f = window_fraction(times[d], start, ev.known_until, h) or 0.0
                    p1 = (w * f + self.smoothing * b) / (w + self.smoothing)
                else:
                    p1 = b
                floor = min(floor, min(p1 * ratios[i], P_CAP))           # non-increasing in d
                row.append(floor)
            if rows:
                row = [max(a, b) for a, b in zip(row, rows[-1])]        # non-decreasing in h
            rows.append(tuple(row))
        confidence = "normal" if all(s == "own" for s in sources) else "low"
        factors = {"clock_ratio": ratios, "history_months": round(span / MONTH_DAYS, 2), "kgroup": kg,
                   "phase": phase}
        return NSOutput(tuple(rows), confidence, tuple(sources), basis(ev), factors)

