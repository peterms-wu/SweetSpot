"""feature 013 (research R3, FR-001–FR-003): which sale and which record the comparison uses (tasks T003)."""

import gzip

import pytest

from sweetspot.calendar import SaleEvent
from sweetspot.review.target import TargetError, parse_sale, select_target
from tests.forecast_builders import dt
from tests.review_builders import (AS_OF, DURING_AS_OF, EARLY, RECORD, during_records, pre_sale_record,
                                   write_records)


def event(season, year, start, end, kind="seasonal"):
    return SaleEvent(f"{season} {year}", "特賣", kind, season, year, dt(start), dt(end), "ended", "test")


EVENTS = [event("summer", 2026, "2026-06-25T17:00", "2026-07-09T17:00"),
          event("autumn", 2026, "2026-10-01T17:00", "2026-10-08T17:00"),
          event(None, 2026, "2026-10-12T17:00", "2026-10-19T17:00", kind="themed"),
          event("winter", 2026, "2026-12-17T18:00", "2027-01-04T18:00")]


@pytest.fixture
def forecasts(tmp_path):
    d = tmp_path / "forecasts"
    write_records(d, [pre_sale_record(as_of="2026-09-29T18:30:00Z"), pre_sale_record(),
                      *during_records(EARLY)])
    return d


def test_parse_sale():
    assert parse_sale("autumn-2026") == ("autumn", 2026)
    for bad in ("autumn2026", "fall-2026", "autumn-26x", ""):
        with pytest.raises(TargetError):
            parse_sale(bad)


def test_defaults_to_the_latest_ended_sale_and_the_last_official_record_before_it(forecasts):
    t = select_target(EVENTS, forecasts, today=dt("2026-10-12"))
    assert (t.sale.season, t.sale.year) == ("autumn", 2026)
    assert t.record_path.name == RECORD and t.as_of == AS_OF
    assert [p.name[:16] for p, _ in t.during] == [s.replace("-", "").replace(":", "")[:16] for s in DURING_AS_OF]
    assert t.missing_days == () and t.skipped_records == () and not t.forced
    assert t.hours_before_start == 22.5
    assert t.today == dt("2026-10-12")


def test_named_sale(forecasts):
    t = select_target(EVENTS, forecasts, sale="autumn-2026", today=dt("2026-10-12"))
    assert t.sale.season == "autumn"
    with pytest.raises(TargetError, match="找不到"):
        select_target(EVENTS, forecasts, sale="spring-2026", today=dt("2026-10-12"))


def test_themed_sales_are_never_targets(forecasts):
    with pytest.raises(TargetError, match="季節特賣"):
        select_target([e for e in EVENTS if e.kind == "themed"], forecasts, today=dt("2026-11-01"))


def test_a_sale_that_has_not_ended_is_refused(forecasts):
    with pytest.raises(TargetError, match="還沒結束"):
        select_target(EVENTS, forecasts, sale="winter-2026", today=dt("2026-10-12"))


def test_less_than_three_days_after_the_end_needs_force(forecasts):
    with pytest.raises(TargetError, match="3 天"):
        select_target(EVENTS, forecasts, sale="autumn-2026", today=dt("2026-10-10"))
    t = select_target(EVENTS, forecasts, sale="autumn-2026", today=dt("2026-10-10"), force=True)
    assert t.forced


def test_unofficial_and_unreadable_records_are_skipped(tmp_path):
    d = tmp_path / "forecasts"
    write_records(d, [pre_sale_record(as_of="2026-09-29T18:30:00Z"),
                      pre_sale_record(as_of="2026-09-30T18:31:37Z", official=False)])
    (d / "20260930T200000Z.json.gz").write_bytes(gzip.compress(b"not json"))
    t = select_target(EVENTS, d, today=dt("2026-10-12"))
    assert t.record_path.name == "20260929T183000Z.json.gz"
    assert t.skipped_records == ("20260930T200000Z.json.gz",)


def test_the_content_as_of_decides_not_the_file_name(tmp_path):
    d = tmp_path / "forecasts"
    write_records(d, [pre_sale_record(as_of="2026-09-29T18:30:00Z")])
    late = d / "20260929T183000Z.json.gz"
    late.rename(d / "20260101T000000Z.json.gz")
    write_records(d, [pre_sale_record(as_of="2026-10-02T18:30:00Z")])     # during the sale: not a forecast
    t = select_target(EVENTS, d, today=dt("2026-10-12"))
    assert t.record_path.name == "20260101T000000Z.json.gz" and t.as_of == dt("2026-09-29T18:30")


def test_no_record_before_the_sale(tmp_path):
    d = tmp_path / "forecasts"
    write_records(d, during_records(EARLY))
    with pytest.raises(TargetError, match="開賣前"):
        select_target(EVENTS, d, today=dt("2026-10-12"))


def test_a_named_record(forecasts):
    t = select_target(EVENTS, forecasts, record="20260929T183000Z.json.gz", today=dt("2026-10-12"))
    assert t.as_of == dt("2026-09-29T18:30")
    t = select_target(EVENTS, forecasts, record=str(forecasts / RECORD), today=dt("2026-10-12"))
    assert t.as_of == AS_OF
    with pytest.raises(TargetError, match="特賣結束"):
        select_target(EVENTS, forecasts, sale="summer-2026", record=RECORD, today=dt("2026-10-12"))
    with pytest.raises(TargetError):
        select_target(EVENTS, forecasts, record="20990101T000000Z.json.gz", today=dt("2026-10-12"))


def test_missing_sale_days(tmp_path):
    d = tmp_path / "forecasts"
    write_records(d, [pre_sale_record(), *during_records(EARLY, days=[0, 1, 2, 4, 5, 6]),
                      *during_records(EARLY, days=[3], official=False)])
    t = select_target(EVENTS, d, today=dt("2026-10-12"))
    assert len(t.during) == 6
    assert t.missing_days == ("2026-10-05",)        # 10/4 18:31Z is Taipei 10/5; the only record that day is unofficial
