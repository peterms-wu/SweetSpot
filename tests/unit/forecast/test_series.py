"""research R1 / R3: price-state series, sale outcomes and new-discount events (tasks T005)."""

from sweetspot.calendar import SaleEvent
from sweetspot.forecast.series import PriceSeries, build_series, sale_outcomes
from sweetspot.store.query import Observation
from tests.forecast_builders import dt

LEVELS = list(range(5, 100, 5))


def obs(when: str, cut, source: str = "itad-history", first: bool = False, regular: int = 50000,
        region: str = "TW") -> Observation:
    return Observation(app_id=1, region=region, source=source, observed_at=dt(when), retrieved_at=dt("2026-09-24"),
                       regular_cents=regular if region == "TW" else None, price_cents=None, cut_pct=cut,
                       is_tracking_start=first)


def seasonal(season: str, year: int, start: str, end: str) -> SaleEvent:
    return SaleEvent(name="x", name_zh="x", kind="seasonal", season=season, year=year, start=dt(start),
                     end=dt(end), status="ended", source="https://example.test")


def series(rows: list[tuple], known_until: str = "2026-09-24", region: str = "TW") -> PriceSeries:
    observations = [obs(w, c, first=(i == 0), region=region) for i, (w, c) in enumerate(rows)]
    return build_series(observations, region, dt(known_until))


def test_merge_sources_dedupes_same_time_preferring_itad_history():
    rows = [obs("2025-01-01", 0, "itad-history", True), obs("2025-01-01", 0, "legacy-itad", True),
            obs("2025-02-01", 50, "itad-history"), obs("2025-02-01", 40, "legacy-itad"),
            obs("2025-03-01", 0, "legacy-itad")]
    s = build_series(sorted(rows, key=lambda o: (o.observed_at, o.source)), "TW", dt("2026-01-01"))
    assert [(st.start, st.cut) for st in s.states] == [(dt("2025-01-01"), 0), (dt("2025-02-01"), 50),
                                                       (dt("2025-03-01"), 0)]


def test_steam_current_rows_are_ignored():
    rows = [obs("2025-01-01", 0, first=True), obs("2025-01-05", 90, "steam-current")]
    assert [st.cut for st in build_series(rows, "TW", dt("2026-01-01")).states] == [0]


def test_null_cut_produces_no_state():
    rows = [obs("2025-01-01", 0, first=True), obs("2025-02-01", None), obs("2025-03-01", 30)]
    assert [st.cut for st in build_series(rows, "TW", dt("2026-01-01")).states] == [0, 30]


def test_tracking_start_is_not_an_event():
    s = series([("2025-01-01", 50), ("2025-02-01", 0)])
    assert [st.cut for st in s.events_after(dt("2024-12-01"))] == [0]


def test_truncate_keeps_past_states_and_caps_known_until():
    s = series([("2025-01-01", 0), ("2025-02-01", 50), ("2025-03-01", 0)], known_until="2026-01-01")
    t = s.truncate(dt("2025-02-01"))
    assert [st.cut for st in t.states] == [0, 50]
    assert t.known_until == dt("2025-02-01")
    assert s.truncate(dt("2027-01-01")).known_until == dt("2026-01-01")


def test_events_after_excludes_the_state_in_effect_at_as_of():
    s = series([("2025-01-01", 0), ("2025-02-01", 50), ("2025-03-01", 0)])
    assert [st.cut for st in s.events_after(dt("2025-02-01"))] == [0]
    assert [st.cut for st in s.events_after(dt("2025-01-31"))] == [50, 0]


def test_first_crossings_need_a_move_from_below_to_at_or_above_the_level():
    s = series([("2025-01-01", 0), ("2025-02-01", 50), ("2025-03-01", 60), ("2025-04-01", 0),
                ("2025-05-01", 50), ("2025-05-10", 50)])
    firsts = s.first_crossings(dt("2025-02-15"), LEVELS)   # 50% already running at as_of
    assert firsts[50] == dt("2025-05-01")
    assert firsts[5] == dt("2025-05-01")
    assert firsts[55] == dt("2025-03-01") and firsts[60] == dt("2025-03-01")
    assert firsts[65] is None
    before = s.first_crossings(dt("2025-01-15"), LEVELS)
    assert before[50] == dt("2025-02-01") and before[60] == dt("2025-03-01")


def test_regular_price_change_with_same_cut_is_not_a_new_event():
    s = series([("2025-01-01", 0), ("2025-02-01", 50), ("2025-02-10", 50), ("2025-03-01", 0)])
    assert s.first_crossings(dt("2025-02-05"), LEVELS)[50] is None


def test_state_at():
    s = series([("2025-01-01", 0), ("2025-02-01", 50)])
    assert s.state_at(dt("2024-12-31")) is None
    assert s.state_at(dt("2025-02-01")).cut == 50
    assert s.state_at(dt("2025-01-15")).cut == 0


SUMMER = seasonal("summer", 2025, "2025-06-26T17:00", "2025-07-10T17:00")


def test_sale_max_includes_state_at_start_and_changes_inside():
    s = series([("2025-01-01", 20), ("2025-06-27", 50), ("2025-07-01", 30), ("2025-07-20", 0)])
    (out,) = sale_outcomes(s, [SUMMER])
    assert (out.season, out.year, out.label, out.region, out.max_cut) == ("summer", 2025, "2025 夏特", "TW", 50)


def test_sale_max_uses_state_in_effect_at_start():
    s = series([("2025-01-01", 0), ("2025-06-20", 40), ("2025-08-01", 0)])
    assert sale_outcomes(s, [SUMMER])[0].max_cut == 40


def test_sale_end_is_exclusive():
    s = series([("2025-01-01", 0), ("2025-07-10T17:00", 90)])
    assert sale_outcomes(s, [SUMMER])[0].max_cut == 0


def test_series_starting_inside_a_sale_skips_that_sale():
    s = series([("2025-06-30", 50), ("2025-08-01", 0)])
    assert sale_outcomes(s, [SUMMER]) == ()


def test_sale_after_known_until_is_skipped():
    s = series([("2025-01-01", 0)], known_until="2025-07-05")
    assert sale_outcomes(s, [SUMMER]) == ()


def test_no_discount_during_sale_is_zero_not_missing():
    s = series([("2025-01-01", 0)])
    assert sale_outcomes(s, [SUMMER])[0].max_cut == 0


def test_free_promotion_counts_as_100():
    s = series([("2025-01-01", 0), ("2025-06-27", 100), ("2025-06-29", 0)])
    assert sale_outcomes(s, [SUMMER])[0].max_cut == 100


def test_outcomes_are_sorted_by_sale_start_and_skip_themed():
    themed = SaleEvent(name="t", name_zh="t", kind="themed", season=None, year=2025, start=dt("2025-02-01"),
                       end=dt("2025-02-05"), status="ended", source="https://example.test")
    spring = seasonal("spring", 2025, "2025-03-13T17:00", "2025-03-20T17:00")
    s = series([("2025-01-01", 0)])
    assert [o.season for o in sale_outcomes(s, [SUMMER, themed, spring])] == ["spring", "summer"]


def test_empty_series():
    s = build_series([], "TW", None)
    assert s.states == () and s.state_at(dt("2025-01-01")) is None
    assert sale_outcomes(s, [SUMMER]) == ()
