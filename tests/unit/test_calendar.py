"""US7: Steam sale calendar (contracts/sales-calendar.md; FR-030..033)."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from sweetspot import calendar as cal
from sweetspot.store.writer import NewObservation, StoreWriter

ROOT = Path(__file__).parents[2]
NOW = datetime(2026, 9, 25, tzinfo=UTC)

HEADER = 'schema_version = 1\ndefault_time = "10:00"\ndefault_tz = "America/Los_Angeles"\n'


def sale(**kw):
    base = dict(name="Steam Summer Sale", name_zh="夏季特賣", kind="seasonal", season="summer", year=2025,
                start="2025-06-26", end="2025-07-10", status="ended", source="https://store.steampowered.com/x",
                confidence="official")
    base.update(kw)
    lines = ["[[sale]]"]
    for key, value in base.items():
        if value is None:
            continue
        lines.append(f"{key} = {value}" if isinstance(value, int) else f'{key} = "{value}"')
    return "\n".join(lines) + "\n"


def load(tmp_path, *sales, now=NOW):
    path = tmp_path / "steam_sales.toml"
    path.write_text(HEADER + "\n".join(sales), encoding="utf-8")
    return cal.load_calendar(path, now=now)


# --- the real calendar file ----------------------------------------------------------------------

def test_project_calendar_is_valid_and_covers_every_season_since_2024():
    events = cal.load_calendar(ROOT / "data" / "steam_sales.toml", now=NOW)
    seasonal = {(e.year, e.season) for e in events if e.kind == "seasonal"}
    for year in (2024, 2025):
        for season in cal.SEASONS:
            assert (year, season) in seasonal  # SC-009
    assert all(e.source.startswith("https://") and "steamdb" not in e.source for e in events)


def test_times_are_10am_pacific_in_utc():
    events = cal.load_calendar(ROOT / "data" / "steam_sales.toml", now=NOW)
    summer = next(e for e in events if e.year == 2025 and e.season == "summer")
    winter = next(e for e in events if e.year == 2025 and e.season == "winter")
    assert summer.start == datetime(2025, 6, 26, 17, tzinfo=UTC)   # PDT
    assert winter.end == datetime(2026, 1, 5, 18, tzinfo=UTC)      # PST


# --- validation ----------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "bad,message",
    [
        (dict(start="2025-07-10", end="2025-06-26"), "start"),
        (dict(end="2025-08-30"), "天數"),
        (dict(status="ended", start="2026-12-17", end="2027-01-04", year=2026, season="winter"), "ended"),
        (dict(source="https://steamdb.info/sales/"), "steamdb"),
        (dict(source="http://example.com"), "https"),
        (dict(kind="weird"), "kind"),
        (dict(season="monsoon"), "season"),
        (dict(confidence="rumour"), "confidence"),
    ],
)
def test_validation_rejects_bad_entries(tmp_path, bad, message):
    with pytest.raises(cal.CalendarError, match=message):
        load(tmp_path, sale(**bad))


def test_duplicate_season_in_a_year_is_rejected(tmp_path):
    with pytest.raises(cal.CalendarError, match="重複"):
        load(tmp_path, sale(), sale(start="2025-06-30", end="2025-07-12"))


def test_announced_sale_that_has_since_ended_is_treated_as_ended(tmp_path):
    events = load(tmp_path, sale(status="announced"))
    assert events[0].status == "ended"


def test_themed_sales_do_not_need_a_season(tmp_path):
    events = load(tmp_path, sale(kind="themed", season=None, name="Steam Scream 4", name_zh="Steam 尖叫節 4",
                                 start="2025-10-27", end="2025-11-03"))
    assert events[0].season is None and cal.label(events[0]) == "2025 Steam 尖叫節 4"


# --- mapping observations to sales ------------------------------------------------------------------

def test_observation_inside_sale_window_maps_to_it(tmp_path):
    events = load(tmp_path, sale())
    inside = datetime(2025, 6, 27, tzinfo=UTC)
    assert [e.name for e in cal.sales_at(events, inside)] == ["Steam Summer Sale"]
    assert cal.sales_at(events, datetime(2025, 7, 10, 17, tzinfo=UTC)) == []  # end is exclusive
    assert cal.sales_at(events, datetime(2025, 8, 1, tzinfo=UTC)) == []        # outside any sale


def test_overlapping_sales_are_both_returned(tmp_path):
    events = load(tmp_path, sale(), sale(kind="themed", season=None, name="Fest", name_zh="節",
                                         start="2025-07-07", end="2025-07-14"))
    assert len(cal.sales_at(events, datetime(2025, 7, 8, tzinfo=UTC))) == 2


def test_labels():
    event = cal.SaleEvent("Steam Winter Sale", "冬季特賣", "seasonal", "winter", 2026,
                          datetime(2026, 12, 17, 18, tzinfo=UTC), datetime(2027, 1, 4, 18, tzinfo=UTC), "announced",
                          "https://x")
    assert cal.label(event) == "2026 冬特"


# --- estimates ----------------------------------------------------------------------------------

def test_estimate_uses_last_year_aligned_to_same_weekday():
    events = [e for e in cal.load_calendar(ROOT / "data" / "steam_sales.toml", now=NOW) if e.year <= 2025]
    estimate = cal.estimate_sale(events, "autumn", 2026)
    # 2025 autumn started Monday 09-29; 2026-09-29 is a Tuesday -> the nearest Monday is 09-28.
    assert estimate.start.date() == date(2026, 9, 28) and estimate.start.weekday() == 0
    assert (estimate.end - estimate.start) == timedelta(days=7)
    assert estimate.basis["reference_year"] == 2025  # not dragged back to the old November slot
    assert estimate.status == "estimated"


def test_estimate_for_2027_winter_from_announced_2026():
    events = cal.load_calendar(ROOT / "data" / "steam_sales.toml", now=NOW)
    estimate = cal.estimate_sale(events, "winter", 2027)
    assert estimate.start.date() == date(2027, 12, 16) and estimate.start.weekday() == 3   # Thursday
    assert (estimate.end - estimate.start).days == 18


def test_no_reference_year_gives_no_estimate():
    assert cal.estimate_sale([], "spring", 2027) is None


@pytest.fixture
def writer(db_path):
    w = StoreWriter.open(db_path)
    yield w
    w.close()


def test_estimates_are_stored_and_superseded_by_announcements(writer, tmp_path):
    events = cal.load_calendar(ROOT / "data" / "steam_sales.toml", now=NOW)
    created = cal.refresh_estimates(writer, events, now=NOW, horizon_months=24)
    names = {cal.label(e) for e in created}
    assert {"2027 秋特", "2027 冬特"} <= names
    assert not {"2027 春特", "2027 夏特"} & names          # already announced
    assert cal.refresh_estimates(writer, events, now=NOW, horizon_months=24) == []   # idempotent

    announced = cal.SaleEvent("Steam Autumn Sale", "秋季特賣", "seasonal", "autumn", 2027,
                              datetime(2027, 9, 30, 17, tzinfo=UTC), datetime(2027, 10, 7, 17, tzinfo=UTC),
                              "announced", "https://x")
    cal.refresh_estimates(writer, events + [announced], now=NOW, horizon_months=24)
    row = writer.conn.execute(
        "SELECT superseded_at, est_start FROM sale_estimates WHERE season='autumn' AND year=2027").fetchone()
    assert row[0] is not None and row[1].startswith("2027-09-30")   # kept for later comparison
    current = cal.current_estimates(writer)
    assert ("autumn", 2027) not in {(e.season, e.year) for e in current}


def test_alert_when_a_season_has_neither_announcement_nor_estimate():
    only_summer = [cal.SaleEvent("Steam Summer Sale", "夏季特賣", "seasonal", "summer", 2026,
                                 datetime(2026, 6, 25, 17, tzinfo=UTC), datetime(2026, 7, 9, 17, tzinfo=UTC),
                                 "ended", "https://x")]
    alerts = cal.coverage_alerts(only_summer, [], now=NOW)
    assert any("春季特賣" in a for a in alerts) and any("冬季特賣" in a for a in alerts)
    events = cal.load_calendar(ROOT / "data" / "steam_sales.toml", now=NOW)
    estimates = [cal.estimate_sale(events, s, y) for s, y in (("autumn", 2027), ("winter", 2027))]
    assert cal.coverage_alerts(events, estimates, now=NOW) == []


def test_missed_sale_detection(writer, tmp_path):
    events = load(tmp_path, sale())
    run = writer.start_run("daily")
    obs = []
    for app in range(1, 31):
        for day, cut in ((date(2025, 5, 1), 0), (date(2025, 8, 14), 50), (date(2025, 8, 20), 0),
                         (date(2025, 6, 27), 40), (date(2025, 7, 10), 0)):
            if day == date(2025, 8, 14) and app > 25:
                continue
            obs.append(NewObservation(app_id=app, source="itad-history", region="TW", currency="TWD",
                                      regular_cents=1000, price_cents=1000 * (100 - cut) // 100, cut_pct=cut,
                                      observed_at=datetime(day.year, day.month, day.day, 18, tzinfo=UTC),
                                      raw_observed_at=None, retrieved_at=NOW))
    writer.add_observations(run, obs)
    suspects = cal.detect_missed_sales(writer, events, since=datetime(2025, 1, 1, tzinfo=UTC), now=NOW)
    assert [s.day for s in suspects] == [date(2025, 8, 14)]   # 25 apps outside any sale; 06-27 is the summer sale
    assert suspects[0].apps == 25 and suspects[0].publishers == 25   # no publisher facts: one group per app


def test_single_publisher_sale_is_not_a_missed_store_sale(writer, tmp_path):
    events = load(tmp_path, sale())
    run = writer.start_run("daily")
    obs = []
    for app in range(1, 101):   # 100 games, all from one publisher, discounted together on 2025-08-14
        writer.add_facts(run, app, {"publishers": ["Big Publisher"]}, source="steam-appdetails", retrieved_at=NOW)
        for day, cut in ((date(2025, 5, 1), 0), (date(2025, 8, 14), 50)):
            obs.append(NewObservation(app_id=app, source="itad-history", region="TW", currency="TWD",
                                      regular_cents=1000, price_cents=1000 * (100 - cut) // 100, cut_pct=cut,
                                      observed_at=datetime(day.year, day.month, day.day, 18, tzinfo=UTC),
                                      raw_observed_at=None, retrieved_at=NOW))
    writer.add_observations(run, obs)
    assert cal.detect_missed_sales(writer, events, since=datetime(2025, 1, 1, tzinfo=UTC), now=NOW) == []


def test_threshold_ignores_sales_before_the_data_starts(writer, tmp_path):
    """Regression: seasonal sales from years without observations (0 publishers) pulled the typical size,
    and so the threshold, down to the floor, flagging ordinary days as missed sales."""
    old = [sale(year=y, start=f"{y}-06-25", end=f"{y}-07-09") for y in (2019, 2020, 2021, 2022)]
    events = load(tmp_path, *old, sale())
    run = writer.start_run("daily")
    obs = []
    for app in range(1, 201):   # 200 publishers join the 2025 summer sale; 30 start a discount on 08-14
        writer.add_facts(run, app, {"publishers": [f"Pub {app}"]}, source="steam-appdetails", retrieved_at=NOW)
        days = [(date(2025, 5, 1), 0), (date(2025, 6, 26), 40), (date(2025, 7, 10), 0)]
        if app <= 30:
            days += [(date(2025, 8, 14), 50), (date(2025, 8, 20), 0)]
        obs += [NewObservation(app_id=app, source="itad-history", region="TW", currency="TWD", regular_cents=1000,
                               price_cents=1000 * (100 - cut) // 100, cut_pct=cut,
                               observed_at=datetime(d.year, d.month, d.day, 18, tzinfo=UTC), raw_observed_at=None,
                               retrieved_at=NOW) for d, cut in days]
    writer.add_observations(run, obs)
    # typical real sale = 200 publishers -> threshold 60; the 30-publisher day is not a store-wide sale
    assert cal.detect_missed_sales(writer, events, since=datetime(2019, 1, 1, tzinfo=UTC), now=NOW) == []


def test_real_calendar_covers_2012_to_2018_seasonal_sales():
    """FR-033 (feature 002): the US backtest needs every seasonal sale since 2012, each with a source."""
    from pathlib import Path

    events = cal.load_calendar(Path(__file__).parents[2] / "data" / "steam_sales.toml", now=NOW)
    seasonal = [e for e in events if e.kind == "seasonal"]
    have = {(e.year, e.season) for e in seasonal}
    for year in range(2012, 2019):
        for season in ("summer", "autumn", "winter"):
            assert (year, season) in have, (year, season)
    assert not [e for e in seasonal if e.season == "spring" and e.year < 2023]
    for e in seasonal:
        assert e.source.startswith("https://") and "steamdb" not in e.source.lower()


def test_missed_sale_detection_ignores_edition_histories(writer, tmp_path):
    """Feature 009: edition rows (itad-option-history) are another product's prices, not store-wide sale evidence."""
    events = load(tmp_path, sale())
    run = writer.start_run("daily")
    obs = []
    for app in range(1, 31):     # 30 apps: only their editions start a discount on 2025-08-14
        for day, cut, source in ((date(2025, 5, 1), 0, "itad-history"), (date(2025, 5, 1), 0, "itad-option-history"),
                                 (date(2025, 8, 14), 50, "itad-option-history")):
            obs.append(NewObservation(app_id=app, source=source, region="TW", currency="TWD", regular_cents=1000,
                                      price_cents=1000 * (100 - cut) // 100, cut_pct=cut,
                                      observed_at=datetime(day.year, day.month, day.day, 18, tzinfo=UTC),
                                      raw_observed_at=None, retrieved_at=NOW, external_id=f"ed-{app}"))
    writer.add_observations(run, obs)
    assert cal.detect_missed_sales(writer, events, since=datetime(2025, 1, 1, tzinfo=UTC), now=NOW) == []
