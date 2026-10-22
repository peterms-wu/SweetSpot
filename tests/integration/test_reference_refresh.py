"""US4 scenario 4 (added 2026-10-14): once the samples are full, the reference budget updates stale histories."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from sweetspot.config import load_config
from tests.config_builders import TEST_TOML
from sweetspot.pipeline import reference
from sweetspot.sources import HistoryEntry
from sweetspot.sources.errors import SourceError
from sweetspot.store.query import PriceStore
from sweetspot.store.writer import NewObservation, StoreWriter

NOW = datetime(2026, 10, 14, 3, 0, tzinfo=UTC)
SALE_DAY = datetime(2026, 10, 1, 18, 0, tzinfo=UTC)

STALE_OLD = 10        # fetched 9/22: refreshed first
STALE_NEWER = 11      # fetched 9/24
FRESH = 12            # fetched an hour ago: left alone
LEGACY = 13           # only legacy-import rows (retrieved 9/20): refreshed too, and oldest of all
REJECTED = 14         # ITAD mapping rejected: the models never read it
NO_HISTORY = 15       # a sample that never got any history
WISHLIST = 16         # tracked by the daily update, not here


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class History:
    """HistorySource whose every call costs one second of fake time; it knows one autumn-sale row per product."""

    def __init__(self, clock, fail_on: str | None = None):
        self.clock, self.fail_on = clock, fail_on
        self.calls: list[tuple[str, str]] = []

    def history(self, external_id, country, since):
        self.clock.t += 1
        self.calls.append((external_id, country))
        if external_id == self.fail_on:
            raise SourceError("itad", "HTTP 503")
        return [HistoryEntry(SALE_DAY, SALE_DAY.isoformat(), "TWD" if country == "TW" else "USD",
                             10000, 20000, 50)]

    def lookup_steam(self, app_ids):
        return {}

    def reverse_lookup(self, ids):
        return {}

    def current_prices(self, ids, country):
        return {}


def sources(history):
    return reference.ReferenceSources(metadata=None, catalog=None, history=history, app_list=None)


@pytest.fixture
def setup(db_path, tmp_path):
    path = tmp_path / "s.toml"
    path.write_text(TEST_TOML, encoding="utf-8")
    config, _ = load_config(path)
    writer = StoreWriter.open(db_path)
    run = writer.start_run("reference")

    def fetched(app_id, at, verification="verified"):
        writer.ensure_product(app_id, "reference-broad", at)
        writer.add_mapping(run, app_id, "itad", f"id-{app_id}", verification, checked_at=at)
        for region in ("TW", "US"):
            writer.conn.execute(
                "INSERT INTO history_fetches (app_id, source, region, fetched_at, entries, run_id, external_id) "
                "VALUES (?, 'itad', ?, ?, 1, ?, ?)",
                (app_id, region, at.strftime("%Y-%m-%dT%H:%M:%S.000000Z"), run, f"id-{app_id}"))

    fetched(STALE_OLD, datetime(2026, 9, 22, tzinfo=UTC))
    fetched(STALE_NEWER, datetime(2026, 9, 24, tzinfo=UTC))
    fetched(FRESH, NOW - timedelta(hours=1))
    fetched(REJECTED, datetime(2026, 9, 1, tzinfo=UTC), verification="rejected")
    fetched(WISHLIST, datetime(2026, 9, 1, tzinfo=UTC))
    writer.conn.execute("INSERT INTO wishlist_membership (app_id, state, first_added_at, updated_at) "
                        "VALUES (?, 'in_wishlist', '2026-01-01T00:00:00.000000Z', '2026-01-01T00:00:00.000000Z')",
                        (WISHLIST,))
    writer.ensure_product(LEGACY, "legacy", datetime(2026, 9, 20, tzinfo=UTC))
    writer.add_mapping(run, LEGACY, "itad", f"id-{LEGACY}", "verified-legacy",
                       checked_at=datetime(2026, 9, 20, tzinfo=UTC))
    writer.add_observations(run, [NewObservation(
        LEGACY, "legacy-itad", "TW", "TWD", 20000, 20000, 0, datetime(2024, 1, 1, tzinfo=UTC), None,
        datetime(2026, 9, 20, tzinfo=UTC), external_id=f"id-{LEGACY}")])
    writer.ensure_product(NO_HISTORY, "reference-broad", datetime(2026, 9, 1, tzinfo=UTC))
    writer.add_mapping(run, NO_HISTORY, "itad", f"id-{NO_HISTORY}", "verified",
                       checked_at=datetime(2026, 9, 1, tzinfo=UTC))
    yield writer, config
    writer.close()


def run(writer, config, history, *, limit=None, pools=("refresh",)):
    return reference.run_reference(writer, sources(history), config, now=NOW, pools=pools, limit=limit,
                                   clock=history.clock if history else Clock())


def test_stale_reference_histories_are_refreshed_oldest_first(setup):
    writer, config = setup
    history = History(Clock())
    summary = run(writer, config, history)["refresh"]
    assert [c for c in history.calls] == [(f"id-{LEGACY}", "TW"), (f"id-{LEGACY}", "US"),
                                          (f"id-{STALE_OLD}", "TW"), (f"id-{STALE_OLD}", "US"),
                                          (f"id-{STALE_NEWER}", "TW"), (f"id-{STALE_NEWER}", "US")]
    assert summary == {"status": "ok", "stale": 3, "refreshed": 3, "left": 0, "new_rows": 6}


def test_refresh_moves_known_until_past_the_sale(setup):
    """The point of the fix: after a refresh the models see the reference app's history through the autumn sale."""
    writer, config = setup
    store = PriceStore(writer.conn)
    apps = (LEGACY, STALE_OLD)
    keys = store.key_ids(store.history_keys(apps, NOW))
    before = store.history_known_until_all("TW", keys=keys, apps=apps)
    assert set(before) == set(apps) and all(t < SALE_DAY for t in before.values())
    run(writer, config, History(Clock()))
    after = store.history_known_until_all("TW", keys=keys, apps=apps)
    assert all(after[a] >= NOW for a in (LEGACY, STALE_OLD))
    rows = store.series_rows([LEGACY, STALE_OLD], "TW", NOW, keys=keys)
    assert all(any(o.observed_at == SALE_DAY for o in rows[a]) for a in (LEGACY, STALE_OLD))


def test_limit_stops_and_the_next_run_continues(setup):
    writer, config = setup
    first = History(Clock())
    summary = run(writer, config, first, limit=1)
    assert summary["stopped"] == "limit"
    assert summary["refresh"]["refreshed"] == 1 and summary["refresh"]["left"] == 2
    second = History(Clock())
    run(writer, config, second)
    assert {ext for ext, _ in second.calls} == {f"id-{STALE_OLD}", f"id-{STALE_NEWER}"}


def test_a_failing_source_stops_the_refresh(setup):
    writer, config = setup
    history = History(Clock(), fail_on=f"id-{STALE_OLD}")
    summary = run(writer, config, history)
    assert summary["refresh"]["status"] == "failed"
    assert summary["refresh"]["refreshed"] == 1          # the legacy app before it
    assert not any(ext == f"id-{STALE_NEWER}" for ext, _ in history.calls)
    assert any(str(STALE_OLD) in a for a in summary["alerts"])


def test_without_itad_the_refresh_is_disabled(setup):
    writer, config = setup
    summary = reference.run_reference(writer, sources(None), config, now=NOW, pools=("refresh",), clock=Clock())
    assert summary["refresh"] == {"status": "disabled", "reason": reference.HISTORY_SOURCE_MISSING}


def test_samples_come_before_the_refresh_by_default(setup):
    assert reference.POOLS == ("related", "broad", "refresh")


def test_budget_spent_by_the_samples_leaves_nothing_for_the_refresh(setup):
    writer, config = setup
    clock = Clock()
    history = History(clock)
    summary = reference.run_reference(writer, sources(history), config, now=NOW, pools=("refresh",),
                                      deadline=clock() - 1, clock=clock)
    assert summary["stopped"] == "budget"
    assert history.calls == [] and summary["refresh"]["left"] == 3
