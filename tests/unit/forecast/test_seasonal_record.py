"""`seasonal-record` 1.0.0 (004 research R1; contracts/model-api.md; tasks T012). Hand-computed values throughout."""

import random

import pytest

from sweetspot.forecast.contract import LEVELS, validate_curve
from sweetspot.forecast.models import build_model
from sweetspot.forecast.models import seasonal_record as sr
from sweetspot.forecast.models.seasonal_freq import SeasonalFreq
from sweetspot.forecast.models.seasonal_record import (HazardTable, SeasonalRecord, build_hazard_table, chain_tables,
                                                       record_state)
from tests.forecast_builders import evidence, future_points, population

L = {d: i for i, d in enumerate(LEVELS)}


def prepared(pop, **params) -> SeasonalRecord:
    model = SeasonalRecord(**params)
    model.prepare(pop)
    return model


# Population where a fresh record is usually followed by another one, and a flat history never breaks.
TRENDING = {**{a: [50, 55, 60, 65, 70] for a in range(1, 31)}, **{a: [50] * 5 for a in range(31, 61)}}


# 1 ─ parameters ──────────────────────────────────────────────────────────────────────────────────────────────

def test_parameters_and_their_validation():
    model = build_model("seasonal-record@1.0.0", {"min_sales": "2", "half_life": "2", "hazard_history": "TW"})
    assert model.params == {"min_sales": 2, "half_life": 2, "hazard_history": "TW"}
    assert build_model("seasonal-record@1.0.0", {"half_life": "1.5"}).params["half_life"] == 1.5
    assert SeasonalRecord.tw_only_params == frozenset({"hazard_history"})
    assert (SeasonalRecord.name, SeasonalRecord.version) == ("seasonal-record", "1.0.0")
    for bad in ({"min_sales": 0}, {"min_sales": "x"}, {"half_life": -1}, {"hazard_history": "US"}, {"foo": 1}):
        with pytest.raises(ValueError):
            build_model("seasonal-record@1.0.0", bad)


# 2 ─ the low-confidence path is seasonal-freq's, bit for bit (guarantee 1) ─────────────────────────────────

@pytest.mark.parametrize("min_sales", [1, 2])
def test_low_confidence_path_is_seasonal_freq(min_sales):
    pop = population(TRENDING)
    model = prepared(pop, min_sales=min_sales)
    base = SeasonalFreq(min_sales=min_sales, history="TW")
    base.prepare(pop)
    for cuts in ([], [40] if min_sales == 2 else []):
        ev = evidence(cuts)
        assert model.predict(ev, future_points(6), LEVELS) == base.predict(ev, future_points(6), LEVELS)


# 3 ─ with no record data and no weighting it degenerates to seasonal-freq's probabilities (guarantee 2) ──────

def test_empty_table_and_no_weighting_is_seasonal_freq():
    pop = population({a: [30] for a in range(1, 5)})               # one sale each: no record units at min_sales=1
    model = prepared(pop, min_sales=1, half_life=0)
    base = SeasonalFreq(min_sales=1, history="TW")
    base.prepare(pop)
    ev = evidence([50, 60, 50])
    assert model.predict(ev, future_points(8), LEVELS).probabilities == \
        base.predict(ev, future_points(8), LEVELS).probabilities


# 4, 14 ─ recency weights; a shallowing trend lowers the old deep level ──────────────────────────────────────

def test_recency_weights():
    model = prepared(population({}), half_life=2)
    out = model.predict(evidence([50, 50, 70]), future_points(1), LEVELS)
    w = [0.5 ** 1, 0.5 ** 0.5, 1.0]
    assert out.probabilities[0][L[70]] == pytest.approx(1.0 / sum(w))
    assert out.probabilities[0][L[50]] == pytest.approx(1.0)


def test_shallowing_lowers_the_old_deep_level():
    model = prepared(population({}), half_life=2)
    out = model.predict(evidence([70, 70, 50, 50]), future_points(1), LEVELS)
    w = [0.5 ** 1.5, 0.5 ** 1, 0.5 ** 0.5, 1.0]
    assert out.probabilities[0][L[70]] == pytest.approx((w[0] + w[1]) / sum(w))
    assert out.probabilities[0][L[70]] < 0.5
    assert out.evidence["recent_direction"] == "shallower"
    assert any("變淺" in r for r in out.reasons)


# 5 ─ state ───────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cuts, m5, s, first", [
    ([55, 60, 65, 65, 65, 65, 70], 70, 0, 6),
    ([70, 50, 70, 60], 70, 3, 0),
    ([80, 10, 10, 10, 10, 10, 10], 80, 4, 0),          # capped at 4
    ([60, 67], 65, 0, 1),
    ([0, 0, 0], 0, 2, 0),
])
def test_record_state(cuts, m5, s, first):
    assert record_state(cuts) == (m5, s, first)


# 6 ─ the hazard table ──────────────────────────────────────────────────────────────────────────────────────────

def test_table_counts():
    table = build_hazard_table([("TW", [50, 50, 60]), ("TW", [70, 70, 70]), ("TW", [95, 95])], min_sales=1)
    # [50]→50 no (m 50–70, s 0); [50,50]→60 record +2 steps (s 1); [70]→70 no; [70,70]→70 no; 95: nothing deeper
    assert table.cells == {(1, 0): (2, 0), (1, 1): (2, 1)}
    assert table.m_counts == {1: (4, 1)}
    assert table.overall == (4, 1)
    assert table.jumps[1] == {2: 1.0}
    assert build_hazard_table([("TW", [50, 50, 60])], min_sales=2).cells == {(1, 1): (1, 1)}


def test_additive_smoothing():
    table = HazardTable(cells={(1, 0): (10, 5)}, m_counts={1: (100, 20)}, overall=(1000, 150),
                        jumps={}, regions=("TW",))
    m_rate = (20 + 20 * 0.15) / 120
    assert table.rate(60, 0) == pytest.approx((5 + 20 * m_rate) / 30)
    assert table.rate(60, 0) == pytest.approx(0.29444, abs=1e-5)
    assert table.rate(60, 2) == pytest.approx(m_rate)                  # an empty cell is its m group
    assert table.rate(10, 0) == pytest.approx(0.15)                    # an empty m group is the overall rate
    assert table.rate(95, 0) == 0.0
    assert table.basis(60, 0) == {"cell_sales": 10, "cell_records": 5, "m_group_sales": 100, "overall_sales": 1000}


def test_empty_table():
    table = build_hazard_table([], min_sales=1)
    assert table.rate(60, 0) == 0.0 and table.basis(60, 0) == "none"


def test_jumps_fall_back_to_all_groups_below_20_records():
    many = [("TW", [50, 55])] * 25 + [("TW", [80, 90])] * 3          # group 1: +1 step ×25; group 2: +2 ×3
    table = build_hazard_table(many, min_sales=1)
    assert table.jumps[1] == {1: 1.0}
    assert table.jumps[2] == pytest.approx({1: 25 / 28, 2: 3 / 28})
    capped = build_hazard_table([("TW", [10, 90])], min_sales=1)      # +16 steps → capped at 5
    assert capped.jumps[0] == {5: 1.0}


# 7 ─ regions ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_hazard_history_regions():
    pop = population({1: {"TW": [50, 60], "US": [50, 50, 50]}})
    tw = prepared(pop, hazard_history="TW")
    both = prepared(pop, hazard_history="TW+US")
    assert tw.table.overall == (1, 1) and tw.table.regions == ("TW",)
    assert both.table.overall == (3, 1) and both.table.regions == ("TW", "US")
    us = prepared(population({1: {"TW": [50, 60], "US": [50, 50, 50]}}, target="US"), hazard_history="TW+US")
    assert us.table.overall == (2, 0) and us.table.regions == ("US",)
    out = both.predict(evidence([50, 60]), future_points(2), LEVELS)
    assert out.evidence["hazard_regions"] == ["TW", "US"]
    assert any("含美國區折扣百分比" in r for r in out.reasons)


# 8 ─ the record chain ──────────────────────────────────────────────────────────────────────────────────────────

def test_chain_with_a_constant_hazard():
    tables = chain_tables(lambda m, t: 0.2 if m < 95 else 0.0, lambda m: {1: 1.0}, 2)
    assert tables[0][(60, 0, 65)] == pytest.approx(0.2)
    assert tables[1][(60, 0, 65)] == pytest.approx(1 - 0.8 ** 2)
    assert tables[1][(60, 0, 70)] == pytest.approx(0.2 * 0.2)


def test_chain_with_a_hazard_that_depends_on_the_gap():
    h = [0.4, 0.2, 0.1, 0.1, 0.1]
    tables = chain_tables(lambda m, t: h[t], lambda m: {1: 1.0}, 3)
    assert tables[2][(60, 1, 65)] == pytest.approx(1 - 0.8 * 0.9 * 0.9)
    # record at sale 1 (0.2) then another within 2 sales (1 − 0.6 × 0.8), or at sale 2 (0.8 × 0.1) then at sale 3 (0.4)
    assert tables[2][(60, 1, 70)] == pytest.approx(0.2 * (1 - 0.6 * 0.8) + 0.8 * 0.1 * 0.4)


# 9 ─ monotone at the M / M+5 boundary and everywhere (guarantee 4) ────────────────────────────────────────────

def test_random_histories_give_valid_curves():
    rng = random.Random(4)
    pop = population({a: [rng.choice(range(0, 100, 5)) for _ in range(rng.randint(1, 8))] for a in range(1, 80)})
    model = prepared(pop, min_sales=1, half_life=2)
    points = future_points(20)
    for _ in range(200):
        cuts = [rng.choice(range(0, 100, 5)) for _ in range(rng.randint(1, 10))]
        out = model.predict(evidence(cuts), points, LEVELS)
        validate_curve(out.probabilities, len(points), len(LEVELS))
        m5 = max(cuts) - max(cuts) % 5
        if 0 < m5 < 95:
            for row in out.probabilities:
                assert row[L[m5]] >= row[L[m5 + 5]]


# 10 ─ one shared table per prepare (guarantee 5) ────────────────────────────────────────────────────────────

def test_the_chain_is_built_once_and_shared(monkeypatch):
    pop = population(TRENDING)
    calls = []
    real = sr.chain_tables
    monkeypatch.setattr(sr, "chain_tables", lambda *a: calls.append(a) or real(*a))
    model = prepared(pop)
    histories = ([55, 60, 65, 70], [50, 50, 50], [30, 60], [80, 85, 85])
    together = [model.predict(evidence(c), future_points(8), LEVELS) for c in histories]
    assert len(calls) == 1
    for cuts, out in zip(histories, together):
        assert prepared(pop).predict(evidence(cuts), future_points(8), LEVELS) == out


# 11 ─ deeper than past (guarantee 3; US1 scenarios 1-2) ───────────────────────────────────────────────────────

def test_deeper_levels_get_probability_and_trends_matter():
    model = prepared(population(TRENDING), half_life=0)
    rising = model.predict(evidence([55, 60, 65, 65, 65, 65, 70]), future_points(4), LEVELS)
    flat = model.predict(evidence([50] * 7), future_points(4), LEVELS)
    assert rising.probabilities[0][L[75]] > 0
    assert rising.probabilities[0][L[75]] > flat.probabilities[0][L[55]]
    assert rising.confidence == "normal"


# 12 ─ reasons and evidence ────────────────────────────────────────────────────────────────────────────────────

def test_reasons_and_evidence():
    model = prepared(population(TRENDING), half_life=2)
    out = model.predict(evidence([55, 60, 65, 65, 65, 65, 70]), future_points(4), LEVELS)
    ev = out.evidence
    assert ev["record_sale"] == "2021 夏特" and ev["since_record"] == 0 and ev["max_cut"] == 70
    assert ev["hazard"] == pytest.approx(model.table.rate(70, 0))
    assert ev["hazard_basis"]["cell_sales"] == 150 and ev["hazard_regions"] == ["TW"]
    assert ev["half_life"] == 2 and ev["recent_direction"] == "deeper" and ev["sales_used"] == 7
    r = out.reasons
    assert r[0].startswith("依本身的季節特賣紀錄：台灣區 7 場")
    assert r[1].startswith("過去最大折扣 -70%")
    assert r[2] == "最近 4 場折扣加深（-65% → -70%）；近期的特賣權重較高：每早 2 場，權重減半"
    assert r[3].startswith("上一次創新低是 2021 夏特（-70%，0 場以前）；參考資料集中，最深折扣在 -50%～-70%、"
                           "上一場剛創新低的遊戲，下一場打出比過去更深的折扣的比例為 ")
    assert "（150 場）" in r[3]
    assert r[4].startswith("比 -70% 更深的折扣：")
    assert r[5] == "假設在同樣的狀態下，各場特賣彼此獨立"


def test_small_cells_and_empty_tables_are_said_so():
    small = prepared(population({a: [50, 50, 60] for a in range(1, 4)}), half_life=0)
    out = small.predict(evidence([50, 60]), future_points(2), LEVELS)
    assert any("樣本少" in r for r in out.reasons)
    empty = prepared(population({}), half_life=0)
    out = empty.predict(evidence([50, 60]), future_points(2), LEVELS)
    assert out.evidence["hazard_basis"] == "none"
    assert any("沒有足夠的樣本估計創新低機率" in r for r in out.reasons)
    assert out.probabilities[1][L[65]] == 0.0


# 13 ─ interface ───────────────────────────────────────────────────────────────────────────────────────────────

def test_interface_attributes():
    assert SeasonalRecord.predicts_deeper is True
    assert "{now_deeper_within_12m}" in SeasonalRecord.deeper_caveat
    levels = SeasonalRecord(min_sales=1).confidence_levels()
    assert set(levels) == {"normal", "low"} and "1 場" in levels["normal"]


# 15 ─ one own sale (spec Edge Cases, short histories) ─────────────────────────────────────────────────────────

def test_one_own_sale():
    model = prepared(population(TRENDING), min_sales=1, half_life=2)
    out = model.predict(evidence([50]), future_points(4), LEVELS)
    assert out.confidence == "normal"
    assert out.probabilities[0][L[50]] == 1.0
    assert 0 < out.probabilities[0][L[55]] < 1
    assert out.probabilities[0][L[55]] == pytest.approx(model.table.rate(50, 0) * sum(
        p for j, p in model.table.jumps[1].items() if j >= 1))
    assert out.evidence["recent_direction"] is None
    assert not any("最近" in r for r in out.reasons)


# 16 ─ never discounted (spec Edge Cases) ─────────────────────────────────────────────────────────────────────

def test_never_discounted():
    model = prepared(population({**TRENDING, **{a: [0, 0, 10] for a in range(61, 90)}}), half_life=0)
    out = model.predict(evidence([0, 0, 0]), future_points(4), LEVELS)
    assert out.evidence["since_record"] == 2 and out.evidence["max_cut"] == 0
    assert out.probabilities[0][L[5]] > 0
    assert out.reasons[1] == "過去 3 場季節特賣都沒打折"
    assert "已經 2–3 場沒有更深折扣的遊戲" in out.reasons[2]
    assert not any("-0%" in r or "創新低是" in r or "最近" in r for r in out.reasons)
    assert any(r.startswith("-5% 以上的折扣：") for r in out.reasons)
