"""Feature 016: the old -> new name map and the per-file state (data-model §1, contracts/names.md §1 and §3)."""

import os
from pathlib import Path

import pytest

from sweetspot import legacy

CONTRACT = Path(__file__).resolve().parents[2] / "specs" / "016-rename-internal-ids" / "contracts" / "names.md"


def test_items_match_the_data_model():
    got = {i.kind: (i.label, i.old, i.new, i.base, i.companions, i.blocks) for i in legacy.ITEMS}
    assert got == {
        "config": ("設定檔", "steamsage.toml", "sweetspot.toml", "folder", (), True),
        "db": ("資料庫", "steamsage.db", "sweetspot.db", "data_dir", ("-wal", "-shm"), True),
        "extension_data": ("擴充功能資料檔", "data/steamsage-extension.json", "data/sweetspot-extension.json",
                           "extension", (), False),
    }
    assert [i.kind for i in legacy.ITEMS] == ["config", "db", "extension_data"]   # the order of migration.json files


def test_task_and_host_constants():
    assert legacy.OLD_TASK == "SteamSage2 每日背景更新"
    assert legacy.NEW_TASK == "SweetSpot 每日背景更新"
    assert legacy.OLD_HOST_MODULE == "steamsage.host"
    assert legacy.NEW_HOST_MODULE == "sweetspot.host"


def test_every_name_appears_in_the_contract():
    """contracts/names.md is the single source; the code must not drift from it."""
    text = CONTRACT.read_text(encoding="utf-8")
    for item in legacy.ITEMS:
        assert Path(item.old).name in text and Path(item.new).name in text, item.kind
    for name in (legacy.OLD_TASK, legacy.NEW_TASK, legacy.OLD_HOST_MODULE, legacy.NEW_HOST_MODULE):
        assert name in text


@pytest.mark.parametrize("old, new, expected", [
    (True, False, "old-only"), (False, True, "new-only"), (True, True, "both"), (False, False, "absent")])
def test_state(tmp_path, old, new, expected):
    if old:
        (tmp_path / "a").write_text("x", encoding="utf-8")
    if new:
        (tmp_path / "b").write_text("y", encoding="utf-8")
    assert legacy.state(tmp_path / "a", tmp_path / "b") == expected


def _snapshot(folder: Path) -> dict[str, tuple[bytes, int]]:
    return {str(p.relative_to(folder)): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in sorted(folder.rglob("*")) if p.is_file()}


@pytest.mark.parametrize("name", ["steamsage.toml", "sweetspot.toml"])
def test_data_dir_relative_is_read_without_touching_anything(tmp_path, name):
    (tmp_path / name).write_text('[storage]\ndata_dir = "mydata"\n', encoding="utf-8")
    before = _snapshot(tmp_path)
    assert legacy.read_data_dir(tmp_path) == tmp_path / "mydata"
    assert _snapshot(tmp_path) == before                      # no file created, nothing rewritten


def test_data_dir_absolute(tmp_path):
    target = tmp_path / "elsewhere"
    (tmp_path / "steamsage.toml").write_text(f"[storage]\ndata_dir = '{target}'\n", encoding="utf-8")
    assert legacy.read_data_dir(tmp_path) == target


def test_data_dir_prefers_the_new_settings_file(tmp_path):
    (tmp_path / "steamsage.toml").write_text('[storage]\ndata_dir = "old"\n', encoding="utf-8")
    (tmp_path / "sweetspot.toml").write_text('[storage]\ndata_dir = "new"\n', encoding="utf-8")
    assert legacy.read_data_dir(tmp_path) == tmp_path / "new"


def test_data_dir_default_without_settings_file(tmp_path):
    assert legacy.read_data_dir(tmp_path) == tmp_path / "data"
    assert list(tmp_path.iterdir()) == []


def test_items_resolve_paths_and_states(tmp_path):
    (tmp_path / "steamsage.toml").write_text("schema_version = 1\n", encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "steamsage.db").write_bytes(b"db")
    (tmp_path / "extension" / "data").mkdir(parents=True)
    (tmp_path / "extension" / "data" / "sweetspot-extension.json").write_text("{}", encoding="utf-8")
    got = {f.item.kind: (f.old, f.new, f.state) for f in legacy.items(tmp_path)}
    assert got == {
        "config": (tmp_path / "steamsage.toml", tmp_path / "sweetspot.toml", "old-only"),
        "db": (tmp_path / "data" / "steamsage.db", tmp_path / "data" / "sweetspot.db", "old-only"),
        "extension_data": (tmp_path / "extension" / "data" / "steamsage-extension.json",
                           tmp_path / "extension" / "data" / "sweetspot-extension.json", "new-only"),
    }
    assert legacy.items(tmp_path)[1].companions() == [
        (tmp_path / "data" / "steamsage.db-wal", tmp_path / "data" / "sweetspot.db-wal"),
        (tmp_path / "data" / "steamsage.db-shm", tmp_path / "data" / "sweetspot.db-shm")]


def test_items_on_an_empty_folder_are_absent_and_create_nothing(tmp_path):
    assert {f.state for f in legacy.items(tmp_path)} == {"absent"}
    assert not any(tmp_path.iterdir())
    assert os.listdir(tmp_path) == []
