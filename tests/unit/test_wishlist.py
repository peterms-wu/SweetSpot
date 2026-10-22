from datetime import UTC, datetime, timedelta

import pytest

from sweetspot.pipeline import wishlist
from sweetspot.sources import WishlistEntry, WishlistFetchError
from sweetspot.store.writer import StoreWriter

T1 = datetime(2026, 9, 25, 12, tzinfo=UTC)


class FakeSource:
    def __init__(self, result):
        self.result = result

    def get_wishlist(self, steamid):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def entries(*ids):
    return [WishlistEntry(i, n, datetime(2026, 1, 1, tzinfo=UTC)) for n, i in enumerate(ids, 1)]


@pytest.fixture
def writer(db_path):
    w = StoreWriter.open(db_path)
    yield w
    w.close()


def sync(writer, result, now=T1, max_items=500, months=24):
    run = writer.start_run("daily")
    return wishlist.sync_wishlist(writer, FakeSource(result), steamid="1", source_url="u", run_id=run,
                                  now=now, max_items=max_items, tracking_months=months)


def states(writer):
    return dict(writer.conn.execute("SELECT app_id, state FROM wishlist_membership"))


def test_first_sync_adds_everything(writer):
    result = sync(writer, entries(620, 400))
    assert result.status == "ok" and result.count == 2 and sorted(result.added) == [400, 620]
    assert result.active_apps == [400, 620]
    assert states(writer) == {620: "in_wishlist", 400: "in_wishlist"}
    assert writer.conn.execute("SELECT COUNT(*) FROM wishlist_items").fetchone()[0] == 2
    assert writer.conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 2


@pytest.mark.parametrize(
    "result,reason",
    [
        (WishlistFetchError("private"), "private"),
        (WishlistFetchError("rate-limited"), "rate-limited"),
        (WishlistFetchError("malformed"), "malformed"),
        (WishlistFetchError("incomplete"), "incomplete"),
        (WishlistFetchError("network"), "network"),
        (entries(620, 620), "duplicate-appid"),
        (entries(620, 0), "invalid-appid"),
        (entries(*range(1, 503)), "over-limit"),
    ],
)
def test_rejections_keep_previous_list_and_states(writer, result, reason):
    sync(writer, entries(620, 400))
    rejected = sync(writer, result, now=T1 + timedelta(days=1))
    assert rejected.status == "rejected" and rejected.reject_reason == reason
    assert rejected.used_previous and rejected.active_apps == [400, 620]
    assert states(writer) == {620: "in_wishlist", 400: "in_wishlist"}
    items_per_sync = writer.conn.execute(
        "SELECT s.status, COUNT(i.app_id) FROM wishlist_syncs s LEFT JOIN wishlist_items i USING (sync_id) "
        "GROUP BY s.sync_id ORDER BY s.attempted_at").fetchall()
    assert items_per_sync == [("ok", 2), ("rejected", 0)]


def test_explicit_empty_list_is_saved(writer):
    sync(writer, entries(620))
    result = sync(writer, [], now=T1 + timedelta(days=1))
    assert result.status == "empty" and result.count == 0 and result.removed == [620]
    assert states(writer) == {620: "removed_tracking"}


def test_removal_starts_tracking_for_24_months_then_expires(writer):
    sync(writer, entries(620, 400))
    removed_at = T1 + timedelta(days=1)
    result = sync(writer, entries(400), now=removed_at)
    assert result.removed == [620]
    assert result.active_apps == [400, 620]  # still tracked for forecast verification
    track_until = writer.conn.execute("SELECT track_until FROM wishlist_membership WHERE app_id=620").fetchone()[0]
    assert track_until.startswith("2028-09-26")

    later = sync(writer, entries(400), now=datetime(2028, 9, 27, tzinfo=UTC))
    assert later.active_apps == [400]
    assert states(writer)[620] == "reference_only"


def test_re_adding_restores_in_wishlist(writer):
    sync(writer, entries(620))
    sync(writer, [], now=T1 + timedelta(days=1))
    result = sync(writer, entries(620), now=T1 + timedelta(days=2))
    assert result.added == [620]
    assert states(writer) == {620: "in_wishlist"}
    removed_at = writer.conn.execute("SELECT removed_at FROM wishlist_membership").fetchone()[0]
    assert removed_at is None


def test_rejected_first_sync_has_no_list(writer):
    result = sync(writer, WishlistFetchError("private"))
    assert result.status == "rejected" and result.active_apps == []
