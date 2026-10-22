"""Model interface (contracts/model-api.md). Models only fill in probabilities; the framework owns the grid,
the evidence, status decisions, validation and scoring."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from sweetspot.forecast.evidence import GameEvidence, PopulationView
from sweetspot.forecast.salepoints import SalePoint


@dataclass(frozen=True)
class ModelOutput:
    probabilities: tuple[tuple[float, ...], ...]      # [point][level], cumulative
    confidence: str                                   # normal | low
    reasons: tuple[str, ...]                          # Traditional Chinese, human readable
    evidence: Mapping[str, Any] = field(default_factory=dict)


class Model(Protocol):
    name: str
    version: str
    params: Mapping[str, Any]
    tw_only_params: frozenset[str]
    predicts_deeper: bool       # can give P > 0 to levels deeper than the game's own past (004 research R9)
    deeper_caveat: str          # "the lowest price may be lower" note; may quote {now_deeper_within_12m}

    def confidence_levels(self) -> Mapping[str, str]:
        """What each confidence level means, written into every forecast batch (constitution IV)."""

    def prepare(self, population: PopulationView) -> None:
        """Called once per (as_of, target region) before predict()."""

    def predict(self, game: GameEvidence, points: Sequence[SalePoint], levels: Sequence[int]) -> ModelOutput:
        """len(points) × len(levels) cumulative probabilities."""
