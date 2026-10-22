"""Store verified price history for the primary region and discount-only history for the aux region.

Auxiliary-region rows keep only discount % and time — never amounts (FR-007a, constitution IX).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sweetspot.sources import HistoryEntry, HistorySource, PriceQuote
from sweetspot.store import schema
from sweetspot.store.writer import NewObservation, StoreWriter
from sweetspot.timeutil import to_db

HISTORY_SOURCE = "itad-history"
HISTORY_FETCH_SOURCE = schema.HISTORY_FETCH_SOURCE      # an edition (feature 009) uses schema.OPTION_FETCH_SOURCE
SINCE = datetime(2010, 1, 1, tzinfo=UTC)   # ask for everything; ITAD returns only 3 months without `since`


@dataclass(frozen=True)
class HistoryIngest:
    entries: int
    new_rows: int


def history_is_fresh(writer: StoreWriter, app_id: int, region: str, now: datetime, max_age: timedelta,
                     external_id: str | None = None, source: str = HISTORY_FETCH_SOURCE) -> bool:
    """With `external_id`, only fetches of that ITAD product count (feature 006): a new version is fetched at once.
    `source` separates the app's own fetches (itad) from an edition's (itad-option, feature 009)."""
    if external_id is None:
        row = writer.conn.execute("SELECT MAX(fetched_at) FROM history_fetches WHERE app_id = ? AND region = ? "
                                  "AND source = ?", (app_id, region, source)).fetchone()
    else:
        row = writer.conn.execute("SELECT MAX(fetched_at) FROM history_fetches WHERE app_id = ? AND region = ? "
                                  "AND external_id = ? AND source = ?", (app_id, region, external_id, source)).fetchone()
    return bool(row[0]) and row[0] >= to_db(now - max_age)


def fetch_state(writer: StoreWriter, app_id: int, region: str) -> str:
    """'not-fetched', 'none' (fetched, no history) or 'available' (FR-022). Edition fetches do not count."""
    row = writer.conn.execute(
        "SELECT COUNT(*), MAX(entries) FROM history_fetches WHERE app_id = ? AND region = ? AND source = ?",
        (app_id, region, HISTORY_FETCH_SOURCE)).fetchone()
    if not row[0]:
        return "not-fetched"
    return "available" if row[1] else "none"


def to_observations(app_id: int, entries: list[HistoryEntry], *, region: str, primary_region: str,
                    retrieved_at: datetime, source: str = HISTORY_SOURCE,
                    external_id: str | None = None) -> list[NewObservation]:
    """The earliest entry of a series is the source's first snapshot: the price was already in that state
    (full price or an ongoing sale), so it is not a price-change event."""
    primary = region == primary_region
    result = []
    for index, entry in enumerate(sorted(entries, key=lambda e: e.observed_at)):
        result.append(NewObservation(
            app_id=app_id, source=source, region=region,
            currency=entry.currency if primary else None,
            regular_cents=entry.regular_cents if primary else None,
            price_cents=entry.price_cents if primary else None,
            cut_pct=entry.cut_pct,
            observed_at=entry.observed_at, raw_observed_at=entry.raw_timestamp, retrieved_at=retrieved_at,
            is_tracking_start=index == 0, external_id=external_id,
        ))
    return result


def ingest_history(writer: StoreWriter, source: HistorySource, *, app_id: int, external_id: str, region: str,
                   primary_region: str, now: datetime, run_id: str, observation_source: str = HISTORY_SOURCE,
                   fetch_source: str = HISTORY_FETCH_SOURCE,
                   clock: Callable[[], datetime] | None = None) -> HistoryIngest:
    """Fetch and store one product's history. Feature 009: an edition is written with observation_source
    itad-option-history and fetch_source itad-option.

    `clock` gives the moment the response arrived (never earlier than `now`); it is the rows' retrieved_at and the
    fetch time. Without it both are `now`, the batch start, and an event ITAD recorded between the batch start and
    this fetch is quarantined as observed-after-retrieved (the 2026 autumn sale's Stellar Blade, 013 research R9)."""
    entries = source.history(external_id, region, SINCE)
    fetched = max(now, clock()) if clock is not None else now
    observations = to_observations(app_id, entries, region=region, primary_region=primary_region,
                                   retrieved_at=fetched, source=observation_source, external_id=external_id)
    with writer.transaction():
        new_rows = writer.add_observations(run_id, observations)
        writer.conn.execute(
            "INSERT INTO history_fetches (app_id, source, region, fetched_at, entries, run_id, external_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (app_id, fetch_source, region, to_db(fetched), len(entries), run_id, external_id),
        )
    return HistoryIngest(len(entries), new_rows)


def record_price_check(writer: StoreWriter, run_id: str, app_id: int, steam: PriceQuote | None,
                       itad: PriceQuote | None, *, now: datetime, external_id: str | None = None,
                       itad_steam_deals: int | None = None) -> bool | None:
    """Keep both current prices; `match` is None when either side is missing (FR-009). Feature 006 also records
    which ITAD product was checked and how many Steam prices ITAD has for it."""
    match = None
    if steam is not None and itad is not None:
        match = (steam.currency, steam.initial_cents, steam.final_cents) == (
            itad.currency, itad.initial_cents, itad.final_cents)
    writer.conn.execute(
        "INSERT INTO current_price_checks (run_id, app_id, steam_price_cents, steam_regular_cents, "
        "itad_price_cents, itad_regular_cents, match, checked_at, external_id, itad_steam_deals) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, app_id, steam.final_cents if steam else None, steam.initial_cents if steam else None,
         itad.final_cents if itad else None, itad.initial_cents if itad else None,
         None if match is None else int(match), to_db(now), external_id, itad_steam_deals),
    )
    return match
