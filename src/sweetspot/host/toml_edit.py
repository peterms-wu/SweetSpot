"""Edit one app's line in sweetspot.toml's [purchase_options] and nothing else (feature 015, research R3; spec FR-008).

The section holds only `<app> = "sub/N" | "bundle/N"` lines (feature 009), so the edit works line by line and keeps
every other byte. Before returning, tomllib checks that the new file parses to the old one with only this app
changed; a layout it cannot edit safely (the app written twice, outside the section, or not as a plain one-line
string) is refused so the user edits it by hand.
"""

import re
import tomllib
import unicodedata
from typing import Any

from sweetspot.config import OPTIONS_SECTION, _purchase_options

NAME_LIMIT = 80
_HEADER = re.compile(r"\s*\[\s*purchase_options\s*\]\s*(#.*)?")
_TABLE = re.compile(r"\s*\[")
_KEY = re.compile(r"""\s*(?:"(\d+)"|'(\d+)'|(\d+))\s*=""")
_PLAIN = re.compile(r"""\s*(?:"\d+"|'\d+'|\d+)\s*=\s*(?:"[^"\\]*"|'[^']*')\s*(?:#.*)?""")


class ConfigInvalid(Exception):
    """The file is not valid TOML (spec FR-017): nothing is written."""


class ConfigUnsafe(Exception):
    """This app's entry is written in a way the line editor will not touch; the message says why."""


def _parse(text: str) -> dict[str, Any]:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigInvalid(str(exc)) from None


def current_choice(text: str, app: int) -> tuple[str, int] | None:
    """The app's choice as the config loader reads it (None when it has none or the loader would ignore it)."""
    section = _parse(text).get(OPTIONS_SECTION, {})
    if not isinstance(section, dict):
        return None
    return _purchase_options(section)[0].get(app)


def comment_name(name: str | None) -> str | None:
    """A Steam/ITAD name made safe for a one-line comment: control and format characters become spaces."""
    if not name:
        return None
    cleaned = "".join(" " if unicodedata.category(ch).startswith("C") else ch for ch in name)
    cleaned = " ".join(cleaned.split())
    return cleaned[:NAME_LIMIT] or None


def entry_line(app: int, choice: tuple[str, int], *, name: str | None, today: str) -> str:
    safe = comment_name(name)
    comment = f"{safe}（{today} 從 Steam 頁面指定）" if safe else f"{today} 從 Steam 頁面指定"
    return f'{app} = "{choice[0]}/{choice[1]}"   # {comment}'


def _body(line: str) -> str:
    return line.rstrip("\r\n")


def _key_app(line: str) -> int | None:
    match = _KEY.match(line)
    if match is None:
        return None
    return int(next(g for g in match.groups() if g is not None))


def set_choice(text: str, app: int, choice: tuple[str, int] | None, *, name: str | None, today: str) -> str:
    """The file with this app's line added, replaced or (choice None) removed; everything else byte for byte."""
    raw = _parse(text)
    section = raw.get(OPTIONS_SECTION)
    if section is not None and not isinstance(section, dict):
        raise ConfigUnsafe("[purchase_options] 不是一般的區段")
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    headers = [i for i, ln in enumerate(lines) if _HEADER.fullmatch(_body(ln))]
    if section is not None and not headers:
        raise ConfigUnsafe("[purchase_options] 寫在區段以外（例如 purchase_options.<App> 或行內表格）")
    written = [k for k in (section or {}) if k.isdigit() and int(k) == app]

    if headers:
        start = headers[0] + 1
        end = next((i for i in range(start, len(lines)) if _TABLE.match(lines[i])), len(lines))
        mine = [i for i in range(start, end) if _key_app(lines[i]) == app]
        if len(mine) > 1 or len(written) > 1:
            raise ConfigUnsafe("這款遊戲在 [purchase_options] 中出現不只一次")
        if written and not mine:
            raise ConfigUnsafe("這款遊戲在 [purchase_options] 中的寫法不是單純的一行")
        if mine and not _PLAIN.fullmatch(_body(lines[mine[0]])):
            raise ConfigUnsafe("這款遊戲的值不是單行的字串")
        if choice is None:
            if not mine:
                return text
            del lines[mine[0]]
        elif mine:
            ending = lines[mine[0]][len(_body(lines[mine[0]])):]
            lines[mine[0]] = entry_line(app, choice, name=name, today=today) + ending
        else:
            entries = [i for i in range(start, end) if _key_app(lines[i]) is not None]
            content = [i for i in range(headers[0], end) if lines[i].strip()]
            after = entries[-1] if entries else content[-1]   # a trailing comment stays last
            new = entry_line(app, choice, name=name, today=today)
            if lines[after].endswith(("\n", "\r")):
                lines.insert(after + 1, new + nl)
            else:                                   # the file's last line, without a newline: keep it that way
                lines[after] += nl
                lines.insert(after + 1, new)
    else:
        if choice is None:
            return text
        new = entry_line(app, choice, name=name, today=today)
        tail = nl if text.endswith(("\n", "\r")) else ""
        lead = "" if not text or tail else nl
        lines = [text, f"{lead}{nl}[{OPTIONS_SECTION}]{nl}{new}{tail}"]
    out = "".join(lines)

    expected = {k: v for k, v in raw.items()}
    options = {k: v for k, v in (section or {}).items() if k not in written}
    if choice is not None:
        options[str(app)] = f"{choice[0]}/{choice[1]}"
    if options or section is not None:
        expected[OPTIONS_SECTION] = options
    try:
        if tomllib.loads(out) != expected:
            raise ConfigUnsafe("修改後的設定檔不只改了這款遊戲")
    except tomllib.TOMLDecodeError:
        raise ConfigUnsafe("修改後的設定檔無法解析") from None
    return out
