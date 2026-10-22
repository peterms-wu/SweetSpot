"""Install and remove the local program for this Windows user (feature 015; data-model §3, contracts/native-host.md
"sweetspot host 指令"; spec FR-022). Only data/host/ and one HKCU registry key are written; the registry is behind
a small class so tests use a fake one."""

import base64
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

from sweetspot.config import Config

NAME = "com.sweetspot.edition"
REG_KEY = f"Software\\Google\\Chrome\\NativeMessagingHosts\\{NAME}"
DESCRIPTION = "SweetSpot：在 Steam 遊戲頁指定追蹤版本（只改 sweetspot.toml 的 [purchase_options] 一行並重新產生報告）"
_LAUNCHER_PYTHON = re.compile(r'^@"([^"]+)"')


class InstallError(Exception):
    pass


class WinRegistry:
    """The default value of keys under HKEY_CURRENT_USER (no administrator rights needed)."""

    def set_default(self, key: str, value: str) -> None:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, value)

    def get_default(self, key: str) -> str | None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                return str(winreg.QueryValueEx(k, "")[0])
        except OSError:
            return None

    def delete(self, key: str) -> None:
        import winreg

        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        except FileNotFoundError:
            pass


def default_registry() -> WinRegistry:
    if sys.platform != "win32":
        raise InstallError("本機程式只支援 Windows")
    return WinRegistry()


def host_dir(config: Config) -> Path:
    return config.data_dir / "host"


def manifest_path(config: Config) -> Path:
    return host_dir(config) / f"{NAME}.json"


def launcher_path(config: Config) -> Path:
    return host_dir(config) / "sweetspot-host.bat"


def extension_id(key: str) -> str:
    """Chrome's id for an extension with this manifest key: sha256 of the public key, 32 hex digits as a-p."""
    digest = hashlib.sha256(base64.b64decode(key)).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in digest)


def oem_encoding() -> str:
    """cmd.exe reads a batch file in the console (OEM) code page (research R2)."""
    if sys.platform != "win32":
        raise InstallError("本機程式只支援 Windows")
    import ctypes

    return f"cp{ctypes.windll.kernel32.GetOEMCP()}"


def _manifest_key(config: Config) -> str:
    path = config.extension_dir / "manifest.json"
    try:
        key = json.loads(path.read_text(encoding="utf-8")).get("key")
    except (OSError, ValueError):
        key = None
    if not isinstance(key, str) or not key:
        raise InstallError(f"{path} 沒有 key，無法決定擴充功能編號")
    return key


def allowed_origins(config: Config) -> list[str]:
    """The origins in the installed registration file (what the host checks Chrome's argument against)."""
    return allowed_origins_in(config.data_dir)


def allowed_origins_in(data_dir: Path) -> list[str]:
    """The same, for a data folder known without a valid settings file (014 T067)."""
    try:
        origins = json.loads((data_dir / "host" / f"{NAME}.json").read_text(encoding="utf-8")).get("allowed_origins")
    except (OSError, ValueError, AttributeError):
        return []
    return [o for o in origins or [] if isinstance(o, str)]


def install(config: Config, *, registry=None, python: Path | None = None, encoding: str | None = None) -> dict:
    registry = registry or default_registry()
    python = Path(python or sys.executable)
    encoding = encoding or oem_encoding()
    ext_id = extension_id(_manifest_key(config))
    launcher, manifest = launcher_path(config), manifest_path(config)
    text = f'@"{python}" -m sweetspot.host --config "{config.path.resolve()}" %*\r\n'
    try:
        launcher_bytes = text.encode(encoding)
    except UnicodeEncodeError:
        raise InstallError(f"路徑中有系統字碼頁（{encoding}）無法表示的字元，cmd.exe 無法執行：{python}、{config.path}") from None
    folder = host_dir(config)
    created = not folder.exists()
    folder.mkdir(parents=True, exist_ok=True)
    try:
        launcher.write_bytes(launcher_bytes)
        manifest.write_text(json.dumps({"name": NAME, "description": DESCRIPTION, "path": str(launcher.resolve()),
                                        "type": "stdio", "allowed_origins": [f"chrome-extension://{ext_id}/"]},
                                       ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        registry.set_default(REG_KEY, str(manifest.resolve()))
    except OSError as exc:
        if created:
            shutil.rmtree(folder, ignore_errors=True)
        else:
            launcher.unlink(missing_ok=True)
            manifest.unlink(missing_ok=True)
        raise InstallError(f"登錄或檔案寫入失敗：{exc}") from None
    lines = [
        f"已安裝本機程式 {NAME}（只允許 SweetSpot 擴充功能 {ext_id}）",
        "它只接受三種指令：查詢狀態、指定版本、改回 Steam 預設。",
        "指定或改回時，它只改 [purchase_options] 中那一款遊戲的那一行，然後重新產生報告（和手動執行 report 相同）。",
        "它不能改其他設定、不能讀寫其他檔案或執行其他程式、不連網、不開任何連接埠。",
        "第一次安裝後，請在 chrome://extensions 對 SweetSpot 按「重新載入」，確認編號和上面相同。",
        f"啟動檔：{launcher}",
        f"登記檔：{manifest}",
    ]
    return {"extension_id": ext_id, "launcher": str(launcher), "manifest": str(manifest), "lines": lines}


def uninstall(config: Config, *, registry=None) -> dict:
    registry = registry or default_registry()
    try:
        registry.delete(REG_KEY)
    except OSError as exc:
        raise InstallError(f"登錄刪除失敗：{exc}") from None
    # Only what install wrote: a failed restore keeps the original settings file in this folder (service._restore).
    for path in (launcher_path(config), manifest_path(config)):
        path.unlink(missing_ok=True)
    folder = host_dir(config)
    left = sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []
    if folder.is_dir() and not left:
        folder.rmdir()
    lines = [f"已移除本機程式 {NAME} 的登錄、啟動檔與登記檔"]
    if left:
        lines.append(f"{folder} 中其他檔案保留：{'、'.join(left)}")
    return {"lines": lines}


def registration(config: Config, *, registry=None) -> str:
    """Where Chrome is pointed for this host name: "here" (this folder's registration file), "elsewhere" (another
    folder's), or "none" (no key, or the key names this folder's file but the file is gone)."""
    registry = registry or default_registry()
    value, manifest = registry.get_default(REG_KEY), manifest_path(config)
    if value is None:
        return "none"
    if value == str(manifest.resolve()):
        return "here" if manifest.exists() else "none"
    return "elsewhere"


def status(config: Config, *, registry=None) -> dict:
    registry = registry or default_registry()
    manifest, launcher = manifest_path(config), launcher_path(config)
    origins = allowed_origins(config)
    match = re.match(r"^chrome-extension://([a-p]{32})/$", origins[0]) if origins else None
    python = None
    if launcher.exists():
        try:
            first = launcher.read_bytes().decode(oem_encoding() if sys.platform == "win32" else "utf-8")
        except (UnicodeDecodeError, InstallError):
            first = ""
        found = _LAUNCHER_PYTHON.match(first)
        python = found.group(1) if found else None
    return {"registered": registration(config, registry=registry) == "here",
            "manifest": manifest.exists(), "launcher": launcher.exists(),
            "extension_id": match.group(1) if match else None, "python": python,
            "python_exists": bool(python) and Path(python).exists()}
