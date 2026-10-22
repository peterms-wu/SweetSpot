"""SC-008: API keys never reach the database, logs or command output — even when requests fail."""

import io
import json
from urllib.parse import parse_qs

import httpx
import pytest

from sweetspot import cli, commands
from sweetspot.config import Secret, Secrets
from tests.config_builders import TEST_TOML
from tests.integration.test_update_us2 import FakeSteamAndItad

ITAD_KEY = "itad-FAKE-KEY-5f3c9a1b77"
STEAM_KEY = "steam-FAKE-KEY-0e4d2c8b19"


class LeakySteam(FakeSteamAndItad):
    """Fails the keyed calls so their URLs end up in error messages, alerts and logs."""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        query = parse_qs(request.url.query.decode())
        if request.url.path.endswith("/GetAppList/v1/"):
            assert query["key"] == [STEAM_KEY]     # the key is really sent...
            return httpx.Response(500)             # ...and the failure message must not repeat it
        if request.url.path == "/search/results/":
            return httpx.Response(200, json={"success": 1, "results_html": "", "total_count": 0, "start": -1})
        if request.url.host == "api.isthereanydeal.com" and request.url.path == "/games/history/v2" \
                and query["country"] == ["US"]:
            assert request.headers["ITAD-API-Key"] == ITAD_KEY
            return httpx.Response(503)
        return super().__call__(request)


@pytest.fixture
def env(tmp_path, monkeypatch):
    fake = LeakySteam()
    monkeypatch.setattr(commands, "TRANSPORT", httpx.MockTransport(fake))
    monkeypatch.setattr(commands, "SLEEP", lambda s: None)
    monkeypatch.setattr(cli, "load_secrets",
                        lambda: Secrets(itad_api_key=Secret(ITAD_KEY), steam_web_api_key=Secret(STEAM_KEY)))
    config = tmp_path / "sweetspot.toml"
    config.write_text(TEST_TOML.replace("daily_budget_seconds = 120", "daily_budget_seconds = 5"),
                      encoding="utf-8")
    return config


def test_keys_do_not_leak_anywhere(env):
    outputs = []
    for argv in (["update", "--json"], ["reference", "--budget", "5", "--json"], ["coverage", "--json"]):
        out, err = io.StringIO(), io.StringIO()
        cli.main([*argv, "--config", str(env)], stdout=out, stderr=err)
        outputs += [out.getvalue(), err.getvalue()]

    data_dir = env.parent / "data"
    haystacks = outputs + [p.read_bytes().decode("utf-8", "replace") for p in data_dir.rglob("*") if p.is_file()]
    for key in (ITAD_KEY, STEAM_KEY):
        assert not any(key in text for text in haystacks), f"{key[:5]}… leaked"
    # the keyed failures did happen and were reported (error messages carry the URL without its query)
    summary = json.loads(outputs[2])
    assert summary["broad"]["status"] == "failed" and "GetAppList" in summary["broad"]["reason"]
