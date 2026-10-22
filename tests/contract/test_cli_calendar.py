"""Feature 012: `sweetspot calendar` with --fetch, --check, --sync and --write (contracts/calendar-sync.md §4)."""

import io
import json
import sqlite3
from pathlib import Path

import httpx
import pytest

from sweetspot import cli, commands
from tests.config_builders import TEST_TOML
from sweetspot.sources.steam_partner import OFFICIAL_URL
from tests.conftest import partner_page, write_calendar

REAL_CALENDAR = Path(__file__).parents[2] / "data" / "steam_sales.toml"


def calendar_text(*drop):
    head, *blocks = REAL_CALENDAR.read_text(encoding="utf-8").split("\n[[sale]]\n")
    kept = [b for b in blocks if not any(f'season = "{s}"\nyear = {y}\n' in b for s, y in drop)]
    return "\n[[sale]]\n".join([head, *kept])


class Partner:
    def __init__(self):
        self.page, self.requests = partner_page(), []

    def __call__(self, request):
        self.requests.append(str(request.url))
        return httpx.Response(200, headers={"content-type": "text/html; charset=UTF-8"}, text=self.page)


@pytest.fixture
def env(tmp_path, monkeypatch):
    partner = Partner()
    monkeypatch.setattr(commands, "TRANSPORT", httpx.MockTransport(partner))
    monkeypatch.setattr(commands, "SLEEP", lambda s: None)
    monkeypatch.setattr(cli, "load_secrets", lambda: cli.Secrets())
    config = tmp_path / "sweetspot.toml"
    config.write_text(TEST_TOML, encoding="utf-8")
    write_calendar(tmp_path / "data", calendar_text())
    return partner, config


def run(config, *args, json_out=True):
    out, err = io.StringIO(), io.StringIO()
    argv = ["calendar", *args, "--config", str(config)] + (["--json"] if json_out else [])
    code = cli.main(argv, stdout=out, stderr=err)
    return code, (json.loads(out.getvalue()) if json_out and out.getvalue() else out.getvalue()), err.getvalue()


def test_plain_calendar_sends_no_request(env):
    partner, config = env
    code, summary, _ = run(config)
    assert code == cli.EXIT_OK and partner.requests == []
    assert summary["official_page"]["status"] == "not_fetched"


def test_fetch_reads_the_page_once(env):
    partner, config = env
    code, summary, _ = run(config, "--fetch")
    assert partner.requests == [OFFICIAL_URL]
    page = summary["official_page"]
    assert (page["status"], page["listed"], page["same"]) == ("ok", 4, 4)
    conn = sqlite3.connect(config.parent / "data" / "sweetspot.db")
    assert conn.execute("SELECT status, run_id FROM calendar_fetches").fetchall() == [("ok", None)]
    conn.close()
    code, summary, _ = run(config)                        # later: the stored result, no request
    assert summary["official_page"]["same"] == 4 and len(partner.requests) == 1


def test_check_is_ok_when_the_page_agrees(env):
    _, config = env
    run(config, "--fetch")
    code, summary, _ = run(config, "--check")
    assert code == cli.EXIT_OK
    assert not [a for a in summary["alerts"] if a.startswith("官方特賣頁面")]


def test_check_is_partial_on_a_conflict_or_a_failure(env):
    partner, config = env
    partner.page = partner_page(edit=("17 December, 2026", "18 December, 2026"))
    run(config, "--fetch")
    code, summary, _ = run(config, "--check")
    assert code == cli.EXIT_PARTIAL
    assert any("2026 冬特是 12/18–1/4" in a for a in summary["alerts"])
    partner.page = partner_page()
    run(config, "--fetch")
    assert run(config, "--check")[0] == cli.EXIT_OK
    partner.page = ""
    run(config, "--fetch")
    code, summary, _ = run(config, "--check")
    assert code == cli.EXIT_PARTIAL and any("格式改變" in a for a in summary["alerts"])


def test_sync_lists_then_write_writes(env):
    _, config = env
    path = config.parent / "data" / "steam_sales.toml"
    write_calendar(config.parent / "data", calendar_text(("spring", 2027)))
    run(config, "--fetch")
    before = path.read_bytes()
    code, summary, _ = run(config, "--sync")
    assert summary["sync"]["written"] is False
    assert [a["label"] for a in summary["sync"]["add"]] == ["2027 春特"] and summary["sync"]["reschedule"] == []
    assert path.read_bytes() == before
    code, summary, _ = run(config, "--sync", "--write")
    assert code == cli.EXIT_OK and summary["sync"]["written"] is True
    assert 'season = "spring"\nyear = 2027\nstart = "2027-03-18"' in path.read_text(encoding="utf-8")
    code, text, _ = run(config, "--sync", json_out=False)
    assert "已一致" in text
    code, summary, _ = run(config, "--check")
    assert not [a for a in summary["alerts"] if a.startswith("官方特賣頁面")]


def test_write_needs_sync(env):
    _, config = env
    code, _, err = run(config, "--write", json_out=False)
    assert code != cli.EXIT_OK and "--sync" in err
