"""fix-quarantine: the daily update records when each history response arrived, so an event ITAD recorded after the
batch started but before the fetch is kept (the 2026 autumn sale's Stellar Blade, 013 research R9).

The elapsed clock is replaced by one that says the fetch happened 5 minutes into the run; the fake ITAD history holds
an event 2 minutes into the run. The reverse test (a clock stuck at the batch start) proves the check can fail.
"""

from datetime import timedelta

import httpx
import pytest

from sweetspot import cli, commands
from sweetspot.config import Secret, Secrets
from tests.config_builders import TEST_TOML
from sweetspot.pipeline import daily
from tests.integration.test_update_us2 import FakeSteamAndItad, db, run_update

STARTED: list = []


class LateEvent(FakeSteamAndItad):
    """Portal 2's TW history gains a -50% event two minutes after the batch started."""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        response = super().__call__(request)
        if request.url.path == "/games/history/v2" and "country=TW" in str(request.url) and STARTED:
            rows = response.json()
            if rows and rows[0]["deal"]["price"]["amountInt"] == 18800:      # Portal 2 (app 620)
                late = (STARTED[0] + timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
                rows = [{"timestamp": late, "shop": {"id": 61, "name": "Steam"},
                         "deal": {"price": {"amount": 94, "amountInt": 9400, "currency": "TWD"},
                                  "regular": {"amount": 188, "amountInt": 18800, "currency": "TWD"}, "cut": 50}}] + rows
                return httpx.Response(200, json=rows)
        return response


@pytest.fixture
def env(tmp_path, monkeypatch):
    STARTED.clear()
    monkeypatch.setattr(commands, "TRANSPORT", httpx.MockTransport(LateEvent()))
    monkeypatch.setattr(commands, "SLEEP", lambda s: None)
    monkeypatch.setattr(cli, "load_secrets", lambda: Secrets(itad_api_key=Secret("test-itad-key")))
    config = tmp_path / "sweetspot.toml"
    config.write_text(TEST_TOML, encoding="utf-8")
    return config, monkeypatch


def clock_at(minutes):
    def make(now):
        STARTED.append(now)
        return lambda: now + timedelta(minutes=minutes)
    return make


def late_rows(config):
    with db(config) as conn:
        return conn.execute("SELECT anomaly FROM price_observations WHERE app_id = 620 AND region = 'TW' "
                            "AND cut_pct = 50 AND price_cents = 9400").fetchall()


def test_an_event_between_the_batch_start_and_the_fetch_is_kept(env):
    config, monkeypatch = env
    monkeypatch.setattr(daily, "elapsed_clock", clock_at(5))
    code, _, err = run_update(config)
    assert code in (cli.EXIT_OK, cli.EXIT_PARTIAL), err
    assert late_rows(config) == [(None,)]


def test_reverse_a_clock_stuck_at_the_batch_start_quarantines_it(env):
    config, monkeypatch = env
    monkeypatch.setattr(daily, "elapsed_clock", clock_at(0))
    run_update(config)
    assert late_rows(config) == [("observed-after-retrieved",)]
