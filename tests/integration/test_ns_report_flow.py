"""Decisions and the report with non-seasonal forecasts on a synthetic store (feature 007; tasks T026)."""

import gzip
import json
from dataclasses import replace

import pytest

from sweetspot.config import Preferences
from sweetspot.decision import engine as decision_engine
from sweetspot.decision.contract import batch_to_dict
from sweetspot.decision.engine import run_decisions
from sweetspot.forecast.models import build_model
from sweetspot.report.html import render
from sweetspot.store.query import PriceStore
from tests.forecast_builders import BASIC_CALENDAR, GameSpec, build_db, dt

AS_OF = dt("2026-02-01")


def rows(regular=50000):
    """Seasonal sales plus a non-seasonal -50% promotion every ~50 days."""
    out = [("2024-12-11", 0)]
    for s in BASIC_CALENDAR:
        if dt(s.start) > dt("2024-12-11") and dt(s.start) < AS_OF:
            out += [(s.start, 60), (s.end, 0)]
    for start in ("2025-02-05", "2025-04-10", "2025-05-30", "2025-08-01", "2025-09-10", "2025-11-10", "2026-01-15"):
        out += [(start, 50), ((dt(start).replace(day=min(dt(start).day + 6, 28))).isoformat(), 0)]
    return sorted(out, key=lambda r: dt(r[0]))


@pytest.fixture
def store(db_path):
    games = [GameSpec(1, tw=rows(), name="Promo", wishlist=True, known_until={"TW": "2026-01-31"}),
             GameSpec(2, tw=[("2025-12-01", 0), ("2025-12-05", 40), ("2025-12-10", 0)], name="New", wishlist=True,
                      known_until={"TW": "2026-01-31"}),
             GameSpec(3, name="Nothing", wishlist=True)]
    build_db(db_path, games, calendar=BASIC_CALENDAR)
    s = PriceStore.open(db_path)
    yield s
    s.close()


def decide(store):
    return run_decisions(store, store.wishlist_apps(), AS_OF, build_model("seasonal-record", {}), Preferences(),
                         now=dt("2026-02-01"))


def test_decisions_are_unchanged_by_the_non_seasonal_part(store, monkeypatch):
    with_ns = decide(store)
    monkeypatch.setattr(decision_engine, "_with_non_seasonal", lambda decisions, *a, **k: (decisions, None))
    without = decide(store)
    for a, b in zip(with_ns.decisions, without.decisions):
        assert replace(a, non_seasonal=None, tags=tuple(t for t in a.tags if t != "earlier-possible")) == b


def test_report_and_record_carry_the_section(store, tmp_path):
    batch = decide(store)
    data = batch_to_dict(batch)
    assert data["non_seasonal"]["adopted"] is True
    by_app = {d["app_id"]: d for d in data["decisions"]}
    assert by_app[1]["non_seasonal"]["status"] == "ok"
    assert by_app[1]["non_seasonal"]["basis"]["promos_365d"] >= 5
    assert by_app[2]["non_seasonal"]["confidence"] == "low"
    assert by_app[3]["non_seasonal"]["status"] == "na"
    html = render(data)
    assert "季節特賣以外" in html and "非季節 non-seasonal 1.0.0" in html
    path = tmp_path / "r.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        assert json.load(fh)["decisions"][0]["non_seasonal"] == data["decisions"][0]["non_seasonal"]


def test_non_seasonal_population_ignores_the_chosen_edition(db_path):
    """Feature 009 (FR-012): the chosen edition feeds only its own game's non-seasonal forecast."""
    from sweetspot.forecast.engine import all_apps, load_games
    from sweetspot.forecast.nonseasonal import build_ns_model
    from sweetspot.forecast.nonseasonal.engine import ns_forecast
    from sweetspot.store.query import OPTION_HISTORY_SOURCE, HistoryKey
    from tests.forecast_builders import add_history

    deep = [(t, 90 if c else 0, 90000) for t, c in rows()]
    games = [GameSpec(1, tw=rows(), name="Promo", wishlist=True, known_until={"TW": "2026-01-31"})]
    games += [GameSpec(a, tw=rows(), name=f"Other {a}", wishlist=True, known_until={"TW": "2026-01-31"})
              for a in range(2, 6)]
    build_db(db_path, games, calendar=BASIC_CALENDAR)
    add_history(db_path, 1, "itad-edition", tw=deep, regular_cents=90000, fetched="2026-01-31",
                source=OPTION_HISTORY_SOURCE, fetch_source="itad-option")
    store = PriceStore.open(db_path)
    loaded = load_games(store, all_apps(store), AS_OF, regions=("TW", "US"))
    targets = load_games(store, [1], AS_OF, regions=("TW", "US"), keys={1: HistoryKey("itad-edition", "user")},
                         sources=(OPTION_HISTORY_SOURCE,))
    base = ns_forecast(store, [1, 2], AS_OF, build_ns_model("non-seasonal"), games=loaded).outputs
    chosen = ns_forecast(store, [1, 2], AS_OF, build_ns_model("non-seasonal"), games=loaded, targets=targets).outputs
    assert chosen[2] == base[2]
    assert chosen[1] != base[1]
    store.close()
