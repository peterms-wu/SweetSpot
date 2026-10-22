"""contracts/cli.md: exit codes and lock behaviour."""

import argparse
import io
import re

import pytest

from sweetspot import cli, legacy
from tests.config_builders import TEST_TOML


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_secrets", lambda: cli.Secrets())
    path = tmp_path / "sweetspot.toml"
    path.write_text(TEST_TOML, encoding="utf-8")
    return path


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(argv, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_help_works(capsys):
    with pytest.raises(SystemExit) as info:
        cli.main(["--help"])
    assert info.value.code == 0


OLD_NAME = legacy.CONFIG.old.split(".")[0]     # the pre-016 name, spelled once in sweetspot.legacy
KEPT_FORMAT = re.compile(re.escape(OLD_NAME) + r"\.[a-z][a-z-]*/\d+")   # format names stay (016 contracts/names.md §2)


def _subcommands(parser):
    return next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction)).choices


def test_help_texts_use_the_new_name():
    """016 US1 scenario 1: every sub-command's help names sweetspot; only the kept format names keep the old one."""
    parser = cli.build_parser()
    assert parser.prog == "sweetspot"
    subs = _subcommands(parser)
    assert {"update", "report", "review", "host"} <= set(subs)
    for name, sub in subs.items():
        text = KEPT_FORMAT.sub("", sub.format_help())
        assert OLD_NAME not in text.lower(), name
        assert sub.prog.startswith("sweetspot "), name
    assert OLD_NAME not in parser.format_help().lower()


def test_version_names_the_new_program(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert capsys.readouterr().out.strip() == f"sweetspot {cli.__version__}"


class _Stream:
    def __init__(self, encoding, tty):
        self.encoding, self.tty, self.set_to = encoding, tty, None

    def isatty(self):
        return self.tty

    def reconfigure(self, encoding):
        self.set_to = encoding


@pytest.mark.parametrize(("encoding", "tty", "set_to"), [
    ("cp950", True, "utf-8"),      # NUL: a character device, isatty() is True, yet it is no console (2026-10-18)
    ("cp950", False, "utf-8"),     # a pipe or a file
    ("utf-8", True, None),         # a real console
    ("UTF-8", False, None),        # already UTF-8 (PYTHONUTF8=1)
])
def test_output_is_utf8_unless_it_already_is(monkeypatch, encoding, tty, set_to):
    out, err = _Stream(encoding, tty), _Stream(encoding, tty)
    monkeypatch.setattr(cli.sys, "stdout", out)
    monkeypatch.setattr(cli.sys, "stderr", err)
    cli._utf8_when_redirected()
    assert out.set_to == err.set_to == set_to


@pytest.mark.parametrize("argv", [["report", "--bogus"], ["schedule", "bogus"], ["backtest", "--region", "JP"],
                                  ["report", "--update-exit", "x"], ["no-such-command"]])
def test_a_wrong_argument_exits_1_not_2(argv, capsys):
    """014 T069 (001/002/003 contracts/cli.md: 1 = wrong arguments): argparse ends with 2, which here means
    'done, but look at this'."""
    with pytest.raises(SystemExit) as info:
        cli.main(argv)
    assert info.value.code == cli.EXIT_FAILED
    assert "usage:" in capsys.readouterr().err


@pytest.mark.parametrize(("code", "note"), [(0, None), (2, "本次資料更新有部分項目未完成"),
                                            (7, "本次資料更新失敗，使用既有資料"),
                                            (-1073741510, "本次資料更新失敗，使用既有資料")])
def test_report_takes_any_update_exit_code(code, note):
    """014 T069: a killed update ends with a Windows status the .cmd passes on as it is; report used to refuse it
    (and so made no report). A code it does not know is an update that did not finish."""
    from sweetspot.decision import engine

    assert cli.build_parser().parse_args(["report", "--update-exit", str(code)]).update_exit == code
    assert engine.refresh_note(code) == note


def test_bad_config_exits_1(config_path):
    config_path.write_text(TEST_TOML.replace('region = "TW"', 'region = "JP"'), encoding="utf-8")
    code, _, err = run(["update", "--config", str(config_path)])
    assert code == cli.EXIT_FAILED and "market.region" in err


def test_lock_held_exits_3(config_path, monkeypatch):
    data = config_path.parent / "data"
    data.mkdir()
    (data / ".lock").write_text("4242\n", encoding="utf-8")
    real_lock = cli.WriterLock
    monkeypatch.setattr(cli, "WriterLock", lambda path: real_lock(path, pid_alive=lambda pid: True))
    monkeypatch.setitem(cli.HANDLERS, "update", lambda ctx, args: cli.CommandResult(0, {}))

    code, _, err = run(["update", "--config", str(config_path)])
    assert code == cli.EXIT_LOCKED and "4242" in err
    assert (data / ".lock").read_text(encoding="utf-8").startswith("4242")  # foreign lock untouched


def test_handler_exception_exits_1_and_releases_lock(config_path, monkeypatch):
    def boom(ctx, args):
        raise RuntimeError("kaboom")

    monkeypatch.setitem(cli.HANDLERS, "update", boom)
    code, _, err = run(["update", "--config", str(config_path)])
    assert code == cli.EXIT_FAILED and "kaboom" in err
    assert not (config_path.parent / "data" / ".lock").exists()


def test_summary_json_and_exit_code_pass_through(config_path, monkeypatch):
    monkeypatch.setitem(cli.HANDLERS, "update",
                        lambda ctx, args: cli.CommandResult(cli.EXIT_PARTIAL, {"status": "partial"}))
    code, out, _ = run(["update", "--json", "--config", str(config_path)])
    assert code == cli.EXIT_PARTIAL and '"status": "partial"' in out


def test_coverage_command_reports_and_writes_escaped_csv(config_path):
    from datetime import UTC, datetime

    from sweetspot.store.writer import NewObservation, StoreWriter

    now = datetime(2026, 9, 25, tzinfo=UTC)
    writer = StoreWriter.open(config_path.parent / "data" / "sweetspot.db")
    run_id = writer.start_run("daily")
    writer.ensure_product(7, "reference-broad", now)
    writer.add_facts(run_id, 7, {"name": "=cmd|' /C calc'!A0"}, source="steam-appdetails", retrieved_at=now)
    writer.add_observations(run_id, [NewObservation(7, "itad-history", "TW", "TWD", 1000, 500, 50,
                                                    datetime(2025, 3, 13, tzinfo=UTC), None, now)])
    writer.close()
    out_csv = config_path.parent / "coverage.csv"
    code, out, _ = run(["coverage", "--scope", "reference", "--csv", str(out_csv), "--json", "--config",
                        str(config_path)])
    assert code == cli.EXIT_OK and '"available": 1' in out
    text = out_csv.read_text(encoding="utf-8-sig")
    assert "'=cmd" in text and ",=cmd" not in text


def test_coverage_only_reads(config_path, monkeypatch):
    """014 T070 (001 contracts/cli.md: coverage only reads, no lock): it opened a StoreWriter, which creates a missing
    database and migrates an old one, without the lock."""
    from sweetspot.store.writer import StoreWriter

    db = config_path.parent / "data" / "sweetspot.db"
    code, _, _ = run(["coverage", "--config", str(config_path)])
    assert code == cli.EXIT_FAILED and not db.exists()            # nothing to read: no database is made

    StoreWriter.open(db).close()
    opened = []
    real_open = StoreWriter.open
    monkeypatch.setattr(StoreWriter, "open", classmethod(lambda cls, *a, **k: opened.append(a) or real_open(*a, **k)))
    code, out, _ = run(["coverage", "--json", "--config", str(config_path)])
    assert code == cli.EXIT_OK and '"apps": 0' in out and opened == []
    assert not (config_path.parent / "data" / ".lock").exists()


# --- the result line in the daily log (2026-10-18) -------------------------------------------------------------------

def daily_log(config_path):
    import logging
    from datetime import datetime

    for handler in logging.getLogger("sweetspot").handlers:
        handler.flush()
    path = config_path.parent / "data" / "logs" / f"sweetspot-{datetime.now():%Y%m%d}.log"
    return path.read_text(encoding="utf-8")


def test_every_command_leaves_its_exit_code_in_the_daily_log(config_path, monkeypatch):
    monkeypatch.setitem(cli.HANDLERS, "update", lambda ctx, args: cli.CommandResult(
        cli.EXIT_PARTIAL, {"status": "completed", "failures": [{"app_id": 7}], "alerts": [], "http": {"x": 1}}))
    assert run(["update", "--config", str(config_path)])[0] == cli.EXIT_PARTIAL
    text = daily_log(config_path)
    assert "WARNING sweetspot.result: update 結束：代碼 2，" in text
    assert "；status=completed, failures=1 項, alerts=0 項" in text and "http" not in text
    assert 'update failures：[{"app_id": 7}]' in text


def test_a_failed_or_locked_run_is_logged_too(config_path, monkeypatch):
    def boom(ctx, args):
        raise RuntimeError("kaboom")

    monkeypatch.setitem(cli.HANDLERS, "update", boom)
    assert run(["update", "--config", str(config_path)])[0] == cli.EXIT_FAILED
    assert "update 結束：代碼 1，" in daily_log(config_path)
    assert "執行失敗：RuntimeError: kaboom" in daily_log(config_path)

    (config_path.parent / "data" / ".lock").write_text("4242\n", encoding="utf-8")
    real_lock = cli.WriterLock
    monkeypatch.setattr(cli, "WriterLock", lambda path: real_lock(path, pid_alive=lambda pid: True))
    assert run(["update", "--config", str(config_path)])[0] == cli.EXIT_LOCKED
    assert "update 結束：代碼 3，" in daily_log(config_path)


def test_a_source_failure_of_reference_says_it_resumes(config_path, monkeypatch):
    """014 T049 (001 contracts/cli.md `reference`): seen when the Steam store answered 502 for every page.
    The command adds the words to the exception (PEP 678 notes); the generic failure path prints any notes."""
    from sweetspot import commands
    from sweetspot.sources.errors import SourceError

    def outage(*args, **kwargs):
        raise SourceError("steam-store: HTTP 502 for https://store.steampowered.com/api/appdetails after 3 retries")

    monkeypatch.setattr(commands, "run_reference", outage)
    code, _, err = run(["reference", "--config", str(config_path)])
    assert code == cli.EXIT_FAILED
    assert "執行失敗：SourceError: steam-store: HTTP 502" in err and commands.REFERENCE_RESUME in err
    assert commands.REFERENCE_RESUME in daily_log(config_path)

    monkeypatch.setattr(commands, "run_daily", outage)                  # only reference resumes this way
    code, _, err = run(["update", "--config", str(config_path)])
    assert code == cli.EXIT_FAILED and commands.REFERENCE_RESUME not in err

    def bug(*args, **kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(commands, "run_reference", bug)                 # nor does a bug
    assert commands.REFERENCE_RESUME not in run(["reference", "--config", str(config_path)])[2]


def test_a_key_in_an_exception_note_is_masked_too(config_path, monkeypatch):
    """014 T057: since 7f27ef1 every exception's notes are added to the failure line; a library's note could hold a
    key (a request URL, say), so the notes are masked like the message."""
    from sweetspot.config import Secret

    key = "fake-" + "steam-" + "key-0123456789"
    monkeypatch.setattr(cli, "load_secrets", lambda: cli.Secrets(steam_web_api_key=Secret(key)))

    def boom(ctx, args):
        exc = RuntimeError(f"failed with {key}")
        exc.add_note(f"while asking https://api.example.com/?key={key}")
        raise exc

    monkeypatch.setitem(cli.HANDLERS, "update", boom)
    code, _, err = run(["update", "--config", str(config_path)])
    assert code == cli.EXIT_FAILED and "while asking" in err
    assert key not in err and err.count("***") == 2


def test_output_that_cannot_be_printed_is_logged_as_a_failure(config_path, monkeypatch):
    class Cp950Console(io.StringIO):
        def write(self, text):
            "≥".encode("cp950")

    monkeypatch.setitem(cli.HANDLERS, "forecast", lambda ctx, args: cli.CommandResult(0, {"games": 1}, text="≥"))
    with pytest.raises(UnicodeEncodeError):
        cli.main(["forecast", "--config", str(config_path)], stdout=Cp950Console(), stderr=io.StringIO())
    assert "forecast 結束：代碼 1，" in daily_log(config_path)
    assert "；輸出失敗：UnicodeEncodeError；games=1" in daily_log(config_path)
