"""Output checks and the present-time forecast (feature 007 contracts/ns-model-api.md; tasks T010)."""

from dataclasses import replace

from sweetspot.forecast.nonseasonal import build_ns_model
from sweetspot.forecast.nonseasonal.engine import check_output, ns_forecast, predict_ns
from sweetspot.forecast.nonseasonal.evidence import NSBasis
from sweetspot.forecast.nonseasonal.model import NSOutput
from sweetspot.store.query import PriceStore
from tests.forecast_builders import BASIC_CALENDAR, GameSpec, build_db, dt

AS_OF = dt("2026-02-01")
BASIS = NSBasis(dt("2025-01-01"), "TW", 396, 0, None, None, None, None, None, False)
LEVELS = ("normal", "low")


def output(rows, confidence="normal", basis=BASIS):
    return NSOutput(tuple(tuple(r) for r in rows), confidence, ("own",) * 3, basis)


def good():
    return [[0.5 - 0.02 * j + 0.1 * i for j in range(19)] for i in range(3)]


def test_check_output_guarantees():
    assert check_output(output(good()), AS_OF, LEVELS) is None
    assert "形狀" in check_output(output(good()[:2]), AS_OF, LEVELS)
    bad = good()
    bad[0][3] = 1.0
    assert "超出" in check_output(output(bad), AS_OF, LEVELS)
    bad = good()
    bad[0][3] = float("nan")
    assert "超出" in check_output(output(bad), AS_OF, LEVELS)
    bad = good()
    bad[0][4] = bad[0][3] + 0.01
    assert "較深" in check_output(output(bad), AS_OF, LEVELS)
    bad = good()
    bad[2][0] = 0.0
    assert "較長" in check_output(output(bad), AS_OF, LEVELS)
    assert "信心" in check_output(output(good(), "high"), AS_OF, LEVELS)
    late = replace(BASIS, last_start=dt("2026-03-01"))
    assert "日期" in check_output(output(good(), basis=late), AS_OF, LEVELS)


class Broken:
    name, version, params = "broken", "0", {}

    def confidence_levels(self):
        return {"normal": "n"}

    def predict(self, ev):
        raise RuntimeError("boom")


def test_a_broken_model_only_gives_a_reason():
    assert predict_ns(Broken(), None) == "RuntimeError: boom"


def promo_rows(first, starts, cut=50):
    rows = [(first, 0)]
    for s in starts:
        rows += [(s, cut), (dt(s).replace(day=min(dt(s).day + 5, 28)).isoformat(), 0)]
    return rows


def test_present_forecast_on_a_small_store(db_path):
    games = [GameSpec(1, tw=promo_rows("2024-12-11", ["2025-02-01", "2025-04-01", "2025-08-01", "2025-11-01"]),
                      us=promo_rows("2023-01-01", ["2023-05-01", "2024-02-01"]), known_until={"TW": "2026-01-31"}),
             GameSpec(2, tw=promo_rows("2025-12-01", ["2025-12-05"]), known_until={"TW": "2026-01-31"}),
             GameSpec(3, tw=[("2024-12-11", 0)], known_until={"TW": "2026-01-31"})]
    build_db(db_path, games, calendar=BASIC_CALENDAR)
    store = PriceStore.open(db_path)
    try:
        batch = ns_forecast(store, [1, 2, 3, 99], AS_OF, build_ns_model("non-seasonal"))
    finally:
        store.close()
    assert batch.model == {"name": "non-seasonal", "version": "1.0.0",
                           "params": {"smoothing": 2, "history": "TW+US", "clock": True}}
    assert batch.outputs[99] == "沒有台灣區的價格歷史"
    one = batch.outputs[1]
    assert one.confidence == "normal" and one.basis.history_source == "TW+US"
    assert one.basis.promos_365d == 3                       # 2025-04, 08, 11 (02-01 is more than a year before)
    assert batch.outputs[2].confidence == "low"
    assert batch.outputs[3].basis.promos_365d == 0
