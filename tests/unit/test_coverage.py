"""US6: per-game coverage summary (FR-021, FR-022; data-model §9)."""

import csv
from datetime import UTC, datetime, timedelta

import pytest

from sweetspot import coverage
from sweetspot.store.writer import NewObservation, StoreWriter

NOW = datetime(2026, 9, 25, tzinfo=UTC)


def tw(app, day, cut, *, source="itad-history", regular=10000, price=None, tracking=False):
    price = regular * (100 - cut) // 100 if price is None else price
    return NewObservation(app_id=app, source=source, region="TW", currency="TWD", regular_cents=regular,
                          price_cents=price, cut_pct=cut, observed_at=day, raw_observed_at=None, retrieved_at=NOW,
                          is_tracking_start=tracking)


def us(app, day, cut):
    return NewObservation(app_id=app, source="itad-history", region="US", currency=None, regular_cents=None,
                          price_cents=None, cut_pct=cut, observed_at=day, raw_observed_at=None, retrieved_at=NOW)


D = lambda y, m, d: datetime(y, m, d, 18, tzinfo=UTC)  # noqa: E731


@pytest.fixture
def writer(db_path):
    w = StoreWriter.open(db_path)
    run = w.start_run("daily")
    w.add_observations(run, [
        # app 1: normal history, a free giveaway, US data, and a current-price series with a 120-day hole
        tw(1, D(2024, 12, 11), 0, tracking=True), tw(1, D(2025, 3, 13), 50), tw(1, D(2025, 3, 20), 0),
        tw(1, D(2025, 6, 26), 60), tw(1, D(2025, 7, 10), 0),
        tw(1, D(2025, 8, 1), 100, price=0), tw(1, D(2025, 8, 8), 0),
        us(1, D(2020, 1, 1), 0),
        tw(1, D(2026, 1, 1), 0, source="steam-current"), tw(1, D(2026, 5, 1), 0, source="steam-current"),
        tw(1, D(2026, 9, 20), 0, source="steam-current"),
    ])
    w.conn.execute("INSERT INTO history_fetches (app_id, source, region, fetched_at, entries) "
                   "VALUES (2, 'itad', 'TW', '2026-09-25T00:00:00.000000Z', 0)")
    w.add_mapping(run, 1, "itad", "id-1", "verified", checked_at=NOW)
    w.add_mapping(run, 3, "itad", None, "rejected", checked_at=NOW, reason_code="bundle")
    yield w
    w.close()


def test_history_state_distinguishes_none_not_fetched_available(writer):
    assert coverage.coverage(writer.conn, 1, NOW).history_state == "available"
    assert coverage.coverage(writer.conn, 2, NOW).history_state == "none"          # asked, nothing there
    assert coverage.coverage(writer.conn, 3, NOW).history_state == "not-fetched"   # never asked


def test_zero_sales_differs_from_no_history(writer):
    none = coverage.coverage(writer.conn, 2, NOW)
    assert none.paid_sale_count is None and none.free_promo_count is None   # unknown, not zero


def test_counts_paid_sales_and_free_promos_separately(writer):
    c = coverage.coverage(writer.conn, 1, NOW)
    assert c.paid_sale_count == 2 and c.free_promo_count == 1


def test_ranges_per_region(writer):
    c = coverage.coverage(writer.conn, 1, NOW)
    assert c.tw_earliest.date().isoformat() == "2024-12-11" and c.tw_latest.date().isoformat() == "2025-08-08"
    assert c.aux_available and c.aux_earliest.year == 2020


def test_data_gaps_are_holes_in_our_own_price_series(writer):
    c = coverage.coverage(writer.conn, 1, NOW)
    assert [(g.start.date().isoformat(), g.end.date().isoformat()) for g in c.data_gaps] == [
        ("2026-01-01", "2026-05-01"), ("2026-05-01", "2026-09-20")]


def test_long_unchanged_are_hints_from_change_only_history(writer):
    c = coverage.coverage(writer.conn, 1, NOW)
    spans = [(g.start.date().isoformat(), g.end.date().isoformat()) for g in c.long_unchanged]
    assert ("2024-12-11", "2025-03-13") in spans           # 92 days without a change
    assert spans[-1][0] == "2025-08-08" and spans[-1][1] == NOW.date().isoformat()   # unchanged since
    assert "ITAD" in c.note


def test_mapping_state_and_reason(writer):
    assert coverage.coverage(writer.conn, 1, NOW).mapping_state == "verified"
    rejected = coverage.coverage(writer.conn, 3, NOW)
    assert rejected.mapping_state == "rejected" and rejected.mapping_reason == "bundle"
    assert coverage.coverage(writer.conn, 2, NOW).mapping_state is None


@pytest.mark.parametrize("value,expected", [
    ("=HYPERLINK(\"x\")", "'=HYPERLINK(\"x\")"), ("+1", "'+1"), ("-1", "'-1"), ("@SUM(A1)", "'@SUM(A1)"),
    ("\tx", "'\tx"), ("\rx", "'\rx"), ("Portal 2", "Portal 2"), (None, ""), (12, "12"),
])
def test_csv_cells_are_escaped(value, expected):
    assert coverage.csv_cell(value) == expected


def test_write_csv(writer, tmp_path):
    rows = [coverage.coverage(writer.conn, a, NOW) for a in (1, 2)]
    path = tmp_path / "out.csv"
    coverage.write_csv(path, rows, names={1: "=evil()", 2: "Fine"})
    with path.open(encoding="utf-8-sig", newline="") as handle:
        table = list(csv.DictReader(handle))
    assert table[0]["name"] == "'=evil()" and table[0]["history_state"] == "available"
    assert table[1]["paid_sale_count"] == ""


# --- feature 006 --------------------------------------------------------------------------------------------------

def test_coverage_reads_one_itad_product(writer):
    before = coverage.coverage(writer.conn, 1, NOW)
    run = writer.start_run("daily")
    writer.add_observations(run, [NewObservation(**{**vars(tw(1, D(2025, 9, 1), 90)), "external_id": "id-other"})])
    after = coverage.coverage(writer.conn, 1, NOW, key="id-1")
    assert (after.tw_latest, after.paid_sale_count) == (before.tw_latest, before.paid_sale_count)
    assert coverage.coverage(writer.conn, 1, NOW).paid_sale_count == before.paid_sale_count + 1


def test_edition_history_and_fetches_do_not_change_coverage(writer):
    """Feature 009: an edition's rows (itad-option-history) and fetches (itad-option) are not the app's history."""
    before = {a: coverage.coverage(writer.conn, a, NOW) for a in (1, 2, 4)}
    run = writer.start_run("daily")
    writer.add_observations(run, [tw(4, D(2025, 3, 13), 50, source="itad-option-history", tracking=True),
                                  tw(1, D(2025, 9, 1), 70, source="itad-option-history")])
    writer.conn.execute("INSERT INTO history_fetches (app_id, source, region, fetched_at, entries) "
                        "VALUES (4, 'itad-option', 'TW', '2026-09-25T00:00:00.000000Z', 1)")
    after = {a: coverage.coverage(writer.conn, a, NOW) for a in (1, 2, 4)}
    assert after == before
    assert after[4].history_state == "not-fetched"
