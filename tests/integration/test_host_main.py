"""The local program as Chrome starts it: `python -m sweetspot.host --config … <origin>` (015 contracts/native-host.md
「啟動」; 014 T067). The other host tests call service.handle directly and so never pass through __main__.

014 T067: with a settings file that cannot be read, __main__ ended before reading the request and answered nothing;
the extension then said to reinstall the local program, which cannot fix it (015 FR-017: say to fix the file first).
"""

import json
import struct
import subprocess
import sys

import pytest

from sweetspot.host import install
from tests.config_builders import TEST_TOML

ORIGIN = "chrome-extension://" + "a" * 32 + "/"


def folder_with(tmp_path, settings: bytes | None, origins=(ORIGIN,)):
    if settings is not None:
        (tmp_path / "sweetspot.toml").write_bytes(settings)
    host = tmp_path / "data" / "host"
    host.mkdir(parents=True)
    (host / f"{install.NAME}.json").write_text(json.dumps({"name": install.NAME, "allowed_origins": list(origins)}),
                                               encoding="utf-8")
    return tmp_path / "sweetspot.toml"


def ask(config, request: dict, origin=ORIGIN):
    body = json.dumps(request).encode("utf-8")
    done = subprocess.run([sys.executable, "-m", "sweetspot.host", "--config", str(config), origin],
                          input=struct.pack("=I", len(body)) + body, capture_output=True, timeout=60)
    reply = None
    if len(done.stdout) >= 4:
        (size,) = struct.unpack("=I", done.stdout[:4])
        reply = json.loads(done.stdout[4:4 + size].decode("utf-8"))
    return done, reply


STATUS = {"v": 1, "cmd": "status", "app": 10}
CHOOSE = {"v": 1, "cmd": "choose", "app": 10, "option": "sub/1"}
BROKEN = {
    "not toml": TEST_TOML.encode("utf-8") + b"\nthis is not toml\n",
    "not utf-8": TEST_TOML.encode("cp950", "replace") + "\n# 註解\n".encode("cp950"),
    "a bom": b"\xef\xbb\xbf" + TEST_TOML.encode("utf-8"),
    "an empty url": TEST_TOML.replace(TEST_TOML.split('url = "')[1].split('"')[0], "").encode("utf-8"),
}


def test_a_readable_settings_file_is_answered(tmp_path):
    config = folder_with(tmp_path, TEST_TOML.encode("utf-8"))
    done, reply = ask(config, STATUS)
    assert reply is not None, done.stderr.decode("utf-8", "replace")
    assert reply["ok"] is True and reply["config_ok"] is True


@pytest.mark.parametrize("kind", ["not toml", "not utf-8", "a bom", "missing"])
def test_a_status_with_a_broken_settings_file_says_to_fix_it(tmp_path, kind):
    config = folder_with(tmp_path, None if kind == "missing" else BROKEN[kind])
    done, reply = ask(config, STATUS)
    assert reply is not None, f"no answer ({kind}): {done.stderr.decode('utf-8', 'replace')}"
    assert reply["ok"] is True and reply["config_ok"] is False and "sweetspot.toml" in reply["message"]


@pytest.mark.parametrize("kind", ["not toml", "not utf-8", "a bom", "an empty url", "missing"])
def test_a_change_with_a_broken_settings_file_is_config_invalid(tmp_path, kind):
    config = folder_with(tmp_path, None if kind == "missing" else BROKEN[kind])
    done, reply = ask(config, CHOOSE)
    assert reply is not None, f"no answer ({kind}): {done.stderr.decode('utf-8', 'replace')}"
    assert reply["ok"] is False and reply["code"] == "config-invalid" and "sweetspot.toml" in reply["message"]
    assert b"Traceback" not in done.stderr


@pytest.mark.parametrize("settings", [TEST_TOML.encode("utf-8"), BROKEN["not toml"]])
def test_an_origin_not_registered_gets_no_answer(tmp_path, settings):
    """The origin is checked first, from the registration file, whether or not the settings file can be read."""
    config = folder_with(tmp_path, settings)
    done, reply = ask(config, STATUS, origin="chrome-extension://" + "b" * 32 + "/")
    assert reply is None and done.returncode == 1
