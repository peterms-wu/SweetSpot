"""feature 010: bundles holding several wishlist games (research R1, R3, R4; data-model §2; tasks T014-T017)."""

from dataclasses import replace

import pytest

from sweetspot.decision import bundles
from sweetspot.decision.contract import na_decision
from tests.decision_builders import (AS_OF, bundle_record, dave_miside, decision, e33_dispatch, make_forecast)
from tests.forecast_builders import dt


def build(decisions, forecasts, records, *, specified=(), names=None, as_of=AS_OF):
    by_app = {}
    for r in records:
        by_app.setdefault(r.app_id, []).append(r)
    return bundles.build_bundles(by_app, decisions, forecasts, as_of=as_of, names=names or {},
                                 specified=set(specified))


def only(block):
    assert len(block.bundles) == 1
    return block.bundles[0]


# --- T014: which bundles count, grades and roles --------------------------------------------------------------

def test_a_bundle_seen_from_both_games_is_listed_once():
    ds, fs, rec = e33_dispatch()
    block = build(ds, fs, [rec, replace(rec, app_id=2592160)])
    b = only(block)
    assert (b["id"], b["grade"]) == (74895, "pure")
    assert block.per_app == {1903340: [74895], 2592160: [74895]}


def test_one_wishlist_game_is_not_enough():
    ds, fs, _ = e33_dispatch()
    rec = bundle_record(1903340, 53645, [(1903340, None, None), (504230, 0, None)], final_cents=122300)
    block = build(ds, fs, [rec])
    assert block.bundles == [] and block.per_app == {1903340: [], 2592160: []}


def test_roles_and_mixed_grade():
    ds, fs, _ = e33_dispatch()
    rec = bundle_record(1903340, 1, [(1903340, None, None), (2592160, 0, None), (777, 0, None, 30000),
                                     (888, 4, 1903340, 15000), (999, 11, 12345, 5000)], final_cents=200000)
    b = only(build(ds, fs, [rec], names={777: "Other Game"}))
    assert [(c["app_id"], c["role"]) for c in b["contents"]] == [
        (1903340, "wishlist"), (2592160, "wishlist"), (777, "other-game"), (888, "wishlist-dlc"), (999, "other")]
    assert b["grade"] == "mixed" and b["advice"] is None and b["plan"] is None
    assert (b["extra_games"], b["extra_dlc"]) == (1, 2)
    assert b["extra_game_names"] == ["Other Game"]


def test_dlc_of_a_wishlist_game_keeps_the_bundle_pure_but_it_has_no_forecast():
    ds, fs, _ = e33_dispatch()
    rec = bundle_record(1903340, 2, [(1903340, None, None), (2592160, 0, None), (888, 4, 2592160, 9000)],
                        final_cents=130000)
    b = only(build(ds, fs, [rec]))
    assert b["grade"] == "pure"
    assert (b["advice"]["status"], b["advice"]["reason_code"]) == ("none", "no-forecast")


def test_unknown_contents_are_counted_not_listed():
    ds, fs, rec = e33_dispatch()
    block = build(ds, fs, [replace(rec, contents=None), replace(rec, app_id=2592160, contents=None)])
    assert block.bundles == [] and block.contents_unknown == 1


def test_a_game_off_the_wishlist_turns_a_pure_bundle_mixed():
    ds, fs, _ = e33_dispatch()
    rec = bundle_record(1903340, 3, [(1903340, None, None), (2592160, 0, None), (1868140, 0, None, 35000)],
                        final_cents=150000)
    b = only(build(ds, fs, [rec]))                      # 1868140 has no decision: not on the wishlist
    assert b["grade"] == "mixed" and b["extra_games"] == 1


# --- T015: the formula check ----------------------------------------------------------------------------------

def test_real_pair_passes_the_check_within_rounding():
    ds, fs, rec = e33_dispatch()
    b = only(build(ds, fs, [rec]))
    assert b["check"]["status"] == "ok" and b["check"]["expected_cents"] == 115020 and b["check"]["text"] is None


@pytest.mark.parametrize("price,prices,discount,status", [
    (10200, [5000, 6111], 10, "ok"),            # expected 10,000: tolerance NT$2
    (10201, [5000, 6111], 10, "mismatch"),
    (101000, [55556, 55555], 10, "ok"),         # expected 100,000: tolerance 1%
    (101001, [55556, 55555], 10, "mismatch"),
    (10000, [5000, None], 10, "unknown"),       # a content price unknown
    (10000, [5000, 6111], None, "unknown"),     # bundle discount unknown (a v4 row)
])
def test_check_tolerance(price, prices, discount, status):
    assert bundles.check_formula(price, discount, prices)["status"] == status


def test_mismatch_stops_the_advice_and_says_why():
    ds, fs, rec = e33_dispatch()
    b = only(build(ds, fs, [replace(rec, final_cents=120000)]))
    assert b["check"]["status"] == "mismatch" and "NT$1,200" in b["check"]["text"]
    assert (b["advice"]["status"], b["advice"]["reason_code"]) == ("none", "check-mismatch")


# --- T016: the separate plan, the cheapest combination, research R0.3 -----------------------------------------

def test_e33_dispatch_reproduces_research():
    ds, fs, rec = e33_dispatch()
    b = only(build(ds, fs, [rec]))
    assert (b["separate_cents"], b["wishlist_cents"], b["price_cents"]) == (127800, 127800, 115000)
    assert b["plan"]["cents"] == 113160 and b["plan"]["latest_point"]["index"] == 2       # 790 now + 342 winter
    a = b["advice"]
    assert (a["status"], a["kind"], a["estimate_cents"], a["saving_cents"], a["timing"]) == (
        "ok", "next-sale", 106272, 6888, "earlier")
    assert a["joint_probability"] == pytest.approx(0.826 * 0.881, abs=1e-6)
    assert [(x["app_id"], x["pct"], x["cents"]) for x in a["levels"]] == [(1903340, 20, 79040), (2592160, 20, 39040)]
    assert a["sale"]["index"] == 1 and a["hit_rate"]["bin"] == [0.7, 0.8] and a["hit_rate"]["observed"] == 0.83
    assert a["confidence"] == "normal"


def test_dave_miside_reproduces_research():
    ds, fs, rec = dave_miside()
    a = only(build(ds, fs, [rec]))["advice"]
    assert (a["kind"], a["estimate_cents"], a["saving_cents"], a["timing"]) == ("next-sale", 36621, 4069, "same")
    assert [x["pct"] for x in a["levels"]] == [45, 20] and a["hit_rate"]["bin"] == [0.5, 0.6]


def rows(spec):
    return list(make_forecast(1, spec=spec).probabilities[0])


def test_cheapest_may_leave_a_game_undiscounted_and_accepts_exactly_half():
    got = bundles.cheapest_combination([(10000, rows({50: 0.5})), (10000, rows({}))])
    assert (got.levels, got.joint) == ((50, 0), 0.5)


def test_cheapest_breaks_price_ties_by_the_higher_probability():
    got = bundles.cheapest_combination([(10000, rows({10: 0.8})), (10000, rows({10: 0.6}))])
    assert (got.levels, got.cents) == ((10, 0), 19000)


def test_cheapest_with_three_games():
    got = bundles.cheapest_combination([(10000, rows({10: 0.8}))] * 3)
    assert got.levels == (10, 10, 10) and got.joint == pytest.approx(0.512)


def test_estimate_rounds_half_up_in_cents():
    assert bundles.bundle_price(12345, 10) == 11111          # 11,110.5 cents


# --- T017: the advice -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("price,plan,latest,estimate,kind", [
    (40000, 40690, 1, 36621, "now"),
    (55600, 40690, 1, 40690, "next-sale"),           # estimate = plan: not higher, so the bundle
    (55600, 40690, 1, 40691, "separately"),          # clarify Q2: no tolerance
    (55600, 40690, 0, 30000, "separately"),          # clarify Q1: every game is 現在買, no later sale
])
def test_advice_branches(price, plan, latest, estimate, kind):
    assert bundles.choose(price, plan, latest, estimate) == kind


def test_now_advice_text_and_fields():
    """Both games are already at their sweet prices: the bundle takes another 10% off the plan."""
    _, fs, rec = dave_miside()
    ds = [decision(1868140, "now", name="DAVE THE DIVER", regular=35000, current=17500, sweet_pct=45, p_min_pct=55),
          decision(2527500, "now", name="MiSide", regular=26800, current=21440, sweet_pct=20, p_min_pct=30)]
    b = only(build(ds, fs, [replace(rec, final_cents=35046)]))
    a = b["advice"]
    assert b["plan"] == {"cents": 38940, "twd": 389, "latest_point": None}
    assert (a["kind"], a["saving_cents"], a["timing"], a["hit_rate"]) == ("now", 3894, "now", None)
    assert "現在買組合包" in a["text"] and "NT$350" in a["text"]


def test_next_sale_text_quotes_the_hit_rate_and_timing():
    ds, fs, rec = e33_dispatch()
    text = only(build(ds, fs, [rec]))["advice"]["text"]
    assert "2026 秋特買組合包" in text and "NT$1,063" in text and "73%" in text and "83%" in text
    assert "便宜 NT$69" in text and "早 1 場" in text


def test_separately_text_keeps_the_bundle_discount():
    ds, fs, rec = dave_miside()
    low = {k: make_forecast(k, spec={5: 0.9}, regular_cents=f.regular_price_cents) for k, f in fs.items()}
    a = only(build(ds, low, [rec]))["advice"]
    assert (a["kind"], a["saving_cents"], a["timing"]) == ("separately", None, None)
    assert "分開買較划算" in a["text"] and "10%" in a["text"]


def test_low_confidence_is_marked():
    ds, fs, rec = e33_dispatch()
    fs = {**fs, 2592160: replace(fs[2592160], confidence="low")}
    assert only(build(ds, fs, [rec]))["advice"]["confidence"] == "low"
    ds2 = [ds[0], replace(ds[1], group="low")]
    assert only(build(ds2, e33_dispatch()[1], [rec]))["advice"]["confidence"] == "low"


def reason(block):
    a = only(block)["advice"]
    assert a["status"] == "none" and a["kind"] is None and a["reason_text"]
    return a["reason_code"]


def test_every_reason_for_no_advice():
    ds, fs, rec = e33_dispatch()
    assert reason(build(ds, fs, [rec], specified={2592160})) == "specified"
    na = [ds[0], na_decision(2592160, "Dispatch", "insufficient-history", "沒有價格歷史")]
    assert reason(build(na, fs, [rec])) == "no-forecast"
    stale = [ds[0], replace(ds[1], current=replace(ds[1].current, stale=True))]
    assert reason(build(stale, fs, [rec])) == "stale-price"
    assert reason(build(ds, fs, [replace(rec, bundle_discount_pct=None)])) == "check-unknown"
    assert reason(build(ds, fs, [replace(rec, final_cents=120000)])) == "check-mismatch"
    assert reason(build(ds, fs, [rec], as_of=dt("2024-06-01"))) == "no-sale"      # next sale over 12 months away


def test_one_failing_bundle_does_not_hide_the_others(monkeypatch):
    ds1, fs1, rec1 = e33_dispatch()
    ds2, fs2, rec2 = dave_miside()
    original = bundles._advise

    def flaky(item, *args, **kw):
        if item["id"] == 74895:
            raise RuntimeError("boom")
        return original(item, *args, **kw)

    monkeypatch.setattr(bundles, "_advise", flaky)
    block = build(ds1 + ds2, {**fs1, **fs2}, [rec1, rec2])
    by_id = {b["id"]: b["advice"] for b in block.bundles}
    assert (by_id[74895]["status"], by_id[74895]["reason_code"]) == ("none", "error")
    assert by_id[77855]["status"] == "ok"
    assert [b["id"] for b in block.bundles] == [74895, 77855]        # pure first, then by id


def test_contents_carry_prices_and_the_specified_flag():
    ds, fs, rec = e33_dispatch()
    b = only(build(ds, fs, [rec], specified={1903340}))
    assert [(c["price_cents"], c["price_twd"], c["specified"]) for c in b["contents"]] == [
        (79000, 790, True), (48800, 488, False)]
    assert b["owned_note"] and b["discount_pct"] == 10 and b["price_twd"] == 1150


# --- T026: mixed bundles ------------------------------------------------------------------------------------------

def test_mixed_bundle_compares_with_the_wishlist_games_only():
    ds, fs, _ = e33_dispatch()
    rec = bundle_record(1903340, 7, [(1903340, None, None, 79000), (2592160, 0, None, 48800), (777, 0, None, 30000),
                                     (888, 4, 777, 12000)], final_cents=153000, discount=10)
    b = only(build(ds, fs, [rec], names={777: "Other"}))
    assert (b["separate_cents"], b["wishlist_cents"], b["extra_cents"]) == (169800, 127800, 25200)
    assert b["check"]["status"] == "ok" and b["check"]["expected_cents"] == 152820
    assert (b["extra_games"], b["extra_dlc"], b["extra_game_names"]) == (1, 1, ["Other"])


def test_mixed_bundle_with_an_unknown_content_price():
    ds, fs, _ = e33_dispatch()
    rec = bundle_record(1903340, 8, [(1903340, None, None), (2592160, 0, None), (777, 0, None, None)],
                        final_cents=140000)
    b = only(build(ds, fs, [rec]))
    assert b["separate_cents"] is None and b["wishlist_cents"] == 127800 and b["extra_cents"] == 12200
    assert b["check"]["status"] == "unknown"


def test_a_recorded_content_name_is_used_when_the_store_has_none():
    ds, fs, _ = e33_dispatch()
    rec = bundle_record(1903340, 9, [(1903340, None, None), (2592160, 0, None), (888, 11, 777, 5000)],
                        final_cents=120000)
    rec.contents[2]["name"] = "Original Soundtrack"
    b = only(build(ds, fs, [rec], names={888: None}))
    assert b["contents"][2]["name"] == "Original Soundtrack"
