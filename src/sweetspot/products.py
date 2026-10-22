"""Source-independent product classification helpers."""

import re
import unicodedata
INDIE_GENRE_ID = "23"
INDIE_NAMES = {"indie", "獨立", "独立"}


def is_indie(genres: list[dict] | None) -> bool | None:
    if not genres:
        return None
    return any(str(g.get("id")) == INDIE_GENRE_ID or str(g.get("description", "")).strip().lower() in INDIE_NAMES
               for g in genres)


def normalize_name(name: str) -> str:
    """Publisher/developer key: NFKC, case-folded, single spaces (matches the legacy catalog keys)."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", name)).strip().casefold()


def product_type(steam_type: str | None, parent_app_id: int | None) -> str | None:
    """Map Steam's app type to data-model product_type. Soundtracks (music) with a base game count as DLC."""
    if steam_type is None:
        return None
    if steam_type == "game":
        return "game"
    if steam_type == "dlc" or (steam_type == "music" and parent_app_id):
        return "dlc"
    return "other"
