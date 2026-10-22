"""run_decisions on a synthetic wishlist: groups, reasons, isolation, determinism (tasks T013)."""

import pytest

from sweetspot.config import Preferences
from sweetspot.decision import engine as decision_engine
from sweetspot.decision.contract import batch_to_dict
from sweetspot.decision.engine import run_decisions
from sweetspot.decision.rule import lookup_backtest
from sweetspot.forecast.models import build_model
from sweetspot.store.query import PriceStore
from tests.decision_builders import steam_current
from tests.forecast_builders import BASIC_CALENDAR, GameSpec, build_db, dt

AS_OF = dt("2025-08-01")


def sales(winter, spring, summer, regular=50000):
    return [("2024-12-11", 0, regular), ("2024-12-19T18:00", winter, regular), ("2025-01-02T18:00", 0, regular),
            ("2025-03-13T17:00", spring, regular), ("2025-03-20T17:00", 0, regular),
            ("2025-06-26T17:00", summer, regular), ("2025-07-10T17:00", 0, regular)]


@pytest.fixture
def store(db_path):
    games = [
        GameSpec(1, tw=sales(50, 50, 50), name="Soon", wishlist=True),
        GameSpec(2, tw=sales(50, 50, 50), name="Now", wishlist=True,
                 extra_tw=[steam_current(2, "2025-07-31", 20000, 50000)]),
        GameSpec(3, tw=sales(50, 50, 80), name="Wait", wishlist=True),
        GameSpec(4, tw=[("2025-04-01", 0), ("2025-06-26T17:00", 40), ("2025-07-10T17:00", 0)], name="Low",
                 wishlist=True),
        GameSpec(5, tw=[("2024-12-11", 0, 169000), ("2025-07-20", 20, 169000), ("2025-07-25", 0, 169000)],
                 regular_cents=169000, name="Pragmatic", wishlist=True),
        GameSpec(6, tw=sales(70, 70, 70, regular=30000), regular_cents=30000, name="Dying", wishlist=True,
                 extra_tw=[steam_current(6, "2025-07-31", 67000, 67000)]),
        GameSpec(7, release_date="2027-01-01", name="Future", wishlist=True),
        GameSpec(8, name="Nothing", wishlist=True),
        GameSpec(9, tw=sales(50, 50, 50, regular=51000), regular_cents=51000, name="Broken", wishlist=True),
    ]
    build_db(db_path, games, calendar=BASIC_CALENDAR)
    s = PriceStore.open(db_path)
    yield s
    s.close()


def decide_all(store, **kw):
    """The 003 combination (seasonal-freq + sweet-price 1.0.0), pinned so these scenarios outlive a model switch."""
    model = build_model("seasonal-freq", {"min_sales": 2})
    return run_decisions(store, store.wishlist_apps(), AS_OF, model, Preferences(), now=dt("2026-09-25"),
                         **{"rule": "1.0.0", **kw})


def by_app(batch):
    return {d.app_id: d for d in batch.decisions}


def test_groups_and_hand_computed_values(store):
    d = by_app(decide_all(store))
    soon = d[1]
    assert (soon.group, soon.p_min_pct, soon.gap_pp, soon.tolerance_cents) == ("soon", 50, 10, 5000)
    assert (soon.sweet_pct, soon.sweet_cents, soon.sweet_point.index) == (40, 30000, 1)
    now = d[2]
    assert now.group == "now" and now.current.price_cents == 20000 and "below-history" in now.tags
    wait = d[3]
    assert (wait.group, wait.p_min_pct, wait.gap_pp, wait.tolerance_bound) == ("wait", 80, 5, "min")
    assert (wait.sweet_pct, wait.sweet_point.index, len(wait.ladder)) == (75, 2, 2)
    assert d[4].group == "low" and d[4].confidence == "low" and d[4].horizon_points <= 4
    assert (d[7].group, d[7].status) == ("na", "unreleased")
    assert (d[8].group, d[8].status) == ("na", "no-history")


def test_zero_p_min_falls_back_and_mentions_the_non_seasonal_discount(store):
    game = by_app(decide_all(store))[5]
    assert (game.group, game.basis, game.confidence) == ("low", "no-history", "low")
    text = "\n".join(game.reasons)
    assert "過去季節特賣沒有打折" in text
    assert "季節特賣以外出現過 -20%（2025-07-20），模型不預測這類折扣" in text
    assert "只看未來 12 個月" in text


def test_regular_mismatch_converts_with_the_current_regular(store):
    game = by_app(decide_all(store))[6]
    assert game.regular_cents == 67000 and game.confidence == "low" and game.group == "low"
    assert "regular-mismatch" in game.tags
    assert "原價與價格歷史不一致（歷史 NT$300，目前 NT$670）：可能漲價，或 Steam 改賣其他版本" in "\n".join(game.reasons)


def test_reasons_cover_basis_tolerance_timing_and_the_deeper_discount_warning(store):
    text = "\n".join(by_app(decide_all(store))[3].reasons)
    assert "依本身的季節特賣紀錄" in text                         # the model's own reasons come first
    assert "長期最低價 -80%" in text
    assert "容許差距 NT$30" in text and "使用者偏好" in text and "下限" in text
    assert "甜蜜價 NT$125（-75%）" in text
    assert "累積機率第一次達到 50%" in text
    assert "長期最低價可能更低：目前的模型無法預測比過去更深的折扣" in text


def test_a_failing_game_is_isolated(store, monkeypatch):
    real = decision_engine.decide

    def flaky(**kw):
        if kw["regular_cents"] == 51000:
            raise RuntimeError("boom")
        return real(**kw)

    monkeypatch.setattr(decision_engine, "decide", flaky)
    batch = decide_all(store)
    errors = [d for d in batch.decisions if d.status == "decision-error"]
    assert len(errors) == 1 and errors[0].group == "na" and "boom" in errors[0].status_reason
    assert sum(d.group != "na" for d in batch.decisions) == 6


def test_decisions_are_deterministic(store):
    a = batch_to_dict(decide_all(store))
    b = batch_to_dict(run_decisions(store, store.wishlist_apps(), AS_OF, build_model("seasonal-freq", {"min_sales": 2}),
                                    Preferences(), now=dt("2026-10-01"), rule="1.0.0"))
    assert a["decisions"] == b["decisions"]
    assert a["official"] is False and a["comparison"] is None
    figures = lookup_backtest("1.0.0", {"name": "seasonal-freq", "version": "1.0.0",
                                        "params": {"min_sales": 2, "history": "TW"}})
    assert a["rule_backtest"] == figures and a["rule_backtest"]["hit_rate"]["low"] < 0.5


@pytest.mark.parametrize("code, note", [(None, None), (0, None), (1, "本次資料更新失敗，使用既有資料"),
                                        (2, "本次資料更新有部分項目未完成"), (3, "另一個更新正在執行，使用既有資料")])
def test_data_refresh_note(store, code, note):
    batch = decide_all(store, update_exit=code)
    assert batch.data_refresh == {"update_exit": code, "note": note}



def test_notes_and_figures_follow_the_model_and_rule(store):
    """004 research R9 (spec FR-027): the caveat comes from the model, its number from that combination's backtest."""
    old = batch_to_dict(decide_all(store))
    figures = old["rule_backtest"]
    assert figures["rule"] == "1.0.0" and figures["model"]["name"] == "seasonal-freq"
    assert old["notes"] == ["長期最低價可能更低：目前的模型無法預測比過去更深的折扣"]
    new = batch_to_dict(run_decisions(store, store.wishlist_apps(), AS_OF, build_model("seasonal-record", {}),
                                      Preferences(), rule="2.0.0"))
    if new["rule_backtest"] is None:
        assert new["notes"] == []                       # nothing to quote: no invented number
    else:
        assert new["notes"] == [f"12 個月內最低價可能更低：回測中判為現在買之後 12 個月內，仍有 "
                                f"{new['rule_backtest']['now_deeper_within_12m']:.0%} 出現更深折扣"]
    for d in new["decisions"]:
        assert "deeper-possible" not in d["tags"]
        assert not any("目前的模型無法預測" in r for r in d["reasons"])


def test_a_combination_without_a_backtest_quotes_no_figure(store, monkeypatch):
    from sweetspot.decision import rule

    monkeypatch.setattr(rule, "RULE_BACKTESTS", ())
    data = batch_to_dict(decide_all(store))
    assert data["rule_backtest"] is None
    assert data["notes"] == ["長期最低價可能更低：目前的模型無法預測比過去更深的折扣"]    # no number in it


# --- feature 005: rule 3.0.0 decisions and reasons (tasks T010; research R8, R11) --------------------------------

from dataclasses import replace as _replace  # noqa: E402

from sweetspot.decision.rule import RULE_BACKTESTS  # noqa: E402

FREQ = {"name": "seasonal-freq", "version": "1.0.0", "params": {"min_sales": 2, "history": "TW"}}


def decide_v3(store, c=20, model=None, **kw):
    model = model or build_model("seasonal-freq", {"min_sales": 2})
    return run_decisions(store, store.wishlist_apps(), AS_OF, model, Preferences(wait_cost_twd=c),
                         now=dt("2026-09-25"), rule="3.0.0", **kw)


def v3_entry(c=20):
    return {"rule": "3.0.0", "model": FREQ, "wait_cost_twd": c, "date": "2026-09-25", "region": "TW",
            "window_months": 12, "hit_rate": {"soon": 0.86, "wait": 0.8, "low": 0.1},
            "now_deeper_within_12m": 0.4, "source": "docs/model/model-definition.md"}


def test_v3_waiting_decision_and_reasons_in_order(store):
    game = by_app(decide_v3(store))[1]
    assert game.group == "soon" and game.expected is not None and game.expected.chosen
    assert game.deadline_point.index == game.expected.deadline_index
    assert game.sweet_point.index == game.expected.likely_index == 1
    assert (game.gap_pp, game.tolerance_cents, game.target_cents) == (None, None, None)
    text = game.reasons
    order = [next(i for i, r in enumerate(text) if key in r) for key in (
        "只看未來 12 個月", "等待成本 NT$20／月（使用者偏好）", "建議：目標 -", "期望比現價多省", "對照：")]
    assert order == sorted(order), text
    joined = "\n".join(text)
    assert "每多等一個月要多省 NT$20 才值得" in joined
    assert "到期沒達到時以原價計算（規則常數）" in joined
    assert "12 個月內最低價（參考）" in joined
    assert "容許差距" not in joined


def test_v3_buy_now_explains_why_waiting_does_not_pay(store):
    game = by_app(decide_v3(store))[2]               # current NT$200 = -60%, deeper than anything seen
    assert game.group == "now" and game.expected.deadline_index == 0 and game.deadline_point is None
    joined = "\n".join(game.reasons)
    assert "等下去最好的選項是" in joined and "不划算；現在買" in joined


def test_v3_special_paths_keep_the_003_reasons(store):
    d = by_app(decide_v3(store))
    no_history = "\n".join(d[5].reasons)
    assert d[5].basis == "no-history" and d[5].group == "low" and "過去季節特賣沒有打折" in no_history
    assert "季節特賣以外出現過 -20%" in no_history
    mismatch = d[6]
    assert mismatch.group == "low" and "原價與價格歷史不一致" in "\n".join(mismatch.reasons)
    assert d[4].group == "low" and "低信心" in "\n".join(d[4].reasons)


def test_v3_unknown_price_wording(store, monkeypatch):
    real = decision_engine.current_prices

    def no_price(*args, **kw):
        out = real(*args, **kw)
        return {**out, 1: _replace(out[1], price_cents=None, cut_pct=None)}

    monkeypatch.setattr(decision_engine, "current_prices", no_price)
    game = by_app(decide_v3(store))[1]
    joined = "\n".join(game.reasons)
    assert game.group != "now" and "price-unknown" in game.tags
    assert "現價未知，以原價估計，無法判斷是否現在買" in joined and "期望比原價多省" in joined


def test_v3_never_writes_minus_zero_or_new_low_for_undiscounted_games(store):
    # the current model (seasonal-record; the baseline seasonal-freq keeps its 003 wording) plus the 3.0.0 part
    for game in decide_v3(store, model=build_model("seasonal-record", {})).decisions:
        assert "-0%" not in "\n".join(game.reasons)


def test_v3_preferences_are_only_what_the_rule_uses(store):
    data = batch_to_dict(decide_v3(store))
    assert data["preferences"] == {"wait_cost_twd": 20, "soon_sales": 1}
    assert data["rule"]["version"] == "3.0.0" and data["rule"]["constants"]["miss_price"] == "regular"


def test_v3_figures_follow_the_wait_cost(store, monkeypatch):
    from sweetspot.decision import rule

    monkeypatch.setattr(rule, "RULE_BACKTESTS", (*RULE_BACKTESTS, v3_entry(20)))
    same = batch_to_dict(decide_v3(store, c=20))
    assert same["rule_backtest"]["wait_cost_twd"] == 20 and same["rule_backtest"]["hit_rate"]["soon"] == 0.86
    other = batch_to_dict(decide_v3(store, c=30))
    assert other["rule_backtest"] is None
    assert ("規則回測是以等待成本 NT$20 算的，目前設定為 NT$30，沒有對應的回測，所以不引用到價率"
            in other["notes"])


def test_v3_caveat_number_comes_from_the_v3_entry(store, monkeypatch):
    from sweetspot.decision import rule

    record = {"name": "seasonal-record", "version": "1.0.0",
              "params": {"min_sales": 1, "half_life": 2, "hazard_history": "TW+US"}}
    monkeypatch.setattr(rule, "RULE_BACKTESTS", (*RULE_BACKTESTS, {**v3_entry(20), "model": record,
                                                                    "now_deeper_within_12m": 0.377}))
    data = batch_to_dict(decide_v3(store, model=build_model("seasonal-record@1.0.0", {})))
    assert data["notes"] == ["12 個月內最低價可能更低：回測中判為現在買之後 12 個月內，仍有 38% 出現更深折扣"]


def test_lookup_ignores_the_wait_cost_for_tolerance_rules():
    assert lookup_backtest("1.0.0", FREQ) == lookup_backtest("1.0.0", FREQ, 55)
    assert all("wait_cost_twd" in entry for entry in RULE_BACKTESTS)


# --- feature 006 US3 ------------------------------------------------------------------------------------------

from tests.forecast_builders import add_version  # noqa: E402

UNCONFIRMED = "無法確認 Steam 目前賣的版本（{}），沿用這款遊戲本身的價格歷史"


@pytest.mark.parametrize("status,text", [("ambiguous", "價格和現價相同的購買選項不只一個，或一個都沒有"),
                                          ("not-in-itad", "ITAD 沒有追蹤這個購買選項")])
def test_unconfirmed_version_is_explained(db_path, store, status, text):
    add_version(db_path, 1, "2025-07-31", external_id=None, status=status)
    reasons = by_app(decide_all(store))[1].reasons
    assert UNCONFIRMED.format(text) in reasons


def test_no_record_is_noted_only_once_versions_exist(db_path, store):
    assert not any("版本紀錄" in r for r in by_app(decide_all(store))[1].reasons)     # before 006: nothing
    add_version(db_path, 2, "2025-07-31", external_id="itad-2")
    reasons = by_app(decide_all(store))[1].reasons
    assert "這個時點沒有版本紀錄，沿用這款遊戲本身的價格歷史" in reasons



def test_stopped_tracking_is_low_confidence_with_the_last_confirmation(db_path, store):
    add_version(db_path, 1, "2025-07-31", external_id="itad-1", itad_steam_deals=0)
    d = by_app(decide_all(store, rule="2.1.0"))[1]
    assert d.confidence == "low" and "history-stopped" in d.tags
    assert ("價格歷史停止更新：ITAD 在 2025-07-11 之後就沒有這個商品在 Steam 的價格，之後的特賣視為未知；決策改為低信心"
            in d.reasons)


def test_version_change_is_explained(db_path, store):
    from tests.forecast_builders import add_history

    add_history(db_path, 3, "itad-new", tw=sales(50, 60, 80), regular_cents=50000, fetched="2025-07-31")
    add_version(db_path, 3, "2025-07-31", external_id="itad-new", package_name="Wait Deluxe")
    d = by_app(decide_all(store, rule="2.1.0"))[3]
    assert ("價格歷史來自 Steam 目前預設的購買選項 Wait Deluxe（ITAD 從 2024-12-11 開始追蹤）；2025-07-31 偵測到 Steam 換了版本，"
            "舊版本的歷史不使用") in d.reasons


# --- feature 009: the other editions of each game (contracts/outputs-options.md) ------------------------------

def test_editions_are_listed_from_the_latest_purchase_options(db_path, store):
    from tests.forecast_builders import add_history, add_purchase_options
    add_purchase_options(db_path, 1, "2025-07-31", [
        dict(kind="sub", option_id=100, name="Soon", original_cents=50000, final_cents=50000, role="default"),
        dict(kind="bundle", option_id=900, name="Soon Complete", original_cents=80000, final_cents=40000,
             role="edition", external_id="itad-900", verification="verified", verified_by="version-check",
             verified_at="2025-07-31"),
        dict(kind="bundle", option_id=901, name="Soon + Other", original_cents=90000, final_cents=90000,
             role="other-games"),
        dict(kind="sub", option_id=902, name="Soon Broken", original_cents=60000, final_cents=60000, role="edition",
             external_id="itad-902", verification="rejected", verified_by="version-check", verified_at="2025-07-31",
             reason_code="bundle", reason_detail="bundle/5"),
    ])
    add_purchase_options(db_path, 2, "2025-07-31", [
        dict(kind="sub", option_id=200, name="Now", original_cents=50000, final_cents=20000, role="default")])
    add_history(db_path, 1, "itad-900", tw=[("2024-12-11", 0, 80000), ("2025-06-26T17:00", 50, 80000)],
                regular_cents=80000, fetched="2025-07-31", source="itad-option-history", fetch_source="itad-option")
    d = by_app(decide_all(store))
    editions = d[1].editions
    assert [(e["kind"], e["id"]) for e in editions] == [("bundle", 900), ("sub", 902)]
    complete, broken = editions
    assert complete["name"] == "Soon Complete" and complete["is_default"] is False
    assert (complete["price_cents"], complete["regular_cents"], complete["cut_pct"]) == (40000, 80000, 50)
    assert (complete["price_twd"], complete["regular_twd"]) == (400, 800)
    assert (complete["low_cents"], complete["low_twd"], complete["low_at"]) == (40000, 400, "2025-06-26T17:00:00Z")
    assert complete["history_start"] == "2024-12-11T00:00:00Z"
    assert complete["config_line"] == '1 = "bundle/900"' and complete["unset_hint"] is False
    assert complete["verification"] == "verified" and complete["itad_id"] == "itad-900"
    assert broken["config_line"] is None and (broken["reason_code"], broken["reason_detail"]) == ("bundle", "bundle/5")
    assert broken["low_cents"] is None and broken["history_start"] is None
    assert d[2].editions == ()                      # purchase options recorded, no other edition
    assert d[3].editions is None                    # nothing recorded for this game


def test_editions_reach_the_contract(db_path, store):
    from tests.forecast_builders import add_purchase_options
    add_purchase_options(db_path, 2, "2025-07-31", [
        dict(kind="sub", option_id=200, name="Now", original_cents=50000, final_cents=20000, role="default")])
    got = {d["app_id"]: d for d in batch_to_dict(decide_all(store))["decisions"]}
    assert got[2]["editions"] == [] and got[1]["editions"] is None



def test_a_choice_that_cannot_be_used_falls_back_with_the_reason(db_path, store):
    """Feature 009 US3: the game keeps its default forecast; version and reasons explain the fallback."""
    from tests.forecast_builders import add_purchase_options, add_version
    for app in (1, 2):                                   # the version step has run: versions are reported
        add_version(db_path, app, "2025-07-31", external_id=f"itad-{app}", package_id=100 * app)
    add_purchase_options(db_path, 1, "2025-07-31", [
        dict(kind="sub", option_id=100, name="Soon", original_cents=50000, final_cents=50000, role="default"),
        dict(kind="bundle", option_id=901, name="Soon + Other", original_cents=90000, final_cents=90000,
             role="other-games")])
    base = by_app(decide_all(store))
    got = by_app(decide_all(store, choices={1: ("bundle", 901), 2: ("sub", 5)}))
    v = got[1].version
    assert v["source"] == "user-fallback" and v["basis"] == base[1].version["basis"]
    assert v["fallback"]["code"] == "not-edition" and v["fallback"]["requested"] == {"kind": "bundle", "id": 901,
                                                                                    "name": "Soon + Other"}
    text = "指定的購買選項（Soon + Other，bundle/901）不是這款遊戲的版本（還包含其他遊戲），改用 Steam 預設版本"
    assert v["fallback"]["text"] == text and text in got[1].reasons
    assert (got[1].group, got[1].sweet_cents) == (base[1].group, base[1].sweet_cents)
    assert got[2].version["fallback"]["code"] == "no-record"


def test_a_choice_for_a_game_removed_but_still_tracked_is_not_warned(store, db_path):
    """014 T074 (009 spec Edge Case: a game removed from the wishlist but still in its tracking months keeps its
    choice, as the daily update does): report said it was outside the tracking scope and ignored."""
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE wishlist_membership SET state = 'removed_tracking' WHERE app_id = 9")
    batch = decide_all(store, choices={9: ("sub", 1), 999: ("sub", 1)})
    assert 9 not in {d.app_id for d in batch.decisions}           # not in the report: it left the wishlist
    assert batch.warnings == ("purchase_options.999：不在願望清單的追蹤範圍，已忽略",)


def test_choices_outside_the_wishlist_are_warned(store):
    batch = decide_all(store, choices={999: ("sub", 1)})
    assert batch.warnings == ("purchase_options.999：不在願望清單的追蹤範圍，已忽略",)
    assert batch_to_dict(batch)["warnings"] == ["purchase_options.999：不在願望清單的追蹤範圍，已忽略"]
