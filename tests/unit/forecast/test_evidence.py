"""research R3: what a model may see at as_of (tasks T011)."""

from sweetspot.calendar import SaleEvent
from sweetspot.forecast.evidence import GameData, game_evidence, population_view, visible_regions
from sweetspot.forecast.series import build_series, sale_outcomes
from sweetspot.store.query import Observation
from tests.forecast_builders import dt

SALES = [SaleEvent(name="x", name_zh="x", kind="seasonal", season=s, year=y, start=dt(a), end=dt(b),
                   status="ended", source="https://example.test")
         for s, y, a, b in [("winter", 2024, "2024-12-19T18:00", "2025-01-02T18:00"),
                            ("spring", 2025, "2025-03-13T17:00", "2025-03-20T17:00"),
                            ("summer", 2025, "2025-06-26T17:00", "2025-07-10T17:00")]]


def rows(region: str, spec: list[tuple]) -> list[Observation]:
    return [Observation(app_id=1, region=region, source="itad-history", observed_at=dt(w), retrieved_at=dt("2026-09-24"),
                        regular_cents=50000 if region == "TW" else None, price_cents=None, cut_pct=c,
                        is_tracking_start=(i == 0)) for i, (w, c) in enumerate(spec)]


def game(app_id: int = 1) -> GameData:
    series = {
        "TW": build_series(rows("TW", [("2024-12-11", 0), ("2024-12-20", 40), ("2025-01-05", 0),
                                       ("2025-03-14", 50), ("2025-03-21", 0), ("2025-06-27", 60)]),
                           "TW", dt("2026-09-24")),
        "US": build_series(rows("US", [("2020-01-01", 0), ("2025-03-14", 50)]), "US", dt("2026-09-24")),
    }
    return GameData(app_id=app_id, series=series,
                    outcomes={r: sale_outcomes(s, SALES) for r, s in series.items()})


def test_visible_regions():
    assert visible_regions("TW") == ("TW", "US")
    assert visible_regions("US") == ("US",)


def test_sale_history_contains_only_ended_sales():
    ev = game_evidence(game(), dt("2025-06-30"), "TW")        # summer 2025 is still running
    assert [(o.season, o.max_cut) for o in ev.sale_history["TW"]] == [("winter", 40), ("spring", 50)]


def test_series_are_truncated_and_known_until_capped():
    as_of = dt("2025-03-15")
    ev = game_evidence(game(), as_of, "TW")
    for s in ev.series.values():
        assert all(st.start <= as_of for st in s.states)
        assert s.known_until <= as_of


def test_us_target_sees_only_us():
    ev = game_evidence(game(), dt("2025-12-01"), "US")
    assert set(ev.series) == {"US"} and set(ev.sale_history) == {"US"}
    pop = population_view([game(1), game(2)], dt("2025-12-01"), "US")
    assert all(set(h) == {"US"} for h in pop.sale_history.values())


def test_tw_target_sees_both_regions():
    ev = game_evidence(game(), dt("2025-12-01"), "TW")
    assert set(ev.series) == {"TW", "US"}


def test_population_is_truncated():
    pop = population_view([game(1), game(2)], dt("2025-04-01"), "TW")
    assert pop.as_of == dt("2025-04-01") and set(pop.sale_history) == {1, 2}
    for history in pop.sale_history.values():
        assert all(o.end <= dt("2025-04-01") for outs in history.values() for o in outs)


def test_facts_are_loaded_lazily():
    calls = []
    ev = game_evidence(game(), dt("2025-06-01"), "TW", facts_loader=lambda: calls.append(1) or "facts")
    assert calls == []
    assert ev.facts == "facts" and calls == [1]
