"""Release dates as a model input (feature 008 research R3; data-model; tasks T007)."""

from dataclasses import replace
from datetime import date

from sweetspot.forecast.engine import load_games
from sweetspot.forecast.evidence import game_evidence, population_view
from sweetspot.store.query import PriceStore
from tests.forecast_builders import GameSpec, Sale, build_db, dt
from tests.unit.forecast.test_evidence import game


def test_game_evidence_carries_the_release_date():
    g = replace(game(1), release_date=date(2024, 11, 1))
    assert game_evidence(g, dt("2025-06-30"), "TW").release_date == date(2024, 11, 1)
    assert game_evidence(game(2), dt("2025-06-30"), "TW").release_date is None      # unknown stays unknown


def test_population_view_covers_every_game_given():
    with_history = replace(game(1), release_date=date(2024, 11, 1))
    no_history = replace(game(2), outcomes={}, release_date=date(2025, 5, 1))
    unknown = game(3)
    view = population_view([with_history, no_history, unknown], dt("2025-06-30"), "TW")
    assert view.release_dates == {1: date(2024, 11, 1), 2: date(2025, 5, 1), 3: None}
    assert set(view.sale_history) == {1, 3}                          # unchanged: games without records are left out


def test_existing_fields_do_not_change():
    ev = game_evidence(game(), dt("2025-06-30"), "TW")
    assert [(o.season, o.max_cut) for o in ev.sale_history["TW"]] == [("winter", 40), ("spring", 50)]


def test_load_games_reads_release_dates_once(tmp_path, monkeypatch):
    db = build_db(tmp_path / "t.db", [GameSpec(1, tw=[("2025-01-01", 0)], release_date="2024-12-01"),
                                       GameSpec(2, tw=[("2025-01-01", 0)], release_date=None)],
                  calendar=[Sale("summer", 2025, "2025-06-26T17:00", "2025-07-10T17:00")])
    store = PriceStore.open(db)
    calls = []
    original = store.release_dates
    monkeypatch.setattr(store, "release_dates", lambda apps: calls.append(list(apps)) or original(apps))
    try:
        games = load_games(store, [1, 2], dt("2026-01-01"))
    finally:
        store.close()
    assert len(calls) == 1
    assert games[1].release_date == date(2024, 12, 1) and games[2].release_date is None
