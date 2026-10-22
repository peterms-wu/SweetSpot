"""store-api sales(): past sales always; future sales only in the present (no look-ahead in backtests)."""

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sweetspot import calendar as cal
from sweetspot.store.query import PriceStore
from sweetspot.store.writer import StoreWriter
from sweetspot.timeutil import now_utc

CALENDAR = Path(__file__).parents[2] / "data" / "steam_sales.toml"


@pytest.fixture
def store(db_path):
    w = StoreWriter.open(db_path)
    shutil.copy(CALENDAR, db_path.parent / "steam_sales.toml")
    events = cal.load_calendar(CALENDAR, now=now_utc())
    cal.refresh_estimates(w, events, now=now_utc(), horizon_months=24)
    w.close()
    s = PriceStore.open(db_path)
    yield s
    s.close()


def test_backtest_sees_no_sale_that_starts_after_as_of(store):
    as_of = datetime(2025, 6, 1, tzinfo=UTC)
    events = store.sales(as_of)
    assert events and all(e.start <= as_of for e in events)
    assert all(e.status == "ended" for e in events if e.end <= as_of)
    assert not any(e.status == "estimated" for e in events)


def test_sale_in_progress_at_as_of_is_announced_not_ended(store):
    during = datetime(2025, 6, 30, tzinfo=UTC)
    summer = [e for e in store.sales(during) if cal.label(e) == "2025 夏特"]
    assert summer and summer[0].status == "announced"


def test_present_includes_announced_future_sales_and_estimates(store):
    labels = {cal.label(e): e.status for e in store.sales(now_utc())}
    assert labels.get("2027 夏特") == "announced"
    assert labels.get("2027 冬特") == "estimated"
    without = {cal.label(e) for e in store.sales(now_utc(), include_estimates=False)}
    assert "2027 冬特" not in without


OFFICIAL = "https://partner.steamgames.com/doc/marketing/discounts/seasonalsales"


@pytest.fixture
def store_with_official(db_path):
    """Feature 012: the database has official sightings of 2027 autumn (not in the file) and of 2026 winter one day
    later than the file. Estimates are NOT refreshed afterwards, so the 2027 autumn estimate is still open."""
    from datetime import date, time
    from zoneinfo import ZoneInfo

    from sweetspot import calendar_sync
    from sweetspot.sources import OfficialSale, SeasonalSalesPage

    w = StoreWriter.open(db_path)
    shutil.copy(CALENDAR, db_path.parent / "steam_sales.toml")
    cal.refresh_estimates(w, cal.load_calendar(CALENDAR, now=now_utc()), now=now_utc(), horizon_months=24)
    page = SeasonalSalesPage(url=OFFICIAL, fetched_at=now_utc(), http_status=200, bytes=1, sha256="0" * 64,
                             found_dates_section=True, sales=[
                                 OfficialSale("winter", 2026, date(2026, 12, 18), date(2027, 1, 4)),
                                 OfficialSale("autumn", 2027, date(2027, 9, 30), date(2027, 10, 7))])
    calendar_sync.record_fetch(w, page, now=now_utc(), default_time=time(10), tz=ZoneInfo("America/Los_Angeles"))
    w.close()
    s = PriceStore.open(db_path)
    yield s
    s.close()


def test_adopted_official_sales_are_part_of_the_calendar(store_with_official):
    now = now_utc()
    sales = {cal.label(e): e for e in store_with_official.sales(now)}
    autumn = sales["2027 秋特"]
    assert (autumn.status, autumn.confidence, autumn.source) == ("announced", "official", OFFICIAL)
    assert sum(cal.label(e) == "2027 秋特" for e in store_with_official.sales(now)) == 1   # no leftover estimate
    winter = sales["2026 冬特"]
    assert winter.start == datetime(2026, 12, 17, 18, tzinfo=UTC)       # the file's date wins over the page's 12/18
    assert "2027 秋特" in {cal.label(e) for e in store_with_official.calendar_events()}


def test_sales_for_observation(store):
    from sweetspot.store.query import Observation

    t = datetime(2025, 6, 27, tzinfo=UTC)
    obs = Observation(620, "TW", "itad-history", t, t, 18800, 3760, 80, False)
    assert [cal.label(e) for e in store.sales_for(obs)] == ["2025 夏特"]
    outside = Observation(620, "TW", "itad-history", t + timedelta(days=40), t, 18800, 3760, 80, False)
    assert store.sales_for(outside) == []
