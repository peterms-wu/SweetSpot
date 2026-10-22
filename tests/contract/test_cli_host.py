"""`sweetspot host install|uninstall|status` (feature 015 tasks T014; contracts/native-host.md)."""

import io
import json

import pytest

from sweetspot import cli
from tests.config_builders import TEST_TOML
from sweetspot.host import install
from tests.host_builders import ROOT
from tests.unit.host.test_install import KEY, FakeRegistry


@pytest.fixture
def setup(tmp_path, monkeypatch):
    config = tmp_path / "sweetspot.toml"
    config.write_text(TEST_TOML, encoding="utf-8")
    (tmp_path / "extension").mkdir()
    (tmp_path / "extension" / "manifest.json").write_bytes((ROOT / "extension" / "manifest.json").read_bytes())
    reg = FakeRegistry()
    monkeypatch.setattr(install, "default_registry", lambda: reg)
    monkeypatch.setattr(cli, "load_secrets", lambda: cli.Secrets())
    opened = []
    monkeypatch.setattr(cli.StoreWriter, "open", lambda *a, **k: opened.append(a) or pytest.fail("no database"))
    return config, reg


def run(config, *args):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(["host", *args, "--config", str(config)], stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_install_status_uninstall(setup):
    config, reg = setup
    code, out, _ = run(config, "install")
    assert code == 0 and "只接受三種指令" in out and "ecomigpdpdmcjbndhgiojplbaohkmhcm" in out
    assert KEY in reg.values
    assert not (config.parent / "data" / ".lock").exists()          # no writer lock taken
    code, out, _ = run(config, "status", "--json")
    assert code == 0 and json.loads(out)["registered"] is True
    code, out, _ = run(config, "uninstall")
    assert code == 0 and reg.values == {}
    code, out, _ = run(config, "status", "--json")
    assert json.loads(out)["registered"] is False


def test_a_failed_install_exits_1(setup, monkeypatch):
    config, _ = setup
    monkeypatch.setattr(install, "default_registry", lambda: FakeRegistry(fail=True))
    code, _, err = run(config, "install")
    assert code == 1 and "登錄" in err
