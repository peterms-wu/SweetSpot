"""What a model may see at as_of (research R3; contracts/model-api.md guarantees 1-2).

Everything handed to a model is truncated to as_of: price series (with known_until capped at as_of) and the
outcomes of seasonal sales that had *ended* by as_of. A US target sees only US data.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sweetspot.forecast.series import PriceSeries, SaleOutcome

REGIONS = ("TW", "US")


def visible_regions(target_region: str) -> tuple[str, ...]:
    if target_region == "TW":
        return ("TW", "US")
    if target_region == "US":
        return ("US",)
    raise ValueError(f"未知的目標區域：{target_region!r}")


@dataclass(frozen=True)
class GameData:
    """Everything loaded for one app up to the data cutoff. Only the framework holds this; models get views."""

    app_id: int
    series: Mapping[str, PriceSeries]
    outcomes: Mapping[str, tuple[SaleOutcome, ...]]
    release_date: date | None = None          # static fact; None = unknown (feature 008 research R3)


@dataclass(frozen=True)
class GameEvidence:
    app_id: int
    as_of: datetime
    target_region: str
    series: Mapping[str, PriceSeries]
    sale_history: Mapping[str, tuple[SaleOutcome, ...]]
    facts_loader: Callable[[], Any] | None = field(default=None, compare=False, repr=False)
    release_date: date | None = None          # the target's release date (static fact; feature 008)

    @property
    def facts(self) -> Any:
        """ProductFacts at as_of, loaded on first use (most models never need it)."""
        return None if self.facts_loader is None else self.facts_loader()


@dataclass(frozen=True)
class PopulationView:
    as_of: datetime
    target_region: str
    sale_history: Mapping[int, Mapping[str, tuple[SaleOutcome, ...]]]
    release_dates: Mapping[int, date | None] = field(default_factory=dict)   # every game given (feature 008)


def _ended(outcomes: Iterable[SaleOutcome], as_of: datetime) -> tuple[SaleOutcome, ...]:
    return tuple(o for o in outcomes if o.end <= as_of)


def game_evidence(data: GameData, as_of: datetime, target_region: str,
                  facts_loader: Callable[[], Any] | None = None) -> GameEvidence:
    regions = visible_regions(target_region)
    return GameEvidence(
        app_id=data.app_id, as_of=as_of, target_region=target_region,
        series={r: data.series[r].truncate(as_of) for r in regions if r in data.series},
        sale_history={r: _ended(data.outcomes.get(r, ()), as_of) for r in regions},
        facts_loader=facts_loader, release_date=data.release_date)


def population_view(games: Iterable[GameData], as_of: datetime, target_region: str) -> PopulationView:
    regions = visible_regions(target_region)
    history, releases = {}, {}
    for g in games:
        releases[g.app_id] = g.release_date
        visible = {r: _ended(g.outcomes.get(r, ()), as_of) for r in regions}
        if any(visible.values()):
            history[g.app_id] = visible
    return PopulationView(as_of, target_region, history, releases)
