"""014 T005: the first-run setup (contracts/cli.md §1; FR-001–FR-004, FR-014, FR-019)."""

import io
import tomllib
from datetime import date

import pytest

from sweetspot import setup
from sweetspot.config import DEFAULT_TOML, Secret, Secrets, load_config
from sweetspot.sources.errors import SourceError
from sweetspot.sources.steam_community import Profile, ProfileNotFound
from sweetspot.sources.steam_webapi import WishlistEntry, WishlistFetchError
from tests.config_builders import FAKE_STEAMID, FAKE_WISHLIST_URL, TEST_TOML

OTHER_ID = "76561190000000001"          # below account 0, so no one's: a second fictional account
KEY = "itad-test-key-value"


class FakeCommunity:
    def __init__(self, profiles=None):
        self.profiles = profiles or {}      # vanity name or steamid -> Profile | Exception
        self.asked = []

    def _get(self, key):
        self.asked.append(key)
        value = self.profiles.get(key, ProfileNotFound("not found"))
        if isinstance(value, Exception):
            raise value
        return value

    by_vanity = _get
    by_steamid = _get


def wishlist_of(mapping):
    def get(steamid):
        value = mapping.get(steamid, [])
        if isinstance(value, Exception):
            raise value
        return value
    return get


ONE = [WishlistEntry(app_id=10, priority=1, date_added=None)]


def run(tmp_path, answers, *, community=None, wishlist=None, secrets=Secrets(itad_api_key=Secret(KEY)),
        interactive=True, change=False, path=None):
    path = path or tmp_path / "sweetspot.toml"
    out = io.StringIO()
    replies = iter(answers)

    def ask(prompt):
        out.write(prompt)
        try:
            reply = next(replies)
        except StopIteration:
            raise EOFError from None
        if isinstance(reply, BaseException):               # e.g. Ctrl+C at this prompt
            raise reply
        return reply

    community = community or FakeCommunity({FAKE_STEAMID: Profile(FAKE_STEAMID, "範例玩家", "public")})
    code = setup.run(path, change=change, ask=ask, out=out, interactive=interactive, secrets=secrets,
                     community=community, wishlist=wishlist or wishlist_of({FAKE_STEAMID: ONE}),
                     today=date(2026, 10, 18))
    return code, out.getvalue(), path


def test_existing_file_is_left_alone(tmp_path):
    path = tmp_path / "sweetspot.toml"
    path.write_text(TEST_TOML, encoding="utf-8")
    code, out, _ = run(tmp_path, [], path=path)
    assert code == 0 and FAKE_WISHLIST_URL in out and "--change" in out
    assert path.read_text(encoding="utf-8") == TEST_TOML


def test_not_interactive_creates_nothing(tmp_path):
    code, out, path = run(tmp_path, [FAKE_WISHLIST_URL], interactive=False)
    assert code == setup.EXIT_NOT_SET_UP == 5
    assert "sweetspot setup" in out and not path.exists() and list(tmp_path.iterdir()) == []


def test_missing_itad_key_stops_before_asking(tmp_path):
    code, out, path = run(tmp_path, [FAKE_WISHLIST_URL], secrets=Secrets())
    assert code == 5 and not path.exists()
    assert "ITAD_API_KEY" in out and "重開" in out
    assert "網址" not in out.split("ITAD_API_KEY")[0]          # the key is checked before the url is asked


@pytest.mark.parametrize("url", [
    FAKE_WISHLIST_URL,
    FAKE_WISHLIST_URL.rstrip("/"),
    f"https://steamcommunity.com/profiles/{FAKE_STEAMID}",
    f"https://steamcommunity.com/profiles/{FAKE_STEAMID}/",
    f"{FAKE_WISHLIST_URL}#sort=order",
    f"  {FAKE_WISHLIST_URL}  ",
])
def test_numeric_forms_are_accepted(tmp_path, url):
    code, out, path = run(tmp_path, [url])
    assert code == 0
    config, _ = load_config(path)
    assert config.wishlist_url == FAKE_WISHLIST_URL and config.steamid == FAKE_STEAMID


@pytest.mark.parametrize("url", [
    "https://store.steampowered.com/wishlist/id/Some_Name/",
    "https://store.steampowered.com/wishlist/id/Some_Name",
    "https://steamcommunity.com/id/Some_Name",
    "https://steamcommunity.com/id/Some_Name/",
])
def test_custom_url_is_stored_as_the_number(tmp_path, url):
    community = FakeCommunity({"Some_Name": Profile(OTHER_ID, "範例玩家二號", "public"),
                               OTHER_ID: Profile(OTHER_ID, "範例玩家二號", "public")})
    code, out, path = run(tmp_path, [url], community=community, wishlist=wishlist_of({OTHER_ID: ONE}))
    assert code == 0
    assert f"已記成這個帳號：範例玩家二號（{OTHER_ID}）" in out
    text = path.read_text(encoding="utf-8")
    assert f"/wishlist/profiles/{OTHER_ID}/" in text and "Some_Name" not in text


@pytest.mark.parametrize("bad", [
    "https://store.steampowered.com/app/620/",
    "https://store.steampowered.com/wishlist/profiles/123/",
    "steamcommunity.com/id/x",
    "https://example.com/wishlist/profiles/76561197960265728/",
    "https://steamcommunity.com/groups/somegroup",
])
def test_wrong_forms_are_explained_and_asked_again(tmp_path, bad):
    code, out, path = run(tmp_path, [bad, FAKE_WISHLIST_URL])
    assert code == 0 and "格式" in out
    assert out.count("網址") >= 2


def test_unknown_account_is_explained_and_asked_again(tmp_path):
    code, out, _ = run(tmp_path, ["https://steamcommunity.com/id/nobody-here", FAKE_WISHLIST_URL])
    assert code == 0 and "找不到這個帳號" in out


@pytest.mark.parametrize("privacy", ["friendsonly", "private"])
def test_private_profile_is_explained(tmp_path, privacy):
    community = FakeCommunity({FAKE_STEAMID: Profile(FAKE_STEAMID, "x", privacy)})
    code, out, path = run(tmp_path, [FAKE_WISHLIST_URL], community=community)
    assert code == 5 and not path.exists()
    assert "隱私設定" in out and "遊戲詳細資料" in out


def test_private_wishlist_on_a_public_profile_is_explained(tmp_path):
    wishlist = wishlist_of({FAKE_STEAMID: WishlistFetchError("private", "wishlist is private")})
    code, out, path = run(tmp_path, [FAKE_WISHLIST_URL], wishlist=wishlist)
    assert code == 5 and not path.exists() and "遊戲詳細資料" in out


def test_empty_wishlist_needs_a_yes(tmp_path):
    empty = wishlist_of({FAKE_STEAMID: []})
    code, out, path = run(tmp_path, [FAKE_WISHLIST_URL, "n"], wishlist=empty)
    assert code == 5 and not path.exists() and "0 款" in out
    code, out, path = run(tmp_path, [FAKE_WISHLIST_URL, "y"], wishlist=empty)
    assert code == 0 and path.exists()


@pytest.mark.parametrize("answers", [[], [""], ["   "]])
def test_empty_answer_or_closed_input_creates_nothing(tmp_path, answers):
    code, out, path = run(tmp_path, answers)
    assert code == 5 and not path.exists()


@pytest.mark.parametrize("answers", [[KeyboardInterrupt()], [FAKE_WISHLIST_URL, KeyboardInterrupt()]])
def test_ctrl_c_creates_nothing_and_says_so(tmp_path, answers):
    """014 T060: Ctrl+C at a prompt (the URL, or the (y/N) of an empty list) is a cancel, not a traceback."""
    try:
        code, out, path = run(tmp_path, answers, wishlist=wishlist_of({FAKE_STEAMID: []}))
    except KeyboardInterrupt:
        pytest.fail("Ctrl+C escaped setup.run (a traceback for the user)")
    assert code == 5 and not path.exists() and "已取消" in out


def test_seventeen_digits_that_are_no_steamid_are_a_wrong_form(tmp_path):
    """014 T060: /profiles/<17 digits> not starting 7656119 reached by_steamid, whose ValueError was explained as
    a wrong custom name."""
    community = FakeCommunity({FAKE_STEAMID: Profile(FAKE_STEAMID, "範例玩家", "public")})
    code, out, _ = run(tmp_path, ["https://steamcommunity.com/profiles/12345678901234567", FAKE_WISHLIST_URL],
                       community=community)
    assert code == 0 and "接受這幾種" in out and "自訂名稱只能有" not in out
    assert community.asked == [FAKE_STEAMID]


def test_steam_unreachable_stops_with_1(tmp_path):
    community = FakeCommunity({FAKE_STEAMID: SourceError("network error")})
    code, out, path = run(tmp_path, [FAKE_WISHLIST_URL], community=community)
    assert code == 1 and not path.exists() and "稍後" in out


def test_written_file_is_the_template_with_the_url(tmp_path):
    code, out, path = run(tmp_path, [FAKE_WISHLIST_URL])
    text = path.read_text(encoding="utf-8")
    first, rest = text.split("\n", 1)
    assert first.startswith("# 由 sweetspot setup 建立（2026-10-18）")
    assert rest == TEST_TOML
    assert tomllib.loads(text)["wishlist"]["url"] == FAKE_WISHLIST_URL
    assert "sweetspot schedule install" in out and "更新資料.cmd" in out


def test_change_rewrites_only_the_url_line(tmp_path):
    path = tmp_path / "sweetspot.toml"
    original = TEST_TOML.replace("max_items = 500", "max_items = 300  # 我的註解")
    path.write_text(original, encoding="utf-8")
    community = FakeCommunity({OTHER_ID: Profile(OTHER_ID, "y", "public")})
    code, out, _ = run(tmp_path, [f"https://steamcommunity.com/profiles/{OTHER_ID}"], change=True, path=path,
                       community=community, wishlist=wishlist_of({OTHER_ID: ONE}))
    assert code == 0
    assert path.read_text(encoding="utf-8") == original.replace(FAKE_WISHLIST_URL,
                                                                f"https://store.steampowered.com/wishlist/profiles/{OTHER_ID}/")


NEW_URL = f"https://store.steampowered.com/wishlist/profiles/{OTHER_ID}/"


def change_to_other(tmp_path, text):
    path = tmp_path / "sweetspot.toml"
    path.write_text(text, encoding="utf-8")
    community = FakeCommunity({OTHER_ID: Profile(OTHER_ID, "y", "public")})
    try:
        code, out, _ = run(tmp_path, [f"https://steamcommunity.com/profiles/{OTHER_ID}"], change=True, path=path,
                           community=community, wishlist=wishlist_of({OTHER_ID: ONE}))
    except ValueError:
        pytest.fail("a url line in another form escaped as a traceback")
    return code, out, path.read_text(encoding="utf-8")


@pytest.mark.parametrize(("line", "kept"), [
    (f"url = '{FAKE_WISHLIST_URL}'", ""),                               # single quotes
    (f'url="{FAKE_WISHLIST_URL}"', ""),                                 # no spaces
    (f'url = "{FAKE_WISHLIST_URL}"   # 我的清單', "   # 我的清單"),      # a comment after it
])
def test_change_takes_every_form_of_the_url_line(tmp_path, line, kept):
    """014 T066: only `url = "..."` was found; any other form was a ValueError traceback."""
    text = TEST_TOML.replace(f'url = "{FAKE_WISHLIST_URL}"', line)
    assert line in text
    code, _, written = change_to_other(tmp_path, text)
    assert code == 0 and written == text.replace(line, f'url = "{NEW_URL}"{kept}')


def test_change_adds_a_missing_url_line_to_wishlist_only(tmp_path):
    """014 T066: with no url under [wishlist], the first url line of a later section was rewritten."""
    text = TEST_TOML.replace(f'url = "{FAKE_WISHLIST_URL}"\n', "") + '\n[elsewhere]\nurl = "https://example.com/"\n'
    code, _, written = change_to_other(tmp_path, text)
    parsed = tomllib.loads(written)
    assert code == 0 and parsed["wishlist"]["url"] == NEW_URL and parsed["elsewhere"]["url"] == "https://example.com/"


def test_change_adds_the_wishlist_section_when_there_is_none(tmp_path):
    code, _, written = change_to_other(tmp_path, "schema_version = 1\n")
    assert code == 0 and tomllib.loads(written)["wishlist"]["url"] == NEW_URL
    assert written.startswith("schema_version = 1\n")


def test_change_leaves_a_file_it_cannot_read_and_says_what_to_do(tmp_path):
    text = TEST_TOML + "\nthis is not toml\n"
    code, out, written = change_to_other(tmp_path, text)
    assert code == 1 and written == text
    assert NEW_URL in out and "沒有改" in out


def test_change_without_a_file_is_a_first_setup(tmp_path):
    code, out, path = run(tmp_path, [FAKE_WISHLIST_URL], change=True)
    assert code == 0 and path.exists()


@pytest.mark.parametrize("answers", [[FAKE_WISHLIST_URL], ["bad", ""]])
def test_no_key_in_any_output(tmp_path, answers):
    _, out, path = run(tmp_path, answers)
    assert KEY not in out
    if path.exists():
        assert KEY not in path.read_text(encoding="utf-8")


def test_never_asks_for_a_password(tmp_path):
    _, out, _ = run(tmp_path, [FAKE_WISHLIST_URL])
    out = out.replace(str(tmp_path), "")                 # the test's own folder name contains "password"
    assert "密碼" not in out and "password" not in out.lower()


# --- 014 T050: a written settings file leaves a result line in the daily log ------------------------------------------

@pytest.fixture
def interactive(monkeypatch):
    """interactive_run with fake sources; answers are taken in order."""
    import logging

    answers = []
    monkeypatch.setattr(setup, "load_secrets", lambda: Secrets(itad_api_key=Secret(KEY)))
    monkeypatch.setattr(setup, "_sources", lambda secrets: (
        FakeCommunity({FAKE_STEAMID: Profile(FAKE_STEAMID, "範例玩家", "public")}), wishlist_of({FAKE_STEAMID: ONE})))

    def ask(prompt):
        if not answers:
            raise EOFError
        return answers.pop(0)

    monkeypatch.setattr(setup, "ask", ask)
    yield answers
    logger = logging.getLogger("sweetspot")
    for handler in [h for h in logger.handlers if getattr(h, "_sweetspot", False)]:
        logger.removeHandler(handler)
        handler.close()


def day_log(tmp_path):
    logs = list((tmp_path / "data" / "logs").glob("sweetspot-*.log"))
    return logs[0].read_text(encoding="utf-8") if logs else None


def test_a_created_file_leaves_a_result_line(tmp_path, interactive):
    interactive.append(FAKE_WISHLIST_URL)
    assert setup.interactive_run(tmp_path / "sweetspot.toml", change=False, stdout=io.StringIO()) == 0
    text = day_log(tmp_path)
    assert "setup 結束：代碼 0" in text and "settings=created" in text
    assert FAKE_STEAMID not in text and KEY not in text                  # no url, no key


def test_a_changed_file_leaves_a_result_line(tmp_path, interactive):
    path = tmp_path / "sweetspot.toml"
    interactive.extend([FAKE_WISHLIST_URL, FAKE_WISHLIST_URL])
    setup.interactive_run(path, change=False, stdout=io.StringIO())
    assert setup.interactive_run(path, change=True, stdout=io.StringIO()) == 0
    assert "settings=changed" in day_log(tmp_path)


def test_nothing_written_means_no_log(tmp_path, interactive):
    assert setup.interactive_run(tmp_path / "sweetspot.toml", change=False, stdout=io.StringIO()) == 5
    assert list(tmp_path.iterdir()) == []                                 # still creates nothing (FR-001)


def test_template_has_no_personal_wishlist():
    assert tomllib.loads(DEFAULT_TOML)["wishlist"]["url"] == ""
