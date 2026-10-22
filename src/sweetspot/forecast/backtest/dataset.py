"""Backtest dataset: games, schedules and per-region identity (research R6; FR-012, FR-028).

A region's dataset_id hashes everything that decides its scoring units and what its target can see, so two
results with the same id were scored on exactly the same units.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sweetspot.calendar import SaleEvent
from sweetspot.forecast.backtest.scoring import WINDOWS
from sweetspot.forecast.backtest.split import SALT, select
from sweetspot.forecast.contract import LEVELS, iso
from sweetspot.forecast.engine import BUNDLE_TYPES, is_paid_at
from sweetspot.forecast.evidence import REGIONS, GameData, visible_regions
from sweetspot.store.query import PriceStore
from sweetspot.timeutil import add_months


@dataclass(frozen=True)
class RegionDataset:
    region: str
    apps: tuple[int, ...]
    schedule: tuple[datetime, ...]
    window: tuple[int, int]
    dataset_id: str
    population_apps: tuple[int, ...] = ()    # games the population share is built from (004 research R4)

    def __post_init__(self):
        if not self.population_apps:
            object.__setattr__(self, "population_apps", self.apps)


@dataclass(frozen=True)
class BacktestDataset:
    cutoff: datetime
    levels: tuple[int, ...]
    calendar_hash: str
    pools: Mapping[int, str]
    regions: Mapping[str, RegionDataset]
    split: str = "all"


def _floor_day(moment: datetime) -> datetime:
    return datetime(moment.year, moment.month, moment.day, tzinfo=UTC)


def _next_month_start(moment: datetime) -> datetime:
    return add_months(datetime(moment.year, moment.month, 1, tzinfo=UTC), 1)


def _month_starts(first: datetime, last: datetime) -> tuple[datetime, ...]:
    out, current = [], first
    while current <= last:
        out.append(current)
        current = add_months(current, 1)
    return tuple(out)


def default_cutoff(store: PriceStore) -> datetime:
    """Latest known-until over all apps and regions, floored to 00:00 UTC (research R6)."""
    latest = [t for r in REGIONS for t in store.history_known_until_all(r).values()]
    if not latest:
        raise ValueError("資料庫中沒有任何 ITAD 歷史，無法回測")
    return _floor_day(max(latest))


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _calendar_rows(events: Sequence[SaleEvent]) -> list:
    return sorted([e.season, e.year, iso(e.start), iso(e.end)] for e in events if e.kind == "seasonal" and e.season)


def _region_id(region: str, apps: Sequence[int], games: Mapping[int, GameData], cutoff: datetime,
               schedule: Sequence[datetime], levels: Sequence[int], window: tuple[int, int], calendar_hash: str,
               split: str = "all", population: Sequence[int] = ()) -> str:
    """With split = all the id is exactly 002's. A tuning/validation id also covers the split and every game the
    population share is built from, since those games change the forecasts (004 research R4)."""
    digest = hashlib.sha256()
    header = {"region": region, "apps": list(apps), "cutoff": iso(cutoff), "schedule": [iso(t) for t in schedule],
              "levels": list(levels), "window": list(window), "calendar": calendar_hash}
    hashed = apps
    if split != "all":
        header.update({"split": split, "salt": SALT, "population": list(population)})
        hashed = population
    digest.update(json.dumps(header, sort_keys=True).encode("utf-8"))
    for app in hashed:
        for r in visible_regions(region):
            series = games[app].series.get(r)
            if series is None:
                continue
            digest.update(f"|{app}|{r}|{iso(series.known_until)}".encode())
            for s in series.states:
                digest.update(f";{iso(s.start)},{s.cut},{int(s.is_tracking_start)},{s.regular_cents}".encode())
    return digest.hexdigest()


def eligible_apps(store: PriceStore, games: Mapping[int, GameData], cutoff: datetime) -> list[int]:
    """TW ITAD history, paid at the cutoff, not a bundle (FR-032)."""
    out = []
    for app in sorted(games):
        g = games[app]
        if "TW" not in g.series or not is_paid_at(g, cutoff):
            continue
        if store.facts(app, cutoff).product_type.value in BUNDLE_TYPES:
            continue
        out.append(app)
    return out


def build_dataset(store: PriceStore, games: Mapping[int, GameData], events: Sequence[SaleEvent], *,
                  cutoff: datetime, regions: Sequence[str] = REGIONS, apps_limit: int | None = None,
                  levels: Sequence[int] = LEVELS, windows: Mapping[str, tuple[int, int]] = WINDOWS,
                  split: str = "all") -> BacktestDataset:
    eligible = eligible_apps(store, games, cutoff)
    apps = list(select(eligible, split))
    if apps_limit is not None:
        apps = apps[:apps_limit]
    if split == "all":
        eligible = apps                      # 002 behaviour: the population is the scored games
    pools_all = store.sample_pools()
    pools = {a: pools_all.get(a, "legacy") for a in apps}
    calendar_hash = _sha(_calendar_rows(events))
    out = {}
    for region in regions:
        region_apps = tuple(a for a in apps if region in games[a].series)
        population = tuple(a for a in eligible if region in games[a].series)
        ends = [o.end for a in population for o in games[a].outcomes.get(region, ())]
        window = tuple(windows[region])
        if ends:
            last = cutoff if window[0] == 0 else add_months(cutoff, -window[0])
            last = datetime(last.year, last.month, 1, tzinfo=UTC)
            if last == cutoff:                        # a month start equal to the cutoff has nothing to score
                last = add_months(last, -1)
            schedule = _month_starts(_next_month_start(min(ends)), last)
        else:
            schedule = ()
        out[region] = RegionDataset(
            region, region_apps, schedule, window,
            _region_id(region, region_apps, games, cutoff, schedule, levels, window, calendar_hash, split, population),
            population)
    return BacktestDataset(cutoff, tuple(levels), calendar_hash, pools, out, split)
