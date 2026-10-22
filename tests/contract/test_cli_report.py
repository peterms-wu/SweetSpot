"""contracts/cli.md: `sweetspot report` (tasks T019, T028-T029)."""

import hashlib
import io
import json

import pytest

from sweetspot import cli, commands
from tests.config_builders import TEST_TOML
from sweetspot.decision import engine as decision_engine
from sweetspot.decision.rule import CURRENT_RULE
from tests.decision_builders import steam_current
from tests.forecast_builders import BASIC_CALENDAR, GameSpec, build_db, dt

HISTORY = [("2024-12-11", 0), ("2024-12-19T18:00", 50), ("2025-01-02T18:00", 0), ("2025-03-13T17:00", 40),
           ("2025-03-20T17:00", 0), ("2025-06-26T17:00", 50), ("2025-07-10T17:00", 0)]
NOW = dt("2026-09-25T04:00")


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_secrets", lambda: cli.Secrets())
    monkeypatch.setattr(commands, "NOW", lambda: NOW)
    monkeypatch.setattr(commands, "OPEN_FILE", lambda path: pytest.fail(f"opened {path} without --open"))
    path = tmp_path / "sweetspot.toml"
    path.write_text(TEST_TOML, encoding="utf-8")
    return path


@pytest.fixture
def db(config_path):
    games = [GameSpec(1, tw=HISTORY, name="Alpha", wishlist=True,
                      extra_tw=[steam_current(1, "2026-09-25T03:00", 50000, 50000)]),
             GameSpec(2, tw=HISTORY, name="Beta", wishlist=True, regular_cents=51000),
             GameSpec(3, tw=HISTORY, name="Reference only"),
             GameSpec(4, name="Coming soon", release_date="2099-01-01", wishlist=True)]
    return build_db(config_path.parent / "data" / "sweetspot.db", games, calendar=BASIC_CALENDAR)


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(list(argv), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_official_report_default_path_and_summary(config_path, db):
    before = digest(db)
    code, out, _ = run("report", "--json", "--config", str(config_path))
    assert code == cli.EXIT_OK
    summary = json.loads(out)
    data_dir = config_path.parent / "data"
    report = data_dir / "reports" / "latest.html"
    assert summary["report"] == str(report) and report.exists()
    for key in ("now", "soon", "wait", "low", "na", "decision_error", "changed", "baseline", "record", "model",
                "rule", "as_of", "seconds"):
        assert key in summary, key
    assert summary["na"] == 1 and summary["as_of"] == "2026-09-25T04:00:00Z"
    assert summary["rule"] == {"name": "sweet-price", "version": CURRENT_RULE}
    assert digest(db) == before                                  # read-only
    assert not (data_dir / ".lock").exists()
    assert "Alpha" in report.read_text(encoding="utf-8")


def test_text_output_lists_group_counts(config_path, db):
    code, out, _ = run("report", "--config", str(config_path))
    assert code == 0
    assert "現在買" in out and "即將到價" in out and "無法預測" in out


def test_as_of_and_out_paths(config_path, db, tmp_path):
    code, out, _ = run("report", "--json", "--as-of", "2025-08-01", "--config", str(config_path))
    assert code == 0
    assert json.loads(out)["report"].endswith("asof-2025-08-01.html")
    target = tmp_path / "elsewhere" / "r.html"
    code, out, _ = run("report", "--json", "--out", str(target), "--config", str(config_path))
    assert code == 0 and target.exists()


def test_open_calls_the_system_viewer(config_path, db, monkeypatch):
    opened = []
    monkeypatch.setattr(commands, "OPEN_FILE", opened.append)
    code, _, _ = run("report", "--open", "--config", str(config_path))
    assert code == 0 and len(opened) == 1 and str(opened[0]).endswith("latest.html")


@pytest.mark.parametrize("update_exit, note", [("0", None), ("1", "本次資料更新失敗，使用既有資料"),
                                               ("2", "本次資料更新有部分項目未完成"),
                                               ("3", "另一個更新正在執行，使用既有資料"),
                                               ("4", "找到舊名稱的檔案，本次沒有更新資料：請先執行搬家（uv run sweetspot migrate）")])
def test_update_exit_is_reported(config_path, db, update_exit, note):
    code, out, _ = run("report", "--json", "--update-exit", update_exit, "--config", str(config_path))
    assert code == (cli.EXIT_OK if update_exit == "0" else cli.EXIT_PARTIAL)
    page = (config_path.parent / "data" / "reports" / "latest.html").read_text(encoding="utf-8")
    if note:
        assert note in page
    assert json.loads(out)["data_refresh"] == {"update_exit": int(update_exit), "note": note}


def test_decision_error_gives_exit_2(config_path, db, monkeypatch):
    real = decision_engine.decide

    def flaky(**kw):
        if kw["regular_cents"] == 51000:
            raise RuntimeError("boom")
        return real(**kw)

    monkeypatch.setattr(decision_engine, "decide", flaky)
    code, out, _ = run("report", "--json", "--config", str(config_path))
    assert code == cli.EXIT_PARTIAL and json.loads(out)["decision_error"] == 1


def test_missing_database_fails(config_path):
    code, _, err = run("report", "--config", str(config_path))
    assert code == cli.EXIT_FAILED and "執行失敗" in err


# --- feature 005: `report --rule` preview (tasks T013; contracts/cli.md) --------------------------------------

def test_preview_with_another_rule_writes_no_record(config_path, db):
    code, out, err = run("report", "--json", "--rule", "3.0.0", "--config", str(config_path))
    assert code == cli.EXIT_OK, err
    summary = json.loads(out)
    data_dir = config_path.parent / "data"
    preview = data_dir / "reports" / "preview-3.0.0.html"
    assert summary["report"] == str(preview) and preview.exists()
    assert summary["rule"] == {"name": "sweet-price", "version": "3.0.0"} and summary["preview"] is True
    assert summary["record"] is None and summary["baseline"] is None
    assert not (data_dir / "forecasts").exists() or not list((data_dir / "forecasts").iterdir())
    assert not (data_dir / "reports" / "latest.html").exists()
    assert "預覽：非現行規則" in preview.read_text(encoding="utf-8")


def test_rule_equal_to_the_current_one_is_a_normal_report(config_path, db):
    code, out, _ = run("report", "--json", "--rule", CURRENT_RULE, "--config", str(config_path))
    summary = json.loads(out)
    assert code == cli.EXIT_OK and summary["report"].endswith("latest.html") and summary["preview"] is False
    assert summary["record"] is not None


def test_invalid_wait_cost_in_the_config_fails(config_path, db):
    config_path.write_text(TEST_TOML.replace("wait_cost_twd = 20", "wait_cost_twd = -5"), encoding="utf-8")
    code, _, err = run("report", "--rule", "3.0.0", "--config", str(config_path))
    assert code == cli.EXIT_FAILED and "wait_cost_twd" in err


def test_report_passes_the_configured_choices(config_path, db, monkeypatch):
    """Feature 009 (tasks T032): [purchase_options] reaches run_decisions."""
    from sweetspot import commands
    seen = {}
    original = commands.run_decisions

    def spy(*args, **kw):
        seen["choices"] = kw.get("choices")
        return original(*args, **kw)

    monkeypatch.setattr(commands, "run_decisions", spy)
    config_path.write_text(config_path.read_text(encoding="utf-8") + '620 = "sub/7877"\n', encoding="utf-8")
    code, _, err = run("report", "--json", "--config", str(config_path))
    assert code in (0, 2), err
    assert seen["choices"] == {620: ("sub", 7877)}



def test_report_warns_about_choices_outside_the_wishlist(config_path, db):
    config_path.write_text(config_path.read_text(encoding="utf-8") + '999 = "sub/1"\n', encoding="utf-8")
    code, out, err = run("report", "--json", "--config", str(config_path))
    assert code in (0, 2), err
    warning = "purchase_options.999：不在願望清單的追蹤範圍，已忽略"
    assert warning in json.loads(out)["warnings"] and warning in err


# --- feature 011: the extension data file (contracts/extension-ui.md; tasks T010) -------------------------------

def _extension(config_path, manifest=True):
    folder = config_path.parent / "extension"
    if manifest:
        folder.mkdir(exist_ok=True)
        (folder / "manifest.json").write_text("{}", encoding="utf-8")
    return folder / "data" / "sweetspot-extension.json"


def test_official_report_writes_the_extension_data(config_path, db):
    target = _extension(config_path)
    code, out, _ = run("report", "--json", "--config", str(config_path))
    assert code == cli.EXIT_OK
    assert json.loads(out)["extension"] == str(target)
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["format"] == "steamsage.extension/1" and payload["summary"]["na"] == 1
    assert payload["record"] and payload["record"].endswith(".json.gz")
    assert [p.name for p in target.parent.iterdir()] == [target.name]              # no .tmp left behind


def test_no_manifest_no_extension_folder(config_path, db):
    code, out, _ = run("report", "--json", "--config", str(config_path))
    assert code == cli.EXIT_OK and json.loads(out)["extension"] is None
    assert not (config_path.parent / "extension").exists()


@pytest.mark.parametrize("extra", [["--as-of", "2025-08-01"], ["--rule", "3.0.0"]])
def test_unofficial_runs_leave_the_extension_data_alone(config_path, db, extra):
    target = _extension(config_path)
    run("report", "--config", str(config_path))
    before = (target.stat().st_mtime_ns, target.read_bytes())
    code, out, _ = run("report", "--json", *extra, "--config", str(config_path))
    assert code == cli.EXIT_OK and json.loads(out)["extension"] is None
    assert (target.stat().st_mtime_ns, target.read_bytes()) == before


def test_write_failure_keeps_the_report_and_gives_exit_2(config_path, db, monkeypatch):
    from sweetspot.report import extension

    _extension(config_path)

    def broken(payload):
        raise OSError("disk full")

    monkeypatch.setattr(extension, "dumps", broken)
    code, out, err = run("report", "--json", "--config", str(config_path))
    summary = json.loads(out)
    assert code == cli.EXIT_PARTIAL
    assert summary["extension"].startswith("未寫入：") and "disk full" in summary["extension"]
    assert "擴充功能資料未寫入" in err
    assert (config_path.parent / "data" / "reports" / "latest.html").exists() and summary["record"]


def test_html_report_is_the_same_with_or_without_the_extension(config_path, db):
    report = config_path.parent / "data" / "reports" / "latest.html"
    run("report", "--config", str(config_path))
    without = report.read_text(encoding="utf-8")
    for record in (config_path.parent / "data" / "forecasts").iterdir():     # same clock: both runs are the first
        record.unlink()
    _extension(config_path)
    run("report", "--config", str(config_path))
    assert report.read_text(encoding="utf-8") == without


# --- feature 012 (plan D1; FR-021): calendar notices in the official report -------------------------------------

SUMMER_NOTICE = ("官方特賣頁面的 2026 夏特是 6/26–7/10，data/steam_sales.toml 是 6/25–7/9；預測沿用檔案的日期。"
                 "確認後執行 sweetspot calendar --sync --write")


def _record_conflicting_summer(db):
    from datetime import date, time
    from zoneinfo import ZoneInfo

    from sweetspot import calendar_sync
    from sweetspot.sources import OfficialSale, SeasonalSalesPage
    from sweetspot.store.writer import StoreWriter

    page = SeasonalSalesPage(url="https://partner.steamgames.com/doc/marketing/discounts/seasonalsales",
                             fetched_at=NOW, http_status=200, bytes=1, sha256="0" * 64, found_dates_section=True,
                             sales=[OfficialSale("summer", 2026, date(2026, 6, 26), date(2026, 7, 10))])
    writer = StoreWriter.open(db)
    try:
        calendar_sync.record_fetch(writer, page, now=NOW, default_time=time(10), tz=ZoneInfo("America/Los_Angeles"))
    finally:
        writer.close()


def _latest_record(config_path):
    import gzip

    folder = config_path.parent / "data" / "forecasts"
    return json.loads(gzip.decompress(sorted(folder.iterdir())[-1].read_bytes()))


def test_calendar_notices_are_empty_without_official_records(config_path, db):
    run("report", "--json", "--config", str(config_path))
    assert _latest_record(config_path)["calendar_notices"] == []


def test_official_report_shows_calendar_notices(config_path, db):
    _record_conflicting_summer(db)
    run("report", "--json", "--config", str(config_path))
    assert _latest_record(config_path)["calendar_notices"] == [SUMMER_NOTICE]
    page = (config_path.parent / "data" / "reports" / "latest.html").read_text(encoding="utf-8")
    assert f'<p class="banner">{SUMMER_NOTICE}</p>' in page


def test_as_of_report_has_no_calendar_notices(config_path, db, tmp_path):
    _record_conflicting_summer(db)
    out = tmp_path / "asof.html"
    run("report", "--json", "--as-of", "2026-09-01", "--out", str(out), "--config", str(config_path))
    assert SUMMER_NOTICE not in out.read_text(encoding="utf-8")
