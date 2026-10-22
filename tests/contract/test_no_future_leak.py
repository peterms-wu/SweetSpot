"""SC-001 / FR-011: tampering with everything after as_of never changes a forecast (tasks T026).

The test proves it can catch a leak: a model that reads the database itself is detected.
"""

import sqlite3

import pytest

from sweetspot.forecast.contract import LEVELS, batch_to_dict
from sweetspot.forecast.engine import load_games, run_forecast
from sweetspot.forecast.evidence import game_evidence
from sweetspot.forecast.models import build_model
from sweetspot.forecast.models.base import ModelOutput
from sweetspot.forecast.models import seasonal_record
from sweetspot.forecast.models.seasonal_record import SeasonalRecord, SeasonalRecordV110, build_hazard_table
from sweetspot.forecast.salepoints import future_sale_points
from sweetspot.store.query import PriceStore
from sweetspot.timeutil import to_db
from tests.forecast_builders import BASIC_CALENDAR, GameSpec, Sale, build_db, dt

AS_OF = dt("2025-08-01")
BEFORE = {
    1: [("2024-12-11", 0), ("2024-12-19T18:00", 50), ("2025-01-02T18:00", 0), ("2025-06-26T17:00", 60),
        ("2025-07-10T17:00", 0)],
    2: [("2024-12-11", 10), ("2025-03-13T17:00", 30), ("2025-03-20T17:00", 10)],
    3: [("2025-07-01", 20), ("2025-07-12", 0)],
}
AFTER = {1: [("2025-09-29T17:00", 70), ("2025-10-06T17:00", 0)], 2: [("2025-12-18T18:00", 50)], 3: []}
US = [("2020-01-01", 0), ("2024-06-27T17:00", 40), ("2024-07-11T17:00", 0)]
# feature 008: new games (first record ≤ 365 days after release), so seasonal-record 1.1.0 builds sequences
RELEASE = {1: "2024-06-01", 2: "2024-10-01", 3: "2025-06-15"}


def build(path, tamper: bool):
    games = []
    for app, rows in BEFORE.items():
        after = [(w, 99) for w, _ in AFTER[app]] + [("2026-02-01", 95)] if tamper else AFTER[app]
        games.append(GameSpec(app, tw=rows + after, us=US + ([("2025-11-01", 90)] if tamper else []),
                              release_date=RELEASE[app],
                              # both fetched after as_of (at different times): what is known *up to* as_of is
                              # identical, only later knowledge differs
                              known_until={"TW": "2026-09-01" if tamper else "2026-09-24",
                                           "US": "2026-08-01" if tamper else "2026-09-24"}))
    calendar = [s for s in BASIC_CALENDAR if not tamper or dt(s.start) <= AS_OF]
    if tamper:
        calendar.append(Sale("autumn", 2025, "2025-08-15T17:00", "2025-08-20T17:00"))   # a "surprise" date
    return build_db(path, games, calendar=calendar)


class Cheater:
    """Breaks the model contract by reading the database: the leak test must notice."""

    name, version, params, tw_only_params = "cheater", "0", {}, frozenset()

    def __init__(self, db):
        self.db = db

    def confidence_levels(self):
        return {"normal": "n", "low": "l"}

    def prepare(self, population):
        pass

    def predict(self, game, points, levels):
        with sqlite3.connect(self.db) as conn:
            (future,) = conn.execute("SELECT MAX(cut_pct) FROM price_observations WHERE app_id = ?",
                                     (game.app_id,)).fetchone()
        p = (future or 0) / 100
        return ModelOutput(tuple(tuple(p for _ in levels) for _ in points), "normal", ("偷看",), {})


def forecasts(path, model):
    store = PriceStore.open(path)
    try:
        data = batch_to_dict(run_forecast(store, [1, 2, 3], AS_OF, model, now=dt("2026-09-25")))
    finally:
        store.close()
    data.pop("generated_at")
    return data


MODELS = [("seasonal-freq", {"history": "TW"}), ("seasonal-freq", {"history": "TW+US"}),
          ("seasonal-freq", {"min_sales": 3}),
          ("seasonal-record", {"min_sales": 1, "half_life": 2, "hazard_history": "TW+US"}),
          ("seasonal-record", {"min_sales": 2, "half_life": 0, "hazard_history": "TW"}),
          ("seasonal-record@1.1.0", {"low_base": "new-split", "shrink": 0.5}),
          ("seasonal-record@1.1.0", {"low_base": "new", "shrink": 1})]


@pytest.fixture(autouse=True)
def tiny_sequences(monkeypatch):
    """Three games cannot reach 30 new-game sequences: let one be enough so 1.1.0's new-game base is exercised."""
    monkeypatch.setattr(seasonal_record, "MIN_SEQUENCES", 1)


@pytest.mark.parametrize("name, params", MODELS)
def test_tampering_after_as_of_changes_nothing(tmp_path, name, params):
    a, b = build(tmp_path / "a" / "sweetspot.db", False), build(tmp_path / "b" / "sweetspot.db", True)
    assert forecasts(a, build_model(name, params)) == forecasts(b, build_model(name, params))


class RecordPeeker(SeasonalRecord):
    """Builds its record table with discounts seen after as_of (read from the database): the leak test must notice
    a peeking feature, not only a peeking forecast (004 FR-007)."""

    def __init__(self, db):
        super().__init__(min_sales=1, half_life=0, hazard_history="TW")
        self.db = db

    def prepare(self, population):
        super().prepare(population)
        with sqlite3.connect(self.db) as conn:
            later = [c for (c,) in conn.execute("SELECT cut_pct FROM price_observations WHERE observed_at > ? "
                                                "AND cut_pct IS NOT NULL", (to_db(population.as_of),))]
        seen = [("TW", [0, c]) for c in later] + list(self._sequences(population))
        self.table = build_hazard_table(seen, self.min_sales)


class NewGamePeeker(SeasonalRecordV110):
    """Adds discounts seen after as_of to the new-game sequences (a peeking feature of 1.1.0): must be noticed."""

    def __init__(self, db):
        super().__init__(low_base="new", shrink=0.5)
        self.db = db

    def prepare(self, population):
        super().prepare(population)
        with sqlite3.connect(self.db) as conn:
            later = [c for (c,) in conn.execute("SELECT cut_pct FROM price_observations WHERE observed_at > ? "
                                                "AND cut_pct IS NOT NULL", (to_db(population.as_of),))]
        self._new_sequences["all-new"] += [[c] for c in later]


def test_the_check_catches_new_game_sequences_that_peek(tmp_path):
    a, b = build(tmp_path / "a" / "sweetspot.db", False), build(tmp_path / "b" / "sweetspot.db", True)
    assert forecasts(a, NewGamePeeker(a)) != forecasts(b, NewGamePeeker(b))


def test_the_new_game_base_is_exercised(tmp_path):
    """Guard: game 3 has no own record at as_of, so the 1.1.0 forecast really comes from the new-game table."""
    a = build(tmp_path / "a" / "sweetspot.db", False)
    data = forecasts(a, build_model("seasonal-record@1.1.0", {"low_base": "new-split", "shrink": 0.5}))
    game3 = next(g for g in data["games"] if g["app_id"] == 3)
    assert game3["confidence"] == "low" and game3["evidence"]["low_sequences"] == "released"


def test_the_check_catches_a_model_that_peeks(tmp_path):
    a, b = build(tmp_path / "a" / "sweetspot.db", False), build(tmp_path / "b" / "sweetspot.db", True)
    assert forecasts(a, Cheater(a)) != forecasts(b, Cheater(b))


def test_the_check_catches_a_record_table_that_peeks(tmp_path):
    a, b = build(tmp_path / "a" / "sweetspot.db", False), build(tmp_path / "b" / "sweetspot.db", True)
    assert forecasts(a, RecordPeeker(a)) != forecasts(b, RecordPeeker(b))


def test_backtest_truncation_equals_loading_at_as_of(tmp_path):
    """The runner loads everything to the cutoff once and truncates in memory (research R7)."""
    path = build(tmp_path / "a" / "sweetspot.db", False)
    store = PriceStore.open(path)
    try:
        full = load_games(store, [1, 2, 3], dt("2026-09-24"))
        at = load_games(store, [1, 2, 3], AS_OF)
        points = future_sale_points(store, AS_OF)
    finally:
        store.close()
    from sweetspot.forecast.evidence import population_view

    for model in (build_model("seasonal-freq", {"history": "TW+US"}), build_model("seasonal-record", {})):
        model.prepare(population_view(full.values(), AS_OF, "TW"))
        for app in (1, 2, 3):
            truncated, loaded = game_evidence(full[app], AS_OF, "TW"), game_evidence(at[app], AS_OF, "TW")
            assert truncated == loaded
            assert model.predict(truncated, points, LEVELS) == model.predict(loaded, points, LEVELS)
    assert population_view(full.values(), AS_OF, "TW") == population_view(at.values(), AS_OF, "TW")


# --- feature 012: official sales adopted from the seasonal sales page (research R7; FR-018) -----------------------

def _official_store(tmp_path, name, *, sighting: bool):
    """A store with the real calendar file; with `sighting`, the database also holds an official 2027 autumn sale
    (not in the file) first seen now."""
    import shutil
    from datetime import date, time
    from pathlib import Path
    from zoneinfo import ZoneInfo

    from sweetspot import calendar_sync
    from sweetspot.sources import OfficialSale, SeasonalSalesPage
    from sweetspot.store.writer import StoreWriter
    from sweetspot.timeutil import now_utc

    path = tmp_path / name / "sweetspot.db"
    writer = StoreWriter.open(path)
    shutil.copy(Path(__file__).parents[2] / "data" / "steam_sales.toml", path.parent / "steam_sales.toml")
    if sighting:
        page = SeasonalSalesPage(url="https://partner.steamgames.com/doc/marketing/discounts/seasonalsales",
                                 fetched_at=now_utc(), http_status=200, bytes=1, sha256="0" * 64,
                                 found_dates_section=True,
                                 sales=[OfficialSale("autumn", 2027, date(2027, 9, 30), date(2027, 10, 7))])
        calendar_sync.record_fetch(writer, page, now=now_utc(), default_time=time(10),
                                   tz=ZoneInfo("America/Los_Angeles"))
    writer.close()
    return PriceStore.open(path)


PAST = [dt("2019-01-01") + (dt("2019-01-31") - dt("2019-01-01")) * i for i in range(95)]      # every 30 days


def _same_past_sales(with_official: PriceStore, without: PriceStore) -> None:
    for moment in PAST:
        assert with_official.sales(moment) == without.sales(moment), moment


def test_adopted_future_sale_is_invisible_in_the_past(tmp_path):
    from sweetspot.calendar import label

    with_official = _official_store(tmp_path, "a", sighting=True)
    without = _official_store(tmp_path, "b", sighting=False)
    try:
        assert PAST[-1] < dt("2026-09-27")
        assert "2027 秋特" in {label(e) for e in with_official.calendar_events()}      # the sale is really there
        _same_past_sales(with_official, without)
    finally:
        with_official.close()
        without.close()


def test_the_check_catches_a_store_that_shows_adopted_sales_early(tmp_path, monkeypatch):
    with_official = _official_store(tmp_path, "a", sighting=True)
    without = _official_store(tmp_path, "b", sighting=False)

    def leaky(self, as_of, include_estimates=True):
        return sorted(self._events(), key=lambda e: e.start)      # every sale, whenever it starts

    try:
        monkeypatch.setattr(PriceStore, "sales", leaky)
        with pytest.raises(AssertionError):
            _same_past_sales(with_official, without)
    finally:
        with_official.close()
        without.close()


def test_forecast_and_decision_never_read_the_official_page_records():
    from pathlib import Path

    root = Path(__file__).parents[2] / "src" / "sweetspot"
    for folder in ("forecast", "decision"):
        for path in (root / folder).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for name in ("calendar_fetches", "sale_sightings", "calendar_sync"):
                assert name not in text, f"{path.relative_to(root)} mentions {name}"
