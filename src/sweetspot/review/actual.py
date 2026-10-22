"""What a seasonal sale actually did to the product a record followed (feature 013 research R1, R2; FR-004–FR-006).

The series is the one the record's decision read: the version's ITAD product, or the user's edition history. A sale
the series does not cover is unknown, never 0% (constitution I). D1: a level counts as reached when the sale's
deepest cut reaches it (primary) and, for comparison with the backtest, when the cut first moves from below to at or
above it after as_of and before the sale ends (secondary). D2: the tracked purchase option's daily rows can deepen
what the history shows.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from sweetspot.calendar import SaleEvent
from sweetspot.forecast.contract import LEVELS
from sweetspot.forecast.series import PriceSeries, build_series, sale_outcomes
from sweetspot.store.query import ITAD_SOURCES, OPTION_HISTORY_SOURCE, Observation, OptionRecord, PriceStore


@dataclass(frozen=True)
class Tracked:
    """The series a record's decision followed, or why there is none."""
    itad_id: str | None
    basis: str                          # default | user
    option: dict | None                 # the purchase option {kind, id, name} the record followed
    series: PriceSeries | None
    rows: tuple[Observation, ...]
    known_until: datetime | None
    reason: str | None                  # set when the sale cannot be compared (status no-actual)
    version_changed: bool = False       # Steam's default option moved to another product after the record


def _day(moment: datetime | None) -> str:
    return "（不明）" if moment is None else f"{moment:%Y-%m-%d}"


def tracked_series(store: PriceStore, decision: dict[str, Any], sale: SaleEvent, today: datetime) -> Tracked:
    app = decision["app_id"]
    version = decision.get("version") or {}
    itad_id = version.get("itad_id")
    user = version.get("source") == "user"
    basis = "user" if user else "default"
    option = version.get("option")
    if not itad_id:
        return Tracked(None, basis, option, None, (), None, "紀錄沒有追蹤的 ITAD 商品")
    sources = (OPTION_HISTORY_SOURCE,) if user else ITAD_SOURCES
    rows = tuple(store.series_rows([app], "TW", today, keys={app: itad_id}, sources=sources).get(app, []))
    known = store.history_known_until_all("TW", keys={app: itad_id}, apps=(app,)).get(app)
    if known is not None:
        known = min(known, today)
    changed = False
    if not user:
        current = store.history_keys([app], today).get(app)
        changed = current is not None and current.external_id not in (None, itad_id)
    series = build_series(list(rows), "TW", known)
    reason = None
    if not series.states:
        reason = "指定的版本沒有自己的價格歷史" if user else "沒有價格序列"
    elif series.states[0].start > sale.start:
        reason = f"價格序列從 {_day(series.states[0].start)} 才開始，沒有涵蓋特賣開始"
    elif known is None or known < sale.end:
        reason = f"價格歷史只到 {_day(known)}"
    return Tracked(itad_id, basis, option, series, rows, known, reason, changed)


@dataclass(frozen=True)
class SaleActual:
    max_cut: int                         # deepest cut in effect during [start, end) (after D2)
    min_cents: int | None                # lowest TWD price in effect during the sale
    running_cut_at_as_of: int | None     # the cut already running when the record was made
    crossings: dict[int, datetime | None] = field(repr=False)   # first move from < d to >= d after as_of
    sale_end: datetime = field(repr=False)
    regular_changed: bool = False
    history_max_cut: int | None = None   # the price history's own deepest cut (differs from max_cut when corrected)
    daily_max_cut: int | None = None     # the tracked option's daily rows during the sale (D2)
    daily_min_cents: int | None = None
    corrected: bool = False              # the daily rows were deeper and replaced the history's numbers
    noted: bool = False                  # the history was deeper than the daily rows (normal; noted only)

    def sale_max(self, level: int) -> bool:
        return self.max_cut >= level

    def crossing(self, level: int) -> bool:
        t = self.crossings.get(level)
        return t is not None and t < self.sale_end


def _price_in_sale(rows, sale: SaleEvent) -> int | None:
    """Lowest price_cents among the state in effect at the start and the states that begin during the sale."""
    best, at_start = None, None
    for o in rows:
        if o.observed_at <= sale.start:
            at_start = o
        elif o.observed_at < sale.end and o.price_cents is not None:
            best = o.price_cents if best is None else min(best, o.price_cents)
    if at_start is not None and at_start.price_cents is not None:
        best = at_start.price_cents if best is None else min(best, at_start.price_cents)
    return best


def sale_actual(tracked: Tracked, sale: SaleEvent, as_of: datetime) -> SaleActual:
    """Only for a tracked series that covers the sale (tracked.reason is None)."""
    series = tracked.series
    outcome = sale_outcomes(series, [sale])
    if not outcome:
        raise ValueError("價格序列沒有涵蓋這場特賣")
    running = series.state_at(as_of)
    in_sale = [series.state_at(sale.start)] + [s for s in series.states if sale.start < s.start < sale.end]
    regulars = {s.regular_cents for s in in_sale if s.regular_cents is not None}
    return SaleActual(max_cut=outcome[0].max_cut, history_max_cut=outcome[0].max_cut,
                      min_cents=_price_in_sale(tracked.rows, sale),
                      running_cut_at_as_of=running.cut if running else None,
                      crossings=series.first_crossings(as_of, LEVELS), sale_end=sale.end,
                      regular_changed=len(regulars) > 1)


def option_cut(row: OptionRecord) -> int | None:
    if not row.original_cents or row.final_cents is None:
        return None
    return round(100 * (row.original_cents - row.final_cents) / row.original_cents)


def cross_check(actual: SaleActual, steps: list[OptionRecord]) -> SaleActual:
    """D2: compare with the tracked option's daily rows during the sale (whole-sale deepest cut, not day by day).
    Deeper daily rows replace the history's numbers (corrected); a deeper history is normal and only noted."""
    cuts = [(row.checked_at, c) for row in steps if (c := option_cut(row)) is not None]
    if not cuts:
        return actual
    daily_max = max(c for _, c in cuts)
    daily_min = min(row.final_cents for row in steps if row.final_cents is not None)
    out = replace(actual, daily_max_cut=daily_max, daily_min_cents=daily_min)
    if daily_max > actual.max_cut:
        running = actual.running_cut_at_as_of or 0
        crossings = dict(actual.crossings)
        for d in LEVELS:
            if running < d <= daily_max and not actual.crossing(d):
                crossings[d] = next(t for t, c in cuts if c >= d)
        low = daily_min if actual.min_cents is None else min(actual.min_cents, daily_min)
        return replace(out, max_cut=daily_max, min_cents=low, crossings=crossings, corrected=True)
    if daily_max < actual.max_cut:
        return replace(out, noted=True)
    return out
