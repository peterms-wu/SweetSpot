"""CLI command handlers. Each wires concrete sources into a pipeline and returns a CommandResult."""

import argparse
import json
import os
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime

import httpx

from sweetspot import calendar, calendar_sync, coverage
from sweetspot.cli import EXIT_FAILED, EXIT_OK, EXIT_PARTIAL, CommandResult, Context, command
from sweetspot.pipeline.daily import DailyOptions, DailySources, run_daily
from sweetspot.pipeline.legacy_import import import_legacy
from sweetspot.pipeline import reference
from sweetspot.pipeline.reference import ReferenceSources, run_reference
from sweetspot.sources.legacy_cache import LegacyCache
from sweetspot.sources import itad
from sweetspot.sources.errors import SourceError
from sweetspot.sources.http import RateLimitedClient
from sweetspot.sources.itad import ItadClient
from sweetspot.sources.steam_partner import SteamPartnerDocs
from sweetspot.sources.steam_store import SteamStore
from sweetspot.sources.steam_webapi import SteamWebApi
from sweetspot.forecast.backtest.compare import append_record, check_attempt, compare_results, format_record
from sweetspot.forecast.backtest.dataset import build_dataset, default_cutoff
from sweetspot.forecast.backtest.grid import GridError, format_grid_record, run_grid, select
from sweetspot.forecast.backtest.runner import run_backtest
from sweetspot.forecast.contract import LEVELS, Forecast, batch_to_dict, write_json_atomic
from sweetspot.forecast.engine import all_apps, load_games, run_forecast
from sweetspot.forecast.models import CURRENT_MODEL, build_model, current_model, model_class, split_name
from sweetspot.forecast import nonseasonal
from sweetspot.forecast.nonseasonal import backtest as ns_backtest
from dataclasses import replace

from sweetspot.decision import records
from sweetspot.decision.backtest import report_figures, run_rule_backtests
from sweetspot.decision.changes import compare
from sweetspot.decision.compare_rule import (DEFAULT_WAIT_COST, RULE_VALIDATION_TITLE, check_rule_attempt,
                                             compare_rule_results,
                                             format_rule_record, format_rule_records, net_by_cost, net_comparison,
                                             wishlist_diff)
from sweetspot.decision.contract import batch_to_dict as decision_to_dict
from sweetspot.decision.engine import run_decisions
from sweetspot.decision import rule as decision_rule
from sweetspot.review import contract as review_contract
from sweetspot.review.run import partial as review_partial
from sweetspot.review.run import run_review
from sweetspot.report import extension as extension_data
from sweetspot.report.html import render
from sweetspot.store.query import PriceStore
from sweetspot.timeutil import now_utc, parse_iso

# Test seams: integration tests swap in a MockTransport and a no-op sleep, a fixed clock and a fake viewer.
TRANSPORT: httpx.BaseTransport | None = None
SLEEP = time.sleep
NOW = now_utc
OPEN_FILE = getattr(os, "startfile", None)

STEAM_STORE_INTERVAL = 1.5   # research R2: ~200 requests / 5 min community-observed limit
STEAM_WEBAPI_INTERVAL = 1.0
STEAM_PARTNER_INTERVAL = 2.0   # feature 012: one request per update; no retries, a 429 is not waited for
STEAM_PARTNER_MAX_BYTES = 2 * 1024 * 1024


def _client(name: str, interval: float, ctx: Context, **kw) -> RateLimitedClient:
    return RateLimitedClient(name, min_interval=interval, transport=TRANSPORT, sleep=SLEEP,
                             secrets=ctx.secrets.redaction_values(), **kw)


def http_usage(*clients: RateLimitedClient | None) -> dict[str, dict[str, float]]:
    return {c.name: {"requests": c.requests_sent, "throttle_wait_s": round(c.throttle_wait, 1),
                     "by_path": dict(c.requests_by_path.most_common())}
            for c in clients if c is not None}


def steam_sources(ctx: Context) -> tuple[SteamWebApi, SteamStore]:
    key = ctx.secrets.steam_web_api_key.reveal() if ctx.secrets.steam_web_api_key else None
    webapi = SteamWebApi(_client("steam-webapi", STEAM_WEBAPI_INTERVAL, ctx), api_key=key)
    store = SteamStore(_client("steam-store", STEAM_STORE_INTERVAL, ctx), webapi)
    return webapi, store


def partner_source(ctx: Context) -> SteamPartnerDocs:
    return SteamPartnerDocs(_client("steam-partner", STEAM_PARTNER_INTERVAL, ctx, max_retries=0, max_retry_wait=0,
                                    max_bytes=STEAM_PARTNER_MAX_BYTES))


def itad_source(ctx: Context) -> ItadClient | None:
    if ctx.secrets.itad_api_key is None:
        return None
    http = _client("itad", itad.MIN_INTERVAL, ctx, window_limit=itad.WINDOW_LIMIT,
                   max_retry_wait=itad.MAX_RETRY_WAIT)
    return ItadClient(http, ctx.secrets.itad_api_key.reveal())


@command("coverage")
def coverage_command(ctx: Context, args: argparse.Namespace) -> CommandResult:
    store = open_store(ctx)                            # read-only, no lock (001 contracts/cli.md; 014 T070)
    try:
        return _coverage(ctx, args, store.conn)
    finally:
        store.close()


def _coverage(ctx: Context, args: argparse.Namespace, conn) -> CommandResult:
    now = now_utc()
    if args.app:
        apps = [args.app]
    else:
        wishlist = [a for (a,) in conn.execute("SELECT app_id FROM wishlist_membership WHERE state = 'in_wishlist'")]
        reference_apps = [a for (a,) in conn.execute(
            "SELECT p.app_id FROM products p LEFT JOIN wishlist_membership m USING (app_id) "
            "WHERE m.state = 'reference_only' OR (m.state IS NULL AND p.first_seen_via != 'wishlist')")]
        apps = {"wishlist": wishlist, "reference": reference_apps, "all": wishlist + reference_apps}[args.scope]
    rows = [coverage.coverage(conn, a, now, ctx.config.aux_region) for a in sorted(set(apps))]
    names = {a: json.loads(v) for a, v in conn.execute(
        "SELECT app_id, value_json FROM product_facts WHERE field = 'name' ORDER BY retrieved_at")}
    if args.csv:
        coverage.write_csv(args.csv, rows, names)
    latest_all = conn.execute(
        "SELECT days_compared, days_same_cut, sales_tw, sales_matched, computed_at FROM region_consistency "
        "WHERE scope = 'ALL' ORDER BY computed_at DESC, row_id DESC LIMIT 1").fetchone()
    summary: dict = {
        "scope": f"app {args.app}" if args.app else args.scope,
        "apps": len(rows),
        "history_state": dict(Counter(r.history_state for r in rows)),
        "aux_available": sum(r.aux_available for r in rows),
        "with_data_gaps": sum(bool(r.data_gaps) for r in rows),
        "mapping_rejected": sum(r.mapping_state == "rejected" for r in rows),
        "region_consistency_all": None if latest_all is None else {
            "days_same_cut_pct": round(100 * latest_all[1] / latest_all[0], 1) if latest_all[0] else None,
            "sales_matched_pct": round(100 * latest_all[3] / latest_all[2], 1) if latest_all[2] else None,
            "sales_tw": latest_all[2], "computed_at": latest_all[4]},
    }
    if args.csv:
        summary["csv"] = str(args.csv)
    if args.app and rows:
        c = rows[0]
        summary["detail"] = {
            "name": names.get(args.app), "history_state": c.history_state,
            "tw": [c.tw_earliest and c.tw_earliest.isoformat(), c.tw_latest and c.tw_latest.isoformat()],
            "aux": [c.aux_earliest and c.aux_earliest.isoformat(), c.aux_latest and c.aux_latest.isoformat()],
            "paid_sale_count": c.paid_sale_count, "free_promo_count": c.free_promo_count,
            "data_gaps": [[g.start.isoformat(), g.end.isoformat()] for g in c.data_gaps],
            "long_unchanged": [[g.start.isoformat(), g.end.isoformat()] for g in c.long_unchanged],
            "mapping": [c.mapping_state, c.mapping_reason], "note": c.note,
        }
    return CommandResult(EXIT_OK, summary)


@command("calendar")
def calendar_command(ctx: Context, args: argparse.Namespace) -> CommandResult:
    if args.write and not args.sync:
        raise ValueError("--write 要和 --sync 一起使用")
    now = now_utc()
    path = ctx.config.data_dir / "steam_sales.toml"
    file_events = calendar.load_calendar(path, now=now)
    fetched = None
    if args.fetch:                                          # feature 012: one request to the official page
        default_time, tz = calendar.read_defaults(path)
        partner = partner_source(ctx)
        try:
            fetched = calendar_sync.fetch(ctx.writer, partner, now=now, default_time=default_time, tz=tz)
        finally:
            partner.http.close()
    events = calendar.effective_events(file_events,
                                       calendar_sync.adopted_sales(ctx.writer, file_events=file_events, now=now))
    latest = calendar_sync.latest_fetch(ctx.writer)
    official = calendar_sync.official_state(
        ctx.writer, file_events, now=now,
        fetched=fetched or ({"status": latest["status"], "seconds": 0.0} if latest else None))
    if not fetched:
        official.summary["status"] = "not_fetched"
    created = calendar.refresh_estimates(ctx.writer, events, now=now)
    estimates = calendar.current_estimates(ctx.writer)
    upcoming = sorted([e for e in events if e.end > now] + estimates, key=lambda e: e.start)
    summary = {
        "sales": len(file_events),
        "seasonal": sum(e.kind == "seasonal" for e in file_events),
        "themed": sum(e.kind == "themed" for e in file_events),
        "official_page": official.summary,
        "new_estimates": [calendar.label(e) for e in created],
        "upcoming_seasonal": [
            {"label": calendar.label(e), "start": e.start.isoformat(), "end": e.end.isoformat(), "status": e.status,
             "source": e.source}
            for e in upcoming if e.kind == "seasonal"
        ],
    }
    exit_code = EXIT_OK
    text = None
    if args.check:
        alerts = calendar.coverage_alerts(events, estimates, now=now) + official.alerts
        missed = calendar.detect_missed_sales(ctx.writer, events, since=datetime(2019, 1, 1, tzinfo=UTC), now=now)
        summary["alerts"] = alerts
        summary["possible_missed_sales"] = [{"day": m.day.isoformat(), "publishers": m.publishers, "apps": m.apps}
                                           for m in missed]
        exit_code = EXIT_PARTIAL if alerts or missed else EXIT_OK
    if args.sync:                                           # feature 012 (research R5): list, or write with --write
        plan = calendar_sync.sync_plan(ctx.writer, path, now=now)
        result = calendar_sync.write_sync(path, plan, now=now) if args.write else {"written": False}
        summary["sync"] = calendar_sync.sync_summary(plan, written=result["written"], error=result.get("error"))
        text = _sync_text(summary["sync"], args.write)
        if result.get("error"):
            exit_code = EXIT_FAILED
    return CommandResult(exit_code, summary, text=text)


def _sync_text(sync: dict, write: bool) -> str:
    if not sync["add"] and not sync["reschedule"]:
        return "已一致：data/steam_sales.toml 和官方特賣頁面相同"
    lines = [f"新增 {a['label']}：{a['start']} – {a['end']}（第一次看到 {a['first_seen']}）" for a in sync["add"]]
    lines += [f"改期 {r['label']}：{r['file'][0]} – {r['file'][1]} → {r['official'][0]} – {r['official'][1]}"
              for r in sync["reschedule"]]
    if sync.get("error"):
        lines.append(f"未寫入：{sync['error']}")
    elif sync["written"]:
        lines.append("已寫入 data/steam_sales.toml；請檢查差異後 commit")
    elif not write:
        lines.append("加上 --write 寫入 data/steam_sales.toml（日期為太平洋時間）")
    return "\n".join(lines)


@command("import-legacy")
def import_legacy_command(ctx: Context, args: argparse.Namespace) -> CommandResult:
    path = args.path or ctx.config.legacy_cache_path
    if path is None:                                   # 014 FR-010: no one's folder is the default any more
        return CommandResult(EXIT_FAILED, {"status": "not_configured"},
                             text="import-legacy 只給前身專案 SteamSage 的使用者：在指令後面加上它的快取資料夾（uv run sweetspot import-legacy <路徑>），"
                                  "或在設定檔的 [legacy] cache_path 填入；沒有前身專案的資料就不需要這個指令。")
    cache = LegacyCache(path)
    summary = import_legacy(ctx.writer, cache, now=now_utc(), progress=ctx.progress)
    return CommandResult(EXIT_OK, summary)


REFERENCE_RESUME = "已完成的部分都已保存；來源恢復後再執行 uv run sweetspot reference 會接著做。"   # 001 contracts/cli.md


@command("reference")
def reference_command(ctx: Context, args: argparse.Namespace) -> CommandResult:
    webapi, store = steam_sources(ctx)
    history = itad_source(ctx)
    pools = reference.POOLS if args.pool == "all" else (args.pool,)
    try:
        sources = ReferenceSources(metadata=store, catalog=store, history=history,
                                   app_list=webapi if webapi.api_key else None)
        deadline = time.monotonic() + args.budget if args.budget else None
        summary = run_reference(ctx.writer, sources, ctx.config, now=now_utc(), pools=pools, deadline=deadline,
                                limit=args.limit, progress=ctx.progress)
    except SourceError as exc:          # e.g. the Steam store answering 502 for every page (014 T049)
        exc.add_note(REFERENCE_RESUME)
        raise
    finally:
        for client in (webapi.http, store.http, history.http if history else None):
            if client:
                client.close()
    summary["http"] = http_usage(webapi.http, store.http, history.http if history else None)
    if history is None:
        summary["alerts"].append("未設定 ITAD_API_KEY：參考遊戲只記錄中繼資料，沒有歷史價格")
    return CommandResult(EXIT_PARTIAL if summary["alerts"] else EXIT_OK, summary)


@command("update")
def update(ctx: Context, args: argparse.Namespace) -> CommandResult:
    webapi, store = steam_sources(ctx)
    history = None if args.no_history else itad_source(ctx)
    partner = partner_source(ctx)
    try:
        sources = DailySources(wishlist=webapi, prices=store, metadata=store, history=history, catalog=store,
                               app_list=webapi if webapi.api_key else None, sales_page=partner)
        options = DailyOptions(no_history=args.no_history, skip_reference=args.skip_reference)
        partial, summary = run_daily(ctx.writer, sources, ctx.config, options, now=now_utc(),
                                     progress=ctx.progress)
    finally:
        for client in (webapi.http, store.http, history.http if history else None, partner.http):
            if client:
                client.close()
    summary["http"] = http_usage(webapi.http, store.http, history.http if history else None, partner.http)
    if summary["status"] == "failed":                 # every source unavailable (014 T072)
        return CommandResult(EXIT_FAILED, summary)
    return CommandResult(EXIT_PARTIAL if partial else EXIT_OK, summary)


# --- feature 002: read-only analysis commands ---------------------------------------------------------

def parse_moment(text: str) -> datetime:
    """'YYYY-MM-DD' (00:00 UTC) or a full ISO timestamp with offset."""
    try:
        if "T" in text:
            return parse_iso(text)
        return datetime.fromisoformat(text).replace(tzinfo=UTC)
    except ValueError:
        raise ValueError(f"無法解析日期：{text!r}（格式 YYYY-MM-DD）") from None


def parse_params(pairs: list[str]) -> dict[str, str]:
    params = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise ValueError(f"--param 格式應為 K=V：{pair!r}")
        params[key.strip()] = value.strip()
    return params


def model_from_args(args: argparse.Namespace):
    """--model [name@version] / --param on top of CURRENT_MODEL. Same model name: the current params are the defaults,
    keeping only those the chosen version knows (feature 008: seasonal-record@1.0.0 next to 1.1.0)."""
    name, version, current_params = CURRENT_MODEL
    if not args.param and not args.model:
        return current_model()
    chosen, chosen_version = split_name(args.model or name)
    params = {}
    if chosen == name:
        known = set(model_class(chosen, chosen_version)().params)
        params = {k: v for k, v in current_params.items() if k in known}
    params.update(parse_params(args.param))
    return build_model(chosen, params, chosen_version)


REFERENCE_TARGET = 2000      # 014 FR-014a: 001 SC-006 set at least 2,000 reference games with history as the target


def reference_notice(dataset_size: int, *, has_steam_key: bool,
                     complete: Callable[[], bool] = lambda: False) -> dict | None:
    """The small-dataset notice of the report and the extension, or None at the target (presentation only).

    `complete` (014 T048) is asked only below the target: has the sampling nothing left to add?"""
    if dataset_size >= REFERENCE_TARGET:
        return None
    return {"dataset_size": dataset_size, "threshold": REFERENCE_TARGET,
            "broad_sample": "ok" if has_steam_key else "disabled",
            "sampling": "complete" if has_steam_key and complete() else "incomplete"}


def open_store(ctx: Context) -> PriceStore:
    return PriceStore.open(ctx.config.db_path, ctx.config.data_dir / "steam_sales.toml")


def _forecast_line(game: Forecast) -> str:
    title = f"{game.name or '（無名稱）'}（{game.app_id}）"
    if game.status != "ok":
        return f"{title}：{game.status}（{game.status_reason}）"
    first = game.points[0]
    p50 = game.probabilities[0][LEVELS.index(50)]
    return f"{title}：信心 {game.confidence}，下一場 {first.label} ≥-50%：{p50:.0%}"


@command("forecast")
def forecast_command(ctx: Context, args: argparse.Namespace) -> CommandResult:
    started = time.monotonic()
    as_of = parse_moment(args.as_of) if args.as_of else now_utc()
    model = model_from_args(args)
    store = open_store(ctx)
    try:
        if args.app:
            apps = sorted(set(args.app))
        elif args.scope == "all":
            apps = all_apps(store)
        else:
            apps = store.wishlist_apps()
        batch = run_forecast(store, apps, as_of, model,
                             progress=lambda n, total: ctx.progress.step("預測", n, total))
    finally:
        store.close()
    data = batch_to_dict(batch)
    exit_code = EXIT_PARTIAL if data["summary"]["model_error"] else EXIT_OK
    summary = {"games": len(batch.games), **data["summary"], "model": data["model"], "as_of": data["as_of"],
               "data_cutoff": data["data_cutoff"], "seconds": round(time.monotonic() - started, 1)}
    if args.out:
        write_json_atomic(args.out, data)
        summary["out"] = str(args.out)
    elif args.json:
        return CommandResult(exit_code, data)
    return CommandResult(exit_code, summary, text="\n".join(_forecast_line(g) for g in batch.games))


@command("backtest")
def backtest_command(ctx: Context, args: argparse.Namespace) -> CommandResult:
    started = time.monotonic()
    model = model_from_args(args)
    regions = ("TW", "US") if args.region == "all" else (args.region,)
    store = open_store(ctx)
    try:
        cutoff = parse_moment(args.cutoff) if args.cutoff else default_cutoff(store)
        ctx.progress.note(f"讀取資料（截止 {cutoff.strftime('%Y-%m-%d')}）")
        games = load_games(store, all_apps(store), cutoff)
        events = store.calendar_events()
        dataset = build_dataset(store, games, events, cutoff=cutoff, regions=regions, apps_limit=args.apps_limit,
                                split=args.split)
        result, path = run_backtest(store, dataset, games, events, model, out_dir=ctx.config.data_dir / "backtests",
                                    progress=lambda message: ctx.progress.note(message))
    finally:
        store.close()
    summary = {
        "result": str(path),
        "model": result["model"],
        "cutoff": result["dataset"]["cutoff"],
        "split": args.split,
        "regions": {r: {"games": v["games"], "as_of_count": v["as_of_count"], "brier": v["brier"],
                        "reference_brier": v["reference_brier"], "units": v["units"]}
                    for r, v in result["regions"].items()},
        "finished": {r: _finished_line(v.get("finished_calibration") or {}) for r, v in result["regions"].items()},
        "errors": len(result["errors"]),
        "seconds": round(time.monotonic() - started, 1),
    }
    return CommandResult(EXIT_PARTIAL if result["errors"] else EXIT_OK, summary)


def _finished_line(fc: dict) -> dict:
    """feature 008: finished-only Brier and, over predictions ≥ 0.7, predicted − actual in percentage points."""
    high = [b for b in fc.get("bins", []) if b["lo"] >= 0.7]
    n = sum(b["n"] for b in high)
    excess = None if not n else round(sum((b["predicted"] - b["actual"]) * b["n"] for b in high) / n * 100, 1)
    return {"units": fc.get("units", 0), "brier": fc.get("brier"), "high_excess_pp": excess}


@command("compare")
def compare_command(ctx: Context, args: argparse.Namespace) -> CommandResult:
    current = json.loads(args.current.read_text(encoding="utf-8"))
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    groups = tuple(g.strip() for g in (args.target_groups or "").split(",") if g.strip())
    comparison = compare_results(current, candidate, target_groups=groups)
    record = args.record_to or (args.config.resolve().parent / "docs" / "model" / "comparisons.md"
                                if args.record else None)
    if record:
        check_attempt(record, comparison, args.attempt, args.change)
        append_record(record, format_record(comparison, date=now_utc().strftime("%Y-%m-%d"),
                                            files=(args.current.name, args.candidate.name), attempt=args.attempt,
                                            change=args.change))
    summary = {
        "verdict": comparison.verdict,
        "split": comparison.split,
        "reasons": comparison.reasons,
        "current": comparison.model_a,
        "candidate": comparison.model_b,
        "regions": {r: {"current": c.brier_a, "candidate": c.brier_b, "diff": c.diff, "interval": [c.low, c.high],
                        "games": c.games, "omitted": c.omitted} for r, c in comparison.regions.items()},
        "groups": {g: {"current": c.brier_a, "candidate": c.brier_b, "diff": c.diff, "interval": [c.low, c.high],
                       "games": c.games} for g, c in comparison.groups.items()},
        "record": str(record) if record else None,
    }
    return CommandResult(EXIT_OK if comparison.verdict == "優於" else EXIT_PARTIAL, summary)


def parse_grid(pairs: list[str]) -> list[tuple[str, list[str]]]:
    grid = []
    for pair in pairs:
        key, sep, values = pair.partition("=")
        if not sep or not key.strip() or not values.strip():
            raise ValueError(f"--grid 格式應為 K=V1,V2：{pair!r}")
        grid.append((key.strip(), [v.strip() for v in values.split(",") if v.strip()]))
    if not grid:
        raise ValueError("至少需要一個 --grid")
    return grid


@command("grid")
def grid_command(ctx: Context, args: argparse.Namespace) -> CommandResult:
    started = time.monotonic()
    grid = parse_grid(args.grid)
    fixed = parse_params(args.param)
    if args.split == "validation":
        raise GridError("網格只能在調參組或全部資料上執行，不能用驗證組選參數（FR-011）")
    regions = ("TW", "US") if args.region == "all" else (args.region,)
    store = open_store(ctx)
    try:
        cutoff = parse_moment(args.cutoff) if args.cutoff else default_cutoff(store)
        ctx.progress.note(f"讀取資料（截止 {cutoff.strftime('%Y-%m-%d')}）")
        games = load_games(store, all_apps(store), cutoff)
        events = store.calendar_events()
        dataset = build_dataset(store, games, events, cutoff=cutoff, regions=regions, split=args.split)
        current, rows = run_grid(store, dataset, games, events, args.model, fixed, grid,
                                 out_dir=ctx.config.data_dir / "backtests", progress=ctx.progress.note)
    finally:
        store.close()
    chosen, notes = select(current, current["model"]["params"], rows)
    text = format_grid_record(date=now_utc().strftime("%Y-%m-%d"), name=args.model, split=args.split,
                              current=current, rows=rows, chosen=chosen, notes=notes)
    record = args.record_to or (args.config.resolve().parent / "docs" / "model" / "comparisons.md"
                                if args.record else None)
    if record:
        append_record(record, text)
    summary = {
        "split": args.split,
        "current": {"model": current["model"], **{r: v["brier"] for r, v in current["regions"].items()}},
        "rows": [{"params": r.params, "excluded": r.excluded, "files": list(r.files),
                  **{reg: {"brier": c.brier_b, "diff": c.diff, "interval": [c.low, c.high], "omitted": c.omitted}
                     for reg, c in r.comparison.regions.items()}} for r in rows],
        "chosen": chosen.params if chosen else None,
        "notes": notes,
        "record": str(record) if record else None,
        "seconds": round(time.monotonic() - started, 1),
    }
    errors = any(r.result.get("errors") for r in rows) or bool(current.get("errors"))
    return CommandResult(EXIT_OK if chosen and not errors else EXIT_PARTIAL, summary, text=text)


# --- feature 003: sweet-price decisions and the HTML report ---------------------------------------------

GROUP_TITLES = (("now", "現在買"), ("soon", "即將到價"), ("wait", "繼續等"), ("low", "低信心"), ("na", "無法預測"))


def write_text_atomic(path, text: str):
    """Write to <path>.tmp, then rename, so a reader never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path


def _calendar_notices(store: PriceStore, now: datetime) -> list[str]:
    """Feature 012 (plan D1): the sale-calendar alerts the user must act on; none when the file cannot be read (the
    daily update already reports that)."""
    try:
        return calendar_sync.calendar_notices(store.conn, calendar.load_calendar(store.calendar_path, now=now), now=now)
    except calendar.CalendarError:
        return []


def _with_comparison(batch, forecasts_dir):
    """Attach the baseline comparison and per-game changes to an official batch (FR-019 to FR-021)."""
    base_path, base, skipped = records.find_baseline(forecasts_dir, batch.as_of)
    changes, comparison = compare(decision_to_dict(batch), base, file=base_path.name if base_path else None,
                                  as_of=base["as_of"] if base else None, skipped=skipped)
    return replace(batch, comparison=comparison,
                   decisions=tuple(replace(d, change=changes[d.app_id]) for d in batch.decisions))


def _write_extension_data(ctx: Context, data: dict, record_status: dict | None) -> str | None:
    """Feature 011 (contracts/extension-ui.md): the extension's data file, only when the extension folder exists.
    A failure leaves the report and the record as they are (constitution III) and is reported."""
    folder = ctx.config.extension_dir
    if not (folder / "manifest.json").exists():
        return None
    target = folder / "data" / "sweetspot-extension.json"
    try:
        payload = extension_data.build(data, record=record_status, config_path=ctx.config.path)
        write_text_atomic(target, extension_data.dumps(payload))
    except Exception as exc:  # noqa: BLE001 - the report is already written
        message = f"{type(exc).__name__}: {exc}"
        ctx.progress.note(f"擴充功能資料未寫入：{message}")
        return f"未寫入：{message}"
    return str(target)


@command("report")
def report_command(ctx: Context, args: argparse.Namespace) -> CommandResult:
    started = time.monotonic()
    rule = args.rule or decision_rule.CURRENT_RULE
    preview = rule != decision_rule.CURRENT_RULE          # feature 005: a preview is never official, never a baseline
    official = not args.as_of and not preview
    now = NOW()
    as_of = parse_moment(args.as_of) if args.as_of else now
    store = open_store(ctx)
    try:
        notices = _calendar_notices(store, now) if official else []
        has_key = ctx.secrets.steam_web_api_key is not None
        small = reference_notice(reference.dataset_size(store), has_steam_key=has_key,
                                 complete=lambda: reference.sampling_complete(store, ctx.config, has_steam_key=has_key))
        batch = run_decisions(store, store.wishlist_apps(), as_of, current_model(), ctx.config.preferences, now=now,
                              official=official, update_exit=args.update_exit, rule=rule,
                              choices=ctx.config.purchase_options, calendar_notices=notices, reference_notice=small)
    finally:
        store.close()
    forecasts_dir = ctx.config.data_dir / "forecasts"
    record_status = None
    if official:
        batch = _with_comparison(batch, forecasts_dir)
    data = decision_to_dict(batch)
    if official:
        try:
            record_status = {"saved": True, "file": str(records.write_record(forecasts_dir, data))}
        except Exception as exc:  # noqa: BLE001 - the report is still written; the baseline does not advance
            record_status = {"saved": False, "error": f"{type(exc).__name__}: {exc}"}
    reports = ctx.config.data_dir / "reports"
    if preview:
        default = reports / f"preview-{rule}.html"
    else:
        default = reports / "latest.html" if official else reports / f"asof-{as_of.strftime('%Y-%m-%d')}.html"
    path = args.out or default
    page = {**data, "record": record_status} if record_status else dict(data)
    if preview:
        page["preview"] = True
    write_text_atomic(path, render(page))
    extension_status = _write_extension_data(ctx, data, record_status) if official else None
    if args.open:
        if OPEN_FILE is None:
            ctx.progress.note(f"無法自動開啟報告，請手動開啟：{path}")
        else:
            OPEN_FILE(path)
    counts = data["summary"]
    comparison = data["comparison"] or {}
    attention = (counts["decision_error"] or data["forecast"]["summary"]["model_error"]
                 or args.update_exit not in (None, 0) or (record_status and not record_status["saved"])
                 or comparison.get("skipped_records") or (extension_status or "").startswith("未寫入"))
    record_text = None
    if record_status:
        record_text = record_status["file"] if record_status["saved"] else f"未保存：{record_status['error']}"
    summary = {**{k: counts[k] for k in ("now", "soon", "wait", "low", "na", "decision_error", "changed")},
               "baseline": (comparison.get("baseline") or {}).get("file"), "record": record_text,
               "report": str(path), "preview": preview, "data_refresh": data["data_refresh"], "extension": extension_status,
               "model": data["forecast"]["model"], "rule": {"name": data["rule"]["name"],
                                                            "version": data["rule"]["version"]},
               "as_of": data["as_of"], "warnings": data["warnings"], "seconds": round(time.monotonic() - started, 1)}
    for warning in data["warnings"]:
        ctx.progress.note(warning)
    lines = [f"{title}：{counts[g]} 款" for g, title in GROUP_TITLES]
    names = {d["app_id"]: d["name"] for d in data["decisions"]}
    lines += [f"變動：{names[d['app_id']]}" for d in data["decisions"] if d["change"]]
    return CommandResult(EXIT_PARTIAL if attention else EXIT_OK, summary, text="\n".join(lines))


@command("backtest-rule")
def backtest_rule_command(ctx: Context, args: argparse.Namespace) -> CommandResult:
    started = time.monotonic()
    rule = args.rule or decision_rule.CURRENT_RULE
    costs = _wait_costs(args.wait_cost, rule)
    model = model_from_args(args)
    store = open_store(ctx)
    try:
        cutoff = parse_moment(args.cutoff) if args.cutoff else default_cutoff(store)
        ctx.progress.note(f"讀取資料（截止 {cutoff.strftime('%Y-%m-%d')}）")
        games = load_games(store, all_apps(store), cutoff)
        events = store.calendar_events()
        dataset = build_dataset(store, games, events, cutoff=cutoff, regions=("TW",), apps_limit=args.apps_limit,
                                split=args.split)
    finally:
        store.close()
    runs = run_rule_backtests(dataset, games, events, model, ctx.config.preferences,
                              out_dir=ctx.config.data_dir / "backtests",
                              progress=lambda message: ctx.progress.note(message), rule=rule, wait_costs=costs)
    seconds = round(time.monotonic() - started, 1)
    summaries = [_rule_summary(result, path, args.split, seconds) for result, path in runs]
    partial = any(result["errors"] for result, _ in runs)
    return CommandResult(EXIT_PARTIAL if partial else EXIT_OK, summaries if len(summaries) > 1 else summaries[0])


def _wait_costs(text: str | None, rule: str) -> list[int] | None:
    """`--wait-cost 10,20`: whole NT$ 0-10,000 a month, only for a waiting-cost rule (005 contracts/cli.md)."""
    if text is None:
        return None
    if decision_rule.RULES[rule]["kind"] != "wait-cost":
        raise ValueError(f"規則 {rule} 不使用等待成本")
    try:
        costs = [int(part) for part in text.split(",")]
    except ValueError:
        costs = []
    if not costs or any(not 0 <= c <= 10000 for c in costs):
        raise ValueError("--wait-cost 必須是 0 到 10000 的整數，多個值以逗號分隔")
    return sorted(set(costs))


def _rule_summary(result: dict, path, split: str, seconds: float) -> dict:
    cost = result["preferences"].get("wait_cost_twd")
    at = lambda block: next((n["mean"] for n in block["overall"]["net_twd"] if n["cost_twd"] == cost), None)  # noqa
    summary = {"result": str(path), "rule": result["rule"]["version"], "wait_cost_twd": cost,
               "model": result["model"], "split": split, "cutoff": result["dataset"]["cutoff"],
               "dataset_id": result["dataset"]["dataset_id"], "decisions": result["decisions"],
               "hit_rate": result["hit_rate"], "timing_error": {k: result["timing_error"][k] for k in ("n", "mean_abs")},
               "now_followup": result["now_followup"], "sweet_timing": result["sweet_timing"],
               "follow_advice": result["follow_advice"]["overall"],
               "follow_advice_monthly": result["follow_advice_monthly"]["overall"],
               "net_twd": None if cost is None else {"fixed": at(result["follow_advice"]),
                                                     "monthly": at(result["follow_advice_monthly"])},
               "hindsight": result["hindsight"], "report_figures": report_figures(result), "seconds": seconds}
    if "longer_horizon" in result:
        summary["longer_horizon"] = result["longer_horizon"]
    return summary


@command("compare-rule")
def compare_rule_command(ctx: Context, args: argparse.Namespace) -> CommandResult:
    """004 research R8 / 005 research R7: a base and one or more candidates, their net benefit, the wishlist."""
    current = json.loads(args.current.read_text(encoding="utf-8"))
    candidates = [json.loads(path.read_text(encoding="utf-8")) for path in args.candidates]
    comparisons = [compare_rule_results(current, c) for c in candidates]
    no_cost = lambda r: r["preferences"].get("wait_cost_twd") is None  # noqa: E731
    nets = [net_comparison(current, c, default_cost=DEFAULT_WAIT_COST,
                           cost=DEFAULT_WAIT_COST if no_cost(current) and no_cost(c) else None) for c in candidates]
    record = args.record_to or (args.config.resolve().parent / "docs" / "model" / "comparisons.md"
                                if args.record or args.decision else None)
    split = comparisons[0]["dataset"]["split"]
    rule = candidates[0]["rule"]["version"]
    if record and args.decision and args.attempt is not None and _recorded(record, rule, args.attempt):
        # the attempt is already recorded: append only the user's decision (append-only file; spec FR-018)
        title = RULE_VALIDATION_TITLE.format(rule=rule, n=args.attempt)
        append_record(record, f"## {now_utc().strftime('%Y-%m-%d')} · 使用者的決定：{title}\n\n{args.decision}\n")
        return CommandResult(EXIT_OK, {"record": str(record), "decision": args.decision, "attempt": args.attempt})
    if record:
        check_rule_attempt(record, split=split, rule=rule, attempt=args.attempt, change=args.change,
                           base_rule=current["rule"]["version"])
    wishlists: list = [None] * len(candidates)
    if not args.no_wishlist:
        store = open_store(ctx)
        try:
            apps = store.wishlist_apps()
            now = now_utc()
            batches = []
            for result in (current, *candidates):
                m = result["model"]
                model = build_model(m["name"], m["params"], m["version"])
                prefs = ctx.config.preferences
                if result["preferences"].get("wait_cost_twd") is not None:
                    prefs = replace(prefs, wait_cost_twd=result["preferences"]["wait_cost_twd"])
                batches.append(decision_to_dict(run_decisions(store, apps, now, model, prefs, now=now,
                                                              rule=result["rule"]["version"])))
        finally:
            store.close()
        wishlists = [wishlist_diff(batches[0], b, (n or {}).get("cost_twd")) for b, n in zip(batches[1:], nets)]
    labels = ["基準"] + [f"c{n['cost_twd']}" if n else f"候選 {i + 1}" for i, n in enumerate(nets)]
    by_cost = net_by_cost(list(zip(labels, (current, *candidates))))
    date = now_utc().strftime("%Y-%m-%d")
    files = [args.current.name, *(p.name for p in args.candidates)]
    if len(candidates) == 1 and nets[0] is None and args.attempt is None:          # a 004-style comparison
        text = format_rule_record(date=date, comparison=comparisons[0], files=tuple(files), wishlist=wishlists[0],
                                  decision=args.decision)
    else:
        text = format_rule_records(date=date, comparisons=comparisons, nets=nets, by_cost=by_cost, files=files,
                                   wishlists=wishlists, decision=args.decision, attempt=args.attempt,
                                   change=args.change, rule=rule)
    if record:
        append_record(record, text)
    summary = {"current": comparisons[0]["a"]["label"], "candidate": comparisons[0]["b"]["label"],
               "candidates": [c["b"]["label"] for c in comparisons], "dataset": comparisons[0]["dataset"],
               "rows": comparisons[0]["rows"], "net": [n for n in nets if n], "net_by_cost": by_cost,
               "wishlist": wishlists[0] if len(wishlists) == 1 else wishlists,
               "record": str(record) if record else None}
    return CommandResult(EXIT_OK, summary, text=text)




def _recorded(record, rule: str, attempt: int) -> bool:
    title = RULE_VALIDATION_TITLE.format(rule=rule, n=attempt)
    return record.exists() and any(line.startswith("## ") and line.endswith(title)
                                   for line in record.read_text(encoding="utf-8").splitlines())


# --- feature 007: non-seasonal forecasts ---------------------------------------------------------------

def ns_model_from_args(args: argparse.Namespace):
    """--model / --param on top of CURRENT_NS_MODEL. Before adoption without --param: the defaults, with a note."""
    current = nonseasonal.CURRENT_NS_MODEL
    name = args.model or (current[0] if current else "non-seasonal")
    params = dict(current[2]) if current and name == current[0] else {}
    params.update(parse_params(args.param))
    note = None
    if current is None and not args.param:
        defaults = ", ".join(f"{k}={v}" for k, v in nonseasonal.DEFAULT_PARAMS.items())
        note = f"非季節模型尚未採用，使用預設參數 {defaults}"
    return nonseasonal.build_ns_model(name, params), note


def _ns_setup(ctx: Context, args: argparse.Namespace, split: str):
    store = open_store(ctx)
    try:
        cutoff = parse_moment(args.cutoff) if args.cutoff else default_cutoff(store)
        ctx.progress.note(f"讀取資料（截止 {cutoff.strftime('%Y-%m-%d')}）")
        games = load_games(store, all_apps(store), cutoff)
        events = store.calendar_events()
        dataset = build_dataset(store, games, events, cutoff=cutoff, regions=("TW",),
                                apps_limit=getattr(args, "apps_limit", None), split=split)
    finally:
        store.close()
    return dataset, games, events


def _earlier_at_threshold(result: dict) -> dict | None:
    e = result.get("earlier")
    if not e:
        return None
    row = next((r for r in e["thresholds"] if r["threshold"] == nonseasonal.EARLIER_THRESHOLD), None)
    return {"eligible": e["eligible"], "threshold": nonseasonal.EARLIER_THRESHOLD,
            "said": row["said"] if row else None, "hit": row["hit"] if row else None,
            "rate": row["rate"] if row else None}


@command("ns-backtest")
def ns_backtest_command(ctx: Context, args: argparse.Namespace) -> CommandResult:
    started = time.monotonic()
    model, note = ns_model_from_args(args)
    dataset, games, events = _ns_setup(ctx, args, args.split)
    result, path = ns_backtest.run_ns_backtest(dataset, games, events, model, earlier=not args.no_earlier,
                                               out_dir=ctx.config.data_dir / "backtests",
                                               progress=lambda message: ctx.progress.note(message))
    summary = {
        "result": str(path), "model": result["model"], "model_note": note,
        "cutoff": result["dataset"]["cutoff"], "split": args.split, "games": result["dataset"]["games"],
        "as_of_count": len(result["dataset"]["schedule"]), "units": result["units"],
        "brier": result["brier"], "reference_brier": result["reference_brier"],
        "by_horizon": {h: v["brier"] for h, v in result["by_horizon"].items()},
        "earlier": _earlier_at_threshold(result), "errors": len(result["errors"]),
        "seconds": round(time.monotonic() - started, 1),
    }
    return CommandResult(EXIT_PARTIAL if result["errors"] else EXIT_OK, summary)


@command("ns-grid")
def ns_grid_command(ctx: Context, args: argparse.Namespace) -> CommandResult:
    started = time.monotonic()
    if args.split == "validation":
        raise GridError("網格只能在調參組或全部資料上執行，不能用驗證組選參數（feature 007 spec FR-009）")
    grid = parse_grid(args.grid)
    fixed = parse_params(args.param)
    dataset, games, events = _ns_setup(ctx, args, args.split)
    rows = ns_backtest.run_ns_grid(dataset, games, events, args.model, fixed, grid, earlier=not args.no_earlier,
                                   out_dir=ctx.config.data_dir / "backtests", progress=ctx.progress.note)
    chosen, notes = ns_backtest.select_ns([(p, r) for p, r, _ in rows])
    text = ns_backtest.format_ns_grid_record(date=now_utc().strftime("%Y-%m-%d"), split=args.split,
                                             rows=[(p, r) for p, r, _ in rows], chosen=chosen, notes=notes,
                                             files=[path.name for _, _, path in rows])
    record = args.record_to or (args.config.resolve().parent / "docs" / "model" / "comparisons.md"
                                if args.record else None)
    if record:
        append_record(record, text)
    summary_rows = []
    for params, result, path in rows:
        c = ns_backtest.compare_ns(result)
        summary_rows.append({"params": params, "brier": result["brier"], "reference_brier": result["reference_brier"],
                             "by_horizon": {h: v["brier"] for h, v in result["by_horizon"].items()},
                             "diff": c.diff, "interval": [c.low, c.high], "earlier": _earlier_at_threshold(result),
                             "errors": len(result["errors"]), "file": path.name})
    summary = {"split": args.split, "rows": summary_rows, "chosen": chosen, "notes": notes,
               "record": str(record) if record else None, "seconds": round(time.monotonic() - started, 1)}
    errors = any(r["errors"] for _, r, _ in rows)
    return CommandResult(EXIT_OK if chosen and not errors else EXIT_PARTIAL, summary, text=text)


@command("ns-compare")
def ns_compare_command(ctx: Context, args: argparse.Namespace) -> CommandResult:
    result = json.loads(args.result.read_text(encoding="utf-8"))
    against = json.loads(args.against.read_text(encoding="utf-8")) if args.against else None
    c = ns_backtest.compare_ns(result, against)
    record = args.record_to or (args.config.resolve().parent / "docs" / "model" / "comparisons.md"
                                if args.record else None)
    if record:
        ns_backtest.check_ns_attempt(record, c, args.attempt, args.change)
        files = [args.result.name] + ([args.against.name] if args.against else [])
        append_record(record, ns_backtest.format_ns_compare_record(
            c, date=now_utc().strftime("%Y-%m-%d"), files=files, attempt=args.attempt, change=args.change))
    summary = {"verdict": c.verdict, "split": c.split, "model": c.model, "against": c.against,
               "brier": c.brier, "brier_against": c.brier_against, "diff": c.diff, "interval": [c.low, c.high],
               "games": c.games, "by_horizon": {h: list(v) for h, v in c.by_horizon.items()},
               "earlier": _earlier_at_threshold(result), "record": str(record) if record else None}
    return CommandResult(EXIT_OK if c.verdict == "優於" else EXIT_PARTIAL, summary)


# --- feature 013: post-sale comparison ----------------------------------------------------------------

@command("review")
def review_command(ctx: Context, args: argparse.Namespace) -> CommandResult:
    from sweetspot import __version__

    started = time.monotonic()
    now = NOW()
    today = parse_moment(args.today) if args.today else now
    run = {"started_at": review_contract.iso(now), "seconds": None, "steamsage_version": __version__}
    store = open_store(ctx)
    try:
        target, data = run_review(store, ctx.config.data_dir / "forecasts", sale=args.sale, record=args.record,
                                  today=today, force=args.force, with_recompute=not args.no_recompute, run=run)
    finally:
        store.close()
    run["seconds"] = round(time.monotonic() - started, 1)
    sale = target.sale
    stem = target.record_path.name.removesuffix(records.SUFFIX)
    path = args.out or ctx.config.data_dir / "reviews" / f"{sale.season}-{sale.year}_{stem}_{today:%Y%m%d}.json"
    review_contract.write_review(path, data)
    code = EXIT_PARTIAL if review_partial(target, data) else EXIT_OK
    if args.doc:
        return CommandResult(code, {}, text=review_contract.doc_draft(data))
    text = review_contract.summary_text(data) + f"\n結果：{path}"
    return CommandResult(code, data["summary"] if args.json else {}, text=text)


# --- feature 015: the local program the extension calls (contracts/native-host.md) -------------------------------

HOST_ACTIONS = {"install": "安裝", "uninstall": "移除", "status": "狀態查詢"}


@command("host")
def host_command(ctx: Context, args: argparse.Namespace) -> CommandResult:
    """install / uninstall / status. No API key, no writer lock, no database (data-model §3)."""
    from sweetspot.host import install

    try:
        registry = install.default_registry()
        if args.action == "install":
            result = install.install(ctx.config, registry=registry)
            summary = {k: result[k] for k in ("extension_id", "launcher", "manifest")}
            return CommandResult(EXIT_OK, summary, text="\n".join(result["lines"]))
        if args.action == "uninstall":
            lines = install.uninstall(ctx.config, registry=registry)["lines"]
            return CommandResult(EXIT_OK, {"removed": True}, text="\n".join(lines))
        return CommandResult(EXIT_OK, install.status(ctx.config, registry=registry))
    except install.InstallError as exc:
        ctx.progress.note(f"本機程式{HOST_ACTIONS[args.action]}失敗：{exc}")
        return CommandResult(EXIT_FAILED, {"error": str(exc)})
