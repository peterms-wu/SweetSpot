"""The native messaging frames and the request format (feature 015 tasks T003; contracts/native-host.md)."""

import io
import json
import struct

import pytest

from sweetspot.host import protocol
from sweetspot.host.protocol import BadRequest, Request


def frame(payload: bytes | str | dict) -> bytes:
    if isinstance(payload, dict):
        payload = json.dumps(payload)
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return struct.pack("=I", len(payload)) + payload


class Reader(io.BytesIO):
    """Counts how many bytes were read, so a test can see the rest of an oversized request was left alone."""


def test_reads_one_message():
    stream = io.BytesIO(frame({"v": 1, "cmd": "status", "app": 10}))
    assert protocol.read_message(stream) == {"v": 1, "cmd": "status", "app": 10}


@pytest.mark.parametrize("raw", [b"", b"\x01", b"\x01\x00\x00"])
def test_eof_before_a_full_header_is_none(raw):
    assert protocol.read_message(io.BytesIO(raw)) is None


def test_an_oversized_request_is_refused_without_reading_it():
    body = json.dumps({"v": 1, "cmd": "status", "app": 1, "pad": "x" * 600}).encode()
    stream = Reader(struct.pack("=I", len(body)) + body)
    with pytest.raises(BadRequest) as info:
        protocol.read_message(stream)
    assert info.value.size == len(body)
    assert stream.tell() == 4                       # only the header


def test_the_limit_itself_is_allowed():
    body = json.dumps({"v": 1, "cmd": "status", "app": 1, "pad": ""}).encode()
    body = body[:-2] + b" " * (protocol.MAX_REQUEST - len(body)) + body[-2:]
    assert len(body) == protocol.MAX_REQUEST
    assert protocol.read_message(io.BytesIO(frame(body)))["app"] == 1


@pytest.mark.parametrize("body", [
    b"\xff\xfe{}",                                  # not UTF-8
    b"{not json",
    b"[1, 2]",                                      # not an object
    b'"text"',
    b'{"v": 1, "v": 2, "cmd": "status", "app": 1}',  # a repeated key could hide a value
    b'{"v": 1, "cmd": "status", "app": NaN}',
])
def test_bad_bodies(body):
    with pytest.raises(BadRequest) as info:
        protocol.read_message(io.BytesIO(frame(body)))
    assert info.value.size == len(body)


def test_a_short_body_is_bad():
    with pytest.raises(BadRequest):
        protocol.read_message(io.BytesIO(struct.pack("=I", 40) + b'{"v": 1}'))


def test_write_message_frames_utf8_json():
    out = io.BytesIO()
    protocol.write_message(out, {"ok": False, "message": "背景更新進行中"})
    raw = out.getvalue()
    (size,) = struct.unpack("=I", raw[:4])
    assert size == len(raw) - 4
    assert json.loads(raw[4:].decode("utf-8")) == {"ok": False, "message": "背景更新進行中"}
    assert "背景".encode("utf-8") in raw             # not \\u escapes


def test_a_reply_over_4_kb_is_a_program_error():
    with pytest.raises(ValueError):
        protocol.write_message(io.BytesIO(), {"message": "x" * protocol.MAX_REPLY})


# --- validate -----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("obj, want", [
    ({"v": 1, "cmd": "status", "app": 1091500}, Request("status", 1091500, None)),
    ({"v": 1, "cmd": "reset", "app": 1091500}, Request("reset", 1091500, None)),
    ({"v": 1, "cmd": "choose", "app": 1091500, "option": "bundle/32470"}, Request("choose", 1091500, ("bundle", 32470))),
    ({"v": 1, "cmd": "choose", "app": 1, "option": "sub/2147483647"}, Request("choose", 1, ("sub", 2147483647))),
    ({"v": 1, "cmd": "status", "app": 2147483647}, Request("status", 2147483647, None)),
])
def test_valid_requests(obj, want):
    assert protocol.validate(obj) == want


@pytest.mark.parametrize("obj", [
    {"v": 1, "cmd": "delete", "app": 1},                               # unknown command
    {"v": 1, "cmd": 1, "app": 1},
    {"v": 1, "cmd": "status", "app": 1, "path": "C:/x"},               # an extra field
    {"v": 1, "cmd": "status", "app": 1, "option": "sub/1"},            # option on a command without it
    {"v": 1, "cmd": "reset", "app": 1, "option": "sub/1"},
    {"v": 1, "cmd": "choose", "app": 1},                               # a missing field
    {"v": 1, "cmd": "status"},
    {"cmd": "status", "app": 1},
    {"v": 2, "cmd": "status", "app": 1},
    {"v": "1", "cmd": "status", "app": 1},
    {"v": True, "cmd": "status", "app": 1},
    {"v": 1, "cmd": "status", "app": "1091500"},
    {"v": 1, "cmd": "status", "app": True},
    {"v": 1, "cmd": "status", "app": 1.0},
    {"v": 1, "cmd": "status", "app": 0},
    {"v": 1, "cmd": "status", "app": -5},
    {"v": 1, "cmd": "status", "app": 2147483648},
    {"v": 1, "cmd": "choose", "app": 1, "option": "sub/0"},
    {"v": 1, "cmd": "choose", "app": 1, "option": "bundle/01"},
    {"v": 1, "cmd": "choose", "app": 1, "option": "sub/1/../x"},
    {"v": 1, "cmd": "choose", "app": 1, "option": "pkg/1"},
    {"v": 1, "cmd": "choose", "app": 1, "option": "sub/ 1"},
    {"v": 1, "cmd": "choose", "app": 1, "option": "SUB/1"},
    {"v": 1, "cmd": "choose", "app": 1, "option": "sub/1\n"},
    {"v": 1, "cmd": "choose", "app": 1, "option": "sub/99999999999"},
    {"v": 1, "cmd": "choose", "app": 1, "option": "sub/2147483648"},
    {"v": 1, "cmd": "choose", "app": 1, "option": ["sub", 1]},
])
def test_invalid_requests(obj):
    with pytest.raises(BadRequest):
        protocol.validate(obj)
