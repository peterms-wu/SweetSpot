"""What the local program does with one request (feature 015; data-model §2, contracts/native-host.md).

status reads the settings file. choose / reset take the host lock and the writer lock, check the request against
the settings file and the database as they are now (spec FR-016), change one line of [purchase_options], and run
the official report in this process exactly as `sweetspot report` does (FR-007, FR-012). When the report fails,
the settings file, the HTML report and the extension data file go back to what they were; a record the report
already saved stays (constitution IV; plan D5).
"""

import io
import json
import logging
import os
import time
from datetime import timedelta
from pathlib import Path

from sweetspot import __version__, cli, commands
from sweetspot.choices import TRACKED_STATES, resolve_choice
from sweetspot.config import ConfigError, Config, load_config
from sweetspot.host import protocol, toml_edit
from sweetspot.host.protocol import BadRequest, Request
from sweetspot.lock import LockHeld, WriterLock
from sweetspot.logs import RedactingFilter
from sweetspot.store.query import PriceStore

log = logging.getLogger("sweetspot.host")
TAIPEI = timedelta(hours=8)
RESTORED = "，設定檔與報告已還原"
MESSAGES = {
    "bad-request": "請求格式不正確",
    "busy-host": "上一個指定還在處理",
    "busy-update": "背景更新進行中，請稍後再試",
    "not-tracked": "這款遊戲不在願望清單的追蹤範圍",
}
NOT_CHOOSABLE = {
    "no-record": "這款遊戲還沒有購買選項紀錄",
    "not-offered": "它目前不在 Steam 的購買選項中",
    "not-edition": "它不是這款遊戲的版本：{detail}",
    "not-in-itad": "ITAD 沒有對應的商品，沒有價格歷史",
    "rejected": "ITAD 商品核對未通過：{detail}",
}
FAILED = {"report": "報告產生失敗", "record": "正式紀錄沒有保存", "extension-data": "擴充功能資料沒有寫入",
          "internal": "本機程式發生錯誤"}


class Refused(Exception):
    def __init__(self, code: str, message: str | None = None, **extra):
        super().__init__(code)
        self.code, self.message, self.extra = code, message or MESSAGES[code], extra


def _refusal(code: str, message: str, **extra) -> dict:
    return {"v": protocol.VERSION, "ok": False, "code": code, "message": message, **extra}


def _ref(option: tuple[str, int] | None) -> str | None:
    return None if option is None else f"{option[0]}/{option[1]}"


def _write_atomic(path: Path, data: bytes) -> None:
    """Temporary file, then rename: a reader never sees half a file (spec FR-008)."""
    tmp = path.with_name(path.name + ".host-tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def bad_request(exc: BadRequest) -> dict:
    """A frame or request that is not one of the three forms; only its size is logged (data-model §4)."""
    size = "?" if exc.size is None else exc.size
    log.info(f"host request result=rejected code=bad-request bytes={size}")
    return _refusal("bad-request", MESSAGES["bad-request"])


def answer(stream, *, config_path: Path) -> dict | None:
    """Read one frame from the channel and answer it; None at end of input (Chrome closed the channel)."""
    try:
        message = protocol.read_message(stream)
    except BadRequest as exc:
        return bad_request(exc)
    return None if message is None else handle(message, config_path=config_path)


def handle(obj: dict, *, config_path: Path) -> dict:
    """The reply to one request object (already read from the channel)."""
    try:
        req = protocol.validate(obj)
    except BadRequest as exc:
        if exc.size is None:
            exc.size = len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))
        return bad_request(exc)
    redact = RedactingFilter(cli.load_secrets().redaction_values()).redact
    started = time.monotonic()
    try:
        reply = _status(req, Path(config_path)) if req.cmd == "status" else _change(req, Path(config_path), redact,
                                                                                    started)
    except Refused as exc:
        reply = _refusal(exc.code, redact(exc.message), **exc.extra)
    except Exception as exc:  # noqa: BLE001 - every request gets an answer and a log line
        reply = _refusal("internal", f"{FAILED['internal']}（{type(exc).__name__}）")
    _log(req, reply)
    return reply


def _log(req: Request, reply: dict) -> None:
    head = f"host {req.cmd} app={req.app}" + (f" option={_ref(req.option)}" if req.option else "")
    if not reply["ok"]:
        result = "failed" if reply.get("step") or reply["code"] in ("restore", "internal") else "rejected"
        log.info(f"{head} result={result} code={reply['code']}")
    elif req.cmd == "status":
        tail = "" if reply["config_ok"] else " config_ok=false"
        log.info(f"{head} result=ok choice={reply['choice'] or 'none'}{tail}")
    elif reply["changed"]:
        log.info(f"{head} result=ok changed=true seconds={reply['seconds']}" + (" partial=true" if reply["partial"] else ""))
    else:
        log.info(f"{head} result=ok changed=false")


def _read_settings(config_path: Path) -> tuple[bytes, str]:
    if not config_path.is_file():
        raise Refused("config-invalid", "找不到設定檔 sweetspot.toml")
    raw = config_path.read_bytes()
    try:
        return raw, raw.decode("utf-8")
    except UnicodeDecodeError:
        raise Refused("config-invalid", "設定檔有錯誤，請先修正 sweetspot.toml（不是 UTF-8）") from None


def _status(req: Request, config_path: Path) -> dict:
    reply = {"v": protocol.VERSION, "ok": True, "cmd": "status", "app": req.app, "choice": None, "config_ok": True,
             "host": __version__}
    try:
        _, text = _read_settings(config_path)
        reply["choice"] = _ref(toml_edit.current_choice(text, req.app))
    except (Refused, toml_edit.ConfigInvalid) as exc:
        detail = exc.message if isinstance(exc, Refused) else f"設定檔有錯誤，請先修正 sweetspot.toml（{exc}）"
        reply.update(config_ok=False, message=detail)
    return reply


def _change(req: Request, config_path: Path, redact, started: float) -> dict:
    _read_settings(config_path)
    try:
        config, _ = load_config(config_path)
    except ConfigError as exc:
        raise Refused("config-invalid", f"設定檔有錯誤，請先修正 sweetspot.toml（{exc}）") from None
    host_lock = WriterLock(config.data_dir / ".host.lock")
    try:
        host_lock.acquire()
    except LockHeld:
        raise Refused("busy-host") from None
    try:
        writer_lock = WriterLock(config.data_dir / ".lock")
        try:
            writer_lock.acquire()
        except LockHeld:
            raise Refused("busy-update") from None
        try:
            return _apply(req, config, config_path, redact, started)
        finally:
            writer_lock.release()
    finally:
        host_lock.release()


def _apply(req: Request, config: Config, config_path: Path, redact, started: float) -> dict:
    raw, text = _read_settings(config_path)            # read again under the locks: this is what gets changed
    try:
        current = toml_edit.current_choice(text, req.app)
    except toml_edit.ConfigInvalid as exc:
        raise Refused("config-invalid", f"設定檔有錯誤，請先修正 sweetspot.toml（{exc}）") from None
    now = commands.NOW()
    store = PriceStore.open(config.db_path, config.data_dir / "steam_sales.toml")
    try:
        if req.app not in set(store.wishlist_apps(TRACKED_STATES)):    # the daily update's scope (014 T074)
            raise Refused("not-tracked")
        records = store.purchase_options([req.app], now).get(req.app)
    finally:
        store.close()
    target, name = None, None
    if req.cmd == "choose":
        chosen = resolve_choice(records, req.option)
        if not chosen.active:
            why = NOT_CHOOSABLE[chosen.code].format(detail=chosen.detail or "")
            raise Refused("not-choosable", f"這個版本不能指定（{why}）")
        if chosen.record.role != "default":            # choosing the Steam default is a reset (spec FR-003)
            target, name = req.option, chosen.record.name
    done = {"v": protocol.VERSION, "ok": True, "cmd": req.cmd, "app": req.app}
    if req.option:
        done["option"] = _ref(req.option)
    if target == current:
        return {**done, "changed": False}
    try:
        new_text = toml_edit.set_choice(text, req.app, target, name=name, today=(now + TAIPEI).strftime("%Y-%m-%d"))
    except toml_edit.ConfigUnsafe as exc:
        raise Refused("config-unsafe", f"設定檔中這款遊戲的寫法無法自動修改（{exc}），請手動修改") from None
    except toml_edit.ConfigInvalid as exc:
        raise Refused("config-invalid", f"設定檔有錯誤，請先修正 sweetspot.toml（{exc}）") from None

    outputs = [config.data_dir / "reports" / "latest.html", config.extension_dir / "data" / "sweetspot-extension.json"]
    saved = {path: path.read_bytes() if path.exists() else None for path in outputs}
    try:
        _write_atomic(config_path, new_text.encode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - nothing was changed
        raise Refused("config-write", f"設定檔寫入失敗（{type(exc).__name__}: {exc}）",
                      step="config-write") from None
    try:
        code, summary, err = _run_report(config_path)
        failure = _failure(code, summary, err)
    except Exception as exc:  # noqa: BLE001 - roll back whatever happened
        failure = ("internal", type(exc).__name__)
    if failure is None:
        return {**done, "changed": True, "seconds": round(time.monotonic() - started, 1), "partial": code != 0}
    step, detail = failure
    problem = _restore(config, config_path, raw, saved, now)
    if problem:
        raise Refused("restore", problem, step=step)
    raise Refused(step, f"{FAILED[step]}（{detail}）{RESTORED}", step=step)


def _run_report(config_path: Path) -> tuple[int, dict | None, str]:
    """The same code path as `sweetspot report --config <file>` (an official run)."""
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(["report", "--config", str(config_path), "--json"], stdout=out, stderr=err)
    text = out.getvalue().strip()
    return code, json.loads(text) if text else None, err.getvalue()


def _after(text: str, prefix: str) -> str:
    return text.split(prefix, 1)[1].strip() if prefix in text else text


def _failure(code: int, summary: dict | None, err: str) -> tuple[str, str] | None:
    """research R5: exit 1, a record not saved, or no extension data file. Other exit-2 causes (one game's
    decision error, a skipped old record) are per-item problems, not failures (constitution III)."""
    if code == 1 or summary is None:
        line = next((ln for ln in err.splitlines() if ln.startswith("執行失敗：")), None)
        lines = [ln for ln in err.splitlines() if ln.strip()]
        return "report", _after(line, "執行失敗：") if line else (lines[-1] if lines else f"結束代碼 {code}")
    record = summary.get("record") or ""
    if record.startswith("未保存"):
        return "record", _after(record, "未保存：")
    extension = summary.get("extension")
    if extension is None:
        return "extension-data", "擴充功能資料夾不存在"
    if extension.startswith("未寫入"):
        return "extension-data", _after(extension, "未寫入：")
    return None


def _restore(config: Config, config_path: Path, raw: bytes, saved: dict[Path, bytes | None], now) -> str | None:
    """Put the settings file and the outputs back; None when everything was restored, else what to tell the user."""
    problem = None
    try:
        _write_atomic(config_path, raw)
    except Exception:  # noqa: BLE001 - keep the original somewhere the user can find it
        host = config.data_dir / "host"
        host.mkdir(parents=True, exist_ok=True)
        aside = host / f"restore-{now:%Y%m%dT%H%M%SZ}.toml"
        n = 1
        while aside.exists():
            aside = host / f"restore-{now:%Y%m%dT%H%M%SZ}-{n}.toml"
            n += 1
        aside.write_bytes(raw)
        try:
            shown = aside.relative_to(config_path.parent).as_posix()
        except ValueError:
            shown = str(aside)
        problem = f"還原失敗：請手動檢查 sweetspot.toml（原本的內容在 {shown}）"
    for path, data in saved.items():
        try:
            if data is None:
                path.unlink(missing_ok=True)
            else:
                _write_atomic(path, data)
        except Exception:  # noqa: BLE001
            problem = problem or "還原失敗：報告或擴充功能資料檔沒有改回，請重新執行 report"
    return problem
