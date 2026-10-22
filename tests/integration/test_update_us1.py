"""US1 end-to-end: `update --no-history` against a mocked Steam (SC-002)."""

import io
import json
import sqlite3
from urllib.parse import parse_qs

import httpx
import pytest

from sweetspot import cli, commands
from tests.config_builders import TEST_TOML
from tests.conftest import FIXTURES

STEAM = FIXTURES / "steam"
PRICED = [620, 413150, 1145360]
MISSING = 999


def fixture(name):
    return json.loads((STEAM / name).read_text(encoding="utf-8"))


def wishlist_payload(app_ids):
    return {"response": {"items": [{"appid": a, "priority": i, "date_added": 1700000000} for i, a in
                                   enumerate(app_ids, 1)]}}


class FakeSteam:
    """Routes Steam URLs to recorded fixtures; the wishlist response is swappable per run."""

    def __init__(self):
        self.wishlist = wishlist_payload(PRICED + [MISSING])
        self.prices = fixture("appdetails_prices.json")
        self.requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        path, query = request.url.path, parse_qs(request.url.query.decode())
        if path.endswith("/GetWishlist/v1/"):
            return httpx.Response(200, json=self.wishlist)
        if path == "/api/appdetails" and query.get("filters") == ["price_overview"]:
            ids = query["appids"][0].split(",")
            return httpx.Response(200, json={i: self.prices.get(i, {"success": False}) for i in ids})
        if path == "/api/appdetails":
            app = int(query["appids"][0])
            if app == 620:
                return httpx.Response(200, json=fixture("appdetails_620.json"))
            if app == MISSING:
                return httpx.Response(200, json={str(app): {"success": False}})
            return httpx.Response(200, json={str(app): {"success": True, "data": {
                "steam_appid": app, "type": "game", "name": f"Game {app}", "is_free": False,
                "release_date": {"coming_soon": False, "date": "2020-01-01"}, "genres": [{"id": "23",
                                                                                        "description": "獨立"}]}}})
        if path.startswith("/appreviews/"):
            return httpx.Response(200, json=fixture("appreviews_620.json"))
        if path.endswith("/GetItems/v1/"):
            return httpx.Response(200, json=fixture("getitems.json"))
        return httpx.Response(404)


@pytest.fixture
def env(tmp_path, monkeypatch):
    steam = FakeSteam()
    monkeypatch.setattr(commands, "TRANSPORT", httpx.MockTransport(steam))
    monkeypatch.setattr(commands, "SLEEP", lambda s: None)
    monkeypatch.setattr(cli, "load_secrets", lambda: cli.Secrets())
    config = tmp_path / "sweetspot.toml"
    config.write_text(TEST_TOML, encoding="utf-8")
    return steam, config


def run_update(config):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(["update", "--no-history", "--json", "--config", str(config)], stdout=out, stderr=err)
    return code, json.loads(out.getvalue()) if out.getvalue() else None, err.getvalue()


def db(config):
    return sqlite3.connect(config.parent / "data" / "sweetspot.db")


def test_two_runs_accumulate_one_observation_per_run(env):
    steam, config = env
    code1, s1, err = run_update(config)
    code2, s2, _ = run_update(config)
    assert code1 == code2 == cli.EXIT_PARTIAL  # the missing app makes both runs partial
    rows = db(config).execute(
        "SELECT app_id, COUNT(*), MIN(observed_at = retrieved_at) FROM price_observations "
        "WHERE source='steam-current' GROUP BY app_id").fetchall()
    assert {r[0]: (r[1], r[2]) for r in rows} == {a: (2, 1) for a in PRICED}
    assert "現價 第" in err  # progress on stderr (FR-026)


def test_every_app_has_a_status(env):
    _, config = env
    _, summary, _ = run_update(config)
    assert summary["wishlist"]["status"] == "ok" and summary["wishlist"]["count"] == 4
    assert summary["current_prices"]["ok"] == 3 and summary["current_prices"]["not_found"] == 1
    assert [f["app_id"] for f in summary["failures"]] == [MISSING]


def test_rejected_wishlist_reuses_previous_list(env):
    steam, config = env
    run_update(config)
    steam.wishlist = {"response": {}}  # private
    code, summary, _ = run_update(config)
    assert code == cli.EXIT_PARTIAL
    assert summary["wishlist"]["status"] == "rejected" and summary["wishlist"]["reject_reason"] == "private"
    assert summary["wishlist"]["used_previous"] is True
    assert summary["current_prices"]["ok"] == 3


def test_nothing_reachable_is_exit_1(env, monkeypatch):
    """014 T072 (001 contracts/cli.md: 1 = every source unavailable): with no network at all, update ended with 2,
    and 更新資料.cmd said "done, some items need attention"."""
    steam, config = env
    run_update(config)

    def offline(request):
        raise httpx.ConnectError("no network", request=request)

    monkeypatch.setattr(commands, "TRANSPORT", httpx.MockTransport(offline))
    code, summary, _ = run_update(config)
    assert code == cli.EXIT_FAILED
    assert summary["status"] == "failed" and summary["wishlist"]["reject_reason"] == "network"
    status = db(config).execute("SELECT status FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()[0]
    assert status == "failed"


def test_one_source_down_is_still_partial(env, monkeypatch):
    """The wishlist unreachable but the store answering is part of the sources: 2, as before."""
    steam, config = env
    run_update(config)
    steam.wishlist = None
    real = steam.__call__

    def wishlist_down(request):
        if request.url.path.endswith("/GetWishlist/v1/"):
            raise httpx.ConnectError("no route", request=request)
        return real(request)

    monkeypatch.setattr(commands, "TRANSPORT", httpx.MockTransport(wishlist_down))
    code, summary, _ = run_update(config)
    assert code == cli.EXIT_PARTIAL and summary["status"] == "partial" and summary["current_prices"]["ok"] == 3


def test_removed_game_is_reported_and_still_tracked(env):
    steam, config = env
    run_update(config)
    steam.wishlist = wishlist_payload([620, 413150])
    code, summary, _ = run_update(config)
    assert code == cli.EXIT_PARTIAL  # the removed-but-tracked missing app is still reported
    assert [f["app_id"] for f in summary["failures"]] == [MISSING]
    assert summary["wishlist"]["removed"] == [MISSING, 1145360]
    assert summary["current_prices"]["ok"] == 3  # 1145360 keeps being tracked
    state = db(config).execute("SELECT state FROM wishlist_membership WHERE app_id = 1145360").fetchone()[0]
    assert state == "removed_tracking"


def test_metadata_facts_are_written(env):
    _, config = env
    run_update(config)
    facts = dict(db(config).execute(
        "SELECT field, value_json FROM product_facts WHERE app_id = 620 AND field IN "
        "('name', 'product_type', 'is_indie', 'release_date', 'review_count_total', 'review_count_filtered')"))
    assert json.loads(facts["name"]) == "Portal 2"
    assert json.loads(facts["product_type"]) == "game"
    assert json.loads(facts["release_date"]) == "2011-04-18"
    assert json.loads(facts["review_count_total"]) == 467117
    assert json.loads(facts["review_count_filtered"]) == 390695


def test_second_run_reuses_fresh_metadata(env):
    steam, config = env
    run_update(config)
    before = len([u for u in steam.requests if "l=tchinese" in u])
    run_update(config)
    after = len([u for u in steam.requests if "l=tchinese" in u])
    assert after - before == 1  # only the missing app is re-queried
