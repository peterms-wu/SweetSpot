"""feature 013 SC-006 / FR-015: recomputing at the record's as_of sees nothing after it (tasks T030).

The reverse test proves the check can fail: the same rows moved before as_of change the result.
"""

import pytest

from sweetspot.forecast.models import seasonal_record
from sweetspot.review.recompute import recompute
from sweetspot.store.query import PriceStore
from tests.review_builders import AS_OF, HISTORY, pre_sale_record, review_db

# A summer 2026 discount (6/25-7/9) for game 1: seen before as_of, it is evidence; seen after, it must not be.
BEFORE = {1: [("2026-01-01", 0), ("2026-06-26", 90), ("2026-07-05", 0), *HISTORY[1][1:]]}
AFTER = {1: [*HISTORY[1], ("2026-10-10", 90), ("2026-10-12", 0)], 2: [*HISTORY[2], ("2026-10-09", 95)]}


@pytest.fixture(autouse=True)
def tiny_sequences(monkeypatch):
    monkeypatch.setattr(seasonal_record, "MIN_SEQUENCES", 1)


def result(path, history=None):
    review_db(path, history=history)
    s = PriceStore.open(path)
    try:
        r = recompute(s, pre_sale_record(), AS_OF)
    finally:
        s.close()
    current = {g["app_id"]: (g.get("curve") or {}).get("probabilities") for g in r["current"]["forecast"]["games"]}
    groups = {d["app_id"]: (d["group"], d["sweet_cents"]) for d in r["current"]["decisions"]}
    baseline = {g["app_id"]: (g.get("curve") or {}).get("probabilities") for g in r["baseline"]["games"]}
    return current, groups, baseline


def test_rows_after_as_of_change_nothing(tmp_path):
    plain = result(tmp_path / "a" / "sweetspot.db")
    later = result(tmp_path / "b" / "sweetspot.db", AFTER)
    assert plain == later
    assert plain[0][1] is not None and plain[2][1] is not None      # both models produced curves to compare


def test_the_same_rows_before_as_of_do_change_it(tmp_path):
    plain = result(tmp_path / "a" / "sweetspot.db")
    earlier = result(tmp_path / "b" / "sweetspot.db", BEFORE)
    assert plain[0][1] != earlier[0][1]
    assert plain[2][1] != earlier[2][1]
