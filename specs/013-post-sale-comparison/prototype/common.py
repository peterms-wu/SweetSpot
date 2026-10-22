"""Shared helpers for the 013 plan prototypes (read-only on the main folder's database and records)."""

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

from steamsage.store.query import ITAD_SOURCES, OPTION_HISTORY_SOURCE, PriceStore

MAIN = Path(r"〈專案資料夾〉")
DB = MAIN / "data" / "steamsage.db"
FORECASTS = MAIN / "data" / "forecasts"
NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


def parse_time(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def load_record(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def records() -> list[tuple[datetime, Path]]:
    out = []
    for p in sorted(FORECASTS.glob("*.json.gz")):
        out.append((datetime.strptime(p.name[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC), p))
    return out


def open_store() -> PriceStore:
    return PriceStore.open(DB)


def autumn_2026(store: PriceStore):
    return next(e for e in store.calendar_events() if e.kind == "seasonal" and e.season == "autumn" and e.year == 2026)


def pre_sale_record(sale) -> tuple[datetime, Path]:
    """The last record whose file time is before the sale start (prototype: no official/preview check)."""
    return [r for r in records() if r[0] < sale.start][-1]


def tracked_key(decision: dict) -> tuple[str | None, tuple[str, ...]]:
    """The ITAD product and sources the record's decision read: a user edition reads its own option history."""
    v = decision.get("version") or {}
    if v.get("source") == "user":
        return v.get("itad_id"), (OPTION_HISTORY_SOURCE,)
    return v.get("itad_id"), ITAD_SOURCES
