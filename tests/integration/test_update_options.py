"""feature 009: the purchase-option step of `sweetspot update` (contracts/cli-and-report.md, research R8)."""

import json
from urllib.parse import parse_qs

import httpx
import pytest

from sweetspot import cli, commands
from sweetspot.config import Secret, Secrets
from tests.config_builders import TEST_TOML
from tests.integration.test_update_us2 import db, itad_fixture, run_update
from tests.integration.test_update_versions import FakeVersions

GAME, DLC, BUNDLE, EDITION = 413150, 5002, 5001, "itad-edition-5001"
OTHER_GAME, MIXED = 1145360, 5003          # a bundle with another tracked game
STRANGER = 777001                          # feature 010: a game nobody tracks, inside bundle 5003
CONTENT_PRICES = {GAME: ("Game", 49800), OTHER_GAME: ("Other Game", 39000), STRANGER: ("Stranger", 20000)}


class FakeOptions(FakeVersions):
    """Game 413150 is also sold as bundle 5001 (the game and its DLC 5002); ITAD tracks the bundle as EDITION.
    Bundle 5003 holds two tracked games."""

    def __init__(self):
        super().__init__()
        self.edition_history: list[str] = []
        self.content_requests: list[list[int]] = []
        self.content_fails = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, query = request.url.path, parse_qs(request.url.query.decode())
        if request.url.host == "api.isthereanydeal.com":
            if path == "/lookup/id/shop/61/v1":
                keys = json.loads(request.content)
                if keys and keys[0].startswith("bundle/"):
                    self.requests.append(str(request.url))
                    return httpx.Response(200, json={k: EDITION if k == f"bundle/{BUNDLE}" else None for k in keys})
            if path == "/lookup/shop/61/id/v1" and EDITION in json.loads(request.content):
                self.requests.append(str(request.url))
                return httpx.Response(200, json={EDITION: [f"bundle/{BUNDLE}"]})
            if path == "/games/history/v2" and query["id"][0] == EDITION:
                self.edition_history.append(query["country"][0])
                rows = itad_fixture("history_cyberpunk_ultimate_TW.json") if query["country"][0] == "TW" else []
                return httpx.Response(200, json=rows)
        if path.endswith("/GetItems/v1/"):
            body = json.loads(query["input_json"][0])
            if body.get("data_request") == {"include_all_purchase_options": True}:
                response = json.loads(super().__call__(request).content)
                for item in response["response"]["store_items"]:
                    if item["appid"] == GAME:
                        item["purchase_options"].append({"bundleid": BUNDLE, "purchase_option_name": "Deluxe Bundle",
                                                         "final_price_in_cents": "49800"})
                        item["purchase_options"].append({"bundleid": MIXED, "purchase_option_name": "Two Games",
                                                         "final_price_in_cents": "97600", "bundle_discount_pct": 10,
                                                         "price_before_bundle_discount": "108800"})
                return httpx.Response(200, json=response)
            if "bundleid" in body["ids"][0]:
                self.requests.append(str(request.url))
                contents = {BUNDLE: [GAME, DLC], MIXED: [GAME, OTHER_GAME, STRANGER]}
                return httpx.Response(200, json={"response": {"store_items": [
                    {"id": i["bundleid"], "success": 1, "name": "b", "included_appids": contents[i["bundleid"]]}
                    for i in body["ids"] if i["bundleid"] in contents]}})
            if "appid" in body["ids"][0] and body.get("data_request") == {"include_basic_info": False}:
                kinds = {DLC: {"id": DLC, "appid": DLC, "success": 1, "type": 4, "related_items": {"parent_appid": GAME}},
                         OTHER_GAME: {"id": OTHER_GAME, "appid": OTHER_GAME, "success": 1, "type": 0},
                         STRANGER: {"id": STRANGER, "appid": STRANGER, "success": 1, "type": 0}}
                return httpx.Response(200, json={"response": {"store_items": [
                    kinds[i["appid"]] for i in body["ids"] if i["appid"] in kinds]}})
            if "appid" in body["ids"][0] and body.get("data_request") == {"include_basic_info": True} \
                    and body["ids"][0]["appid"] in CONTENT_PRICES:
                self.content_requests.append([i["appid"] for i in body["ids"]])
                if self.content_fails:
                    return httpx.Response(500)
                return httpx.Response(200, json={"response": {"store_items": [
                    {"id": i["appid"], "appid": i["appid"], "success": 1, "name": CONTENT_PRICES[i["appid"]][0],
                     "best_purchase_option": {"final_price_in_cents": str(CONTENT_PRICES[i["appid"]][1])}}
                    for i in body["ids"]]}})
        return super().__call__(request)


@pytest.fixture
def env(tmp_path, monkeypatch):
    fake = FakeOptions()
    monkeypatch.setattr(commands, "TRANSPORT", httpx.MockTransport(fake))
    monkeypatch.setattr(commands, "SLEEP", lambda s: None)
    monkeypatch.setattr(cli, "load_secrets", lambda: Secrets(itad_api_key=Secret("test-itad-key")))
    config = tmp_path / "sweetspot.toml"
    config.write_text(TEST_TOML, encoding="utf-8")
    return fake, config, monkeypatch


def test_update_records_every_purchase_option_and_the_edition_history(env):
    fake, config, _ = env
    code, summary, err = run_update(config)
    po = summary["purchase_options"]
    assert (po["apps"], po["options"], po["editions"], po["editions_verified"]) == (3, 5, 1, 1)
    assert po["rejected"] == [] and po["source_error"] is False
    assert {k: v for k, v in po["history"].items() if k != "seconds"} == {"tw": 1, "aux": 0, "skipped_fresh": 0,
                                                                          "failed": 0}
    assert po["specified"] == {"active": [], "fallback": [], "ignored": []}
    assert "購買選項" in err
    roles = dict(((k, o), r) for k, o, r in db(config).execute(
        "SELECT kind, option_id, role FROM purchase_options WHERE app_id = ?", (GAME,)))
    assert roles == {("sub", 82712): "default", ("bundle", BUNDLE): "edition", ("bundle", MIXED): "other-games"}
    assert fake.edition_history == ["TW"]                  # nobody chose it: no aux history (plan D2)
    stored = db(config).execute("SELECT source, COUNT(*) FROM price_observations WHERE external_id = ? GROUP BY source",
                                (EDITION,)).fetchall()
    assert stored == [("itad-option-history", 8)]
    fetches = db(config).execute("SELECT source, region FROM history_fetches WHERE external_id = ?",
                                 (EDITION,)).fetchall()
    assert fetches == [("itad-option", "TW")]


def test_the_chosen_edition_also_gets_its_aux_history(env):
    fake, config, _ = env
    config.write_text(TEST_TOML + f'{GAME} = "bundle/{BUNDLE}"\n', encoding="utf-8")
    _, summary, _ = run_update(config)
    assert sorted(fake.edition_history) == ["TW", "US"]
    active = summary["purchase_options"]["specified"]["active"]
    assert [(a["app_id"], a["option"]) for a in active] == [(GAME, f"bundle/{BUNDLE}")]


def test_second_run_reuses_fresh_edition_history(env):
    fake, config, _ = env
    run_update(config)
    _, summary, _ = run_update(config)
    assert summary["purchase_options"]["history"]["skipped_fresh"] == 1
    assert fake.edition_history == ["TW"]


def test_no_history_and_no_key_skip_the_step(env):
    _, config, monkeypatch = env
    _, summary, _ = run_update(config, "--no-history")
    assert summary["purchase_options"] == {"skipped": "no-history"}
    monkeypatch.setattr(cli, "load_secrets", lambda: Secrets())
    _, summary, _ = run_update(config)
    assert summary["purchase_options"] == {"skipped": "no-itad-key"}
    assert db(config).execute("SELECT COUNT(*) FROM purchase_options").fetchone()[0] == 0



def test_update_alerts_on_choices_it_cannot_use(env):
    _, config, _ = env
    config.write_text(TEST_TOML + f'{GAME} = "bundle/{MIXED}"\n424242 = "sub/1"\n', encoding="utf-8")
    _, summary, _ = run_update(config)
    specified = summary["purchase_options"]["specified"]
    assert [(f["app_id"], f["reason"]) for f in specified["fallback"]] == [(GAME, "not-edition")]
    assert specified["ignored"] == [{"app_id": 424242, "option": "sub/1"}]
    assert any(f"bundle/{MIXED}" in a and "改用 Steam 預設版本" in a for a in summary["alerts"])
    assert any("purchase_options.424242" in a for a in summary["alerts"])



# --- feature 010: content prices of bundles holding >= 2 wishlist games (tasks T025) ------------------------------

def contents(config, option_id):
    rows = db(config).execute("SELECT app_id, contents_json, bundle_discount_pct, before_bundle_cents "
                              "FROM purchase_options WHERE option_id = ?", (option_id,)).fetchall()
    return {r[0]: (json.loads(r[1]) if r[1] else None, r[2], r[3]) for r in rows}


def test_bundle_of_two_wishlist_games_gets_its_content_prices(env):
    fake, config, _ = env
    _, summary, _ = run_update(config)
    assert fake.content_requests == [sorted([GAME, OTHER_GAME, STRANGER])]   # one request, only bundle 5003
    mixed = contents(config, MIXED)
    items, discount, before = mixed[GAME]
    assert (discount, before) == (10, 108800)
    assert [(c["app_id"], c.get("final_cents"), c.get("name")) for c in items] == [
        (GAME, 49800, "Game"), (OTHER_GAME, 39000, "Other Game"), (STRANGER, 20000, "Stranger")]
    edition = contents(config, BUNDLE)[GAME][0]
    assert all("final_cents" not in c for c in edition)                       # not a wishlist bundle
    bundles = summary["purchase_options"]["bundles"]
    assert {k: v for k, v in bundles.items() if k != "seconds"} == {
        "wishlist_bundles": 1, "pure": 0, "mixed": 1, "contents_unknown": 0, "prices_unknown": 0,
        "check_mismatch": []}
    facts = db(config).execute("SELECT COUNT(*) FROM product_facts WHERE app_id = ?", (STRANGER,)).fetchone()[0]
    products = db(config).execute("SELECT COUNT(*) FROM products WHERE app_id = ?", (STRANGER,)).fetchone()[0]
    assert (facts, products) == (0, 0)                                        # 009 research R1


def test_a_failed_content_request_leaves_prices_unknown(env):
    fake, config, _ = env
    fake.content_fails = True
    _, summary, _ = run_update(config)
    items = contents(config, MIXED)[GAME][0]
    assert [c.get("final_cents") for c in items] == [None, None, None]
    assert summary["purchase_options"]["bundles"]["prices_unknown"] == 1
    assert any("組合包內容的現價" in a for a in summary["alerts"])
    assert summary["purchase_options"]["editions"] == 1                        # the rest of the step went on


def test_a_price_that_breaks_the_formula_is_reported(env):
    fake, config, _ = env
    CONTENT_PRICES[STRANGER] = ("Stranger", 30000)
    try:
        _, summary, _ = run_update(config)
    finally:
        CONTENT_PRICES[STRANGER] = ("Stranger", 20000)
    mismatch = summary["purchase_options"]["bundles"]["check_mismatch"]
    assert [m["id"] for m in mismatch] == [MIXED]
    assert any(f"bundle/{MIXED}" in a and "今天不給組合包建議" in a for a in summary["alerts"])
