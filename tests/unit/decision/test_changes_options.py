"""feature 009: version changes carry their cause (contracts/outputs-options.md, tasks T051)."""

from sweetspot.decision.changes import compare

STANDARD = {"kind": "sub", "id": 367653, "name": "Cyberpunk 2077"}
ULTIMATE = {"kind": "bundle", "id": 32470, "name": "終極版"}


def version(source, option, *, basis="version", itad="itad-std", package_id=367653, fallback=None, change=None):
    return {"basis": basis, "source": source, "option": option, "package_id": package_id,
            "package_name": option["name"] if option else None, "itad_id": itad, "own_itad_id": "itad-std",
            "fallback": fallback, "change": change}


def decision(v, group="wait", sweet=480):
    return {"app_id": 1, "name": "Cyberpunk 2077", "group": group, "sweet_point": {"label": "2026 冬特"},
            "sweet_twd": sweet, "version": v}


def contract(d):
    return {"decisions": [d], "forecast": {"model": {"name": "m", "version": "1", "params": {}}},
            "rule": {"name": "sweet-price", "version": "2.1.0"}, "preferences": {}}


def change_of(old, new):
    changes, _ = compare(contract(new), contract(old))
    return changes[1]


def test_choosing_an_edition():
    old = decision(version("steam-default", STANDARD))
    new = decision(version("user", ULTIMATE, basis="user", itad="itad-ult", package_id=None), sweet=772)
    c = change_of(old, new)
    assert c["version"] == {"from": "Cyberpunk 2077", "to": "終極版", "detected_at": None, "cause": "user"}
    assert c["sweet_twd"] == {"from": 480, "to": 772}              # the usual "last time" still shows


def test_unsetting_the_choice():
    old = decision(version("user", ULTIMATE, basis="user", itad="itad-ult", package_id=None))
    new = decision(version("steam-default", STANDARD))
    assert change_of(old, new)["version"]["cause"] == "unset"


def test_a_choice_that_stops_working():
    old = decision(version("user", ULTIMATE, basis="user", itad="itad-ult", package_id=None))
    new = decision(version("user-fallback", STANDARD, fallback={"code": "not-offered", "text": "…"}))
    got = change_of(old, new)["version"]
    assert (got["cause"], got["from"], got["to"]) == ("fallback", "終極版", "Cyberpunk 2077")


def test_steam_switching_its_default_keeps_the_006_marker():
    old = decision(version("steam-default", STANDARD))
    new = decision(version("steam-default", {"kind": "sub", "id": 1, "name": "Essentials"}, itad="itad-new",
                           package_id=1, change={"detected_at": "2026-09-27T01:00:00Z"}))
    got = change_of(old, new)["version"]
    assert got == {"from": "Cyberpunk 2077", "to": "Essentials", "detected_at": "2026-09-27T01:00:00Z",
                   "cause": "steam"}


def test_same_choice_again_is_no_change():
    v = version("user", ULTIMATE, basis="user", itad="itad-ult", package_id=None)
    assert change_of(decision(v), decision(v)) is None


def test_a_record_before_009_counts_its_package_as_the_option():
    old = decision({k: v for k, v in version("steam-default", STANDARD).items() if k not in ("source", "option",
                                                                                            "fallback")})
    assert change_of(old, decision(version("steam-default", STANDARD))) is None
    new = decision(version("user", ULTIMATE, basis="user", itad="itad-ult", package_id=None))
    assert change_of(old, new)["version"]["cause"] == "user"


def test_only_the_package_changing_on_the_same_product_is_no_change():
    old = decision(version("steam-default", STANDARD))
    new = decision(version("steam-default", {"kind": "sub", "id": 999, "name": "Cyberpunk 2077"}, package_id=999))
    assert change_of(old, new) is None
