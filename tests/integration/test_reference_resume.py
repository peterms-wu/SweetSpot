"""US4 end-to-end with fake sources: related + broad pools, caps, strata, budget and resume (SC-006)."""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from sweetspot.config import load_config
from tests.config_builders import TEST_TOML
from sweetspot.pipeline import reference
from sweetspot.sources import (AppDetails, AppListPage, CatalogPage, HistoryEntry, ItemSummary, PriceQuote,
                               ReviewSummary)
from sweetspot.store.writer import StoreWriter

NOW = datetime(2026, 9, 25, tzinfo=UTC)
WISHLIST_APP = 1
PUB_A = [100 + i for i in range(40)]         # 40 games by "Pub A"
BROAD = [5000 + i for i in range(120)]       # broad population


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class FakeSources:
    """Every call costs one second of fake time so budgets are deterministic."""

    def __init__(self, clock, with_app_list=True):
        self.clock = clock
        self.calls: list[tuple] = []
        self.with_app_list = with_app_list

    def _tick(self, *call):
        self.calls.append(call)
        self.clock.t += 1

    # CatalogSource
    def search_catalog(self, kind, name, start):
        self._tick("search", kind, name, start)
        members = PUB_A if name == "Pub A" and kind == "publisher" else []
        return CatalogPage(members[start:start + 25], len(members), start)

    # AppListSource
    def app_list(self, last_appid, max_results):
        self._tick("applist", last_appid)
        apps = [(a, f"G{a}", None) for a in BROAD if last_appid is None or a > last_appid][:100]
        more = bool(apps) and apps[-1][0] != BROAD[-1]
        return AppListPage(apps, more, apps[-1][0] if apps else None)

    # MetadataSource
    def item_summaries(self, app_ids):
        self._tick("items", tuple(app_ids))
        return {a: ItemSummary(a, f"G{a}", 20 if a % 4 == 0 else 500, 90, [], 0, False, date(2020, 1, 1), False)
                for a in app_ids}

    def app_details(self, app_id):
        self._tick("details", app_id)
        year = 2016 + app_id % 10
        indie = [{"id": "23", "description": "獨立"}] if app_id % 2 else []
        price = [19900, 45000, 79000, 129000][app_id % 4]
        return AppDetails(app_id, f"G{app_id}", "game", False, False, date(year, 3, 1), ["Pub A"], ["Dev"], indie,
                          None, [], PriceQuote("TWD", price, price, 0))

    def review_summary(self, app_id):
        self._tick("reviews", app_id)
        return ReviewSummary(20, 15)

    def canonical_app_id(self, app_id):
        return app_id

    def package_details(self, package_id):
        return None

    def package_details_batch(self, package_ids):
        self._tick("packages", tuple(package_ids))
        return {p: None for p in package_ids}

    # HistorySource
    def lookup_steam(self, app_ids):
        self._tick("lookup", tuple(app_ids))
        return {a: f"id-{a}" for a in app_ids}

    def reverse_lookup(self, ids):
        return {i: [f"app/{i[3:]}"] for i in ids}

    def history(self, external_id, country, since):
        self._tick("history", external_id, country)
        return [HistoryEntry(datetime(2025, 1, 1, tzinfo=UTC), "2025-01-01T00:00:00Z",
                             "TWD" if country == "TW" else "USD", 10000, 20000, 50)]

    def current_prices(self, ids, country):
        return {}

    def as_reference_sources(self):
        return reference.ReferenceSources(metadata=self, catalog=self, history=self,
                                          app_list=self if self.with_app_list else None)


@pytest.fixture
def setup(db_path, tmp_path):
    path = tmp_path / "s.toml"
    path.write_text(TEST_TOML, encoding="utf-8")
    config, _ = load_config(path)
    config = replace(config, reference=replace(config.reference, broad_per_stratum=2))
    writer = StoreWriter.open(db_path)
    run = writer.start_run("daily")
    writer.ensure_product(WISHLIST_APP, "wishlist", NOW)
    writer.conn.execute("INSERT INTO wishlist_membership (app_id, state, first_added_at, updated_at) "
                        "VALUES (1, 'in_wishlist', '2026-01-01T00:00:00.000000Z', '2026-01-01T00:00:00.000000Z')")
    writer.add_facts(run, WISHLIST_APP, {"publishers": ["Pub A"], "developers": ["Dev"]}, source="steam-appdetails",
                     retrieved_at=NOW)
    yield writer, config
    writer.close()


def run(writer, config, sources, clock, *, budget=None, limit=None, pools=("related", "broad")):
    deadline = clock() + budget if budget is not None else None
    return reference.run_reference(writer, sources.as_reference_sources(), config, now=NOW, pools=pools,
                                   deadline=deadline, limit=limit, clock=clock)


def rows(writer, pool_prefix):
    return writer.conn.execute(
        "SELECT status, reject_reason, COUNT(*) FROM reference_candidates WHERE pool LIKE ? AND sample_version != "
        "'legacy-catalog-v3' GROUP BY 1, 2", (pool_prefix + "%",)).fetchall()


def test_related_pool_caps_each_publisher(setup):
    writer, config = setup
    clock = Clock()
    summary = run(writer, config, FakeSources(clock), clock, pools=("related",))
    statuses = {(s, r): n for s, r, n in rows(writer, "related-publisher")}
    fetched = statuses.get(("fetched", None), 0)
    assert fetched == 30   # per_publisher_cap
    capped = statuses.get(("rejected", "publisher-cap"), 0)
    assert capped + fetched + statuses.get(("rejected", "few-reviews"), 0) == 40
    assert summary["related"]["catalogs_complete"] >= 1 and summary["stopped"] == "complete"
    size = writer.conn.execute("SELECT value_json FROM product_facts WHERE app_id = 1 "
                               "AND field = 'publisher_catalog_size'").fetchone()
    assert size == ("40",)


def test_budget_stop_and_resume_without_refetching(setup):
    writer, config = setup
    clock = Clock()
    first_sources = FakeSources(clock)
    first = run(writer, config, first_sources, clock, budget=15, pools=("related",))
    assert first["stopped"] == "budget"
    done_before = {a for (a,) in writer.conn.execute(
        "SELECT app_id FROM reference_candidates WHERE status = 'fetched'")}
    assert done_before

    second_sources = FakeSources(clock)
    run(writer, config, second_sources, clock, pools=("related",))
    refetched = {c[1] for c in second_sources.calls if c[0] == "details"} & done_before
    assert refetched == set()
    searched = [c[3] for c in second_sources.calls if c[0] == "search"]
    assert searched == [] or searched[0] > 0   # paging resumed, not restarted


def test_limit_stops_after_n_apps(setup):
    writer, config = setup
    clock = Clock()
    summary = run(writer, config, FakeSources(clock), clock, limit=3, pools=("related",))
    assert summary["stopped"] == "limit"
    assert writer.conn.execute("SELECT COUNT(*) FROM reference_candidates WHERE status IN "
                               "('fetched', 'rejected') AND reject_reason IS NOT 'publisher-cap'").fetchone()[0] <= 3


def test_broad_pool_fills_strata_up_to_cap(setup):
    writer, config = setup
    clock = Clock()
    summary = run(writer, config, FakeSources(clock), clock, pools=("broad",))
    per_stratum = writer.conn.execute(
        "SELECT pool_detail, COUNT(*) FROM reference_candidates WHERE pool = 'broad' AND status = 'fetched' "
        "GROUP BY 1").fetchall()
    assert per_stratum and all(n <= 2 for _, n in per_stratum)
    reasons = {r for s, r, _ in rows(writer, "broad") if s == "rejected"}
    assert reasons <= {"few-reviews", "stratum-full"} and "stratum-full" in reasons
    assert summary["broad"]["status"] == "ok" and summary["broad"]["app_list"] == len(BROAD)
    assert writer.conn.execute("SELECT COUNT(*) FROM products WHERE first_seen_via = 'reference-broad'").fetchone()[0] \
        == sum(n for _, n in per_stratum)


def test_without_app_list_broad_is_disabled_but_related_runs(setup):
    writer, config = setup
    clock = Clock()
    summary = run(writer, config, FakeSources(clock, with_app_list=False), clock)
    assert summary["broad"]["status"] == "disabled"
    assert "STEAM_WEB_API_KEY" in summary["broad"]["reason"]
    assert summary["related"]["fetched"] == 30


def test_a_steam_list_that_cannot_be_fetched_is_an_alert(setup):
    """014 T071 (001 contracts/cli.md: exit 2 when part failed): the failure was only in broad.status, with no
    alert, so `reference` ended with 0 and the daily update never said so."""
    from sweetspot.sources.errors import SourceError

    writer, config = setup
    clock = Clock()
    sources = FakeSources(clock)

    def down(last_appid, max_results):
        raise SourceError("steam-webapi: HTTP 502 for GetAppList")

    sources.app_list = down
    summary = run(writer, config, sources, clock)
    assert summary["broad"]["status"] == "failed"
    assert any("Steam 遊戲清單" in a and "502" in a for a in summary["alerts"])


def test_app_in_two_pools_keeps_both_rows(setup):
    writer, config = setup
    clock = Clock()
    global BROAD
    original = BROAD
    try:
        BROAD = PUB_A[:10]
        run(writer, config, FakeSources(clock), clock)
    finally:
        BROAD = original
    pools = writer.conn.execute(
        "SELECT app_id, COUNT(DISTINCT pool) FROM reference_candidates WHERE sample_version != 'legacy-catalog-v3' "
        "GROUP BY app_id HAVING COUNT(DISTINCT pool) > 1").fetchall()
    assert pools


def test_dataset_size_counts_reference_apps_with_history(setup):
    writer, config = setup
    clock = Clock()
    summary = run(writer, config, FakeSources(clock), clock, pools=("related",))
    assert summary["dataset_size"] == 30


def test_interrupted_accepted_app_is_finished_not_rejected(setup):
    """Regression: an 'accepted' row left by an interrupted run must be fetched on resume, not counted twice."""
    writer, config = setup
    clock = Clock()
    sources = FakeSources(clock)
    app = next(a for a in BROAD if a % 4)
    details = sources.app_details(app)
    stratum = reference.sampling.stratum_key(details.release_date.year, details.quote.initial_cents / 100,
                                             app % 2 == 1, config.reference)
    version = reference.sampling.sample_version(config.reference)
    writer.conn.execute(
        "INSERT INTO reference_candidates (app_id, pool, pool_detail, sample_version, status, updated_at) "
        "VALUES (?, 'broad', ?, ?, 'accepted', '2026-09-24T00:00:00.000000Z')", (app, stratum, version))
    run(writer, config, sources, clock, pools=("broad",))
    status = writer.conn.execute("SELECT status FROM reference_candidates WHERE app_id = ? AND pool = 'broad'",
                                 (app,)).fetchall()
    assert status == [("fetched",)]
    per_stratum = writer.conn.execute(
        "SELECT COUNT(*) FROM reference_candidates WHERE pool = 'broad' AND pool_detail = ? AND status = 'fetched'",
        (stratum,)).fetchone()[0]
    assert per_stratum <= config.reference.broad_per_stratum


@pytest.mark.parametrize("pages,expected_complete", [
    ([CatalogPage([], 0, -1, rows=0)], True),                                  # empty search result
    ([CatalogPage([1001, 1002], 3, 0, rows=3), CatalogPage([], 3, 3, rows=0)], True),   # package row counted
    # a page that never advances: one re-page from 0 is allowed, the repeat after that is an anomaly
    ([CatalogPage([1001], 5, 0, rows=1)] * 4, False),
    # an unaligned saved offset is snapped back by Steam: re-page from 0 once, then finish normally
    ([CatalogPage([1001, 1002], 2, 0, rows=2), CatalogPage([1001, 1002], 2, 0, rows=2)], True),
])
def test_catalog_paging_edge_cases(setup, pages, expected_complete):
    writer, config = setup
    clock = Clock()
    feed = iter(pages)

    class Catalog(FakeSources):
        def search_catalog(self, kind, name, start):
            self._tick("search", kind, name, start)
            return next(feed)

    if len(pages) == 2 and pages[0].total_count == 2:   # simulate progress saved at an unaligned offset
        writer.conn.execute("INSERT INTO catalog_progress (kind, name, next_start, total_count, complete, updated_at) "
                            "VALUES ('publisher', 'x', 1, 2, 0, '2026-09-24T00:00:00.000000Z')")
    job = reference.ReferenceRun(writer, Catalog(clock).as_reference_sources(), config, now=NOW,
                                 budget=reference.Budget(None, None, clock), run_id="r")
    assert job._page_catalog("publisher", "x", "X") is expected_complete
    assert bool(job.alerts) is (not expected_complete)


def test_item_summaries_are_fetched_in_full_batches(setup):
    """Regression: the prefetch used to top up one app at a time (one GetItems request per app)."""
    writer, config = setup
    clock = Clock()
    sources = FakeSources(clock)
    run(writer, config, sources, clock, pools=("broad",))
    batches = [len(c[1]) for c in sources.calls if c[0] == "items"]
    evaluated = writer.conn.execute("SELECT COUNT(*) FROM reference_candidates WHERE pool = 'broad'").fetchone()[0]
    assert len(batches) <= evaluated // reference.ITEM_BATCH + 2
    assert max(batches) == reference.ITEM_BATCH


def test_itad_id_lookups_are_batched(setup):
    """Mapping lookups for upcoming candidates go out together instead of one ITAD request per game."""
    writer, config = setup
    clock = Clock()
    sources = FakeSources(clock)
    summary = run(writer, config, sources, clock, pools=("broad",))
    lookups = [c for c in sources.calls if c[0] == "lookup"]
    assert summary["broad"]["fetched"] >= 10
    assert len(lookups) <= summary["broad"]["fetched"] // 5
    assert max(len(c[1]) for c in lookups) > 1


# --- 014 T048: would another full run add nothing? (data-model `reference_notice.sampling`) ------------------------

def complete(writer, config, key=True):
    return reference.sampling_complete(writer, config, has_steam_key=key)


def test_sampling_is_complete_only_after_a_full_run(setup):
    writer, config = setup
    clock = Clock()
    assert complete(writer, config) is False                          # nothing sampled yet
    first = run(writer, config, FakeSources(clock), clock, budget=40)
    assert first["stopped"] == "budget" and complete(writer, config) is False
    summary = run(writer, config, FakeSources(clock), clock)
    assert summary["broad"]["population_exhausted"] is True          # the fake population cannot fill all strata
    assert complete(writer, config) is True
    assert complete(writer, config, key=False) is False               # without the key the broad sample is off


def test_the_wishlist_game_in_its_own_companys_catalog_is_not_waited_for(setup):
    """Seen on the owner's database: every company catalog lists the wishlist game, left 'pending' for good."""
    writer, config = setup
    clock = Clock()
    global PUB_A
    original = PUB_A
    try:
        PUB_A = [WISHLIST_APP, *original]
        run(writer, config, FakeSources(clock), clock)
    finally:
        PUB_A = original
    assert writer.conn.execute("SELECT status FROM reference_candidates WHERE app_id = ? AND pool LIKE 'related-%'",
                               (WISHLIST_APP,)).fetchall() == [("pending",)]
    assert complete(writer, config) is True


def test_a_new_app_in_the_steam_list_makes_it_incomplete(setup):
    writer, config = setup
    clock = Clock()
    run(writer, config, FakeSources(clock), clock)
    writer.conn.execute("INSERT INTO steam_app_list (app_id, name, last_modified, fetched_at) "
                        "VALUES (99999, 'new', NULL, '2026-09-25T00:00:00.000000Z')")
    assert complete(writer, config) is False


def test_a_wishlist_app_is_not_waited_for(setup):
    writer, config = setup
    clock = Clock()
    run(writer, config, FakeSources(clock), clock)
    writer.conn.execute("INSERT INTO steam_app_list (app_id, name, last_modified, fetched_at) "
                        "VALUES (1, 'wishlist game', NULL, '2026-09-25T00:00:00.000000Z')")
    assert complete(writer, config) is True                           # the broad sample never takes wishlist apps


def test_a_new_company_on_the_wishlist_makes_it_incomplete(setup):
    writer, config = setup
    clock = Clock()
    run(writer, config, FakeSources(clock), clock)
    writer.conn.execute("INSERT INTO wishlist_membership (app_id, state, first_added_at, updated_at) "
                        "VALUES (2, 'in_wishlist', '2026-09-25T00:00:00.000000Z', '2026-09-25T00:00:00.000000Z')")
    writer.ensure_product(2, "wishlist", NOW)
    writer.add_facts(writer.start_run("daily"), 2, {"publishers": ["Pub B"], "developers": ["Dev"]},
                     source="steam-appdetails", retrieved_at=NOW)
    assert complete(writer, config) is False                          # Pub B's catalog is not paged yet


@pytest.mark.parametrize("status", ["pending", "accepted"])
def test_an_undecided_related_candidate_makes_it_incomplete(setup, status):
    writer, config = setup
    clock = Clock()
    run(writer, config, FakeSources(clock), clock)
    version = reference.sampling.sample_version(config.reference)
    writer.conn.execute(
        "INSERT INTO reference_candidates (app_id, pool, pool_detail, sample_version, status, updated_at) "
        "VALUES (777, 'related-publisher', ?, ?, ?, '2026-09-25T00:00:00.000000Z')",
        (reference.normalize_name("Pub A"), version, status))
    assert complete(writer, config) is False


def test_full_strata_are_complete_even_with_unseen_apps(setup):
    writer, config = setup
    clock = Clock()
    run(writer, config, FakeSources(clock), clock, pools=("related",))
    version = reference.sampling.sample_version(config.reference)
    rows = [(20000 + n, s, version) for n, s in enumerate(
        s for s in reference.sampling.all_strata(config.reference) for _ in range(config.reference.broad_per_stratum))]
    writer.conn.executemany(
        "INSERT INTO reference_candidates (app_id, pool, pool_detail, sample_version, status, updated_at) "
        "VALUES (?, 'broad', ?, ?, 'fetched', '2026-09-25T00:00:00.000000Z')", rows)
    writer.conn.execute("INSERT INTO steam_app_list (app_id, name, last_modified, fetched_at) "
                        "VALUES (99999, 'unseen', NULL, '2026-09-25T00:00:00.000000Z')")
    assert complete(writer, config) is True


class ConsistentSources(FakeSources):
    """Item summaries agree with the details (year and price), so full strata can be skipped early."""

    def item_summaries(self, app_ids):
        self._tick("items", tuple(app_ids))
        return {a: ItemSummary(a, f"G{a}", 20 if a % 4 == 0 else 500, 90, [], 0, False,
                               date(2016 + a % 10, 3, 1), False, [19900, 45000, 79000, 129000][a % 4])
                for a in app_ids}

    def app_details(self, app_id):
        details = super().app_details(app_id)
        indie = [{"id": "23", "description": "獨立"}] if (app_id // 20) % 2 else []   # both kinds per year/price
        return replace(details, genres=indie)


def test_full_strata_are_skipped_without_details_and_unfilled_strata_reported(setup):
    writer, config = setup
    clock = Clock()
    sources = ConsistentSources(clock)
    summary = run(writer, config, sources, clock, pools=("broad",))
    broad = summary["broad"]
    assert broad["population_exhausted"] is True
    assert broad["unfilled_strata"]          # the fake population cannot fill all 48 strata
    assert all(n < config.reference.broad_per_stratum for n in broad["unfilled_strata"].values())
    early = writer.conn.execute(
        "SELECT COUNT(*) FROM reference_candidates WHERE pool = 'broad' AND pool_detail LIKE '%/*'").fetchone()[0]
    assert early > 0
    detail_calls = sum(1 for c in sources.calls if c[0] == "details")
    evaluated_fully = writer.conn.execute(
        "SELECT COUNT(*) FROM reference_candidates WHERE pool = 'broad' AND pool_detail NOT LIKE '%/*' "
        "AND reject_reason IS NOT 'few-reviews'").fetchone()[0]
    assert detail_calls <= evaluated_fully   # skipped apps cost no store request
