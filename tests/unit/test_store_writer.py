import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from sweetspot.store import schema
from sweetspot.store.writer import NewObservation, NewPurchaseOption, StoreWriter
from sweetspot.timeutil import to_db

T0 = datetime(2025, 6, 26, 17, 0, tzinfo=UTC)
NOW = datetime(2026, 9, 25, tzinfo=UTC)

EXPECTED_TABLES = {
    "runs", "run_item_results", "wishlist_syncs", "wishlist_items", "wishlist_membership",
    "products", "product_facts", "source_mappings", "price_observations", "current_price_checks",
    "reference_candidates", "catalog_progress", "steam_app_list", "sale_estimates",
    "region_consistency", "schema_meta", "app_versions", "purchase_options",
}


def tw(app_id=620, price=18800, regular=18800, cut=0, observed=T0, source="itad-history", **kw):
    return NewObservation(app_id=app_id, source=source, region="TW", currency=kw.pop("currency", "TWD"),
                          regular_cents=regular, price_cents=price, cut_pct=cut, observed_at=observed,
                          raw_observed_at=None, retrieved_at=kw.pop("retrieved", NOW), **kw)


@pytest.fixture
def writer(db_path):
    w = StoreWriter.open(db_path)
    yield w
    w.close()


def test_all_tables_created_with_wal(writer):
    names = {r[0] for r in writer.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert EXPECTED_TABLES <= names
    assert writer.conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert writer.conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0] == str(
        schema.SCHEMA_VERSION)


def test_null_is_unknown_and_zero_is_known(writer):
    run = writer.start_run("daily")
    writer.add_observations(run, [tw(price=0, regular=18800, cut=100),
                                  tw(price=None, regular=None, cut=None, observed=T0 + timedelta(days=1))])
    rows = writer.conn.execute("SELECT price_cents FROM price_observations ORDER BY observed_at").fetchall()
    assert [r[0] for r in rows] == [0, None]


def test_duplicates_are_ignored_including_null_amounts(writer):
    run = writer.start_run("daily")
    aux = NewObservation(app_id=620, source="itad-history", region="US", currency=None, regular_cents=None,
                         price_cents=None, cut_pct=80, observed_at=T0, raw_observed_at=None, retrieved_at=NOW)
    assert writer.add_observations(run, [tw(), aux]) == 2
    assert writer.add_observations(run, [tw(retrieved=NOW + timedelta(hours=1)), aux]) == 0
    assert writer.conn.execute("SELECT COUNT(*) FROM price_observations").fetchone()[0] == 2


def test_same_time_different_source_both_kept(writer):
    run = writer.start_run("legacy-import")
    writer.add_observations(run, [tw(source="itad-history"), tw(source="legacy-itad")])
    assert writer.conn.execute("SELECT COUNT(*) FROM price_observations").fetchone()[0] == 2


@pytest.mark.parametrize(
    "obs,anomaly",
    [
        (dict(price=-1), "negative-price"),
        (dict(regular=-5), "negative-price"),
        (dict(price=20000, regular=18800), "price-above-regular"),
        (dict(observed=NOW + timedelta(days=1)), "observed-after-retrieved"),
        (dict(currency="USD"), "currency-mismatch"),
        (dict(cut=120), "invalid-cut"),
    ],
)
def test_anomalies_are_isolated(writer, obs, anomaly):
    run = writer.start_run("daily")
    writer.add_observations(run, [tw(**obs)])
    assert writer.conn.execute("SELECT anomaly FROM price_observations").fetchone()[0] == anomaly


def test_aux_region_with_amounts_is_rejected(writer):
    run = writer.start_run("daily")
    bad = NewObservation(app_id=620, source="itad-history", region="US", currency="USD", regular_cents=999,
                         price_cents=199, cut_pct=80, observed_at=T0, raw_observed_at=None, retrieved_at=NOW)
    with pytest.raises(ValueError, match="aux"):
        writer.add_observations(run, [bad])


def test_failed_transaction_rolls_back_only_that_app(writer):
    run = writer.start_run("daily")
    writer.add_observations(run, [tw(app_id=1)])
    with pytest.raises(RuntimeError):
        with writer.transaction():
            writer.add_observations(run, [tw(app_id=2)])
            raise RuntimeError("boom")
    apps = [r[0] for r in writer.conn.execute("SELECT app_id FROM price_observations")]
    assert apps == [1]


@pytest.mark.parametrize("table", ["price_observations", "product_facts", "source_mappings"])
def test_fact_tables_are_append_only(writer, table):
    run = writer.start_run("daily")
    writer.add_observations(run, [tw()])
    writer.add_facts(run, 620, {"name": "Portal 2"}, source="steam-appdetails", retrieved_at=NOW)
    writer.add_mapping(run, 620, "itad", "uuid-620", "verified", checked_at=NOW)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        writer.conn.execute(f"UPDATE {table} SET app_id = 1")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        writer.conn.execute(f"DELETE FROM {table}")


def test_facts_record_volatility_and_reject_unknown_fields(writer):
    run = writer.start_run("daily")
    writer.add_facts(run, 620, {"publishers": ["Valve"], "review_count_total": 467117},
                     source="steam-appdetails", retrieved_at=NOW)
    rows = dict(writer.conn.execute("SELECT field, volatility FROM product_facts"))
    assert rows == {"publishers": "static", "review_count_total": "volatile"}
    with pytest.raises(ValueError, match="unknown fact field"):
        writer.add_facts(run, 620, {"favourite_colour": "blue"}, source="x", retrieved_at=NOW)


def test_run_lifecycle_and_item_results(writer):
    run = writer.start_run("daily")
    writer.record_item_result(run, 620, "current-price", "ok")
    writer.record_item_result(run, 1, "current-price", "delisted", "success-false", "商店查無資料")
    with pytest.raises(ValueError):
        writer.record_item_result(run, 1, "current-price", "weird")
    writer.finish_run(run, "partial", {"x": 1})
    status, summary = writer.conn.execute("SELECT status, summary_json FROM runs").fetchone()
    assert status == "partial" and summary == '{"x": 1}'


def test_interrupted_runs_are_marked(writer):
    run = writer.start_run("daily")
    writer.conn.execute("UPDATE runs SET pid = 999999999 WHERE run_id = ?", (run,))
    own = writer.start_run("daily")
    assert writer.mark_interrupted_runs() == [run]
    statuses = dict(writer.conn.execute("SELECT run_id, status FROM runs"))
    assert statuses == {run: "interrupted", own: "running"}


def test_products_record_first_seen(writer):
    writer.ensure_product(620, "wishlist", NOW)
    writer.ensure_product(620, "legacy-import", NOW + timedelta(days=1))
    assert writer.conn.execute("SELECT first_seen_via FROM products").fetchall() == [("wishlist",)]


# --- feature 006 ------------------------------------------------------------------------------------------------

def test_observation_external_id_is_written(writer):
    run = writer.start_run("daily")
    writer.add_observations(run, [tw(), tw(observed=T0 + timedelta(days=1), external_id="itad-new")])
    rows = writer.conn.execute("SELECT external_id FROM price_observations ORDER BY observed_at").fetchall()
    assert [r[0] for r in rows] == [None, "itad-new"]


def test_add_version_appends_one_row(writer):
    run = writer.start_run("daily")
    row_id = writer.add_version(run, 239140, checked_at=NOW, status="ok", package_id=1345940,
                                package_name="Dying Light Essentials Edition", regular_cents=67000, price_cents=13400,
                                external_id="itad-new", itad_title="Dying Light: Essentials Edition",
                                verification="verified", verified_by="version-check", verified_at=NOW,
                                warnings=["sub/1345941 無法公開查詢"], aliases=["sub/1345941", "sub/1345940"],
                                itad_steam_deals=1)
    row = writer.conn.execute("SELECT app_id, checked_at, run_id, status, package_id, verification, verified_by, "
                              "verified_at, warnings_json, aliases_json, itad_steam_deals, reason_code "
                              "FROM app_versions WHERE version_row_id = ?", (row_id,)).fetchone()
    assert row[:8] == (239140, "2026-09-25T00:00:00.000000Z", run, "ok", 1345940, "verified", "version-check",
                       "2026-09-25T00:00:00.000000Z")
    assert row[8:] == ('["sub/1345941 無法公開查詢"]', '["sub/1345941", "sub/1345940"]', 1, None)


@pytest.mark.parametrize("kw,message", [
    (dict(status="nope"), "status"),
    (dict(status="ok", verification="maybe"), "verification"),
    (dict(status="ok", verification="verified", verified_by="guess"), "verified_by"),
])
def test_add_version_rejects_unknown_codes(writer, kw, message):
    with pytest.raises(ValueError, match=message):
        writer.add_version(None, 1, checked_at=NOW, **kw)


def test_price_check_records_external_id_and_deal_count(writer):
    from sweetspot.pipeline.history import record_price_check
    from sweetspot.sources import PriceQuote

    run = writer.start_run("daily")
    quote = PriceQuote("TWD", 67000, 13400, 80)
    assert record_price_check(writer, run, 239140, quote, quote, now=NOW, external_id="itad-new",
                              itad_steam_deals=1) is True
    assert record_price_check(writer, run, 2, quote, None, now=NOW, external_id="itad-old", itad_steam_deals=0) is None
    rows = writer.conn.execute("SELECT app_id, external_id, itad_steam_deals, match FROM current_price_checks "
                               "ORDER BY app_id").fetchall()
    assert rows == [(2, "itad-old", 0, None), (239140, "itad-new", 1, 1)]


# --- feature 009: purchase_options (data-model §1) ----------------------------------------------------------

def test_add_purchase_options_writes_every_column(writer):
    run = writer.start_run("daily")
    rows = [
        NewPurchaseOption(app_id=1091500, kind="sub", option_id=367653, name="Cyberpunk 2077", original_cents=159900,
                          final_cents=159900, position=0, is_default=True, role="default"),
        NewPurchaseOption(app_id=1091500, kind="bundle", option_id=32470, name="《電馭叛客 2077：終極版》",
                          original_cents=220600, final_cents=220600, position=1, is_default=False, role="edition",
                          contents=[{"app_id": 1091500, "type": 0, "parent_app_id": None},
                                    {"app_id": 2138330, "type": 4, "parent_app_id": 1091500}],
                          contents_checked_at=NOW - timedelta(days=3), external_id="itad-cp-ult",
                          verification="verified", verified_by="version-check", verified_at=NOW,
                          warnings=["sub/9 無法公開查詢"], aliases=["bundle/32470"], itad_steam_deals=1),
    ]
    assert writer.add_purchase_options(run, rows, checked_at=NOW) == 2
    cur = writer.conn.execute("SELECT * FROM purchase_options ORDER BY position")
    names = [d[0] for d in cur.description]
    got = [dict(zip(names, r)) for r in cur.fetchall()]
    assert got[0]["role"] == "default" and got[0]["is_default"] == 1 and got[0]["contents_json"] is None
    ult = got[1]
    assert (ult["kind"], ult["option_id"], ult["run_id"], ult["checked_at"]) == (
        "bundle", 32470, run, to_db(NOW))
    assert json.loads(ult["contents_json"])[1] == {"app_id": 2138330, "type": 4, "parent_app_id": 1091500}
    assert ult["contents_checked_at"] == to_db(NOW - timedelta(days=3))
    assert json.loads(ult["aliases_json"]) == ["bundle/32470"]
    assert json.loads(ult["warnings_json"]) == ["sub/9 無法公開查詢"]
    assert (ult["verification"], ult["verified_by"], ult["verified_at"], ult["itad_steam_deals"]) == (
        "verified", "version-check", to_db(NOW), 1)
    assert (got[0]["bundle_discount_pct"], got[0]["before_bundle_cents"]) == (None, None)


def test_add_purchase_options_writes_the_bundle_discount(writer):
    """feature 010 (data-model §1): bundle_discount_pct, before_bundle_cents and each content's final_cents."""
    contents = [{"app_id": 1868140, "type": None, "parent_app_id": None, "final_cents": 35000},
                {"app_id": 2527500, "type": 0, "parent_app_id": None, "final_cents": 26800}]
    row = NewPurchaseOption(app_id=1868140, kind="bundle", option_id=77855, name="DAVE THE DIVER x MiSide",
                            original_cents=55600, final_cents=55600, position=2, is_default=False, role="other-games",
                            contents=contents, bundle_discount_pct=10, before_bundle_cents=61800)
    writer.add_purchase_options(None, [row], checked_at=NOW)
    got = writer.conn.execute("SELECT bundle_discount_pct, before_bundle_cents, contents_json FROM purchase_options"
                              ).fetchone()
    assert got[:2] == (10, 61800) and json.loads(got[2]) == contents


@pytest.mark.parametrize("field,value", [("kind", "package"), ("role", "deluxe"), ("verification", "maybe"),
                                         ("verified_by", "guess")])
def test_add_purchase_options_checks_value_domains(writer, field, value):
    base = dict(app_id=1, kind="sub", option_id=5, name=None, original_cents=100, final_cents=100, position=0,
                is_default=False, role="edition")
    base[field] = value
    with pytest.raises(ValueError):
        writer.add_purchase_options(None, [NewPurchaseOption(**base)], checked_at=NOW)


# --- fix-quarantine: a valid row can follow a quarantined one (schema v7) ----------------------------------------

def test_a_valid_row_can_follow_a_quarantined_one(writer):
    """The 2026 autumn sale case (Stellar Blade): the event was quarantined because retrieved_at was the batch start;
    a later fetch sees it again with a later retrieved_at and must be able to add it."""
    run = writer.start_run("daily")
    early = tw(cut=33, price=12596, observed=NOW + timedelta(seconds=61))
    assert writer.add_observations(run, [early]) == 1
    late = tw(cut=33, price=12596, observed=NOW + timedelta(seconds=61), retrieved=NOW + timedelta(days=1))
    assert writer.add_observations(run, [late]) == 1
    rows = writer.conn.execute("SELECT anomaly FROM price_observations ORDER BY obs_id").fetchall()
    assert rows == [("observed-after-retrieved",), (None,)]
    again = tw(cut=33, price=12596, observed=NOW + timedelta(seconds=61), retrieved=NOW + timedelta(days=2))
    assert writer.add_observations(run, [again, early]) == 0      # duplicates of either kind are still ignored
