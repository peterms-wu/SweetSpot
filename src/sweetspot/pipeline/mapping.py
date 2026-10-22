"""Resolve and verify each app's external history id, reusing recent decisions (FR-008, cache.mapping_days).

Requests are batched: ITAD id lookups and reverse lookups for many apps at once (CachedHistory), and every
package that needs checking is fetched in one GetItems call per 50 packages instead of one store request each.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sweetspot.pipeline.metadata import DetailsCache
from sweetspot.pipeline.verify import verify_mapping
from sweetspot.sources import HistoryEntry, HistorySource, MetadataSource, PackageDetails, PriceQuote
from sweetspot.store.writer import StoreWriter
from sweetspot.timeutil import to_db

SOURCE = "itad"


@dataclass(frozen=True)
class Mapping:
    app_id: int
    external_id: str | None
    verification: str
    reason_code: str | None
    reused: bool


class CachedHistory:
    """HistorySource wrapper that remembers id and alias lookups, so callers can prefetch them in batches."""

    def __init__(self, source: HistorySource):
        self.source = source
        self._ids: dict[int, str | None] = {}
        self._aliases: dict[str, list[str]] = {}

    def prefetch(self, app_ids: list[int]) -> None:
        missing = [a for a in dict.fromkeys(app_ids) if a not in self._ids]
        if not missing:
            return
        self._ids.update(self.source.lookup_steam(missing))
        found = [e for a in missing if (e := self._ids.get(a)) and e not in self._aliases]
        if found:
            self._aliases.update(self.source.reverse_lookup(found))

    def knows(self, app_id: int) -> bool:
        return app_id in self._ids

    def lookup_steam(self, app_ids: list[int]) -> dict[int, str | None]:
        self.prefetch(app_ids)
        return {a: self._ids.get(a) for a in app_ids}

    def reverse_lookup(self, external_ids: list[str]) -> dict[str, list[str]]:
        missing = [e for e in external_ids if e not in self._aliases]
        if missing:
            self._aliases.update(self.source.reverse_lookup(missing))
        return {e: self._aliases.get(e, []) for e in external_ids}

    def history(self, external_id: str, country: str, since: datetime) -> list[HistoryEntry]:
        return self.source.history(external_id, country, since)

    def current_prices(self, external_ids: list[str], country: str) -> dict[str, PriceQuote | None]:
        return self.source.current_prices(external_ids, country)


class _PrefetchedPackages:
    """MetadataSource view for verify_mapping that answers package questions from one batched fetch."""

    def __init__(self, metadata: MetadataSource, packages: dict[int, PackageDetails | None]):
        self._metadata = metadata
        self._packages = packages

    def package_details(self, package_id: int) -> PackageDetails | None:
        if package_id not in self._packages:
            self._packages.update(self._metadata.package_details_batch([package_id]))
        return self._packages.get(package_id)

    def canonical_app_id(self, app_id: int) -> int | None:
        return self._metadata.canonical_app_id(app_id)


def latest_mapping(writer: StoreWriter, app_id: int) -> tuple | None:
    return writer.conn.execute(
        "SELECT external_id, verification, reason_code, checked_at FROM source_mappings "
        "WHERE app_id = ? AND source = ? ORDER BY checked_at DESC, mapping_id DESC LIMIT 1",
        (app_id, SOURCE)).fetchone()


def resolve_mappings(writer: StoreWriter, history: HistorySource, metadata: MetadataSource,
                     details_cache: DetailsCache, apps: list[int], quotes: dict[int, PriceQuote | None], *,
                     run_id: str, now: datetime, max_age: timedelta) -> dict[int, Mapping]:
    result: dict[int, Mapping] = {}
    stale = []
    for app_id in apps:
        row = latest_mapping(writer, app_id)
        if row and row[3] >= to_db(now - max_age) and row[1] in ("verified", "verified-legacy", "rejected"):
            result[app_id] = Mapping(app_id, row[0], row[1], row[2], reused=True)
        else:
            stale.append(app_id)
    if not stale:
        return result

    external = history.lookup_steam(stale)
    found = [e for e in external.values() if e]
    aliases = history.reverse_lookup(found) if found else {}
    alias_lists = {a: aliases.get(external[a], []) if external.get(a) else [] for a in stale}
    subs = sorted({int(x[4:]) for lst in alias_lists.values() for x in lst
                   if x.startswith("sub/") and x[4:].isdigit()})
    packages = _PrefetchedPackages(metadata, metadata.package_details_batch(subs) if subs else {})
    for app_id in stale:
        alias_list = alias_lists[app_id]
        needs_packages = any(a.startswith("sub/") for a in alias_list)
        details = details_cache.get(app_id) if needs_packages else None
        verdict = verify_mapping(app_id, alias_list, quote=quotes.get(app_id),
                                 current_packages=details.package_ids if details else [], metadata=packages)
        with writer.transaction():
            writer.add_mapping(run_id, app_id, SOURCE, external.get(app_id), verdict.verification, checked_at=now,
                               reason_code=verdict.reason_code, warnings=verdict.warnings, aliases=alias_list)
        result[app_id] = Mapping(app_id, external.get(app_id), verdict.verification, verdict.reason_code,
                                 reused=False)
    return result
