"""feature 013 (research R4, FR-007–FR-010a): scoring one sale against a record. Expected values are worked out
by hand in the comments, not computed with the code under test."""

from pathlib import Path

import pytest

from sweetspot.calendar import SaleEvent
from sweetspot.review.actual import SaleActual, Tracked
from sweetspot.review.score import (decision_summary, early_switch, review_game, seasonal_summary, seed_for)
from tests.forecast_builders import dt
from tests.review_builders import (AS_OF, DURING_AS_OF, EARLY, RECORD, SEASONAL, WINTER_POINT, decision,
                                   during_records, forecast_game, pre_sale_record)

SALE = SaleEvent("Steam Autumn Sale", "秋季特賣", "seasonal", "autumn", 2026, dt("2026-10-01T17:00"),
                 dt("2026-10-08T17:00"), "ended", "test")
LEVELS = list(range(5, 100, 5))
SEED = seed_for(RECORD)


def tracked(app=1, reason=None):
    return Tracked(f"itad-{app}", "default", {"kind": "sub", "id": app * 1000 + 1, "name": f"Game {app}"}, None, (),
                   dt("2026-10-10"), reason)


def actual(max_cut, min_cents, running=0):
    """Hand-made outcome: levels above the running cut up to max_cut are first crossed at the sale start."""
    crossings = {d: SALE.start if running < d <= max_cut else None for d in LEVELS}
    return SaleActual(max_cut=max_cut, min_cents=min_cents, running_cut_at_as_of=running, crossings=crossings,
                      sale_end=SALE.end)


def during(groups=EARLY, days=range(7)):
    return tuple((Path(f"{r['as_of']}.json.gz"), r) for r in during_records(groups, days=days))


def review(d, a, game=None, *, tr=None, dur=(), missing=()):
    game = forecast_game(d["app_id"]) if game is None and d["status"] == "ok" else game
    return review_game(d, game, tr or tracked(d["app_id"]), a, SALE, dur, missing)


A = decision(1, "soon")                                  # sweet -50% → NT$250.00
B = decision(2, "now", current_cents=30000)


# --- seasonal probabilities (T008) ----------------------------------------------------------------------

def test_per_game_brier_under_both_definitions():
    a = review(A, actual(60, 20000))
    # A: p 0.8 for 5..60 (reached), 0.2 for 65..95 (not reached) → every unit (0.2)^2 = 0.04, both definitions
    assert a["status"] == "reviewed"
    assert a["seasonal"]["brier"] == {"sale_max": 0.04, "crossing": 0.04}
    b = review(B, actual(40, 30000, running=40))
    # B: p 0.9 for 5..40, 0.1 for 45..95. Deepest cut 40: (0.1)^2 everywhere = 0.01.
    # Crossing: nothing new after as_of → 8 × 0.81 + 11 × 0.01 = 6.59; / 19 = 0.346842…
    assert b["seasonal"]["brier"] == {"sale_max": 0.01, "crossing": 0.3468}
    assert b["seasonal"]["sale_max"] == [1] * 8 + [0] * 11 and b["seasonal"]["crossing"] == [0] * 19


def test_seasonal_summary_weights_games_equally():
    games = [review(A, actual(60, 20000)), review(B, actual(40, 30000, running=40))]
    s = seasonal_summary(games, SEED)
    assert s["brier"]["sale_max"]["value"] == 0.025                       # (0.04 + 0.01) / 2
    assert s["brier"]["crossing"]["value"] == 0.1934                      # (0.04 + 0.346842) / 2
    assert s["brier"]["sale_max"]["n"] == 2 and s["units"] == 38
    assert s["differs_games"] == [2]
    assert s["brier"]["crossing"]["backtest"] == 0.0604 and "backtest_source" in s["brier"]["crossing"]
    lo, hi = s["brier"]["sale_max"]["interval"]
    assert 0.01 <= lo <= 0.025 <= hi <= 0.04
    assert s["by_confidence"]["normal"] == {"games": 2, "sale_max": 0.025, "crossing": 0.1934}


def test_calibration_bins():
    s = seasonal_summary([review(A, actual(60, 20000)), review(B, actual(40, 30000, running=40))], SEED)
    bins = {row["bin"]: row for row in s["calibration"]["sale_max"]}
    # 0.1: B's 11 units, none reached; 0.2: A's 7 units, none; 0.8: A's 12, all; 0.9: B's 8, all
    assert {k: (v["units"], v["games"], v["predicted"], v["actual"]) for k, v in bins.items()} == {
        "0.1": (11, 1, 0.1, 0.0), "0.2": (7, 1, 0.2, 0.0), "0.8": (12, 1, 0.8, 1.0), "0.9": (8, 1, 0.9, 1.0)}
    assert {row["bin"]: row["actual"] for row in s["calibration"]["crossing"]}["0.9"] == 0.0


def test_the_curve_point_for_this_sale_is_found_by_season_and_year():
    game = forecast_game(1, points=(WINTER_POINT, dict(WINTER_POINT, season="autumn", label="2026 秋特",
                                                       index=2)))
    g = review(A, actual(60, 20000), game)
    assert g["seasonal"]["point"] == "2026 秋特"
    assert g["seasonal"]["probabilities"] == [min(1.0, x + 0.05) for x in SEASONAL[1]]


def test_a_curve_without_this_sale_is_not_scored():
    g = review(A, actual(60, 20000), forecast_game(1, points=(WINTER_POINT,)))
    assert g["seasonal"] is None and "沒有這一場" in g["seasonal_reason"]
    assert g["status"] == "reviewed" and g["decision"]["hit"] is True        # the decision is still compared
    assert seasonal_summary([g], SEED)["brier"]["sale_max"]["n"] == 0


def test_a_record_without_a_forecast_is_not_scored():
    g = review(decision(7, "na", status="na"), None)
    assert g["status"] == "not-scored" and g["reason"] == "無法預測"
    assert g["seasonal"] is None and g["decision"] is None


# --- decisions (T009) -----------------------------------------------------------------------------------

def test_decision_hit_and_gap():
    g = review(A, actual(60, 20000))
    assert (g["decision"]["hit"], g["decision"]["gap_cents"], g["timing"]) == (True, -5000, "on-time")
    assert (review(A, actual(50, 25000))["decision"]["hit"], review(A, actual(50, 25000))["decision"]["gap_cents"]) \
        == (True, 0)
    g = review(A, actual(33, 33400))
    assert (g["decision"]["hit"], g["decision"]["gap_cents"]) == (False, 8400)       # spec US1 scenario 2


def test_timing():
    wait = decision(3, "wait", sweet_point=WINTER_POINT)
    assert review(wait, actual(50, 25000))["timing"] == "early"
    assert review(wait, actual(30, 35000))["timing"] == "not-yet"
    assert review(B, actual(40, 30000, 40))["timing"] == "n/a"


def test_buy_now_against_the_sale():
    assert review(B, actual(40, 30000, 40))["now_vs_sale"] == {"kind": "same", "diff_cents": 0}
    assert review(B, actual(50, 25000, 40))["now_vs_sale"] == {"kind": "lower", "diff_cents": -5000}
    assert review(B, actual(30, 35000, 40))["now_vs_sale"] == {"kind": "higher", "diff_cents": 5000}
    assert review(A, actual(60, 20000))["now_vs_sale"] is None


def test_decision_summary_by_group():
    record = pre_sale_record()
    wait = decision(3, "wait", sweet_point=WINTER_POINT)
    games = [review(A, actual(60, 20000)), review(decision(5, "soon"), actual(33, 33400)),
             review(B, actual(40, 30000, 40)), review(wait, actual(50, 25000), dur=during())]
    s = decision_summary(games, record, SEED)
    soon = s["on_time"]["soon"]
    assert (soon["value"], soon["n"], soon["backtest"], soon["differs"]) == (0.5, 2, 0.924, False)
    assert s["misses"] == [{"app_id": 5, "name": "Game 5", "group": "soon", "gap_cents": 8400}]
    assert s["early"]["n"] == 1 and s["early"]["first_now"] == 1 and s["early"]["missed"] == 0
    assert s["now"] == {"n": 1, "lower": 0, "same": 1, "higher": 0, "backtest_now_deeper_within_12m": 0.444}
    assert s["counts"] == {"now": 1, "soon": 2, "wait": 1}


# --- early hits: did a record during the sale switch to buy now? (T010) ----------------------------------

def test_first_buy_now_record_during_the_sale():
    s = early_switch(3, during(), ())
    assert s == {"state": "first_now", "as_of": DURING_AS_OF[1], "file": f"{DURING_AS_OF[1]}.json.gz"}


def test_never_switched_is_missed():
    assert early_switch(3, during({3: ["wait"] * 7}), ()) == {"state": "missed", "last_group": "wait"}


def test_missing_days_make_it_unknown_not_missed():
    s = early_switch(3, during({3: ["wait"] * 7}, days=[0, 1, 2, 4, 5, 6]), ("2026-10-05",))
    assert s == {"state": "unknown", "missing_days": ["2026-10-05"]}


def test_a_record_without_the_game_is_not_buy_now():
    s = early_switch(3, during({3: [None, None, "now", "now", "now", "now", "now"]}), ())
    assert s["as_of"] == DURING_AS_OF[2]


def test_switch_is_only_reported_for_early_hits():
    wait = decision(3, "wait", sweet_point=WINTER_POINT)
    assert review(wait, actual(50, 25000), dur=during())["switch"]["state"] == "first_now"
    assert review(wait, actual(30, 35000), dur=during())["switch"] is None
    assert review(A, actual(60, 20000), dur=during())["switch"] is None


def test_the_seed_comes_from_the_record_name():
    assert seed_for(RECORD) == seed_for(RECORD) != seed_for("20260929T183000Z.json.gz")


# --- bundles (T025) --------------------------------------------------------------------------------------------

def _bundle_games():
    wait = decision(3, "wait", sweet_point=WINTER_POINT)
    return {1: review(A, actual(60, 20000)), 3: review(wait, actual(50, 25000))}


def _rows(final_cents, discount=10, days=range(7)):
    from sweetspot.store.query import OptionRecord
    from tests.review_builders import bundle_rows

    return [OptionRecord(app_id=1, checked_at=dt(t), kind="bundle", option_id=r["option_id"], name=r["name"],
                         original_cents=r["original_cents"], final_cents=r["final_cents"], position=1,
                         is_default=False, role="other-games", external_id=None, verification=None,
                         verified_at=None, reason_code=None, reason_detail=None, itad_steam_deals=None,
                         bundle_discount_pct=r["bundle_discount_pct"]) for t, r in bundle_rows(final_cents, discount, days)]


def test_bundle_advice_against_the_sale():
    from sweetspot.review.score import bundle_review
    from tests.review_builders import bundle_entry

    b = bundle_review(bundle_entry(), _rows(40500), _bundle_games(), SALE)
    # A -60% (NT$200) and C -50% (NT$250) in the sale: (20000 + 25000) × 0.9 = 40500 → NT$45 below the estimate
    assert b["scored"] and b["advice"]["kind"] == "next-sale" and b["advice"]["estimate_cents"] == 45000
    assert b["actual"] == {"min_cents": 40500, "discounts": [10], "discount_same": True, "days": 7}
    assert b["estimate_gap_cents"] == -4500
    assert b["joint_hit"] is True
    assert [(x["app_id"], x["needed_pct"], x["max_cut"], x["hit"]) for x in b["contents"]] == [
        (1, 50, 60, True), (3, 50, 50, True)]
    # separately at the sweet points: A in this sale (NT$200); C's sweet point is the winter sale → not complete
    assert b["separate_plan"] == {"cents": 20000, "complete": False, "pending": [3]}


def test_a_changed_bundle_discount_is_flagged():
    from sweetspot.review.score import bundle_review
    from tests.review_builders import bundle_entry

    rows = _rows(40500, days=[0, 1, 2]) + _rows(38250, discount=15, days=[3, 4, 5, 6])
    b = bundle_review(bundle_entry(), rows, _bundle_games(), SALE)
    assert b["actual"]["discounts"] == [10, 15] and b["actual"]["discount_same"] is False
    assert b["actual"]["min_cents"] == 38250


def test_no_daily_rows_means_no_actual_price():
    from sweetspot.review.score import bundle_review
    from tests.review_builders import bundle_entry

    b = bundle_review(bundle_entry(), [], _bundle_games(), SALE)
    assert b["actual"] is None and b["actual_reason"] == "特賣期間沒有這個組合包的每日價格紀錄"
    assert b["estimate_gap_cents"] is None and b["joint_hit"] is True     # the contents are still known


def test_a_content_without_an_actual_leaves_the_joint_hit_unknown():
    from sweetspot.review.score import bundle_review
    from tests.review_builders import bundle_entry

    games = _bundle_games()
    games[3] = review(decision(3, "wait", sweet_point=WINTER_POINT), None, tr=tracked(3, reason="價格歷史只到 2026-10-05"))
    assert bundle_review(bundle_entry(), _rows(40500), games, SALE)["joint_hit"] is None


def test_mixed_bundles_and_bundles_without_advice_are_only_listed():
    from sweetspot.review.score import bundle_review
    from tests.review_builders import bundle_entry

    mixed = bundle_review(bundle_entry(grade="mixed", kind=None), _rows(40500), _bundle_games(), SALE)
    assert not mixed["scored"] and mixed["advice"] is None and mixed["joint_hit"] is None
    assert mixed["actual"]["min_cents"] == 40500
    assert "hit_rate" not in mixed                                         # FR-012: too few for a rate


def test_buy_now_advice_compares_with_the_price_at_the_record():
    from sweetspot.review.score import bundle_review
    from tests.review_builders import bundle_entry

    b = bundle_review(bundle_entry(kind="now", price_cents=42000), _rows(40500), _bundle_games(), SALE)
    assert b["estimate_gap_cents"] == -1500 and b["joint_hit"] is None    # bought at the record: nothing to wait for


# --- non-seasonal: only periods that have ended (T027) -----------------------------------------------------------

def _ns(db_path, today, known=None):
    from sweetspot.forecast.nonseasonal.events import SeasonalWindows
    from sweetspot.review.actual import tracked_series
    from sweetspot.review.score import ns_review
    from sweetspot.store.query import PriceStore
    from tests.review_builders import default_decisions, review_db

    review_db(db_path, known=known)
    s = PriceStore.open(db_path)
    try:
        windows = SeasonalWindows.from_events(s.calendar_events())
        out = {}
        for d in default_decisions():
            if d["app_id"] in (1, 3):
                t = tracked_series(s, d, SALE, today)
                out[d["app_id"]] = ns_review(d, t.series, windows, AS_OF, today, (30, 60, 90))
        return out
    finally:
        s.close()


DUE = {30: "2026-10-30T18:31:37Z", 60: "2026-11-29T18:31:37Z", 90: "2026-12-29T18:31:37Z"}


def test_nothing_is_due_yet(db_path):
    from sweetspot.review.score import ns_summary

    got = _ns(db_path, dt("2026-10-12"))
    assert [(u["h"], u["due"], u["state"]) for u in got[3]["units"]] == [(h, DUE[h], "pending") for h in (30, 60, 90)]
    s = ns_summary([{"app_id": a, "non_seasonal": v} for a, v in got.items()], pre_sale_record(), SEED)
    assert {h: (v["scored_units"], v["games"]) for h, v in s["horizons"].items()} == {"30": (0, 0), "60": (0, 0),
                                                                                      "90": (0, 0)}
    assert s["next_due"] == DUE[30] and s["earlier"][0]["state"] == "pending"


def test_the_30_day_period_after_it_ends(db_path):
    from sweetspot.review.score import ns_summary

    got = _ns(db_path, dt("2026-11-01"), known={1: "2026-11-02"})
    c30 = got[3]["units"][0]
    # C: 0% → 50% on 10/20, outside any seasonal sale → levels 5..50 arrived
    assert c30["state"] == "scored" and c30["arrived"] == [1] * 10 + [0] * 9
    # A: the 60% at the sale start is seasonal → nothing arrived
    assert got[1]["units"][0]["arrived"] == [0] * 19
    assert [u["state"] for u in got[3]["units"][1:]] == ["pending", "pending"]
    s = ns_summary([{"app_id": a, "non_seasonal": v} for a, v in got.items()], pre_sale_record(), SEED)
    h30 = s["horizons"]["30"]
    # A: 19 × 0.04 / 19 = 0.04; C: (10 × 0.25 + 9 × 0.01) / 19 = 0.136316; mean 0.088158
    assert (h30["scored_units"], h30["games"], h30["brier"]["value"], h30["brier"]["backtest"]) == (38, 2, 0.0882, 0.1082)
    assert s["next_due"] == DUE[60]


def test_history_not_yet_known_to_the_due_date_is_pending_not_unknown(db_path):
    got = _ns(db_path, dt("2026-11-01"))
    a30 = got[1]["units"][0]
    assert a30["state"] == "pending" and a30["reason"] == "價格歷史還沒到到期日"     # A is known until 10/09


def test_the_earlier_hint_is_judged_when_its_period_ends(db_path):
    from sweetspot.review.score import ns_summary

    got = _ns(db_path, dt("2026-12-01"), known={3: "2026-12-01"})
    s = ns_summary([{"app_id": a, "non_seasonal": v} for a, v in got.items()], pre_sale_record(), SEED)
    [e] = s["earlier"]
    assert (e["app_id"], e["horizon_days"], e["state"], e["hit"], e["backtest"]) == (3, 60, "scored", True, 0.736)


def test_a_game_without_a_non_seasonal_forecast_has_no_units(db_path):
    from sweetspot.review.score import ns_review

    assert ns_review(decision(2, "now"), None, None, AS_OF, dt("2026-11-01"), (30, 60, 90)) is None


# --- recompute side by side (T031) ------------------------------------------------------------------------------

def test_recompute_side_by_side_without_a_verdict():
    from sweetspot.review.score import recompute_summary

    games = [review(A, actual(60, 20000)), review(B, actual(40, 30000, running=40)),
             review(decision(7, "na", status="na"), None)]
    same_a = forecast_game(1)
    other_b = forecast_game(2, [0.5] * 19)
    current = {"forecast": {"games": [same_a, other_b]},
               "decisions": [dict(A), dict(B, group="soon", sweet_cents=25000)]}
    baseline = {"games": [forecast_game(1, [0.6] * 19), forecast_game(2, [0.6] * 19)]}
    s = recompute_summary(games, pre_sale_record(), {"current": current, "baseline": baseline, "note": None}, SALE, SEED)
    # record: A 0.04, B 0.01 → 0.025; current: A 0.04, B 0.25 → 0.145
    # baseline 0.6 everywhere: A (12 × 0.16 + 7 × 0.36) / 19 = 0.233684; B (8 × 0.16 + 11 × 0.36) / 19 = 0.275789
    assert (s["record"]["value"], s["current"]["value"], s["baseline"]["value"]) == (0.025, 0.145, 0.2547)
    assert s["record"]["n"] == 2 and "differs" not in s["current"] and "verdict" not in s
    [d] = s["different"]
    assert (d["app_id"], d["record_group"], d["current_group"], d["record_sweet_cents"], d["current_sweet_cents"]) == (
        2, "now", "soon", 25000, 25000)
    assert d["max_probability_diff"] == 0.4 and d["reason"].startswith("分析時點以前的資料在紀錄之後有補上或修正")
    assert games[0]["recomputed"] == {"brier": {"record": 0.04, "current": 0.04, "baseline": 0.2337},
                                      "max_probability_diff": 0.0}
    # B's probabilities moved 0.4 (0.9 → 0.5); A's did not
    assert s["probability_drift"] == {"games": 2, "moved": 1, "max": 0.4}


def test_probabilities_that_drift_without_changing_the_decision_are_not_listed():
    from sweetspot.review.score import recompute_summary

    games = [review(A, actual(60, 20000))]
    drifted = forecast_game(1, [x + 0.003 for x in SEASONAL[1]])
    current = {"forecast": {"games": [drifted]}, "decisions": [dict(A)]}
    s = recompute_summary(games, pre_sale_record(), {"current": current, "baseline": {"games": [drifted]},
                                                     "note": None}, SALE, SEED)
    assert s["different"] == [] and s["probability_drift"] == {"games": 1, "moved": 1, "max": 0.003}


def test_why_a_recomputed_decision_differs():
    from sweetspot.review.score import _why_different

    assert _why_different({"version": {"itad_id": "a"}}, {"version": {"itad_id": "b"}}) == "追蹤的版本不同"
    assert _why_different({"current": {"price_cents": 1}}, {"current": {"price_cents": 2}}) == "紀錄當時的現價不同"
