"""Official forecast records: gzip'd decision contracts in data/forecasts/, append only (research R6; FR-015–FR-019).

A record exists only once it has been renamed from `.tmp` to `.json.gz`, so an interrupted write never becomes the
comparison baseline (constitution III). The baseline is the latest readable record whose as_of falls on an earlier
Taipei (UTC+8) day than the current run.
"""

import gzip
import io
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sweetspot.timeutil import parse_iso

SCHEMA = "steamsage.decision/2"
READABLE = ("steamsage.decision/1", SCHEMA)     # feature 005: /1 records stay readable and comparable
SUFFIX = ".json.gz"
NAME_FORMAT = "%Y%m%dT%H%M%SZ"
TAIPEI = timedelta(hours=8)


class RecordError(ValueError):
    pass


def record_name(as_of: datetime) -> str:
    return as_of.strftime(NAME_FORMAT) + SUFFIX


def write_record(directory: Path, data: dict[str, Any]) -> Path:
    """Write one record; the same content always gives the same bytes. Never overwrites an existing record."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / record_name(parse_iso(data["as_of"]))
    if path.exists():
        raise FileExistsError(f"紀錄已存在，不覆蓋：{path.name}")
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0) as gz:
        gz.write(raw)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_bytes(buffer.getvalue())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return path


def list_records(directory: Path) -> list[Path]:
    directory = Path(directory)
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if p.is_file() and p.name.endswith(SUFFIX))


def load_record(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(gzip.decompress(Path(path).read_bytes()).decode("utf-8"))
    except (OSError, EOFError, ValueError) as exc:
        raise RecordError(f"無法讀取紀錄 {Path(path).name}：{exc}") from exc
    if not isinstance(data, dict) or data.get("schema") not in READABLE:
        raise RecordError(f"紀錄 {Path(path).name} 的格式不是 {' 或 '.join(READABLE)}")
    return data


def _taipei_day(moment: datetime):
    return (moment + TAIPEI).date()


def find_baseline(directory: Path, as_of: datetime) -> tuple[Path | None, dict | None, list[str]]:
    """(path, data, skipped file names) of the comparison baseline; (None, None, skipped) when there is none."""
    today = _taipei_day(as_of)
    skipped = []
    for path in reversed(list_records(directory)):
        try:
            moment = datetime.strptime(path.name[:-len(SUFFIX)], NAME_FORMAT).replace(tzinfo=as_of.tzinfo)
        except ValueError:
            skipped.append(path.name)
            continue
        if _taipei_day(moment) >= today:
            continue
        try:
            return path, load_record(path), skipped
        except RecordError:
            skipped.append(path.name)
    return None, None, skipped
