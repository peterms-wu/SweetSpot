"""Tuning / validation split of a backtest dataset by a fixed hash of the app id (research R4; spec FR-009).

The same app lands in the same part in every region and every run. The salt is a framework setting
(docs/model/model-definition.md) and never changes.
"""

import hashlib
from collections.abc import Sequence

SALT = "steamsage-004-split"
SPLITS = ("all", "tuning", "validation")


def part(app_id: int) -> str:
    value = int(hashlib.sha256(f"{SALT}:{app_id}".encode()).hexdigest()[:8], 16)
    return "tuning" if value % 2 == 0 else "validation"


def select(apps: Sequence[int], split: str) -> tuple[int, ...]:
    if split not in SPLITS:
        raise ValueError(f"split 必須是 {', '.join(SPLITS)} 之一：{split!r}")
    if split == "all":
        return tuple(apps)
    return tuple(a for a in apps if part(a) == split)
