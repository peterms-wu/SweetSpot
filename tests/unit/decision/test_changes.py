"""Changes against the comparison baseline (tasks T024; research R7; FR-019 to FR-021; SC-005)."""

import copy

from sweetspot.decision.changes import compare


def game(app_id, group="wait", label="2027 春特", twd=300):
    return {"app_id": app_id, "group": group, "sweet_point": None if group == "na" else {"label": label},
            "sweet_twd": None if group == "na" else twd}


def contract(*games, rule="1.0.0", model=("seasonal-freq", "1.0.0", {"min_sales": 2}), prefs=None):
    return {"rule": {"name": "sweet-price", "version": rule},
            "forecast": {"model": {"name": model[0], "version": model[1], "params": model[2]}},
            "preferences": prefs or {"gap_pp_deep": 5, "soon_sales": 1}, "decisions": list(games)}


def test_three_kinds_of_change_with_previous_values():
    old = contract(game(1, "wait", "2027 春特", 300), game(2))
    new = contract(game(1, "soon", "2026 冬特", 280), game(2))
    changes, comparison = compare(new, old, file="20260924T010000Z.json.gz", as_of="2026-09-24T01:00:00Z")
    assert changes[1] == {"group": {"from": "wait", "to": "soon"},
                          "sweet_point": {"from": "2027 春特", "to": "2026 冬特"},
                          "sweet_twd": {"from": 300, "to": 280}}
    assert changes[2] is None                                            # no false positives
    assert comparison == {"baseline": {"file": "20260924T010000Z.json.gz", "as_of": "2026-09-24T01:00:00Z"},
                          "version_changes": [], "skipped_records": [], "changed_games": 1, "calendar_changes": []}


def test_buy_now_timing_is_now():
    changes, _ = compare(contract(game(1, "now", "2027 春特")), contract(game(1, "wait", "2027 春特")),
                         file="f", as_of="a")
    assert changes[1]["sweet_point"] == {"from": "2027 春特", "to": "現在"}


def test_single_changes_and_na():
    changes, comparison = compare(
        contract(game(1, twd=299), game(2, label="2027 夏特"), game(3, "na"), game(4)),
        contract(game(1, twd=300), game(2), game(3), game(4, "na")), file="f", as_of="a")
    assert changes[1] == {"group": None, "sweet_point": None, "sweet_twd": {"from": 300, "to": 299}}
    assert changes[2] == {"group": None, "sweet_point": {"from": "2027 春特", "to": "2027 夏特"}, "sweet_twd": None}
    assert changes[3] == {"group": {"from": "wait", "to": "na"}, "sweet_point": None, "sweet_twd": None}
    assert changes[4] == {"group": {"from": "na", "to": "wait"}, "sweet_point": None, "sweet_twd": None}
    assert comparison["changed_games"] == 4


def test_game_missing_from_the_baseline_has_no_change():
    changes, comparison = compare(contract(game(1), game(9)), contract(game(1)), file="f", as_of="a")
    assert changes[9] is None and comparison["changed_games"] == 0


def test_no_baseline():
    changes, comparison = compare(contract(game(1)), None, skipped=["bad.json.gz"])
    assert changes == {1: None}
    assert comparison == {"baseline": None, "version_changes": [], "skipped_records": ["bad.json.gz"],
                          "changed_games": 0, "calendar_changes": []}


def test_version_and_preference_changes_are_listed():
    old = contract(game(1))
    new = copy.deepcopy(contract(game(1), rule="1.1.0", model=("seasonal-freq", "1.1.0", {"min_sales": 3}),
                                 prefs={"gap_pp_deep": 10, "soon_sales": 1}))
    _, comparison = compare(new, old, file="f", as_of="a")
    assert comparison["version_changes"] == [
        "模型 seasonal-freq 1.0.0 {min_sales=2} → seasonal-freq 1.1.0 {min_sales=3}",
        "規則 sweet-price 1.0.0 → 1.1.0",
        "偏好 gap_pp_deep 5 → 10",
    ]


# --- feature 005: waiting cost wording, shared preference keys only (tasks T006) --------------------------------

V2_PREFS = {"gap_pp_shallow": 10, "gap_pp_deep": 5, "gap_boundary_pct": 75, "tolerance_min_twd": 30,
            "tolerance_max_twd": 100, "soon_sales": 1}


def test_wait_cost_change_is_worded_in_ntd():
    old = contract(game(1), rule="3.0.0", prefs={"wait_cost_twd": 20, "soon_sales": 1})
    new = contract(game(1), rule="3.0.0", prefs={"wait_cost_twd": 30, "soon_sales": 1})
    _, comparison = compare(new, old, file="f", as_of="a")
    assert comparison["version_changes"] == ["等待成本從 NT$20 改成 NT$30"]


def test_rule_switch_lists_only_the_rule_not_unrelated_preferences():
    old = contract(game(1, "wait"), rule="2.0.0", prefs=V2_PREFS)
    new = contract(game(1, "soon"), rule="3.0.0", prefs={"wait_cost_twd": 20, "soon_sales": 1})
    changes, comparison = compare(new, old, file="f", as_of="a")
    assert comparison["version_changes"] == ["規則 sweet-price 2.0.0 → 3.0.0"]
    assert changes[1]["group"] == {"from": "wait", "to": "soon"}



# --- feature 006 ------------------------------------------------------------------------------------------------

def versioned(app_id, itad, title, own="itad-own", detected="2026-09-27T01:00:00Z"):
    g = game(app_id)
    g["version"] = {"basis": "version", "itad_id": itad, "own_itad_id": own, "package_name": title,
                    "change": {"to_itad_id": itad, "to_title": title, "detected_at": detected}}
    return g


def test_a_new_itad_product_is_a_version_change():
    old = versioned(1, "itad-a", "Standard")
    new = versioned(1, "itad-b", "Essentials")
    changes, comparison = compare(contract(new), contract(old), file="f", as_of="a")
    assert changes[1]["version"] == {"from": "Standard", "to": "Essentials", "detected_at": "2026-09-27T01:00:00Z",
                                     "cause": "steam"}                 # feature 009 adds the cause
    assert comparison["changed_games"] == 1


def test_an_old_record_without_versions_compares_with_the_apps_own_product():
    old = game(1)
    old["name"] = "Dying Light"
    new = versioned(1, "itad-b", "Essentials")
    new["name"] = "Dying Light"
    changes, _ = compare(contract(new), contract(old), file="f", as_of="a")
    assert changes[1]["version"]["from"] == "Dying Light"
    same = versioned(1, "itad-own", "Dying Light")
    assert compare(contract(same), contract(old), file="f", as_of="a")[0][1] is None


def test_same_product_is_no_version_change():
    changes, _ = compare(contract(versioned(1, "itad-a", "A")), contract(versioned(1, "itad-a", "A")),
                         file="f", as_of="a")
    assert changes[1] is None


# --- feature 012: sale dates that became official or moved (research R6; FR-015) ---------------------------------

def timed(app_id, label, status, start, end, group="wait"):
    return {"app_id": app_id, "group": group, "sweet_twd": 300,
            "sweet_point": {"label": label, "status": status, "start": start, "end": end}}


WINTER = ("2026-12-17T18:00:00Z", "2027-01-04T18:00:00Z")
SPRING = ("2027-03-18T17:00:00Z", "2027-03-25T17:00:00Z")
SPRING_LATER = ("2027-03-25T17:00:00Z", "2027-04-01T17:00:00Z")


def test_estimate_became_official():
    old = contract(timed(1, "2026 冬特", "estimated", *WINTER), timed(2, "2026 冬特", "estimated", *WINTER))
    new = contract(timed(1, "2026 冬特", "announced", *WINTER), timed(2, "2026 冬特", "announced", *WINTER))
    changes, comparison = compare(new, old, file="f", as_of="a")
    assert comparison["calendar_changes"] == ["2026 冬特 預估 → 官方（太平洋時間 12/17–1/4）"]   # one line per sale
    assert changes == {1: None, 2: None}                                   # per-game changes are unaffected


def test_official_dates_moved():
    old = contract(timed(1, "2027 春特", "announced", *SPRING))
    new = contract(timed(1, "2027 春特", "announced", *SPRING_LATER))
    _, comparison = compare(new, old, file="f", as_of="a")
    assert comparison["calendar_changes"] == ["2027 春特 官方日期 3/18–3/25 → 3/25–4/1（太平洋時間）"]


def test_no_calendar_change():
    same = contract(timed(1, "2027 春特", "announced", *SPRING))
    assert compare(same, copy.deepcopy(same), file="f", as_of="a")[1]["calendar_changes"] == []
    estimated = contract(timed(1, "2027 春特", "estimated", *SPRING))
    assert compare(estimated, estimated, file="f", as_of="a")[1]["calendar_changes"] == []
    assert compare(same, None)[1]["calendar_changes"] == []                 # no baseline
    other_sale = contract(timed(1, "2027 夏特", "announced", *SPRING))
    assert compare(same, other_sale, file="f", as_of="a")[1]["calendar_changes"] == []


def test_baseline_without_dates_can_still_be_compared():
    old = contract(game(1, "wait", "2027 春特"))                               # an old record: label only
    new = contract(timed(1, "2027 春特", "announced", *SPRING))
    assert compare(new, old, file="f", as_of="a")[1]["calendar_changes"] == []
