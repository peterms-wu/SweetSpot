"""US2 end-to-end: mapping verification, TW + aux history, current-price cross-check."""

import io
import json
import sqlite3
from urllib.parse import parse_qs

import httpx
import pytest

from sweetspot import cli, commands
from sweetspot.config import Secret, Secrets
from tests.config_builders import TEST_TOML
from tests.conftest import FIXTURES
from tests.integration.test_update_us1 import MISSING, PRICED, FakeSteam, wishlist_payload

ITAD = FIXTURES / "itad"
IDS = json.loads((ITAD / "lookup.json").read_text(encoding="utf-8"))
APP_BY_ID = {v: int(k.split("/")[1]) for k, v in IDS.items()}


def itad_fixture(name):
    return json.loads((ITAD / name).read_text(encoding="utf-8"))


class FakeSteamAndItad(FakeSteam):
    def __init__(self):
        super().__init__()
        self.history_calls: list[tuple[int, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.isthereanydeal.com":
            self.requests.append(str(request.url))
            path, query = request.url.path, parse_qs(request.url.query.decode())
            if path == "/lookup/id/shop/61/v1":
                return httpx.Response(200, json={k: IDS.get(k) for k in json.loads(request.content)})
            if path == "/lookup/shop/61/id/v1":
                return httpx.Response(200, json=itad_fixture("reverse_lookup.json"))
            if path == "/games/history/v2":
                app, country = APP_BY_ID[query["id"][0]], query["country"][0]
                self.history_calls.append((app, country))
                name = f"history_{app}_{country}.json"
                return httpx.Response(200, json=itad_fixture(name) if (ITAD / name).exists() else [])
            if path == "/games/prices/v3":
                return httpx.Response(200, json=itad_fixture("prices_tw.json"))
            return httpx.Response(404)
        path, query = request.url.path, parse_qs(request.url.query.decode())
        if path.endswith("/GetItems/v1/") and "packageid" in query["input_json"][0]:
            self.requests.append(str(request.url))
            ids = [i["packageid"] for i in json.loads(query["input_json"][0])["ids"]]
            return httpx.Response(200, json={"response": {"store_items": [self.package_item(p) for p in ids]}})
        if path == "/api/packagedetails" and query["packageids"][0] in ("82712", "415372"):
            sub = query["packageids"][0]
            app, price = (413150, 39800) if sub == "82712" else (1145360, 46000)
            quote = self.prices[str(app)]["data"]["price_overview"]
            return httpx.Response(200, json={sub: {"success": True, "data": {"apps": [{"id": app}], "price": quote}}})
        if path == "/api/packagedetails":
            sub = query["packageids"][0]
            file = FIXTURES / "steam" / f"packagedetails_{sub}.json"
            return httpx.Response(200, json=json.loads(file.read_text(encoding="utf-8")) if file.exists()
                                  else {sub: {"success": False}})
        if path == "/api/appdetails" and query.get("filters") == ["basic"]:
            app = query["appids"][0]
            file = FIXTURES / "steam" / f"appdetails_{app}.json"
            return httpx.Response(200, json=json.loads(file.read_text(encoding="utf-8")))
        return super().__call__(request)


    def package_item(self, package_id):
        """GetItems-shaped package built from recorded packagedetails (or synthetic single-app packages)."""
        synthetic = {82712: 413150, 415372: 1145360}
        if package_id in synthetic:
            app = synthetic[package_id]
            quote = self.prices[str(app)]["data"]["price_overview"]
            return {"id": package_id, "success": 1, "included_appids": [app],
                    "best_purchase_option": {"final_price_in_cents": str(quote["final"])}}
        file = FIXTURES / "steam" / f"packagedetails_{package_id}.json"
        data = json.loads(file.read_text(encoding="utf-8"))[str(package_id)] if file.exists() else {"success": False}
        if not data.get("success"):
            return {"id": package_id, "success": 15}
        price = data["data"]["price"]
        return {"id": package_id, "success": 1, "included_appids": [a["id"] for a in data["data"]["apps"]],
                "best_purchase_option": {"final_price_in_cents": str(price["final"])}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    fake = FakeSteamAndItad()
    monkeypatch.setattr(commands, "TRANSPORT", httpx.MockTransport(fake))
    monkeypatch.setattr(commands, "SLEEP", lambda s: None)
    monkeypatch.setattr(cli, "load_secrets", lambda: Secrets(itad_api_key=Secret("test-itad-key")))
    config = tmp_path / "sweetspot.toml"
    config.write_text(TEST_TOML, encoding="utf-8")
    return fake, config, monkeypatch


def run_update(config, *extra):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(["update", "--skip-reference", "--json", "--config", str(config), *extra], stdout=out,
                    stderr=err)
    return code, json.loads(out.getvalue()) if out.getvalue() else None, err.getvalue()


def db(config):
    return sqlite3.connect(config.parent / "data" / "sweetspot.db")


def test_verified_history_is_stored_for_both_regions(env):
    fake, config, _ = env
    code, summary, _ = run_update(config)
    assert code == cli.EXIT_PARTIAL  # only the missing app is a problem
    assert [f["app_id"] for f in summary["failures"]] == [MISSING]
    assert summary["mappings"] == {"verified": 3, "rejected": 0, "reused": 0, "failed": 0}
    assert summary["history"]["fetched"] == 3
    assert summary["aux_history"] == {"fetched": 1, "reused": 0, "unavailable": 2, "failed": 0}
    counts = dict(db(config).execute(
        "SELECT region, COUNT(*) FROM price_observations WHERE app_id = 620 AND source = 'itad-history' "
        "GROUP BY region"))
    assert counts == {"TW": 19, "US": 147}
    verification = db(config).execute(
        "SELECT verification, aliases_json FROM source_mappings WHERE app_id = 620").fetchone()
    assert verification[0] == "verified" and "app/659" in verification[1]


def test_second_run_reuses_history_and_mappings(env):
    fake, config, _ = env
    run_update(config)
    calls = len(fake.history_calls)
    _, summary, _ = run_update(config)
    assert len(fake.history_calls) == calls
    assert summary["history"]["reused"] == 3 and summary["mappings"]["reused"] == 3


def test_removed_but_tracked_app_still_gets_history(env):
    fake, config, _ = env
    fake.wishlist = wishlist_payload([620, 413150])
    run_update(config)
    fake.wishlist = wishlist_payload([620])
    _, summary, _ = run_update(config)
    assert 413150 in summary["wishlist"]["removed"]
    statuses = db(config).execute(
        "SELECT r.status FROM run_item_results r WHERE app_id = 413150 "
        "AND stage = 'history-tw' ORDER BY recorded_at").fetchall()
    assert len(statuses) == 2  # processed in both runs


def test_price_checks_recorded(env):
    _, config, _ = env
    _, summary, _ = run_update(config)
    checks = db(config).execute("SELECT COUNT(*) FROM current_price_checks").fetchone()[0]
    assert checks == 3
    assert set(summary["price_checks"]) == {"match", "mismatch", "missing"}


def test_without_itad_key_history_is_disabled_but_prices_work(env):
    fake, config, monkeypatch = env
    monkeypatch.setattr(cli, "load_secrets", lambda: Secrets())
    code, summary, _ = run_update(config)
    assert summary["current_prices"]["ok"] == 3
    assert summary["history"]["disabled"] is True
    assert any("ITAD" in a for a in summary["alerts"])
    assert not any("isthereanydeal" in u for u in fake.requests)


def test_no_history_flag_skips_itad(env):
    fake, config, _ = env
    run_update(config, "--no-history")
    assert not any("isthereanydeal" in u for u in fake.requests)
