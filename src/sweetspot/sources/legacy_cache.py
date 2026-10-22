"""Read-only reader for the legacy SteamSage cache (research R8).

Each file is {"identity": [...], "payload": ..., "retrieved_at": ..., "schema_version": "1.0"} and is named
sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True)). Only raw source data is imported; data
derived by the old model is skipped.
"""

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sweetspot.products import normalize_name
from sweetspot.sources import AppDetails, HistoryEntry
from sweetspot.sources.itad import parse_history
from sweetspot.sources.steam_store import parse_app_details
from sweetspot.timeutil import parse_iso, parse_steam_date

SUPPORTED_SCOPE = ("TW", "TWD", "base-public")
SKIPPED_KINDS = {
    "publisher-library-v1": "derived-data",       # the old model's derived records
    "publisher-catalog-v1": "truncated-catalog",  # first page only
    "publisher-catalog-v2": "truncated-catalog",
}


@dataclass(frozen=True)
class LegacyMapping:
    path: Path
    app_id: int
    external_id: str
    warnings: list[str]
    retrieved_at: datetime


@dataclass(frozen=True)
class LegacyHistory:
    path: Path
    app_id: int
    entries: list[HistoryEntry]
    retrieved_at: datetime


@dataclass(frozen=True)
class LegacyMetadata:
    path: Path
    app_id: int
    details: AppDetails
    partial: bool          # True when only some fields were recorded (publisher-metadata-v1)
    retrieved_at: datetime


@dataclass(frozen=True)
class LegacyCatalog:
    path: Path
    publisher: str
    app_ids: list[int]
    retrieved_at: datetime


@dataclass(frozen=True)
class LegacySkip:
    path: Path
    reason: str


LegacyRecord = LegacyMapping | LegacyHistory | LegacyMetadata | LegacyCatalog | LegacySkip


def _app_id(product_key: Any) -> int | None:
    if isinstance(product_key, str) and product_key.startswith("app:") and product_key[4:].isdigit():
        return int(product_key[4:])
    return None


def _parse(path: Path, data: Any) -> LegacyRecord:
    if not isinstance(data, dict) or not {"identity", "payload", "retrieved_at"} <= data.keys() \
            or data.get("schema_version") != "1.0" or not isinstance(data["identity"], list) or not data["identity"]:
        return LegacySkip(path, "bad-wrapper")
    identity, payload = data["identity"], data["payload"]
    expected_name = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if path.stem != expected_name:
        return LegacySkip(path, "identity-mismatch")
    try:
        retrieved_at = parse_iso(data["retrieved_at"])
    except (TypeError, ValueError):
        return LegacySkip(path, "bad-wrapper")

    kind = identity[0]
    if kind in SKIPPED_KINDS:
        return LegacySkip(path, SKIPPED_KINDS[kind])

    if kind == "itad-steam-verified-v1":
        app_id = _app_id(identity[1] if len(identity) > 1 else None)
        if app_id is None or tuple(identity[2:5]) != SUPPORTED_SCOPE or len(identity) < 6:
            return LegacySkip(path, "unsupported-scope")
        sub = identity[5]
        if sub == "identity":
            if not isinstance(payload, dict) or not payload.get("itad_id") \
                    or payload.get("subtype") not in ("game", "dlc"):
                return LegacySkip(path, "unsupported-scope")
            return LegacyMapping(path, app_id, payload["itad_id"], list(payload.get("mapping_warnings") or []),
                                 retrieved_at)
        if sub == "history":
            return LegacyHistory(path, app_id, parse_history(payload), retrieved_at)
        if sub == "current":
            return LegacySkip(path, "stale-snapshot")
        return LegacySkip(path, "unknown-kind")

    if kind == "publisher-metadata-v1":
        app_id = _app_id(identity[1] if len(identity) > 1 else None)
        if app_id is None or not isinstance(payload, dict):
            return LegacySkip(path, "bad-wrapper")
        details = AppDetails(
            app_id=app_id, name=None, type=payload.get("subtype"), is_free=None,
            coming_soon=payload.get("coming_soon"),
            release_date=parse_steam_date(payload.get("release_date")),
            publishers=list(payload.get("publishers") or []), developers=list(payload.get("developers") or []),
            genres=[{"id": str(g), "description": None} for g in payload.get("genres") or []],
        )
        when = payload.get("metadata_retrieved_at")
        return LegacyMetadata(path, app_id, details, True, parse_iso(when) if when else retrieved_at)

    if kind == "steam-release-v1":
        app_id = _app_id(identity[1] if len(identity) > 1 else None)
        details = parse_app_details({"legacy": {"success": True, "data": payload}}, app_id) if app_id else None
        if details is None:
            return LegacySkip(path, "identity-mismatch")
        return LegacyMetadata(path, app_id, details, False, retrieved_at)

    if kind == "publisher-catalog-v3":
        if len(identity) < 2 or not isinstance(identity[1], str) or not isinstance(payload, list):
            return LegacySkip(path, "bad-wrapper")
        ids = sorted({int(a) for a in payload if str(a).isdigit()})
        return LegacyCatalog(path, normalize_name(identity[1]), ids, retrieved_at)

    return LegacySkip(path, "unknown-kind")


class LegacyCache:
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def records(self) -> Iterator[LegacyRecord]:
        if not self.directory.is_dir():
            raise FileNotFoundError(f"舊專案快取目錄不存在：{self.directory}")
        for path in sorted(self.directory.glob("*.json")):
            try:
                with path.open("r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, UnicodeDecodeError, ValueError):
                yield LegacySkip(path, "malformed-json")
                continue
            yield _parse(path, data)
