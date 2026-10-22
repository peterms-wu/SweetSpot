"""Non-seasonal backtest: units, scoring, reference, earlier-arrival counts, identity (feature 007 R2; tasks T012)."""

from datetime import timedelta

import pytest

from sweetspot.calendar import SaleEvent
from sweetspot.forecast.backtest.dataset import BacktestDataset, RegionDataset
from sweetspot.forecast.nonseasonal import backtest as nsb
from sweetspot.forecast.nonseasonal.backtest import ns_dataset_id, run_ns_backtest
from sweetspot.forecast.nonseasonal.evidence import NSFrame, basis
from sweetspot.forecast.nonseasonal.model import NSOutput
from tests.forecast_builders import dt
from tests.ns_builders import game

DAY = timedelta(days=1)
LEVELS = tuple(range(5, 100, 5))
AS_OF = dt("2025-09-01")


def sale(season, year, start, end):
    return SaleEvent(f"{season}", "特賣", "seasonal", season, year, dt(start), dt(end), "ended", "https://x.test")


EVENTS = [sale("winter", 2024, "2024-12-19T18:00", "2025-01-02T18:00"),
          sale("spring", 2025, "2025-03-13T17:00", "2025-03-20T17:00"),
          sale("summer", 2025, "2025-06-26T17:00", "2025-07-10T17:00"),
          sale("autumn", 2025, "2025-09-29T17:00", "2025-10-06T17:00"),
          sale("winter", 2025, "2025-12-18T18:00", "2026-01-05T18:00")]


class Const:
    """A stand-in model: the same probability everywhere."""

    name, version = "const", "0"

    def __init__(self, p, confidence="normal"):
        self.p, self.confidence = p, confidence
        self.params = {"history": "TW", "clock": False}

    def confidence_levels(self):
        return {"normal": "n", "low": "l"}

    def prepare(self, population):
        self.population = population

    def predict(self, ev):
        return NSOutput(((self.p,) * 19,) * 3, self.confidence, ("own",) * 3, basis(ev))


def games():
    # app 1: a -50% promotion 10 days after as_of, history known well past as_of + 90 days
    # app 2: a -30% promotion 20 days after as_of, but history known only to as_of + 45 days
    return {1: game(1, [("2024-12-01", 0), ("2025-02-01", 50), ("2025-02-08", 0), ("2025-09-11", 50),
                        ("2025-09-18", 0)], tw_until="2026-06-01"),
            2: game(2, [("2024-12-01", 0), ("2025-09-21", 30), ("2025-09-25", 0)], tw_until="2025-10-16")}


def dataset(gs, split="all", schedule=(AS_OF,)):
    rd = RegionDataset("TW", tuple(sorted(gs)), tuple(schedule), (0, 12), "d" * 64, tuple(sorted(gs)))
    return BacktestDataset(dt("2026-06-01"), LEVELS, "c", {a: "broad" for a in gs}, {"TW": rd}, split)


def test_units_scoring_and_the_reference():
    gs = games()
    result, _ = run_ns_backtest(dataset(gs), gs, EVENTS, Const(0.3), earlier=False)
    assert result["schema"] == "steamsage.ns-backtest/1"
    # app 1: all three horizons; app 2: only 30 days (known to as_of + 45)
    assert result["units"]["scored"] == {"30": 38, "60": 19, "90": 19}
    assert result["units"]["not_scored"] == {"30": 0, "60": 19, "90": 19}
    # app 1 reached 5..50 in every horizon; app 2 reached 5..30 within 30 days
    sse1 = sum((0.3 - (d <= 50)) ** 2 for d in LEVELS) * 3 / 57
    sse2 = sum((0.3 - (d <= 30)) ** 2 for d in LEVELS) / 19
    assert result["brier"] == pytest.approx((sse1 + sse2) / 2)
    frame = NSFrame(gs, EVENTS, "TW", population=list(gs), clock=False)
    share = frame.population_at(AS_OF, list(gs)).share
    ref1 = sum((share[(h, d)] - (d <= 50)) ** 2 for h in (30, 60, 90) for d in LEVELS) / 57
    ref2 = sum((share[(30, d)] - (d <= 30)) ** 2 for d in LEVELS) / 19
    assert result["reference_brier"] == pytest.approx((ref1 + ref2) / 2)
    assert result["per_game"]["2"][0] == 19
    assert result["by_horizon"]["60"]["units"] == 19
    bins = {b["bin"]: b for b in result["calibration"]}
    assert set(bins) == {"0.3"} and bins["0.3"]["n"] == 76
    assert bins["0.3"]["actual"] == pytest.approx((10 * 3 + 6) / 76)
    assert result["point_hit_rate"]["n"] == 0
    assert result["earlier"] is None


def test_an_occurred_unit_beyond_known_until_is_not_scored():
    gs = games()
    result, _ = run_ns_backtest(dataset(gs), gs, EVENTS, Const(0.6), earlier=False)
    assert result["per_game"]["2"][0] == 19                 # app 2's -30% on day 20 counts for 30 days only
    assert result["point_hit_rate"]["n"] == 76
    assert result["point_hit_rate"]["hits"] == 10 * 3 + 6


def test_by_confidence_and_by_count():
    gs = games()
    result, _ = run_ns_backtest(dataset(gs), gs, EVENTS, Const(0.3, "low"), earlier=False)
    assert set(result["by_confidence"]) == {"low"}
    assert set(result["by_count"]) == {"1-2", "0"}          # app 1 had one promotion in the past year, app 2 none


def test_earlier_arrival_counts():
    gs = games()
    decisions = {(1, AS_OF): ("soon", 50, AS_OF + 45 * DAY),     # judged on 30 days: reached -50% on day 10
                 (2, AS_OF): ("wait", 30, AS_OF + 75 * DAY)}     # 60 days, but history ends on day 45
    result, _ = run_ns_backtest(dataset(gs), gs, EVENTS, Const(0.55), earlier=True, decisions=decisions)
    e = result["earlier"]
    assert (e["eligible"], e["eligible_hit"], e["censored"], e["no_horizon"]) == (1, 1, 1, 0)
    rows = {r["threshold"]: r for r in e["thresholds"]}
    assert (rows[0.5]["said"], rows[0.5]["hit"]) == (1, 1)
    assert rows[0.6]["said"] == 0
    decisions = {(1, AS_OF): ("wait", 50, AS_OF + 29 * DAY), (2, AS_OF): ("now", 30, AS_OF + 90 * DAY)}
    e = run_ns_backtest(dataset(gs), gs, EVENTS, Const(0.55), earlier=True, decisions=decisions)[0]["earlier"]
    assert (e["eligible"], e["no_horizon"]) == (0, 1)
    low = run_ns_backtest(dataset(gs), gs, EVENTS, Const(0.9, "low"), earlier=True,
                          decisions={(1, AS_OF): ("soon", 50, AS_OF + 45 * DAY)})[0]["earlier"]
    assert (low["eligible"], low["low_confidence"]) == (0, 1)


def test_dataset_identity(monkeypatch):
    gs = games()
    rd = dataset(gs).regions["TW"]
    first = ns_dataset_id(rd)
    assert ns_dataset_id(rd) == first
    other = RegionDataset("TW", rd.apps, rd.schedule, rd.window, "e" * 64, rd.population_apps)
    assert ns_dataset_id(other) != first
    monkeypatch.setattr(nsb, "TOL", timedelta(hours=12))
    assert ns_dataset_id(rd) != first
    monkeypatch.setattr(nsb, "TOL", timedelta(days=1))
    monkeypatch.setattr(nsb, "HORIZONS", (30, 60))
    assert ns_dataset_id(rd) != first


def test_errors_are_isolated():
    class Boom(Const):
        def predict(self, ev):
            if ev.app_id == 2:
                raise RuntimeError("boom")
            return super().predict(ev)
    gs = games()
    result, _ = run_ns_backtest(dataset(gs), gs, EVENTS, Boom(0.3), earlier=False)
    assert [e["app_id"] for e in result["errors"]] == [2]
    assert list(result["per_game"]) == ["1"]
