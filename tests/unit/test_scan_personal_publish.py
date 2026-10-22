"""014 T017: the publish-time kinds of the personal scan (contracts/scan-personal.md §2 「發佈時的類別」).
Keys, the owner's SteamID, the wishlist dates, the database names and the content lookup are all fakes here."""

import importlib.util
import io
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("scan_personal", ROOT / "scripts" / "scan_personal.py")
sp = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sp)

KEY = "fake-" + "itad-" + "key-0123456789"
OWN = "7656119" + "9" + "000000" + "123"
DATES = {1771234567, 1769999999}


def lookup_of(descriptors):
    calls = []

    def lookup(app_ids):
        calls.append(sorted(app_ids))
        return {a: set(descriptors.get(a, ())) for a in app_ids}
    lookup.calls = calls
    return lookup


def publish(files, *, owners=(), descriptors=None, names=None, lookup=None):
    return sp.scan_publish(files, owners=set(owners), secrets=[KEY], own_steamid=OWN, wishlist_dates=DATES,
                           product_names=names or {}, content_lookup=lookup or lookup_of(descriptors or {}))


def kinds(result):
    return [(h.path, h.kind, h.value, h.category) for h in result.hits if h.category is None]


def test_a_key_value_is_reported_by_place_only():
    result = publish([("README.md", f"one\nkey = {KEY}\n")])
    assert kinds(result) == [("README.md", "key", "***", None)]
    out = io.StringIO()
    sp.report(result, out)
    assert KEY not in out.getvalue() and "README.md:2: key: ***" in out.getvalue()


def test_the_owners_steamid_is_found_even_where_the_offline_rules_would_not_look():
    assert ("docs/x.md", "own_steamid", OWN, None) in kinds(publish([("docs/x.md", f"id {OWN}")]))


def test_wishlist_dates_are_found():
    assert ("tests/f.json", "wishlist_date", "1771234567", None) in kinds(
        publish([("tests/f.json", '{"date_added": 1771234567}')]))
    assert kinds(publish([("tests/f.json", '{"date_added": 1771234568}')])) == []


@pytest.mark.parametrize("text", ['{"appid": 4242420}', '"app_id": 4242420', 'data-ds-appid="4242420"',
                                  "https://store.steampowered.com/app/4242420/Name/", "app_id=4242420"])
def test_nsfw_games_by_app_id(text):
    result = publish([("tests/f.json", text)], descriptors={4242420: {3}})
    assert ("tests/f.json", "nsfw", "app 4242420", None) in kinds(result)


def test_nsfw_games_by_name_from_the_database():
    result = publish([("specs/x.md", "例如 Some Adult Game 的版本")], names={"Some Adult Game": 4242420},
                     descriptors={4242420: {4}})
    assert ("specs/x.md", "nsfw", "app 4242420", None) in kinds(result)


def test_only_descriptors_3_and_4_count():
    result = publish([("tests/f.json", '{"appid": 4242420}')], descriptors={4242420: {1, 2, 5}})
    assert kinds(result) == []


def test_the_lookup_is_asked_once_for_every_app_id_found():
    lookup = lookup_of({})
    publish([("a.json", '{"appid": 30}\n{"appid": 10}'), ("b.json", '{"appid": 20}')], lookup=lookup)
    assert lookup.calls == [[10, 20, 30]]


def test_offline_kinds_still_apply():
    result = publish([("src/x.py", "C" + ":" + "\\SourceCode\\Real")])
    assert ("src/x.py", "path", None) == (kinds(result)[0][0], kinds(result)[0][1], kinds(result)[0][3])


def test_a_failed_lookup_is_exit_2(tmp_path, monkeypatch):
    (tmp_path / "a.json").write_text('{"appid": 10}', encoding="utf-8")

    def broken(app_ids):
        raise OSError("network down")

    monkeypatch.setattr(sp, "publish_inputs", lambda root: dict(owners=set(), secrets=[], own_steamid=None,
                                                                wishlist_dates=set(), product_names={},
                                                                content_lookup=broken))
    out = io.StringIO()
    assert sp.main(["--publish", str(tmp_path)], out=out) == 2
    assert "不能判定" in out.getvalue()


def public_folder(tmp_path, monkeypatch, files):
    """A public folder as publish.py leaves it before the scan: a git repository with everything staged."""
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    (tmp_path / ".git" / "config").write_text(f"[x]\n\ty = {KEY}\n", encoding="utf-8")
    monkeypatch.setattr(sp, "publish_inputs", lambda root: dict(owners=set(), secrets=[KEY], own_steamid=None,
                                                                wishlist_dates=set(), product_names={},
                                                                content_lookup=lookup_of({})))
    return tmp_path


def test_publish_reads_every_file_a_clone_would_have_but_not_git(tmp_path, monkeypatch):
    folder = public_folder(tmp_path, monkeypatch, {"sub/a.txt": f"x {KEY}", ".gitignore": ".venv/\n"})
    (folder / "new.txt").write_text(f"x {KEY}", encoding="utf-8")            # not staged, not ignored: still seen
    out = io.StringIO()
    assert sp.main(["--publish", str(folder)], out=out) == 1
    assert "sub/a.txt:1: key: ***" in out.getvalue() and "new.txt:1: key: ***" in out.getvalue()
    assert ".git/" not in out.getvalue()


def test_publish_skips_what_the_tests_left_in_ignored_folders(tmp_path, monkeypatch):
    """Regression (014 T055): the test step's `uv sync` leaves .venv/ in the public folder; its pyvenv.cfg holds the
    owner's folders, so every publish after the first one failed the scan. A clone has no .venv/."""
    folder = public_folder(tmp_path, monkeypatch, {"a.txt": "clean\n", ".gitignore": ".venv/\n"})
    (folder / ".venv").mkdir()
    (folder / ".venv" / "pyvenv.cfg").write_text(f"home = {KEY}\n", encoding="utf-8")
    out = io.StringIO()
    assert sp.main(["--publish", str(folder)], out=out) == 0, out.getvalue()
    assert "2 個檔案" in out.getvalue()


def test_a_folder_that_is_not_a_git_repository_cannot_be_decided(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("clean\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))      # do not find a repository above it
    out = io.StringIO()
    assert sp.main(["--publish", str(tmp_path)], out=out) == 2
    assert "不能判定" in out.getvalue()


def test_publish_scans_handoff_too_if_it_got_into_the_folder(tmp_path, monkeypatch):
    """014 T055: HANDOFF.md is skipped on master because it is never published; in the public folder it must not be."""
    folder = public_folder(tmp_path, monkeypatch, {"HANDOFF.md": "在 C" + ":" + "\\SourceCode\\Real 執行\n"})
    out = io.StringIO()
    assert sp.main(["--publish", str(folder)], out=out) == 1
    assert "HANDOFF.md:1: path: " in out.getvalue()


@pytest.mark.parametrize("line", ['"""Mirror of follow_advice_monthly"""', "- Put in earliest story"])
def test_short_database_names_are_not_matched_as_ordinary_words(line):
    """2026-10-18 smoke run on the real database: games named like ordinary words must not count."""
    result = publish([("docs/x.md", line)], names={"Mirror": 4242420, "Put in": 4242421},
                     descriptors={4242420: {3}, 4242421: {4}})
    assert kinds(result) == []


def test_a_cjk_name_of_three_characters_is_matched():
    result = publish([("specs/x.md", "例如範例三字的版本")], names={"範例三": 4242420}, descriptors={4242420: {3}})
    assert ("specs/x.md", "nsfw", "app 4242420", None) in kinds(result)
