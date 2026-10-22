"""research R4 metrics on hand-computed examples (tasks T022)."""

import pytest

from sweetspot.forecast.backtest.metrics import RegionMetrics

O, N, C, H = "occurred", "not-occurred", "censored", "not-held"


def metrics(levels=(50,)) -> RegionMetrics:
    return RegionMetrics("TW", list(levels))


def test_brier_is_the_mean_of_per_game_means():
    m = metrics()
    # game A: three units, errors .01, .04, .09 → mean .14/3; game B: one unit, error .25
    m.add(app=1, pool="broad", confidence="normal", horizons=["0-3m", "3-6m", "6-12m"], indexes=[1, 2, 3],
          probs=[[0.9], [0.8], [0.7]], ref=[[0.5], [0.5], [0.5]], outcomes=[[O], [O], [O]])
    m.add(app=2, pool="wishlist", confidence="low", horizons=["0-3m"], indexes=[1], probs=[[0.5]], ref=[[0.5]],
          outcomes=[[N]])
    r = m.result()
    assert r["brier"] == pytest.approx(((0.01 + 0.04 + 0.09) / 3 + 0.25) / 2)
    assert r["games"] == 2 and r["units"] == {"scored": 4, "censored": 0, "not_held": 0}
    assert r["reference_brier"] == pytest.approx((0.25 + 0.25) / 2)
    assert r["per_game"] == {"1": [3, pytest.approx(0.14)], "2": [1, pytest.approx(0.25)]}


def test_censored_and_not_held_are_counted_not_scored():
    m = metrics()
    m.add(app=1, pool="broad", confidence="normal", horizons=["0-3m", "3-6m", "6-12m"], indexes=[1, 2, 3],
          probs=[[0.2], [0.4], [0.6]], ref=[[0.5]] * 3, outcomes=[[N], [H], [C]])
    r = m.result()
    assert r["units"] == {"scored": 1, "censored": 1, "not_held": 1}
    assert r["brier"] == pytest.approx(0.04)


def test_groups_are_per_game_means_within_the_group():
    m = metrics(levels=(30, 60))
    m.add(app=1, pool="broad", confidence="normal", horizons=["0-3m"], indexes=[1], probs=[[1.0, 0.5]],
          ref=[[0.5, 0.5]], outcomes=[[O, N]])
    m.add(app=2, pool="broad", confidence="low", horizons=["0-3m"], indexes=[1], probs=[[0.0, 0.0]],
          ref=[[0.5, 0.5]], outcomes=[[O, N]])
    r = m.result()
    by_level = {g["group"]: g for g in r["by_level"]}
    assert by_level[30]["brier"] == pytest.approx((0.0 + 1.0) / 2)
    assert by_level[60]["brier"] == pytest.approx((0.25 + 0.0) / 2)
    by_conf = {g["group"]: g for g in r["by_confidence"]}
    assert by_conf["normal"]["brier"] == pytest.approx(0.125) and by_conf["normal"]["games"] == 1
    assert by_conf["low"]["brier"] == pytest.approx(0.5)
    assert {g["group"] for g in r["by_horizon"]} == {"0-3m"}
    assert r["by_pool"] == [{"group": "broad", "brier": pytest.approx((0.125 + 0.5) / 2), "games": 2, "units": 4}]


def test_calibration_weights_units_by_one_over_game_units():
    m = metrics()
    # game 1: two units in bin 0.8-0.9 (both occurred); game 2: one unit in the same bin (not occurred)
    m.add(app=1, pool="broad", confidence="normal", horizons=["0-3m", "3-6m"], indexes=[1, 2],
          probs=[[0.8], [0.8]], ref=[[0.5]] * 2, outcomes=[[O], [O]])
    m.add(app=2, pool="broad", confidence="normal", horizons=["0-3m"], indexes=[1], probs=[[0.85]], ref=[[0.5]],
          outcomes=[[N]])
    (row,) = [b for b in m.result()["calibration"] if b["units"]]
    assert row["bin"] == [0.8, 0.9] and row["units"] == 3
    # weights: game 1 units 1/2 each (total 1), game 2 unit 1 → forecast (0.8 + 0.85)/2, observed (1 + 0)/2
    assert row["mean_forecast"] == pytest.approx(0.825) and row["observed_rate"] == pytest.approx(0.5)


def test_hit_rate_and_timing_error():
    m = metrics()
    # case 1: forecast crosses 0.5 at point 2, first occurrence at point 2 → hit, error 0
    m.add(app=1, pool="broad", confidence="normal", horizons=["0-3m"] * 3, indexes=[1, 2, 3],
          probs=[[0.3], [0.6], [0.8]], ref=[[0.5]] * 3, outcomes=[[N], [O], [O]])
    # case 2: crosses at point 1, occurs at point 3 → miss, error -2
    m.add(app=2, pool="broad", confidence="normal", horizons=["0-3m"] * 3, indexes=[1, 2, 3],
          probs=[[0.6], [0.7], [0.8]], ref=[[0.5]] * 3, outcomes=[[N], [N], [O]])
    # case 3: never reaches 0.5, but occurs → never_predicted_but_occurred
    m.add(app=3, pool="broad", confidence="normal", horizons=["0-3m"] * 2, indexes=[1, 2],
          probs=[[0.1], [0.2]], ref=[[0.5]] * 2, outcomes=[[N], [O]])
    # case 4: crosses at point 1, nothing happens in the window → miss, not_occurred_in_window
    m.add(app=4, pool="broad", confidence="normal", horizons=["0-3m"] * 2, indexes=[1, 2],
          probs=[[0.9], [0.95]], ref=[[0.5]] * 2, outcomes=[[N], [N]])
    # case 5: point forecast is censored
    m.add(app=5, pool="broad", confidence="normal", horizons=["0-3m"], indexes=[1], probs=[[0.9]], ref=[[0.5]],
          outcomes=[[C]])
    r = m.result()
    assert r["hit_rate"] == {"point_forecasts": 3, "hits": 1, "rate": pytest.approx(1 / 3), "never_predicted": 1,
                             "never_predicted_but_occurred": 1, "censored": 1}
    assert r["timing_error"]["n"] == 2
    assert r["timing_error"]["mean"] == pytest.approx(-1.0)
    assert r["timing_error"]["mean_abs"] == pytest.approx(1.0)
    assert r["timing_error"]["distribution"] == {"-2": 1, "0": 1}
    assert r["timing_error"]["not_occurred_in_window"] == 1


def test_empty_region():
    r = metrics().result()
    assert r["brier"] is None and r["games"] == 0


# --- feature 004: deeper than past, by own sales (research R2; tasks T006) --------------------------------

def test_deeper_than_past_scores_only_levels_beyond_the_games_own_deepest_cut():
    m = metrics(levels=(50, 60, 70))
    # game 1: 2 own sales, deepest -55% → levels 60 and 70 are deeper than its past
    m.add(app=1, pool="broad", confidence="normal", horizons=["0-3m"], indexes=[1], probs=[[0.9, 0.3, 0.1]],
          ref=[[0.5] * 3], outcomes=[[O, O, N]], own_sales=2, past_max=55)
    # game 2: no own sale → nothing is "deeper than its past"
    m.add(app=2, pool="broad", confidence="low", horizons=["0-3m"], indexes=[1], probs=[[0.5, 0.5, 0.5]],
          ref=[[0.5] * 3], outcomes=[[O, O, O]], own_sales=0, past_max=None)
    # game 3: deepest -70% → no level is deeper
    m.add(app=3, pool="broad", confidence="normal", horizons=["0-3m"], indexes=[1], probs=[[1.0, 1.0, 1.0]],
          ref=[[0.5] * 3], outcomes=[[O, O, O]], own_sales=1, past_max=70)
    deeper = m.result()["deeper_than_past"]
    assert deeper["brier"] == pytest.approx((0.49 + 0.01) / 2)
    assert deeper["games"] == 1 and deeper["units"] == 2
    cal = {c["bin"][0]: c for c in deeper["calibration"] if c["units"]}
    assert cal[0.1]["mean_forecast"] == pytest.approx(0.1) and cal[0.1]["observed_rate"] == 0
    assert cal[0.3]["mean_forecast"] == pytest.approx(0.3) and cal[0.3]["observed_rate"] == 1


def test_by_own_sales_groups_games_by_their_ended_seasonal_sales_at_as_of():
    m = metrics()
    m.add(app=1, pool="broad", confidence="low", horizons=["0-3m"], indexes=[1], probs=[[0.5]], ref=[[0.5]],
          outcomes=[[O]], own_sales=0, past_max=None)
    m.add(app=2, pool="broad", confidence="normal", horizons=["0-3m"], indexes=[1], probs=[[0.9]], ref=[[0.5]],
          outcomes=[[O]], own_sales=1, past_max=50)
    m.add(app=3, pool="broad", confidence="normal", horizons=["0-3m"], indexes=[1], probs=[[0.8]], ref=[[0.5]],
          outcomes=[[O]], own_sales=5, past_max=50)
    m.add(app=3, pool="broad", confidence="normal", horizons=["0-3m"], indexes=[1], probs=[[0.6]], ref=[[0.5]],
          outcomes=[[O]], own_sales=2, past_max=50)       # the same game at an earlier as_of
    groups = {g["group"]: g for g in m.result()["by_own_sales"]}
    assert list(groups) == ["0", "1", "2", "3+", "3-5"]                 # 3-5 / 6+ added by feature 008
    assert groups["3-5"]["brier"] == pytest.approx(0.04)
    assert groups["0"]["brier"] == pytest.approx(0.25)
    assert groups["1"]["brier"] == pytest.approx(0.01)
    assert groups["2"]["brier"] == pytest.approx(0.16) and groups["2"]["games"] == 1
    assert groups["3+"]["brier"] == pytest.approx(0.04)


def test_new_groups_without_any_unit():
    m = metrics()
    m.add(app=1, pool="broad", confidence="low", horizons=["0-3m"], indexes=[1], probs=[[0.5]], ref=[[0.5]],
          outcomes=[[O]])
    r = m.result()
    assert r["deeper_than_past"]["brier"] is None and r["deeper_than_past"]["games"] == 0
    assert r["by_own_sales"] == []
