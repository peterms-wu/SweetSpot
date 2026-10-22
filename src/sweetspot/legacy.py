"""Old (before feature 016) and new names of the user's files, and the state of each (data-model §1).

contracts/names.md is the single source; tests/unit/test_legacy_names.py checks this module against it. Shared by the
command line (refuse while only old-name files exist), the migration (sweetspot migrate) and scripts/backup_db.py.
Nothing here creates or changes a file.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from sweetspot.config import data_dir_of

OLD_TASK = "SteamSage2 每日背景更新"
NEW_TASK = "SweetSpot 每日背景更新"
OLD_HOST_MODULE = "steamsage.host"
NEW_HOST_MODULE = "sweetspot.host"
MIGRATE_COMMAND = "uv run sweetspot migrate"

OLD_ONLY, NEW_ONLY, BOTH, ABSENT = "old-only", "new-only", "both", "absent"


@dataclass(frozen=True)
class Item:
    kind: str
    label: str
    old: str                      # relative to the item's base folder
    new: str
    base: str                     # "folder" (next to the settings file), "data_dir" or "extension"
    companions: tuple[str, ...]   # suffixes renamed together with the file when present
    blocks: bool                  # old-only blocks every command but the migration (FR-010)


CONFIG = Item("config", "設定檔", "steamsage.toml", "sweetspot.toml", "folder", (), True)
DB = Item("db", "資料庫", "steamsage.db", "sweetspot.db", "data_dir", ("-wal", "-shm"), True)
EXTENSION_DATA = Item("extension_data", "擴充功能資料檔", "data/steamsage-extension.json",
                      "data/sweetspot-extension.json", "extension", (), False)
ITEMS = (CONFIG, DB, EXTENSION_DATA)


def state(old: Path, new: Path) -> str:
    has_old, has_new = Path(old).exists(), Path(new).exists()
    if has_old and has_new:
        return BOTH
    return OLD_ONLY if has_old else NEW_ONLY if has_new else ABSENT


def read_data_dir(folder: Path) -> Path:
    """[storage] data_dir of the new settings file, else the old one, else "data" -- read only, never created
    (load_config would write a default file when it is missing)."""
    folder = Path(folder)
    for name in (CONFIG.new, CONFIG.old):
        path = folder / name
        if path.exists():
            return data_dir_of(path, tomllib.loads(path.read_text(encoding="utf-8")))
    return data_dir_of(folder / CONFIG.new, {})


@dataclass(frozen=True)
class FileItem:
    item: Item
    old: Path
    new: Path
    state: str

    def companions(self) -> list[tuple[Path, Path]]:
        return [(self.old.with_name(self.old.name + s), self.new.with_name(self.new.name + s))
                for s in self.item.companions]


def _base(item: Item, folder: Path, data_dir: Path) -> Path:
    return {"folder": folder, "data_dir": data_dir, "extension": folder / "extension"}[item.base]


def refusal(old: Path) -> str:
    """The one line every command but the migration prints while only the old-name file exists (FR-010)."""
    return f"找到舊名稱的檔案（{Path(old).name}），請先執行搬家：{MIGRATE_COMMAND}"


def config_blocker(config_path: Path) -> Path | None:
    """The old settings file when the new one does not exist yet (checked before load_config, which would create it)."""
    config_path = Path(config_path)
    old = config_path.parent / CONFIG.old
    return old if not config_path.exists() and old.exists() else None


def db_blocker(db_path: Path) -> Path | None:
    """The old database when the new one does not exist yet (checked before a writer would create an empty one)."""
    db_path = Path(db_path)
    old = db_path.with_name(DB.old)
    return old if not db_path.exists() and old.exists() else None


def leftovers(config_path: Path, db_path: Path, extension_dir: Path) -> list[Path]:
    """Old-name files still there next to their new-name file (FR-011): used is the new one, the old one is reported."""
    pairs = [(Path(config_path).parent / CONFIG.old, Path(config_path)), (Path(db_path).with_name(DB.old), Path(db_path)),
             (Path(extension_dir) / EXTENSION_DATA.old, Path(extension_dir) / EXTENSION_DATA.new)]
    return [old for old, new in pairs if state(old, new) == BOTH]


def items(folder: Path, data_dir: Path | None = None) -> list[FileItem]:
    """Every file of the name map with its full old and new path and its state, in migration order."""
    folder = Path(folder)
    data_dir = read_data_dir(folder) if data_dir is None else Path(data_dir)
    out = []
    for item in ITEMS:
        base = _base(item, folder, data_dir)
        old, new = base / item.old, base / item.new
        out.append(FileItem(item, old, new, state(old, new)))
    return out
