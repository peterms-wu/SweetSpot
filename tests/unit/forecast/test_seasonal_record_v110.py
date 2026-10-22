"""`seasonal-record` 1.1.0 (feature 008 research R1, R2; contracts/model-api.md; tasks T013, T014).
Hand-computed values throughout. Records of a population game start on first_year-12-20 (tests.forecast_builders)."""

from datetime import date

import pytest

from sweetspot.forecast.contract import LEVELS, validate_curve
from sweetspot.forecast.models import build_model
from sweetspot.forecast.models.seasonal_record import SeasonalRecord, SeasonalRecordV110
from tests.forecast_builders import evidence, future_points, population

L = {d: i for i, d in enumerate(LEVELS)}
AS_OF_DATE = date(2030, 1, 1)


def prepared(pop, **params) -> SeasonalRecordV110:
    model = SeasonalRecordV110(**params)
    model.prepare(pop)
    return model


def new_game_population(sequences: dict[int, list[int]], *, release=date(2019, 6, 1), extra=None, releases=None):
    """Every game's first record starts 2019-12-20; released 2019-06-01 = a new game (≤ 365 days)."""
    histories = dict(sequences)
    rel = {a: release for a in sequences}
    for a, cuts in (extra or {}).items():                         # old games: released long before their first record
        histories[a] = cuts
        rel[a] = date(2010, 1, 1)
    rel.update(releases or {})
    return population(histories, release_dates=rel)


# 40 new games: 15 × [0, 50], 15 × [30, 30], 10 × [60]; plus old games that must not count
SEQS = {**{a: [0, 50] for a in range(1, 16)}, **{a: [30, 30] for a in range(16, 31)}, **{a: [60] for a in range(31, 41)}}
OLD = {a: [90, 90, 90] for a in range(100, 150)}


# ─ parameters ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_parameters_and_their_validation():
    model = build_model("seasonal-record", {"low_base": "new-split", "shrink": "0.5"}, version="1.1.0")
    assert model.params == {"min_sales": 1, "half_life": 2, "hazard_history": "TW+US", "low_base": "new-split",
                            "shrink": 0.5}
    assert (SeasonalRecordV110.name, SeasonalRecordV110.version) == ("seasonal-record", "1.1.0")
    assert build_model("seasonal-record", {"shrink": "1"}, version="1.1.0").params["shrink"] == 1
    for bad in ({"low_base": "old"}, {"shrink": -0.1}, {"shrink": "x"}, {"foo": 1}):
        with pytest.raises(ValueError):
            build_model("seasonal-record", bad, version="1.1.0")
    assert SeasonalRecordV110.grid_exclusion({"shrink": 0}) == "fr-003"
    assert SeasonalRecordV110.grid_exclusion({"shrink": "0.5"}) is None


# ─ guarantee 1: population + shrink 0 is 1.0.0 bit for bit ─────────────────────────────────────────────────────

@pytest.mark.parametrize("cuts", [[], [50], [0, 0, 0], [50, 60, 70, 60]])
def test_degenerates_to_1_0_0(cuts):
    pop = new_game_population(SEQS, extra=OLD)
    old = SeasonalRecord()
    old.prepare(pop)
    new = prepared(pop, low_base="population", shrink=0)
    ev = evidence(cuts, release_date=date(2029, 5, 1))
    assert new.predict(ev, future_points(6), LEVELS) == old.predict(ev, future_points(6), LEVELS)


# ─ guarantee 2, 3: shrinking the seen levels ───────────────────────────────────────────────────────────────────

SHARE_POP = {a: [50, 0] for a in range(1, 11)}                     # 20 records, 10 at -50%: b(50) = 0.5


def test_one_sale_is_no_longer_certain():
    model = prepared(population(SHARE_POP), shrink=0.5)
    out = model.predict(evidence([50]), future_points(3), LEVELS)
    p = (1 * 1.0 + 0.5 * 0.5) / 1.5
    h = model.table.rate(50, 0)
    assert out.probabilities[0][L[50]] == pytest.approx(1 - (1 - p) * (1 - h))
    assert out.probabilities[0][L[50]] < 1
    assert out.evidence["shrink"] == 0.5 and out.evidence["own_share_raw"] == pytest.approx(1.0)


def test_shrink_weakens_with_more_records():
    model = prepared(population(SHARE_POP), shrink=0.5)
    first = [model.predict(evidence([50] * n), future_points(1), LEVELS).probabilities[0][L[50]] for n in (1, 2, 5)]
    assert first[0] < first[1] < first[2] < 1


# ─ guarantee 4: the new-game base ──────────────────────────────────────────────────────────────────────────────

def test_new_game_empirical_cumulative():
    model = prepared(new_game_population(SEQS, extra=OLD), low_base="new")
    out = model.predict(evidence([], release_date=date(2029, 6, 1)), future_points(4), LEVELS)
    assert out.confidence == "low"
    # k = 1 over 40 sequences: first cuts 0 ×15, 30 ×15, 60 ×10
    assert out.probabilities[0][L[30]] == pytest.approx(25 / 40)
    assert out.probabilities[0][L[50]] == pytest.approx(10 / 40)
    # k = 2 over the 30 sequences with ≥ 2 records: max 50 ×15, 30 ×15; monotone in k keeps 60 at 10/40
    assert out.probabilities[1][L[30]] == pytest.approx(1.0)
    assert out.probabilities[1][L[50]] == pytest.approx(0.5)
    assert out.probabilities[1][L[60]] == pytest.approx(10 / 40)
    # k = 3: fewer than 30 sequences → carries k = 2
    assert out.probabilities[3] == out.probabilities[1]
    assert out.evidence["low_sequences"] == "all-new" and out.evidence["new_games"] == 40
    assert out.probabilities[0][L[90]] == 0                          # the old games' -90% never counts


def test_new_split_uses_pre_release_sequences_for_unreleased_targets():
    pre = {a: [0] for a in range(1, 31)}                            # released after their first record (2020-02-01)
    post = {a: [50] for a in range(31, 61)}
    pop = new_game_population({**pre, **post}, releases={a: date(2020, 2, 1) for a in pre})
    model = prepared(pop, low_base="new-split")
    unreleased = model.predict(evidence([], release_date=date(2031, 1, 1)), future_points(2), LEVELS)
    released = model.predict(evidence([], release_date=date(2029, 1, 1)), future_points(2), LEVELS)
    assert unreleased.probabilities[0][L[5]] == 0 and unreleased.evidence["low_sequences"] == "pre-release"
    assert released.probabilities[0][L[50]] == 1 and released.evidence["low_sequences"] == "released"


# ─ guarantee 5: unknown release dates and thin samples ─────────────────────────────────────────────────────────

def test_unknown_release_date_counts_as_released():
    pre = {a: [0] for a in range(1, 31)}
    post = {a: [50] for a in range(31, 61)}
    unknown = {a: [95] for a in range(61, 71)}                     # unknown release: never in any sequence
    pop = new_game_population({**pre, **post, **unknown},
                              releases={**{a: date(2020, 2, 1) for a in pre}, **{a: None for a in unknown}})
    model = prepared(pop, low_base="new-split")
    out = model.predict(evidence([], release_date=None), future_points(1), LEVELS)
    assert out.evidence["low_sequences"] == "released" and out.probabilities[0][L[95]] == 0
    assert any("發行日未知，視為已發行" in r for r in out.reasons)


def test_thin_sample_falls_back_to_the_population_share():
    pop = new_game_population({a: [40] for a in range(1, 11)}, extra=OLD)     # 10 new sequences < 30
    model = prepared(pop, low_base="new")
    old = SeasonalRecord()
    old.prepare(pop)
    ev = evidence([], release_date=date(2029, 6, 1))
    out = model.predict(ev, future_points(3), LEVELS)
    assert out.probabilities == old.predict(ev, future_points(3), LEVELS).probabilities
    assert any("樣本不足" in r for r in out.reasons)


# ─ guarantee 6: monotone curves ────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cuts", [[], [50], [80], [30, 60], [60, 40, 40], [0]])
@pytest.mark.parametrize("shrink", [0.25, 1, 3])
def test_curves_stay_monotone(cuts, shrink):
    pop = new_game_population(SEQS, extra={**OLD, **{a: [50, 55, 60, 65] for a in range(200, 230)}})
    model = prepared(pop, low_base="new-split", shrink=shrink)
    out = model.predict(evidence(cuts, release_date=date(2029, 6, 1)), future_points(8), LEVELS)
    validate_curve(out.probabilities, 8, len(LEVELS))


# ─ guarantee 7: a US target uses US records only ───────────────────────────────────────────────────────────────

def test_us_target_builds_sequences_from_us_records():
    tw_only = {a: {"TW": [50]} for a in range(1, 41)}
    old_us = {a: {"US": [70, 70]} for a in range(100, 110)}          # the pool has US records, but no new US games
    pop = population({**tw_only, **old_us}, target="US",
                     release_dates={**{a: date(2019, 6, 1) for a in tw_only}, **{a: date(2010, 1, 1) for a in old_us}})
    model = prepared(pop, low_base="new")
    out = model.predict(evidence({}, target="US", release_date=date(2029, 6, 1)), future_points(1), LEVELS)
    assert any("樣本不足" in r for r in out.reasons)                     # no US sequences at all
    us = {a: {"US": [20]} for a in range(1, 41)}
    pop = population(us, target="US", release_dates={a: date(2019, 6, 1) for a in us})
    model = prepared(pop, low_base="new")
    out = model.predict(evidence({}, target="US", release_date=date(2029, 6, 1)), future_points(1), LEVELS)
    assert out.probabilities[0][L[20]] == 1 and out.probabilities[0][L[25]] == 0


# ─ reasons (T014) ──────────────────────────────────────────────────────────────────────────────────────────────

def test_reasons_for_a_released_new_game():
    model = prepared(new_game_population(SEQS, extra=OLD), low_base="new-split")
    out = model.predict(evidence([], release_date=date(2029, 6, 1)), future_points(2), LEVELS)
    assert out.reasons[0] == "本身沒有已結束的季節特賣紀錄（發行於 2029-06-01）"
    assert out.reasons[1].startswith("參考資料集中 40 款新遊戲（發行 1 年內開始有紀錄）：")
    assert "第 1 場" in out.reasons[1] and "-30%" in out.reasons[1] and "62%" in out.reasons[1]    # 25/40 = 62.5%
    assert "新遊戲前幾場的折扣通常比老遊戲淺" in out.reasons[2]


def test_reasons_for_an_unreleased_game():
    pre = {a: [10] for a in range(1, 31)}
    pop = new_game_population(pre, releases={a: date(2020, 2, 1) for a in pre})
    model = prepared(pop, low_base="new-split")
    out = model.predict(evidence([], release_date=date(2031, 3, 1)), future_points(2), LEVELS)
    assert out.reasons[0] == "尚未發行（預定 2031-03-01），本身沒有季節特賣紀錄"
    assert "發售前就有季節特賣紀錄的 30 款遊戲" in out.reasons[1]


def test_shrink_reason_only_for_few_records():
    model = prepared(population(SHARE_POP), shrink=0.5)
    one = model.predict(evidence([50]), future_points(2), LEVELS)
    line = next(r for r in one.reasons if "向參考資料集的比例靠攏" in r)
    assert "本身只有 1 場紀錄" in line and "0.5 場" in line and "不是 100%" in line
    many = model.predict(evidence([50] * 4), future_points(2), LEVELS)
    assert not any("向參考資料集的比例靠攏" in r for r in many.reasons)


def test_confidence_levels_describe_the_base():
    assert "新遊戲" in SeasonalRecordV110(low_base="new-split").confidence_levels()["low"]
    assert "發售前" in SeasonalRecordV110(low_base="new-split").confidence_levels()["low"]
    assert SeasonalRecordV110(low_base="population").confidence_levels() == SeasonalRecord().confidence_levels()
