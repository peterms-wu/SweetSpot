"""`sweetspot setup`: the first run asks for the user's own wishlist (014 contracts/cli.md §1; FR-001–FR-004, FR-014).

The settings file is written only here, once the ITAD key is there and the wishlist has been read. A custom URL is
turned into the numeric profile once and only that is stored (FR-002). Nothing here asks for a password or a key.
"""

import os
import re
import sys
import time
import tomllib
from collections.abc import Callable, Mapping
from datetime import date
from pathlib import Path
from typing import TextIO

from sweetspot.config import DEFAULT_TOML, Secrets, load_secrets
from sweetspot.sources.errors import SourceError
from sweetspot.sources.steam_community import ProfileNotFound
from sweetspot.sources.steam_webapi import WishlistFetchError

EXIT_OK, EXIT_FAILED, EXIT_NOT_SET_UP = 0, 1, 5
BACKGROUND = "SWEETSPOT_BACKGROUND"            # set by 背景更新.cmd (research R2: not isatty() of a headless console)
WISHLIST_URL = "https://store.steampowered.com/wishlist/profiles/{}/"
ITAD_KEY_PAGE = "https://isthereanydeal.com/apps/my/"
_FORMS = [re.compile(r"https://store\.steampowered\.com/wishlist/(profiles|id)/([^/?#\s]+)/?(?:[?#]\S*)?"),
          re.compile(r"https://steamcommunity\.com/(profiles|id)/([^/?#\s]+)/?(?:[?#]\S*)?")]
_URL_LINE = re.compile(r"""^(?P<indent>[ \t]*)url[ \t]*=[ \t]*(?:"[^"\n]*"|'[^'\n]*')(?P<rest>[ \t]*(?:#.*)?)$""", re.M)
_WISHLIST_HEADER = re.compile(r"^[ \t]*\[wishlist\][ \t]*(?:#.*)?$", re.M)
_TABLE_HEADER = re.compile(r"^[ \t]*\[", re.M)
ACCEPTED = ("  https://store.steampowered.com/wishlist/profiles/<17 位數字>/\n"
            "  https://store.steampowered.com/wishlist/id/<自訂名稱>/\n"
            "  https://steamcommunity.com/profiles/<17 位數字>\n"
            "  https://steamcommunity.com/id/<自訂名稱>")
PRIVATE = ("這個帳號的願望清單不公開：到 Steam「編輯個人檔案 → 隱私設定」，"
           "把「遊戲詳細資料」設為「公開」後再試一次。")
REFUSAL = "還沒設定願望清單：請先在視窗中執行 uv run sweetspot setup（或雙擊「更新資料.cmd」）"

ask: Callable[[str], str] = input


def stdin_is_terminal() -> bool:
    return sys.stdin is not None and sys.stdin.isatty()


def is_interactive(environ: Mapping[str, str] = os.environ) -> bool:
    """Someone can answer: stdin is a terminal and 背景更新.cmd did not say it is the background."""
    return environ.get(BACKGROUND) != "1" and stdin_is_terminal()


def parse_url(text: str) -> tuple[str, str] | None:
    """('profiles', '<17 digits>') or ('id', '<name>') for the accepted forms; None otherwise."""
    text = text.strip()
    for form in _FORMS:
        m = form.fullmatch(text)
        if m:
            kind, value = m.groups()
            if kind == "profiles" and not re.fullmatch(r"7656119\d{10}", value):   # a SteamID64 (014 T060)
                return None
            return kind, value
    return None


def _write_atomically(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".setup-tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _with_url(text: str, url: str) -> str | None:
    """The settings text with the url of [wishlist] set to `url`; every other line and comment stays (014 T066).

    The url line may be in any one-line TOML form (either quote, any spacing, a comment after it); it is looked for
    in the [wishlist] section only, added under its header when missing, and the section is added when there is
    none. None when the result would not read back as that url (the file is not valid TOML): write nothing then."""
    line = f'url = "{url}"'
    header = _WISHLIST_HEADER.search(text)
    if header is None:
        new = text + ("\n" if text and not text.endswith("\n") else "") + f"\n[wishlist]\n{line}\n"
    else:
        start = header.end()
        following = _TABLE_HEADER.search(text, start)
        m = _URL_LINE.search(text, start, following.start() if following else len(text))
        if m:
            new = text[:m.start()] + m.group("indent") + line + m.group("rest") + text[m.end():]
        else:
            new = text[:start] + "\n" + line + text[start:]
    try:
        return new if tomllib.loads(new).get("wishlist", {}).get("url") == url else None
    except tomllib.TOMLDecodeError:
        return None


def _current_url(path: Path) -> str:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8")).get("wishlist", {}).get("url", "") or "（空的）"
    except (OSError, tomllib.TOMLDecodeError):
        return f"（讀不懂 {path}）"


def _ask_account(ask: Callable[[str], str], say: Callable[..., None], community, wishlist: Callable[[str], list]):
    """The Profile of the wishlist the user pasted (asked again until it can be read), or an exit code."""
    while True:
        try:
            text = ask("請貼上你的 Steam 願望清單網址（或個人檔案網址），直接按 Enter 結束：")
        except EOFError:
            text = ""
        if not text.strip():
            say("沒有輸入網址；什麼都沒建立。")
            return EXIT_NOT_SET_UP
        parsed = parse_url(text)
        if parsed is None:
            say("網址格式不對。接受這幾種：")
            say(ACCEPTED)
            continue
        kind, value = parsed
        try:
            profile = community.by_vanity(value) if kind == "id" else community.by_steamid(value)
        except ValueError:
            say("網址格式不對：自訂名稱只能有英文字母、數字、底線與減號。")
            continue
        except ProfileNotFound:
            say("找不到這個帳號，請確認網址。")
            continue
        except SourceError as exc:
            say(f"暫時連不上 Steam（{exc}），請稍後再試；什麼都沒建立。")
            return EXIT_FAILED
        if profile.privacy != "public":
            say(PRIVATE)
            continue
        try:
            entries = wishlist(profile.steamid)
        except WishlistFetchError as exc:
            if exc.reason == "private":
                say(PRIVATE)
                continue
            if "HTTP 400" in str(exc):
                say("找不到這個帳號，請確認網址。")
                continue
            say(f"暫時讀不到願望清單（{exc.reason}），請稍後再試；什麼都沒建立。")
            return EXIT_FAILED
        if kind == "id":
            say(f"已記成這個帳號：{profile.name or '（沒有名稱）'}（{profile.steamid}）")
        if not entries:
            try:
                yes = ask("讀到 0 款：可能是清單是空的，或「遊戲詳細資料」不公開。要用這份空的清單嗎？(y/N) ")
            except EOFError:
                yes = ""
            if yes.strip().lower() not in ("y", "yes"):
                continue
        else:
            say(f"願望清單讀到 {len(entries)} 款。")
        return profile


def run(path: Path, *, change: bool, ask: Callable[[str], str], out: TextIO, interactive: bool, secrets: Secrets,
        community, wishlist: Callable[[str], list], today: date) -> int:
    path = Path(path)
    say = lambda line="": print(line, file=out, flush=True)          # noqa: E731
    if path.exists() and not change:
        say(f"已經設定過：{_current_url(path)}")
        say("要換願望清單請執行：uv run sweetspot setup --change")
        return EXIT_OK
    if not interactive:
        say("請在視窗中執行 sweetspot setup（雙擊「更新資料.cmd」也會詢問）；什麼都沒建立。")
        return EXIT_NOT_SET_UP
    if secrets.itad_api_key is None:
        say("還缺 ITAD_API_KEY：SweetSpot 需要 IsThereAnyDeal 的金鑰才能取得歷史價格。")
        say(f"  1. 到 {ITAD_KEY_PAGE} 登入後建立一個應用程式，複製它的 API key。")
        say("  2. 設成使用者層級的環境變數 ITAD_API_KEY：在 PowerShell 執行")
        say('       [Environment]::SetEnvironmentVariable("ITAD_API_KEY", "<你的金鑰>", "User")')
        say("     （或 Windows 設定 → 系統 → 關於 → 進階系統設定 → 環境變數）。金鑰不要寫進任何檔案。")
        say("  3. 設定後關掉這個視窗再重開，然後重新執行。")
        return EXIT_NOT_SET_UP
    try:
        profile = _ask_account(ask, say, community, wishlist)
    except KeyboardInterrupt:                           # Ctrl+C at a prompt or while asking Steam (014 T060)
        say("已取消；什麼都沒建立。")
        return EXIT_NOT_SET_UP
    if isinstance(profile, int):
        return profile
    url = WISHLIST_URL.format(profile.steamid)
    if path.exists():
        new = _with_url(path.read_text(encoding="utf-8"), url)
        if new is None:                                # not valid TOML: changing one line would not fix it
            say(f"讀不懂 {path}（不是有效的 TOML），沒有改它；請手動把 [wishlist] 的 url 改成：{url}")
            return EXIT_FAILED
        _write_atomically(path, new)
        say(f"已更新 {path} 的願望清單網址。")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        header = f"# 由 sweetspot setup 建立（{today.isoformat()}）；換願望清單：uv run sweetspot setup --change\n"
        _write_atomically(path, header + _with_url(DEFAULT_TOML, url))
        say(f"已建立 {path}。")
    say("下一步：")
    say("  雙擊「更新資料.cmd」：更新資料並產生報告（第一次會比較久）")
    say("  每天自動更新：uv run sweetspot schedule install")
    return EXIT_OK


def _sources(secrets: Secrets):
    from sweetspot import commands                     # late: commands imports cli, which imports this module
    from sweetspot.sources.http import RateLimitedClient
    from sweetspot.sources.steam_community import MIN_INTERVAL, SteamCommunity
    from sweetspot.sources.steam_webapi import SteamWebApi

    def client(name: str, interval: float) -> RateLimitedClient:
        return RateLimitedClient(name, min_interval=interval, transport=commands.TRANSPORT, sleep=commands.SLEEP,
                                 secrets=secrets.redaction_values())

    community = SteamCommunity(client("steam-community", MIN_INTERVAL))
    webapi = SteamWebApi(client("steam-webapi", commands.STEAM_WEBAPI_INTERVAL))
    return community, webapi.get_wishlist


def interactive_run(path: Path, *, change: bool, stdout: TextIO) -> int:
    secrets = load_secrets()
    community, wishlist = _sources(secrets)
    started, before = time.monotonic(), _stamp(path)
    code = run(path, change=change, ask=lambda prompt: ask(prompt), out=stdout, interactive=True, secrets=secrets,
               community=community, wishlist=wishlist, today=date.today())
    if code == EXIT_OK and _stamp(path) != before:
        log_written(path, "changed" if before else "created", time.monotonic() - started, secrets)
    return code


def _stamp(path: Path) -> int | None:
    path = Path(path)
    return path.stat().st_mtime_ns if path.exists() else None


def log_written(path: Path, what: str, seconds: float, secrets: Secrets) -> None:
    """014 T050 (contracts/cli.md §1 step 8): a settings file was written, so its data folder may hold the daily log.
    Only then: an exit that wrote nothing still creates nothing."""
    from sweetspot.config import ConfigError, load_config
    from sweetspot.logs import log_result, setup_logging

    try:
        config, _ = load_config(path)
    except ConfigError:
        return
    setup_logging(config.data_dir, secrets.redaction_values())
    log_result("setup", EXIT_OK, seconds, {"settings": what})


def main(args, stdout: TextIO, stderr: TextIO) -> int:
    """`sweetspot setup [--change]` (sweetspot.cli hands it over after the 016 old-name check)."""
    path = Path(args.config)
    if path.exists() and not args.change:
        return run(path, change=False, ask=ask, out=stdout, interactive=False, secrets=Secrets(), community=None,
                   wishlist=lambda s: [], today=date.today())
    if not is_interactive():
        print("請在視窗中執行 sweetspot setup（雙擊「更新資料.cmd」也會詢問）；什麼都沒建立。", file=stderr)
        return EXIT_NOT_SET_UP
    return interactive_run(path, change=args.change, stdout=stdout)


def ensure(path: Path, stdout: TextIO, stderr: TextIO) -> int:
    """Another command found no settings file: ask now if someone can answer, otherwise refuse with 5."""
    if not is_interactive():
        print(REFUSAL, file=stderr)
        return EXIT_NOT_SET_UP
    print("還沒設定願望清單，先設定一次：", file=stdout)
    return interactive_run(Path(path), change=False, stdout=stdout)
