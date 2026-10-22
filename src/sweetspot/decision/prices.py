"""Current TW price, when it was last confirmed, regular-price mismatch (research R3) and discounts outside seasonal
sales that the model does not see (research R4)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sweetspot.decision.rule import STALE_HOURS
from sweetspot.forecast.series import PriceSeries, PriceState
from sweetspot.store.query import OPTION_HISTORY_SOURCE, OptionKey, PriceStore


@dataclass(frozen=True)
class CurrentPrice:
    price_cents: int | None
    regular_cents: int | None
    cut_pct: int | None
    source: str | None
    observed_at: datetime | None
    confirmed_at: datetime | None
    stale: bool
    history_regular_cents: int | None
    regular_mismatch: bool


def current_prices(store: PriceStore, app_ids: Sequence[int], as_of: datetime,
                   history_regular: Mapping[int, int | None],
                   option_keys: Mapping[int, OptionKey] | None = None) -> dict[int, CurrentPrice]:
    """Current price per app. `history_regular` is the regular price of the forecast's ITAD series at as_of.
    Feature 009 (research R5): a chosen edition's price comes from its purchase-option record or its own history,
    whichever is newer; never from the Steam default's snapshot."""
    ids = store.key_ids(store.history_keys(app_ids, as_of))          # feature 006: the version's product
    latest = store.latest_observations(app_ids, "TW", as_of, keys=ids)
    snapshots = store.latest_snapshot_times("TW", as_of)
    known = store.history_known_until_all("TW", keys=ids)
    out = {}
    for app in app_ids:
        obs = latest.get(app)
        history = history_regular.get(app)
        confirmations = [t for t in (snapshots.get(app), known.get(app)) if t is not None]
        confirmed = min(max(confirmations), as_of) if confirmations else None
        stale = confirmed is None or as_of - confirmed > timedelta(hours=STALE_HOURS)
        if obs is None or obs.price_cents is None:
            out[app] = CurrentPrice(None, history if obs else None, None, obs.source if obs else None,
                                    obs.observed_at if obs else None, confirmed if obs else None, True,
                                    history, False)
            continue
        regular = obs.regular_cents if obs.regular_cents is not None else history
        mismatch = obs.regular_cents is not None and history is not None and obs.regular_cents != history
        out[app] = CurrentPrice(obs.price_cents, regular, obs.cut_pct, obs.source, obs.observed_at, confirmed,
                                stale, history, mismatch)
    for app, choice in (option_keys or {}).items():
        if app in out and choice.source == "user" and not choice.same_as_default:
            out[app] = _chosen_price(store, app, choice, as_of, history_regular.get(app))
    return out


def _chosen_price(store: PriceStore, app: int, choice: OptionKey, as_of: datetime,
                  history: int | None) -> CurrentPrice:
    record = choice.record
    rows = store.series_rows([app], "TW", as_of, keys={app: choice.key.external_id},
                             sources=(OPTION_HISTORY_SOURCE,)).get(app, [])
    last = rows[-1] if rows else None
    if last is not None and last.price_cents is not None and last.observed_at > record.checked_at:
        price, regular, cut, source, seen = (last.price_cents, last.regular_cents, last.cut_pct,
                                             OPTION_HISTORY_SOURCE, last.observed_at)
    else:
        price, regular, source, seen = record.final_cents, record.original_cents, "steam-option", record.checked_at
        cut = round(100 - 100 * price / regular) if regular and price < regular else 0
    stale = as_of - seen > timedelta(hours=STALE_HOURS)
    mismatch = regular is not None and history is not None and regular != history
    return CurrentPrice(price, regular if regular is not None else history, cut, source, seen, seen, stale, history,
                        mismatch)


def non_seasonal_deeper(series: PriceSeries, seasonal_windows: Sequence[tuple[datetime, datetime]],
                        own_max_cut: int | None, as_of: datetime) -> PriceState | None:
    """The deepest discount state before as_of that overlaps no seasonal sale, when deeper than the game's own
    seasonal record (no record counts as 0); otherwise None."""
    best = None
    states = [s for s in series.states if s.start <= as_of]
    for i, state in enumerate(states):
        if state.cut <= 0:
            continue
        end = states[i + 1].start if i + 1 < len(states) else as_of
        if any(start < end and state.start < stop for start, stop in seasonal_windows):
            continue
        if best is None or state.cut > best.cut:
            best = state
    if best is None or best.cut <= (own_max_cut or 0):
        return None
    return best
