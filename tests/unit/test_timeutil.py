from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from sweetspot import timeutil


def test_parse_iso_offset_converts_to_utc():
    dt = timeutil.parse_iso("2026-07-09T19:20:55+02:00")
    assert dt == datetime(2026, 7, 9, 17, 20, 55, tzinfo=UTC)


def test_parse_iso_accepts_z_suffix():
    assert timeutil.parse_iso("2024-12-11T14:06:00Z") == datetime(2024, 12, 11, 14, 6, tzinfo=UTC)


def test_parse_iso_rejects_naive():
    with pytest.raises(ValueError):
        timeutil.parse_iso("2024-12-11T14:06:00")


def test_to_db_is_fixed_width_and_sortable():
    a = timeutil.to_db(datetime(2025, 1, 1, tzinfo=UTC))
    b = timeutil.to_db(datetime(2025, 1, 1, 0, 0, 0, 5, tzinfo=UTC))
    c = timeutil.to_db(datetime(2025, 1, 1, 1, tzinfo=timezone(timedelta(hours=2))))
    assert a == "2025-01-01T00:00:00.000000Z"
    assert len(a) == len(b) == len(c)
    assert sorted([b, a, c]) == [c, a, b]  # c is 2024-12-31T23:00Z
    assert timeutil.from_db(b) == datetime(2025, 1, 1, 0, 0, 0, 5, tzinfo=UTC)


def test_to_db_rejects_naive():
    with pytest.raises(ValueError):
        timeutil.to_db(datetime(2025, 1, 1))


def test_itad_since_has_no_fractional_seconds():
    dt = datetime(2010, 1, 1, 0, 0, 0, 123456, tzinfo=UTC)
    assert timeutil.itad_since(dt) == "2010-01-01T00:00:00Z"
    local = datetime(2025, 1, 1, 8, 0, tzinfo=timezone(timedelta(hours=8)))
    assert timeutil.itad_since(local) == "2025-01-01T00:00:00Z"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("19 Apr, 2011", date(2011, 4, 19)),
        ("Apr 19, 2011", date(2011, 4, 19)),
        ("2011-04-19", date(2011, 4, 19)),
        ("2011 年 4 月 19 日", date(2011, 4, 19)),
        ("2011年4月19日", date(2011, 4, 19)),
        ("Coming soon", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_steam_date(text, expected):
    assert timeutil.parse_steam_date(text) == expected


def test_add_months_clamps_to_month_end():
    assert timeutil.add_months(datetime(2026, 1, 31, tzinfo=UTC), 1) == datetime(2026, 2, 28, tzinfo=UTC)
    assert timeutil.add_months(datetime(2024, 1, 31, tzinfo=UTC), 1) == datetime(2024, 2, 29, tzinfo=UTC)
    assert timeutil.add_months(datetime(2026, 9, 25, 3, tzinfo=UTC), 24) == datetime(2028, 9, 25, 3, tzinfo=UTC)


def test_elapsed_clock_adds_the_monotonic_time_since_it_was_made(monkeypatch):
    from datetime import UTC, datetime, timedelta

    from sweetspot import timeutil

    ticks = iter([100.0, 100.0, 162.5])
    monkeypatch.setattr(timeutil.time, "monotonic", lambda: next(ticks))
    start = datetime(2026, 10, 1, 18, 30, 3, tzinfo=UTC)
    clock = timeutil.elapsed_clock(start)
    assert clock() == start
    assert clock() == start + timedelta(seconds=62.5)
