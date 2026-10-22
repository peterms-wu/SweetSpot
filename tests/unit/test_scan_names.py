"""Feature 016 US4: scripts/scan_names.py finds every old name in tracked files; only the rule table may allow one
(contracts/scan.md). Every rule has a frozen sample that must match and one that must not."""

import importlib.util
import io
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("scan_names", ROOT / "scripts" / "scan_names.py")
scan_names = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(scan_names)


def categories(path: str, line: str) -> list[str | None]:
    """The category of each hit on one line (None = not allowed)."""
    return [h.category for h in scan_names.scan([(path, line + "\n")]).hits]


SAMPLES = [
    # (path, line, expected category of each hit) -- what must match and what must not, per rule
    ("specs/001-price-data-foundation/plan.md", "uv run steamsage update", ["history"]),
    ("docs/specs-notes.md", "uv run steamsage update", [None]),
    ("HANDOFF.md", "uv run steamsage update", ["handoff"]),
    ("docs/HANDOFF.md", "uv run steamsage update", [None]),
    ("docs/model/comparisons.md", "`steamsage compare … --record`", ["comparisons"]),
    ("docs/model/model-definition.md", "`steamsage backtest-rule`", [None]),
    ("scripts/scan_names.py", "steamsage", ["scan"]),
    ("scripts/backup_db.py", "data/steamsage.db", [None]),
    ("src/sweetspot/migrate.py", "steamsage.toml", ["migration"]),
    ("src/sweetspot/legacy.py", "steamsage.toml", ["migration"]),
    ("tests/integration/test_migrate.py", "steamsage.toml", ["migration"]),
    ("tests/unit/test_legacy_names.py", "steamsage.toml", ["migration"]),
    ("tests/unit/test_legacy_import.py", "steamsage.toml", [None]),
    (".gitignore", "steamsage.toml", ["gitignore"]),
    ("extension/.gitignore", "steamsage.toml", [None]),
    ("src/sweetspot/decision/contract.py", 'FORMAT = "steamsage.decision/2"', ["data-id"]),
    ("extension/lib.js", "const FORMAT = 'steamsage.extension/1';", ["data-id"]),
    ("src/sweetspot/x.py", 'name = "steamsage.decision"', [None]),
    ("src/sweetspot/forecast/backtest/split.py", 'SALT = "steamsage-004-split"', ["data-id"]),
    ("src/sweetspot/x.py", 'SALT = "steamsage-005-split"', [None]),
    ("src/sweetspot/x.py", '"steamsage_version": __version__', ["data-id"]),
    ("src/sweetspot/x.py", '"steamsage_versions": []', [None]),
    ("README.md", "程式指令原本沿用的舊名 `steamsage`", ["old-name"]),
    ("src/sweetspot/__init__.py", '"""SweetSpot (formerly SteamSage2): local Steam price data."""', ["old-name"]),
    ("README.md", "「SteamSage2 每日背景更新」工作", [None]),
    ("src/sweetspot/config.py", "cache_path = 'D:\\\\Tools\\\\SteamSage\\\\state\\\\cache'", ["predecessor"]),
    ("tests/unit/test_import.py", '"""US5: import the legacy SteamSage cache."""', ["predecessor"]),
    ("README.md", "| 匯入舊專案 SteamSage 的快取 |", ["predecessor"]),
    ("tests/unit/test_import.py", "the legacy steamsage cache", [None]),          # lower case is not the project
    ("extension/content.js", "const S = globalThis.SteamSage;", [None]),
    ("tests/extension/static.test.js", "assert.match(sw, /sendNativeMessage\\(SteamSage\\.HOST_NAME, request,/);", [None]),
    ("README.md", "uv run steamsage update", [None]),
    ("README.md", "設定檔 `steamsage.toml`", [None]),
    ("src/sweetspot/x.py", '"steamsage.decision/2" or steamsage.toml', ["data-id", None]),
]


@pytest.mark.parametrize("path, line, expected", SAMPLES)
def test_rule_samples(path, line, expected):
    assert categories(path, line) == expected


def test_every_rule_has_a_sample_that_matches_and_one_that_does_not():
    keys = {r.key for r in scan_names.RULES}
    matched = {c for _, _, cats in SAMPLES for c in cats if c}
    assert matched == keys
    assert sum(None in cats for _, _, cats in SAMPLES) >= len(keys)


def test_a_line_with_one_unallowed_hit_is_reported():
    result = scan_names.scan([("src/sweetspot/x.py", '"steamsage.decision/2" or steamsage.toml\n')])
    assert [(h.path, h.line_no) for h in result.unallowed] == [("src/sweetspot/x.py", 1)]


def test_a_planted_old_name_is_found_with_file_and_line():
    out = io.StringIO()
    files = [("src/sweetspot/ok.py", "a = 1\n"), ("src/sweetspot/new.py", "a = 1\nb = 'steamsage'\n")]
    code = scan_names.main([], files=files, out=out)
    assert code == 1
    assert "src/sweetspot/new.py:2: b = 'steamsage'" in out.getvalue()


def test_the_repository_has_no_unallowed_old_name():
    result = scan_names.scan(scan_names.repo_files(ROOT)[0])
    assert [f"{h.path}:{h.line_no}: {h.line}" for h in result.unallowed] == []


def test_the_exceptions_document_is_current():
    files, _ = scan_names.repo_files(ROOT)
    expected = scan_names.render_doc(scan_names.scan(files))
    actual = (ROOT / "docs" / "legacy-names.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert actual == expected, "docs/legacy-names.md is stale: run uv run python scripts/scan_names.py --write"


def test_the_document_has_a_section_for_every_rule():
    doc = (ROOT / "docs" / "legacy-names.md").read_text(encoding="utf-8")
    for n, rule in enumerate(scan_names.RULES, 1):
        assert f"## {n}. {rule.title}" in doc


def test_repo_files_reads_chinese_file_names():
    """git ls-files quotes non-ASCII paths unless -z is used; 016 T001 missed the two .cmd files this way."""
    files, _ = scan_names.repo_files(ROOT)
    names = {path for path, _ in files}
    assert {"更新資料.cmd", "背景更新.cmd"} <= names
