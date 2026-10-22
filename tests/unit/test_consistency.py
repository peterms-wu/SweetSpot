"""US6: TW vs aux-region discount consistency (FR-007b, SC-010)."""

from datetime import UTC, datetime, timedelta

import pytest

from sweetspot.pipeline import consistency
from sweetspot.store.writer import NewObservation, StoreWriter

NOW = datetime(2025, 9, 1, tzinfo=UTC)
D = lambda m, d, h=18: datetime(2025, m, d, h, tzinfo=UTC)  # noqa: E731


def obs(app, region, day, cut, tracking=False):
    tw = region == "TW"
    return NewObservation(app_id=app, source="itad-history", region=region, currency="TWD" if tw else None,
                          regular_cents=10000 if tw else None, price_cents=10000 * (100 - cut) // 100 if tw else None,
                          cut_pct=cut, observed_at=day, raw_observed_at=None, retrieved_at=NOW,
                          is_tracking_start=tracking)


@pytest.fixture
def writer(db_path):
    w = StoreWriter.open(db_path)
    run = w.start_run("daily")
    w.add_observations(run, [
        # app 1: TW tracking starts 01-01; TW sales 03-13 (50%) and 06-26 (60%); US matches the first one a day
        # later and runs the second at 50% instead of 60%.
        obs(1, "TW", D(1, 1), 0, tracking=True), obs(1, "TW", D(3, 13), 50), obs(1, "TW", D(3, 20), 0),
        obs(1, "TW", D(6, 26), 60), obs(1, "TW", D(7, 10), 0),
        obs(1, "US", D(1, 1), 0, tracking=True), obs(1, "US", D(3, 14), 50), obs(1, "US", D(3, 20), 0),
        obs(1, "US", D(6, 26), 50), obs(1, "US", D(7, 10), 0),
        # app 2: TW only
        obs(2, "TW", D(1, 1), 0, tracking=True), obs(2, "TW", D(4, 1), 30),
    ])
    yield w
    w.close()


def test_overlap_starts_at_first_non_tracking_start_tw_row(writer):
    result = consistency.compute(writer.conn, 1, "US", now=NOW)
    assert result.overlap_start == D(3, 13) and result.overlap_end == NOW


def test_daily_same_cut_comparison(writer):
    result = consistency.compute(writer.conn, 1, "US", now=NOW)
    # 03-13..08-31 compared at 12:00 UTC each day: 03-13 differs (US starts 03-14), 06-26..07-09 differ (60 vs 50)
    assert result.days_compared == (NOW.date() - D(3, 13).date()).days
    assert result.days_compared - result.days_same_cut == 1 + 14


def test_sale_matching_within_one_day(writer):
    result = consistency.compute(writer.conn, 1, "US", now=NOW)
    assert result.sales_tw == 2 and result.sales_matched == 1


def test_no_aux_data_means_no_result(writer):
    assert consistency.compute(writer.conn, 2, "US", now=NOW) is None


def test_refresh_writes_per_app_rows_and_all(writer):
    rows = consistency.refresh(writer, [1, 2], "US", now=NOW)
    scopes = {r.scope for r in rows}
    assert scopes == {"1", "ALL"}
    all_row = next(r for r in rows if r.scope == "ALL")
    one = next(r for r in rows if r.scope == "1")
    assert all_row.days_compared >= one.days_compared and all_row.sales_tw >= one.sales_tw
    stored = writer.conn.execute("SELECT scope, days_compared, sales_matched FROM region_consistency").fetchall()
    assert {s for s, _, _ in stored} == {"1", "ALL"}


def test_all_covers_every_app_with_both_regions(writer):
    run = writer.start_run("daily")
    writer.add_observations(run, [obs(3, "TW", D(1, 1), 0, tracking=True), obs(3, "TW", D(5, 1), 40),
                                  obs(3, "US", D(1, 1), 0, tracking=True), obs(3, "US", D(5, 1), 40)])
    rows = consistency.refresh(writer, [1], "US", now=NOW)   # per-app rows only for app 1
    all_row = next(r for r in rows if r.scope == "ALL")
    assert all_row.sales_tw == 3 and all_row.sales_matched == 2   # apps 1 and 3
    assert {r.scope for r in rows} == {"1", "ALL"}


# --- feature 006 --------------------------------------------------------------------------------------------------

def test_another_itad_product_is_not_mixed_in(writer):
    before = consistency.compute(writer.conn, 1, "US", now=NOW)
    run = writer.start_run("daily")
    other = [NewObservation(**{**vars(o), "external_id": "itad-other"}) for o in (
        obs(1, "TW", D(4, 10), 90), obs(1, "US", D(4, 10), 10))]
    writer.add_observations(run, other)
    writer.add_mapping(run, 1, "itad", "itad-own", "verified", checked_at=NOW)
    assert consistency.compute(writer.conn, 1, "US", now=NOW, key="itad-own") == before
    mixed = consistency.compute(writer.conn, 1, "US", now=NOW)      # no key: every row, as before 006
    assert mixed != before


def test_edition_histories_do_not_change_consistency(writer):
    """Feature 009: an edition's TW and US rows (itad-option-history) are left out of the region comparison."""
    before = consistency.compute(writer.conn, 1, "US", now=NOW)
    run = writer.start_run("daily")
    edition = [NewObservation(app_id=a, source="itad-option-history", region=r, currency="TWD" if r == "TW" else None,
                              regular_cents=20000 if r == "TW" else None,
                              price_cents=(20000 * (100 - c) // 100) if r == "TW" else None, cut_pct=c,
                              observed_at=day, raw_observed_at=None, retrieved_at=NOW, external_id=f"ed-{a}")
               for a in (1, 2) for r in ("TW", "US") for day, c in ((D(2, 1), 0), (D(5, 5), 90), (D(5, 20), 0))]
    writer.add_observations(run, edition)
    assert consistency.compute(writer.conn, 1, "US", now=NOW) == before
    rows = consistency.refresh(writer, [1, 2], "US", now=NOW)
    assert [r.scope for r in rows] == ["1", "ALL"]            # app 2 still has no US history of its own
