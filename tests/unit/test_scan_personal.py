"""014 T016: the offline personal-information scan (contracts/scan-personal.md §2–§4; FR-005, FR-016b, SC-002).

Samples that must be found are put together at run time, so this file itself holds no SteamID, path or address
the scan would have to allow.
"""

import importlib.util
import io
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("scan_personal", ROOT / "scripts" / "scan_personal.py")
scan_personal = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(scan_personal)

SID = "7656119" + "8" + "1234" + "56789"                 # a SteamID shape above account 0: could be someone's
DRIVE = "C" + ":"
BS = "\\"
MAIL = "someone" + "@" + "mail" + ".example-isp.net"


def categories(path: str, text: str, owners=()) -> list[tuple[str, str | None]]:
    result = scan_personal.scan([(path, text)], owners=set(owners))
    return [(h.kind, h.category) for h in result.hits]


# --- every kind is found -----------------------------------------------------------------------------------------

@pytest.mark.parametrize(("text", "kind"), [
    (f"steamid = {SID}", "steamid"),
    (f"url = 'https://store.steampowered.com/wishlist/profiles/{SID}/'", "steamid"),
    (f"folder = {DRIVE}{BS}SourceCode{BS}Project", "path"),
    (f'escaped = "{DRIVE}{BS}{BS}SourceCode{BS}{BS}Project"', "path"),
    (f"forward = {DRIVE}/SourceCode/Project", "path"),
    (f"home = {BS}Users{BS}somebody{BS}AppData", "userdir"),
    ("mac = /Users/somebody/Library", "userdir"),
    (f"mail = {MAIL}", "email"),
    ("link = https://claude.ai/code/session_" + "01AbCdEf", "session"),
    ("-----BEGIN " + "RSA PRIVATE KEY-----", "private_key"),
])
def test_each_kind_is_found_and_not_allowed_in_ordinary_code(text, kind):
    found = categories("src/sweetspot/example.py", text)
    assert (kind, None) in found


def test_the_account_name_comes_from_the_git_remotes():
    found = categories("README.md", "see github.com/somebody-else/x and somebody", owners={"somebody"})
    assert ("account", None) in found
    assert categories("README.md", "nothing here", owners={"somebody"}) == []


def test_a_private_key_file_is_found_by_name():
    result = scan_personal.scan([("certs/server.pem", "anything")], owners=set())
    assert [(h.kind, h.category) for h in result.hits] == [("private_key", None)]


# --- what is allowed, and what is not ----------------------------------------------------------------------------

@pytest.mark.parametrize("value", ["76561197960265728", "76561190000000001"])
def test_steamids_at_or_below_account_0_are_fictional(value):
    assert categories("tests/unit/test_x.py", f"id = {value}") == [("steamid", "fictional-steamid")]


@pytest.mark.parametrize("text", [f"{DRIVE}{BS}Windows{BS}System32{BS}conhost.exe",
                                  f"{DRIVE}{BS}WINDOWS{BS}system32{BS}conhost.exe",
                                  f"{DRIVE}{BS}Program Files{BS}Google{BS}Chrome"])
def test_system_paths_are_allowed_everywhere(text):
    assert categories("README.md", text) == [("path", "system-path")]


@pytest.mark.parametrize("root", ["D:" + BS + "Tools" + BS + "SweetSpot", DRIVE + BS + "x", "Z:" + BS + "nowhere"])
def test_fictional_test_paths_are_allowed_only_under_tests(root):
    assert categories("tests/unit/test_x.py", f"p = r'{root}'") == [("path", "test-fiction")]
    assert categories("src/sweetspot/x.py", f"p = r'{root}'") == [("path", None)]


def test_a_look_alike_of_a_system_folder_is_not_one():
    assert categories("README.md", f"{DRIVE}{BS}WindowsTools{BS}x") == [("path", None)]


# 014 T061: the clause that keeps a real folder out of both rules ("not in the folder holding this repository or the
# home folder"). The folders here stand for the owner's: the context says they are real.
REAL = scan_personal.Context(real_roots=(scan_personal.PureWindowsPath("D:" + BS + "Work"),
                                         scan_personal.PureWindowsPath("D:" + BS + "ProgramData" + BS + "Owner")))


def categories_in(path: str, text: str) -> list[tuple[str, str | None]]:
    return [(h.kind, h.category) for h in scan_personal.scan([(path, text)], owners=set(), ctx=REAL).hits]


def test_a_real_folder_under_tests_is_not_fiction():
    assert categories_in("tests/unit/test_x.py", f"p = r'D:{BS}Work{BS}SweetSpot{BS}data'") == [("path", None)]
    assert categories_in("tests/unit/test_x.py", f"p = r'D:{BS}Elsewhere'") == [("path", "test-fiction")]


def test_a_real_folder_shaped_like_a_system_one_is_not_allowed():
    text = f"p = D:{BS}ProgramData{BS}Owner{BS}SweetSpot"
    assert categories_in("README.md", text) == [("path", None)]
    assert categories_in("README.md", f"p = D:{BS}ProgramData{BS}Google") == [("path", "system-path")]


def test_the_exceptions_document_names_what_the_publish_check_looks_for():
    """014 T061: the publish check looks for wishlist dates, not the order (contracts/scan-personal.md, 014 T017)."""
    text = scan_personal.render_doc(scan_personal.ScanResult())
    assert "排序" not in text and "加入日期" in text and "本人的 SteamID" in text


@pytest.mark.parametrize("address", ["git" + "@github.com", "123+someone@users.noreply.github.com",
                                     "noreply" + "@anthropic.com", "a@example.com", "b@example.org"])
def test_known_addresses_are_allowed(address):
    assert categories("README.md", f"x {address} y") == [("email", "known-address")]


def test_the_account_name_is_allowed_only_in_the_license_copyright_line():
    assert categories("LICENSE", "Copyright (c) 2026 somebody", owners={"somebody"}) == [("account", "license")]
    assert categories("LICENSE", "somebody wrote this", owners={"somebody"}) == [("account", None)]


def test_rule_documents_may_show_paths_and_addresses_but_not_a_real_steamid():
    doc = "specs/014-publish-github/contracts/scan-personal.md"
    assert categories(doc, f"`{DRIVE}{BS}Users{BS}…`") == [("path", "rule-doc"), ("userdir", "rule-doc")]
    assert categories(doc, f"`{SID}`") == [("steamid", None)]


def test_placeholders_are_not_paths():
    assert categories("specs/001/x.md", "在〈專案資料夾〉-016 執行；〈使用者資料夾〉、〈SteamID〉") == []


def test_urls_and_regexes_are_not_paths():
    assert categories("src/x.py", 'url = "https://store.steampowered.com/app/1/"; r"[A-Za-z]:[\\\\/]"') == []


# --- output and exit codes ---------------------------------------------------------------------------------------

def test_unallowed_hits_are_listed_with_file_and_line(tmp_path):
    out = io.StringIO()
    code = scan_personal.main([], files=[("src/a.py", f"ok\nid = {SID}\n")], owners=set(), out=out)
    assert code == 1
    assert f"src/a.py:2: steamid: {SID}" in out.getvalue()


def test_a_clean_scan_prints_counts_and_exits_0():
    out = io.StringIO()
    code = scan_personal.main([], files=[("tests/a.py", "id = 76561197960265728\n")], owners=set(), out=out)
    assert code == 0 and "不允許 0" in out.getvalue()


def test_the_repository_is_clean():
    """FR-016b: a later feature that writes a personal value fails here, on the owner's own machine."""
    out = io.StringIO()
    code = scan_personal.main([], out=out)
    assert code == 0, out.getvalue()


def test_the_exceptions_document_is_current():
    files, _ = scan_personal.repo_files(ROOT)
    expected = scan_personal.render_doc(scan_personal.scan(files, owners=scan_personal.remote_owners(ROOT)))
    assert (ROOT / scan_personal.DOC).read_text(encoding="utf-8") == expected, \
        "docs/personal-scan.md is stale: run uv run python scripts/scan_personal.py --write"
