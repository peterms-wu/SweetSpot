"""Logging to data/logs/ with a filter that removes API keys from every record (FR-028).

One file per local day (2026-10-18: was the UTC day, which put the 02:30 run in the previous day's file). Every
command ends with one result line (result_lines), so the daily files answer "did last night's run succeed" after
background-update.log has been overwritten by the next run."""

import json
import logging
import re
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

_KEY_PARAM = re.compile(r"(?i)\b(key=)[^&\s]+")
_LISTED = ("failures", "alerts", "warnings")   # summary lists whose items are logged when not empty
_MAX_TEXT = 120                               # longer strings in a summary are left out of the result line
_MAX_ITEMS = 500                              # characters of one listed summary list


class RedactingFilter(logging.Filter):
    def __init__(self, secrets: Iterable[str]):
        super().__init__()
        self._secrets = [s for s in secrets if s]

    def redact(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, "***")
        return _KEY_PARAM.sub(r"\1***", text)

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self.redact(record.getMessage())
        record.args = ()
        if record.exc_info and record.exc_info[1] is not None:
            record.exc_text = self.redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


def setup_logging(data_dir: Path, secrets: Iterable[str]) -> Path:
    """Attach a redacting file handler to the 'sweetspot' logger; returns the log file path."""
    log_dir = Path(data_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"sweetspot-{datetime.now():%Y%m%d}.log"
    logger = logging.getLogger("sweetspot")
    logger.setLevel(logging.INFO)
    for handler in list(logger.handlers):
        if getattr(handler, "_sweetspot", False):
            logger.removeHandler(handler)
            handler.close()
    handler = logging.FileHandler(path, encoding="utf-8")
    handler._sweetspot = True  # type: ignore[attr-defined]
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter(secrets))
    logger.addHandler(handler)
    return path


def result_lines(command: str, code: int, seconds: float, summary: Any = None, note: str | None = None) -> list[str]:
    """The end of one command, for the daily log: the exit code, the seconds, the summary's short values (a list as
    its length), then one line per non-empty failures / alerts / warnings list."""
    head = f"{command} 結束：代碼 {code}，{seconds:.1f} 秒"
    if note:
        head += f"；{' '.join(note.split())}"
    parts, listed = [], []
    for key, value in (summary.items() if isinstance(summary, dict) else ()):
        if isinstance(value, list):
            parts.append(f"{key}={len(value)} 項")
            if value and key in _LISTED:
                text = json.dumps(value, ensure_ascii=False)
                listed.append(f"{command} {key}：{text if len(text) <= _MAX_ITEMS else text[:_MAX_ITEMS] + '…'}")
        elif isinstance(value, (bool, int, float)) or (isinstance(value, str) and len(value) <= _MAX_TEXT):
            parts.append(f"{key}={value}")
    if parts:
        head += "；" + ", ".join(parts)
    return [head, *listed]


def log_result(command: str, code: int, seconds: float, summary: Any = None, note: str | None = None) -> None:
    log = logging.getLogger("sweetspot.result")
    for n, line in enumerate(result_lines(command, code, seconds, summary, note)):
        (log.info if n == 0 and code == 0 else log.warning)(line)
