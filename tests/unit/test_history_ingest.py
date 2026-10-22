import json
from datetime import UTC, datetime, timedelta

import pytest

from sweetspot.pipeline import history
from sweetspot.sources import PriceQuote
from sweetspot.sources import itad
from sweetspot.store.writer import StoreWriter
from sweetspot.timeutil import to_db
from tests.conftest import FIXTURES

NOW = datetime(2026, 9, 25, tzinfo=UTC)
ID_620 = "018d937f-21e1-728e-86d7-9acb3c59f2bb"


def raw(name):
    return json.loads((FIXTURES / "itad" / name).read_text(encoding="utf-8"))


class FixtureHistory:
    def __init__(self):
        self.calls = []

    def history(self, external_id, country, since):
        self.calls.append((external_id, country))
        return itad.parse_history(raw(f"history_620_{country}.json"))


@pytest.fixture
def writer(db_path):
    w = StoreWriter.open(db_path)
    yield w
    w.close()


def ingest(writer, source, region, now=NOW):
    run = writer.start_run("daily")
    return history.ingest_history(writer, source, app_id=620, external_id=ID_620, region=region,
                                  primary_region="TW", now=now, run_id=run)


def rows(writer, region):
    return writer.conn.execute(
        "SELECT observed_at, raw_observed_at, currency, regular_cents, price_cents, cut_pct, is_tracking_start, "
        "retrieved_at FROM price_observations WHERE region = ? ORDER BY observed_at", (region,)).fetchall()


def test_parse_history_converts_to_utc_cents():
    entries = itad.parse_history(raw("history_620_TW.json"))
    assert entries == sorted(entries, key=lambda e: e.observed_at)
    first = entries[0]
    assert first.observed_at == datetime(2024, 12, 11, 14, 6, 55, tzinfo=UTC)
    assert first.raw_timestamp == "2024-12-11T15:06:55+01:00"
    assert first.currency == "TWD" and first.regular_cents == 18800 and first.cut_pct == 0


def test_first_record_of_series_is_tracking_start_even_during_a_sale(writer):
    entries = itad.parse_history(raw("history_620_TW.json"))
    sale_first = [e for e in entries if e.cut_pct][:1] + [e for e in entries if not e.cut_pct]
    observations = history.to_observations(620, sale_first, region="TW", primary_region="TW", retrieved_at=NOW)
    earliest = min(observations, key=lambda o: o.observed_at)
    assert earliest.is_tracking_start and sum(o.is_tracking_start for o in observations) == 1


def test_tw_first_zero_cut_record_is_tracking_start(writer):
    result = ingest(writer, FixtureHistory(), "TW")
    stored = rows(writer, "TW")
    assert result.new_rows == len(stored) == 19
    assert stored[0][6] == 1 and sum(r[6] for r in stored) == 1
    assert stored[0][1] == "2024-12-11T15:06:55+01:00"  # raw timestamp kept
    assert all(r[2] == "TWD" for r in stored)


def test_aux_region_keeps_only_discount_and_time(writer):
    ingest(writer, FixtureHistory(), "US")
    stored = rows(writer, "US")
    # 148 raw rows; two share a timestamp with cut 0 (a US list-price change 9.99 -> 1.99). Without
    # amounts they are the same discount state, so they deduplicate to one row.
    assert len(stored) == 147
    assert all(r[2] is None and r[3] is None and r[4] is None for r in stored)
    assert {r[5] for r in stored} >= {0, 80, 90}
    assert stored[0][0].startswith("2012-11-22")


def test_fetch_is_logged_and_freshness_respected(writer):
    source = FixtureHistory()
    ingest(writer, source, "TW")
    assert history.history_is_fresh(writer, 620, "TW", NOW + timedelta(hours=23), timedelta(hours=24))
    assert not history.history_is_fresh(writer, 620, "TW", NOW + timedelta(hours=25), timedelta(hours=24))
    assert not history.history_is_fresh(writer, 620, "US", NOW, timedelta(hours=24))


def test_refetch_adds_nothing_and_keeps_original_retrieved_at(writer):
    ingest(writer, FixtureHistory(), "TW")
    result = ingest(writer, FixtureHistory(), "TW", now=NOW + timedelta(days=2))
    assert result.new_rows == 0
    assert {r[7] for r in rows(writer, "TW")} == {"2026-09-25T00:00:00.000000Z"}


def test_empty_history_is_logged_as_fetched(writer):
    class Empty:
        def history(self, external_id, country, since):
            return []

    result = ingest(writer, Empty(), "TW")
    assert result.new_rows == 0 and result.entries == 0
    assert history.fetch_state(writer, 620, "TW") == "none"
    assert history.fetch_state(writer, 413150, "TW") == "not-fetched"


def test_price_check_records_both_sides(writer):
    run = writer.start_run("daily")
    history.record_price_check(writer, run, 620, PriceQuote("TWD", 18800, 18800, 0),
                               PriceQuote("TWD", 18800, 3700, 80), now=NOW)
    history.record_price_check(writer, run, 413150, PriceQuote("TWD", 39800, 39800, 0),
                               PriceQuote("TWD", 39800, 39800, 0), now=NOW)
    history.record_price_check(writer, run, 1, None, PriceQuote("TWD", 100, 100, 0), now=NOW)
    checks = writer.conn.execute(
        "SELECT app_id, steam_price_cents, itad_price_cents, match FROM current_price_checks ORDER BY app_id"
    ).fetchall()
    assert checks == [(1, None, 100, None), (620, 18800, 3700, 0), (413150, 39800, 39800, 1)]


# --- feature 006 --------------------------------------------------------------------------------------------------

def test_ingested_rows_and_fetch_carry_the_itad_product(writer):
    ingest(writer, FixtureHistory(), "TW")
    ingest(writer, FixtureHistory(), "US")
    products = writer.conn.execute("SELECT DISTINCT external_id FROM price_observations").fetchall()
    assert products == [(ID_620,)]
    fetches = writer.conn.execute("SELECT region, external_id FROM history_fetches ORDER BY region").fetchall()
    assert fetches == [("TW", ID_620), ("US", ID_620)]


def test_to_observations_tags_every_row():
    entries = itad.parse_history(raw("history_620_TW.json"))
    rows = history.to_observations(620, entries, region="TW", primary_region="TW", retrieved_at=NOW,
                                   external_id="itad-x")
    assert rows and {r.external_id for r in rows} == {"itad-x"}


# --- feature 009: edition fetches (source itad-option) never count as the app's own fetches --------------------

def _option_fetch(writer, region="TW", when=NOW):
    writer.conn.execute("INSERT INTO history_fetches (app_id, source, region, fetched_at, entries, external_id) "
                        "VALUES (620, 'itad-option', ?, ?, 5, 'itad-edition')", (region, to_db(when)))


def test_edition_fetches_do_not_make_the_app_fresh_or_fetched(writer):
    _option_fetch(writer)
    assert history.fetch_state(writer, 620, "TW") == "not-fetched"
    assert not history.history_is_fresh(writer, 620, "TW", NOW, timedelta(hours=24))
    assert history.history_is_fresh(writer, 620, "TW", NOW, timedelta(hours=24), external_id="itad-edition",
                                    source="itad-option")
    ingest(writer, FixtureHistory(), "TW")
    assert history.fetch_state(writer, 620, "TW") == "available"


def test_ingest_history_can_write_an_edition(writer):
    run = writer.start_run("daily")
    history.ingest_history(writer, FixtureHistory(), app_id=620, external_id="itad-edition", region="TW",
                           primary_region="TW", now=NOW, run_id=run, observation_source="itad-option-history",
                           fetch_source="itad-option")
    assert {s for (s,) in writer.conn.execute("SELECT DISTINCT source FROM price_observations")} == {
        "itad-option-history"}
    assert writer.conn.execute("SELECT source, external_id FROM history_fetches").fetchall() == [
        ("itad-option", "itad-edition")]
    assert history.fetch_state(writer, 620, "TW") == "not-fetched"


# --- fix-quarantine: retrieved_at is when the response arrived, not when the batch started ------------------------

class LateEvent:
    """ITAD recorded a price change a few seconds after the batch started, before this app was fetched."""

    def history(self, external_id, country, since):
        entries = itad.parse_history(raw(f"history_620_{country}.json"))
        from dataclasses import replace
        return entries + [replace(entries[-1], observed_at=NOW + timedelta(seconds=61), cut_pct=33)]


def test_the_fetch_time_comes_from_the_clock(writer):
    run = writer.start_run("daily")
    history.ingest_history(writer, LateEvent(), app_id=620, external_id=ID_620, region="TW", primary_region="TW",
                           now=NOW, run_id=run, clock=lambda: NOW + timedelta(seconds=90))
    got = writer.conn.execute("SELECT COUNT(*), SUM(anomaly IS NOT NULL), MIN(retrieved_at) FROM price_observations "
                              "WHERE region = 'TW'").fetchone()
    assert got[1] == 0 and got[2] == to_db(NOW + timedelta(seconds=90))
    fetched = writer.conn.execute("SELECT fetched_at FROM history_fetches").fetchone()[0]
    assert fetched == to_db(NOW + timedelta(seconds=90))


def test_without_a_clock_the_late_event_is_quarantined(writer):
    """The old behaviour, kept for callers that pass no clock: documents what the fix is about."""
    run = writer.start_run("daily")
    history.ingest_history(writer, LateEvent(), app_id=620, external_id=ID_620, region="TW", primary_region="TW",
                           now=NOW, run_id=run)
    assert writer.conn.execute("SELECT anomaly FROM price_observations WHERE observed_at = ?",
                               (to_db(NOW + timedelta(seconds=61)),)).fetchone()[0] == "observed-after-retrieved"


def test_a_clock_behind_now_never_moves_the_fetch_earlier(writer):
    run = writer.start_run("daily")
    history.ingest_history(writer, FixtureHistory(), app_id=620, external_id=ID_620, region="TW",
                           primary_region="TW", now=NOW, run_id=run, clock=lambda: NOW - timedelta(hours=1))
    assert writer.conn.execute("SELECT fetched_at FROM history_fetches").fetchone()[0] == to_db(NOW)
