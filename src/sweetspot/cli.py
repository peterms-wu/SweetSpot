"""Command-line entry point (contracts/cli.md).

Exit codes: 0 completed, 2 completed with per-item problems, 1 whole run failed, 3 another update running,
4 only the files named before feature 016 exist: run `sweetspot migrate` first (016 contracts/migrate.md §4),
5 not set up yet: no settings file and no one to answer, run `sweetspot setup` (014 contracts/cli.md §2).
"""

import argparse
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from sweetspot import __version__, legacy, setup
from sweetspot.config import Config, ConfigError, Secrets, load_config, load_secrets
from sweetspot.lock import LockHeld, WriterLock
from sweetspot.logs import log_result, setup_logging
from sweetspot.store.writer import StoreWriter

EXIT_OK, EXIT_FAILED, EXIT_PARTIAL, EXIT_LOCKED, EXIT_NEEDS_MIGRATION = 0, 1, 2, 3, 4
EXIT_NOT_SET_UP = setup.EXIT_NOT_SET_UP            # 5 (feature 014)
WRITE_COMMANDS = {"update", "reference", "import-legacy", "calendar"}
READ_ONLY_COMMANDS = {"forecast", "backtest", "compare", "report", "backtest-rule", "grid", "compare-rule",
                      "ns-backtest", "ns-grid", "ns-compare", "review",
                      "host",   # no writer, no lock (002 FR-035, 003 R9); host: feature 015 install / uninstall / status
                      "coverage"}   # 001 contracts/cli.md: it only reads (it opened a writer until 014 T070)
# migrate (feature 016) is in neither set: main() hands it over before the settings file is read; it takes the lock itself
# setup (feature 014) neither: it writes only the settings file, after the 016 old-name check


class Progress:
    """Progress lines on stderr: '<step> 第 n/N 款' (FR-026)."""

    def __init__(self, stream: TextIO | None = None):
        self.stream = stream or sys.stderr

    def step(self, name: str, n: int, total: int) -> None:
        end = "\n" if n >= total else "\r"
        print(f"{name} 第 {n}/{total} 款", end=end, file=self.stream, flush=True)

    def note(self, message: str) -> None:
        print(message, file=self.stream, flush=True)


@dataclass
class Context:
    config: Config
    secrets: Secrets
    writer: StoreWriter | None
    progress: Progress
    warnings: list[str] = field(default_factory=list)


@dataclass
class CommandResult:
    exit_code: int
    summary: dict[str, Any]
    text: str | None = None       # human-readable lines printed before the summary (not with --json)


Handler = Callable[[Context, argparse.Namespace], CommandResult]
HANDLERS: dict[str, Handler] = {}


def command(name: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        HANDLERS[name] = fn
        return fn

    return register


class _Parser(argparse.ArgumentParser):
    """A wrong argument is exit 1 (contracts/cli.md), not argparse's 2, which here means 'done, but look' (014 T069).
    Sub-command parsers are made with the same class (add_subparsers takes the parent's)."""

    def error(self, message: str):
        self.print_usage(sys.stderr)
        self.exit(EXIT_FAILED, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", type=Path, default=Path("sweetspot.toml"), help="設定檔路徑")
    common.add_argument("--json", action="store_true", help="摘要以 JSON 輸出到 stdout")

    parser = _Parser(prog="sweetspot", description="Steam 願望清單價格資料工具")
    parser.add_argument("--version", action="version", version=f"sweetspot {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    update = sub.add_parser("update", parents=[common], help="日常更新")
    update.add_argument("--skip-reference", action="store_true", help="不執行參考資料集小批次")
    update.add_argument("--no-history", action="store_true", help="只更新清單與現價")

    reference = sub.add_parser("reference", parents=[common], help="建立或更新參考資料集")
    reference.add_argument("--limit", type=int)
    reference.add_argument("--budget", type=int, help="本次執行秒數上限")
    reference.add_argument("--pool", choices=["related", "broad", "refresh", "all"], default="all",
                           help="refresh：只更新過期的參考遊戲價格歷史")

    legacy = sub.add_parser("import-legacy", parents=[common], help="匯入舊專案快取")
    legacy.add_argument("path", nargs="?", type=Path)

    coverage = sub.add_parser("coverage", parents=[common], help="資料覆蓋摘要")
    coverage.add_argument("--app", type=int)
    coverage.add_argument("--scope", choices=["wishlist", "reference", "all"], default="wishlist")
    coverage.add_argument("--csv", type=Path)

    calendar = sub.add_parser("calendar", parents=[common], help="Steam 特賣行事曆")
    calendar.add_argument("--check", action="store_true")
    calendar.add_argument("--fetch", action="store_true", help="先讀取一次官方季節特賣頁面（1 個請求）")
    calendar.add_argument("--sync", action="store_true", help="列出官方頁面和 data/steam_sales.toml 的差異")
    calendar.add_argument("--write", action="store_true", help="和 --sync 一起用：把差異寫入 data/steam_sales.toml")

    model_args = argparse.ArgumentParser(add_help=False)
    model_args.add_argument("--model", help="模型名稱，可加 @版本（例如 seasonal-record@1.0.0），預設為現行模型")
    model_args.add_argument("--param", action="append", default=[], metavar="K=V", help="模型參數，可重複")

    forecast = sub.add_parser("forecast", parents=[common, model_args], help="折扣機率曲線預測（唯讀）")
    forecast.add_argument("--as-of", help="分析時點（YYYY-MM-DD，UTC），預設為現在")
    forecast.add_argument("--app", type=int, action="append", default=[], help="只預測指定的 AppID，可重複")
    forecast.add_argument("--scope", choices=["wishlist", "all"], default="wishlist")
    forecast.add_argument("--out", type=Path, help="把 steamsage.forecast/1 JSON 寫到檔案")

    backtest = sub.add_parser("backtest", parents=[common, model_args], help="回測模型（唯讀）")
    backtest.add_argument("--region", choices=["TW", "US", "all"], default="all")
    backtest.add_argument("--cutoff", help="資料截止日（YYYY-MM-DD），預設為最新的資料已知時間")
    backtest.add_argument("--apps-limit", type=int, help="只取前 N 款遊戲快速試跑（資料集識別碼會不同）")
    backtest.add_argument("--split", choices=["all", "tuning", "validation"], default="all",
                          help="只計分調參組或驗證組；整體比例仍用全部遊戲（資料集識別碼會不同）")

    grid = sub.add_parser("grid", parents=[common], help="在調參組上跑參數網格並依 FR-011 選參數（唯讀）")
    grid.add_argument("--model", required=True, help="模型名稱，可加 @版本；沒有版本時取最新版本")
    grid.add_argument("--grid", action="append", default=[], metavar="K=V1,V2", help="網格參數，可重複")
    grid.add_argument("--param", action="append", default=[], metavar="K=V", help="網格以外的固定參數，可重複")
    grid.add_argument("--split", choices=["all", "tuning", "validation"], default="tuning")
    grid.add_argument("--region", choices=["TW", "US", "all"], default="all")
    grid.add_argument("--cutoff", help="資料截止日（YYYY-MM-DD），預設為最新的資料已知時間")
    grid.add_argument("--record", action="store_true", help="附加網格紀錄到 docs/model/comparisons.md")
    grid.add_argument("--record-to", type=Path, help="附加網格紀錄到指定檔案（隱含 --record）")

    report = sub.add_parser("report", parents=[common], help="甜蜜價決策與 HTML 報告（資料庫唯讀）")
    report.add_argument("--as-of", help="過去的分析時點（YYYY-MM-DD，UTC），只供檢查：不寫紀錄、不比較")
    report.add_argument("--out", type=Path, help="報告路徑，預設 data/reports/latest.html")
    report.add_argument("--open", action="store_true", help="完成後用系統預設瀏覽器開啟報告")
    report.add_argument("--update-exit", type=int,          # any integer: a killed update's status too (014 T069)
                        help="更新資料.cmd 傳入的 update 結束代碼（0–5；其他代碼當作更新沒有完成）")
    report.add_argument("--rule", choices=["2.0.0", "2.1.0", "3.0.0", "3.1.0"],
                        help="預覽其他規則版本：不寫紀錄、不比較，輸出 data/reports/preview-<版本>.html（feature 005）")

    rule = sub.add_parser("backtest-rule", parents=[common, model_args], help="回測甜蜜價規則（唯讀，台灣區 12 個月內）")
    rule.add_argument("--rule", choices=["1.0.0", "2.0.0", "2.1.0", "3.0.0", "3.1.0"], help="規則版本，預設為現行規則")
    rule.add_argument("--wait-cost", help="規則 3.0.0 的等待成本（元／月），可用逗號分隔多個值；預設為設定檔的值")
    rule.add_argument("--split", choices=["all", "tuning", "validation"], default="all",
                      help="只評分調參組或驗證組；整體比例仍用全部遊戲")
    rule.add_argument("--cutoff", help="資料截止日（YYYY-MM-DD），預設為最新的資料已知時間")
    rule.add_argument("--apps-limit", type=int, help="只取前 N 款遊戲快速試跑（資料集識別碼會不同）")

    compare_rule = sub.add_parser("compare-rule", parents=[common], help="並列兩份規則回測結果與願望清單差異（唯讀）")
    compare_rule.add_argument("current", type=Path, help="現行組合的規則回測結果")
    compare_rule.add_argument("candidates", type=Path, nargs="+",
                              help="候選組合的規則回測結果，可以多份（例如規則 3.0.0 的多個 c）")
    compare_rule.add_argument("--attempt", type=int, help="驗證組比較的次數 1–3（feature 005 spec FR-014）")
    compare_rule.add_argument("--change", help="這次比較改了什麼、為什麼改（第 2、3 次必填）")
    compare_rule.add_argument("--no-wishlist", action="store_true", help="不列出願望清單差異")
    compare_rule.add_argument("--record", action="store_true", help="附加並列紀錄到 docs/model/comparisons.md")
    compare_rule.add_argument("--record-to", type=Path, help="附加並列紀錄到指定檔案（隱含 --record）")
    compare_rule.add_argument("--decision", help="使用者的決定，附在紀錄最後（隱含 --record）")

    compare = sub.add_parser("compare", parents=[common], help="比較兩份回測結果（唯讀）")
    compare.add_argument("current", type=Path, help="現行模型（或比較基準）的回測結果")
    compare.add_argument("candidate", type=Path, help="候選模型的回測結果")
    compare.add_argument("--record", action="store_true", help="附加比較紀錄到 docs/model/comparisons.md")
    compare.add_argument("--record-to", type=Path, help="附加比較紀錄到指定檔案（隱含 --record）")
    compare.add_argument("--attempt", type=int, help="驗證組比較的第幾次（1–3，驗證組紀錄必填）")
    compare.add_argument("--change", help="這次比較改了什麼、為什麼改（第 2、3 次必填）")
    compare.add_argument("--target-groups", help="另外要求這些本身場數組的台灣區 Brier 都較低，例如 0,1（feature 008）")

    # feature 007: non-seasonal forecasts
    ns_model = argparse.ArgumentParser(add_help=False)
    ns_model.add_argument("--model", help="非季節模型名稱，預設為現行（未採用時為 non-seasonal）")
    ns_model.add_argument("--param", action="append", default=[], metavar="K=V", help="模型參數，可重複")
    ns_common = argparse.ArgumentParser(add_help=False)
    ns_common.add_argument("--cutoff", help="資料截止日（YYYY-MM-DD），預設為最新的資料已知時間")
    ns_common.add_argument("--no-earlier", action="store_true",
                           help="不計算「可能更早到價」的命中率（省下季節模型與規則的決策）")

    ns_backtest = sub.add_parser("ns-backtest", parents=[common, ns_model, ns_common],
                                 help="回測非季節預測（唯讀，台灣區 30／60／90 天）")
    ns_backtest.add_argument("--split", choices=["all", "tuning", "validation"], default="all")
    ns_backtest.add_argument("--apps-limit", type=int, help="只取前 N 款遊戲快速試跑（資料集識別碼會不同）")

    ns_grid = sub.add_parser("ns-grid", parents=[common, ns_common], help="在調參組上跑非季節模型的參數網格（唯讀）")
    ns_grid.add_argument("--model", default="non-seasonal", help="非季節模型名稱")
    ns_grid.add_argument("--grid", action="append", default=[], metavar="K=V1,V2", help="網格參數，可重複")
    ns_grid.add_argument("--param", action="append", default=[], metavar="K=V", help="網格以外的固定參數，可重複")
    ns_grid.add_argument("--split", choices=["all", "tuning", "validation"], default="tuning")
    ns_grid.add_argument("--record", action="store_true", help="附加網格紀錄到 docs/model/comparisons.md")
    ns_grid.add_argument("--record-to", type=Path, help="附加網格紀錄到指定檔案（隱含 --record）")

    ns_compare = sub.add_parser("ns-compare", parents=[common], help="比較非季節回測結果與整體比例或另一份結果（唯讀）")
    ns_compare.add_argument("result", type=Path, help="非季節回測結果")
    ns_compare.add_argument("--against", type=Path, help="另一份結果；不給時和整體比例比較")
    ns_compare.add_argument("--record", action="store_true", help="附加比較紀錄到 docs/model/comparisons.md")
    ns_compare.add_argument("--record-to", type=Path, help="附加比較紀錄到指定檔案（隱含 --record）")
    ns_compare.add_argument("--attempt", type=int, help="非季節驗證組比較的第幾次（1–3，驗證組紀錄必填）")
    ns_compare.add_argument("--change", help="這次比較改了什麼、為什麼改（第 2、3 次必填）")

    # feature 013: post-sale comparison
    review = sub.add_parser("review", parents=[common], help="事後對照：開賣前的正式紀錄 vs 季節特賣的實際價格（唯讀）")
    review.add_argument("--sale", help="季節特賣，例如 autumn-2026；預設最近一場已結束的")
    review.add_argument("--record", help="指定紀錄（data/forecasts/ 中的檔名或路徑）；預設開賣前最後一份正式紀錄")
    review.add_argument("--today", help="執行對照的時點（YYYY-MM-DD，UTC）；決定非季節期間是否到期，預設現在")
    review.add_argument("--force", action="store_true", help="特賣結束不到 3 天也執行（結果標示資料可能不完整）")
    review.add_argument("--no-recompute", action="store_true", help="不在分析時點重算現行與基準模型")
    review.add_argument("--doc", action="store_true", help="stdout 改印 comparisons.md「事後對照」一節的草稿")
    review.add_argument("--out", type=Path, help="結果 JSON 的路徑，預設 data/reviews/<特賣>_<紀錄>_<今天>.json")

    # feature 015: the local program the Chrome extension calls to choose an edition
    host = sub.add_parser("host", parents=[common], help="本機程式：讓擴充功能在 Steam 遊戲頁指定追蹤版本")
    host.add_argument("action", choices=["install", "uninstall", "status"],
                      help="install：登記到目前使用者的 Chrome；uninstall：移除；status：顯示登記狀態")

    # feature 016: one-off move of the files named before the rename; handled before the settings file is read
    migrate = sub.add_parser("migrate", parents=[common],
                             help="一次性：把改名前（feature 016 之前）的設定檔、資料庫、擴充功能資料檔搬到新名稱")
    migrate.add_argument("--dry-run", action="store_true", help="只列出會做什麼，不改任何檔案")

    # feature 014: the first run asks for the user's own wishlist; only this writes the settings file
    setup_cmd = sub.add_parser("setup", parents=[common], help="第一次設定：輸入自己的 Steam 願望清單網址，建立設定檔")
    setup_cmd.add_argument("--change", action="store_true", help="已經設定過時，改用另一份願望清單（只改網址那一行）")

    # feature 014: the daily background update in the Task Scheduler (no administrator rights needed)
    schedule_cmd = sub.add_parser("schedule", parents=[common], help="每日背景更新：在工作排程器註冊、移除或查看")
    schedule_cmd.add_argument("action", choices=["install", "uninstall", "status"],
                              help="install：每天 02:30 背景更新；uninstall：移除；status：上次與下次執行")
    schedule_cmd.add_argument("--name", default="SweetSpot 每日背景更新", help="排程工作的名稱")
    schedule_cmd.add_argument("--replace", action="store_true", help="install：同名的工作已存在時取代它")
    schedule_cmd.add_argument("--dry-run", action="store_true", help="install：只列出會建立的設定，不改任何東西")
    return parser


def _print_summary(summary: dict[str, Any] | list[dict[str, Any]], as_json: bool, out: TextIO) -> None:
    if as_json:
        print(json.dumps(summary, ensure_ascii=False, indent=2), file=out)
        return
    if isinstance(summary, list):                      # one summary per waiting cost (feature 005)
        for n, part in enumerate(summary):
            if n:
                print("", file=out)
            _print_summary(part, False, out)
        return
    for key, value in summary.items():
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        print(f"{key}: {value}", file=out)


def _utf8_when_redirected() -> None:
    """Consoles get Unicode natively (UTF-8); pipes, files and NUL would otherwise use the ANSI code page (cp950).
    Decided by the encoding, not isatty(): NUL (`> /dev/null`, `> nul`) is a character device, so isatty() is True
    there although it is no console, and printing a character outside cp950 failed (2026-10-18)."""
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", None) or "").replace("-", "").replace("_", "").lower()
        if hasattr(stream, "reconfigure") and encoding != "utf8":
            stream.reconfigure(encoding="utf-8")


def _old_database_refused(config: Path, stderr: TextIO) -> bool:
    """For the commands handled before load_config (014 setup, schedule): next to an old-name database only, the
    016 refusal comes first, as for every other command."""
    if not Path(config).exists():
        return False
    old = legacy.db_blocker(legacy.read_data_dir(Path(config).resolve().parent) / legacy.DB.new)
    if old is not None:
        print(legacy.refusal(old), file=stderr)
    return old is not None


def main(argv: list[str] | None = None, stdout: TextIO | None = None, stderr: TextIO | None = None) -> int:
    if stdout is None and stderr is None:
        _utf8_when_redirected()
    stdout, stderr = stdout or sys.stdout, stderr or sys.stderr
    args = build_parser().parse_args(argv)
    if args.command == "migrate":                      # before load_config: the new settings file may not exist yet
        from sweetspot import migrate

        return migrate.main(args, stdout, stderr)
    # feature 016 FR-010: with only the old-name file, refuse before load_config / a writer would create an empty one
    old = legacy.config_blocker(args.config)
    if old is not None:
        print(legacy.refusal(old), file=stderr)
        return EXIT_NEEDS_MIGRATION
    if args.command == "setup":                        # feature 014: writes only the settings file
        if _old_database_refused(args.config, stderr):
            return EXIT_NEEDS_MIGRATION
        return setup.main(args, stdout, stderr)
    if not Path(args.config).exists():                 # feature 014 FR-001: ask now, or refuse with 5 and create nothing
        code = setup.ensure(args.config, stdout, stderr)
        if code != EXIT_OK:
            return code
    if args.command == "schedule":                     # feature 014: needs only the folder, not the database
        from sweetspot import schedule

        if _old_database_refused(args.config, stderr):
            return EXIT_NEEDS_MIGRATION
        return schedule.main(args, stdout, stderr)
    try:
        config, warnings = load_config(args.config)
    except ConfigError as exc:
        print(f"設定錯誤：{exc}", file=stderr)
        return EXIT_FAILED
    old = legacy.db_blocker(config.db_path)
    if old is not None:
        print(legacy.refusal(old), file=stderr)
        return EXIT_NEEDS_MIGRATION
    for warning in warnings:
        print(f"警告：{warning}", file=stderr)
    for old in legacy.leftovers(config.path, config.db_path, config.extension_dir):    # FR-011
        print(f"警告：舊名稱的檔案還在（{old.name}），沒有使用；確認不需要後可以自行刪除", file=stderr)
    secrets = load_secrets()
    setup_logging(config.data_dir, secrets.redaction_values())
    started = time.monotonic()
    progress = Progress(stderr)

    def done(code: int, summary: Any = None, note: str | None = None) -> int:
        """Every exit after the log is set up leaves one result line in the daily log (2026-10-18)."""
        log_result(args.command, code, time.monotonic() - started, summary, note)
        return code

    handler = HANDLERS.get(args.command)
    if handler is None:
        print(f"指令 {args.command} 尚未實作", file=stderr)
        return done(EXIT_FAILED, note="尚未實作")

    read_only = args.command in READ_ONLY_COMMANDS
    lock = WriterLock(config.data_dir / ".lock") if args.command in WRITE_COMMANDS else None
    try:
        if lock:
            lock.acquire()
    except LockHeld as exc:
        print(str(exc), file=stderr)
        return done(EXIT_LOCKED, note=str(exc))

    writer = None
    try:
        writer = None if read_only else StoreWriter.open(config.db_path)
        if writer is not None and writer.migration:
            m = writer.migration
            backup = f"已備份 {m['backup'].name}，" if m.get("backup") else ""
            tagged = f"補上 {m['tagged']} 列的 ITAD 商品 id" if m.get("tagged") is not None else "結構已更新"
            progress.note(f"資料庫升級到 v{m['to']}：{backup}{tagged}（{m['seconds']} 秒）")
        if lock:
            interrupted = writer.mark_interrupted_runs()
            if interrupted:
                progress.note(f"上次有 {len(interrupted)} 個執行被中斷，已標記為 interrupted")
        result = handler(Context(config, secrets, writer, progress, warnings), args)
    except Exception as exc:  # whole-run failure: report, keep existing data intact
        extras = getattr(exc, "__notes__", ())           # what the command added for the user (e.g. 014 T049)
        note = " ".join(" ".join(part.split()) for part in (f"執行失敗：{type(exc).__name__}: {exc}", *extras))
        for secret in secrets.redaction_values():        # the notes too: a library's note may hold a key (014 T057)
            note = note.replace(secret, "***")
        print(note, file=stderr)
        return done(EXIT_FAILED, note=note)
    finally:
        if writer:
            writer.close()
        if lock:
            lock.release()

    try:
        if result.text and not args.json:
            print(result.text, file=stdout)
        _print_summary(result.summary, args.json, stdout)
    except Exception as exc:                           # e.g. a console that cannot show a character: still logged
        done(EXIT_FAILED, result.summary, note=f"輸出失敗：{type(exc).__name__}")
        raise
    return done(result.exit_code, result.summary)


# Register command handlers (imported for their @command side effects).
from sweetspot import commands as _commands  # noqa: E402,F401
