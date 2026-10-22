"""Future seasonal-sale points of a forecast curve (research R2).

Points are the seasonal sales that start after as_of, up to as_of + horizon. Known sales come from
PriceStore.sales(as_of), which only returns announced future sales when as_of is the present; every other
(season, year) is estimated from earlier sales with calendar.estimate_sale(), so a backtest never sees a date
announced after its as_of (FR-010).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sweetspot.calendar import SEASONS, SaleEvent, estimate_sale, label
from sweetspot.timeutil import add_months

HORIZON_MONTHS = 60          # framework setting: longest horizon that can be backtested (US 1-5 years)
ACTIVE_SEASON_MONTHS = 18    # framework setting: a season counts as running if held within this window


@dataclass(frozen=True)
class SalePoint:
    index: int                # 1 = the first seasonal sale that starts after as_of
    season: str
    year: int
    label: str                # "2027 春特"
    start: datetime
    end: datetime
    status: str               # announced | estimated
    basis: dict | None        # estimate basis; None when announced

    @property
    def sale_key(self) -> tuple[str, int]:
        return (self.season, self.year)


def sale_points(events: Sequence[SaleEvent], as_of: datetime,
                horizon_months: int = HORIZON_MONTHS) -> tuple[SalePoint, ...]:
    """`events` are the sales known at as_of (past ones, plus announced future ones when as_of is now)."""
    seasonal = [e for e in events if e.kind == "seasonal" and e.season]
    horizon = add_months(as_of, horizon_months)
    active_since = add_months(as_of, -ACTIVE_SEASON_MONTHS)
    active = {e.season for e in seasonal if e.start >= active_since}
    known = {(e.season, e.year): e for e in seasonal}
    reference = [e for e in seasonal if e.status != "estimated"]
    chosen: list[SaleEvent] = []
    for year in range(as_of.year - 1, horizon.year + 1):
        for season in SEASONS:
            if season not in active:
                continue
            event = known.get((season, year))
            if event is None:
                event = estimate_sale(reference, season, year)
                if event is None:
                    continue
                if event.end <= as_of:          # estimate already over although the sale never started
                    continue
            elif event.start <= as_of:          # held or running: the running sale is the current price
                continue
            if event.end <= horizon:
                chosen.append(event)
    chosen.sort(key=lambda e: e.start)
    return tuple(
        SalePoint(index=i, season=e.season, year=e.year, label=label(e), start=e.start, end=e.end,
                  status="estimated" if e.status == "estimated" else "announced",
                  basis=e.basis if e.status == "estimated" else None)
        for i, e in enumerate(chosen, 1))


def future_sale_points(store, as_of: datetime, horizon_months: int = HORIZON_MONTHS) -> tuple[SalePoint, ...]:
    return sale_points(store.sales(as_of, include_estimates=False), as_of, horizon_months)
