"""Feature 008 metrics (research R5; data-model; tasks T009): finer own-sales groups, per-game group Brier and the
finished-only calibration. Hand-computed."""

import pytest

from sweetspot.forecast.backtest.metrics import RegionMetrics

O, N, C = "occurred", "not-occurred", "censored"


def _add(m, app, probs, outcomes, *, finished=None, own_sales=None, past_max=None, confidence="normal"):
    m.add(app=app, pool="broad", confidence=confidence, horizons=["0-3m"] * len(probs),
          indexes=list(range(1, len(probs) + 1)), probs=probs, ref=[[0.5] * len(probs[0])] * len(probs),
          outcomes=outcomes, own_sales=own_sales, past_max=past_max, finished=finished)


def test_finer_own_sales_groups_keep_the_old_one():
    m = RegionMetrics("TW", [50])
    _add(m, 1, [[0.9]], [[O]], own_sales=4, past_max=50)                  # error .01
    _add(m, 2, [[0.5]], [[N]], own_sales=7, past_max=50)                  # error .25
    r = m.result()
    groups = {g["group"]: g for g in r["by_own_sales"]}
    assert groups["3+"]["brier"] == pytest.approx((0.01 + 0.25) / 2) and groups["3+"]["games"] == 2
    assert groups["3-5"]["brier"] == pytest.approx(0.01) and groups["6+"]["brier"] == pytest.approx(0.25)
    assert r["per_game_by_own_sales"] == {"1": {"3+": [1, pytest.approx(0.01)], "3-5": [1, pytest.approx(0.01)]},
                                          "2": {"3+": [1, pytest.approx(0.25)], "6+": [1, pytest.approx(0.25)]}}


def test_finished_calibration_counts_only_finished_units():
    m = RegionMetrics("TW", [30, 60])
    # game 1, two points: point 1 finished (reached 30, not 60); point 2 not finished (censored for the 002 score)
    _add(m, 1, [[0.8, 0.4], [0.9, 0.5]], [[O, N], [O, C]], finished=[[1, 0], None], own_sales=1, past_max=30)
    # game 2, low confidence, finished and nothing reached
    _add(m, 2, [[0.6, 0.2]], [[N, N]], finished=[[0, 0]], own_sales=0, confidence="low")
    fc = m.result()["finished_calibration"]
    assert fc["units"] == 4
    game1 = ((0.8 - 1) ** 2 + 0.4 ** 2) / 2
    game2 = (0.6 ** 2 + 0.2 ** 2) / 2
    assert fc["brier"] == pytest.approx((game1 + game2) / 2)               # each game weighted equally (002)
    bins = {b["lo"]: b for b in fc["bins"]}
    assert bins[0.8]["n"] == 1 and bins[0.8]["predicted"] == pytest.approx(0.8) and bins[0.8]["actual"] == 1
    assert bins[0.4]["n"] == 1 and bins[0.4]["actual"] == 0
    assert bins[0.2]["n"] == 1 and bins[0.6]["n"] == 1
    assert 0.9 not in bins                                                  # the unfinished point is left out
    conf = {g["group"]: g for g in fc["groups"]["confidence"]}
    assert conf["normal"]["n"] == 2 and conf["normal"]["predicted"] == pytest.approx(0.6)
    assert conf["normal"]["actual"] == pytest.approx(0.5) and conf["normal"]["brier"] == pytest.approx(game1)
    assert conf["low"]["brier"] == pytest.approx(game2)
    sales = {g["group"]: g for g in fc["groups"]["own_sales"]}
    assert set(sales) == {"0", "1"}
    seen = {g["group"]: g for g in fc["groups"]["seen"]}                     # M = 30: level 30 seen, 60 deeper
    assert seen["seen"]["n"] == 1 and seen["deeper"]["n"] == 1
    dist = {g["group"]: g for g in fc["groups"]["distance"]}
    assert dist["M"]["n"] == 1 and dist[">=M+10"]["n"] == 1


def test_distance_groups():
    m = RegionMetrics("TW", [40, 45, 50, 55, 60, 70])
    _add(m, 1, [[0.5] * 6], [[N] * 6], finished=[[0] * 6], own_sales=2, past_max=55)
    dist = {g["group"]: g["n"] for g in m.result()["finished_calibration"]["groups"]["distance"]}
    assert dist == {"<=M-15": 1, "M-10": 1, "M-5": 1, "M": 1, "M+5": 1, ">=M+10": 1}


def test_existing_results_do_not_change():
    """SC-004: the new inputs never touch the 002 score."""
    def run(finished):
        m = RegionMetrics("TW", [30, 60])
        _add(m, 1, [[0.8, 0.4], [0.9, 0.5]], [[O, N], [O, C]], finished=finished, own_sales=1, past_max=30)
        _add(m, 2, [[0.6, 0.2]], [[N, N]], own_sales=0, confidence="low")
        r = m.result()
        for key in ("finished_calibration", "per_game_by_own_sales"):
            r.pop(key)
        r["by_own_sales"] = [g for g in r["by_own_sales"] if g["group"] in ("0", "1", "2", "3+")]
        return r

    assert run(None) == run([[1, 0], None])


def test_without_finished_input_the_block_is_empty():
    m = RegionMetrics("TW", [30])
    _add(m, 1, [[0.8]], [[O]], own_sales=1, past_max=30)
    fc = m.result()["finished_calibration"]
    assert fc["units"] == 0 and fc["brier"] is None
