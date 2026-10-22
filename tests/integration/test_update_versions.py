"""feature 006 end-to-end: the version step of `update` (spec FR-002–FR-004, FR-011, FR-015; contracts/cli-and-report.md)."""

import json
import shutil
import sqlite3
from urllib.parse import parse_qs

import httpx
import pytest

from sweetspot import cli, commands
from sweetspot.config import Secret, Secrets
from tests.config_builders import TEST_TOML
from sweetspot.store import schema
from tests.conftest import FIXTURES
from tests.integration.test_update_us1 import PRICED
from tests.integration.test_update_us2 import IDS, FakeSteamAndItad, db, itad_fixture, run_update

PORTAL, NEW_PORTAL = 620, "itad-620-new"
PACKAGES = {620: 7877, 413150: 82712, 1145360: 415372}


class FakeVersions(FakeSteamAndItad):
    """Portal 2's default package (sub/7877) is tracked by ITAD as another product than app/620."""

    def __init__(self):
        super().__init__()
        self.itad_history_ids: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, query = request.url.path, parse_qs(request.url.query.decode())
        if request.url.host == "api.isthereanydeal.com":
            if path == "/lookup/id/shop/61/v1":
                keys = json.loads(request.content)
                if keys and keys[0].startswith("sub/"):
                    self.requests.append(str(request.url))
                    subs = {f"sub/{p}": IDS[f"app/{a}"] for a, p in PACKAGES.items()}
                    subs["sub/7877"] = NEW_PORTAL
                    return httpx.Response(200, json={k: subs.get(k) for k in keys})
            if path == "/lookup/shop/61/id/v1":
                self.requests.append(str(request.url))
                aliases = itad_fixture("reverse_lookup.json")
                aliases[NEW_PORTAL] = ["sub/7877"]
                return httpx.Response(200, json={k: aliases.get(k, []) for k in json.loads(request.content)})
            if path == "/games/history/v2":
                self.itad_history_ids.append(query["id"][0])
                if query["id"][0] == NEW_PORTAL:
                    self.requests.append(str(request.url))
                    rows = itad_fixture("history_essentials_TW.json") if query["country"][0] == "TW" else []
                    return httpx.Response(200, json=rows)
            if path == "/games/prices/v3":
                self.requests.append(str(request.url))
                prices = itad_fixture("prices_tw.json")
                prices.append({"id": NEW_PORTAL, "deals": [{"shop": {"id": 61}, "price": {"amountInt": 18800, "currency": "TWD"},
                                                             "regular": {"amountInt": 18800, "currency": "TWD"}, "cut": 0}]})
                return httpx.Response(200, json=prices)
        if path.endswith("/GetItems/v1/"):
            body = json.loads(query["input_json"][0])
            if body.get("data_request") == {"include_all_purchase_options": True}:
                self.requests.append(str(request.url))
                items = []
                for ref in body["ids"]:
                    app = ref["appid"]
                    quote = (self.prices.get(str(app)) or {}).get("data", {}).get("price_overview")
                    options = [{"packageid": PACKAGES[app], "purchase_option_name": f"Package of {app}",
                                "final_price_in_cents": str(quote["final"]),
                                "original_price_in_cents": str(quote["initial"])}] if quote and app in PACKAGES else []
                    items.append({"id": app, "appid": app, "success": 1, "purchase_options": options})
                return httpx.Response(200, json={"response": {"store_items": items}})
            if body.get("data_request") == {"include_basic_info": False} and "appid" in body["ids"][0]:
                return httpx.Response(200, json={"response": {"store_items": []}})
        return super().__call__(request)


@pytest.fixture
def env(tmp_path, monkeypatch):
    fake = FakeVersions()
    monkeypatch.setattr(commands, "TRANSPORT", httpx.MockTransport(fake))
    monkeypatch.setattr(commands, "SLEEP", lambda s: None)
    monkeypatch.setattr(cli, "load_secrets", lambda: Secrets(itad_api_key=Secret("test-itad-key")))
    config = tmp_path / "sweetspot.toml"
    config.write_text(TEST_TOML, encoding="utf-8")
    return fake, config, monkeypatch


def test_version_step_switches_portal_to_its_default_package_product(env):
    fake, config, _ = env
    code, summary, err = run_update(config)
    versions = summary["versions"]
    assert versions["checked"] == 3 and versions["unchanged"] == 2 and versions["source_error"] is False
    assert versions["changed"] == [{"app_id": PORTAL, "name": "Portal 2", "from": "Portal 2", "to": "Package of 620"}]
    assert any("改用 Package of 620 的價格歷史" in a for a in summary["alerts"])
    assert "版本" in err
    rows = db(config).execute("SELECT app_id, status, package_id, external_id, verification, verified_by "
                              "FROM app_versions ORDER BY app_id").fetchall()
    assert rows == [(620, "ok", 7877, NEW_PORTAL, "verified", "version-check"),
                    (413150, "ok", 82712, IDS["app/413150"], "verified", "own-mapping"),
                    (1145360, "ok", 415372, IDS["app/1145360"], "verified", "own-mapping")]
    assert IDS["app/620"] not in fake.itad_history_ids          # the old product is no longer fetched
    tagged = dict(db(config).execute("SELECT region, COUNT(*) FROM price_observations WHERE app_id = 620 AND "
                                     "external_id = ? GROUP BY region", (NEW_PORTAL,)))
    assert tagged == {"TW": 23}
    check = db(config).execute("SELECT external_id, itad_steam_deals FROM current_price_checks WHERE app_id = 620"
                               ).fetchone()
    assert check == (NEW_PORTAL, 1)


def test_second_run_records_no_new_change(env):
    _, config, _ = env
    run_update(config)
    _, summary, _ = run_update(config)
    assert summary["versions"]["changed"] == [] and summary["versions"]["unchanged"] == 3
    verified_by = db(config).execute("SELECT verified_by FROM app_versions WHERE app_id = 620 ORDER BY checked_at"
                                     ).fetchall()
    assert [v[0] for v in verified_by] == ["version-check", "cached"]


def test_no_history_skips_the_version_step(env):
    _, config, _ = env
    _, summary, _ = run_update(config, "--no-history")
    assert summary["versions"] == {"skipped": "no-history"}
    assert db(config).execute("SELECT COUNT(*) FROM app_versions").fetchone()[0] == 0


def test_without_itad_key_the_version_step_is_skipped_with_an_alert(env):
    _, config, monkeypatch = env
    monkeypatch.setattr(cli, "load_secrets", lambda: Secrets())
    _, summary, _ = run_update(config)
    assert summary["versions"] == {"skipped": "no-itad-key"}
    assert "未設定 ITAD_API_KEY：版本步驟略過，沿用上一次的版本" in summary["alerts"]


def test_a_v2_database_is_upgraded_on_the_first_update(env):
    _, config, _ = env
    data = config.parent / "data"
    data.mkdir(exist_ok=True)
    conn = sqlite3.connect(data / "sweetspot.db")
    conn.executescript((FIXTURES / "schema_v2.sql").read_text(encoding="utf-8"))
    conn.close()
    _, _, err = run_update(config)
    assert f"資料庫升級到 v{schema.SCHEMA_VERSION}：已備份 sweetspot.db.bak-v2" in err   # v2 -> ... -> latest in one run
    assert (data / "sweetspot.db.bak-v2").exists()
    _, _, err = run_update(config)
    assert "資料庫升級" not in err
