"""Baseline model seasonal-freq (research R5; tasks T013, T038). Every number is checked by hand."""

import pytest

from sweetspot.forecast.contract import LEVELS, validate_curve
from sweetspot.forecast.evidence import GameEvidence, PopulationView
from sweetspot.forecast.models import build_model
from sweetspot.forecast.models.seasonal_freq import SeasonalFreq
from sweetspot.forecast.salepoints import SalePoint
from sweetspot.forecast.series import SaleOutcome
from tests.forecast_builders import dt

AS_OF = dt("2026-08-01")
SEASONS = ["winter", "spring", "summer", "autumn"]


def outcomes(region: str, cuts: list[int], first_year: int = 2024) -> tuple[SaleOutcome, ...]:
    out = []
    for i, cut in enumerate(cuts):
        season, year = SEASONS[i % 4], first_year + i // 4
        start = dt(f"{year}-{3 * (i % 4) + 1:02d}-10")
        out.append(SaleOutcome(season, year, f"{year} {season}", region, start, start.replace(day=17), cut))
    return tuple(out)


def points(n: int) -> tuple[SalePoint, ...]:
    return tuple(SalePoint(index=i, season="summer", year=2026 + i, label=f"{2026 + i} 夏特",
                           start=dt(f"{2026 + i}-06-25"), end=dt(f"{2026 + i}-07-09"), status="estimated",
                           basis={}) for i in range(1, n + 1))


def evidence(tw=(), us=(), target="TW") -> GameEvidence:
    history = {"TW": tuple(tw), "US": tuple(us)} if target == "TW" else {"US": tuple(us)}
    return GameEvidence(app_id=7, as_of=AS_OF, target_region=target, series={}, sale_history=history)


def population(histories: list[dict], target="TW") -> PopulationView:
    return PopulationView(AS_OF, target, {i: h for i, h in enumerate(histories, 100)})


POP = population([{"TW": outcomes("TW", [0, 20, 40, 60]), "US": ()}])   # shares: ≥5 .75, ≥25 .5, ≥45 .25


def test_own_frequency_and_cumulative_probability():
    model = SeasonalFreq(min_sales=1, history="TW")
    model.prepare(POP)
    out = model.predict(evidence(tw=outcomes("TW", [50, 50, 60, 20, 50, 70, 0, 50])), points(3), LEVELS)
    j50 = LEVELS.index(50)
    assert out.probabilities[0][j50] == pytest.approx(0.75)                    # 6 of 8 sales ≥ 50
    assert out.probabilities[1][j50] == pytest.approx(1 - 0.25 ** 2)
    assert out.probabilities[2][j50] == pytest.approx(1 - 0.25 ** 3)
    assert out.probabilities[0][LEVELS.index(75)] == 0.0                        # deeper than ever seen
    assert out.confidence == "normal"
    validate_curve(out.probabilities, 3, len(LEVELS))


def test_below_threshold_uses_population_and_is_low_confidence():
    model = SeasonalFreq(min_sales=3, history="TW")
    model.prepare(POP)
    out = model.predict(evidence(tw=outcomes("TW", [90, 90])), points(2), LEVELS)
    assert out.confidence == "low"
    assert out.probabilities[0][LEVELS.index(25)] == pytest.approx(0.5)
    assert out.probabilities[1][LEVELS.index(45)] == pytest.approx(1 - 0.75 ** 2)
    assert any("少於門檻 3 場" in r and "2 場" in r for r in out.reasons)
    assert out.evidence["population_sales"] == 4


def test_exactly_at_threshold_is_normal():
    model = SeasonalFreq(min_sales=2)
    model.prepare(POP)
    assert model.predict(evidence(tw=outcomes("TW", [10, 20])), points(1), LEVELS).confidence == "normal"


def test_history_tw_ignores_us():
    model = SeasonalFreq(min_sales=1, history="TW")
    model.prepare(POP)
    out = model.predict(evidence(tw=outcomes("TW", [50]), us=outcomes("US", [0, 0, 0], first_year=2020)),
                        points(1), LEVELS)
    assert out.probabilities[0][LEVELS.index(50)] == 1.0
    assert out.evidence["regions"] == ["TW"]


def test_history_tw_plus_us_prefers_tw_for_the_same_sale():
    model = SeasonalFreq(min_sales=1, history="TW+US")
    model.prepare(POP)
    tw = outcomes("TW", [50, 50], first_year=2025)                       # winter/spring 2025
    us = outcomes("US", [0, 0, 0, 0, 0, 0], first_year=2024)             # 2024 ×4 + winter/spring 2025
    out = model.predict(evidence(tw=tw, us=us), points(1), LEVELS)
    assert out.probabilities[0][LEVELS.index(50)] == pytest.approx(2 / 6)   # 2 TW sales + 4 US-only sales
    assert out.evidence["regions"] == ["TW", "US"]
    assert any("美國區" in r for r in out.reasons)


def test_us_target_uses_only_us_whatever_the_history_param():
    pop = population([{"US": outcomes("US", [0, 100])}], target="US")
    for history in ("TW", "TW+US"):
        model = SeasonalFreq(min_sales=1, history=history)
        model.prepare(pop)
        out = model.predict(evidence(us=outcomes("US", [50, 0]), target="US"), points(1), LEVELS)
        assert out.probabilities[0][LEVELS.index(50)] == pytest.approx(0.5)
        assert any("美國區" in r for r in out.reasons)


def test_population_uses_history_param_too():
    pop = population([{"TW": outcomes("TW", [100]), "US": outcomes("US", [0, 0, 0], first_year=2020)}])
    only_tw, merged = SeasonalFreq(min_sales=5, history="TW"), SeasonalFreq(min_sales=5, history="TW+US")
    only_tw.prepare(pop)
    merged.prepare(pop)
    j = LEVELS.index(50)
    assert only_tw.predict(evidence(), points(1), LEVELS).probabilities[0][j] == 1.0
    assert merged.predict(evidence(), points(1), LEVELS).probabilities[0][j] == pytest.approx(0.25)


def test_empty_population_cannot_estimate():
    model = SeasonalFreq(min_sales=1)
    model.prepare(population([]))
    with pytest.raises(ValueError, match="沒有任何已結束的季節特賣"):
        model.predict(evidence(), points(1), LEVELS)


def test_reasons_and_evidence_describe_the_data():
    model = SeasonalFreq(min_sales=1)
    model.prepare(POP)
    out = model.predict(evidence(tw=outcomes("TW", [50, 30, 60])), points(1), LEVELS)
    text = " ".join(out.reasons)
    assert "台灣區" in text and "3 場" in text and "-60%" in text
    assert out.evidence == {"regions": ["TW"], "sales_used": 3, "first_sale": "2024 winter",
                            "last_sale": "2024 summer", "max_cut": 60, "population_sales": None}


def test_confidence_levels_mention_threshold():
    levels = SeasonalFreq(min_sales=3).confidence_levels()
    assert set(levels) == {"normal", "low"}
    assert "3 場" in levels["normal"] and "3 場" in levels["low"]


def test_params_parsing_and_validation():
    model = build_model("seasonal-freq", {"min_sales": "2", "history": "TW+US"})
    assert model.params == {"min_sales": 2, "history": "TW+US"}
    assert model.tw_only_params == frozenset({"history"})
    assert build_model("seasonal-freq").params == {"min_sales": 1, "history": "TW"}
    for bad in ({"min_sales": "0"}, {"min_sales": "x"}, {"history": "JP"}, {"other": "1"}):
        with pytest.raises(ValueError):
            build_model("seasonal-freq", bad)
    with pytest.raises(ValueError):
        build_model("nope")


def test_it_does_not_predict_deeper_than_its_past():
    """004 research R9: the model states its own limitation; the decision core quotes it."""
    from sweetspot.forecast.models.seasonal_freq import SeasonalFreq

    model = SeasonalFreq()
    assert model.predicts_deeper is False
    assert model.deeper_caveat == "長期最低價可能更低：目前的模型無法預測比過去更深的折扣"
