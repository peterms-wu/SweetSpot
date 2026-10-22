"""Installing and removing the local program (feature 015 tasks T014; data-model §3; contracts/native-host.md
"sweetspot host 指令"). The registry is a fake: no test writes the real one."""

import base64
import hashlib
import json
import sys
from pathlib import Path

import pytest

from sweetspot.config import load_config
from tests.config_builders import TEST_TOML
from sweetspot.host import install
from tests.host_builders import ROOT

KEY = "Software\\Google\\Chrome\\NativeMessagingHosts\\com.sweetspot.edition"


class FakeRegistry:
    def __init__(self, fail: bool = False):
        self.values: dict[str, str] = {}
        self.fail = fail

    def set_default(self, key: str, value: str) -> None:
        if self.fail:
            raise PermissionError("denied")
        self.values[key] = value

    def get_default(self, key: str) -> str | None:
        return self.values.get(key)

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "sweetspot.toml"
    path.write_text(TEST_TOML, encoding="utf-8")
    (tmp_path / "extension").mkdir()
    (tmp_path / "extension" / "manifest.json").write_bytes((ROOT / "extension" / "manifest.json").read_bytes())
    return load_config(path)[0]


def test_the_extension_id_comes_from_the_manifest_key():
    raw = b"any public key bytes"
    want = "".join(chr(ord("a") + int(c, 16)) for c in hashlib.sha256(raw).hexdigest()[:32])
    assert install.extension_id(base64.b64encode(raw).decode()) == want
    key = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))["key"]
    assert install.extension_id(key) == "ecomigpdpdmcjbndhgiojplbaohkmhcm"   # printed when the key was made (T002)


def test_install_writes_the_launcher_the_registration_and_the_key(config):
    reg = FakeRegistry()
    result = install.install(config, registry=reg, python=Path(sys.executable), encoding="cp950")
    host = config.data_dir / "host"
    bat, manifest = host / "sweetspot-host.bat", host / "com.sweetspot.edition.json"
    assert bat.read_bytes() == (f'@"{sys.executable}" -m sweetspot.host --config "{config.path.resolve()}" %*\r\n'
                                .encode("cp950"))
    m = json.loads(manifest.read_text(encoding="utf-8"))
    assert m == {"name": "com.sweetspot.edition", "description": install.DESCRIPTION, "path": str(bat.resolve()),
                 "type": "stdio", "allowed_origins": ["chrome-extension://ecomigpdpdmcjbndhgiojplbaohkmhcm/"]}
    assert reg.values == {KEY: str(manifest.resolve())}
    assert result["extension_id"] == "ecomigpdpdmcjbndhgiojplbaohkmhcm"
    text = "\n".join(result["lines"])
    for phrase in ("只接受三種指令", "只改 [purchase_options] 中那一款遊戲的那一行", "重新產生報告", "不能改其他設定",
                   "不能讀寫其他檔案", "不連網", "重新載入"):
        assert phrase in text, phrase


def test_install_again_overwrites(config):
    reg = FakeRegistry()
    install.install(config, registry=reg, python=Path(sys.executable), encoding="cp950")
    other = Path(sys.executable).with_name("other-python.exe")
    install.install(config, registry=reg, python=other, encoding="cp950")
    assert f'@"{other}"'.encode("cp950") in (config.data_dir / "host" / "sweetspot-host.bat").read_bytes()
    assert len(reg.values) == 1


def test_a_path_the_code_page_cannot_hold_is_refused_and_nothing_is_left(config):
    reg = FakeRegistry()
    with pytest.raises(install.InstallError, match="字碼頁"):
        install.install(config, registry=reg, python=Path("C:/工具/python.exe"), encoding="ascii")
    assert not (config.data_dir / "host").exists() and reg.values == {}


def test_a_registry_failure_leaves_no_files(config):
    with pytest.raises(install.InstallError, match="登錄"):
        install.install(config, registry=FakeRegistry(fail=True), python=Path(sys.executable), encoding="cp950")
    assert not (config.data_dir / "host").exists()


def test_without_a_manifest_key_install_is_refused(config):
    (config.extension_dir / "manifest.json").write_text('{"manifest_version": 3}', encoding="utf-8")
    with pytest.raises(install.InstallError, match="key"):
        install.install(config, registry=FakeRegistry(), python=Path(sys.executable), encoding="cp950")


def test_uninstall_removes_the_key_and_the_folder_only(config):
    reg = FakeRegistry()
    reg.values["Software\\Other"] = "keep"
    install.install(config, registry=reg, python=Path(sys.executable), encoding="cp950")
    (config.data_dir / "sweetspot-keep.txt").write_text("x", encoding="utf-8")
    install.uninstall(config, registry=reg)
    assert reg.values == {"Software\\Other": "keep"}
    assert not (config.data_dir / "host").exists() and (config.data_dir / "sweetspot-keep.txt").exists()
    install.uninstall(config, registry=reg)                       # nothing installed: still fine


def test_uninstall_keeps_a_settings_file_set_aside_by_a_failed_restore(config):
    """service._restore keeps the original settings file in data/host/restore-*.toml when it cannot write it
    back; that may be the only copy, so uninstall removes only what install wrote."""
    reg = FakeRegistry()
    install.install(config, registry=reg, python=Path(sys.executable), encoding="cp950")
    host = config.data_dir / "host"
    aside = host / "restore-20251014T120000Z.toml"
    aside.write_bytes(b"[purchase_options]\n1 = \"bundle/900\"\n")
    (host / "notes.txt").write_text("mine", encoding="utf-8")
    result = install.uninstall(config, registry=reg)
    assert reg.values == {}
    assert sorted(p.name for p in host.iterdir()) == ["notes.txt", "restore-20251014T120000Z.toml"]
    assert aside.read_bytes() == b"[purchase_options]\n1 = \"bundle/900\"\n"
    assert any("restore-20251014T120000Z.toml" in line and "保留" in line for line in result["lines"]), result["lines"]


def test_status(config):
    reg = FakeRegistry()
    assert install.status(config, registry=reg) == {
        "registered": False, "manifest": False, "launcher": False, "extension_id": None, "python": None,
        "python_exists": False}
    install.install(config, registry=reg, python=Path(sys.executable), encoding="cp950")
    assert install.status(config, registry=reg) == {
        "registered": True, "manifest": True, "launcher": True, "extension_id": "ecomigpdpdmcjbndhgiojplbaohkmhcm",
        "python": sys.executable, "python_exists": True}


def test_registration_here_elsewhere_or_none(config, tmp_path):
    """Feature 016: migrate rewrites the launcher only for "here"; status' "registered" is the same test."""
    reg = FakeRegistry()
    assert install.registration(config, registry=reg) == "none"
    install.install(config, registry=reg, python=Path(sys.executable), encoding="cp950")
    assert install.registration(config, registry=reg) == "here"
    install.manifest_path(config).unlink()                     # the key still names this folder's file
    assert install.registration(config, registry=reg) == "none"
    reg.values[install.REG_KEY] = str(tmp_path / "elsewhere" / "data" / "host" / f"{install.NAME}.json")
    assert install.registration(config, registry=reg) == "elsewhere"


def test_the_registered_origin_is_what_the_host_reads(config):
    install.install(config, registry=FakeRegistry(), python=Path(sys.executable), encoding="cp950")
    assert install.allowed_origins(config) == ["chrome-extension://ecomigpdpdmcjbndhgiojplbaohkmhcm/"]
    (config.data_dir / "host" / "com.sweetspot.edition.json").unlink()
    assert install.allowed_origins(config) == []
