"""Reference dataset for modelling and backtests: related and broad samples (US4; FR-016..018).

- Related: other games by the wishlist's publishers and developers, at most `per_publisher_cap` per company.
- Broad: chosen without looking at the wishlist, stratified by release year x regular TW price x indie,
  at most `broad_per_stratum` per stratum.
- Refresh (US4 scenario 4, added 2026-10-14): whatever budget the samples leave updates the stale histories of
  every reference app, legacy imports included, oldest first.
Order within each pool is a seeded hash rank, so samples are reproducible and stable as lists grow.
Every app is committed as it finishes; an interrupted or budget-limited run resumes where it stopped.
"""

import json
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sweetspot.config import Config
from sweetspot.pipeline import history, mapping, metadata, sampling
from sweetspot.products import normalize_name
from sweetspot.sources import AppListSource, CatalogSource, HistorySource, MetadataSource
from sweetspot.sources.errors import SourceError
from sweetspot.store.query import PriceStore
from sweetspot.store.writer import StoreWriter
from sweetspot.timeutil import elapsed_clock, from_db, now_utc, to_db

ITEM_BATCH = 50
MAPPING_WINDOW = 100        # upcoming candidates whose ITAD ids are looked up together (ITAD allows 200)
APP_LIST_PAGE = 50_000
HISTORY_SOURCE_MISSING = "history-disabled"
POOLS = ("related", "broad", "refresh")
# the wishlist games, current and tracked after removal: never reference games, never sampled
_WISHLIST = "SELECT app_id FROM wishlist_membership WHERE state IN ('in_wishlist', 'removed_tracking')"


@dataclass
class ReferenceSources:
    metadata: MetadataSource
    catalog: CatalogSource
    history: HistorySource | None
    app_list: AppListSource | None


@dataclass
class Budget:
    deadline: float | None
    limit: int | None
    clock: Callable[[], float]
    processed: int = 0
    stopped: str | None = None

    def exhausted(self) -> bool:
        if self.deadline is not None and self.clock() >= self.deadline:
            self.stopped = "budget"
        elif self.limit is not None and self.processed >= self.limit:
            self.stopped = "limit"
        return self.stopped is not None


@dataclass
class PoolStats:
    fetched: int = 0
    failed: int = 0
    rejected: Counter = field(default_factory=Counter)


class ReferenceRun:
    def __init__(self, writer: StoreWriter, sources: ReferenceSources, config: Config, *, now: datetime,
                 budget: Budget, run_id: str, progress=None, fetch_clock: Callable[[], datetime] | None = None):
        self.writer, self.sources, self.config, self.now = writer, sources, config, now
        # when each history response arrived (fix-quarantine); the daily update passes its own, started at its start
        self.fetch_clock = fetch_clock or elapsed_clock(now)
        self.ref = config.reference
        self.budget, self.run_id, self.progress = budget, run_id, progress
        self.version = sampling.sample_version(self.ref)
        self.details = metadata.DetailsCache(sources.metadata)
        self.history = mapping.CachedHistory(sources.history) if sources.history else None
        self.window: list[int] = []     # upcoming candidates, for batched ITAD id lookups
        self.items: dict[int, Any] = {}
        self.evaluations: dict[int, tuple[str | None, str | None]] = {}
        self.wishlist = {a for (a,) in writer.conn.execute(_WISHLIST)}
        self.alerts: list[str] = []
        self.related = PoolStats()
        self.broad = PoolStats()

    # --- candidate rows -------------------------------------------------------------------------

    def _set(self, app_id: int, pool: str, detail: str, status: str, reason: str | None = None) -> None:
        self.writer.conn.execute(
            "INSERT INTO reference_candidates (app_id, pool, pool_detail, sample_version, shuffle_rank, status, "
            "reject_reason, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (app_id, pool, pool_detail, sample_version) DO UPDATE SET status = excluded.status, "
            "reject_reason = excluded.reject_reason, updated_at = excluded.updated_at",
            (app_id, pool, detail, self.version, sampling.rank(self.ref.seed, app_id) >> 1, status, reason,
             to_db(now_utc())),
        )

    def _fetched_anywhere(self, app_id: int) -> bool:
        return self.writer.conn.execute(
            "SELECT 1 FROM reference_candidates WHERE app_id = ? AND sample_version = ? AND status = 'fetched' "
            "LIMIT 1", (app_id, self.version)).fetchone() is not None

    # --- evaluation -----------------------------------------------------------------------------

    def _prefetch(self, app_ids: list[int]) -> None:
        """Fetch store-item summaries a full batch at a time, only when the next app is not cached yet.

        (Topping up whenever *any* of the next apps was missing sent one request per app.)
        """
        if not app_ids or app_ids[0] in self.items:
            return
        missing = [a for a in app_ids if a not in self.items][:ITEM_BATCH]
        if missing:
            found = self.sources.metadata.item_summaries(missing)
            for app_id in missing:
                self.items[app_id] = found.get(app_id)

    def _evaluate(self, app_id: int) -> tuple[str | None, str | None]:
        """(reject_reason, stratum_key). Writes the facts it learns along the way."""
        if app_id in self.evaluations:
            return self.evaluations[app_id]
        item = self.items.get(app_id)
        reason = sampling.prefilter(item, self.ref, self.now) if item else None
        if reason:
            result = (reason, None)
        else:
            details = self.details.get(app_id)
            if details is None:
                result = ("no-tw-price", None)   # not purchasable or not visible in the TW store
            else:
                metadata.refresh_static(self.writer, self.details, app_id, run_id=self.run_id, now=self.now,
                                        max_age=timedelta(days=self.config.cache.static_metadata_days))
                total = item.review_count_filtered if item and item.review_count_filtered is not None else None
                if total is None or total < self.ref.min_total_reviews:
                    summary = self.sources.metadata.review_summary(app_id)
                    total = summary.total_reviews if summary else None
                    with self.writer.transaction():
                        self.writer.add_facts(self.run_id, app_id, {"review_count_total": total},
                                              source="steam-appreviews", retrieved_at=self.now)
                result = sampling.evaluate(details, total, self.ref, self.now)
        self.evaluations[app_id] = result
        return result

    def _fetch_history(self, app_id: int) -> str | None:
        """Verify the mapping and store TW + aux history. Returns a failure reason or None."""
        if self.history is None:
            return HISTORY_SOURCE_MISSING
        if not self.history.knows(app_id):
            promising = [a for a in self.window if (item := self.items.get(a)) is None
                         or sampling.prefilter(item, self.ref, self.now) is None]
            self.history.prefetch([app_id] + promising[:MAPPING_WINDOW])
        details = self.details.get(app_id)
        quote = details.quote if details else None
        found = mapping.resolve_mappings(self.writer, self.history, self.sources.metadata, self.details,
                                         [app_id], {app_id: quote}, run_id=self.run_id, now=self.now,
                                         max_age=timedelta(days=self.config.cache.mapping_days))[app_id]
        if found.verification == "rejected":
            return found.reason_code or "rejected"
        max_age = timedelta(hours=self.config.cache.history_hours)
        for region in (self.config.region, self.config.aux_region):
            if not history.history_is_fresh(self.writer, app_id, region, self.now, max_age):
                history.ingest_history(self.writer, self.history, app_id=app_id,
                                       external_id=found.external_id, region=region,
                                       primary_region=self.config.region, now=self.now, run_id=self.run_id,
                                       clock=self.fetch_clock)
        return None

    def _accept(self, app_id: int, pool: str, detail: str, via: str, stats: PoolStats) -> bool:
        """Accept an eligible app and fetch its history. Returns True when it now counts toward quotas."""
        with self.writer.transaction():
            self.writer.ensure_product(app_id, via, self.now)
            self._set(app_id, pool, detail, "accepted")
        if self._fetched_anywhere(app_id):
            failure = None
        else:
            try:
                failure = self._fetch_history(app_id)
            except SourceError as exc:
                failure = "source-error"
                self.alerts.append(f"{app_id}: {exc}")
        with self.writer.transaction():
            self._set(app_id, pool, detail, "failed" if failure else "fetched", failure)
        if failure:
            stats.failed += 1
            return False
        stats.fetched += 1
        return True

    def _reject(self, app_id: int, pool: str, detail: str, reason: str, stats: PoolStats) -> None:
        with self.writer.transaction():
            self._set(app_id, pool, detail, "rejected", reason)
        stats.rejected[reason] += 1

    # --- related pool ---------------------------------------------------------------------------

    def _targets(self) -> list[tuple[str, str, str]]:
        return wishlist_companies(self.writer)

    def _page_catalog(self, kind: str, norm: str, display: str) -> bool:
        """Page through a company's store catalog, resuming from catalog_progress. True when complete."""
        row = self.writer.conn.execute(
            "SELECT next_start, total_count, complete FROM catalog_progress WHERE kind = ? AND name = ?",
            (kind, norm)).fetchone()
        next_start, complete = (row[0], row[2]) if row else (0, 0)
        previous: list[int] | None = None
        restarted = False
        while not complete:
            if self.budget.exhausted():
                return False
            try:
                page = self.sources.catalog.search_catalog(kind, display, next_start)
            except SourceError as exc:
                self.alerts.append(f"{kind} {display} 目錄查詢失敗：{exc}")
                return False
            rows = page.row_count
            if rows and page.start != next_start and not restarted:
                # Steam snaps unaligned offsets back to a page boundary; progress saved by older code (which
                # advanced by app count instead of rows) can be unaligned. Re-page from the start once;
                # candidate inserts are idempotent.
                next_start, previous, restarted = 0, None, True
                continue
            # An empty page ends the catalog: Steam's total also counts rows it never shows as apps, and an
            # empty search answers total_count 0 with start -1.
            if rows and (page.start != next_start or page.app_ids and page.app_ids == previous):
                self.alerts.append(f"{kind} {display} 目錄翻頁異常（重複頁或沒有前進），本次略過")
                return False
            previous = page.app_ids
            next_start += rows
            complete = int(rows == 0 or next_start >= page.total_count)
            with self.writer.transaction():
                self.writer.conn.executemany(
                    "INSERT OR IGNORE INTO reference_candidates (app_id, pool, pool_detail, sample_version, "
                    "shuffle_rank, status, updated_at) VALUES (?, ?, ?, ?, ?, 'pending', ?)",
                    [(a, f"related-{kind}", norm, self.version, sampling.rank(self.ref.seed, a) >> 1,
                      to_db(self.now)) for a in page.app_ids])
                self.writer.conn.execute(
                    "INSERT INTO catalog_progress (kind, name, next_start, total_count, complete, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (kind, name) DO UPDATE SET next_start = excluded.next_start, "
                    "total_count = excluded.total_count, complete = excluded.complete, updated_at = excluded.updated_at",
                    (kind, norm, next_start, page.total_count, complete, to_db(self.now)))
        return True

    def _members(self, kind: str, norm: str) -> list[int]:
        rows = self.writer.conn.execute(
            "SELECT DISTINCT app_id FROM reference_candidates WHERE pool = ? AND pool_detail = ?",
            (f"related-{kind}", norm))
        return [a for (a,) in rows]

    def _write_catalog_size(self, norm: str) -> None:
        """FR-005/FR-016a: publisher size = number of games in its store catalog (volatile fact)."""
        size = len(self._members("publisher", norm))
        apps = set(self._members("publisher", norm))
        for app_id, value in self.writer.conn.execute(
                "SELECT app_id, value_json FROM product_facts WHERE field = 'publishers'").fetchall():
            if value and norm in {normalize_name(n) for n in json.loads(value) or []}:
                apps.add(app_id)
        fresh = timedelta(days=self.config.cache.volatile_metadata_days)
        stale = [a for a in apps if not metadata.fact_is_fresh(self.writer, a, "publisher_catalog_size", self.now,
                                                               fresh)]
        with self.writer.transaction():
            for app_id in stale:
                self.writer.add_facts(self.run_id, app_id, {"publisher_catalog_size": size}, source="steam-search",
                                      retrieved_at=self.now)

    def _select_related(self, kind: str, norm: str) -> None:
        pool = f"related-{kind}"
        decided = dict(self.writer.conn.execute(
            "SELECT app_id, status FROM reference_candidates WHERE pool = ? AND pool_detail = ? "
            "AND sample_version = ? AND status != 'pending'", (pool, norm, self.version)))
        # Only finished apps count toward the cap; 'accepted' rows were interrupted mid-fetch and are redone.
        counted = sum(1 for s in decided.values() if s == "fetched")
        ordered = sorted((a for a in self._members(kind, norm) if a not in self.wishlist),
                         key=lambda a: sampling.rank(self.ref.seed, a))
        todo = [a for a in ordered if decided.get(a) in (None, "accepted")]
        for index, app_id in enumerate(todo):
            if counted >= self.ref.per_publisher_cap:
                with self.writer.transaction():
                    for rest in todo[index:]:
                        if decided.get(rest) is None:
                            self._set(rest, pool, norm, "rejected", "publisher-cap")
                            self.related.rejected["publisher-cap"] += 1
                return
            if self.budget.exhausted():
                return
            self.budget.processed += 1
            if self._fetched_anywhere(app_id):   # already sampled via another company: no new requests
                if self._accept(app_id, pool, norm, "reference-related", self.related):
                    counted += 1
                continue
            self.window = todo[index + 1:index + 1 + MAPPING_WINDOW]
            self._prefetch(todo[index:index + ITEM_BATCH])
            reason, _ = self._evaluate(app_id)
            if reason:
                self._reject(app_id, pool, norm, reason, self.related)
            elif self._accept(app_id, pool, norm, "reference-related", self.related):
                counted += 1

    def run_related(self) -> dict[str, Any]:
        targets = self._targets()
        complete = 0
        for n, (kind, norm, display) in enumerate(targets, 1):
            if self.progress:
                self.progress.step("參考：相關樣本", n, len(targets))
            if self.budget.exhausted():
                break
            if not self._page_catalog(kind, norm, display):
                continue
            complete += 1
            if kind == "publisher":
                self._write_catalog_size(norm)
            self._select_related(kind, norm)
        return {"catalogs": len(targets), "catalogs_complete": complete, "fetched": self.related.fetched,
                "failed": self.related.failed, "rejected": dict(self.related.rejected)}

    # --- broad pool -----------------------------------------------------------------------------

    def _refresh_app_list(self) -> int:
        row = self.writer.conn.execute("SELECT COUNT(*), MIN(fetched_at) FROM steam_app_list").fetchone()
        max_age = timedelta(days=self.config.cache.static_metadata_days)
        if row[0] and from_db(row[1]) >= self.now - max_age:
            return row[0]
        last = None
        while True:
            page = self.sources.app_list.app_list(last, APP_LIST_PAGE)
            with self.writer.transaction():
                self.writer.conn.executemany(
                    "INSERT INTO steam_app_list (app_id, name, last_modified, fetched_at) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT (app_id) DO UPDATE SET name = excluded.name, last_modified = excluded.last_modified, "
                    "fetched_at = excluded.fetched_at",
                    [(a, name, modified, to_db(self.now)) for a, name, modified in page.apps])
            if not page.have_more or not page.last_appid:
                break
            last = page.last_appid
        return self.writer.conn.execute("SELECT COUNT(*) FROM steam_app_list").fetchone()[0]

    def run_broad(self) -> dict[str, Any]:
        if self.sources.app_list is None:
            return {"status": "disabled", "reason": "廣泛樣本停用：缺少 STEAM_WEB_API_KEY"}
        try:
            population = self._refresh_app_list()
        except SourceError as exc:                     # an alert too: the run is partial (014 T071)
            self.alerts.append(f"廣泛樣本：無法取得 Steam 遊戲清單：{exc}")
            return {"status": "failed", "reason": f"無法取得 Steam 遊戲清單：{exc}"}
        strata = Counter(dict(self.writer.conn.execute(
            "SELECT pool_detail, COUNT(*) FROM reference_candidates WHERE pool = 'broad' AND sample_version = ? "
            "AND status = 'fetched' GROUP BY pool_detail", (self.version,))))
        decided = {a for (a,) in self.writer.conn.execute(
            "SELECT app_id FROM reference_candidates WHERE pool = 'broad' AND sample_version = ? "
            "AND status != 'accepted'", (self.version,))}
        all_strata = sampling.all_strata(self.ref)
        todo = sorted((a for (a,) in self.writer.conn.execute("SELECT app_id FROM steam_app_list")
                       if a not in decided and a not in self.wishlist),
                      key=lambda a: sampling.rank(self.ref.seed, a))
        cap = self.ref.broad_per_stratum
        exhausted = True
        for index, app_id in enumerate(todo):
            if all(strata[s] >= cap for s in all_strata):
                exhausted = False
                break
            if self.budget.exhausted():
                exhausted = False
                break
            if self.progress and index % 25 == 0:
                filled = sum(min(strata[s], cap) for s in all_strata)
                self.progress.step("參考：廣泛樣本", filled, len(all_strata) * cap)
            self.window = todo[index + 1:index + 1 + MAPPING_WINDOW]
            self._prefetch(todo[index:index + ITEM_BATCH])
            self.budget.processed += 1
            item = self.items.get(app_id)
            if item is not None and sampling.prefilter(item, self.ref, self.now) is None:
                prefix = sampling.likely_prefix(item, self.ref)
                if prefix and strata[f"{prefix}/indie"] >= cap and strata[f"{prefix}/nonindie"] >= cap:
                    # Both possible strata are full: skip the per-app store request that would only
                    # tell us which of the two it belongs to.
                    self._reject(app_id, "broad", f"{prefix}/*", "stratum-full", self.broad)
                    continue
            reason, stratum = self._evaluate(app_id)
            if reason:
                self._reject(app_id, "broad", "-", reason, self.broad)
            elif strata[stratum] >= cap:
                self._reject(app_id, "broad", stratum, "stratum-full", self.broad)
            elif self._accept(app_id, "broad", stratum, "reference-broad", self.broad):
                strata[stratum] += 1
        unfilled = {s: strata[s] for s in all_strata if strata[s] < cap}
        return {"status": "ok", "app_list": population, "fetched": self.broad.fetched, "failed": self.broad.failed,
                "strata_full": len(all_strata) - len(unfilled), "strata_total": len(all_strata),
                # Scanning the whole population and still missing strata means Steam simply has fewer
                # eligible games there: the sample keeps what exists instead of scanning forever.
                "population_exhausted": exhausted, "unfilled_strata": unfilled if exhausted else {},
                "rejected": dict(self.broad.rejected)}

    # --- refresh (US4 scenario 4) ---------------------------------------------------------------

    def _stale(self) -> list[tuple[int, str]]:
        """(app_id, ITAD product) of every reference app whose Taiwan history was last confirmed more than
        cache.history_hours ago, oldest first, so an app that missed the latest seasonal sale comes before one
        that only missed a few days. The product is the one the models read (history_keys); an app without a
        usable product or without any history yet (a failed sample) is left alone."""
        store = PriceStore(self.writer.conn)
        apps = store.reference_apps()
        keys = store.history_keys(apps, self.now)
        known = store.history_known_until_all(self.config.region, keys=store.key_ids(keys))
        cutoff = self.now - timedelta(hours=self.config.cache.history_hours)
        stale = []
        for app_id in apps:
            key = keys[app_id]
            if key.external_id is None or key.basis == "rejected" or app_id not in known or known[app_id] >= cutoff:
                continue
            if key.basis == "own" and store.itad_mapping_state(app_id) == "rejected":
                continue
            stale.append((known[app_id], app_id, key.external_id))
        return [(app_id, external_id) for _, app_id, external_id in sorted(stale)]

    def run_refresh(self) -> dict[str, Any]:
        if self.history is None:
            return {"status": "disabled", "reason": HISTORY_SOURCE_MISSING}
        todo = self._stale()
        max_age = timedelta(hours=self.config.cache.history_hours)
        refreshed = new_rows = 0
        status = "ok"
        for n, (app_id, external_id) in enumerate(todo, 1):
            if self.budget.exhausted():
                break
            if self.progress:
                self.progress.step("參考：更新歷史", n, len(todo))
            self.budget.processed += 1
            try:
                for region in (self.config.region, self.config.aux_region):
                    if not history.history_is_fresh(self.writer, app_id, region, self.now, max_age,
                                                    external_id=external_id):
                        result = history.ingest_history(self.writer, self.history, app_id=app_id,
                                                        external_id=external_id, region=region,
                                                        primary_region=self.config.region, now=self.now,
                                                        run_id=self.run_id, clock=self.fetch_clock)
                        new_rows += result.new_rows
            except SourceError as exc:      # stop rather than spend the budget on a failing source
                self.alerts.append(f"參考歷史更新中止（{app_id}）：{exc}")
                status = "failed"
                break
            refreshed += 1
        return {"status": status, "stale": len(todo), "refreshed": refreshed, "left": len(todo) - refreshed,
                "new_rows": new_rows}


def dataset_size(writer: StoreWriter) -> int:
    """Reference apps (outside the current/tracked wishlist) that have Taiwan price history."""
    return writer.conn.execute(
        "SELECT COUNT(DISTINCT app_id) FROM price_observations WHERE region = 'TW' "
        f"AND source IN ('itad-history', 'legacy-itad') AND app_id NOT IN ({_WISHLIST})").fetchone()[0]


def wishlist_companies(store: StoreWriter | PriceStore) -> list[tuple[str, str, str]]:
    """(kind, normalized name, display name) for every wishlist publisher and developer."""
    found: dict[tuple[str, str], str] = {}
    for app_id in sorted(a for (a,) in store.conn.execute(
            "SELECT app_id FROM wishlist_membership WHERE state = 'in_wishlist'")):
        for kind, field_name in (("publisher", "publishers"), ("developer", "developers")):
            row = store.conn.execute(
                "SELECT value_json FROM product_facts WHERE app_id = ? AND field = ? "
                "ORDER BY retrieved_at DESC LIMIT 1", (app_id, field_name)).fetchone()
            for name in json.loads(row[0]) if row and row[0] else []:
                found.setdefault((kind, normalize_name(name)), name)
    return sorted((kind, norm, display) for (kind, norm), display in found.items())


def sampling_complete(store: StoreWriter | PriceStore, config: Config, *, has_steam_key: bool) -> bool:
    """014 T048 (data-model `reference_notice.sampling`): would another full `reference` run add nothing?

    Related: every current wishlist company's catalog is paged and its candidates are all decided. Broad: every
    stratum is full, or every app of the Steam app list (wishlist aside) has a broad decision. Read-only."""
    if not has_steam_key:
        return False                       # the broad sample is disabled: the key would still add games
    conn, version = store.conn, sampling.sample_version(config.reference)
    paged = {(kind, name) for kind, name in conn.execute("SELECT kind, name FROM catalog_progress WHERE complete = 1")}
    # one scan, not one per company (the key starts with app_id). A company's catalog lists the wishlist game
    # itself, which the samples never take: it stays 'pending' for good.
    undecided = {(pool.removeprefix("related-"), detail) for pool, detail in conn.execute(
        "SELECT DISTINCT pool, pool_detail FROM reference_candidates WHERE pool != 'broad' AND sample_version = ? "
        f"AND status IN ('pending', 'accepted') AND app_id NOT IN ({_WISHLIST})", (version,))}
    for kind, norm, _ in wishlist_companies(store):
        if (kind, norm) not in paged or (kind, norm) in undecided:
            return False
    if not conn.execute("SELECT 1 FROM steam_app_list LIMIT 1").fetchone():
        return False
    fetched = dict(conn.execute(
        "SELECT pool_detail, COUNT(*) FROM reference_candidates WHERE pool = 'broad' AND sample_version = ? "
        "AND status = 'fetched' GROUP BY pool_detail", (version,)))
    if all(fetched.get(s, 0) >= config.reference.broad_per_stratum for s in sampling.all_strata(config.reference)):
        return True
    return conn.execute(
        f"SELECT 1 FROM steam_app_list a WHERE a.app_id NOT IN ({_WISHLIST}) AND NOT EXISTS (SELECT 1 FROM "
        "reference_candidates c WHERE c.app_id = a.app_id AND c.pool = 'broad' AND c.sample_version = ? "
        "AND c.status != 'accepted') LIMIT 1", (version,)).fetchone() is None


def run_reference(writer: StoreWriter, sources: ReferenceSources, config: Config, *, now: datetime,
                  pools: tuple[str, ...] = POOLS, deadline: float | None = None,
                  limit: int | None = None, clock: Callable[[], float] = time.monotonic, progress=None,
                  run_id: str | None = None, fetch_clock: Callable[[], datetime] | None = None) -> dict[str, Any]:
    own_run = run_id is None
    run_id = run_id or writer.start_run("reference")
    budget = Budget(deadline, limit, clock)
    job = ReferenceRun(writer, sources, config, now=now, budget=budget, run_id=run_id, progress=progress,
                       fetch_clock=fetch_clock)
    summary: dict[str, Any] = {"sample_version": job.version}
    if "related" in pools:
        summary["related"] = job.run_related()
    if "broad" in pools:
        summary["broad"] = job.run_broad()
    if "refresh" in pools:              # after the samples: growing the dataset comes first (FR-017a)
        summary["refresh"] = job.run_refresh()
    summary.update(stopped=budget.stopped or "complete", processed=budget.processed,
                   dataset_size=dataset_size(writer), alerts=job.alerts)
    if own_run:
        writer.finish_run(run_id, "completed" if not job.alerts else "partial", {"kind": "reference", **summary})
    return summary
