"""Product metadata as append-only facts (FR-005; data-model §3)."""

from datetime import datetime, timedelta

from sweetspot.sources import AppDetails, MetadataSource
from sweetspot.products import is_indie, product_type
from sweetspot.store.writer import StoreWriter
from sweetspot.timeutil import to_db

STATIC_MARKER = "name"               # every static refresh writes this field
VOLATILE_MARKER = "review_count_total"


def fact_is_fresh(writer: StoreWriter, app_id: int, field: str, now: datetime, max_age: timedelta) -> bool:
    row = writer.conn.execute(
        "SELECT MAX(retrieved_at) FROM product_facts WHERE app_id = ? AND field = ?", (app_id, field)).fetchone()
    return bool(row[0]) and row[0] >= to_db(now - max_age)


def has_known_data(writer: StoreWriter, app_id: int) -> bool:
    """True when we hold facts or prices for the app — used to tell 'delisted' from 'not-found'."""
    return writer.conn.execute(
        "SELECT EXISTS(SELECT 1 FROM product_facts WHERE app_id = ?) "
        "OR EXISTS(SELECT 1 FROM price_observations WHERE app_id = ?)", (app_id, app_id)).fetchone()[0] == 1


def static_facts(details: AppDetails) -> dict:
    if details.coming_soon:
        release_state = "coming_soon"
    elif details.coming_soon is False:
        release_state = "released"
    else:
        release_state = "unknown"
    return {
        "name": details.name,
        "product_type": product_type(details.type, details.parent_app_id),
        "parent_app_id": details.parent_app_id,
        "publishers": details.publishers,
        "developers": details.developers,
        "release_date": details.release_date.isoformat() if details.release_date else None,
        "release_state": release_state,
        "genres": details.genres,
        "is_indie": is_indie(details.genres),
        "is_free": details.is_free,
    }


class DetailsCache:
    """Fetch each app's store details at most once per run."""

    def __init__(self, source: MetadataSource):
        self.source = source
        self._cache: dict[int, AppDetails | None] = {}

    def get(self, app_id: int) -> AppDetails | None:
        if app_id not in self._cache:
            self._cache[app_id] = self.source.app_details(app_id)
        return self._cache[app_id]


def refresh_static(writer: StoreWriter, details_cache: DetailsCache, app_id: int, *, run_id: str,
                   now: datetime, max_age: timedelta) -> str:
    """Returns 'reused', 'ok' or 'not-found'."""
    if fact_is_fresh(writer, app_id, STATIC_MARKER, now, max_age):
        return "reused"
    details = details_cache.get(app_id)
    if details is None:
        return "not-found"
    with writer.transaction():
        writer.add_facts(run_id, app_id, static_facts(details), source="steam-appdetails", retrieved_at=now)
    return "ok"


def refresh_volatile(writer: StoreWriter, source: MetadataSource, app_ids: list[int], *, run_id: str,
                     now: datetime, max_age: timedelta, progress=None) -> list[int]:
    """Refresh review counts and tags for apps whose volatile facts are stale; returns refreshed ids."""
    stale = [a for a in app_ids if not fact_is_fresh(writer, a, VOLATILE_MARKER, now, max_age)]
    items = source.item_summaries(stale) if stale else {}
    for n, app_id in enumerate(stale, 1):
        if progress:
            progress.step("評論數", n, len(stale))
        summary = source.review_summary(app_id)
        item = items.get(app_id)
        with writer.transaction():
            writer.add_facts(run_id, app_id,
                             {"review_count_total": summary.total_reviews if summary else None},
                             source="steam-appreviews", retrieved_at=now)
            if item:
                writer.add_facts(run_id, app_id, {"review_count_filtered": item.review_count_filtered,
                                                  "review_percent_positive": item.percent_positive,
                                                  "tags": item.tag_ids},
                                 source="steam-getitems", retrieved_at=now)
    return stale
