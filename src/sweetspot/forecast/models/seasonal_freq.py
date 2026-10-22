"""Baseline model `seasonal-freq` (docs/model/model-definition.md; research R5).

p(d) = share of the product's ended seasonal sales whose max cut reached d. Cumulative probability at the k-th
future seasonal sale = 1 - (1 - p(d))^k (sales treated as independent). With fewer than `min_sales` own sales,
p(d) is the population share over all ended seasonal sales (each sale weighted equally) and confidence is low.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from sweetspot.forecast.evidence import GameEvidence, PopulationView
from sweetspot.forecast.models import register
from sweetspot.forecast.models.base import ModelOutput
from sweetspot.forecast.salepoints import SalePoint
from sweetspot.forecast.series import SaleOutcome

HISTORIES = ("TW", "TW+US")
REGION_ZH = {"TW": "台灣區", "US": "美國區（只用折扣百分比）"}


@register
class SeasonalFreq:
    name = "seasonal-freq"
    version = "1.0.0"
    tw_only_params = frozenset({"history"})
    predicts_deeper = False
    deeper_caveat = "長期最低價可能更低：目前的模型無法預測比過去更深的折扣"

    def __init__(self, min_sales: int = 1, history: str = "TW"):
        if not isinstance(min_sales, int) or isinstance(min_sales, bool) or min_sales < 1:
            raise ValueError(f"min_sales 必須是 ≥ 1 的整數：{min_sales!r}")
        if history not in HISTORIES:
            raise ValueError(f"history 必須是 {HISTORIES} 之一：{history!r}")
        self.min_sales = min_sales
        self.history = history
        self._pool: tuple[int, list[int]] | None = None

    @classmethod
    def from_params(cls, raw: Mapping[str, Any]) -> "SeasonalFreq":
        unknown = set(raw) - {"min_sales", "history"}
        if unknown:
            raise ValueError(f"seasonal-freq 沒有這些參數：{', '.join(sorted(unknown))}")
        kwargs: dict[str, Any] = {}
        if "min_sales" in raw:
            try:
                kwargs["min_sales"] = int(raw["min_sales"])
            except (TypeError, ValueError):
                raise ValueError(f"min_sales 必須是整數：{raw['min_sales']!r}") from None
        if "history" in raw:
            kwargs["history"] = str(raw["history"])
        return cls(**kwargs)

    @property
    def params(self) -> dict[str, Any]:
        return {"min_sales": self.min_sales, "history": self.history}

    def confidence_levels(self) -> dict[str, str]:
        n = self.min_sales
        return {
            "normal": f"本身至少有 {n} 場已結束的季節特賣紀錄，用本身的經驗頻率",
            "low": f"本身已結束的季節特賣紀錄少於 {n} 場，改用參考資料集的整體比例",
        }

    # --- history -----------------------------------------------------------------------------

    def _history(self, sale_history: Mapping[str, Sequence[SaleOutcome]], target: str) -> list[SaleOutcome]:
        """US targets always use US only; TW targets use TW, plus US for sales TW does not cover (TW+US)."""
        if target == "US":
            return list(sale_history.get("US", ()))
        tw = list(sale_history.get("TW", ()))
        if self.history == "TW":
            return tw
        covered = {o.sale_key for o in tw}
        merged = tw + [o for o in sale_history.get("US", ()) if o.sale_key not in covered]
        return sorted(merged, key=lambda o: o.start)

    # --- model interface ---------------------------------------------------------------------

    def prepare(self, population: PopulationView) -> None:
        counts = [0] * 101
        total = 0
        for history in population.sale_history.values():
            for o in self._history(history, population.target_region):
                counts[o.max_cut] += 1
                total += 1
        at_least = [0] * 102
        for cut in range(100, -1, -1):
            at_least[cut] = at_least[cut + 1] + counts[cut]
        self._pool = (total, at_least)

    def predict(self, game: GameEvidence, points: Sequence[SalePoint], levels: Sequence[int]) -> ModelOutput:
        own = self._history(game.sale_history, game.target_region)
        regions = sorted({o.region for o in own}, key=["TW", "US"].index)
        if len(own) >= self.min_sales:
            shares = [sum(o.max_cut >= d for o in own) / len(own) for d in levels]
            confidence, population_sales = "normal", None
            reasons = self._own_reasons(own, regions)
        else:
            if self._pool is None:
                raise ValueError("prepare() 必須在 predict() 之前呼叫")
            total, at_least = self._pool
            if total == 0:
                raise ValueError("資料庫中沒有任何已結束的季節特賣，無法估計")
            shares = [at_least[d] / total for d in levels]
            confidence, population_sales = "low", total
            reasons = (f"本身只有 {len(own)} 場已結束的季節特賣紀錄，少於門檻 {self.min_sales} 場，"
                       f"改用參考資料集的整體比例（{total} 場季節特賣）",)
        probabilities = tuple(tuple(1.0 - (1.0 - p) ** k for p in shares) for k in range(1, len(points) + 1))
        evidence = {
            "regions": regions,
            "sales_used": len(own),
            "first_sale": own[0].label if own else None,
            "last_sale": own[-1].label if own else None,
            "max_cut": max((o.max_cut for o in own), default=None),
            "population_sales": population_sales,
        }
        return ModelOutput(probabilities, confidence, reasons, evidence)

    def _own_reasons(self, own: list[SaleOutcome], regions: list[str]) -> tuple[str, ...]:
        by_region = "、".join(f"{REGION_ZH[r]} {sum(o.region == r for o in own)} 場" for r in regions)
        best = max(o.max_cut for o in own)
        reached = sum(o.max_cut >= best for o in own)
        half = sum(o.max_cut >= 50 for o in own)
        return (
            f"依本身的季節特賣紀錄：{by_region}（{own[0].label}–{own[-1].label}）",
            f"過去最大折扣 -{best}%（{len(own)} 場中 {reached} 場達到）；{half} 場達到 -50% 以上",
            "假設未來每場季節特賣達到各折扣的機率與過去相同，且各場獨立",
        )
