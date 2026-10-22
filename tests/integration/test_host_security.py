"""Wrong or hostile requests to the local program (feature 015 tasks T025; spec US3, SC-002, FR-013-FR-017).

Every request goes through the channel the way Chrome sends it (a 4-byte length, then the body) and is refused
with the right code; the settings file, the database, latest.html, the extension data file and data/forecasts/
stay byte for byte; the log names the reason, a malformed request only by its size; fake API keys appear in no
reply, log line or stderr.
"""

import io
import json
import logging
import socket
import struct

import pytest

from sweetspot import cli, commands
from sweetspot.config import Secret
from tests.config_builders import TEST_TOML
from sweetspot.host import service
from tests.forecast_builders import dt
from tests.host_builders import APP, GONE, make_env
from tests.report_builders import run_report

ITAD_FAKE = "itad-FAKE-0123456789abcdef"
STEAM_FAKE = "STEAMFAKE0123456789ABCDEF"


def frame(body: bytes, size: int | None = None) -> bytes:
    return struct.pack("=I", len(body) if size is None else size) + body


def req(**fields) -> bytes:
    return frame(json.dumps(fields).encode("utf-8"))


def choose(option, app=APP) -> bytes:
    return req(v=1, cmd="choose", app=app, option=option)


BROKEN_TOML = TEST_TOML + "[purchase_options\n"
assert TEST_TOML.count("[purchase_options]\n") == 1
TWICE_TOML = TEST_TOML.replace("[purchase_options]\n",                    # app 1 written two ways
                                  '[purchase_options]\n"0001" = "sub/100"\n1 = "bundle/900"\n')

# (case, frame, settings file or None for the default, expected code)
CASES = [
    ("unknown command", req(v=1, cmd="delete", app=APP), None, "bad-request"),
    ("command carrying a key", req(v=1, cmd=ITAD_FAKE, app=APP), None, "bad-request"),
    ("an extra path field", req(v=1, cmd="status", app=APP, path="C:/Windows/win.ini"), None, "bad-request"),
    ("an extra field on choose", req(v=1, cmd="choose", app=APP, option="bundle/900", args=["--as-of"]), None,
     "bad-request"),
    ("no app", req(v=1, cmd="status"), None, "bad-request"),
    ("protocol version 2", req(v=2, cmd="status", app=APP), None, "bad-request"),
    ("app as a string", req(v=1, cmd="status", app="1"), None, "bad-request"),
    ("app as a boolean", req(v=1, cmd="status", app=True), None, "bad-request"),
    ("app 0", req(v=1, cmd="status", app=0), None, "bad-request"),
    ("app negative", req(v=1, cmd="reset", app=-1), None, "bad-request"),
    ("app 2147483648", req(v=1, cmd="reset", app=2147483648), None, "bad-request"),
    ("option sub/0", choose("sub/0"), None, "bad-request"),
    ("option bundle/01", choose("bundle/01"), None, "bad-request"),
    ("option with a path", choose("sub/1/../x"), None, "bad-request"),
    ("option of another kind", choose("pkg/1"), None, "bad-request"),
    ("option with a space", choose("sub/ 1"), None, "bad-request"),
    ("option id too large", choose("sub/99999999999"), None, "bad-request"),
    ("option not a string", req(v=1, cmd="choose", app=APP, option=900), None, "bad-request"),
    ("request of 513 bytes", frame(b"{" + b" " * 511 + b"}"), None, "bad-request"),
    ("length over the limit, no body", frame(b"", size=1 << 30), None, "bad-request"),
    ("body shorter than its length", frame(b'{"v":1}', size=40), None, "bad-request"),
    ("not UTF-8", frame(b'{"v":1,"cmd":"status","app":\xff}'), None, "bad-request"),
    ("a JSON array", frame(b'[1,"status",1]'), None, "bad-request"),
    ("a repeated key", frame(b'{"v":1,"cmd":"status","app":1,"app":2}'), None, "bad-request"),
    ("NaN", frame(b'{"v":1,"cmd":"status","app":NaN}'), None, "bad-request"),
    ("a game outside the wishlist", choose("sub/100", app=GONE), None, "not-tracked"),
    ("reset for a game outside the wishlist", req(v=1, cmd="reset", app=GONE), None, "not-tracked"),
    ("a game the database does not know", req(v=1, cmd="reset", app=424242), None, "not-tracked"),
    ("an option not in the purchase records", choose("sub/12345"), None, "not-choosable"),
    ("an edition whose ITAD check failed", choose("sub/902"), None, "not-choosable"),
    ("an option that is not an edition", choose("bundle/901"), None, "not-choosable"),
    ("a settings file that does not parse", choose("bundle/900"), BROKEN_TOML, "config-invalid"),
    ("the game written twice", choose("bundle/900"), TWICE_TOML, "config-unsafe"),
]


def test_at_least_twenty_kinds():
    assert len(CASES) >= 20                                            # spec SC-002
    assert len({c[0] for c in CASES}) == len(CASES)


@pytest.mark.parametrize("case, raw, toml, code", CASES, ids=[c[0] for c in CASES])
def test_refused_and_nothing_changes(case, raw, toml, code, tmp_path, monkeypatch, caplog, capsys):
    env = make_env(tmp_path, monkeypatch)
    assert run_report(env.config)[0] == 0                              # latest.html and the data file exist
    if toml is not None:
        env.config.write_bytes(toml.encode("utf-8"))
    monkeypatch.setattr(cli, "load_secrets", lambda: cli.Secrets(Secret(ITAD_FAKE), Secret(STEAM_FAKE)))
    before = env.snapshot()
    caplog.clear()
    capsys.readouterr()

    with caplog.at_level(logging.INFO, logger="sweetspot.host"):
        reply = service.answer(io.BytesIO(raw), config_path=env.config)

    assert reply["ok"] is False and reply["code"] == code, reply
    assert env.snapshot() == before
    assert not (env.data / ".host.lock").exists() and not (env.data / ".lock").exists()
    lines = [r.getMessage() for r in caplog.records if r.name == "sweetspot.host"]
    assert len(lines) == 1 and f"code={code}" in lines[0] and "result=rejected" in lines[0], lines
    if code == "bad-request":                                          # only the size, never the content
        assert lines[0].startswith("host request result=rejected code=bad-request bytes=")
        assert reply["message"] == service.MESSAGES["bad-request"]
    else:
        assert lines[0].startswith(f"host {'reset' if b'reset' in raw else 'choose'} app=")
    seen = json.dumps(reply, ensure_ascii=False) + "\n".join(lines) + "".join(capsys.readouterr())
    assert ITAD_FAKE not in seen and STEAM_FAKE not in seen


def test_a_choice_and_its_report_open_no_connection(tmp_path, monkeypatch):
    """FR-013 at run time: the host's own imports are checked in tests/unit/host/test_main.py; this covers the
    report it runs (sweetspot.commands imports httpx for `update`)."""
    env = make_env(tmp_path, monkeypatch)
    assert run_report(env.config)[0] == 0
    tried = []

    def refuse(*args, **kwargs):
        tried.append(args)
        raise OSError("no network in this test")

    monkeypatch.setattr(commands, "NOW", lambda: dt("2025-08-01T12:00"))   # a new record name
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    reply = service.answer(io.BytesIO(choose("bundle/900")), config_path=env.config)
    assert reply["ok"] is True and reply["changed"] is True and tried == []


def test_status_never_writes(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    assert run_report(env.config)[0] == 0
    for toml in (None, BROKEN_TOML, TWICE_TOML):
        if toml is not None:
            env.config.write_bytes(toml.encode("utf-8"))
        before = env.snapshot()
        for app in (APP, GONE, 424242):
            reply = service.answer(io.BytesIO(req(v=1, cmd="status", app=app)), config_path=env.config)
            assert reply["ok"] is True and reply["cmd"] == "status"
        assert env.snapshot() == before


def test_end_of_input_is_not_a_request(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    for raw in (b"", b"\x01\x00"):
        assert service.answer(io.BytesIO(raw), config_path=env.config) is None
