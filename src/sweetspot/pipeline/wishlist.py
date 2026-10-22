"""Wishlist sync and membership state machine (FR-001, FR-002, FR-003a; data-model §2)."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sweetspot.sources import WishlistEntry, WishlistFetchError, WishlistSource
from sweetspot.store.writer import StoreWriter
from sweetspot.timeutil import add_months, to_db


@dataclass
class WishlistSyncResult:
    status: str                      # ok | empty | rejected
    reject_reason: str | None
    count: int
    added: list[int] = field(default_factory=list)
    removed: list[int] = field(default_factory=list)
    active_apps: list[int] = field(default_factory=list)
    used_previous: bool = False


def _validate(entries: list[WishlistEntry], max_items: int) -> str | None:
    if len(entries) > max_items:
        return "over-limit"
    ids = [e.app_id for e in entries]
    if any(not isinstance(i, int) or i <= 0 for i in ids):
        return "invalid-appid"
    if len(set(ids)) != len(ids):
        return "duplicate-appid"
    return None


def active_apps(writer: StoreWriter, now: datetime) -> list[int]:
    """Apps the daily update tracks: current wishlist plus removed apps still inside track_until."""
    rows = writer.conn.execute(
        "SELECT app_id FROM wishlist_membership WHERE state = 'in_wishlist' "
        "OR (state = 'removed_tracking' AND track_until >= ?) ORDER BY app_id",
        (to_db(now),),
    )
    return [r[0] for r in rows]


def expire_tracking(writer: StoreWriter, now: datetime) -> list[int]:
    expired = [r[0] for r in writer.conn.execute(
        "SELECT app_id FROM wishlist_membership WHERE state = 'removed_tracking' AND track_until < ?",
        (to_db(now),))]
    writer.conn.executemany(
        "UPDATE wishlist_membership SET state = 'reference_only', updated_at = ? WHERE app_id = ?",
        [(to_db(now), app_id) for app_id in expired],
    )
    return expired


def _apply_membership(writer: StoreWriter, entries: list[WishlistEntry], now: datetime,
                      tracking_months: int) -> tuple[list[int], list[int]]:
    current = dict(writer.conn.execute("SELECT app_id, state FROM wishlist_membership"))
    new_ids = {e.app_id for e in entries}
    stamp = to_db(now)
    added, removed = [], []
    for entry in entries:
        state = current.get(entry.app_id)
        if state == "in_wishlist":
            continue
        added.append(entry.app_id)
        writer.ensure_product(entry.app_id, "wishlist", now)
        if state is None:
            writer.conn.execute(
                "INSERT INTO wishlist_membership (app_id, state, first_added_at, updated_at) "
                "VALUES (?, 'in_wishlist', ?, ?)",
                (entry.app_id, to_db(entry.date_added or now), stamp),
            )
        else:
            writer.conn.execute(
                "UPDATE wishlist_membership SET state = 'in_wishlist', removed_at = NULL, track_until = NULL, "
                "updated_at = ? WHERE app_id = ?",
                (stamp, entry.app_id),
            )
    for app_id, state in current.items():
        if state == "in_wishlist" and app_id not in new_ids:
            removed.append(app_id)
            writer.conn.execute(
                "UPDATE wishlist_membership SET state = 'removed_tracking', removed_at = ?, track_until = ?, "
                "updated_at = ? WHERE app_id = ?",
                (stamp, to_db(add_months(now, tracking_months)), stamp, app_id),
            )
    return sorted(added), sorted(removed)


def sync_wishlist(writer: StoreWriter, source: WishlistSource, *, steamid: str, source_url: str, run_id: str,
                  now: datetime, max_items: int, tracking_months: int) -> WishlistSyncResult:
    sync_id = str(uuid.uuid4())
    try:
        entries = source.get_wishlist(steamid)
        reason = _validate(entries, max_items)
    except WishlistFetchError as exc:
        entries, reason = [], exc.reason

    with writer.transaction():
        if reason:
            writer.conn.execute(
                "INSERT INTO wishlist_syncs (sync_id, source_url, attempted_at, status, reject_reason, run_id) "
                "VALUES (?, ?, ?, 'rejected', ?, ?)",
                (sync_id, source_url, to_db(now), reason, run_id),
            )
            writer.record_item_result(run_id, None, "wishlist", "failed", reason)
            expire_tracking(writer, now)
            return WishlistSyncResult("rejected", reason, 0, active_apps=active_apps(writer, now),
                                      used_previous=True)

        status = "ok" if entries else "empty"
        writer.conn.execute(
            "INSERT INTO wishlist_syncs (sync_id, source_url, attempted_at, status, item_count, run_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sync_id, source_url, to_db(now), status, len(entries), run_id),
        )
        writer.conn.executemany(
            "INSERT INTO wishlist_items (sync_id, app_id, priority, date_added) VALUES (?, ?, ?, ?)",
            [(sync_id, e.app_id, e.priority, to_db(e.date_added) if e.date_added else None) for e in entries],
        )
        added, removed = _apply_membership(writer, entries, now, tracking_months)
        expire_tracking(writer, now)
        writer.record_item_result(run_id, None, "wishlist", "ok")
        return WishlistSyncResult(status, None, len(entries), added, removed, active_apps(writer, now))
