"""`sweetspot update`: the daily update flow (contracts/cli.md)."""

import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sweetspot import calendar, calendar_sync
from sweetspot.config import Config
from sweetspot.pipeline import consistency, history, mapping, metadata, reference, versions, wishlist
from sweetspot.pipeline import options as option_step
from sweetspot.products import product_type
from sweetspot.sources import (AppListSource, BundleSource, CatalogSource, CurrentPriceSource, HistorySource,
                               ItadPriceSource, MetadataSource, OptionLookupSource, PriceLookup,
                               SeasonalSalesSource, VersionSource, WishlistSource)
from sweetspot.store import schema
from sweetspot.sources.errors import SourceDisabled, SourceError
from sweetspot.store.writer import NewObservation, StoreWriter
from sweetspot.timeutil import elapsed_clock

# item outcome -> (run_item_results status, summary bucket)
OUTCOMES = {
    "priced": ("ok", "ok"),
    "free": ("ok", "free"),
    "unreleased": ("skipped", "unreleased"),
    "not-purchasable": ("skipped", "not_purchasable"),
    "unsupported": ("unsupported", "unsupported"),
    "delisted": ("delisted", "delisted"),
    "not-found": ("not-found", "not_found"),
    "failed": ("failed", "failed"),
}
PROBLEM_OUTCOMES = {"unsupported", "delisted", "not-found", "failed"}
HISTORY_OUTCOMES = {"priced", "free", "not-purchasable", "delisted"}   # apps worth asking history for
UNREACHABLE = {"network", "rate-limited"}       # wishlist rejections that mean the source did not answer (014 T072)
# The daily run only looks for missed sales in recent data; `calendar --check` scans all history.
RECENT_MISSED_SALE_WINDOW = timedelta(days=60)


@dataclass
class DailySources:
    wishlist: WishlistSource
    prices: CurrentPriceSource
    metadata: MetadataSource
    history: HistorySource | None = None
    catalog: CatalogSource | None = None
    app_list: AppListSource | None = None
    sales_page: SeasonalSalesSource | None = None       # feature 012: the official seasonal sales page


@dataclass
class DailyOptions:
    no_history: bool = False
    skip_reference: bool = False


@dataclass
class DailyReport:
    failures: list[dict[str, Any]] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)

    def fail(self, app_id: int | None, stage: str, reason_code: str, message: str = "") -> None:
        self.failures.append({"app_id": app_id, "stage": stage, "reason_code": reason_code, "message": message})


def _observation(app_id: int, lookup: PriceLookup | None, free: bool, now: datetime) -> NewObservation:
    if free:
        currency, regular, price, cut = "TWD", 0, 0, 0
    else:
        quote = lookup.quote
        currency, regular, price, cut = quote.currency, quote.initial_cents, quote.final_cents, quote.discount_pct
    return NewObservation(app_id=app_id, source="steam-current", region="TW", currency=currency,
                          regular_cents=regular, price_cents=price, cut_pct=cut, observed_at=now,
                          raw_observed_at=None, retrieved_at=now)


def classify(writer: StoreWriter, details_cache: metadata.DetailsCache, app_id: int,
             lookup: PriceLookup | None) -> str:
    """Decide the current-price outcome of one app (FR-006)."""
    if lookup is None:
        return "failed"
    if not lookup.found:
        return "delisted" if metadata.has_known_data(writer, app_id) else "not-found"
    if lookup.quote is not None:
        return "priced"
    details = details_cache.get(app_id)
    if details is None:
        return "delisted" if metadata.has_known_data(writer, app_id) else "not-found"
    if product_type(details.type, details.parent_app_id) == "other":
        return "unsupported"
    if details.coming_soon:
        return "unreleased"
    if details.is_free:
        return "free"
    return "not-purchasable"


def update_current_prices(writer: StoreWriter, sources: DailySources, details_cache: metadata.DetailsCache,
                          apps: list[int], *, run_id: str, now: datetime, report: DailyReport,
                          progress) -> tuple[Counter, dict[int, str], dict[int, PriceLookup]]:
    counts: Counter = Counter({bucket: 0 for _, bucket in OUTCOMES.values()})
    outcomes: dict[int, str] = {}
    try:
        lookups = sources.prices.current_prices(apps)
    except SourceError as exc:
        lookups = {}
        report.alerts.append(f"現價來源失敗：{exc}")
    for n, app_id in enumerate(apps, 1):
        progress.step("現價", n, len(apps))
        try:
            outcome = classify(writer, details_cache, app_id, lookups.get(app_id))
        except SourceError as exc:
            outcome, message = "failed", str(exc)
        else:
            message = ""
        outcomes[app_id] = outcome
        status, bucket = OUTCOMES[outcome]
        counts[bucket] += 1
        with writer.transaction():
            if outcome in ("priced", "free"):
                writer.add_observations(run_id, [_observation(app_id, lookups.get(app_id), outcome == "free", now)])
            writer.record_item_result(run_id, app_id, "current-price", status,
                                      None if outcome == "priced" else outcome, message or None)
        if outcome in PROBLEM_OUTCOMES:
            report.fail(app_id, "current-price", outcome, message)
    return counts, outcomes, lookups


def update_metadata(writer: StoreWriter, sources: DailySources, details_cache: metadata.DetailsCache,
                    apps: list[int], *, config: Config, run_id: str, now: datetime, report: DailyReport,
                    progress) -> Counter:
    counts: Counter = Counter()
    static_age = timedelta(days=config.cache.static_metadata_days)
    for n, app_id in enumerate(apps, 1):
        progress.step("商品資料", n, len(apps))
        try:
            result = metadata.refresh_static(writer, details_cache, app_id, run_id=run_id, now=now,
                                             max_age=static_age)
        except SourceError as exc:
            result = "failed"
            report.fail(app_id, "metadata", "source-error", str(exc))
        counts[result] += 1
        writer.record_item_result(run_id, app_id, "metadata",
                                  {"ok": "ok", "reused": "reused", "not-found": "skipped"}.get(result, "failed"))
    try:
        metadata.refresh_volatile(writer, sources.metadata, apps, run_id=run_id, now=now,
                                  max_age=timedelta(days=config.cache.volatile_metadata_days), progress=progress)
    except SourceError as exc:
        report.alerts.append(f"評論數更新失敗：{exc}")
    return counts


def update_history(writer: StoreWriter, sources: DailySources, details_cache: metadata.DetailsCache,
                   apps: list[int], lookups: dict[int, PriceLookup], *, config: Config, run_id: str, now: datetime,
                   report: DailyReport, progress, clock: Callable[[], datetime] | None = None) -> dict[str, Any]:
    """Step 4: verify mappings, fetch primary and aux history, cross-check current prices (FR-007..009)."""
    hist: dict[str, Any] = {"fetched": 0, "reused": 0, "rejected": 0, "failed": 0}
    aux: dict[str, Any] = {"fetched": 0, "reused": 0, "unavailable": 0, "failed": 0}
    maps = {"verified": 0, "rejected": 0, "reused": 0, "failed": 0}
    checks = {"match": 0, "mismatch": 0, "missing": 0}
    summary = {"mappings": maps, "history": hist, "aux_history": aux, "price_checks": checks}
    if sources.history is None:
        hist["disabled"] = True
        summary["versions"] = {"skipped": "no-itad-key"}
        summary["purchase_options"] = {"skipped": "no-itad-key"}
        report.alerts.append("未設定 ITAD_API_KEY：歷史價格停用，只更新清單與現價")
        report.alerts.append("未設定 ITAD_API_KEY：版本步驟略過，沿用上一次的版本")
        return summary

    quotes = {a: lookups[a].quote for a in apps if a in lookups}
    try:
        mappings = mapping.resolve_mappings(writer, sources.history, sources.metadata, details_cache, apps, quotes,
                                            run_id=run_id, now=now,
                                            max_age=timedelta(days=config.cache.mapping_days))
    except SourceError as exc:
        report.alerts.append(f"ITAD 對應查詢失敗，本次略過歷史：{exc}")
        maps["failed"] = len(apps)
        return summary

    tracked, purchase_options = _versions(writer, sources, apps, lookups, mappings, config=config, run_id=run_id,
                                          now=now, summary=summary, report=report, progress=progress)
    editions = _options(writer, sources, apps, purchase_options, tracked, config=config, run_id=run_id, now=now,
                        summary=summary, report=report, progress=progress)

    verified = []          # (app_id, ITAD product whose history to fetch)
    for app_id in apps:
        m = mappings[app_id]
        maps["reused" if m.reused else ("rejected" if m.verification == "rejected" else "verified")] += 1
        if m.verification == "rejected":
            writer.record_item_result(run_id, app_id, "mapping", "failed", m.reason_code)
        else:
            writer.record_item_result(run_id, app_id, "mapping", "reused" if m.reused else "ok")
        version = tracked.get(app_id)
        product = version.history_id if version else (m.external_id if m.verification != "rejected" else None)
        if product is None:
            hist["rejected"] += 1
            if m.verification == "rejected" and not (version and version.verification == "rejected"):
                report.fail(app_id, "mapping", m.reason_code or "rejected")
            continue
        verified.append((app_id, product))
    summary["products"] = dict(verified)

    max_age = timedelta(hours=config.cache.history_hours)
    disabled = False
    for n, (app_id, product) in enumerate(verified, 1):
        progress.step("歷史價格", n, len(verified))
        for region, counter, stage in ((config.region, hist, "history-tw"), (config.aux_region, aux, "history-aux")):
            if disabled:
                counter["failed"] += 1
                writer.record_item_result(run_id, app_id, stage, "failed", "source-disabled")
                continue
            if history.history_is_fresh(writer, app_id, region, now, max_age, external_id=product):
                counter["reused"] += 1
                writer.record_item_result(run_id, app_id, stage, "reused")
                continue
            try:
                result = history.ingest_history(writer, sources.history, app_id=app_id, external_id=product,
                                                region=region, primary_region=config.region, now=now,
                                                run_id=run_id, clock=clock)
            except SourceError as exc:
                disabled = disabled or isinstance(exc, SourceDisabled)
                counter["failed"] += 1
                writer.record_item_result(run_id, app_id, stage, "failed", "source-error", str(exc))
                report.fail(app_id, stage, "source-error", str(exc))
                continue
            aux_missing = region != config.region and result.entries == 0
            counter["unavailable" if aux_missing else "fetched"] += 1
            writer.record_item_result(run_id, app_id, stage, "ok")

    if editions is not None:
        summary["purchase_options"]["history"] = _edition_histories(
            writer, sources, editions, config=config, run_id=run_id, now=now, max_age=max_age, report=report,
            progress=progress, disabled=disabled, clock=clock)

    if verified and not disabled:
        products = sorted({p for _, p in verified})
        deals: dict[str, int | None] = {}
        try:
            if isinstance(sources.history, ItadPriceSource):
                summaries = sources.history.price_summaries(products, config.region)
                itad_quotes = {k: v.quote for k, v in summaries.items()}
                deals = {k: v.steam_deals for k, v in summaries.items()}
            else:
                itad_quotes = sources.history.current_prices(products, config.region)
        except SourceError as exc:
            report.alerts.append(f"ITAD 現價交叉核對失敗：{exc}")
            itad_quotes = {}
        mismatched = []
        with writer.transaction():
            for app_id, product in verified:
                match = history.record_price_check(writer, run_id, app_id, quotes.get(app_id),
                                                   itad_quotes.get(product), now=now, external_id=product,
                                                   itad_steam_deals=deals.get(product))
                checks["missing" if match is None else ("match" if match else "mismatch")] += 1
                if match is False:
                    mismatched.append(app_id)
        if mismatched:
            report.alerts.append(f"ITAD 與 Steam 現價不一致（兩者皆已保存）：{mismatched}")
    return summary


def _versions(writer: StoreWriter, sources: DailySources, apps: list[int], lookups: dict[int, PriceLookup],
              mappings: dict, *, config: Config, run_id: str, now: datetime, summary: dict, report: DailyReport,
              progress) -> tuple[dict[int, versions.AppVersion], dict[int, list] | None]:
    """The version step (feature 006, contracts/cli-and-report.md): between current prices and history. Also returns
    the purchase options it fetched (None after a source error), which the purchase-option step reuses."""
    if not isinstance(sources.history, ItadPriceSource) or not isinstance(sources.metadata, VersionSource):
        summary["versions"] = {"skipped": "unsupported-source"}
        return {}, None
    progress.step("版本", 0, len(apps))
    run = versions.resolve_versions(writer, sources.metadata, sources.history, sources.metadata, apps, lookups,
                                    mappings, run_id=run_id, now=now,
                                    max_age=timedelta(days=config.cache.mapping_days), region=config.region)
    progress.step("版本", len(apps), len(apps))
    summary["versions"] = run.summary
    report.alerts.extend(run.alerts)
    return run.versions, None if run.summary.get("source_error") else run.options


def _options(writer: StoreWriter, sources: DailySources, apps: list[int], purchase_options: dict[int, list] | None,
             tracked: dict[int, versions.AppVersion], *, config: Config, run_id: str, now: datetime, summary: dict,
             report: DailyReport, progress) -> list[option_step.EditionFetch] | None:
    """The purchase-option step (feature 009, contracts/cli-and-report.md): after the version step."""
    if not isinstance(sources.metadata, BundleSource) or not isinstance(sources.history, OptionLookupSource):
        summary["purchase_options"] = {"skipped": "unsupported-source"}
        return None
    if purchase_options is None:
        summary["purchase_options"] = {"skipped": "no-purchase-options", "source_error": True}
        report.alerts.append("購買選項步驟略過：版本步驟沒有取得購買選項，沿用上一次的紀錄")
        return None
    progress.step("購買選項", 0, len(apps))
    run = option_step.resolve_options(writer, sources.metadata, sources.history, sources.metadata, apps,
                                      purchase_options, tracked, config.purchase_options, run_id=run_id, now=now,
                                      max_age=timedelta(days=config.cache.mapping_days),
                                      kinds_age=timedelta(days=config.cache.static_metadata_days),
                                      region=config.region)
    progress.step("購買選項", len(apps), len(apps))
    summary["purchase_options"] = run.summary
    report.alerts.extend(run.alerts)
    return run.fetch


def _edition_histories(writer: StoreWriter, sources: DailySources, editions: list[option_step.EditionFetch], *,
                       config: Config, run_id: str, now: datetime, max_age: timedelta, report: DailyReport, progress,
                       disabled: bool, clock: Callable[[], datetime] | None = None) -> dict[str, int]:
    """Feature 009 (research R8): TW history of every verified edition; aux history only for the chosen one."""
    started = time.monotonic()
    counts: dict[str, Any] = {"tw": 0, "aux": 0, "skipped_fresh": 0, "failed": 0}
    jobs = [(e, config.region) for e in editions] + [(e, config.aux_region) for e in editions if e.aux]
    for n, (edition, region) in enumerate(jobs, 1):
        progress.step("版本歷史", n, len(jobs))
        if disabled:
            counts["failed"] += 1
            continue
        if history.history_is_fresh(writer, edition.app_id, region, now, max_age, external_id=edition.external_id,
                                    source=schema.OPTION_FETCH_SOURCE):
            counts["skipped_fresh"] += 1
            continue
        try:
            history.ingest_history(writer, sources.history, app_id=edition.app_id, external_id=edition.external_id,
                                   region=region, primary_region=config.region, now=now, run_id=run_id,
                                   observation_source=schema.OPTION_HISTORY_SOURCE,
                                   fetch_source=schema.OPTION_FETCH_SOURCE, clock=clock)
        except SourceError as exc:
            disabled = disabled or isinstance(exc, SourceDisabled)
            counts["failed"] += 1
            report.alerts.append(f"版本歷史抓取失敗（{edition.kind}/{edition.option_id}）：{exc}")
            continue
        counts["tw" if region == config.region else "aux"] += 1
    counts["seconds"] = round(time.monotonic() - started, 1)
    return counts


def update_calendar(writer: StoreWriter, config: Config, *, now: datetime, report: DailyReport,
                    sales_page: SeasonalSalesSource | None = None, run_id: str | None = None) -> dict[str, Any]:
    """Step 5: read the official seasonal sales page (feature 012), merge the sales the file lacks, refresh sale
    estimates and raise calendar alerts (FR-032, FR-033). A file that cannot be read skips the page too (FR-009)."""
    path = config.data_dir / "steam_sales.toml"
    try:
        file_events = calendar.load_calendar(path, now=now)
        default_time, tz = calendar.read_defaults(path)
    except calendar.CalendarError as exc:
        report.alerts.append(f"特賣行事曆無法使用：{exc}")
        return {"calendar": {"status": "unavailable", "official_page": {"status": "skipped"}}}
    fetched = None
    if sales_page is not None:
        fetched = calendar_sync.fetch(writer, sales_page, now=now, default_time=default_time, tz=tz, run_id=run_id)
    events = calendar.effective_events(file_events,
                                       calendar_sync.adopted_sales(writer, file_events=file_events, now=now))
    official = calendar_sync.official_state(writer, file_events, now=now, fetched=fetched)
    report.alerts.extend(official.alerts)
    created = calendar.refresh_estimates(writer, events, now=now)
    estimates = calendar.current_estimates(writer)
    report.alerts.extend(calendar.coverage_alerts(events, estimates, now=now))
    for missed in calendar.detect_missed_sales(writer, events, since=now - RECENT_MISSED_SALE_WINDOW, now=now):
        report.alerts.append(f"{missed.day} 有 {missed.publishers} 家發行商（{missed.apps} 款遊戲）同時開始打折，"
                             "但不在任何已知特賣內，可能漏收一場特賣")
    return {"calendar": {"status": "ok", "new_estimates": [calendar.label(e) for e in created],
                         "official_page": official.summary}}


def update_consistency(writer: StoreWriter, config: Config, apps: list[int], *, now: datetime,
                       keys: dict[int, str | None] | None = None) -> dict[str, Any]:
    """Step 5b: TW vs aux-region discount consistency for tracked games plus the overall figure (FR-007b). `keys`:
    the ITAD product each tracked game reads (feature 006)."""
    rows = consistency.refresh(writer, apps, config.aux_region, now=now, keys=keys)
    overall = next(r for r in rows if r.scope == "ALL")
    return {
        "apps_with_result": len(rows) - 1,
        "days_same_cut_pct": round(100 * overall.days_same_cut / overall.days_compared, 1)
        if overall.days_compared else None,
        "sales_matched_pct": round(100 * overall.sales_matched / overall.sales_tw, 1) if overall.sales_tw else None,
        "sales_tw": overall.sales_tw,
    }


def update_reference(writer: StoreWriter, sources: DailySources, config: Config, options: DailyOptions, *,
                     now: datetime, run_id: str, report: DailyReport, progress,
                     clock: Callable[[], datetime] | None = None) -> dict[str, Any]:
    """Step 6: spend a small fixed time budget growing the reference dataset (FR-017a)."""
    budget = config.reference.daily_budget_seconds
    if options.skip_reference or options.no_history or budget <= 0 or sources.catalog is None:
        return {"status": "skipped", "budget_seconds": budget, "dataset_size": reference.dataset_size(writer)}
    ref_sources = reference.ReferenceSources(metadata=sources.metadata, catalog=sources.catalog,
                                             history=sources.history, app_list=sources.app_list)
    try:
        result = reference.run_reference(writer, ref_sources, config, now=now, deadline=time.monotonic() + budget,
                                         progress=progress, run_id=run_id, fetch_clock=clock)
    except SourceError as exc:
        report.alerts.append(f"參考資料集小批次中止：{exc}")
        return {"status": "failed", "budget_seconds": budget, "dataset_size": reference.dataset_size(writer)}
    report.alerts.extend(result.pop("alerts"))
    return {"status": "ok", "budget_seconds": budget, **result}


def run_daily(writer: StoreWriter, sources: DailySources, config: Config, options: DailyOptions, *, now: datetime,
              progress) -> tuple[bool, dict[str, Any]]:
    """Run the daily update. Returns (partial, summary)."""
    run_id = writer.start_run("daily")
    report = DailyReport()
    started = now
    clock = elapsed_clock(now)      # when each history response arrived (fix-quarantine)

    progress.note("同步願望清單…")
    sync = wishlist.sync_wishlist(writer, sources.wishlist, steamid=config.steamid, source_url=config.wishlist_url,
                                  run_id=run_id, now=now, max_items=config.max_items,
                                  tracking_months=config.removed_tracking_months)
    apps = sync.active_apps
    details_cache = metadata.DetailsCache(sources.metadata)
    prices, outcomes, lookups = update_current_prices(writer, sources, details_cache, apps, run_id=run_id,
                                                      now=now, report=report, progress=progress)
    meta = update_metadata(writer, sources, details_cache, apps, config=config, run_id=run_id, now=now,
                           report=report, progress=progress)
    history_summary: dict[str, Any] = ({"versions": {"skipped": "no-history"},
                                        "purchase_options": {"skipped": "no-history"}} if options.no_history else {})
    if not options.no_history:
        eligible = [a for a in apps if outcomes.get(a) in HISTORY_OUTCOMES]
        history_summary = update_history(writer, sources, details_cache, eligible, lookups, config=config,
                                         run_id=run_id, now=now, report=report, progress=progress, clock=clock)
    history_summary.update(update_calendar(writer, config, now=now, report=report, sales_page=sources.sales_page,
                                           run_id=run_id))
    if not options.no_history:
        history_summary["consistency"] = update_consistency(writer, config, apps, now=now,
                                                            keys=history_summary.pop("products", None))
    history_summary["reference"] = update_reference(writer, sources, config, options, now=now, run_id=run_id,
                                                    report=report, progress=progress, clock=clock)

    partial = sync.status == "rejected" or bool(report.failures)
    # 001 contracts/cli.md exit 1 "every source unavailable" (014 T072): the wishlist could not be reached and no
    # current price came back, so nothing at all was learned this run
    unreachable = (sync.status == "rejected" and sync.reject_reason in UNREACHABLE
                   and all(outcomes.get(a) == "failed" for a in apps))
    summary: dict[str, Any] = {
        "run_id": run_id,
        "kind": "daily",
        "status": "failed" if unreachable else "partial" if partial else "completed",
        "started_at": started.isoformat(),
        "wishlist": {"status": sync.status, "reject_reason": sync.reject_reason, "count": sync.count,
                     "added": sync.added, "removed": sync.removed, "used_previous": sync.used_previous,
                     "tracked": len(apps)},
        "current_prices": dict(prices),
        "metadata": dict(meta),
        **history_summary,
        "failures": report.failures,
        "alerts": report.alerts,
    }
    writer.finish_run(run_id, summary["status"], summary)
    return partial, summary
