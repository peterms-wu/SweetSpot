"""Feature 012: the daily update's calendar step with the official seasonal sales page (US1-US4; contracts
/calendar-sync.md §2-§3). The page is a local copy; nothing here touches the network."""

import io
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from sweetspot import calendar, calendar_sync, cli, commands
from sweetspot.config import load_config
from tests.config_builders import TEST_TOML
from sweetspot.pipeline import daily
from sweetspot.sources import SeasonalSalesPage
from sweetspot.sources.errors import RateLimited, SourceDisabled, SourceError
from sweetspot.sources.steam_partner import OFFICIAL_URL, parse_seasonal_sales
from sweetspot.store.writer import StoreWriter
from tests.conftest import partner_page, write_calendar
from tests.integration.test_update_us1 import FakeSteam

REAL_CALENDAR = Path(__file__).parents[2] / "data" / "steam_sales.toml"
NOW = datetime(2026, 9, 27, 12, tzinfo=UTC)
NEW_ALERT = ("官方特賣頁面公告了 2027 春特（太平洋時間 3/18–3/25），已用於預測；"
             "執行 sweetspot calendar --sync --write 寫入 data/steam_sales.toml")


def calendar_text(*drop: tuple[str, int]) -> str:
    """The real calendar file without the given seasonal sales."""
    head, *blocks = REAL_CALENDAR.read_text(encoding="utf-8").split("\n[[sale]]\n")
    kept = [b for b in blocks if not any(f'season = "{s}"\nyear = {y}\n' in b for s, y in drop)]
    assert len(kept) == len(blocks) - len(drop)
    return "\n[[sale]]\n".join([head, *kept])


def official(text: str) -> SeasonalSalesPage:
    parsed = parse_seasonal_sales(text)
    return SeasonalSalesPage(url=OFFICIAL_URL, fetched_at=NOW, http_status=200, bytes=len(text), sha256="0" * 64,
                             found_dates_section=parsed.found_dates_section, sales=parsed.sales,
                             pending=parsed.pending, rejected=parsed.rejected)


class Source:
    """A SeasonalSalesSource returning (or raising) the given results in turn; the last one repeats."""

    def __init__(self, *results):
        self.results, self.calls = list(results), 0

    def seasonal_sales_page(self):
        result = self.results[min(self.calls, len(self.results) - 1)]
        self.calls += 1
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def setup(tmp_path):
    path = tmp_path / "sweetspot.toml"
    path.write_text(TEST_TOML, encoding="utf-8")
    config, _ = load_config(path)
    writer = StoreWriter.open(config.db_path)
    yield config, writer
    writer.close()


def run(config, writer, source, now=NOW):
    report = daily.DailyReport()
    summary = daily.update_calendar(writer, config, now=now, report=report, sales_page=source, run_id="run")
    return summary["calendar"], [a for a in report.alerts if a.startswith("官方特賣頁面")], report


def events(config, writer, now=NOW):
    return calendar_sync.load_effective(writer.conn, config.data_dir / "steam_sales.toml", now=now)


# --- US1 ----------------------------------------------------------------------------------------------------------------

def test_matching_page_changes_nothing(setup):
    config, writer = setup
    write_calendar(config.data_dir, calendar_text())
    before = calendar.load_calendar(config.data_dir / "steam_sales.toml", now=NOW)
    source = Source(official(partner_page()))
    summary, alerts, _ = run(config, writer, source)
    page = summary["official_page"]
    assert (page["status"], page["listed"], page["same"], page["new"], page["conflict"], page["missing"],
            page["not_in_file"]) == ("ok", 4, 4, 0, 0, 0, 0)
    assert alerts == []
    assert source.calls == 1
    assert events(config, writer) == before


def test_new_official_sale_is_adopted(setup):
    config, writer = setup
    path = write_calendar(config.data_dir, calendar_text(("spring", 2027)))
    file_bytes = path.read_bytes()
    summary, alerts, _ = run(config, writer, Source(SourceError("offline")))          # first: only an estimate
    assert "2027 春特" in summary["new_estimates"]

    summary, alerts, _ = run(config, writer, Source(official(partner_page())))
    page = summary["official_page"]
    assert (page["new"], page["not_in_file"], page["same"]) == (1, 1, 3)
    assert alerts == [NEW_ALERT]
    spring = [e for e in events(config, writer) if calendar.label(e) == "2027 春特"]
    assert [(e.status, e.confidence, e.source) for e in spring] == [("announced", "official", OFFICIAL_URL)]
    superseded = writer.conn.execute("SELECT superseded_at FROM sale_estimates WHERE season = 'spring' "
                                     "AND year = 2027").fetchall()
    assert len(superseded) == 1 and superseded[0][0] is not None
    assert path.read_bytes() == file_bytes                                              # SC-002: file untouched

    summary, alerts, _ = run(config, writer, Source(official(partner_page())))          # the next day: one line again
    assert alerts == [NEW_ALERT]


def test_ended_sale_missing_from_the_file_is_still_adopted(setup):
    config, writer = setup
    write_calendar(config.data_dir, calendar_text(("autumn", 2026)))
    after_sale = datetime(2026, 10, 9, tzinfo=UTC)
    summary, _, _ = run(config, writer, Source(official(partner_page())), now=after_sale)
    assert summary["official_page"]["new"] == 1
    autumn = [e for e in events(config, writer, after_sale) if calendar.label(e) == "2026 秋特"]
    assert [e.status for e in autumn] == ["ended"]


def test_update_command_fetches_the_page_once(tmp_path, monkeypatch):
    steam = FakeSteam()
    text = partner_page()

    def transport(request: httpx.Request) -> httpx.Response:
        if request.url.host == "partner.steamgames.com":
            steam.requests.append(str(request.url))
            return httpx.Response(200, headers={"content-type": "text/html; charset=UTF-8"}, text=text)
        return steam(request)

    monkeypatch.setattr(commands, "TRANSPORT", httpx.MockTransport(transport))
    monkeypatch.setattr(commands, "SLEEP", lambda s: None)
    monkeypatch.setattr(cli, "load_secrets", lambda: cli.Secrets())
    config = tmp_path / "sweetspot.toml"
    config.write_text(TEST_TOML, encoding="utf-8")
    write_calendar(tmp_path / "data", calendar_text())
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(["update", "--no-history", "--json", "--config", str(config)], stdout=out, stderr=err)
    summary = json.loads(out.getvalue())
    assert summary["calendar"]["official_page"]["status"] == "ok"
    assert summary["calendar"]["official_page"]["same"] == 4
    assert [u for u in steam.requests if "partner.steamgames.com" in u] == [OFFICIAL_URL]
    assert summary["http"]["steam-partner"]["requests"] == 1
    assert not any(a.startswith("官方特賣頁面") for a in summary["alerts"])
    assert code in (0, 2)


# --- US2: failures change nothing and are reported ---------------------------------------------------------------------

KEEP = "特賣日期沿用既有紀錄"
FAILURES = [
    (SourceError("steam-partner: network error for https://x: ReadTimeout: timed out"), "failed",
     f"官方特賣頁面抓取失敗（steam-partner: network error for https://x: ReadTimeout: timed out），{KEEP}"),
    (SourceDisabled("steam-partner: HTTP 403 for https://x; source disabled for this run"), "denied",
     f"官方特賣頁面拒絕存取（HTTP 403），本次停止，不重試；{KEEP}"),
    (RateLimited("steam-partner: asked to wait 7200s for https://x"), "rate_limited",
     f"官方特賣頁面要求等待 7200 秒（HTTP 429），本次略過；{KEEP}"),
    (official(""), "no_dates", f"官方特賣頁面格式改變，找不到任何季節特賣日期；{KEEP}"),
    (official(partner_page(edit=('<a name="2"></a>Dates', '<a name="2"></a>Schedule'))), "no_dates",
     f"官方特賣頁面格式改變，找不到任何季節特賣日期；{KEEP}"),
]


@pytest.mark.parametrize("result, status, alert", FAILURES)
def test_failures_keep_the_calendar(setup, result, status, alert):
    config, writer = setup
    write_calendar(config.data_dir, calendar_text(("spring", 2027)))
    run(config, writer, Source(official(partner_page())))                 # 2027 spring adopted earlier
    before = events(config, writer)
    summary, alerts, _ = run(config, writer, Source(result), now=NOW.replace(hour=13))
    assert summary["official_page"]["status"] == status
    assert alerts == [alert, NEW_ALERT]                                     # the adopted sale is kept
    assert events(config, writer) == before
    rows = writer.conn.execute("SELECT status FROM calendar_fetches ORDER BY fetch_id").fetchall()
    assert [r[0] for r in rows] == ["ok", status]
    assert writer.conn.execute("SELECT COUNT(*) FROM sale_sightings").fetchone()[0] == 4


def test_failure_on_a_fresh_database_uses_the_file_only(setup):
    config, writer = setup
    write_calendar(config.data_dir, calendar_text())
    run(config, writer, Source(SourceError("offline")))
    assert events(config, writer) == calendar.load_calendar(config.data_dir / "steam_sales.toml", now=NOW)


def test_unparsable_line_and_early_removal(setup):
    config, writer = setup
    write_calendar(config.data_dir, calendar_text())
    renamed = partner_page(edit=("<strong>Winter Sale 2026</strong>", "<strong>Holiday Sale 2026</strong>"))
    summary, alerts, _ = run(config, writer, Source(official(renamed)))
    assert summary["official_page"]["status"] == "ok" and summary["official_page"]["rejected"] == 1
    assert alerts == ["官方特賣頁面有 1 行無法解析，已略過：Holiday Sale 2026 | 17 December, 2026 - 4 January, 2027"
                      "（未知的季節）",
                      "官方特賣頁面不再列出 2026 冬特（可能取消或改名）；行事曆保留原本的日期"]
    winter = [e for e in events(config, writer) if calendar.label(e) == "2026 冬特"]
    assert len(winter) == 1

    no_spring = re.sub(r'<h2 class="bb_subsection"><a name="1"></a><strong>Spring Sale 2027.*?</h2>', "",
                       partner_page())
    _, alerts, _ = run(config, writer, Source(official(no_spring)))
    assert alerts == ["官方特賣頁面不再列出 2027 春特（可能取消或改名）；行事曆保留原本的日期"]


def test_an_ended_sale_leaving_the_page_is_normal(setup):
    config, writer = setup
    write_calendar(config.data_dir, calendar_text())
    no_autumn = re.sub(r'<h2 class="bb_subsection"><a name="1"></a><strong>Autumn Sale 2026.*?</h2>', "",
                       partner_page())
    _, alerts, _ = run(config, writer, Source(official(no_autumn)), now=datetime(2026, 10, 10, tzinfo=UTC))
    assert alerts == []


@pytest.mark.parametrize("days, expected", [(8, True), (6, False)])
def test_stale_official_page(setup, days, expected):
    config, writer = setup
    write_calendar(config.data_dir, calendar_text())
    first = datetime(2026, 9, 28, 12, tzinfo=UTC)
    run(config, writer, Source(official(partner_page())), now=first)
    _, alerts, _ = run(config, writer, Source(SourceError("offline")), now=first + timedelta(days=days))
    stale = "官方特賣頁面已 8 天沒有成功讀取（最後一次 2026-09-28 20:00 台北）"
    assert (stale in alerts) is expected


def test_never_successful_for_a_week(setup):
    config, writer = setup
    write_calendar(config.data_dir, calendar_text())
    first = datetime(2026, 9, 28, 12, tzinfo=UTC)
    run(config, writer, Source(SourceError("offline")), now=first)
    _, alerts, _ = run(config, writer, Source(SourceError("offline")), now=first + timedelta(days=8))
    assert "官方特賣頁面已 8 天沒有成功讀取（從未成功）" in alerts


def test_calendar_file_error_skips_the_page(setup):
    config, writer = setup
    write_calendar(config.data_dir, "not toml [")
    source = Source(official(partner_page()))
    summary, _, report = run(config, writer, source)
    assert summary == {"status": "unavailable", "official_page": {"status": "skipped"}}
    assert source.calls == 0 and any(a.startswith("特賣行事曆無法使用") for a in report.alerts)


@pytest.mark.parametrize("response", [httpx.Response(403), None])
def test_update_command_other_steps_are_unaffected(tmp_path, monkeypatch, response):
    """The real client: 403, or a timeout raised by the transport. Prices, metadata and the exit code match a run
    whose page is fine."""
    def run_update(page_response):
        steam = FakeSteam()

        def transport(request):
            if request.url.host == "partner.steamgames.com":
                if page_response is None:
                    raise httpx.ReadTimeout("timed out", request=request)
                return page_response
            return steam(request)

        monkeypatch.setattr(commands, "TRANSPORT", httpx.MockTransport(transport))
        monkeypatch.setattr(commands, "SLEEP", lambda s: None)
        monkeypatch.setattr(cli, "load_secrets", lambda: cli.Secrets())
        folder = tmp_path / ("bad" if page_response is not ok else "good")
        folder.mkdir(exist_ok=True)
        config = folder / "sweetspot.toml"
        config.write_text(TEST_TOML, encoding="utf-8")
        write_calendar(folder / "data", calendar_text())
        out = io.StringIO()
        code = cli.main(["update", "--no-history", "--json", "--config", str(config)], stdout=out,
                        stderr=io.StringIO())
        return code, json.loads(out.getvalue())

    ok = httpx.Response(200, headers={"content-type": "text/html"}, text=partner_page())
    good_code, good = run_update(ok)
    bad_code, bad = run_update(response)
    assert bad_code == good_code
    assert bad["current_prices"] == good["current_prices"] and bad["metadata"] == good["metadata"]
    assert bad["calendar"]["official_page"]["status"] == ("denied" if response is not None else "failed")
    assert bad["http"]["steam-partner"]["requests"] == 1


# --- US3: conflicts keep the file's dates --------------------------------------------------------------------------

WINTER_MOVED = partner_page(edit=("17 December, 2026", "18 December, 2026"))
CONFLICT_ALERT = ("官方特賣頁面的 2026 冬特是 12/18–1/4，data/steam_sales.toml 是 12/17–1/4；預測沿用檔案的日期。"
                  "確認後執行 sweetspot calendar --sync --write")


def test_conflict_keeps_the_file_dates(setup):
    config, writer = setup
    write_calendar(config.data_dir, calendar_text())
    summary, alerts, _ = run(config, writer, Source(official(WINTER_MOVED)))
    assert summary["official_page"]["conflict"] == 1 and summary["official_page"]["same"] == 3
    assert alerts == [CONFLICT_ALERT]
    winter = [e for e in events(config, writer) if calendar.label(e) == "2026 冬特"]
    assert [e.start for e in winter] == [datetime(2026, 12, 17, 18, tzinfo=UTC)]
    _, alerts, _ = run(config, writer, Source(official(WINTER_MOVED)), now=NOW.replace(day=28))
    assert alerts == [CONFLICT_ALERT]                                      # every day until the file agrees


def test_adopted_sale_moved_by_valve(setup):
    config, writer = setup
    write_calendar(config.data_dir, calendar_text())
    autumn = ('</h2><h2 class="bb_subsection"><a name="1"></a><strong>Autumn Sale 2027</strong> | '
              '{} - {}</h2><h2 class="bb_section"><a name="3"></a>Frequently')
    first = partner_page(edit=('</h2><h2 class="bb_section"><a name="3"></a>Frequently',
                               autumn.format("30 September, 2027", "7 October, 2027")))
    moved = partner_page(edit=('</h2><h2 class="bb_section"><a name="3"></a>Frequently',
                               autumn.format("7 October, 2027", "14 October, 2027")))
    run(config, writer, Source(official(first)))
    _, alerts, _ = run(config, writer, Source(official(moved)), now=NOW.replace(day=28))
    assert alerts == ["官方特賣頁面把 2027 秋特從 9/30–10/7 改成 10/7–10/14（尚未寫入檔案，已改用新日期）",
                      "官方特賣頁面公告了 2027 秋特（太平洋時間 10/7–10/14），已用於預測；"
                      "執行 sweetspot calendar --sync --write 寫入 data/steam_sales.toml"]
    autumn_27 = [e for e in events(config, writer, NOW.replace(day=28)) if calendar.label(e) == "2027 秋特"]
    assert [e.start for e in autumn_27] == [datetime(2027, 10, 7, 17, tzinfo=UTC)]
    _, alerts, _ = run(config, writer, Source(official(moved)), now=NOW.replace(day=29))
    assert not any("改成" in a for a in alerts)                              # reported once, when first seen


def test_reschedule_round_trip(setup):
    """SC-008: conflict -> alert, forecast keeps the file -> write back -> the next update agrees."""
    config, writer = setup
    path = write_calendar(config.data_dir, calendar_text())
    _, alerts, _ = run(config, writer, Source(official(WINTER_MOVED)))
    assert alerts == [CONFLICT_ALERT]
    plan = calendar_sync.sync_plan(writer, path, now=NOW)
    assert calendar_sync.write_sync(path, plan, now=NOW) == {"written": True}
    summary, alerts, _ = run(config, writer, Source(official(WINTER_MOVED)), now=NOW.replace(hour=13))
    assert summary["official_page"]["conflict"] == 0 and summary["official_page"]["same"] == 4 and alerts == []
    winter = [e for e in events(config, writer) if calendar.label(e) == "2026 冬特"]
    assert [e.start for e in winter] == [datetime(2026, 12, 18, 18, tzinfo=UTC)]


# --- US3 / plan D1: the notices the report and the extension show --------------------------------------------------

def test_calendar_notices_are_the_three_kinds_to_act_on(setup):
    config, writer = setup
    write_calendar(config.data_dir, calendar_text(("spring", 2027)))
    file_events = calendar.load_calendar(config.data_dir / "steam_sales.toml", now=NOW)
    run(config, writer, Source(official(WINTER_MOVED)))                    # a conflict and a new sale
    assert calendar_sync.calendar_notices(writer.conn, file_events, now=NOW) == [CONFLICT_ALERT]

    renamed = partner_page(edit=("<strong>Autumn Sale 2026</strong>", "<strong>Fall Sale 2026</strong>"))
    run(config, writer, Source(official(renamed)), now=NOW.replace(hour=13))
    notices = calendar_sync.calendar_notices(writer.conn, file_events, now=NOW.replace(hour=13))
    assert notices[0].startswith("官方特賣頁面有 1 行無法解析") and len(notices) == 1   # the winter date is back in line

    later = NOW + timedelta(days=9, hours=2)                               # 9 days after the 13:00 success
    run(config, writer, Source(SourceError("offline")), now=later)
    notices = calendar_sync.calendar_notices(writer.conn, file_events, now=later)
    assert notices == ["官方特賣頁面已 9 天沒有成功讀取（最後一次 2026-09-27 21:00 台北）"]   # one failure is not a notice
