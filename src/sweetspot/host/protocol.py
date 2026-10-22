"""Native messaging frames and the request format (feature 015, contracts/native-host.md "訊息格式").

A frame is a 4-byte length in native byte order followed by UTF-8 JSON. Requests are small and have exactly the
fields of their command; anything else is a BadRequest, which carries only the size (for the log), never content.
"""

import json
import re
import struct
from typing import Any, BinaryIO, NamedTuple

MAX_REQUEST = 512            # bytes (contracts/native-host.md)
MAX_REPLY = 4096
MAX_ID = 2147483647
VERSION = 1
FIELDS = {"status": {"v", "cmd", "app"}, "reset": {"v", "cmd", "app"}, "choose": {"v", "cmd", "app", "option"}}
_OPTION = re.compile(r"(sub|bundle)/([1-9][0-9]{0,9})")
_HEADER = struct.Struct("=I")


class BadRequest(Exception):
    def __init__(self, reason: str, size: int | None = None):
        super().__init__(reason)
        self.reason = reason
        self.size = size


class Request(NamedTuple):
    cmd: str
    app: int
    option: tuple[str, int] | None


def _no_repeats(pairs: list[tuple[str, Any]]) -> dict:
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("repeated key")
    return dict(pairs)


def _no_constants(name: str):
    raise ValueError(f"{name} is not JSON")


def read_message(stream: BinaryIO) -> dict | None:
    """One request object, or None at end of input. An oversized frame is refused before its body is read."""
    head = stream.read(_HEADER.size)
    if len(head) < _HEADER.size:
        return None
    (size,) = _HEADER.unpack(head)
    if size > MAX_REQUEST:
        raise BadRequest("too long", size)
    body = stream.read(size)
    if len(body) < size:
        raise BadRequest("short body", size)
    try:
        obj = json.loads(body.decode("utf-8"), object_pairs_hook=_no_repeats, parse_constant=_no_constants)
    except (UnicodeDecodeError, ValueError):
        raise BadRequest("not JSON", size) from None
    if not isinstance(obj, dict):
        raise BadRequest("not an object", size)
    return obj


def write_message(stream: BinaryIO, obj: dict) -> None:
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_REPLY:
        raise ValueError(f"reply of {len(data)} bytes is over {MAX_REPLY}")
    stream.write(_HEADER.pack(len(data)) + data)
    stream.flush()


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate(obj: dict) -> Request:
    """The request's command, app and option; BadRequest for anything that is not exactly one of the three forms."""
    cmd = obj.get("cmd")
    if not isinstance(cmd, str) or cmd not in FIELDS:
        raise BadRequest("unknown command")
    if set(obj) != FIELDS[cmd]:
        raise BadRequest("wrong fields")
    if not _is_int(obj["v"]) or obj["v"] != VERSION:
        raise BadRequest("wrong version")
    app = obj["app"]
    if not _is_int(app) or not 1 <= app <= MAX_ID:
        raise BadRequest("bad app")
    option = None
    if cmd == "choose":
        value = obj["option"]
        match = _OPTION.fullmatch(value) if isinstance(value, str) else None
        if match is None or int(match.group(2)) > MAX_ID:
            raise BadRequest("bad option")
        option = (match.group(1), int(match.group(2)))
    return Request(cmd, app, option)
