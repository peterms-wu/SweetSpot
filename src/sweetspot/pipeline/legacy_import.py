"""Import raw data from the legacy SteamSage cache; re-running adds nothing (FR-019, FR-020, SC-005)."""

from collections import Counter
from datetime import datetime
from typing import Any

from sweetspot.pipeline.history import to_observations
from sweetspot.pipeline.metadata import static_facts
from sweetspot.sources.legacy_cache import (LegacyCache, LegacyCatalog, LegacyHistory, LegacyMapping,
                                            LegacyMetadata, LegacySkip)
from sweetspot.store.query import single_own_id
from sweetspot.store.writer import StoreWriter
from sweetspot.timeutil import to_db

SOURCE = "legacy-import"
OBSERVATION_SOURCE = "legacy-itad"
CATALOG_SAMPLE_VERSION = "legacy-catalog-v3"


def _mapping(writer: StoreWriter, run_id: str, record: LegacyMapping) -> bool:
    exists = writer.conn.execute(
        "SELECT 1 FROM source_mappings WHERE app_id = ? AND source = 'itad' AND external_id = ? "
        "AND verification = 'verified-legacy' AND checked_at = ?",
        (record.app_id, record.external_id, to_db(record.retrieved_at))).fetchone()
    if exists:
        return False
    writer.add_mapping(run_id, record.app_id, "itad", record.external_id, "verified-legacy",
                       checked_at=record.retrieved_at, warnings=record.warnings)
    return True


def _metadata(writer: StoreWriter, run_id: str, record: LegacyMetadata) -> bool:
    exists = writer.conn.execute(
        "SELECT 1 FROM product_facts WHERE app_id = ? AND source = ? AND retrieved_at = ? LIMIT 1",
        (record.app_id, SOURCE, to_db(record.retrieved_at))).fetchone()
    if exists:
        return False
    facts = static_facts(record.details)
    if record.partial:  # only keep fields the legacy file actually recorded
        facts = {k: v for k, v in facts.items() if v not in (None, [], "unknown")}
    writer.add_facts(run_id, record.app_id, facts, source=SOURCE, retrieved_at=record.retrieved_at)
    return True


def _catalog(writer: StoreWriter, record: LegacyCatalog) -> bool:
    stamp = to_db(record.retrieved_at)
    before = writer.conn.total_changes
    writer.conn.executemany(
        "INSERT OR IGNORE INTO reference_candidates (app_id, pool, pool_detail, sample_version, status, updated_at) "
        "VALUES (?, 'related-publisher', ?, ?, 'pending', ?)",
        [(app_id, record.publisher, CATALOG_SAMPLE_VERSION, stamp) for app_id in record.app_ids],
    )
    writer.conn.execute(
        "INSERT OR IGNORE INTO catalog_progress (kind, name, next_start, total_count, complete, updated_at) "
        "VALUES ('publisher', ?, ?, ?, 1, ?)",
        (record.publisher, len(record.app_ids), len(record.app_ids), stamp),
    )
    return writer.conn.total_changes > before


def import_legacy(writer: StoreWriter, cache: LegacyCache, *, now: datetime, progress=None) -> dict[str, Any]:
    run_id = writer.start_run("legacy-import")
    files = imported = already = empty_histories = observations = 0
    by_kind: Counter = Counter()
    skipped: Counter = Counter()
    try:
        # Mappings first, so history rows can be tagged with their app's ITAD product (feature 006).
        records = sorted(cache.records(), key=lambda r: not isinstance(r, LegacyMapping))
        for record in records:
            files += 1
            if progress and files % 250 == 0:
                progress.note(f"匯入舊快取：已處理 {files} 個檔案")
            if isinstance(record, LegacySkip):
                skipped[record.reason] += 1
                continue
            by_kind[type(record).__name__] += 1
            if isinstance(record, LegacyHistory) and not record.entries:
                empty_histories += 1   # the old tool queried it but ITAD had no rows: nothing to import
                continue
            with writer.transaction():
                if isinstance(record, LegacyCatalog):
                    new = _catalog(writer, record)
                else:
                    writer.ensure_product(record.app_id, "legacy-import", record.retrieved_at)
                    if isinstance(record, LegacyMapping):
                        new = _mapping(writer, run_id, record)
                    elif isinstance(record, LegacyMetadata):
                        new = _metadata(writer, run_id, record)
                    else:
                        added = writer.add_observations(run_id, to_observations(
                            record.app_id, record.entries, region="TW", primary_region="TW",
                            retrieved_at=record.retrieved_at, source=OBSERVATION_SOURCE,
                            external_id=single_own_id(writer.conn, record.app_id)))
                        observations += added
                        new = added > 0
            imported += new
            already += not new
    except BaseException:
        writer.finish_run(run_id, "failed")
        raise
    summary = {
        "run_id": run_id,
        "kind": "legacy-import",
        "status": "completed",
        "source": str(cache.directory),
        "files": files,
        "records_imported": imported,
        "records_already_imported": already,
        "empty_histories": empty_histories,
        "observations_added": observations,
        "by_kind": dict(by_kind),
        "skipped": dict(skipped),
    }
    writer.finish_run(run_id, "completed", summary)
    return summary
