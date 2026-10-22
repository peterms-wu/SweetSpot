"""The local program as Chrome starts it (feature 015 tasks T027; contracts/native-host.md "啟動", FR-013, FR-015).

Each test runs `python -m sweetspot.host` in a child process (through run_host.py, which keeps this machine's keys
out of reach) with a settings file in a temporary folder and a registration file naming one extension.
"""

import ast
import json
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from tests.config_builders import TEST_TOML

HOST_SRC = Path(__file__).resolve().parents[3] / "src" / "sweetspot" / "host"
RUNNER = Path(__file__).with_name("run_host.py")
ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop/"


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "sweetspot.toml"
    path.write_text(TEST_TOML.replace("[purchase_options]\n", '[purchase_options]\n1 = "bundle/900"\n'),
                    encoding="utf-8")
    host = tmp_path / "data" / "host"
    host.mkdir(parents=True)
    (host / "com.sweetspot.edition.json").write_text(json.dumps({"name": "com.sweetspot.edition",
                                                                 "allowed_origins": [ORIGIN]}), encoding="utf-8")
    return path


def frame(obj) -> bytes:
    body = json.dumps(obj).encode("utf-8")
    return struct.pack("=I", len(body)) + body


def run(config, stdin: bytes, *args, noisy=False):
    cmd = [sys.executable, str(RUNNER), *(["--noisy"] if noisy else []), "--config", str(config), *args]
    return subprocess.run(cmd, input=stdin, capture_output=True, timeout=60, cwd=config.parent)


def replies(stdout: bytes) -> list[dict]:
    out, rest = [], stdout
    while rest:
        assert len(rest) >= 4, stdout
        (size,) = struct.unpack("=I", rest[:4])
        assert len(rest) >= 4 + size, stdout
        out.append(json.loads(rest[4:4 + size].decode("utf-8")))
        rest = rest[4 + size:]
    return out


def host_log(config) -> list[str]:
    logs = sorted((config.parent / "data" / "logs").glob("sweetspot-*.log"))
    lines = [ln for p in logs for ln in p.read_text(encoding="utf-8").splitlines()]
    return [ln for ln in lines if "sweetspot.host" in ln]


STATUS = {"v": 1, "cmd": "status", "app": 1}


def test_a_status_request_gets_one_reply(config):
    p = run(config, frame(STATUS), ORIGIN, "--parent-window=0")
    assert p.returncode == 0, p.stderr.decode("utf-8", "replace")
    [reply] = replies(p.stdout)
    assert reply["ok"] is True and reply["choice"] == "bundle/900" and reply["config_ok"] is True
    assert len(host_log(config)) == 1 and "host status app=1 result=ok choice=bundle/900" in host_log(config)[0]


@pytest.mark.parametrize("origin", ["chrome-extension://pppppppppppppppppppppppppppppppp/", None,
                                    "https://store.steampowered.com/"])
def test_another_origin_is_refused_before_reading(config, origin):
    p = run(config, frame(STATUS), *([origin] if origin else []), "--parent-window=0")
    assert p.returncode == 1 and p.stdout == b""
    lines = host_log(config)
    assert len(lines) == 1 and "host refused origin=" in lines[0] and "not the registered extension" in lines[0]


def test_no_registration_file_refuses_every_origin(config):
    (config.parent / "data" / "host" / "com.sweetspot.edition.json").unlink()
    p = run(config, frame(STATUS), ORIGIN)
    assert p.returncode == 1 and p.stdout == b""


def test_stray_output_never_reaches_the_channel(config):
    p = run(config, frame(STATUS), ORIGIN, "--parent-window=0", noisy=True)
    assert p.returncode == 0
    [reply] = replies(p.stdout)                                        # exactly one well-formed frame
    assert reply["ok"] is True
    assert b"noise from print" in p.stderr and b"noise on fd 1" in p.stderr


def test_end_of_input_ends_quietly(config):
    p = run(config, b"", ORIGIN)
    assert p.returncode == 0 and p.stdout == b""


def test_a_malformed_frame_gets_one_refusal(config):
    p = run(config, struct.pack("=I", 513) + b" " * 513, ORIGIN)
    assert p.returncode == 0
    [reply] = replies(p.stdout)
    assert reply["code"] == "bad-request"


def test_a_missing_settings_file_is_not_created(tmp_path):
    missing = tmp_path / "sweetspot.toml"
    p = run(missing, frame(STATUS), ORIGIN)
    assert p.returncode == 1 and p.stdout == b"" and not missing.exists()


NETWORK = {"socket", "http", "httpx", "urllib", "requests", "ssl", "ftplib", "smtplib"}


def test_the_local_program_imports_no_network_module():
    """FR-013. Only direct imports of src/sweetspot/host/: the report it runs is the same code as `sweetspot
    report`, which does not use the network either (it only reads the database)."""
    seen = {}
    for path in sorted(HOST_SRC.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            for name in names:
                if name.split(".")[0] in NETWORK:
                    seen.setdefault(path.name, []).append(name)
    assert len(list(HOST_SRC.glob("*.py"))) >= 6
    assert seen == {}
